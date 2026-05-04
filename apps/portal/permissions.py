"""Permission classes for portal endpoints. Each view selects whether
parents are allowed (read-only across attendance/timetable/dashboard) or
restricted to students only."""

from rest_framework.permissions import BasePermission

from .helpers import resolve_portal_context


class IsStudentOrParent(BasePermission):
    message = "Not a student or parent account."

    def has_permission(self, request, view):
        ctx = resolve_portal_context(request.user)
        if ctx is None:
            return False
        request.portal_ctx = ctx
        return True


class IsStudentOnly(BasePermission):
    message = "This endpoint is for students only."

    def has_permission(self, request, view):
        ctx = resolve_portal_context(request.user)
        if ctx is None or ctx.is_parent:
            return False
        request.portal_ctx = ctx
        return True
