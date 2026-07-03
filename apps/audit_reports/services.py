"""Compliance calculations + cross-module aggregations.

These functions read from G.1 (ScheduleSlot), G.2 (Attendance), G.3
(Marks) and the new audit_reports tables to give auditors / management
a single read-side surface."""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone


# --- Faculty daily computed hours (class + leave) -------------------

# Nominal working hours in a day, used to express a leave day-fraction
# (0.5 / 1.0) as hours. Adjust to the institute's working day if needed.
WORKDAY_HOURS = Decimal("8")


def faculty_daily_computed(*, faculty, start: date, end: date) -> dict:
    """Per-day scheduled class hours + leave hours for one faculty.

    Returns {"YYYY-MM-DD": {"class_hours": float, "leave_hours": float}}
    for days that have either. Class hours = sum of (end-start) over the
    faculty's non-cancelled ScheduleSlots. Leave hours = approved-leave
    day-fraction × WORKDAY_HOURS (Sundays skipped; holidays not netted)."""
    from datetime import datetime

    from apps.academics.models import ScheduleSlot
    from apps.leaves.models import LeaveApplication

    out: dict = {}

    def bucket(d):
        return out.setdefault(
            d.isoformat(), {"class_hours": 0.0, "leave_hours": 0.0})

    slots = (
        ScheduleSlot.objects.filter(
            instructor=faculty, date__gte=start, date__lte=end,
        )
        .exclude(status=ScheduleSlot.Status.CANCELLED)
        .select_related("time_slot")
    )
    for s in slots:
        ts = s.time_slot
        if ts is None:
            continue
        hours = (
            datetime.combine(s.date, ts.end_time)
            - datetime.combine(s.date, ts.start_time)
        ).total_seconds() / 3600
        bucket(s.date)["class_hours"] += hours

    leaves = LeaveApplication.objects.filter(
        employee=faculty, status=LeaveApplication.Status.APPROVED,
        from_date__lte=end, to_date__gte=start,
    )
    for la in leaves:
        single = la.from_date == la.to_date
        day = max(la.from_date, start)
        last = min(la.to_date, end)
        while day <= last:
            if day.weekday() != 6:  # skip Sundays
                if single and la.from_session in (1, 3, 4):
                    frac = Decimal("0.5")
                else:
                    frac = Decimal("1.0")
                bucket(day)["leave_hours"] += float(frac * WORKDAY_HOURS)
            day += timedelta(days=1)

    return out


# --- Live faculty tracking -----------------------------------------

def live_faculty_tracking(*, on_date: date | None = None) -> list[dict]:
    """For every active faculty, today's load + attendance status +
    daily-report submission flag."""
    from apps.academics.models import Attendance, ScheduleSlot
    from apps.employees.models import Employee
    from .models import FacultyDailyReport

    on_date = on_date or timezone.now().date()
    faculty_qs = Employee.objects.filter(
        status=0, is_deleted=False,  # 0 = ACTIVE per Employee.Status
    ).order_by("emp_code")

    rows = []
    for emp in faculty_qs:
        slots = list(
            ScheduleSlot.objects.filter(
                instructor=emp, date=on_date,
                status=ScheduleSlot.Status.SCHEDULED,
            ).select_related("subject", "batch")
        )
        attendance_marked = sum(
            1 for s in slots
            if Attendance.objects.filter(schedule_slot=s).exists()
        )
        attendance_frozen = sum(1 for s in slots if s.attendance_frozen)
        rows.append({
            "employee_id": emp.id,
            "emp_code": emp.emp_code,
            "name": emp.full_name,
            "campus": emp.campus.name if emp.campus_id else None,
            "slots_today": len(slots),
            "attendance_marked": attendance_marked,
            "attendance_frozen": attendance_frozen,
            "daily_report_submitted": FacultyDailyReport.objects.filter(
                faculty=emp, date=on_date,
            ).exists(),
        })
    return rows


# --- Timetable adherence -------------------------------------------

def timetable_adherence(*, start: date, end: date) -> dict:
    """For the given window: how many SCHEDULED slots had attendance
    marked (proxy for whether the class actually happened)."""
    from apps.academics.models import Attendance, ScheduleSlot

    slots_qs = ScheduleSlot.objects.filter(
        date__gte=start, date__lte=end,
        status=ScheduleSlot.Status.SCHEDULED,
    )
    total = slots_qs.count()
    marked = sum(
        1 for s in slots_qs
        if Attendance.objects.filter(schedule_slot=s).exists()
    )
    frozen = slots_qs.filter(attendance_frozen=True).count()
    cancelled = ScheduleSlot.objects.filter(
        date__gte=start, date__lte=end,
        status=ScheduleSlot.Status.CANCELLED,
    ).count()
    return {
        "start": str(start), "end": str(end),
        "total_scheduled": total,
        "attendance_marked": marked,
        "attendance_frozen": frozen,
        "cancelled": cancelled,
        "marked_pct": round((marked / total) * 100, 2) if total else 0.0,
        "frozen_pct": round((frozen / total) * 100, 2) if total else 0.0,
    }


# --- Batch progression ---------------------------------------------

def batch_progression(*, batch) -> dict:
    """Headline numbers for a single batch: enrollment count, attendance
    avg, marks publication rate, certification status."""
    from apps.academics.attendance_service import (
        batch_attendance_summary, roster_for_batch,
    )
    from apps.academics.models import (
        Certificate, MarksEntry, ScheduleSlot,
    )
    from apps.admissions.models import Enrollment

    enrolled = Enrollment.objects.filter(batch=batch)
    active = enrolled.filter(status=Enrollment.Status.ACTIVE).count()
    alumni = enrolled.filter(status=Enrollment.Status.ALUMNI).count()
    dropped = enrolled.filter(status=Enrollment.Status.DROPPED).count()

    summary = batch_attendance_summary(batch=batch)
    avg_pct = (sum(r["present_pct"] for r in summary) / len(summary)
               if summary else 0)

    marks_qs = MarksEntry.objects.filter(batch=batch)
    total_marks = marks_qs.count()
    published = marks_qs.filter(published=True).count()

    completion_certs = Certificate.objects.filter(
        enrollment__batch=batch, type="COMPLETION",
        status="ISSUED",
    ).count()

    schedule_total = ScheduleSlot.objects.filter(batch=batch).count()
    schedule_completed = ScheduleSlot.objects.filter(
        batch=batch, status=ScheduleSlot.Status.COMPLETED,
    ).count()

    return {
        "batch_id": batch.id,
        "batch_name": batch.name,
        "campus": batch.campus.name,
        "program": batch.program.name,
        "enrollments": {
            "active": active, "alumni": alumni, "dropped": dropped,
            "total": enrolled.count(),
        },
        "attendance": {
            "students_with_marks": len(summary),
            "avg_present_pct": round(avg_pct, 2),
        },
        "marks": {
            "total_entries": total_marks,
            "published": published,
            "publish_pct": round((published / total_marks) * 100, 2)
                            if total_marks else 0.0,
        },
        "schedule": {
            "total": schedule_total, "completed": schedule_completed,
        },
        "completion_certificates_issued": completion_certs,
    }


# --- Faculty self-appraisal aggregate ------------------------------

def feedback_summary_for_instructor(*, instructor, year: int | None = None) -> dict:
    """Aggregate ratings + counts of feedback rows for an instructor."""
    from .models import StudentFeedback

    qs = StudentFeedback.objects.filter(instructor=instructor)
    if year:
        qs = qs.filter(created_at__year=year)
    total = qs.count()
    aggregate = qs.aggregate(
        overall=Avg("rating_overall"),
        clarity=Avg("rating_clarity"),
        engagement=Avg("rating_engagement"),
        responsiveness=Avg("rating_responsiveness"),
    )
    by_type = dict(qs.values("type").annotate(c=Count("id"))
                   .values_list("type", "c"))
    return {
        "instructor_id": instructor.id,
        "name": instructor.full_name,
        "feedback_count": total,
        "by_type": by_type,
        "avg_ratings": {
            "overall": round(aggregate["overall"], 2) if aggregate["overall"] else None,
            "clarity": round(aggregate["clarity"], 2) if aggregate["clarity"] else None,
            "engagement": round(aggregate["engagement"], 2) if aggregate["engagement"] else None,
            "responsiveness": round(aggregate["responsiveness"], 2) if aggregate["responsiveness"] else None,
        },
    }


# --- Consolidated monthly --------------------------------------------

def consolidated_monthly(*, year: int, month: int) -> dict:
    """Single-shot dashboard summary: cross-module headlines for a
    given month."""
    from apps.academics.models import (
        Attendance, Certificate, MarksEntry, ScheduleSlot,
    )
    from apps.admissions.models import Enrollment
    from apps.fees.models import FeeReceipt
    from apps.leads.models import Lead
    from .models import (
        ComplianceFlag, FacultyDailyReport, StudentFeedback,
    )

    if month < 1 or month > 12:
        raise ValueError("month must be 1..12")
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    slots_qs = ScheduleSlot.objects.filter(date__gte=start, date__lte=end)
    return {
        "scope": f"{year}-{month:02d}",
        "start": str(start), "end": str(end),

        # Leads / admissions
        "leads": {
            "in": Lead.objects.filter(
                created_at__date__gte=start, created_at__date__lte=end,
            ).count(),
            "enrolled": Lead.objects.filter(
                created_at__date__gte=start, created_at__date__lte=end,
                status=Lead.Status.ENROLLED,
            ).count(),
        },
        "enrollments": {
            "active": Enrollment.objects.filter(
                status=Enrollment.Status.ACTIVE,
                created_on__date__gte=start, created_on__date__lte=end,
            ).count(),
        },

        # Fees
        "fees": {
            "receipts": FeeReceipt.objects.filter(
                received_date__gte=start, received_date__lte=end,
                status=FeeReceipt.Status.ACTIVE,
            ).count(),
            "amount": str(
                FeeReceipt.objects.filter(
                    received_date__gte=start, received_date__lte=end,
                    status=FeeReceipt.Status.ACTIVE,
                ).aggregate(s=Sum("amount"))["s"] or Decimal("0")
            ),
        },

        # Academics
        "academics": {
            "scheduled_slots": slots_qs.filter(
                status=ScheduleSlot.Status.SCHEDULED,
            ).count(),
            "cancelled_slots": slots_qs.filter(
                status=ScheduleSlot.Status.CANCELLED,
            ).count(),
            "attendance_rows": Attendance.objects.filter(
                schedule_slot__date__gte=start,
                schedule_slot__date__lte=end,
            ).count(),
            "marks_published": MarksEntry.objects.filter(
                published=True,
                published_at__date__gte=start,
                published_at__date__lte=end,
            ).count(),
            "certificates_issued": Certificate.objects.filter(
                status="ISSUED",
                issued_at__date__gte=start,
                issued_at__date__lte=end,
            ).count(),
        },

        # Audit signals
        "audit": {
            "faculty_daily_reports": FacultyDailyReport.objects.filter(
                date__gte=start, date__lte=end,
            ).count(),
            "student_feedback": StudentFeedback.objects.filter(
                created_at__date__gte=start, created_at__date__lte=end,
            ).count(),
            "compliance_open": ComplianceFlag.objects.filter(
                resolved_at__isnull=True,
                created_at__date__gte=start, created_at__date__lte=end,
            ).count(),
            "compliance_resolved": ComplianceFlag.objects.filter(
                resolved_at__isnull=False,
                resolved_at__date__gte=start, resolved_at__date__lte=end,
            ).count(),
        },

        "timetable_adherence": timetable_adherence(start=start, end=end),
    }
