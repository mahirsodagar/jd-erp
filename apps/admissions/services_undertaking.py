"""Undertaking generation + delivery.

The undertaking is a signed declaration the student agrees to: course,
duration, fee, down-payment + installment schedule, plus any free-text
remarks. PHP source of truth is `JD_ERP/admissions/save.php` lines
2336-2864 (the `feeapplicableunder` POST branch).

Concretely:

- Down payment = first installment (sequence=1) with description
  starting "Down payment" — that's how the React enrollment-create form
  lays it down via `/api/fees/installments/bulk/`.
- Installments = remaining sequences ordered by `sequence`.
- Concession = sum of APPROVED concessions on the enrollment.
- Total fee = sum of installments + concession (matches the PHP rule
  `down_payment + Σ installments + concession = total_fee` enforced by
  the enrollment-create page client-side).

We render to PDF with fpdf2 (same dependency the receipts service uses)
and dispatch via the notifications email helper. The PDF is NOT
persisted — re-rendering is idempotent because the source data is in
the DB.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import Sum
from django.utils import timezone
from fpdf import FPDF

from apps.fees.models import Concession, Installment

from .models import Enrollment


# --- PDF rendering -----------------------------------------------------

_UNICODE_FALLBACKS = {
    "–": "-",
    "—": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
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


def _money(v) -> str:
    return f"INR {Decimal(v or 0):,.2f}"


def _row(pdf: FPDF, label: str, value: str) -> None:
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(60, 7, _safe(label), border=1)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, _safe(value), border=1, new_x="LMARGIN", new_y="NEXT")


def render_undertaking_pdf(
    enrollment: Enrollment,
    *,
    remarks: str = "",
    application_form: str = "",
    submitted_by: str = "",
) -> bytes:
    student = enrollment.student
    campus = enrollment.campus
    program = enrollment.program
    course = enrollment.course
    institute = student.institute

    installments = list(
        Installment.objects.filter(enrollment=enrollment).order_by("sequence")
    )
    # Down payment = sequence 1, by the convention set in the React
    # enrollment-create form. If absent, leave blank — PDF still renders.
    down_payment = next(
        (i for i in installments if i.sequence == 1
         and i.description.lower().startswith("down payment")),
        None,
    )
    if down_payment is None and installments:
        # Fall back to lowest-sequence row as the down payment.
        down_payment = installments[0]

    other_installments = [i for i in installments if i is not down_payment]

    concession_total = Decimal(
        Concession.objects.filter(
            enrollment=enrollment, status=Concession.Status.APPROVED,
        ).aggregate(s=Sum("amount"))["s"] or 0
    )

    installments_total = sum(
        (Decimal(i.amount) for i in installments), Decimal("0")
    )
    total_fee = installments_total + concession_total

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Header band
    pdf.set_fill_color(20, 60, 120)
    pdf.set_draw_color(20, 60, 120)
    pdf.rect(0, 0, 210, 22, style="F")
    pdf.set_y(6)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, _safe(getattr(institute, "name", "") or "Undertaking"),
             align="C")

    # Title
    pdf.set_y(28)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Fee Undertaking", align="C")

    # Top meta
    pdf.set_xy(15, 42)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6,
             _safe(f"Date: {timezone.now().strftime('%d-%b-%Y %H:%M')}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _safe(f"Campus: {campus.name}"),
             new_x="LMARGIN", new_y="NEXT")

    # Body — single 2-col table modelled on the PHP layout.
    pdf.ln(4)
    pdf.set_x(15)
    _row(pdf, "Course title", course.name if course else program.name)
    duration_months = getattr(program, "duration_months", None)
    _row(pdf, "Duration",
         f"{duration_months} months" if duration_months else "-")
    _row(pdf, "Student name", student.student_name)
    _row(pdf, "Contact number", student.student_mobile or "-")
    _row(pdf, "Tuition fee applicable", _money(total_fee))

    if down_payment is not None:
        _row(pdf, "Registration amount paid", _money(down_payment.amount))
    else:
        _row(pdf, "Registration amount paid", "-")

    balance_due = total_fee - Decimal(
        down_payment.amount if down_payment is not None else 0
    )
    _row(pdf, "Total balance due", _money(balance_due))

    for idx, inst in enumerate(other_installments, start=1):
        date_str = inst.due_date.strftime("%d-%b-%Y") if inst.due_date else "-"
        _row(pdf, f"Balance payment {idx}",
             f"{_money(inst.amount)} · due {date_str}")

    if concession_total > 0:
        _row(pdf, "Concession", _money(concession_total))

    _row(pdf, "Application form",
         application_form or student.application_form_id or "-")
    _row(pdf, "Remarks", remarks or "-")
    _row(pdf, "Submitted by", submitted_by or "-")

    # Acknowledgement line — verbatim from the PHP template.
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(
        0, 5,
        _safe(
            "I hereby agree to follow the above-mentioned payment schedule. "
            "Failing which, I am liable for penalty charges."
        ),
    )

    out = pdf.output(dest="S")
    return bytes(out)


# --- Delivery ----------------------------------------------------------

def send_undertaking(
    enrollment: Enrollment,
    *,
    requested_by,
    remarks: str = "",
    application_form: str = "",
    extra_cc: list[str] | None = None,
) -> dict:
    """Render the PDF and email it to the student with CC to staff.

    Returns a dict suitable for direct JSON response. Raises ValueError
    when the student has no email on file.
    """
    student = enrollment.student
    to_addr = (student.student_email or "").strip()
    if not to_addr:
        raise ValueError("Student has no email address on file.")

    pdf_bytes = render_undertaking_pdf(
        enrollment,
        remarks=remarks,
        application_form=application_form,
        submitted_by=(
            getattr(requested_by, "full_name", "")
            or getattr(requested_by, "username", "")
            or ""
        ),
    )

    cc_list: list[str] = []
    staff_email = (getattr(requested_by, "email", "") or "").strip()
    if staff_email and staff_email.lower() != to_addr.lower():
        cc_list.append(staff_email)
    if extra_cc:
        for raw in extra_cc:
            addr = (raw or "").strip()
            if addr and addr.lower() != to_addr.lower() and addr not in cc_list:
                cc_list.append(addr)

    subject = (
        f"Undertaking - {student.student_name} "
        f"({(enrollment.course.name if enrollment.course else enrollment.program.name)})"
    )
    body = (
        f"Dear {student.student_name},\n\n"
        f"Please find your fee undertaking attached. Reach out to your "
        f"counsellor if anything needs to be corrected.\n\n"
        f"Application ID: {student.application_form_id}\n"
        f"Program: {enrollment.program.name}\n"
        f"Campus: {enrollment.campus.name}\n"
    )

    msg = EmailMessage(
        subject=subject,
        body=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=[to_addr],
        cc=cc_list,
    )
    filename = (
        f"undertaking-{student.application_form_id or enrollment.id}.pdf"
    )
    msg.attach(filename, pdf_bytes, "application/pdf")
    try:
        msg.send(fail_silently=False)
    except Exception as e:
        raise RuntimeError(f"Email delivery failed: {type(e).__name__}: {e}")

    return {
        "sent_to": to_addr,
        "cc": cc_list,
        "sent_at": timezone.now().isoformat(),
        "pdf_bytes": len(pdf_bytes),
    }
