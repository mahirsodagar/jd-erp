"""Access rules for the payments API.

Deliberately reuses the existing `leads.*` permission keys rather than
minting `payments.*` ones: new keys only take effect after
`manage.py seed_permissions`, which resets customised role grants, and
nothing here is a genuinely new capability. Reading a payment request is
reading a lead's fee state; reconciling one can mark that fee paid, so it
carries the same weight as the manual mark-paid action.
"""

from rest_framework.permissions import BasePermission


def _has(user, key: str) -> bool:
    return user.is_authenticated and user.roles.filter(
        permissions__key=key,
    ).exists()


def has_perm(user, key: str) -> bool:
    return bool(user and (user.is_superuser or _has(user, key)))


class CanViewPaymentRequests(BasePermission):
    """Anyone who can see a lead's fee state can see its payment requests."""

    message = "Viewing payments requires a lead or fee role."

    def has_permission(self, request, view):
        u = request.user
        if not u or not u.is_authenticated:
            return False
        return (
            u.is_superuser
            or _has(u, "leads.application_fee.record")
            or _has(u, "leads.send.fee_link")
            or _has(u, "leads.lead.view_all")
            or _has(u, "leads.lead.view")
        )


class CanReconcilePayments(BasePermission):
    """Reconciling takes SmartGateway's word for it and can stamp the lead
    as paid — the same state change as `LeadMarkFeePaidView`, so it needs
    the same grant."""

    message = "Reconciling a payment requires the application-fee role."

    def has_permission(self, request, view):
        return has_perm(request.user, "leads.application_fee.record")
