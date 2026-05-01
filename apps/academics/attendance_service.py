"""Attendance bulk-mark + freeze + absent-notification flows.

The roster of a slot = active enrollments in slot.batch as of the slot
date. We don't snapshot the roster on the slot itself — students who
get added/removed from a batch get reflected in the next attendance
view but past attendance rows persist.
"""

from django.db import transaction
from django.utils import timezone

from apps.admissions.models import Enrollment

from .models import Attendance, ScheduleSlot


def roster_for(slot: ScheduleSlot):
    """Active enrollments in this slot's batch."""
    return Enrollment.objects.filter(
        batch=slot.batch, status=Enrollment.Status.ACTIVE,
    ).select_related("student")


@transaction.atomic
def bulk_mark(*, slot: ScheduleSlot, marks: list[dict], marked_by) -> dict:
    """`marks` = [{student: <id>, status: <STATUS>, note: ""}, ...].

    Creates or updates Attendance rows. Returns
    {created: [...ids], updated: [...ids], skipped: [...]}.

    Caller is responsible for the freeze guard — service does not check
    it (so admins with the right perm can call this directly).
    """
    created, updated, skipped = [], [], []

    # Roster set so we don't accept random student ids.
    roster_ids = set(
        roster_for(slot).values_list("student_id", flat=True)
    )

    for m in marks:
        sid = m.get("student")
        status = m.get("status")
        note = m.get("note", "")
        if not sid or not status:
            skipped.append({"student": sid, "reason": "missing student/status"})
            continue
        if sid not in roster_ids:
            skipped.append({"student": sid, "reason": "not in batch roster"})
            continue
        if status not in Attendance.Status.values:
            skipped.append({"student": sid, "reason": f"invalid status: {status}"})
            continue

        obj, was_created = Attendance.objects.update_or_create(
            schedule_slot=slot, student_id=sid,
            defaults={"status": status, "note": note, "marked_by": marked_by},
        )
        (created if was_created else updated).append(obj.id)

    return {"created": created, "updated": updated, "skipped": skipped}


def freeze_attendance(*, slot: ScheduleSlot, by_user) -> ScheduleSlot:
    slot.attendance_frozen = True
    slot.attendance_frozen_at = timezone.now()
    slot.attendance_frozen_by = by_user
    slot.save(update_fields=["attendance_frozen", "attendance_frozen_at",
                              "attendance_frozen_by", "updated_at"])
    return slot


def unfreeze_attendance(*, slot: ScheduleSlot, by_user) -> ScheduleSlot:
    slot.attendance_frozen = False
    slot.attendance_frozen_at = None
    slot.attendance_frozen_by = None
    slot.save(update_fields=["attendance_frozen", "attendance_frozen_at",
                              "attendance_frozen_by", "updated_at"])
    return slot


def notify_absent_students(slot: ScheduleSlot) -> int:
    """Queue notifications for absentees (PDF: 'SMS to absent student +
    parent'). Uses the F.5 dispatch system; nothing is actually sent on
    PA free — rows are recorded for replay later."""
    from apps.notifications.services import queue_notification

    absent = Attendance.objects.filter(
        schedule_slot=slot, status=Attendance.Status.ABSENT,
    ).select_related("student")

    n = 0
    for a in absent:
        s = a.student
        ctx = {
            "name": s.student_name,
            "subject": slot.subject.name,
            "date": str(slot.date),
            "slot": slot.time_slot.label,
            "campus": slot.batch.campus.name,
            "batch": slot.batch.name,
        }
        if s.student_email:
            queue_notification(
                template_key="student_absent_email",
                recipient=s.student_email, context=ctx, related=a,
            )
            n += 1
        if s.father_email:
            queue_notification(
                template_key="parent_absent_email",
                recipient=s.father_email, context=ctx, related=a,
            )
            n += 1
        if s.mother_email and s.mother_email != s.father_email:
            queue_notification(
                template_key="parent_absent_email",
                recipient=s.mother_email, context=ctx, related=a,
            )
            n += 1
        if s.student_mobile:
            queue_notification(
                template_key="student_absent_wa",
                recipient=s.student_mobile, context=ctx, related=a,
            )
            n += 1
    return n


# --- Reports ----------------------------------------------------------

def batch_attendance_summary(*, batch, from_date=None, to_date=None) -> list[dict]:
    """For each active student in the batch, return their attendance
    counts + percentage across slots in the date range."""
    qs = Attendance.objects.filter(schedule_slot__batch=batch)
    slot_qs = ScheduleSlot.objects.filter(
        batch=batch, status=ScheduleSlot.Status.SCHEDULED,
    )
    if from_date:
        qs = qs.filter(schedule_slot__date__gte=from_date)
        slot_qs = slot_qs.filter(date__gte=from_date)
    if to_date:
        qs = qs.filter(schedule_slot__date__lte=to_date)
        slot_qs = slot_qs.filter(date__lte=to_date)

    total_slots = slot_qs.count()
    rows = []
    for enr in roster_for_batch(batch):
        s = enr.student
        per_status: dict[str, int] = {}
        for status_value, _ in Attendance.Status.choices:
            per_status[status_value] = qs.filter(
                student=s, status=status_value,
            ).count()
        present_like = per_status["PRESENT"] + per_status["LATE"] + per_status["ON_DUTY"]
        marked = sum(per_status.values())
        rows.append({
            "student_id": s.id,
            "application_form_id": s.application_form_id,
            "name": s.student_name,
            "total_slots": total_slots,
            "marked": marked,
            "unmarked": max(total_slots - marked, 0),
            **per_status,
            "present_pct": round((present_like / total_slots) * 100, 2)
                            if total_slots else 0.0,
        })
    return rows


def roster_for_batch(batch):
    return Enrollment.objects.filter(
        batch=batch, status=Enrollment.Status.ACTIVE,
    ).select_related("student").order_by("student__student_name")


def student_attendance_summary(*, student, from_date=None, to_date=None) -> dict:
    """One student's attendance across all their batches in the range."""
    qs = Attendance.objects.filter(student=student)
    slot_qs = ScheduleSlot.objects.filter(
        batch__in=student.enrollments.values_list("batch_id", flat=True),
        status=ScheduleSlot.Status.SCHEDULED,
    )
    if from_date:
        qs = qs.filter(schedule_slot__date__gte=from_date)
        slot_qs = slot_qs.filter(date__gte=from_date)
    if to_date:
        qs = qs.filter(schedule_slot__date__lte=to_date)
        slot_qs = slot_qs.filter(date__lte=to_date)

    total_slots = slot_qs.count()
    per_status = {}
    for status_value, _ in Attendance.Status.choices:
        per_status[status_value] = qs.filter(status=status_value).count()
    present_like = per_status["PRESENT"] + per_status["LATE"] + per_status["ON_DUTY"]
    marked = sum(per_status.values())
    return {
        "student_id": student.id,
        "name": student.student_name,
        "total_slots": total_slots,
        "marked": marked,
        "unmarked": max(total_slots - marked, 0),
        **per_status,
        "present_pct": round((present_like / total_slots) * 100, 2)
                        if total_slots else 0.0,
    }
