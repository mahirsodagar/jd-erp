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


def _upsert_documents(
    student: Student,
    docs: list[dict],
    files: list | None = None,
) -> None:
    """Upsert by (student, header). Re-submits replace fields under the
    same header rather than appending duplicates.

    `files`, when supplied, is index-aligned with `docs` — entry `i`
    holds the uploaded File for `docs[i]` (or None if no file was sent
    for that row). When a file is present we attach it via
    `FileField.save(...)` which moves it under `students/docs/` per the
    model's `upload_to` setting.
    """
    from .models import StudentDocument
    files = files or []
    for idx, d in enumerate(docs):
        header = d.get("header")
        if not header:
            continue
        obj, _created = StudentDocument.objects.update_or_create(
            student=student, header=header,
            defaults={
                "regno_yearpassing": d.get("regno_yearpassing", ""),
                "school_college": d.get("school_college", ""),
                "university_board": d.get("university_board", ""),
                "certificate_no": d.get("certificate_no", ""),
                "percent_obtained": d.get("percent_obtained") or None,
            },
        )
        f = files[idx] if idx < len(files) else None
        if f is not None:
            # Use the original filename for traceability; FileField's
            # upload_to + storage backend handle collisions.
            obj.file.save(getattr(f, "name", "certificate"), f, save=True)


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
        _upsert_documents(
            existing,
            payload.get("documents") or [],
            payload.get("_document_files") or [],
        )
        return existing, {
            "application_form_id": existing.application_form_id,
            "note": "Application updated.",
        }

    # --- Create path: first-time submit ------------------------------------
    # Portal credentials are NOT generated here. Per the revised flow,
    # staff explicitly issues an institute-personalised login + password
    # after the student is enrolled, via the
    # `/api/students/<id>/send-portal-credentials/` endpoint.
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
        lead_origin=lead,
    )

    photo = payload.get("_photo_file")
    if photo is not None:
        student.photo.save("photo.jpg", photo, save=True)

    _upsert_documents(
        student,
        payload.get("documents") or [],
        payload.get("_document_files") or [],
    )

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
        "application_form_id": app_id,
        "note": "Application submitted.",
    }


# --- Batch promotion + bulk graduation ---------------------------------

@transaction.atomic
def promote_batch(
    *,
    source_batch,
    source_semester,
    target_batch,
    target_semester,
    target_academic_year,
    student_ids: list[int] | None = None,
    actor=None,
) -> dict:
    """Promote ACTIVE enrollments from one (batch, semester) into a new
    placement. Mirrors the JD_ERP PHP "Promote Students" screen.

    For each promoted student:
      1. The old Enrollment row is flipped to PROMOTED (audit trail
         preserved — transcripts / attendance stay attached to it).
      2. A new Enrollment row is created in the target with status=ACTIVE.

    `student_ids` lets callers cherry-pick a subset; None = all ACTIVE
    enrollments in the source.

    The target's `program`, `course`, `campus` are inherited from the
    target batch — only `semester` and `academic_year` are caller-
    supplied, which keeps the API small but flexible enough for the
    "next-sem within the same batch" use case.

    Raises ValueError on configuration problems (target == source,
    target batch with no program, etc.) so the view can surface a
    400.
    """
    from datetime import date as _date

    from .models import Enrollment

    if (source_batch.id == target_batch.id
            and source_semester.id == target_semester.id):
        raise ValueError(
            "Target placement matches the source — nothing to promote.",
        )

    qs = (
        Enrollment.objects
        .select_related("student")
        .filter(
            batch=source_batch,
            semester=source_semester,
            status=Enrollment.Status.ACTIVE,
        )
    )
    if student_ids is not None:
        qs = qs.filter(student_id__in=student_ids)

    promoted = []
    skipped = []
    today = _date.today()
    for old in qs:
        # If the student already has an ACTIVE enrollment in the target,
        # skip — don't create duplicates.
        if Enrollment.objects.filter(
            student=old.student,
            batch=target_batch,
            semester=target_semester,
            academic_year=target_academic_year,
        ).exclude(status=Enrollment.Status.DROPPED).exists():
            skipped.append({
                "student_id": old.student_id,
                "student_name": old.student.student_name,
                "reason": "Already has an enrollment in the target placement.",
            })
            continue

        old.status = Enrollment.Status.PROMOTED
        old.save(update_fields=["status", "updated_on"])

        new = Enrollment.objects.create(
            student=old.student,
            program=target_batch.program,
            course=old.course,
            semester=target_semester,
            campus=target_batch.campus,
            batch=target_batch,
            academic_year=target_academic_year,
            status=Enrollment.Status.ACTIVE,
            elective_subjects=old.elective_subjects,
            entry_date=today,
            entry_user=actor,
        )
        promoted.append({
            "student_id": old.student_id,
            "student_name": old.student.student_name,
            "from_enrollment_id": old.id,
            "to_enrollment_id": new.id,
        })

    return {
        "promoted": promoted,
        "skipped": skipped,
        "totals": {
            "promoted": len(promoted),
            "skipped": len(skipped),
        },
    }


@transaction.atomic
def graduate_batch(
    *,
    batch,
    semester=None,
    student_ids: list[int] | None = None,
    actor=None,
) -> dict:
    """Mark every ACTIVE enrollment in a batch (optionally filtered to
    one semester or a subset of students) as ALUMNI, creating an
    AlumniRecord per student via the existing `graduate_enrollment`
    helper.

    Idempotent: enrollments already in ALUMNI are skipped silently.
    """
    from apps.academics.cert_service import graduate_enrollment

    from .models import Enrollment

    qs = (
        Enrollment.objects
        .select_related("student", "academic_year", "program", "batch")
        .filter(batch=batch, status=Enrollment.Status.ACTIVE)
    )
    if semester is not None:
        qs = qs.filter(semester=semester)
    if student_ids is not None:
        qs = qs.filter(student_id__in=student_ids)

    graduated = []
    for enr in qs:
        _, rec = graduate_enrollment(enrollment=enr, by_user=actor)
        graduated.append({
            "student_id": enr.student_id,
            "student_name": enr.student.student_name,
            "enrollment_id": enr.id,
            "alumni_id": rec.id,
        })

    return {
        "graduated": graduated,
        "totals": {"graduated": len(graduated)},
    }


# --- Enrollment guard --------------------------------------------------

def can_enroll(student: Student) -> tuple[bool, str]:
    """Has the student done enough to be enrolled? At minimum: form
    must be filled (DOB realistic, address present). A student may
    only be enrolled once — re-enrollment is not supported here; semester
    progression is handled via promotion on the existing record."""
    if student.dob.year < 1950:
        return False, "Date of birth looks unset; student must complete the form first."
    if not student.current_address:
        return False, "Current address is required before enrollment."
    if Enrollment.objects.filter(student=student).exists():
        return False, "Student is already enrolled. Each student can be enrolled only once."
    return True, ""


# --- Institute-personalised email + portal credentials -----------------

def institute_email_domain(institute) -> str:
    """Pick the email domain configured on the Institute, falling back to
    `<code>.in` lowercased so a missing master value still produces a
    usable address."""
    return (institute.email_domain or "").strip() \
        or f"{(institute.code or 'institute').lower()}.in"


def _institute_local_part(student: Student) -> str:
    """`firstname.lastname` flavoured local-part. Strips diacritics, keeps
    letters and digits, lowercased. Falls back to the application form id
    when the name produces nothing usable."""
    raw = (student.student_name or "").strip().lower()
    parts = [re.sub(r"[^a-z0-9]+", "", p) for p in raw.split()]
    parts = [p for p in parts if p]
    if parts:
        local = ".".join(parts[:2]) if len(parts) >= 2 else parts[0]
    else:
        local = re.sub(r"[^a-z0-9]+", "", student.application_form_id.lower())
    return local or "student"


def _ensure_unique_username(seed: str, *, exclude_pk: int | None = None) -> str:
    """Like `_unique_username` but also leaves an existing username alone
    if it belongs to the user we're about to update (no churn on reset)."""
    base = re.sub(r"[^a-z0-9._]+", "", (seed or "student").lower())[:64] or "student"
    candidate = base
    n = 1
    while True:
        qs = User.objects.filter(username__iexact=candidate)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
        if not qs.exists():
            return candidate
        n += 1
        candidate = f"{base}{n}"


@transaction.atomic
def provision_student_portal_credentials(*, student: Student) -> dict:
    """Create (or rotate) the student's portal user, set the institute
    email, and return `{ username, email, temporary_password }`.

    Idempotent:
      - First call → creates the User, populates `student.institute_email`,
        generates a temp password.
      - Subsequent calls → reuse the existing `user_account` and rotate
        the password. `institute_email` is left alone unless empty.

    The returned dict is plain so the view can hand it to the email
    template *and* return it to staff once.
    """
    institute = student.institute
    if institute is None:
        raise ValueError(
            "Student has no institute set — fix the record before issuing "
            "portal credentials.",
        )

    domain = institute_email_domain(institute)
    if not student.institute_email:
        local = _institute_local_part(student)
        email = f"{local}@{domain}"
        # Guard against another student already owning the same address.
        suffix = 2
        while Student.objects.filter(
            institute_email__iexact=email,
        ).exclude(pk=student.pk).exists():
            email = f"{local}{suffix}@{domain}"
            suffix += 1
        student.institute_email = email

    temp_password = secrets.token_urlsafe(10)
    if student.user_account_id is None:
        username = _ensure_unique_username(student.institute_email)
        user = User.objects.create_user(
            username=username,
            email=student.institute_email,
            full_name=student.student_name,
            password=temp_password,
        )
        if student.campus_id:
            user.campuses.add(student.campus)
        student.user_account = user
    else:
        user = student.user_account
        user.set_password(temp_password)
        # Keep the user's primary email + display name aligned with the
        # latest institute email and student name.
        user.email = student.institute_email
        user.full_name = student.student_name
        user.save(update_fields=["password", "email", "full_name"])

    # Mirror the plaintext so staff can re-share it without forcing a
    # rotation. See model field doc for the trade-off.
    student.portal_temp_password = temp_password
    student.save(update_fields=[
        "institute_email", "user_account", "portal_temp_password",
    ])

    return {
        "username": user.username,
        "email": student.institute_email,
        "temporary_password": temp_password,
    }
