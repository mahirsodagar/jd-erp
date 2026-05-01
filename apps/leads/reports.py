"""Manager dashboard / lead-funnel reports (Module F.6).

Read-side queries against the existing tables. Report endpoints return
JSON; CSV would be a small follow-up using `csv.writer` (same pattern as
the leaves report)."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.models import LeadSource, Program

from .models import Lead, LeadFollowup, LeadStatusHistory
from .outcomes import cold_disposition_to_lost_reason

User = get_user_model()


def _has_perm(user, key: str) -> bool:
    return (
        user.is_authenticated
        and (user.is_superuser
             or user.roles.filter(permissions__key=key).exists())
    )


class _ReportBase(APIView):
    permission_classes = [IsAuthenticated]

    def _check(self, request):
        if not _has_perm(request.user, "leads.report.view"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return None

    def _date_range(self, request):
        params = request.query_params
        start = parse_date(params.get("start_date") or "")
        end = parse_date(params.get("end_date") or "")
        if not start:
            start = (timezone.now() - timedelta(days=30)).date()
        if not end:
            end = timezone.now().date()
        return start, end


# --- Conversion funnel ------------------------------------------------

class ConversionFunnelView(_ReportBase):
    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        start, end = self._date_range(request)

        leads_qs = Lead.objects.filter(created_at__date__gte=start,
                                       created_at__date__lte=end)
        if v := request.query_params.get("source"):
            leads_qs = leads_qs.filter(source_id=v)
        if v := request.query_params.get("campus"):
            leads_qs = leads_qs.filter(campus_id=v)

        # Counts per status
        status_counts = dict(
            leads_qs.values("status").annotate(c=Count("id")).values_list("status", "c")
        )
        total = sum(status_counts.values()) or 0
        enrolled = status_counts.get(Lead.Status.ENROLLED, 0)
        funnel = {
            "total_leads": total,
            "active": status_counts.get(Lead.Status.ACTIVE, 0),
            "inactive": status_counts.get(Lead.Status.INACTIVE, 0),
            "application_submitted": status_counts.get(Lead.Status.APPLICATION_SUBMITTED, 0),
            "enrolled": enrolled,
            "conversion_rate": round((enrolled / total) * 100, 2) if total else 0.0,
        }

        # Per-source breakdown
        per_source = []
        rows = leads_qs.values("source__name").annotate(
            total=Count("id"),
            enrolled=Count("id", filter=Q(status=Lead.Status.ENROLLED)),
        ).order_by("-total")
        for r in rows:
            t, e = r["total"], r["enrolled"]
            per_source.append({
                "source": r["source__name"],
                "total": t, "enrolled": e,
                "rate": round((e / t) * 100, 2) if t else 0.0,
            })

        return Response({
            "start_date": str(start), "end_date": str(end),
            "funnel": funnel,
            "by_source": per_source,
        })


# --- Counsellor leaderboard -------------------------------------------

class CounsellorLeaderboardView(_ReportBase):
    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        start, end = self._date_range(request)

        # Per counsellor: leads handled, contacted (≥1 followup), enrolled.
        rows = []
        users = User.objects.filter(assigned_leads__created_at__date__gte=start,
                                    assigned_leads__created_at__date__lte=end).distinct()
        for u in users:
            handled = Lead.objects.filter(
                assign_to=u,
                created_at__date__gte=start, created_at__date__lte=end,
            )
            handled_n = handled.count()
            contacted_n = handled.filter(followups__isnull=False).distinct().count()
            enrolled_n = handled.filter(status=Lead.Status.ENROLLED).count()
            rows.append({
                "counsellor_id": u.id,
                "counsellor": u.username,
                "handled": handled_n,
                "contacted": contacted_n,
                "enrolled": enrolled_n,
                "conversion_rate": round((enrolled_n / handled_n) * 100, 2)
                                   if handled_n else 0.0,
            })
        rows.sort(key=lambda r: (r["enrolled"], r["handled"]), reverse=True)
        return Response({"start_date": str(start), "end_date": str(end),
                         "rows": rows})


# --- Time spent at each pipeline stage --------------------------------

class TimePerStageView(_ReportBase):
    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        start, end = self._date_range(request)

        # For each lead created in window, compute hours between
        # consecutive status changes by status pair.
        lead_ids = list(Lead.objects.filter(
            created_at__date__gte=start, created_at__date__lte=end,
        ).values_list("id", flat=True))

        durations: dict[str, list[int]] = {}
        for lead_id in lead_ids:
            history = list(LeadStatusHistory.objects.filter(lead_id=lead_id)
                           .order_by("changed_at"))
            for i in range(len(history) - 1):
                stage = history[i].new_status
                delta = (history[i + 1].changed_at - history[i].changed_at).total_seconds()
                durations.setdefault(stage, []).append(int(delta))

        out = {
            stage: {
                "samples": len(seconds),
                "avg_hours": round(sum(seconds) / len(seconds) / 3600, 2)
                              if seconds else 0,
                "max_hours": round(max(seconds) / 3600, 2) if seconds else 0,
            }
            for stage, seconds in durations.items()
        }
        return Response({"start_date": str(start), "end_date": str(end),
                         "stages": out})


# --- Lost-lead analysis (Cold dispositions) ---------------------------

class LostLeadAnalysisView(_ReportBase):
    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        start, end = self._date_range(request)

        cold = LeadFollowup.objects.filter(
            outcome_category=LeadFollowup.Outcome.COLD,
            created_at__date__gte=start,
            created_at__date__lte=end,
        ).values("outcome_disposition").annotate(c=Count("id"))

        # Roll up dispositions to high-level reasons
        reasons: dict[str, int] = {}
        per_disposition = []
        for r in cold:
            disp = r["outcome_disposition"] or "(none)"
            cnt = r["c"]
            per_disposition.append({"disposition": disp, "count": cnt})
            reason = cold_disposition_to_lost_reason(disp)
            reasons[reason] = reasons.get(reason, 0) + cnt

        return Response({
            "start_date": str(start), "end_date": str(end),
            "by_reason": [{"reason": k, "count": v} for k, v in
                          sorted(reasons.items(), key=lambda x: -x[1])],
            "by_disposition": sorted(per_disposition, key=lambda x: -x["count"]),
        })


# --- Course-wise enrollment + revenue forecast ------------------------

class CoursewiseRevenueView(_ReportBase):
    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        start, end = self._date_range(request)

        # Lead-side: count of enrolled leads per program.
        rows = Lead.objects.filter(
            created_at__date__gte=start, created_at__date__lte=end,
            status=Lead.Status.ENROLLED,
        ).values("program__name", "program__code", "program__category").annotate(
            enrolled_leads=Count("id"),
        ).order_by("-enrolled_leads")

        # Optional: cross with FeeReceipt for collected revenue.
        from apps.fees.models import FeeReceipt
        receipts = FeeReceipt.objects.filter(
            status=FeeReceipt.Status.ACTIVE,
            received_date__gte=start, received_date__lte=end,
        ).values("enrollment__program__code").annotate(
            total=Coalesce(Sum("amount"), Decimal("0")),
        )
        revenue_by_code = {r["enrollment__program__code"]: r["total"] for r in receipts}

        out = []
        for r in rows:
            code = r["program__code"]
            out.append({
                "program": r["program__name"],
                "code": code,
                "category": r["program__category"],
                "enrolled_leads": r["enrolled_leads"],
                "collected_revenue": str(revenue_by_code.get(code, Decimal("0"))),
            })
        return Response({"start_date": str(start), "end_date": str(end),
                         "rows": out})


# --- Duplicate frequency by phone -------------------------------------

class DuplicateFrequencyView(_ReportBase):
    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        rows = (
            Lead.objects.exclude(phone_normalized="")
            .values("phone_normalized")
            .annotate(c=Count("id"), max_occ=Avg("occurrence_number"))
            .filter(c__gt=1)
            .order_by("-c")[:200]
        )
        return Response({
            "rows": [{
                "phone_normalized": r["phone_normalized"],
                "count": r["c"],
                "max_occurrence": int(r["max_occ"] or 0),
            } for r in rows],
        })


# --- Summary roll-up (daily / weekly / monthly) ------------------------

class SummaryView(_ReportBase):
    """Single endpoint returning the headline numbers a manager wants
    to see in the morning email."""
    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp

        scope = request.query_params.get("scope", "daily")
        now = timezone.now()
        if scope == "weekly":
            start = now - timedelta(days=7)
        elif scope == "monthly":
            start = now - timedelta(days=30)
        else:
            start = now - timedelta(days=1)

        leads_qs = Lead.objects.filter(created_at__gte=start)
        total = leads_qs.count()
        enrolled = leads_qs.filter(status=Lead.Status.ENROLLED).count()
        followups = LeadFollowup.objects.filter(created_at__gte=start).count()
        overdue = LeadFollowup.objects.filter(
            outcome_category=LeadFollowup.Outcome.HOT,
            next_followup_date__lt=now.date(),
            lead__status=Lead.Status.ACTIVE,
        ).count()

        return Response({
            "scope": scope,
            "since": start.isoformat(),
            "leads_in": total,
            "enrolled": enrolled,
            "followups_logged": followups,
            "overdue_hot": overdue,
            "conversion_rate": round((enrolled / total) * 100, 2) if total else 0.0,
        })
