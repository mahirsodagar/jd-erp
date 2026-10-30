"""In-app (bell) notifications.

`notify()` is the one entry point the modules call. It is best-effort:
it never raises, so a notification problem can never fail the request
that triggered it (a task save, a leave decision, a timetable publish).
"""

import logging

from django.contrib.auth import get_user_model

from .models import InAppNotification

logger = logging.getLogger(__name__)
User = get_user_model()


def notify(recipients, *, title, body="", link="", kind=InAppNotification.Kind.OTHER,
           exclude_user=None) -> int:
    """Create one notification per distinct active recipient.

    `recipients` is any iterable of User instances / ids / None (Nones
    are skipped so callers can pass `employee.user_account` directly).
    `exclude_user` drops the actor so nobody is told about their own
    action. Returns the number of rows written.
    """
    try:
        ids: set[int] = set()
        for r in recipients:
            if r is None:
                continue
            ids.add(r if isinstance(r, int) else r.pk)
        if exclude_user is not None:
            ids.discard(exclude_user.pk)
        if not ids:
            return 0
        active_ids = list(
            User.objects.filter(pk__in=ids, is_active=True).values_list("pk", flat=True)
        )
        rows = [
            InAppNotification(
                recipient_id=uid, kind=kind, title=title[:200],
                body=(body or "")[:500], link=(link or "")[:200],
            )
            for uid in active_ids
        ]
        InAppNotification.objects.bulk_create(rows)
        return len(rows)
    except Exception:  # noqa: BLE001 — never break the caller
        logger.exception("In-app notification failed: %s", title)
        return 0


def user_by_email(email: str):
    """Active user whose email matches, or None. Used to route a
    manager-facing event (leave applied) from the manager_email snapshot."""
    email = (email or "").strip()
    if not email:
        return None
    return User.objects.filter(email__iexact=email, is_active=True).first()
