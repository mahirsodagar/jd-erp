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

@transaction.atomic
def submit_application_from_lead(*, lead: Lead, payload: dict) -> tuple[Student, dict]:
    """Create a Student row from the full self-fill application payload.

    `payload` shape — only the student-supplied fields are listed; FKs
    (institute / campus / program / academic_year) come from the lead.

        {
            "student_name", "father_name", "mother_name",
            "gender", "dob", "category", "study_medium",
            "nationality", "blood_group", "qualification",
            "current_address", "current_city" (id), "current_state" (id),
            "current_pincode",
            "permanent_address", "permanent_city" (id), "permanent_state" (id),
            "permanent_pincode",
            "student_mobile", "father_mobile", "mother_mobile",
            "student_email", "father_email", "mother_email",
            "father_occupation", "mother_occupation",
            "documents": [
                {
                    "header", "regno_yearpassing", "school_college",
                    "university_board", "certificate_no",
                    "percent_obtained",
                },
                ...
            ],
        }
    """
    if hasattr(lead, "promoted_student") and lead.promoted_student is not None:
        raise ValueError("This application has already been submitted.")
    if lead.application_token is None:
        raise ValueError("This application link is no longer valid.")

    # Campus / program / course may be overridden by the form. Resolve
    # them, then derive Institute from the *chosen* campus so the form's
    # institute branding stays consistent with the saved record.
    from apps.master.models import AcademicYear, Campus, Course, Program
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
        # Validate program is offered at the chosen campus.
        if not program.campuses.filter(pk=campus.pk).exists():
            raise ValueError(
                f"Program '{program.name}' is not offered at "
                f"campus '{campus.name}'.",
            )

    course = None
    if payload.get("course"):
        try:
            course = Course.objects.get(pk=payload["course"])
        except Course.DoesNotExist:
            raise ValueError("Selected course does not exist.")
        if course.program_id != program.id:
            raise ValueError(
                f"Course '{course.name}' is not part of "
                f"program '{program.name}'.",
            )

    institute = getattr(campus, "institute", None)
    if institute is None:
        raise ValueError(
            f"Campus '{campus.code}' has no parent Institute set; "
            "fix the campus master before accepting applications."
        )

    acad_year = AcademicYear.objects.filter(is_current=True).first()
    if acad_year is None:
        raise ValueError("No current AcademicYear is set; create one first.")

    # Create the User account.
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
        course=course,
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

    # Optional photo (raw file passed via the view, not in the dict).
    photo = payload.get("_photo_file")
    if photo is not None:
        student.photo.save("photo.jpg", photo, save=True)

    # Documents.
    from .models import StudentDocument
    docs = payload.get("documents") or []
    for d in docs:
        if not d.get("header"):
            continue
        StudentDocument.objects.create(
            student=student,
            header=d["header"],
            regno_yearpassing=d.get("regno_yearpassing", ""),
            school_college=d.get("school_college", ""),
            university_board=d.get("university_board", ""),
            certificate_no=d.get("certificate_no", ""),
            percent_obtained=d.get("percent_obtained") or None,
        )

    # Flip lead → APPLICATION_SUBMITTED + invalidate token.
    from apps.leads.services import change_status as change_lead_status
    if lead.status != Lead.Status.APPLICATION_SUBMITTED:
        change_lead_status(
            lead=lead,
            new_status=Lead.Status.APPLICATION_SUBMITTED,
            changed_by=None,  # student self-submission, no actor
            note=f"Self-submitted application ({app_id}).",
        )
    lead.application_token = None
    lead.save(update_fields=["application_token"])

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
