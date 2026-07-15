"""Attendance Report module — read-only reporting on top of ScheduleSlot
+ Attendance. Powers the five-tab Attendance Report page (Activity,
Batch-Wise, Student-Wise, Remarks, Instructor Module Log) plus the two
drill-down views (per-slot roster reuses the existing roster endpoint;
per-module date-grid lives here).

Percentage convention matches the rest of the app: "present-like" =
PRESENT + LATE + ON_DUTY, taken over the rows that were actually marked.
"""

from datetime import date

from django.db.models import Count, Q

from apps.admissions.models import Enrollment
from apps.master.models import Batch

from .models import Attendance, ScheduleSlot

PRESENT_LIKE = ("PRESENT", "LATE", "ON_DUTY")
SHORTAGE_THRESHOLD = 75.0


def _pct(present: int, total: int) -> float:
    return round(present / total * 100, 2) if total else 0.0


def _slot_qs(*, from_date=None, to_date=None, academic_year=None,
             campus=None, program=None, batch=None, instructor=None,
             subject=None):
    """Scheduled slots narrowed by the common report filters. Academic
    year / campus / program are resolved through the slot's batch."""
    qs = ScheduleSlot.objects.filter(status=ScheduleSlot.Status.SCHEDULED)
    if from_date:
        qs = qs.filter(date__gte=from_date)
    if to_date:
        qs = qs.filter(date__lte=to_date)
    if batch:
        qs = qs.filter(batch_id=batch)
    if program:
        qs = qs.filter(batch__program_id=program)
    if campus:
        qs = qs.filter(batch__campus_id=campus)
    if academic_year:
        qs = qs.filter(batch__academic_year_id=academic_year)
    if instructor:
        qs = qs.filter(instructor_id=instructor)
    if subject:
        qs = qs.filter(subject_id=subject)
    return qs


def _roster(batch, semester=None):
    qs = (Enrollment.objects
          .filter(batch=batch, status=Enrollment.Status.ACTIVE)
          .select_related("student"))
    if semester:
        qs = qs.filter(semester_id=semester)
    return qs.order_by("student__student_name")


# === Tab 1 / Tab 5 — Activity Report & Instructor Module Log =========

def activity_report(**filters) -> list[dict]:
    """One row per scheduled slot with its attendance status + %.

    Accepts the `_slot_qs` filters; `instructor=<employee_id>` produces
    the Instructor Module Log (same shape)."""
    qs = (_slot_qs(**filters)
          .select_related("batch", "batch__campus", "batch__program",
                          "subject", "instructor", "time_slot", "created_by")
          .annotate(
              marked=Count("attendance_entries"),
              present=Count("attendance_entries",
                            filter=Q(attendance_entries__status__in=PRESENT_LIKE)),
          )
          .order_by("date", "time_slot__start_time"))
    rows = []
    for s in qs:
        rows.append({
            "slot_id": s.id,
            "date": str(s.date),
            "time_slot": s.time_slot.label,
            "subject": f"{s.subject.name} ({s.subject.code})",
            "instructor": s.instructor.full_name,
            "updated": s.marked > 0,
            "present": s.present,
            "marked": s.marked,
            "percentage": _pct(s.present, s.marked),
            "updated_on": s.updated_at.isoformat() if s.marked else None,
            "batch": s.batch.short_name or s.batch.name,
            "campus": s.batch.campus.name,
            "program": s.batch.program.name,
            "entry_date": str(s.created_at.date()) if s.created_at else None,
            "entry_user": (s.created_by.username if s.created_by_id else ""),
            "remarks": s.notes,
            "frozen": s.attendance_frozen,
        })
    return rows


# === Tab 4 — Remarks Report ==========================================

def remarks_report(**filters) -> list[dict]:
    """Slot-level remarks for a batch (optionally one subject)."""
    qs = (_slot_qs(**filters)
          .select_related("batch", "subject", "instructor", "time_slot")
          .annotate(marked=Count("attendance_entries"))
          .order_by("date", "time_slot__start_time"))
    return [
        {
            "slot_id": s.id,
            "date": str(s.date),
            "time_slot": s.time_slot.label,
            "subject": f"{s.subject.name} ({s.subject.code})",
            "remarks": s.notes,
            "instructor": s.instructor.full_name,
            "batch": s.batch.short_name or s.batch.name,
            "updated": s.marked > 0,
        }
        for s in qs
    ]


# === Tab 2 — Batch Wise ==============================================

def batch_wise_report(*, batch, from_date=None, to_date=None,
                      semester=None) -> dict:
    """Student × subject cross-tab for one batch, plus a per-module
    summary and a shortage flag (<75%)."""
    slots = _slot_qs(batch=batch.id, from_date=from_date, to_date=to_date)
    subjects = list(
        {s.subject_id: {"id": s.subject_id,
                        "code": s.subject.code,
                        "name": s.subject.name}
         for s in slots.select_related("subject")}.values()
    )
    subjects.sort(key=lambda x: x["code"])
    roster = list(_roster(batch, semester))
    student_ids = [e.student_id for e in roster]

    # (student, subject) -> {present, total}
    agg = (Attendance.objects
           .filter(schedule_slot__in=slots, student_id__in=student_ids)
           .values("student_id", "schedule_slot__subject_id")
           .annotate(
               present=Count("id", filter=Q(status__in=PRESENT_LIKE)),
               total=Count("id"),
           ))
    cell = {}
    for a in agg:
        cell[(a["student_id"], a["schedule_slot__subject_id"])] = (
            a["present"], a["total"],
        )

    rows = []
    module_totals = {s["id"]: [0, 0] for s in subjects}
    for e in roster:
        s = e.student
        cells = {}
        tot_present = tot_marked = 0
        for subj in subjects:
            present, total = cell.get((s.id, subj["id"]), (0, 0))
            cells[subj["id"]] = {
                "present": present, "total": total,
                "pct": _pct(present, total),
            }
            tot_present += present
            tot_marked += total
            module_totals[subj["id"]][0] += present
            module_totals[subj["id"]][1] += total
        overall = _pct(tot_present, tot_marked)
        rows.append({
            "student_id": s.id,
            "application_form_id": s.application_form_id,
            "name": s.student_name,
            "cells": cells,
            "total_present": tot_present,
            "total_marked": tot_marked,
            "overall_pct": overall,
            "shortage": tot_marked > 0 and overall < SHORTAGE_THRESHOLD,
        })

    module_summary = [
        {
            "subject_id": subj["id"],
            "code": subj["code"],
            "name": subj["name"],
            "present": module_totals[subj["id"]][0],
            "total": module_totals[subj["id"]][1],
            "pct": _pct(*module_totals[subj["id"]]),
        }
        for subj in subjects
    ]

    return {
        "batch_id": batch.id,
        "batch_name": batch.name,
        "from": str(from_date) if from_date else None,
        "to": str(to_date) if to_date else None,
        "semester": semester,
        "subjects": subjects,
        "rows": rows,
        "module_summary": module_summary,
    }


# === Tab 3 — Student Wise ============================================

def student_wise_report(*, student, from_date=None, to_date=None) -> dict:
    """Per-subject attendance for one student, with absent/late dates."""
    qs = (Attendance.objects
          .filter(student=student)
          .select_related("schedule_slot", "schedule_slot__subject"))
    if from_date:
        qs = qs.filter(schedule_slot__date__gte=from_date)
    if to_date:
        qs = qs.filter(schedule_slot__date__lte=to_date)

    by_subject = {}
    for a in qs:
        subj = a.schedule_slot.subject
        row = by_subject.setdefault(subj.id, {
            "subject_id": subj.id,
            "code": subj.code,
            "name": subj.name,
            "present": 0,
            "total": 0,
            "absent_dates": [],
            "late_dates": [],
        })
        row["total"] += 1
        if a.status in PRESENT_LIKE:
            row["present"] += 1
        d = str(a.schedule_slot.date)
        if a.status == Attendance.Status.ABSENT:
            row["absent_dates"].append(d)
        elif a.status == Attendance.Status.LATE:
            row["late_dates"].append(d)

    subjects = []
    tot_present = tot_total = 0
    for row in sorted(by_subject.values(), key=lambda x: x["code"]):
        row["pct"] = _pct(row["present"], row["total"])
        row["absent_dates"].sort()
        row["late_dates"].sort()
        tot_present += row["present"]
        tot_total += row["total"]
        subjects.append(row)

    return {
        "student_id": student.id,
        "name": student.student_name,
        "application_form_id": student.application_form_id,
        "subjects": subjects,
        "totals": {
            "present": tot_present,
            "total": tot_total,
            "pct": _pct(tot_present, tot_total),
        },
    }


# === Full Report modal — per-module date grid ========================

def module_grid(*, subject_id, batch, from_date=None, to_date=None) -> dict:
    """Students (rows) × slots/dates (columns) status grid for one
    subject in one batch."""
    slots = list(
        _slot_qs(batch=batch.id, subject=subject_id,
                 from_date=from_date, to_date=to_date)
        .select_related("time_slot", "subject")
        .order_by("date", "time_slot__start_time")
    )
    slot_cols = [
        {"slot_id": s.id, "date": str(s.date), "time_slot": s.time_slot.label}
        for s in slots
    ]
    subject_label = (f"{slots[0].subject.name} ({slots[0].subject.code})"
                     if slots else "")
    roster = list(_roster(batch))
    student_ids = [e.student_id for e in roster]

    marks = (Attendance.objects
             .filter(schedule_slot__in=slots, student_id__in=student_ids)
             .values_list("student_id", "schedule_slot_id", "status"))
    by_student = {}
    for sid, slot_id, status in marks:
        by_student.setdefault(sid, {})[slot_id] = status

    rows = [
        {
            "student_id": e.student_id,
            "application_form_id": e.student.application_form_id,
            "name": e.student.student_name,
            "cells": by_student.get(e.student_id, {}),
        }
        for e in roster
    ]
    return {
        "batch_id": batch.id,
        "batch_name": batch.name,
        "subject": subject_label,
        "slots": slot_cols,
        "rows": rows,
    }


# === Semester dropdown (derived) =====================================

def batch_semesters(batch) -> list[dict]:
    """Distinct semesters present among the batch's active enrollments —
    the schema has no semester on slots, so we derive the filter here."""
    rows = (Enrollment.objects
            .filter(batch=batch, status=Enrollment.Status.ACTIVE)
            .values("semester_id", "semester__number", "semester__name")
            .distinct()
            .order_by("semester__number"))
    return [
        {"id": r["semester_id"],
         "number": r["semester__number"],
         "name": r["semester__name"]}
        for r in rows
    ]
