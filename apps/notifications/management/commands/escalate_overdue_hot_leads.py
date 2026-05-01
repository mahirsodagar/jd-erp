"""Find HOT leads with overdue follow-ups (>24h) and notify managers
(per JD Lead-to-Admission Process PDF Phase 4 Step 9).

Manager identification (current rule): any User with the permission key
`leads.escalation.receive`. When a notification is queued the recipient
is each such user's email.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from apps.leads.services import find_overdue_hot_leads
from apps.notifications.services import queue_notification


def _managers_for(lead):
    """Yield emails of users who should receive an escalation. We use
    a permission-key gate so the customer can pick managers via the
    role admin without a code change."""
    User = get_user_model()
    qs = User.objects.filter(
        is_active=True, is_available=True,
        roles__permissions__key="leads.escalation.receive",
    ).distinct()
    # Restrict to managers in the lead's campus (if they have that scope).
    same_campus = qs.filter(campuses=lead.campus_id) if lead.campus_id else qs
    seen = set()
    for u in (same_campus or qs):
        if u.email and u.email not in seen:
            seen.add(u.email)
            yield u


class Command(BaseCommand):
    help = "Notify managers of HOT leads overdue beyond 24h."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)

    def handle(self, *args, **opts):
        hours = opts["hours"]
        overdue = find_overdue_hot_leads(hours=hours)
        notified = 0
        for lead, fu in overdue:
            counsellor = (lead.assign_to.username if lead.assign_to_id
                          else "(unassigned)")
            ctx = {
                "name": lead.name, "phone": lead.phone, "email": lead.email,
                "counsellor": counsellor,
                "program": lead.program.name if lead.program else "",
                "campus": lead.campus.name if lead.campus else "",
                "hours": hours,
            }
            for mgr in _managers_for(lead):
                queue_notification(
                    template_key="manager_overdue_hot_lead",
                    recipient=mgr.email, context=ctx, related=lead,
                )
                queue_notification(
                    template_key="manager_overdue_hot_lead_in_crm",
                    recipient=mgr.username, context=ctx, related=lead,
                )
                notified += 1
        self.stdout.write(self.style.SUCCESS(
            f"escalated {len(overdue)} leads → {notified} notification(s) queued"
        ))
