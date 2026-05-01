"""Business rules that span multiple models — kept out of views/serializers
so they can be shared between the manual-create endpoint and the
automated intake endpoint.

Module F.2 hardens the dedup logic per the JD Lead-to-Admission Process
PDF: phone normalization, occurrence numbering, alt-contact merging,
and auto-assignment of duplicates to the counsellor who first received
the lead.
"""

import re

from django.db import transaction
from django.db.models import Q

from .models import Lead, LeadStatusHistory


# --- Phone normalization ----------------------------------------------

# --- Round-robin counsellor assignment (F.3) --------------------------

def assign_via_round_robin(*, program_category: str):
    """Pick the next available counsellor from the pool for this
    program category. Returns a User or None.

    Race-safe via select_for_update on the pool row. Skips counsellors
    whose `is_available=False`.
    """
    from django.db import transaction
    from django.contrib.auth import get_user_model
    from .models import CounsellorPool, CounsellorPoolMembership

    User = get_user_model()
    with transaction.atomic():
        try:
            pool = CounsellorPool.objects.select_for_update().get(
                category=program_category, is_active=True,
            )
        except CounsellorPool.DoesNotExist:
            return None

        memberships = list(
            CounsellorPoolMembership.objects
            .filter(pool=pool, is_active=True, user__is_active=True, user__is_available=True)
            .order_by("sort_order", "id")
        )
        if not memberships:
            return None

        idx = pool.pointer % len(memberships)
        chosen = memberships[idx].user
        pool.pointer = (pool.pointer + 1) % max(len(memberships), 1)
        pool.save(update_fields=["pointer", "updated_at"])
        return chosen


def normalize_phone(raw: str | None) -> str:
    """Return the last 10 digits of `raw`, stripping +91, country codes,
    spaces, dashes, parentheses. Empty string if nothing usable."""
    if not raw:
        return ""
    digits = re.sub(r"\D+", "", raw)
    return digits[-10:] if len(digits) >= 10 else digits


# --- Duplicate detection ----------------------------------------------

def find_duplicates(*, email: str, phone_normalized: str) -> list[Lead]:
    """All existing leads that match by email OR phone (case-insensitive,
    normalized). Earliest first."""
    if not email and not phone_normalized:
        return []
    filters = Q()
    if email:
        filters |= Q(email__iexact=email)
    if phone_normalized:
        filters |= Q(phone_normalized=phone_normalized)
    return list(Lead.objects.filter(filters).order_by("created_at"))


def _occurrence_label(n: int) -> str:
    if n <= 1: return "Primary"
    if n == 2: return "Secondary"
    if n == 3: return "Tertiary"
    return "Repeated"


# --- Lead create with full F.2 dedup logic ----------------------------

@transaction.atomic
def create_lead(*, data: dict, created_by=None, utm: dict | None = None) -> Lead:
    """Create a Lead with normalized phone, occurrence numbering,
    alt-contact merging on partial matches, and auto-assignment of
    duplicates back to the original counsellor."""

    # Pop fields the model doesn't have
    data = dict(data)
    raw_phone = data.get("phone", "")
    phone_norm = normalize_phone(raw_phone)
    email = (data.get("email") or "").strip()

    # Find existing leads that match
    existing = find_duplicates(email=email, phone_normalized=phone_norm)

    # No match → fresh lead. Auto-assign via round-robin if no
    # `assign_to` was supplied (matches the PDF's Phase 2 SLA).
    if not existing:
        if not data.get("assign_to") and data.get("program") is not None:
            from apps.master.models import Program
            cat = getattr(data["program"], "category", None)
            if cat:
                rr = assign_via_round_robin(program_category=cat)
                if rr is not None:
                    data["assign_to"] = rr

        lead = Lead.objects.create(
            created_by=created_by,
            phone_normalized=phone_norm,
            occurrence_number=1,
            **data,
        )
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

    # Match found — figure out occurrence + duplicate root
    root = existing[0]
    if root.duplicate_of_id:
        # If root is itself flagged, walk up.
        root = root.duplicate_of or root

    # Count the entire duplicate family (root + already-flagged dups),
    # not just the matches against the new lead's email/phone. This
    # correctly assigns "Tertiary" when the same person comes in via
    # different (email, phone) tuples that each match the root via a
    # different field.
    family_count = Lead.objects.filter(
        Q(pk=root.pk) | Q(duplicate_of=root)
    ).count()
    next_seq = family_count + 1

    # Auto-assign to original counsellor (overrides any incoming assign_to).
    data["assign_to"] = root.assign_to

    lead = Lead.objects.create(
        created_by=created_by,
        phone_normalized=phone_norm,
        is_repeated=True,
        duplicate_of=root,
        occurrence_number=next_seq,
        **data,
    )

    # Alt-contact merge: if a previous lead had the SAME email but a
    # DIFFERENT phone (or vice versa), surface the new value as an alt
    # on the root so the counsellor can see all known numbers/emails.
    _merge_alts(root, new_email=email, new_phone=raw_phone, new_phone_norm=phone_norm)

    if utm and any(v for v in utm.values()):
        from .models import LeadUtm
        LeadUtm.objects.create(lead=lead, **{
            k: v for k, v in utm.items() if v is not None
        })

    LeadStatusHistory.objects.create(
        lead=lead, old_status="", new_status=lead.status,
        changed_by=created_by,
        note=f"Lead created — duplicate of #{root.id} "
             f"({_occurrence_label(next_seq)}, occurrence {next_seq}).",
    )
    return lead


def _merge_alts(root: Lead, *, new_email: str, new_phone: str, new_phone_norm: str) -> None:
    """If root has same email but different phone → store new phone as alt.
    If same phone but different email → store new email as alt."""
    changed = []

    # Same email, diff phone → alt phone
    if (new_phone_norm
            and root.email.lower() == (new_email or "").lower()
            and root.phone_normalized != new_phone_norm
            and not root.alternative_phone):
        root.alternative_phone = new_phone
        changed.append("alternative_phone")

    # Same phone, diff email → alt email
    if (new_email
            and root.phone_normalized == new_phone_norm
            and root.email.lower() != new_email.lower()
            and not root.alternative_email):
        root.alternative_email = new_email
        changed.append("alternative_email")

    if changed:
        root.save(update_fields=changed + ["updated_at"])


# --- Status transitions (unchanged from Module B) ---------------------

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


def has_recent_outcome(lead: Lead) -> bool:
    """True if a follow-up with an outcome_category has been logged AFTER
    the most recent status-history entry. Used by the status-progression
    guard (F.4): the CRM must not advance a stage without a logged outcome.
    """
    from .models import LeadFollowup, LeadStatusHistory
    last_change = (
        LeadStatusHistory.objects.filter(lead=lead).order_by("-changed_at").first()
    )
    qs = LeadFollowup.objects.filter(lead=lead).exclude(outcome_category="")
    if last_change:
        qs = qs.filter(created_at__gte=last_change.changed_at)
    return qs.exists()


def find_overdue_hot_leads(*, hours: int = 24):
    """Hot leads whose `next_followup_date` is older than `hours` ago,
    still PENDING. Used by the escalation command (F.4 + F.5)."""
    from datetime import timedelta
    from django.utils import timezone
    from .models import LeadFollowup

    cutoff = timezone.now() - timedelta(hours=hours)
    cutoff_date = cutoff.date()

    # Latest followup per lead with HOT outcome and overdue date.
    hot_followups = LeadFollowup.objects.filter(
        outcome_category=LeadFollowup.Outcome.HOT,
        next_followup_date__lt=cutoff_date,
    ).select_related("lead").order_by("lead_id", "-created_at")

    seen = set()
    overdue = []
    for fu in hot_followups:
        if fu.lead_id in seen:
            continue
        seen.add(fu.lead_id)
        if fu.lead.status == Lead.Status.ACTIVE:
            overdue.append((fu.lead, fu))
    return overdue


# --- Backfill helper for existing data --------------------------------

def backfill_phone_normalized() -> int:
    """One-shot helper: populate `phone_normalized` on existing rows.
    Called by migration data-fix or by a management command."""
    count = 0
    for lead in Lead.objects.filter(phone_normalized="").iterator():
        norm = normalize_phone(lead.phone)
        if norm:
            Lead.objects.filter(pk=lead.pk).update(phone_normalized=norm)
            count += 1
    return count
