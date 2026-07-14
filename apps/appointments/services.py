from datetime import date, time

from django.db import transaction
from django.utils import timezone

from .models import StudentAppointment


@transaction.atomic
def request_appointment(*, student, reason: str,
                        preferred_date: date, preferred_time: time,
                        team: str = "", faculty=None) -> StudentAppointment:
    # Exactly one target — a generic team OR a specific faculty member.
    if bool(team) == bool(faculty):
        raise ValueError("Pick either a team or a faculty member, not both.")
    if team and team not in StudentAppointment.Team.values:
        raise ValueError("Invalid team.")

    open_statuses = (StudentAppointment.Status.REQUESTED,
                     StudentAppointment.Status.CONFIRMED)
    # Block spamming the same target with multiple open requests.
    dup = StudentAppointment.objects.filter(
        student=student, status__in=open_statuses,
    )
    dup = dup.filter(faculty=faculty) if faculty else dup.filter(team=team)
    if dup.exists():
        who = "faculty member" if faculty else "team"
        raise ValueError(
            f"You already have an open appointment with this {who}."
        )
    return StudentAppointment.objects.create(
        student=student, team=team or "", faculty=faculty, reason=reason,
        preferred_date=preferred_date, preferred_time=preferred_time,
    )


@transaction.atomic
def decide_appointment(*, appointment: StudentAppointment, decision: str,
                       scheduled_date: date | None = None,
                       scheduled_time: time | None = None,
                       venue: str = "", remarks: str = "",
                       decided_by) -> StudentAppointment:
    if appointment.status != StudentAppointment.Status.REQUESTED:
        raise ValueError(f"Appointment is already {appointment.status}.")
    if decision not in (StudentAppointment.Status.CONFIRMED,
                        StudentAppointment.Status.DECLINED):
        raise ValueError("decision must be CONFIRMED or DECLINED.")

    appointment.status = decision
    if decision == StudentAppointment.Status.CONFIRMED:
        # Fall back to the student's proposed slot when staff confirm
        # as-is without picking a new time.
        appointment.scheduled_date = scheduled_date or appointment.preferred_date
        appointment.scheduled_time = scheduled_time or appointment.preferred_time
        appointment.venue = venue or ""
    appointment.staff_remarks = remarks or ""
    appointment.decided_by = decided_by
    appointment.decided_at = timezone.now()
    appointment.save(update_fields=[
        "status", "scheduled_date", "scheduled_time", "venue",
        "staff_remarks", "decided_by", "decided_at", "updated_at",
    ])
    return appointment


@transaction.atomic
def complete_appointment(*, appointment: StudentAppointment,
                         decided_by) -> StudentAppointment:
    if appointment.status != StudentAppointment.Status.CONFIRMED:
        raise ValueError("Only a confirmed appointment can be completed.")
    appointment.status = StudentAppointment.Status.COMPLETED
    appointment.decided_by = decided_by
    appointment.decided_at = timezone.now()
    appointment.save(update_fields=[
        "status", "decided_by", "decided_at", "updated_at",
    ])
    return appointment


@transaction.atomic
def cancel_appointment(*, appointment: StudentAppointment) -> StudentAppointment:
    """Student-initiated cancellation of an open request."""
    if appointment.status not in (StudentAppointment.Status.REQUESTED,
                                  StudentAppointment.Status.CONFIRMED):
        raise ValueError(
            "Only a requested or confirmed appointment can be cancelled."
        )
    appointment.status = StudentAppointment.Status.CANCELLED
    appointment.save(update_fields=["status", "updated_at"])
    return appointment
