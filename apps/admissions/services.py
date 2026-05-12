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


# --- Public application form (student self-fills via tokenized link) ---

_STUDENT_TEXT_FIELDS = (
    "student_name", "father_name", "mother_name",
    "blood_group",
    "current_address", "current_pincode",
    "permanent_address", "permanent_pincode",
    "father_mobile", "mother_mobile",
    "father_email", "mother_email",
    "father_occupation", "mother_occupation",
)


def _apply_payload_to_student(student: Student, payload: dict,
                              *, institute, campus, program,
                              acad_year, lead: Lead) -> None:
    """Copy form fields into an existing Student. Used on re-submits.
    Empty/missing values do NOT overwrite existing data — students fill
    incrementally."""
    # Placement
    student.institute = institute
    student.campus = campus
    student.program = program
    student.academic_year = acad_year

    # Free-text fields — only overwrite when the form sent a non-empty value
    for field in _STUDENT_TEXT_FIELDS:
        val = payload.get(field)
        if val not in (None, ""):
            setattr(student, field, val)

    # Choice fields — same rule
    if v := payload.get("gender"):
        student.gender = v
    if v := payload.get("dob"):
        student.dob = v
    if v := payload.get("category"):
        student.category = v
    if v := payload.get("study_medium"):
        student.study_medium = v
    if v := payload.get("nationality"):
        student.nationality = v
    if v := payload.get("student_mobile"):
        student.student_mobile = v
    if v := payload.get("student_email"):
        student.student_email = v

    # FK ids
    for fk_attr, payload_key in (
        ("current_city_id", "current_city"),
        ("current_state_id", "current_state"),
        ("permanent_city_id", "permanent_city"),
        ("permanent_state_id", "permanent_state"),
    ):
        v = payload.get(payload_key)
        if v not in (None, "", "null"):
            setattr(student, fk_attr, v)

    # Mirror name + email onto the linked User account so the portal
    # login can find them if the student changed their email.
    if student.user_account_id and payload.get("student_email"):
        user = student.user_account
        if user.email != payload["student_email"]:
            user.email = payload["student_email"]
            user.save(update_fields=["email"])

    student.lead_origin = lead
    student.save()


def _upsert_documents(student: Student, docs: list[dict]) -> None:
    """Upsert by (student, header). Re-submits replace fields under the
    same header rather than appending duplicates."""
    from .models import StudentDocument
    for d in docs:
        header = d.get("header")
        if not header:
            continue
        StudentDocument.objects.update_or_create(
            student=student, header=header,
            defaults={
                "regno_yearpassing": d.get("regno_yearpassing", ""),
                "school_college": d.get("school_college", ""),
                "university_board": d.get("university_board", ""),
                "certificate_no": d.get("certificate_no", ""),
                "percent_obtained": d.get("percent_obtained") or None,
            },
        )


@transaction.atomic
def submit_application_from_lead(*, lead: Lead, payload: dict) -> tuple[Student, dict]:
    """Create or update the Student tied to this Lead from the self-fill
    application payload.

    Re-submits are allowed by default — the student may fill incrementally
    after counsellor review. The counsellor can close the form for the
    student by setting `lead.application_locked_for_student=True`; in
    that case this raises PermissionError.

    First submit creates the Student + User account and returns
    temporary credentials. Subsequent submits update the existing
    record and return an empty `creds` dict (the student already has
    their login).

    Documents are upserted by `header` so re-submits replace earlier
    values under the same header rather than appending duplicates.
    """
    if lead.application_locked_for_student:
        raise PermissionError(
            "This application form has been closed by your counsellor. "
            "Please contact us if you need to make further changes."
        )
    if lead.application_token is None:
        raise ValueError("This application link is no longer valid.")

    # --- Resolve placement -------------------------------------------------
    from apps.master.models import AcademicYear, Campus, Program
    campus = lead.campus
    if payload.get("campus"):
        try:
            campus = Campus.objects.get(pk=payload["campus"])
        except Campus.DoesNotExist:
            raise ValueError("Selected campus does not exist.")
    program = lead.program
    if payload.get("program"):
        try:
            program = Program.objects.get(pk=payload["program"])
        except Program.DoesNotExist:
            raise ValueError("Selected program does not exist.")
        if not program.campuses.filter(pk=campus.pk).exists():
            raise ValueError(
                f"Program '{program.name}' is not offered at "
                f"campus '{campus.name}'.",
            )

    institute = getattr(campus, "institute", None)
    if institute is None:
        raise ValueError(
            f"Campus '{campus.code}' has no parent Institute set; "
            "fix the campus master before accepting applications.",
        )

    acad_year = AcademicYear.objects.filter(is_current=True).first()
    if acad_year is None:
        raise ValueError("No current AcademicYear is set; create one first.")

    # --- Update path: Student already exists for this lead -----------------
    existing = getattr(lead, "promoted_student", None)
    if existing is not None:
        _apply_payload_to_student(
            existing, payload,
            institute=institute, campus=campus, program=program,
            acad_year=acad_year, lead=lead,
        )
        # Photo replace (if a new one was uploaded).
        photo = payload.get("_photo_file")
        if photo is not None:
            existing.photo.save("photo.jpg", photo, save=True)
        _upsert_documents(existing, payload.get("documents") or [])
        return existing, {
            "application_form_id": existing.application_form_id,
            "note": "Application updated.",
        }

    # --- Create path: first-time submit ------------------------------------
    seed = (payload.get("student_email") or lead.email or "").split("@")[0] \
        or payload.get("student_name") or lead.name
    username = _unique_username(seed=seed)
    temp_password = secrets.token_urlsafe(12)
    user = User.objects.create_user(
        username=username,
        email=payload.get("student_email") or lead.email,
        full_name=payload.get("student_name") or lead.name,
        password=temp_password,
    )
    user.campuses.add(campus)

    app_id = generate_application_form_id(institute_code=institute.code)
    student = Student.objects.create(
        application_form_id=app_id,
        student_name=payload.get("student_name") or lead.name,
        father_name=payload.get("father_name", ""),
        mother_name=payload.get("mother_name", ""),
        gender=payload.get("gender") or Student.Gender.OTHER,
        dob=payload["dob"],
        category=payload.get("category") or Student.Category.GENERAL,
        study_medium=payload.get("study_medium") or Student.StudyMedium.ENGLISH,
        nationality=payload.get("nationality") or Student.Nationality.INDIAN,
        blood_group=payload.get("blood_group", ""),
        institute=institute,
        campus=campus,
        program=program,
        academic_year=acad_year,
        current_address=payload.get("current_address", ""),
        current_city_id=payload.get("current_city"),
        current_state_id=payload.get("current_state"),
        current_pincode=payload.get("current_pincode", ""),
        permanent_address=payload.get("permanent_address", ""),
        permanent_city_id=payload.get("permanent_city"),
        permanent_state_id=payload.get("permanent_state"),
        permanent_pincode=payload.get("permanent_pincode", ""),
        student_mobile=payload.get("student_mobile") or lead.phone,
        father_mobile=payload.get("father_mobile", ""),
        mother_mobile=payload.get("mother_mobile", ""),
        student_email=payload.get("student_email") or lead.email,
        father_email=payload.get("father_email", ""),
        mother_email=payload.get("mother_email", ""),
        father_occupation=payload.get("father_occupation", ""),
        mother_occupation=payload.get("mother_occupation", ""),
        user_account=user,
        lead_origin=lead,
    )

    photo = payload.get("_photo_file")
    if photo is not None:
        student.photo.save("photo.jpg", photo, save=True)

    _upsert_documents(student, payload.get("documents") or [])

    # Flip lead → APPLICATION_SUBMITTED on first submit only; keep the
    # token around so the student can come back and add missing details.
    from apps.leads.services import change_status as change_lead_status
    if lead.status != Lead.Status.APPLICATION_SUBMITTED:
        change_lead_status(
            lead=lead,
            new_status=Lead.Status.APPLICATION_SUBMITTED,
            changed_by=None,
            note=f"Self-submitted application ({app_id}).",
        )

    return student, {
        "username": username,
        "temporary_password": temp_password,
        "note": "Your portal account has been created. Save these credentials.",
    }


# --- Enrollment guard --------------------------------------------------

def can_enroll(student: Student) -> tuple[bool, str]:
    """Has the student done enough to be enrolled? At minimum: form
    must be filled (DOB realistic, address present)."""
    if student.dob.year < 1950:
        return False, "Date of birth looks unset; student must complete the form first."
    if not student.current_address:
        return False, "Current address is required before enrollment."
    return True, ""
