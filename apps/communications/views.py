"""Communication → Bulk Email endpoints.

Permission keys (apps/roles/seed.py):

    comms.bulk_email.view     History: my own campaigns
    comms.bulk_email.send     Compose + audience preview + test send
    comms.bulk_email.manage   everyone's campaigns; pause / resume /
                              cancel / retry any
    comms.template.view / .manage
    comms.suppression.view / .manage

Nothing here sends mail. A created campaign is queued (or scheduled)
and stays that way until the delivery worker exists.
"""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import has_perm

from .audience import build_audience
from .models import (
    EmailCampaign, EmailCampaignRecipient, EmailTemplate, Suppression,
)
from .serializers import (
    AudienceSerializer, CampaignCreateSerializer, CampaignListSerializer,
    CampaignRecipientSerializer, CampaignSerializer, EmailTemplateSerializer,
    SuppressionAddSerializer, SuppressionSerializer, TestSendSerializer,
)

SOURCE_LABELS = dict(EmailCampaign.Source.choices)


def _any(user, *keys) -> bool:
    return user.is_superuser or any(has_perm(user, k) for k in keys)


def _forbidden():
    return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)


def _display_name(user) -> str:
    return (user.full_name or user.username)


def _default_from() -> str:
    """The From the campaign will carry — the project's default SMTP
    mailbox (jdindia.com over Zoho since 2026-11-13). A bulk-specific
    sender domain is a delivery-side decision; the field is stored per
    campaign so it can change without touching history."""
    by_domain = getattr(settings, "EMAIL_SMTP_BY_DOMAIN", {}) or {}
    for cfg in by_domain.values():
        if cfg.get("from_email"):
            return cfg["from_email"]
    return getattr(settings, "EMAIL_HOST_USER", "") or getattr(settings, "DEFAULT_FROM_EMAIL", "")


def _campaign_qs():
    st = EmailCampaignRecipient.Status
    return EmailCampaign.objects.select_related("created_by").annotate(
        n_total=Count("recipients"),
        n_sent=Count("recipients", filter=Q(recipients__status=st.SENT)),
        n_failed=Count("recipients", filter=Q(recipients__status=st.FAILED)),
        n_pending=Count("recipients", filter=Q(recipients__status=st.PENDING)),
        n_unsubscribed=Count("recipients", filter=Q(recipients__status=st.UNSUBSCRIBED)),
        n_skipped=Count("recipients", filter=Q(recipients__status=st.SKIPPED)),
    )


def _get_campaign(pk) -> EmailCampaign:
    try:
        return _campaign_qs().get(pk=pk)
    except EmailCampaign.DoesNotExist as e:
        raise Http404 from e


def _can_see(user, c: EmailCampaign) -> bool:
    return _any(user, "comms.bulk_email.manage") or c.created_by_id == user.id


# --- Audience -------------------------------------------------------

class AudiencePreviewView(APIView):
    """POST {source, filters} → the people who would get the email.
    Part of composing, so it needs `send` (or `manage`)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _any(request.user, "comms.bulk_email.send", "comms.bulk_email.manage"):
            return _forbidden()
        s = AudienceSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        aud = build_audience(s.validated_data["source"], s.validated_data["filters"])
        return Response(aud.as_dict())


# --- Campaigns ------------------------------------------------------

class CampaignListCreateView(APIView):
    """GET: my campaigns, or everyone's with `manage` (`?mine=1` to
    narrow back). POST (multipart): create + queue a campaign."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        u = request.user
        if not _any(u, "comms.bulk_email.view", "comms.bulk_email.send", "comms.bulk_email.manage"):
            return _forbidden()
        qs = _campaign_qs()
        mine = request.query_params.get("mine") in ("1", "true")
        if mine or not _any(u, "comms.bulk_email.manage"):
            qs = qs.filter(created_by=u)
        if v := request.query_params.get("status"):
            qs = qs.filter(status=v)
        if v := request.query_params.get("source"):
            qs = qs.filter(source=v)
        return Response(CampaignListSerializer(qs, many=True).data)

    def post(self, request):
        u = request.user
        if not _any(u, "comms.bulk_email.send", "comms.bulk_email.manage"):
            return _forbidden()
        s = CampaignCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        p = s.validated_data["payload"]
        attachment = s.validated_data.get("attachment")

        aud = build_audience(p["audience"]["source"], p["audience"]["filters"])
        chosen = [
            r for r in aud.recipients
            if not r["suppressed"] and r["key"] not in p["excluded_keys"]
        ]
        if not chosen:
            return Response(
                {"detail": "No recipients selected."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        source = p["audience"]["source"]
        summary = " · ".join(
            [SOURCE_LABELS[source]] + [v for v in p["filter_labels"].values() if v],
        )[:300]

        with transaction.atomic():
            c = EmailCampaign.objects.create(
                subject=p["subject"],
                source=source,
                filters=p["audience"]["filters"],
                filter_labels=p["filter_labels"],
                audience_summary=summary,
                from_email=_default_from(),
                reply_to=p["reply_to"],
                body_html=p["body_html"],
                include_unsubscribe=p["include_unsubscribe"],
                template=p["template"],
                template_name=p["template"].name if p["template"] else "",
                status=(EmailCampaign.Status.SCHEDULED if p["scheduled_at"]
                        else EmailCampaign.Status.QUEUED),
                scheduled_at=p["scheduled_at"],
                created_by=u,
            )
            if attachment:
                c.attachment_name = attachment.name[:255]
                c.attachment_size = attachment.size
                c.attachment.save(attachment.name, attachment, save=False)
                c.save(update_fields=["attachment", "attachment_name", "attachment_size"])
            EmailCampaignRecipient.objects.bulk_create(
                [
                    EmailCampaignRecipient(
                        campaign=c, source_key=r["key"], name=r["name"][:200],
                        email=r["email"], context=r["context"][:200],
                    )
                    for r in chosen
                ],
                batch_size=1000,
            )
        return Response(CampaignSerializer(_get_campaign(c.pk)).data,
                        status=http.HTTP_201_CREATED)


class CampaignDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        c = _get_campaign(pk)
        if not _can_see(request.user, c):
            return _forbidden()
        return Response(CampaignSerializer(c).data)


class CampaignRecipientsView(APIView):
    """Every recipient row. `?status=` and `?q=` narrow it."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        c = _get_campaign(pk)
        if not _can_see(request.user, c):
            return _forbidden()
        qs = c.recipients.all()
        if v := request.query_params.get("status"):
            qs = qs.filter(status=v)
        if v := (request.query_params.get("q") or "").strip():
            qs = qs.filter(Q(name__icontains=v) | Q(email__icontains=v))
        return Response(CampaignRecipientSerializer(qs, many=True).data)


class CampaignActionView(APIView):
    """POST .../<pk>/<action>/ — pause, resume, cancel, retry-failed.
    The creator or a `manage` holder."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, action):
        c = _get_campaign(pk)
        if not _can_see(request.user, c):
            return _forbidden()
        S = EmailCampaign.Status
        R = EmailCampaignRecipient.Status
        now = timezone.now()

        if action == "pause":
            if c.status not in EmailCampaign.LIVE_STATUSES:
                return self._bad("Only a queued, scheduled or sending campaign can be paused.")
            c.status = S.PAUSED
            c.save(update_fields=["status"])

        elif action == "resume":
            if c.status != S.PAUSED:
                return self._bad("Only a paused campaign can be resumed.")
            if c.scheduled_at and c.scheduled_at > now and not c.started_at:
                c.status = S.SCHEDULED
            else:
                c.status = S.QUEUED
            c.save(update_fields=["status"])

        elif action == "cancel":
            if c.status in EmailCampaign.TERMINAL_STATUSES:
                return self._bad("This campaign has already finished.")
            with transaction.atomic():
                c.recipients.filter(status=R.PENDING).update(
                    status=R.SKIPPED, error="Campaign cancelled",
                )
                c.status = S.CANCELLED
                c.completed_at = now
                c.save(update_fields=["status", "completed_at"])

        elif action == "retry-failed":
            if c.status == S.CANCELLED:
                return self._bad("A cancelled campaign cannot be retried.")
            n = c.recipients.filter(status=R.FAILED).update(
                status=R.PENDING, error="", sent_at=None,
            )
            if not n:
                return self._bad("Nothing to retry — no failed recipients.")
            if c.status == S.COMPLETED:
                c.status = S.QUEUED
                c.completed_at = None
                c.save(update_fields=["status", "completed_at"])

        else:
            raise Http404

        return Response(CampaignSerializer(_get_campaign(c.pk)).data)

    @staticmethod
    def _bad(msg):
        return Response({"detail": msg}, status=http.HTTP_400_BAD_REQUEST)


class TestSendView(APIView):
    """Validates the request; delivery is not wired yet, so this always
    says so rather than pretending a mail went out."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _any(request.user, "comms.bulk_email.send", "comms.bulk_email.manage"):
            return _forbidden()
        s = TestSendSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(
            {"detail": "Email delivery is not connected yet — the test was not sent."},
            status=http.HTTP_503_SERVICE_UNAVAILABLE,
        )


# --- Templates ------------------------------------------------------

def _can_manage_templates(user) -> bool:
    return _any(user, "comms.template.manage", "comms.bulk_email.manage")


def _can_view_templates(user) -> bool:
    return _can_manage_templates(user) or _any(
        user, "comms.template.view", "comms.bulk_email.view", "comms.bulk_email.send",
    )


class TemplateListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view_templates(request.user):
            return _forbidden()
        qs = EmailTemplate.objects.select_related("created_by", "updated_by")
        return Response(EmailTemplateSerializer(qs, many=True).data)

    def post(self, request):
        if not _can_manage_templates(request.user):
            return _forbidden()
        s = EmailTemplateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        t = s.save(created_by=request.user, updated_by=request.user)
        return Response(EmailTemplateSerializer(t).data, status=http.HTTP_201_CREATED)


class TemplateDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        try:
            return EmailTemplate.objects.get(pk=pk)
        except EmailTemplate.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        if not _can_view_templates(request.user):
            return _forbidden()
        return Response(EmailTemplateSerializer(self._get(pk)).data)

    def patch(self, request, pk):
        if not _can_manage_templates(request.user):
            return _forbidden()
        t = self._get(pk)
        s = EmailTemplateSerializer(t, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        t = s.save(updated_by=request.user)
        return Response(EmailTemplateSerializer(t).data)

    put = patch

    def delete(self, request, pk):
        if not _can_manage_templates(request.user):
            return _forbidden()
        self._get(pk).delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- Suppression ----------------------------------------------------

def _can_manage_suppression(user) -> bool:
    return _any(user, "comms.suppression.manage", "comms.bulk_email.manage")


def _can_view_suppression(user) -> bool:
    return _can_manage_suppression(user) or _any(
        user, "comms.suppression.view", "comms.bulk_email.view", "comms.bulk_email.send",
    )


class SuppressionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view_suppression(request.user):
            return _forbidden()
        qs = Suppression.objects.all()
        if v := request.query_params.get("reason"):
            qs = qs.filter(reason=v)
        if v := (request.query_params.get("q") or "").strip():
            qs = qs.filter(Q(email__icontains=v) | Q(source__icontains=v))
        return Response(SuppressionSerializer(qs, many=True).data)

    def post(self, request):
        """Bulk add by hand: `{"emails": [...]}`. Invalid and already
        listed addresses are silently skipped; 400 if nothing was new."""
        if not _can_manage_suppression(request.user):
            return _forbidden()
        s = SuppressionAddSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError

        existing = set(Suppression.objects.values_list("email", flat=True))
        added = []
        for raw in s.validated_data["emails"]:
            email = Suppression.normalise(raw)
            if not email or email in existing:
                continue
            try:
                validate_email(email)
            except ValidationError:
                continue
            existing.add(email)
            added.append(Suppression(
                email=email, reason=Suppression.Reason.MANUAL,
                source=f"Added by {_display_name(request.user)}",
                added_by=request.user,
            ))
        if not added:
            return Response(
                {"detail": "No new valid email addresses to add."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        rows = Suppression.objects.bulk_create(added)
        return Response(SuppressionSerializer(rows, many=True).data,
                        status=http.HTTP_201_CREATED)


class SuppressionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        if not _can_manage_suppression(request.user):
            return _forbidden()
        deleted, _ = Suppression.objects.filter(pk=pk).delete()
        if not deleted:
            raise Http404
        return Response(status=http.HTTP_204_NO_CONTENT)
