"""Manager dashboard / lead-funnel reports (Module F.6).

Read-side queries against the existing tables. Report endpoints return
JSON; CSV would be a small follow-up using `csv.writer` (same pattern as
the leaves report)."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Max, Q, Sum
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
    """Each report declares the key it needs. `leads.report.view` used to
    cover all seven, which put course-wise revenue and the counsellor
    leaderboard on the same checkbox as a duplicate-phone count."""

    permission_classes = [IsAuthenticated]
    required_perm = None

    def _check(self, request):
        if not _has_perm(request.user, self.required_perm):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            self.window = self._window(request)
        except BadPeriod as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return None

    def _window(self, request):
        """Resolve the page's single period control into
        [start, end) aware datetimes — see `report_window`."""
        return report_window(request.query_params)

    def _meta(self, window):
        start, end, period = window
        return {
            "period": period,
            "start": start.isoformat(), "end": end.isoformat(),
            # Inclusive calendar dates (India time) for display.
            "start_date": str(start.astimezone(REPORT_TZ).date()),
            "end_date": str((end - timedelta(microseconds=1))
                            .astimezone(REPORT_TZ).date()),
        }


# --- Period ----------------------------------------------------------
#
# Every section on the Lead Reports page follows one control: a preset
# (`period=`) or a custom `start_date` / `end_date`. A custom range wins
# when both dates are sent. Calendar boundaries ("Today", "This month",
# custom dates) are India time — the server clock is UTC.

REPORT_TZ = ZoneInfo("Asia/Kolkata")

PERIODS = {
    "today": "Today",
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
    "this_month": "This month",
    "90d": "Last 90 days",
}
DEFAULT_PERIOD = "30d"


class BadPeriod(Exception):
    pass


def _midnight(d):
    return datetime.combine(d, time.min, tzinfo=REPORT_TZ)


def report_window(params, *, now=None):
    """(start, end, period) with `end` exclusive."""
    now = now or timezone.now()
    start_d = parse_date(params.get("start_date") or "")
    end_d = parse_date(params.get("end_date") or "")
    if start_d or end_d:
        if not (start_d and end_d):
            raise BadPeriod("Pick both From and To dates.")
        if start_d > end_d:
            raise BadPeriod("From date must be on or before To date.")
        return _midnight(start_d), _midnight(end_d + timedelta(days=1)), "custom"

    period = params.get("period") or DEFAULT_PERIOD
    local_today = now.astimezone(REPORT_TZ).date()
    if period == "today":
        start = _midnight(local_today)
    elif period == "this_month":
        start = _midnight(local_today.replace(day=1))
    elif period in ("24h", "7d", "30d", "90d"):
        start = now - (timedelta(hours=24) if period == "24h"
                       else timedelta(days=int(period[:-1])))
    else:
        raise BadPeriod(f"Unknown period '{period}'.")
    return start, now, period


# --- Conversion funnel ------------------------------------------------

class ConversionFunnelView(_ReportBase):
    required_perm = "leads.report.funnel"

    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        start, end, _ = self.window

        leads_qs = Lead.objects.filter(created_at__gte=start,
                                       created_at__lt=end)
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
            "non_responsive": status_counts.get(Lead.Status.NON_RESPONSIVE, 0),
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
            **self._meta(self.window),
            "funnel": funnel,
            "by_source": per_source,
        })


# --- Counsellor leaderboard -------------------------------------------

class CounsellorLeaderboardView(_ReportBase):
    required_perm = "leads.report.leaderboard"

    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        start, end, _ = self.window

        # Per counsellor: leads handled, contacted (≥1 followup), enrolled.
        rows = []
        users = User.objects.filter(assigned_leads__created_at__gte=start,
                                    assigned_leads__created_at__lt=end).distinct()
        for u in users:
            handled = Lead.objects.filter(
                assign_to=u,
                created_at__gte=start, created_at__lt=end,
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
        return Response({**self._meta(self.window), "rows": rows})


# --- Time spent at each pipeline stage --------------------------------

class TimePerStageView(_ReportBase):
    required_perm = "leads.report.funnel"

    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        start, end, _ = self.window

        # For each lead created in window, compute hours between
        # consecutive status changes by status pair.
        lead_ids = list(Lead.objects.filter(
            created_at__gte=start, created_at__lt=end,
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
        return Response({**self._meta(self.window), "stages": out})


# --- Lost-lead analysis (Cold dispositions) ---------------------------

class LostLeadAnalysisView(_ReportBase):
    required_perm = "leads.report.quality"

    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        start, end, _ = self.window

        cold = LeadFollowup.objects.filter(
            outcome_category=LeadFollowup.Outcome.COLD,
            created_at__gte=start,
            created_at__lt=end,
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
            **self._meta(self.window),
            "by_reason": [{"reason": k, "count": v} for k, v in
                          sorted(reasons.items(), key=lambda x: -x[1])],
            "by_disposition": sorted(per_disposition, key=lambda x: -x["count"]),
        })


# --- Course-wise enrollment + revenue forecast ------------------------

class CoursewiseRevenueView(_ReportBase):
    required_perm = "leads.report.revenue"

    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        start, end, _ = self.window

        # Lead-side: count of enrolled leads per program.
        rows = Lead.objects.filter(
            created_at__gte=start, created_at__lt=end,
            status=Lead.Status.ENROLLED,
        ).values("program__name", "program__code", "program__category").annotate(
            enrolled_leads=Count("id"),
        ).order_by("-enrolled_leads")

        meta = self._meta(self.window)
        # Optional: cross with FeeReceipt for collected revenue.
        from apps.fees.models import FeeReceipt
        receipts = FeeReceipt.objects.filter(
            status=FeeReceipt.Status.ACTIVE,
            # Receipts carry a date only — use the window's calendar days.
            received_date__gte=meta["start_date"],
            received_date__lte=meta["end_date"],
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
        return Response({**meta, "rows": out})


# --- Duplicate frequency by phone -------------------------------------

class DuplicateFrequencyView(_ReportBase):
    required_perm = "leads.report.quality"

    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp
        start, end, _ = self.window
        # Phones that enquired more than once within the period.
        rows = (
            Lead.objects.exclude(phone_normalized="")
            .filter(created_at__gte=start, created_at__lt=end)
            .values("phone_normalized")
            .annotate(c=Count("id"), max_occ=Max("occurrence_number"))
            .filter(c__gt=1)
            .order_by("-c")[:200]
        )
        return Response({
            **self._meta(self.window),
            "rows": [{
                "phone_normalized": r["phone_normalized"],
                "count": r["c"],
                "max_occurrence": int(r["max_occ"] or 0),
            } for r in rows],
        })


# --- Summary KPIs -----------------------------------------------------

class SummaryView(_ReportBase):
    """Headline KPIs for the selected period (the old daily / weekly /
    monthly `scope` is now the page-wide `period`)."""

    required_perm = "leads.report.funnel"

    def get(self, request):
        if (resp := self._check(request)) is not None:
            return resp

        start, end, _ = self.window
        now = timezone.now()

        leads_qs = Lead.objects.filter(created_at__gte=start, created_at__lt=end)
        total = leads_qs.count()
        enrolled = leads_qs.filter(status=Lead.Status.ENROLLED).count()
        followups = LeadFollowup.objects.filter(
            created_at__gte=start, created_at__lt=end).count()
        # Point-in-time: what is overdue right now, whatever the period.
        overdue = LeadFollowup.objects.filter(
            outcome_category=LeadFollowup.Outcome.HOT,
            next_followup_date__lt=now.date(),
            lead__status=Lead.Status.ACTIVE,
        ).count()

        return Response({
            **self._meta(self.window),
            "leads_in": total,
            "enrolled": enrolled,
            "followups_logged": followups,
            "overdue_hot": overdue,
            "conversion_rate": round((enrolled / total) * 100, 2) if total else 0.0,
        })
