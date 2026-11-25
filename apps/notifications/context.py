"""Context builders for system e-mails — the ONE place a Student, Lead,
Employee, Enrollment, receipt or user is turned into template variables.

Every builder returns `{{Canonical_Name}}` keys from the sets declared
in `apps.notifications.registry` (STUDENT_VARS, PROGRAM_VARS…), plus
the routing keys the dispatcher reads but templates never see
(`campus_code`, `institute_code`, `reply_to`). Callers merge builders
with `**` and add the trigger-specific variables on top.

Values are always strings (empty, never None), already formatted the
way the client reads them: dates `dd-mm-yyyy`, money `25,000.00`,
durations "3 years".
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import escape

from django.utils import timezone


# --- Formatting helpers ---------------------------------------------------

def fmt_date(value, pattern: str = "%d-%m-%Y") -> str:
    if not value:
        return ""
    if hasattr(value, "tzinfo") and getattr(value, "tzinfo", None) is not None:
        value = timezone.localtime(value)
    try:
        return value.strftime(pattern)
    except (AttributeError, ValueError):
        return str(value)


def fmt_money(value) -> str:
    """`25000` → "25,000.00" (two decimals, Indian comma grouping is not
    attempted — the receipts use the same plain grouping)."""
    if value in (None, ""):
        return ""
    try:
        return f"{Decimal(value):,.2f}"
    except (InvalidOperation, TypeError, ValueError):
        return str(value)


def fmt_duration(months) -> str:
    """Whole years read better than months ("1 year", "3 years"); a
    length that is not a clean multiple stays in months."""
    if not months:
        return ""
    try:
        months = int(months)
    except (TypeError, ValueError):
        return str(months)
    if months % 12 == 0:
        years = months // 12
        return f"{years} year" if years == 1 else f"{years} years"
    return f"{months} months"


def first_name(full_name: str) -> str:
    parts = (full_name or "").split()
    return parts[0] if parts else (full_name or "")


def lines_to_html(text: str) -> str:
    """Multi-line address → `<br>`-joined, HTML-escaped."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return "<br>".join(escape(ln) for ln in lines)


def _s(value) -> str:
    return "" if value is None else str(value)


def _name_of(obj) -> str:
    return _s(getattr(obj, "name", "")) if obj is not None else ""


# --- Institute / campus (the common set) ----------------------------------

def institute_vars(institute, *, request=None) -> dict:
    """Institute_* for the common set + the `institute_code` routing key.
    Safe with None (blank strings)."""
    if institute is None:
        return {"institute_code": ""}
    logo = getattr(institute, "logo", None)
    logo_url = ""
    if logo:
        try:
            logo_url = _absolute_media_url(logo.url, request)
        except (ValueError, AttributeError):
            logo_url = ""
    return {
        "Institute_Name": _s(getattr(institute, "name", "")),
        "Institute_Short_Name": _s(getattr(institute, "code", "")),
        "Institute_Logo_Url": logo_url,
        "Institute_Address": lines_to_html(getattr(institute, "address", "")),
        "Institute_Phone": _s(getattr(institute, "phone", "")),
        "Institute_Email": _s(getattr(institute, "email", "")),
        "institute_code": _s(getattr(institute, "code", "")),
    }


def campus_vars(campus) -> dict:
    """Campus_* + the `campus_code` routing key (Reply-To / CC inboxes)."""
    if campus is None:
        return {"campus_code": ""}
    return {
        "Campus_Name": _s(getattr(campus, "name", "")),
        "Campus_Address": lines_to_html(getattr(campus, "address", "")),
        "Campus_Phone": _s(getattr(campus, "phone", "")),
        "campus_code": _s(getattr(campus, "code", "")),
    }


def _absolute_media_url(url: str, request=None) -> str:
    """Media URLs must be absolute inside an e-mail. The request wins;
    otherwise the API's public origin, else the path as-is."""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    if request is not None:
        return request.build_absolute_uri(url)
    from django.conf import settings

    base = (getattr(settings, "SMARTGATEWAY_PUBLIC_BASE_URL", "") or "").rstrip("/")
    return f"{base}{url}" if base else url


# --- Program / course / enrolment ----------------------------------------

def program_vars(program, *, course=None, enrollment=None, academic_year=None) -> dict:
    """Program_* / Course_* / Degree / University / Academic_Year / Batch /
    Semester. Pass the enrollment when there is one so the batch and
    semester fill in."""
    course = course if course is not None else getattr(enrollment, "course", None)
    academic_year = (
        academic_year if academic_year is not None
        else getattr(enrollment, "academic_year", None)
    )
    degree = getattr(program, "degree", None) if program is not None else None
    university = getattr(program, "university", None) if program is not None else None
    program_name = _name_of(program)
    course_name = _name_of(course) or program_name
    ay = ""
    if academic_year is not None:
        ay = _s(getattr(academic_year, "full_name", "") or getattr(academic_year, "code", ""))
    return {
        "Program_Name": program_name,
        "Program_Code": _s(getattr(program, "code", "")) if program is not None else "",
        "Program_Duration": fmt_duration(getattr(program, "duration_months", None)) if program is not None else "",
        "Course_Name": course_name,
        "Course_Duration": fmt_duration(
            getattr(course, "duration_months", None)
            or (getattr(program, "duration_months", None) if program is not None else None),
        ),
        "Degree_Name": _name_of(degree),
        "University_Name": _name_of(university),
        "Academic_Year": ay,
        "Batch_Name": _name_of(getattr(enrollment, "batch", None)),
        "Semester_Name": _name_of(getattr(enrollment, "semester", None)),
    }


# --- Student / parents ----------------------------------------------------

def student_vars(student, *, enrollment=None, request=None) -> dict:
    """Everything about a Student: STUDENT_VARS + PROGRAM_VARS + the
    common institute/campus set. `enrollment` (current one) refines the
    program, course, batch and semester; without it the student's own
    program/course/academic year are used."""
    if student is None:
        return {}
    enrollment = enrollment if enrollment is not None else _current_enrollment(student)
    program = getattr(enrollment, "program", None) or getattr(student, "program", None)
    course = getattr(enrollment, "course", None) or getattr(student, "course", None)
    campus = getattr(enrollment, "campus", None) or getattr(student, "campus", None)
    academic_year = (
        getattr(enrollment, "academic_year", None)
        or getattr(student, "academic_year", None)
    )
    father = _s(getattr(student, "father_name", ""))
    mother = _s(getattr(student, "mother_name", ""))
    name = _s(getattr(student, "student_name", ""))
    return {
        **institute_vars(getattr(student, "institute", None), request=request),
        **campus_vars(campus),
        **program_vars(program, course=course, enrollment=enrollment,
                       academic_year=academic_year),
        "Student_Name": name,
        "First_Name": first_name(name),
        "Student_Email": _s(getattr(student, "student_email", "")),
        "Student_Phone": _s(getattr(student, "student_mobile", "")),
        "Application_ID": _s(getattr(student, "application_form_id", "")),
        "Registration_No": _s(getattr(student, "registration_number", "")),
        "Father_Name": father,
        "Mother_Name": mother,
        "Parent_Name": father or mother,
        "Father_Email": _s(getattr(student, "father_email", "")),
        "Mother_Email": _s(getattr(student, "mother_email", "")),
        "Father_Phone": _s(getattr(student, "father_mobile", "")),
        "Mother_Phone": _s(getattr(student, "mother_mobile", "")),
    }


def _current_enrollment(student):
    try:
        from apps.admissions.services import current_enrollment

        return current_enrollment(student)
    except Exception:  # noqa: BLE001 — a missing enrolment is fine
        return None


def enrollment_vars(enrollment, *, request=None) -> dict:
    """Student vars scoped to THIS enrolment (fee mails, undertaking)."""
    if enrollment is None:
        return {}
    return student_vars(getattr(enrollment, "student", None),
                        enrollment=enrollment, request=request)


# --- Lead -----------------------------------------------------------------

def lead_vars(lead, *, request=None) -> dict:
    """LEAD_VARS + common set + the Reply-To routing for lead mail (the
    assigned counsellor, with the campus code for the inbox fallback)."""
    if lead is None:
        return {}
    program = getattr(lead, "program", None) if getattr(lead, "program_id", None) else None
    campus = getattr(lead, "campus", None) if getattr(lead, "campus_id", None) else None
    counsellor = getattr(lead, "assign_to", None)
    institute = getattr(program, "institute", None) if program is not None else None
    name = _s(getattr(lead, "name", ""))
    counsellor_email = _s(getattr(counsellor, "email", "")).strip()
    return {
        **institute_vars(institute, request=request),
        **campus_vars(campus),
        "Student_Name": name,
        "First_Name": first_name(name),
        "Lead_Email": _s(getattr(lead, "email", "")),
        "Lead_Phone": _s(getattr(lead, "phone", "")),
        "Course_Name": _name_of(program),
        "Program_Name": _name_of(program),
        "Program_Duration": fmt_duration(getattr(program, "duration_months", None)) if program is not None else "",
        "Counsellor_Name": _s(
            getattr(counsellor, "full_name", "") or getattr(counsellor, "username", ""),
        ) if counsellor is not None else "",
        "Counsellor_Email": counsellor_email,
        "Lead_Source": _name_of(getattr(lead, "source", None)),
        "reply_to": counsellor_email,
    }


# --- Employee / user ------------------------------------------------------

def employee_vars(employee, *, request=None) -> dict:
    if employee is None:
        return {}
    manager = getattr(employee, "reporting_manager_1", None)
    return {
        **institute_vars(getattr(employee, "institute", None), request=request),
        **campus_vars(getattr(employee, "campus", None)),
        "Employee_Name": _s(getattr(employee, "full_name", "")),
        "Employee_Code": _s(getattr(employee, "emp_code", "")),
        "Employee_Email": _s(getattr(employee, "email_primary", "")),
        "Designation": _name_of(getattr(employee, "designation", None)),
        "Department": _name_of(getattr(employee, "department", None)),
        "Date_Of_Joining": fmt_date(getattr(employee, "date_of_joining", None), "%d %b %Y"),
        "Manager_Name": _s(getattr(manager, "full_name", "")) if manager is not None else "",
        "Manager_Email": _s(getattr(manager, "email_primary", "")) if manager is not None else "",
    }


def user_vars(user) -> dict:
    if user is None:
        return {}
    return {
        "User_Name": _s(getattr(user, "full_name", "") or getattr(user, "username", "")),
        "Username": _s(getattr(user, "username", "")),
        "User_Email": _s(getattr(user, "email", "")),
    }


# --- Receipts -------------------------------------------------------------

def receipt_vars(receipt, *, particular: str = "") -> dict:
    """RECEIPT_VARS from a FeeReceipt or any duck-typed receipt (the
    applicant / application-fee stand-ins expose the same attributes)."""
    if receipt is None:
        return {}
    if not particular:
        particular = _receipt_particular(receipt)
    mode = ""
    get_mode = getattr(receipt, "get_payment_mode_display", None)
    if callable(get_mode):
        try:
            mode = _s(get_mode())
        except Exception:  # noqa: BLE001
            mode = ""
    return {
        "Receipt_No": _s(getattr(receipt, "receipt_no", "")),
        "Amount": fmt_money(getattr(receipt, "amount", None)),
        "Particular": particular,
        "Receipt_Date": fmt_date(getattr(receipt, "received_date", None)),
        "Payment_Mode": mode,
    }


def _receipt_particular(receipt) -> str:
    explicit = getattr(receipt, "particular", "")
    if explicit and not getattr(receipt, "installment_id", None) \
            and not getattr(receipt, "other_fee_id", None):
        return _s(explicit)
    if getattr(receipt, "installment_id", None):
        desc = _s(getattr(getattr(receipt, "installment", None), "description", ""))
        if desc:
            return desc
    if getattr(receipt, "other_fee_id", None):
        return _name_of(getattr(receipt, "other_fee", None))
    return _s(explicit) or "Fee payment"


# --- Today ----------------------------------------------------------------

def today_vars() -> dict:
    now = timezone.localtime()
    return {"Today": now.strftime("%d-%m-%Y"), "Current_Year": str(now.year)}
