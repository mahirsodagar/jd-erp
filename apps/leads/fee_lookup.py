"""Resolving the application fee a lead is expected to pay.

A Lead has no academic year, so the fee it owes is whatever the most
recent active FeeTemplate for its (campus, program) says. Three callers
need the same number and must agree on it: the fee-link email, the
SmartGateway payment request, and the counsellor's Application fee box
on the lead detail screen. Keeping the lookup here is what stops them
quoting the student three different amounts.
"""

from decimal import Decimal


def active_application_fee_map() -> dict[tuple[int, int], Decimal]:
    """{(campus_id, program_id): application_fee} across active templates.

    One query for every pair, so a list of leads costs the same as one.
    Where several academic years are on file the newest wins — same rule
    as {@link application_fee_for}, since a Lead names no year.
    """
    from apps.master.models import FeeTemplate

    fees: dict[tuple[int, int], Decimal] = {}
    for campus_id, program_id, fee in (
        FeeTemplate.objects
        .filter(is_active=True)
        .order_by("-academic_year__id", "-id")
        .values_list("campus_id", "program_id", "application_fee")
    ):
        fees.setdefault((campus_id, program_id), fee)
    return fees


def application_fee_for(lead) -> Decimal | None:
    """The lead's expected application fee, or None when no active
    template covers its campus/program (or the template charges nothing —
    a zero fee is not an amount worth quoting).

    Callers that need a last-resort figure for an outgoing message layer
    their own fallback on top; this returns only what master data knows.
    """
    from apps.master.models import FeeTemplate

    if not (lead.campus_id and lead.program_id):
        return None
    tmpl = (
        FeeTemplate.objects
        .filter(
            campus_id=lead.campus_id,
            program_id=lead.program_id,
            is_active=True,
        )
        .order_by("-academic_year__id", "-id")
        .first()
    )
    if tmpl and tmpl.application_fee:
        return tmpl.application_fee
    return None
