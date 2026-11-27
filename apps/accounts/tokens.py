"""Refresh-token revocation helpers (SimpleJWT token_blacklist app).

Access tokens are stateless and stay valid until they expire (15 min by
default); refresh tokens are the long-lived credential, so revoking a
user's outstanding refresh tokens is what actually ends their other
sessions. Inactive users are additionally rejected on every request by
SimpleJWT (`CHECK_USER_IS_ACTIVE`), so deactivation takes effect at once
regardless of this helper.
"""

from __future__ import annotations

from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)


def revoke_all_refresh_tokens(user) -> int:
    """Blacklist every outstanding refresh token issued to `user`.

    Returns the number of tokens newly blacklisted. Safe to call for a
    user with none.
    """
    if user is None or getattr(user, "pk", None) is None:
        return 0
    outstanding = OutstandingToken.objects.filter(user=user).exclude(
        blacklistedtoken__isnull=False,
    )
    rows = [BlacklistedToken(token=tok) for tok in outstanding]
    if not rows:
        return 0
    BlacklistedToken.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)
