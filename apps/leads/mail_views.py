"""Leads → Email Inbox API (/api/leads/mail/).

    GET  mail/                 paginated inbox rows (status, parser, q, date filters)
    GET  mail/summary/         counts by status + mailbox sync health
    POST mail/fetch/           poll the mailbox now (manage)
    GET  mail/<id>/            one row with bodies and parsed fields
    POST mail/<id>/retry/      re-parse + create (UNPARSED / ERROR / IGNORED rows)
    POST mail/<id>/ignore/     mark not-a-lead
    POST mail/<id>/create/     create the lead by hand from the mail
    GET/POST mail/rules/       routing rules
    PATCH/DELETE mail/rules/<id>/
"""

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPerm
from apps.common.pagination import PaginatedAPIViewMixin

from . import mail_fetch
from .mail_intake import create_manually, process_email
from .mail_models import InboundLeadEmail, LeadMailRule, LeadMailSyncState
from .models import Lead
from .serializers import _LeadBaseSerializer

Status = InboundLeadEmail.Status


# --- serializers ---------------------------------------------------------

class LeadMailRuleSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True, default="")
    default_campus_name = serializers.CharField(
        source="default_campus.name", read_only=True, default="")

    class Meta:
        model = LeadMailRule
        fields = ["id", "name", "match_from", "match_subject", "parser",
                  "source", "source_name", "default_campus", "default_campus_name",
                  "priority", "is_active", "updated_at"]

    def validate(self, attrs):
        m_from = attrs.get("match_from", getattr(self.instance, "match_from", ""))
        m_subj = attrs.get("match_subject", getattr(self.instance, "match_subject", ""))
        if not (m_from or m_subj):
            raise serializers.ValidationError(
                "Give at least one of From contains / Subject contains.")
        return attrs


class InboundLeadEmailListSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    lead_name = serializers.CharField(source="lead.name", read_only=True, default="")
    lead_status = serializers.CharField(source="lead.status", read_only=True, default="")
    rule_name = serializers.CharField(source="rule.name", read_only=True, default="")
    name = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    campus_raw = serializers.SerializerMethodField()
    course_raw = serializers.SerializerMethodField()

    class Meta:
        model = InboundLeadEmail
        fields = ["id", "sent_at", "received_at", "from_address", "from_name",
                  "subject", "parser", "rule", "rule_name", "status", "status_label",
                  "error", "warnings", "lead", "lead_name", "lead_status",
                  "name", "phone", "email", "campus_raw", "course_raw",
                  "processed_at"]

    def _p(self, obj, key):
        return (obj.parsed or {}).get(key, "") or ""

    def get_name(self, obj): return self._p(obj, "name")
    def get_phone(self, obj): return self._p(obj, "phone")
    def get_email(self, obj): return self._p(obj, "email")
    def get_campus_raw(self, obj): return self._p(obj, "campus_raw")
    def get_course_raw(self, obj): return self._p(obj, "course_raw")


class InboundLeadEmailDetailSerializer(InboundLeadEmailListSerializer):
    processed_by_name = serializers.SerializerMethodField()

    class Meta(InboundLeadEmailListSerializer.Meta):
        fields = InboundLeadEmailListSerializer.Meta.fields + [
            "message_id", "text_body", "html_body", "parsed", "processed_by",
            "processed_by_name", "uid",
        ]

    def get_processed_by_name(self, obj):
        u = obj.processed_by
        if not u:
            return ""
        return getattr(u, "full_name", "") or u.get_username()


class ManualCreateSerializer(_LeadBaseSerializer):
    """Fields the staff member confirms on the Email Inbox page. Same
    campus/program rule as Add Lead; parents are not required because a
    portal or chat enquiry never carries them."""

    class Meta:
        model = Lead
        fields = ["name", "email", "phone", "alternative_phone",
                  "campus", "program", "source", "assign_to",
                  "remarks", "city", "state"]
        extra_kwargs = {
            "assign_to": {"required": False, "allow_null": True},
            "email": {"required": False, "allow_blank": True},
            "alternative_phone": {"required": False, "allow_blank": True},
            "remarks": {"required": False, "allow_blank": True},
            "city": {"required": False, "allow_blank": True},
            "state": {"required": False, "allow_blank": True},
        }


class SyncStateSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadMailSyncState
        fields = ["mailbox", "last_uid", "last_run_at", "last_success_at",
                  "last_error", "fetched_total"]


# --- views ---------------------------------------------------------------

class _ViewPerm(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "leads.mail.view"


class _ManagePerm(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "leads.mail.manage"


class InboundEmailListView(PaginatedAPIViewMixin, _ViewPerm):
    def get(self, request):
        qs = InboundLeadEmail.objects.select_related("lead", "rule")
        p = request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=[s for s in p["status"].split(",") if s])
        if p.get("parser"):
            qs = qs.filter(parser=p["parser"])
        if p.get("q"):
            q = p["q"].strip()
            qs = qs.filter(
                Q(subject__icontains=q) | Q(from_address__icontains=q)
                | Q(parsed__icontains=q) | Q(text_body__icontains=q))
        d = parse_date(p.get("date_from") or "")
        if d:
            qs = qs.filter(sent_at__date__gte=d)
        d = parse_date(p.get("date_to") or "")
        if d:
            qs = qs.filter(sent_at__date__lte=d)
        return self.paginate(qs, InboundLeadEmailListSerializer)


class InboundEmailSummaryView(_ViewPerm):
    def get(self, request):
        counts = dict(InboundLeadEmail.objects.values_list("status")
                      .annotate(n=Count("id")).values_list("status", "n"))
        today = timezone.localdate()
        today_counts = dict(
            InboundLeadEmail.objects.filter(sent_at__date=today)
            .values_list("status").annotate(n=Count("id"))
            .values_list("status", "n"))
        state = LeadMailSyncState.objects.order_by("-last_run_at").first()
        return Response({
            "configured": mail_fetch.is_configured(),
            "mailbox": state.mailbox if state else (
                getattr(mail_fetch.settings, "LEAD_MAIL_IMAP_USER", "") or ""),
            "sync": SyncStateSerializer(state).data if state else None,
            "counts": {s: counts.get(s, 0) for s, _ in Status.choices},
            "today": {s: today_counts.get(s, 0) for s, _ in Status.choices},
            "needs_attention": counts.get(Status.UNPARSED, 0) + counts.get(Status.ERROR, 0),
        })


class InboundEmailFetchNowView(_ManagePerm):
    def post(self, request):
        try:
            res = mail_fetch.fetch_new(limit=int(request.data.get("limit") or 100))
        except mail_fetch.MailConfigError as exc:
            return Response({"detail": str(exc)}, status=http.HTTP_503_SERVICE_UNAVAILABLE)
        if res.error:
            return Response({"detail": res.error, **res.as_dict()},
                            status=http.HTTP_502_BAD_GATEWAY)
        return Response(res.as_dict())


class InboundEmailDetailView(_ViewPerm):
    def get(self, request, pk):
        row = InboundLeadEmail.objects.select_related(
            "lead", "rule", "processed_by").filter(pk=pk).first()
        if row is None:
            return Response(status=http.HTTP_404_NOT_FOUND)
        return Response(InboundLeadEmailDetailSerializer(row).data)


class InboundEmailRetryView(_ManagePerm):
    def post(self, request, pk):
        row = InboundLeadEmail.objects.filter(pk=pk).first()
        if row is None:
            return Response(status=http.HTTP_404_NOT_FOUND)
        if row.lead_id:
            return Response({"detail": "This mail already has a lead."},
                            status=http.HTTP_400_BAD_REQUEST)
        process_email(row, force=True)
        return Response(InboundLeadEmailDetailSerializer(row).data)


class InboundEmailIgnoreView(_ManagePerm):
    def post(self, request, pk):
        row = InboundLeadEmail.objects.filter(pk=pk).first()
        if row is None:
            return Response(status=http.HTTP_404_NOT_FOUND)
        if row.lead_id:
            return Response({"detail": "This mail already has a lead."},
                            status=http.HTTP_400_BAD_REQUEST)
        row.status = Status.IGNORED
        row.processed_at = timezone.now()
        row.processed_by = request.user
        row.save(update_fields=["status", "processed_at", "processed_by"])
        return Response(InboundLeadEmailDetailSerializer(row).data)


class InboundEmailCreateLeadView(_ManagePerm):
    def post(self, request, pk):
        row = InboundLeadEmail.objects.filter(pk=pk).first()
        if row is None:
            return Response(status=http.HTTP_404_NOT_FOUND)
        if row.lead_id:
            return Response({"detail": "This mail already has a lead."},
                            status=http.HTTP_400_BAD_REQUEST)
        s = ManualCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        create_manually(row, data=dict(s.validated_data), user=request.user)
        return Response(InboundLeadEmailDetailSerializer(row).data,
                        status=http.HTTP_201_CREATED)


class LeadMailRuleListCreateView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]

    @property
    def required_perm(self):
        return "leads.mail.view" if self.request.method == "GET" else "leads.mail.rules"

    def get(self, request):
        qs = LeadMailRule.objects.select_related("source", "default_campus")
        return Response(LeadMailRuleSerializer(qs, many=True).data)

    def post(self, request):
        s = LeadMailRuleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=http.HTTP_201_CREATED)


class LeadMailRuleDetailView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "leads.mail.rules"

    def patch(self, request, pk):
        rule = LeadMailRule.objects.filter(pk=pk).first()
        if rule is None:
            return Response(status=http.HTTP_404_NOT_FOUND)
        s = LeadMailRuleSerializer(rule, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        deleted, _ = LeadMailRule.objects.filter(pk=pk).delete()
        if not deleted:
            return Response(status=http.HTTP_404_NOT_FOUND)
        return Response(status=http.HTTP_204_NO_CONTENT)
