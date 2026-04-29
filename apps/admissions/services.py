"""Promotion + lifecycle services for admissions.

Lead → Student is the single biggest transition: it creates the Student
row plus a User account so the student can log into the student panel.
"""

import re
import secrets
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Max

from apps.leads.models import Lead

from .models import Enrollment, Student

User = get_user_model()


# --- application_form_id generator -------------------------------------

def generate_application_form_id(*, institute_code: str, year: int | None = None) -> str:
    year = year or datetime.now().year
    prefix = f"{institute_code.upper()}-{year}-"
    last = Student.objects.filter(
        application_form_id__startswith=prefix,
    ).aggregate(m=Max("application_form_id"))["m"]
    if last and (m := re.match(r".+-(\d+)$", last)):
        seq = int(m.group(1)) + 1
    else:
        seq = 1
    return f"{prefix}{seq:05d}"


# --- Username uniqueness -----------------------------------------------

def _unique_username(seed: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "", (seed or "student").lower())[:24] or "student"
    candidate = base
    n = 1
    while User.objects.filter(username__iexact=candidate).exists():
        n += 1
        candidate = f"{base}{n}"
    return candidate


# --- Lead → Student ----------------------------------------------------

@transaction.atomic
def promote_lead_to_student(*, lead: Lead, actor=None) -> tuple[Student, dict]:
    """Create a Student record + a portal User from a Lead.

    Returns (student, credentials_dict). Credentials are returned ONCE —
    PA free can't email them, so HR must capture them at this moment.
    """
    if hasattr(lead, "promoted_student") and lead.promoted_student is not None:
        raise ValueError("This lead already has a promoted student.")

    institute = getattr(lead.campus, "institute", None)
    if institute is None:
        raise ValueError(
            f"Campus '{lead.campus.code}' has no parent Institute set; "
            "fix the campus master before promoting leads."
        )

    # Pick a default current academic year (one row marked is_current=True).
    from apps.master.models import AcademicYear
    acad_year = AcademicYear.objects.filter(is_current=True).first()
    if acad_year is None:
        raise ValueError("No current AcademicYear is set; create one first.")

    # Create the User account.
    username = _unique_username(seed=lead.email.split("@")[0] if "@" in (lead.email or "") else lead.name)
    temp_password = secrets.token_urlsafe(12)
    user = User.objects.create_user(
        username=username,
        email=lead.email,
        full_name=lead.name,
        password=temp_password,
    )
    user.campuses.add(lead.campus)

    # Create the Student row.
    app_id = generate_application_form_id(institute_code=institute.code)
    student = Student.objects.create(
        application_form_id=app_id,
        student_name=lead.name,
        gender=Student.Gender.OTHER,
        dob="2000-01-01",
        nationality=Student.Nationality.INDIAN,
        category=Student.Category.GENERAL,
        institute=institute,
        campus=lead.campus,
        program=lead.program,
        academic_year=acad_year,
        student_mobile=lead.phone,
        student_email=lead.email,
        user_account=user,
        lead_origin=lead,
        created_by=actor,
        updated_by=actor,
    )

    # Mark the lead as Application Submitted.
    from apps.leads.services import change_status as change_lead_status
    if lead.status != Lead.Status.APPLICATION_SUBMITTED:
        change_lead_status(
            lead=lead,
            new_status=Lead.Status.APPLICATION_SUBMITTED,
            changed_by=actor,
            note=f"Promoted to student form ({app_id}).",
        )

    creds = {
        "username": username,
        "temporary_password": temp_password,
        "note": "Save this password now — it's shown once. Email delivery is not configured.",
    }
    return student, creds


# --- Enrollment guard --------------------------------------------------

def can_enroll(student: Student) -> tuple[bool, str]:
    """Has the student done enough to be enrolled? At minimum: form
    must be filled (DOB realistic, address present)."""
    if student.dob.year < 1950:
        return False, "Date of birth looks unset; student must complete the form first."
    if not student.current_address:
        return False, "Current address is required before enrollment."
    return True, ""
