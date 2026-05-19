"""Helper to mirror a freshly-set plaintext password onto the linked
Student / Employee row's `portal_temp_password` column.

The trade-off is documented on the model fields: HR wanted parity with
the old PHP system that stored plaintext so staff could re-share the
password without forcing a rotation. The mirror happens server-side at
the same moment the user's hashed password is updated.

Called from every code path that sets a User password — admin reset,
self change-password, and the forgot/reset-password flow.
"""

from __future__ import annotations


def mirror_plaintext_password(user, plaintext: str) -> None:
    """If `user` is linked to a Student or Employee, copy `plaintext`
    onto that row's `portal_temp_password`. No-op when there's no link
    or the password is blank."""
    if not plaintext:
        return

    student = getattr(user, "student", None)
    if student is not None:
        student.portal_temp_password = plaintext
        student.save(update_fields=["portal_temp_password"])

    employee = getattr(user, "employee", None)
    if employee is not None:
        employee.portal_temp_password = plaintext
        employee.save(update_fields=["portal_temp_password"])
