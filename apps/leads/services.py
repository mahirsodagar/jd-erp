"""Business rules that span multiple models — kept out of views/serializers
so they can be shared between the manual-create endpoint and the
automated intake endpoint."""

from django.db import transaction
from django.db.models import Q

from .models import Lead, LeadStatusHistory


def find_duplicate(*, email: str, phone: str) -> Lead | None:
    """Earliest existing lead with a matching email OR phone."""
    if not email and not phone:
        return None
    qs = Lead.objects.all()
    filters = Q()
    if email:
        filters |= Q(email__iexact=email)
    if phone:
        filters |= Q(phone__iexact=phone)
    return qs.filter(filters).order_by("created_at").first()


def attach_duplicate_flag(lead: Lead) -> None:
    """Set is_repeated + duplicate_of based on existing leads. Saves the lead."""
    match = find_duplicate(email=lead.email, phone=lead.phone)
    if match and match.pk != lead.pk:
        # If the match is itself a duplicate, point at its root.
        root = match.duplicate_of or match
        lead.is_repeated = True
        lead.duplicate_of = root
        lead.save(update_fields=["is_repeated", "duplicate_of"])


@transaction.atomic
def create_lead(*, data: dict, created_by=None, utm: dict | None = None) -> Lead:
    """Create a Lead, flag duplicates, attach UTM. Single source of truth
    for both manual creation and automated intake."""
    lead = Lead.objects.create(created_by=created_by, **data)
    attach_duplicate_flag(lead)

    if utm and any(v for v in utm.values()):
        from .models import LeadUtm
        LeadUtm.objects.create(lead=lead, **{
            k: v for k, v in utm.items() if v is not None
        })

    LeadStatusHistory.objects.create(
        lead=lead, old_status="", new_status=lead.status,
        changed_by=created_by, note="Lead created.",
    )
    return lead


@transaction.atomic
def change_status(*, lead: Lead, new_status: str, changed_by, note: str = "") -> Lead:
    if new_status == lead.status:
        return lead
    old = lead.status
    lead.status = new_status
    lead.save(update_fields=["status", "updated_at"])
    LeadStatusHistory.objects.create(
        lead=lead, old_status=old, new_status=new_status,
        changed_by=changed_by, note=note,
    )
    return lead
