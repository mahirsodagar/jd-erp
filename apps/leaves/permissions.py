from rest_framework.permissions import BasePermission


def _has(user, key: str) -> bool:
    return user.is_authenticated and user.roles.filter(permissions__key=key).exists()


def has_perm(user, key: str) -> bool:
    return user.is_superuser or _has(user, key)


class LeaveAccessPolicy(BasePermission):
    """Authentication + the *minimum* read perm to use any leave endpoint."""

    message = "Authentication required."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated)


def get_employee_for(user):
    """The Employee record linked to this User, or None if the user is
    HR-only (no Employee row, like the bootstrap superuser)."""
    return getattr(user, "employee", None)


def manager_emails(user) -> set[str]:
    """Every (lower-cased) email that identifies this user as the
    approver of a leave / comp-off.

    Requests are routed to the reporting manager's *employee* primary
    email, but the manager may log in with a different address (e.g. a
    personal Gmail set when the portal account was created). Matching on
    the login email alone made such managers' Team Approval list empty,
    so we accept the login email and both employee emails.
    """
    emails = {(getattr(user, "email", "") or "").strip().lower()}
    emp = get_employee_for(user)
    if emp is not None:
        emails.add((emp.email_primary or "").strip().lower())
        emails.add((emp.email_alternate or "").strip().lower())
    emails.discard("")
    return emails


def manager_email_q(user):
    """Queryset filter: rows whose manager_email snapshot is one of
    `manager_emails(user)` (case-insensitive). Matches nothing when the
    user has no email at all."""
    from django.db.models import Q

    q = Q(pk__in=[])
    for e in manager_emails(user):
        q |= Q(manager_email__iexact=e)
    return q


def is_manager_for(user, obj) -> bool:
    """True when `obj.manager_email` names this user."""
    return (obj.manager_email or "").strip().lower() in manager_emails(user)
