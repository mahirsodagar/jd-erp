"""Undertaking generation + delivery.

The undertaking is a signed declaration the student agrees to: course,
duration, fee, registration + installment schedule, plus any free-text
remarks. PHP source of truth is `JD_ERP/admissions/save.php` lines
2336-2864 (the `feeapplicableunder` POST branch); the printed layout
matches the stationery finance issues today — logo and magenta
UNDERTAKING banner, the fixed label/value table, the letterhead footer,
and the program policies on page 2.

Concretely:

- Registration fee = the `kind=REGISTRATION` installment — the mandatory
  yearly charge. Pulled out first so it prints on its own line and can
  never be mistaken for the down payment.
- Down payment = the remaining installment whose description starts
  "Down payment" — that's how the React enrollment-create form lays it
  down via `/api/fees/installments/bulk/`.
- Installments = the remaining course rows ordered by `sequence`, one
  per BALANCE PAYMENT line.
- Concession = sum of APPROVED concessions on the enrollment.
- Total fee = sum of ALL installments (registration included — it is
  carved out of the total, not added to it) + concession, matching the
  rule `registration + down_payment + Σ installments + concession =
  total_fee` enforced by the enrollment-create page client-side.

Every money row states what was actually paid and when: receipts are
matched to their installment so a paid row reads "Paid on 04/09/2025 -
Online" while an outstanding one reads "to be paid on 18/11/2026". The
application fee comes from the lead's SmartGateway payment request,
which is where that money is recorded.

We render with fpdf2 (same dependency the receipts service uses) and
dispatch via the notifications email helper. The PDF is NOT persisted —
re-rendering is idempotent because the source data is in the DB.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import Sum
from django.utils import timezone
from fpdf import FPDF

from apps.common.pdf_theme import (
    BODY_W,
    BRAND_MAGENTA,
    MARGIN,
    PAGE_W,
    draw_letterhead_block,
    draw_logo,
    draw_policy_page,
    safe as _safe,
)
from apps.common.program_policies import policy_for
from apps.fees.models import Concession, FeeReceipt, Installment

from .models import Enrollment

#: BALANCE PAYMENT rows always printed, even when the schedule is
#: shorter — the paper form has five and staff expect the blanks.
_MIN_BALANCE_ROWS = 5

#: Label column width; the value column takes the rest of the body.
_LABEL_W = 78.0
_ROW_H = 7.0


def _amount(v) -> str:
    """Bare rupee figures, as on the printed form: `175000`, `72500.50`."""
    d = Decimal(v or 0)
    return f"{int(d)}" if d == d.to_integral_value() else f"{d:.2f}"


def _date(value) -> str:
    return value.strftime("%d/%m/%Y") if value else ""


# --- Fee overview ------------------------------------------------------

def _paid_note(receipts) -> str:
    """"Paid on 04/09/2025 - Online" for the receipts against a row.

    Multiple part-payments against one installment are summarised on one
    line — the date and mode of the latest, since that is the one the
    student is being asked to recognise.
    """
    active = [r for r in receipts if r.status != FeeReceipt.Status.CANCELLED]
    if not active:
        return ""
    last = max(active, key=lambda r: (r.received_date, r.id))
    mode = last.get_payment_mode_display().split(" (")[0]
    return f"Paid on {_date(last.received_date)} - {mode}"


def _row_value(installment, receipts_by_installment) -> str:
    """`30000 Paid on 04/09/2025 - Online`, or `72500 to be paid on
    18/11/2026` when the row is still outstanding."""
    amount = _amount(installment.amount)
    note = _paid_note(receipts_by_installment.get(installment.id, []))
    if note:
        return f"{amount} {note}"
    if installment.due_date:
        return f"{amount} to be paid on {_date(installment.due_date)}"
    return amount


def _application_fee_line(student) -> str:
    """The application fee as paid on the lead the student came from.

    Application money is taken through SmartGateway against the *lead*,
    before a Student exists, so it is never a FeeReceipt — see
    `apps.payments`. No lead (a walk-in keyed straight into admissions)
    means no line to print.
    """
    lead = getattr(student, "lead_origin", None)
    if lead is None:
        return ""
    from apps.payments.models import PaymentRequest

    pr = (
        PaymentRequest.objects.filter(
            lead=lead,
            purpose=PaymentRequest.Purpose.APPLICATION_FEE,
            status=PaymentRequest.Status.PAID,
        )
        .select_related("paid_order")
        .order_by("-paid_at")
        .first()
    )
    if pr is None:
        return ""
    line = f"{_amount(pr.amount)} Paid on {_date(timezone.localtime(pr.paid_at)) if pr.paid_at else ''}".strip()
    method = getattr(pr.paid_order, "payment_method", "") if pr.paid_order_id else ""
    return f"{line} - {method}" if method else line


def fee_overview(enrollment: Enrollment) -> dict:
    """Everything the undertaking prints about money, in one dict.

    Split out from the renderer so the numbers can be asserted directly
    in tests and reused by any future preview UI.
    """
    student = enrollment.student
    installments = list(
        Installment.objects.filter(enrollment=enrollment).order_by("sequence")
    )

    receipts_by_installment: dict[int, list] = {}
    for r in FeeReceipt.objects.filter(enrollment=enrollment).exclude(
        installment__isnull=True,
    ):
        receipts_by_installment.setdefault(r.installment_id, []).append(r)

    registration = next(
        (i for i in installments if i.kind == Installment.Kind.REGISTRATION),
        None,
    )
    course_installments = [i for i in installments if i is not registration]

    # "REGISTRATION AMOUNT PAID" on the paper form is the money taken up
    # front. That is the mandatory registration row whenever there is
    # one; only when there isn't does the down payment stand in for it —
    # the row the React enrollment-create form labels as such, falling
    # back to the earliest course row.
    #
    # When both exist, the down payment stays in the BALANCE PAYMENT
    # list: it is a scheduled payment like any other, and printing it
    # there keeps `upfront + Σ balance rows = total fee` true.
    if registration is not None:
        upfront = registration
        balance_rows = course_installments
    else:
        upfront = next(
            (i for i in course_installments
             if i.description.lower().startswith("down payment")),
            course_installments[0] if course_installments else None,
        )
        balance_rows = [i for i in course_installments if i is not upfront]

    concession_total = Decimal(
        Concession.objects.filter(
            enrollment=enrollment, status=Concession.Status.APPROVED,
        ).aggregate(s=Sum("amount"))["s"] or 0
    )
    installments_total = sum(
        (Decimal(i.amount) for i in installments), Decimal("0")
    )
    total_fee = installments_total + concession_total

    upfront_amount = Decimal(upfront.amount) if upfront is not None else Decimal("0")

    return {
        "total_fee": total_fee,
        "concession": concession_total,
        "upfront": upfront,
        "upfront_line": (
            _row_value(upfront, receipts_by_installment) if upfront else ""
        ),
        "balance_due": total_fee - upfront_amount,
        "balance_lines": [
            _row_value(i, receipts_by_installment) for i in balance_rows
        ],
        "application_fee_line": _application_fee_line(student),
    }


# --- PDF rendering -----------------------------------------------------

def _row(pdf: FPDF, label: str, value: str) -> None:
    pdf.set_x(MARGIN)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(_LABEL_W, _ROW_H, f" {_safe(label)}", border=1)
    pdf.cell(BODY_W - _LABEL_W, _ROW_H, f" {_safe(value)}", border=1,
             new_x="LMARGIN", new_y="NEXT")


def _draw_header(pdf: FPDF, institute) -> None:
    """Logo left, magenta UNDERTAKING banner right — the printed form's
    masthead."""
    top = 12.0
    logo_bottom = draw_logo(pdf, institute, x=MARGIN, y=top, height=22,
                            fallback_width=95)

    band_w, band_h = 70.0, 26.0
    band_x = PAGE_W - MARGIN - band_w
    pdf.set_fill_color(*BRAND_MAGENTA)
    pdf.rect(band_x, top, band_w, band_h, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_xy(band_x, top + band_h / 2 - 5)
    pdf.cell(band_w, 10, "UNDERTAKING", align="C")
    pdf.set_text_color(0, 0, 0)

    pdf.set_y(max(logo_bottom, top + band_h) + 8)


def _duration(program, course) -> str:
    """Whole years read better than months on this form ("1 year",
    "2 years"); anything that isn't a clean multiple stays in months."""
    months = getattr(course, "duration_months", None) or getattr(
        program, "duration_months", None,
    )
    if not months:
        return ""
    if months % 12 == 0:
        years = months // 12
        return f"{years} year" if years == 1 else f"{years} years"
    return f"{months} months"


def render_undertaking_pdf(
    enrollment: Enrollment,
    *,
    remarks: str = "",
    submitted_by: str = "",
) -> bytes:
    student = enrollment.student
    program = enrollment.program
    course = enrollment.course
    institute = student.institute
    fees = fee_overview(enrollment)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(MARGIN, 12, MARGIN)
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    _draw_header(pdf, institute)

    pdf.set_font("Helvetica", "B", 9)
    date_w = pdf.get_string_width("Date: ") + 1
    pdf.cell(date_w, 5, "Date: ")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, timezone.localtime().strftime("%d-%m-%Y %H:%M:%S"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    _row(pdf, "COURSE TITLE", course.name if course else program.name)
    _row(pdf, "DURATION", _duration(program, course))
    _row(pdf, "NAME OF THE STUDENT", student.student_name)
    _row(pdf, "CONTACT NUMBER", student.student_mobile)
    # "TUTION" is the label on the printed form; kept verbatim so the
    # generated document matches the one staff already hand out.
    _row(pdf, "TUTION FEE APPLICABLE", _amount(fees["total_fee"]))
    _row(pdf, "REGISTRATION AMOUNT PAID", fees["upfront_line"])
    _row(pdf, "TOTAL BALANCE DUE", _amount(fees["balance_due"]))

    lines = fees["balance_lines"]
    for idx in range(max(_MIN_BALANCE_ROWS, len(lines))):
        _row(pdf, f"BALANCE PAYMENT {idx + 1}",
             lines[idx] if idx < len(lines) else "")

    if fees["concession"] > 0:
        _row(pdf, "CONCESSION", _amount(fees["concession"]))

    _row(pdf, "Application Form", fees["application_fee_line"])
    _row(pdf, "REMARKS:", remarks)

    # Full-width acknowledgement row — verbatim from the printed form.
    pdf.set_x(MARGIN)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(BODY_W, _ROW_H,
             " I hereby follow the above-mentioned payment schedule and "
             "falling which, I am liable for penalty charges.",
             border=1, new_x="LMARGIN", new_y="NEXT")

    _row(pdf, "SUBMITTED BY", submitted_by)

    # Letterhead sits at the foot of this document, not the head.
    pdf.ln(4)
    draw_letterhead_block(pdf, institute, x=MARGIN, y=pdf.get_y(),
                          width=BODY_W, align="L", size=9)

    draw_policy_page(pdf, policy_for(getattr(program, "degree_type", "")))

    out = pdf.output(dest="S")
    return bytes(out)


# --- Delivery ----------------------------------------------------------

def send_undertaking(
    enrollment: Enrollment,
    *,
    requested_by,
    remarks: str = "",
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
