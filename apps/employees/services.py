"""Image + code generation. Pure-Python (Pillow + qrcode) so it runs
on PythonAnywhere free without system libraries."""

import io
import re
import secrets
from datetime import datetime

import qrcode
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max
from PIL import Image

from .models import Employee


# --- emp_code -----------------------------------------------------------

def generate_emp_code(*, campus_code: str, year: int | None = None) -> str:
    """`{CAMPUS}-{YYYY}-{seq:04d}`. Race-safe enough for HR-scale traffic
    (single-digit concurrent writers); the unique constraint is the
    real backstop."""
    year = year or datetime.now().year
    prefix = f"{campus_code.upper()}-{year}-"
    last = Employee.all_objects.filter(
        emp_code__startswith=prefix
    ).aggregate(m=Max("emp_code"))["m"]
    if last:
        match = re.match(r".+-(\d+)$", last)
        seq = int(match.group(1)) + 1 if match else 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


# --- Photo thumbnail ----------------------------------------------------

THUMB_SIZE = (300, 300)
PHOTO_MAX_BYTES = 2 * 1024 * 1024  # 2 MB


def validate_photo(file) -> None:
    if file.size > PHOTO_MAX_BYTES:
        raise ValueError("Photo exceeds 2 MB.")
    try:
        img = Image.open(file)
        img.verify()
    except Exception as e:
        raise ValueError(f"Invalid image file: {e}") from e
    file.seek(0)
    fmt = (img.format or "").upper()
    if fmt not in {"JPEG", "PNG"}:
        raise ValueError("Photo must be JPEG or PNG.")


def make_thumbnail(file) -> ContentFile:
    file.seek(0)
    img = Image.open(file).convert("RGB")
    img.thumbnail(THUMB_SIZE)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return ContentFile(buf.getvalue(), name="photo.jpg")


# --- QR code ------------------------------------------------------------

def make_qr_image(payload: str) -> ContentFile:
    qr = qrcode.QRCode(
        version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10, border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return ContentFile(buf.getvalue(), name="qr.png")


@transaction.atomic
def regenerate_qr(employee: Employee) -> None:
    payload = f"emp:{employee.id}:{employee.emp_code}"
    employee.qr_code.save(
        f"qr_{employee.id}.png", make_qr_image(payload), save=True,
    )


# --- Portal account provisioning ----------------------------------------

# Single shared role name that every freshly provisioned employee picks up.
# Keep this in sync with `apps.roles.seed.seed_faculty_role`.
DEFAULT_EMPLOYEE_ROLE = "Faculty"


def _unique_username_for(employee: Employee) -> str:
    """Username = slugified `first_name`, with a numeric suffix on
    collision. Falls back to `emp_code` and then `emp<id>` if the first
    name is missing or only contains characters we can't slugify."""
    User = get_user_model()
    base = re.sub(r"[^a-z0-9]+", "-", (employee.first_name or "").lower()).strip("-")
    if not base:
        base = re.sub(r"[^a-z0-9]+", "-", employee.emp_code.lower()).strip("-")
    candidate = base or f"emp{employee.id}"
    n = 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return candidate


@transaction.atomic
def provision_portal_user(
    *,
    employee: Employee,
    default_role_name: str | None = DEFAULT_EMPLOYEE_ROLE,
) -> tuple[object, str | None]:
    """Create a portal `User` for the employee if one doesn't exist yet.

    Returns `(user, temp_password)`. `temp_password` is None when the
    employee already had an account — callers should show it once to HR
    when fresh, otherwise nothing.

    The user is linked via the `Employee.user_account` OneToOne so the
    employee row is the source of truth; deleting the user nulls the
    link but doesn't delete the employee.
    """
    from apps.roles.models import Role  # local to avoid app-init cycles

    User = get_user_model()

    if employee.user_account_id:
        return employee.user_account, None

    # Re-attach to an existing user that shares the employee's email.
    # This makes the backfill idempotent on a system where someone has
    # already manually provisioned a portal account via the admin UI.
    if employee.email_primary:
        existing = User.objects.filter(
            email__iexact=employee.email_primary,
        ).first()
        if existing is not None:
            employee.user_account = existing
            employee.save(update_fields=["user_account"])
            return existing, None

    username = _unique_username_for(employee)
    temp_password = secrets.token_urlsafe(12)
    user = User.objects.create_user(
        username=username,
        email=employee.email_primary or "",
        full_name=employee.full_name,
        password=temp_password,
    )
    if employee.campus_id:
        user.campuses.add(employee.campus)
    if default_role_name:
        role = Role.objects.filter(name=default_role_name).first()
        if role is not None:
            user.roles.add(role)
    # Inherit the role attached to this employee's designation (if any),
    # so a Faculty designation can grant the Faculty role automatically.
    designation_role_id = (
        employee.designation.role_id if employee.designation_id else None
    )
    if designation_role_id:
        user.roles.add(designation_role_id)

    # The plaintext is returned once for HR to share and never stored.
    employee.user_account = user
    employee.save(update_fields=["user_account"])
    return user, temp_password
