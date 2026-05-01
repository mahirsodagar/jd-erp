"""Certificate eligibility, numbering, and PDF rendering.

Per-type rules:
- COMPLETION : enrollment in {COMPLETED, ALUMNI}, every published mark
               passes (>=40 % of total_max).
- PROVISIONAL: enrollment ALUMNI; marks may be unpublished.
- BONAFIDE   : enrollment ACTIVE.
- TRANSFER   : enrollment in {DROPPED, ALUMNI}.
- CHARACTER  : any enrollment.
- NO_DUES    : fee balance is zero.

Override via `academics.certificate.override_eligibility`.
"""

import io
import re
from datetime import datetime
from decimal import Decimal

from django.db.models import Max
from fpdf import FPDF

from apps.admissions.models import Enrollment

from .marks_service import build_transcript
from .models import Certificate, MarksEntry


PASS_PERCENTAGE = 40.0


# --- Eligibility -----------------------------------------------------

def check_eligibility(*, student, enrollment, cert_type: str) -> dict:
    """Returns {ok: bool, reasons: [str]}."""
    reasons: list[str] = []

    if cert_type == Certificate.Type.BONAFIDE:
        if not enrollment or enrollment.status != Enrollment.Status.ACTIVE:
            reasons.append("Bonafide requires an ACTIVE enrollment.")

    elif cert_type == Certificate.Type.PROVISIONAL:
        if not enrollment or enrollment.status != Enrollment.Status.ALUMNI:
            reasons.append("Provisional requires enrollment status ALUMNI.")
        if not MarksEntry.objects.filter(student=student).exists():
            reasons.append("No marks recorded yet.")

    elif cert_type == Certificate.Type.COMPLETION:
        if not enrollment or enrollment.status not in (
            Enrollment.Status.PROMOTED,  # final-semester promote also counts
            Enrollment.Status.ALUMNI,
        ):
            reasons.append(
                "Completion requires enrollment status PROMOTED or ALUMNI."
            )
        marks = MarksEntry.objects.filter(student=student)
        if not marks.exists():
            reasons.append("No marks recorded yet.")
        else:
            unpublished = marks.filter(published=False).count()
            if unpublished:
                reasons.append(
                    f"{unpublished} mark(s) still unpublished."
                )
            failing = []
            for m in marks.filter(published=True):
                if m.percentage < PASS_PERCENTAGE:
                    failing.append(
                        f"{m.subject.code}: {m.percentage}% < {PASS_PERCENTAGE}%"
                    )
            if failing:
                reasons.append(
                    "Subject(s) below pass mark: " + "; ".join(failing)
                )

    elif cert_type == Certificate.Type.TRANSFER:
        if not enrollment or enrollment.status not in (
            Enrollment.Status.DROPPED, Enrollment.Status.ALUMNI,
        ):
            reasons.append(
                "Transfer requires enrollment status DROPPED or ALUMNI."
            )

    elif cert_type == Certificate.Type.CHARACTER:
        if not enrollment:
            reasons.append("Character cert requires an enrollment.")

    elif cert_type == Certificate.Type.NO_DUES:
        # Use the fees balance service.
        try:
            from apps.fees.services.balance import enrollment_balance
        except ImportError:
            reasons.append("Fees module unavailable.")
        else:
            if not enrollment:
                reasons.append("No-dues requires an enrollment.")
            else:
                bal = enrollment_balance(enrollment)
                if Decimal(bal["balance"]) > Decimal("0"):
                    reasons.append(f"Outstanding balance: {bal['balance']}")

    return {"ok": not reasons, "reasons": reasons}


# --- Certificate number ----------------------------------------------

_TYPE_SHORT = {
    Certificate.Type.COMPLETION: "COMP",
    Certificate.Type.PROVISIONAL: "PROV",
    Certificate.Type.BONAFIDE: "BONA",
    Certificate.Type.TRANSFER: "TRAN",
    Certificate.Type.CHARACTER: "CHAR",
    Certificate.Type.NO_DUES: "NODU",
}


def generate_certificate_no(*, cert_type: str, institute_code: str,
                            year: int | None = None) -> str:
    year = year or datetime.now().year
    prefix = f"CERT-{_TYPE_SHORT[cert_type]}-{institute_code.upper()}-{year}-"
    last = Certificate.objects.filter(
        certificate_no__startswith=prefix,
    ).aggregate(m=Max("certificate_no"))["m"]
    if last and (m := re.match(r".+-(\d+)$", last)):
        seq = int(m.group(1)) + 1
    else:
        seq = 1
    return f"{prefix}{seq:05d}"


# --- Snapshot --------------------------------------------------------

def build_snapshot(*, student, enrollment, cert_type: str) -> dict:
    """Frozen at issue time. Used by the PDF renderer."""
    snap = {
        "type": cert_type,
        "student": {
            "id": student.id,
            "name": student.student_name,
            "father_name": student.father_name,
            "mother_name": student.mother_name,
            "application_form_id": student.application_form_id,
            "dob": str(student.dob) if student.dob else "",
        },
        "institute": {
            "name": student.institute.name,
            "code": student.institute.code,
        },
        "campus": {
            "name": student.campus.name,
            "code": student.campus.code,
        },
    }
    if enrollment:
        snap["enrollment"] = {
            "id": enrollment.id,
            "program": enrollment.program.name,
            "batch": enrollment.batch.name,
            "academic_year": enrollment.academic_year.code,
            "status": enrollment.get_status_display(),
            "entry_date": str(enrollment.entry_date) if enrollment.entry_date else "",
        }
    if cert_type in (Certificate.Type.COMPLETION,
                     Certificate.Type.PROVISIONAL):
        only_pub = (cert_type == Certificate.Type.COMPLETION)
        tr = build_transcript(student=student, only_published=only_pub)
        snap["transcript"] = tr
    return snap


# --- PDF rendering ---------------------------------------------------

_UNICODE_FALLBACKS = {
    "–": "-", "—": "-",
    "‘": "'", "’": "'",
    "“": '"', "”": '"',
    "…": "...",
    "₹": "INR ",
}


def _safe(text) -> str:
    if text is None:
        return ""
    s = str(text)
    for k, v in _UNICODE_FALLBACKS.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _new_pdf() -> FPDF:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    return pdf


def _header_band(pdf: FPDF, institute_name: str, title: str):
    pdf.set_fill_color(20, 60, 120)
    pdf.rect(0, 0, 210, 24, style="F")
    pdf.set_y(7)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, _safe(institute_name), align="C")

    pdf.set_y(34)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 12, _safe(title), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def _meta_block(pdf: FPDF, certificate: Certificate):
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(95, 6, _safe(f"Certificate No: {certificate.certificate_no}"))
    issued = certificate.issued_at.strftime("%d-%b-%Y") if certificate.issued_at else ""
    pdf.cell(0, 6, _safe(f"Date of Issue: {issued}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)


def _footer_signatures(pdf: FPDF, *, lines=("HOD", "Director")):
    pdf.ln(28)
    pdf.set_font("Helvetica", "", 11)
    col = 200 / max(len(lines), 1)
    y = pdf.get_y()
    for i, label in enumerate(lines):
        x = 10 + i * col
        pdf.set_xy(x, y)
        pdf.cell(col, 5, "_" * 26, align="C", new_x="LEFT", new_y="NEXT")
        pdf.set_xy(x, y + 7)
        pdf.cell(col, 5, _safe(label), align="C")


def _title_for(cert_type: str) -> str:
    return {
        Certificate.Type.COMPLETION: "Certificate of Completion",
        Certificate.Type.PROVISIONAL: "Provisional Certificate",
        Certificate.Type.BONAFIDE: "Bonafide Certificate",
        Certificate.Type.TRANSFER: "Transfer Certificate",
        Certificate.Type.CHARACTER: "Character Certificate",
        Certificate.Type.NO_DUES: "No Dues Certificate",
    }[cert_type]


def render_certificate_pdf(certificate: Certificate) -> bytes:
    snap = certificate.snapshot or {}
    student = snap.get("student", {})
    enrl = snap.get("enrollment", {})
    institute = snap.get("institute", {}).get("name", "JD Institute")
    title = _title_for(certificate.type)

    pdf = _new_pdf()
    _header_band(pdf, institute, title)
    _meta_block(pdf, certificate)

    body_lines: list[str] = []

    name = student.get("name", "")
    program = enrl.get("program", "")
    batch = enrl.get("batch", "")
    ay = enrl.get("academic_year", "")
    campus_name = snap.get("campus", {}).get("name", "")

    if certificate.type == Certificate.Type.COMPLETION:
        tr = snap.get("transcript", {})
        pct = tr.get("overall", {}).get("percentage", 0)
        body_lines = [
            f"This is to certify that {name} has",
            f"successfully completed the program {program}",
            f"at our {campus_name} campus, batch {batch}",
            f"(academic year {ay}), with an overall percentage of {pct}%.",
        ]

    elif certificate.type == Certificate.Type.PROVISIONAL:
        body_lines = [
            f"This is the provisional certificate confirming that {name}",
            f"has fulfilled the requirements for the program {program}",
            f"at our {campus_name} campus, batch {batch} ({ay}).",
            "The final certificate will be issued in due course.",
        ]

    elif certificate.type == Certificate.Type.BONAFIDE:
        body_lines = [
            f"This is to certify that {name} is a bonafide",
            f"student of the program {program}",
            f"at our {campus_name} campus, batch {batch}",
            f"during the academic year {ay}.",
        ]
        if certificate.purpose:
            body_lines.append(
                f"This certificate is issued for: {certificate.purpose}."
            )

    elif certificate.type == Certificate.Type.TRANSFER:
        body_lines = [
            f"This is to certify that {name} was a student",
            f"of {program} at our {campus_name} campus,",
            f"batch {batch} ({ay}).",
            "Their record at this institute is satisfactory and we",
            "have no objection to their transfer.",
        ]

    elif certificate.type == Certificate.Type.CHARACTER:
        body_lines = [
            f"This is to certify that {name},",
            f"a student of {program} at {campus_name} campus,",
            f"batch {batch} ({ay}), bore good moral character",
            "during their tenure at this institute.",
        ]

    elif certificate.type == Certificate.Type.NO_DUES:
        body_lines = [
            f"This is to certify that {name} has cleared all",
            f"financial dues for {program}",
            f"at {campus_name} campus, batch {batch} ({ay}).",
            "There are no outstanding dues with the institute.",
        ]

    pdf.set_font("Helvetica", "", 13)
    pdf.ln(6)
    for line in body_lines:
        pdf.cell(0, 9, _safe(line), align="C", new_x="LMARGIN", new_y="NEXT")

    if certificate.remarks:
        pdf.ln(6)
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(0, 6, _safe(f"Remarks: {certificate.remarks}"),
                       align="C")
        pdf.set_text_color(0, 0, 0)

    _footer_signatures(pdf)

    out = pdf.output(dest="S")
    return bytes(out)


# --- Graduation flow -------------------------------------------------

def graduate_enrollment(*, enrollment, by_user) -> tuple[Enrollment, "AlumniRecord"]:
    """Move an enrollment to ALUMNI status and create / update the
    AlumniRecord. Idempotent — safe to call twice."""
    from .models import AlumniRecord

    enrollment.status = Enrollment.Status.ALUMNI
    enrollment.save(update_fields=["status", "updated_on"])

    student = enrollment.student
    grad_year = enrollment.academic_year.end_date.year if enrollment.academic_year else datetime.now().year

    # Final percentage from published marks.
    tr = build_transcript(student=student, only_published=True)
    final_pct = Decimal(tr["overall"]["percentage"]) if tr["overall"].get("percentage") else None

    rec, _ = AlumniRecord.objects.update_or_create(
        student=student,
        defaults={
            "graduation_year": grad_year,
            "final_program": enrollment.program,
            "final_batch": enrollment.batch,
            "final_percentage": final_pct,
            "last_known_email": student.student_email,
            "last_known_phone": student.student_mobile,
        },
    )
    return enrollment, rec
