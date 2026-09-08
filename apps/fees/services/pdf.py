"""Receipt PDF renderer (fpdf2). Pure Python — works on PA free.

Lays out the invoice finance hands to students: institute letterhead
(logo + billing address + GSTIN, all off `Institute`), the student
block, a one-row payment table, the amount in words, and — on page 2 —
the program policies the student signs against.

The tax columns (Basic Fee / SGST / CGST / IGST) only appear when the
receipt actually carries tax. A JD School of Design receipt against the
trust's GSTIN prints a single "Fee Paid" column; a JD Institute receipt
prints the split. That is data-driven, not institute-driven — a
zero-tax receipt anywhere gets the narrow table.

Rendered on demand; we don't store the file. Re-render gives the same
output (status flag included, so cancelled receipts watermark clearly).
"""

from decimal import Decimal

from django.utils import timezone
from fpdf import FPDF

from apps.common.pdf_theme import (
    BODY_W as _BODY_W,
    MARGIN as _MARGIN,
    PAGE_W as _PAGE_W,
    draw_letterhead_block,
    draw_logo,
    draw_policy_page,
    fit as _fit,
    rule as _rule,
    safe as _safe,
)
from apps.common.program_policies import policy_for


def _amount_str(v) -> str:
    """`65000/-` when whole, `65000.50/-` otherwise — the notation on the
    paper receipts."""
    d = Decimal(v or 0)
    if d == d.to_integral_value():
        return f"{int(d)}/-"
    return f"{d:.2f}/-"


def _plain(v) -> str:
    """Tax/basic cells print bare, no currency mark — as on the samples."""
    d = Decimal(v or 0)
    return f"{int(d)}" if d == d.to_integral_value() else f"{d:.2f}"


# --- Amount in words ---------------------------------------------------

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
         "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
         "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy",
         "Eighty", "Ninety"]


def _under_thousand(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return (_TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else "")).strip()
    return (f"{_ONES[n // 100]} Hundred"
            + (f" {_under_thousand(n % 100)}" if n % 100 else ""))


def _indian_words(n: int) -> str:
    """Indian numbering: crore / lakh / thousand."""
    if n == 0:
        return "Zero"
    parts: list[str] = []
    for divisor, label in ((10_000_000, "Crore"), (100_000, "Lakh"),
                           (1_000, "Thousand")):
        if n >= divisor:
            parts.append(f"{_indian_words(n // divisor)} {label}"
                         if divisor == 10_000_000
                         else f"{_under_thousand(n // divisor)} {label}")
            n %= divisor
    if n:
        parts.append(_under_thousand(n))
    return " ".join(p for p in parts if p)


def amount_in_words(value) -> str:
    """`Sixty Five Thousand Rupees Only/-`, paise included when non-zero."""
    d = Decimal(value or 0).quantize(Decimal("0.01"))
    rupees = int(d)
    paise = int((d - rupees) * 100)
    words = f"{_indian_words(rupees)} Rupees"
    if paise:
        words += f" and {_indian_words(paise)} Paise"
    return f"{words} Only/-"


# --- Small drawing helpers ---------------------------------------------

def _label_value(pdf: FPDF, label: str, value: str, *,
                 bullet: bool = True, line_h: float = 5.0) -> None:
    """`• Label : value` with the label bold, wrapping the value across
    lines at the body width (addresses run long).

    The bullet is drawn as a filled dot rather than typed: Helvetica's
    built-in encoding is Latin-1 and has no U+2022.
    """
    indent = 6.0 if bullet else 0.0
    if bullet:
        pdf.set_fill_color(0, 0, 0)
        pdf.ellipse(_MARGIN + 2, pdf.get_y() + line_h / 2 - 0.6, 1.2, 1.2,
                    style="F")
    pdf.set_x(_MARGIN + indent)
    pdf.set_font("Helvetica", "B", 9)
    lead_w = pdf.get_string_width(label) + 1
    pdf.cell(lead_w, line_h, _safe(label))
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(_BODY_W - indent - lead_w, line_h, _safe(value),
                   new_x="LMARGIN", new_y="NEXT")


# --- Header ------------------------------------------------------------

def _draw_letterhead(pdf: FPDF, institute) -> None:
    """Logo top-left, billing block top-right."""
    top = 12.0
    logo_bottom = draw_logo(pdf, institute, x=_MARGIN, y=top, height=16)
    text_bottom = draw_letterhead_block(
        pdf, institute, x=_PAGE_W - _MARGIN - 90, y=top,
    )
    pdf.set_y(max(logo_bottom, text_bottom) + 4)


# --- Payment table -----------------------------------------------------

def _tax_columns(receipt) -> list[tuple[str, Decimal]]:
    """Only the taxes actually charged, labelled with their rate where it
    can be derived from the basic fee (`SGST (9%)`)."""
    basic = Decimal(receipt.basic_fee or 0)
    out = []
    for label, amount in (("SGST", receipt.sgst), ("CGST", receipt.cgst),
                          ("IGST", receipt.igst)):
        amount = Decimal(amount or 0)
        if not amount:
            continue
        if basic:
            rate = (amount / basic * 100).quantize(Decimal("0.1"))
            rate_s = f"{int(rate)}" if rate == rate.to_integral_value() else f"{rate}"
            # Two lines: the rate sits under the tax name so a 15mm
            # column doesn't have to swallow "SGST (9%)" in one go.
            label = f"{label}\n({rate_s}%)"
        out.append((label, amount))
    return out


def _particular(receipt) -> str:
    if receipt.other_fee_id:
        return receipt.other_fee.name
    if receipt.installment_id:
        return receipt.installment.description or "Fee"
    return "Fee"


def _mode_label(receipt) -> str:
    """"Online", not "Online (card / netbanking)" — the parenthetical is
    there to help the cashier pick the right mode, and never fits the
    column."""
    return receipt.get_payment_mode_display().split(" (")[0]


def _draw_payment_table(pdf: FPDF, receipt) -> None:
    taxes = _tax_columns(receipt)

    ref_date = (receipt.received_date.strftime("%d-%m-%Y")
                if receipt.received_date else "")
    base = [
        ("Sl. No", "1", "C"),
        ("Particular", _particular(receipt), "L"),
        ("Mode", _mode_label(receipt), "L"),
        ("Ref. No.", receipt.instrument_ref, "L"),
        ("Ref. Date", ref_date, "C"),
        ("Bank &\nBranch", receipt.bank, "L"),
    ]
    if taxes:
        # Tight layout: the split has to fit four money columns.
        base_w = [10.0, 22.0, 15.0, 32.0, 19.0, 20.0]
        money_n = len(taxes) + 2  # basic fee + taxes + fee paid
        money_w = [(_BODY_W - sum(base_w)) / money_n] * money_n
        money = ([("Basic\nFee", _plain(receipt.basic_fee), "R")]
                 + [(label, _plain(amount), "R") for label, amount in taxes]
                 + [("Fee\nPaid", _amount_str(receipt.amount), "R")])
    else:
        base_w = [14.0, 30.0, 20.0, 40.0, 24.0, 30.0]
        money_w = [_BODY_W - sum(base_w)]
        money = [("Fee Paid", _amount_str(receipt.amount), "R")]

    cols = base + money
    widths = base_w + money_w

    # Header — 9mm tall, labels centred vertically, wrapping at the "\n"
    # the narrow columns need.
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_fill_color(245, 245, 245)
    head_h = 9.0
    x0, y0 = pdf.get_x(), pdf.get_y()
    x = x0
    for (label, _v, _a), w in zip(cols, widths):
        pdf.set_xy(x, y0)
        pdf.cell(w, head_h, "", border=1, fill=True)
        lines = label.split("\n")
        y = y0 + (head_h - len(lines) * 3.2) / 2
        for line in lines:
            pdf.set_xy(x, y)
            pdf.cell(w, 3.2, _fit(pdf, line, w), align="C")
            y += 3.2
        x += w
    pdf.set_xy(x0, y0 + head_h)

    pdf.set_font("Helvetica", "", 8)
    for (_label, value, align), w in zip(cols, widths):
        pdf.cell(w, 8, _fit(pdf, value, w), border=1, align=align)
    pdf.ln(8)


# --- Page 1 ------------------------------------------------------------

def _draw_receipt_page(pdf: FPDF, receipt) -> None:
    enrollment = receipt.enrollment
    student = enrollment.student
    institute = student.institute

    _draw_letterhead(pdf, institute)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "INVOICE", align="C", new_x="LMARGIN", new_y="NEXT")
    _rule(pdf)

    # Two different dates, as on the paper receipts: this line is when
    # the invoice was raised, while the table's "Ref. Date" is when the
    # money was received.
    issued_at = timezone.localtime(receipt.created_on) if receipt.created_on else None
    if issued_at:
        date_s = issued_at.strftime("%d-%m-%Y %H:%M:%S")
    elif receipt.received_date:
        date_s = receipt.received_date.strftime("%d-%m-%Y")
    else:
        date_s = ""

    pdf.set_font("Helvetica", "B", 9)
    label_w = pdf.get_string_width("Date: ") + 1
    pdf.cell(label_w, 5, "Date: ")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _safe(date_s), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, _safe(f"Receipt No: {receipt.receipt_no}"), align="R",
             new_x="LMARGIN", new_y="NEXT")
    _rule(pdf)

    year = enrollment.academic_year
    course = enrollment.course.name if enrollment.course_id else enrollment.program.name
    # City / state / pincode are each optional on a Student, so they are
    # assembled independently — a missing state must not take the
    # pincode down with it.
    address = ", ".join(p for p in [
        (student.current_address or "").strip().replace("\n", ", "),
        student.current_city.name if student.current_city_id else "",
        student.current_state.name if student.current_state_id else "",
    ] if p)
    if student.current_pincode:
        address = f"{address} -{student.current_pincode}".strip()

    rows = [
        ("Student ID : ", student.registration_number or student.application_form_id),
        ("Academic Year : ", (year.full_name or year.code) if year else ""),
        ("Address : ", address),
        ("Phone : ", student.student_mobile),
        ("Course Name : ", course),
        ("Student Name : ", student.student_name),
        ("Father's Name : ", student.father_name),
    ]
    for label, value in rows:
        if value:
            _label_value(pdf, label, value)

    pdf.ln(3)
    _draw_payment_table(pdf, receipt)
    pdf.ln(3)

    _label_value(pdf, "Amount in words : ", amount_in_words(receipt.amount))
    issued_by = ""
    if receipt.received_by_id:
        issued_by = receipt.received_by.full_name or receipt.received_by.username
    if issued_by:
        _label_value(pdf, "Issued By : ", issued_by)

    if receipt.status == receipt.Status.CANCELLED:
        pdf.ln(3)
        pdf.set_text_color(200, 0, 0)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, "CANCELLED", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        when = (receipt.cancelled_on.strftime("%d-%m-%Y")
                if receipt.cancelled_on else "")
        detail = receipt.cancellation_reason or ""
        if when:
            detail = f"{detail} (cancelled {when})" if detail else f"Cancelled {when}"
        pdf.multi_cell(_BODY_W, 5, _safe(detail), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    pdf.ln(4)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _safe("Cheque/Demand Draft to be made in favor of "
                         f"{institute.cheque_payee}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "All Invoices required to be produced by student whenever "
                   "asked for by the institute authorities.",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "FEES ONCE PAID ARE NOT REFUNDABLE/TRANSFERABLE UNDER ANY "
                   "CIRCUMSTANCES", new_x="LMARGIN", new_y="NEXT")
    _rule(pdf)

    if receipt.status == receipt.Status.CANCELLED:
        _draw_cancelled_watermark(pdf)


def _draw_cancelled_watermark(pdf: FPDF) -> None:
    """Diagonal-free but unmissable: large red text across the middle of
    the page, drawn last so it sits over the invoice body."""
    pdf.set_text_color(220, 0, 0)
    pdf.set_font("Helvetica", "B", 54)
    pdf.set_xy(_MARGIN, 120)
    pdf.cell(_BODY_W, 24, "CANCELLED", align="C")
    pdf.set_text_color(0, 0, 0)


# --- Entry point -------------------------------------------------------

def render_receipt_pdf(receipt) -> bytes:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(_MARGIN, 12, _MARGIN)
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()

    _draw_receipt_page(pdf, receipt)

    program = receipt.enrollment.program
    draw_policy_page(pdf, policy_for(program.degree_type if program else None))

    out = pdf.output(dest="S")  # bytearray in fpdf2
    return bytes(out)
