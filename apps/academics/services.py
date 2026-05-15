"""Conflict detection + bulk publish for ScheduleSlot.

Per spec:
- Hard reject: same instructor double-booked, same batch double-booked.
- Soft warn: same classroom double-booked. Caller can pass force=True
  to allow.
"""

from datetime import date as _date, timedelta

from django.db import transaction

from .models import ScheduleSlot


def detect_conflicts(*, batch, instructor, classroom, time_slot, date,
                     exclude_id: int | None = None) -> dict:
    """Returns dict with `errors` (hard) and `warnings` (soft).

    errors  → instructor / batch double-booked → reject the create.
    warnings → classroom double-booked → require force=True.
    """
    errors: list[str] = []
    warnings: list[str] = []

    base = ScheduleSlot.objects.filter(
        date=date, time_slot=time_slot,
        status=ScheduleSlot.Status.SCHEDULED,
    )
    if exclude_id:
        base = base.exclude(pk=exclude_id)

    if instructor and base.filter(instructor=instructor).exists():
        errors.append(
            f"Instructor {instructor} is already scheduled in this slot."
        )
    if batch and base.filter(batch=batch).exists():
        errors.append(
            f"Batch {batch} is already scheduled in this slot."
        )
    if classroom and base.filter(classroom=classroom).exists():
        warnings.append(
            f"Classroom {classroom} is already in use in this slot. "
            "Pass force=true to override."
        )
    return {"errors": errors, "warnings": warnings}


@transaction.atomic
def create_slot(*, batch, subject, instructor, classroom, time_slot, date,
                created_by=None, force: bool = False,
                notes: str = "") -> tuple[ScheduleSlot | None, dict]:
    """Returns (slot, report). slot=None when blocked."""
    report = detect_conflicts(
        batch=batch, instructor=instructor,
        classroom=classroom, time_slot=time_slot, date=date,
    )
    if report["errors"]:
        return None, report
    if report["warnings"] and not force:
        return None, report

    slot = ScheduleSlot.objects.create(
        batch=batch, subject=subject, instructor=instructor,
        classroom=classroom, time_slot=time_slot, date=date,
        notes=notes, created_by=created_by,
        classroom_conflict_overridden=bool(report["warnings"] and force),
    )
    return slot, report


@transaction.atomic
def bulk_publish_weekly(*, start_date: _date, end_date: _date,
                        weekday: int, batch, subject, instructor,
                        classroom, time_slot, created_by=None,
                        force: bool = False) -> dict:
    """Create one ScheduleSlot per matching weekday in [start, end].

    weekday: 0=Mon, 6=Sun (Python convention, matches `date.weekday()`).
    Returns {created: [...ids], skipped: [{date, errors, warnings}]}.
    All created in one transaction; per-date conflicts mark that date
    as skipped without rolling back the rest.
    """
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")
    if not 0 <= weekday <= 6:
        raise ValueError("weekday must be 0..6.")

    created, skipped = [], []
    cur = start_date
    while cur <= end_date:
        if cur.weekday() == weekday:
            slot, report = create_slot(
                batch=batch, subject=subject, instructor=instructor,
                classroom=classroom, time_slot=time_slot, date=cur,
                created_by=created_by, force=force,
            )
            if slot:
                created.append(slot.id)
            else:
                skipped.append({
                    "date": str(cur),
                    "errors": report["errors"],
                    "warnings": report["warnings"],
                })
        cur += timedelta(days=1)
    return {"created": created, "skipped": skipped}


@transaction.atomic
def bulk_publish_weekly_grid(*, start_date: _date, end_date: _date,
                             batch, cells: list[dict],
                             resolver, created_by=None,
                             force: bool = False) -> dict:
    """Expand a full (weekday × time_slot) grid over the date range.

    Mirrors the PHP "Publish Time Table" action — the whole grid is
    published in one call so the user doesn't need to fire one request
    per cell.

    Each cell dict carries pre-fetched FK objects (subject, instructor,
    classroom, time_slot) — the resolver is the caller's view that
    already had to fetch them anyway. The transaction wraps every cell,
    so a serializer-level rejection (e.g. unknown id) rolls the whole
    publish back; per-date soft conflicts inside one cell still get
    skipped through the existing `bulk_publish_weekly` semantics.

    Returns:
      {
        "total_created": int,
        "total_skipped": int,
        "cells": [
          {
            "index": int,
            "weekday": int,
            "time_slot": int,
            "created": [ids],
            "skipped": [{date, errors, warnings}],
          },
          ...
        ],
      }
    """
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date.")

    out_cells: list[dict] = []
    total_created = 0
    total_skipped = 0

    for idx, cell in enumerate(cells):
        resolved = resolver(cell)
        sub = bulk_publish_weekly(
            start_date=start_date,
            end_date=end_date,
            weekday=cell["weekday"],
            batch=batch,
            subject=resolved["subject"],
            instructor=resolved["instructor"],
            classroom=resolved["classroom"],
            time_slot=resolved["time_slot"],
            created_by=created_by,
            force=force,
        )
        total_created += len(sub["created"])
        total_skipped += len(sub["skipped"])
        out_cells.append({
            "index": idx,
            "weekday": cell["weekday"],
            "time_slot": cell["time_slot"],
            "created": sub["created"],
            "skipped": sub["skipped"],
        })

    return {
        "total_created": total_created,
        "total_skipped": total_skipped,
        "cells": out_cells,
    }
