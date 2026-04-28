"""Helpers used by views to record auth events. Keeping the call sites
free of model imports keeps view files focused."""

from .models import AuthLog


def _request_meta(request):
    if request is None:
        return None, ""
    ip = (
        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.META.get("REMOTE_ADDR")
        or None
    )
    ua = request.META.get("HTTP_USER_AGENT", "")[:400]
    return ip, ua


def record_login_success(request, *, user):
    ip, ua = _request_meta(request)
    AuthLog.objects.create(
        event=AuthLog.Event.LOGIN_SUCCESS,
        actor=user, target=user,
        ip_address=ip, user_agent=ua,
    )


def record_login_failure(request, *, identifier):
    ip, ua = _request_meta(request)
    AuthLog.objects.create(
        event=AuthLog.Event.LOGIN_FAILURE,
        identifier=identifier or "",
        ip_address=ip, user_agent=ua,
    )


def record_logout(request, *, user):
    ip, ua = _request_meta(request)
    AuthLog.objects.create(
        event=AuthLog.Event.LOGOUT,
        actor=user, target=user,
        ip_address=ip, user_agent=ua,
    )


def record_password_change(request, *, user):
    ip, ua = _request_meta(request)
    AuthLog.objects.create(
        event=AuthLog.Event.PASSWORD_CHANGE,
        actor=user, target=user,
        ip_address=ip, user_agent=ua,
    )


def record_password_reset(request, *, actor, target):
    ip, ua = _request_meta(request)
    AuthLog.objects.create(
        event=AuthLog.Event.PASSWORD_RESET,
        actor=actor, target=target,
        ip_address=ip, user_agent=ua,
    )


def record_role_change(request, *, action, role):
    ip, ua = _request_meta(request)
    event_map = {
        "create": AuthLog.Event.ROLE_CREATE,
        "update": AuthLog.Event.ROLE_UPDATE,
        "delete": AuthLog.Event.ROLE_DELETE,
    }
    AuthLog.objects.create(
        event=event_map[action],
        actor=getattr(request, "user", None) if request else None,
        ip_address=ip, user_agent=ua,
        metadata={"role_id": role.id, "role_name": role.name},
    )


def record_lockout(*, identifier, ip):
    AuthLog.objects.create(
        event=AuthLog.Event.LOCKOUT,
        identifier=identifier or "",
        ip_address=ip,
    )
