"""Receipt PDF renderer (fpdf2). Pure Python — works on PA free.

Lays out the invoice finance hands to students: institute letterhead
(logo + billing address + GSTIN, all off `Institute`), the student
block, a one-row payment table, the amount in words, and — on page 2 —
the program policies (without the agreement clause or signature boxes,
which only the undertaking carries). Matches the paper receipts issued
in 2026 for both institutes, down to the 4-digit dates.

The tax columns (Basic Fee / SGST / CGST / IGST) only appear when the
receipt actually carries tax. A JD School of Design receipt against the
trust's GSTIN prints a single "Fee Paid" column; a JD Institute receipt
prints the split. That is data-driven, not institute-driven — a
zero-tax receipt anywhere gets the narrow table.

Rendered on demand; we don't store the file. Re-render gives the same
output (status flag included, so cancelled receipts watermark clearly).
"""

from decimal import Decimal
from zoneinfo import ZoneInfo

from fpdf import FPDF

from apps.common.pdf_theme import (
    BODY_W as _BODY_W,
    MARGIN as _MARGIN,
    PAGE_W as _PAGE_W,
    SERIF,
    draw_letterhead_block,
    draw_policy_page,
    fit as _fit,
    logo_path,
    prints_right,
    rule as _rule,
    safe as _safe,
)
from apps.common.program_policies import policy_for

#: Receipts are stamped in Indian time whatever the server runs on
#: (settings.TIME_ZONE is UTC) — the paper ones show the clock on the
#: counter, not Greenwich.
_RECEIPT_TZ = ZoneInfo("Asia/Kolkata")


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

#: The bulleted rows are indented 7mm in from the margin, as on the
#: template; the dash is typed, not drawn.
_ROW_X = _MARGIN + 7.0
_ROW_H = 6.0


def _label_value(pdf: FPDF, label: str, value: str, *,
                 label_w: float = 34.0) -> None:
    """`-  Label : value` with the label bold in a fixed-width column so
    the values line up, and the value wrapping to the right margin
    (addresses run long)."""
    pdf.set_x(_ROW_X)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(label_w, _ROW_H, _safe(f"-  {label} :"))
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, _ROW_H, _safe(value), new_x="LMARGIN", new_y="NEXT")


# --- Header ------------------------------------------------------------

_LOGO_W, _LOGO_H = 42.0, 22.0
# The JD School of Design stationery carries a noticeably larger logo
# than the JD Institute one; its address sits opposite, so the extra
# height costs nothing on the page.
_LOGO_W_RIGHT, _LOGO_H_RIGHT = 58.0, 30.0


def _draw_letterhead(pdf: FPDF, institute) -> None:
    """Logo top-left (42x22mm box on JD Institute, 58x30mm on JD School
    of Design), the billing block underneath it: left-aligned on the JD
    Institute stationery, right-aligned (with a wider gap before the
    title) on the JD School of Design one."""
    top = 12.0
    right = prints_right(institute)
    logo_w, logo_h = (
        (_LOGO_W_RIGHT, _LOGO_H_RIGHT) if right else (_LOGO_W, _LOGO_H)
    )
    logo_bottom = top + logo_h
    if path := logo_path(institute):
        try:
            pdf.image(path, x=_MARGIN, y=top, w=logo_w, h=logo_h,
                      keep_aspect_ratio=True)
        except Exception:  # noqa: BLE001 — a corrupt logo must not 500 the document
            path = None
    if not path:
        # No artwork on file: the institute name stands in for the logo.
        pdf.set_xy(_MARGIN, top)
        pdf.set_font("Helvetica", "B", 13)
        pdf.multi_cell(_BODY_W, 6, _safe(getattr(institute, "name", "")))
        logo_bottom = max(logo_bottom, pdf.get_y())

    text_bottom = draw_letterhead_block(
        pdf, institute, x=_MARGIN, y=logo_bottom + 3, width=_BODY_W,
        align="R" if right else "L", size=9, line_h=5.0, color=(0, 0, 0),
    )
    pdf.set_y(text_bottom + (10 if right else 4))


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
            label = f"{label} ({rate_s}%)"
        out.append((label, amount))
    return out


def _particular(receipt) -> str:
    if receipt.other_fee_id:
        return receipt.other_fee.name
    if receipt.installment_id:
        return receipt.installment.description or "Fee"
    # A pre-enrolment registration receipt names its purpose directly —
    # see fees.services.registration_receipt.
    return getattr(receipt, "particular", "") or "Fee"


def user_display_name(user) -> str:
    """A person's name for a document: the account's full name, else the
    name on the linked Employee record (many staff accounts were created
    with a blank full_name), else the username. Empty only for None."""
    if user is None:
        return ""
    name = (getattr(user, "full_name", "") or "").strip()
    if name:
        return name
    employee = getattr(user, "employee", None)
    if employee is not None:
        name = (getattr(employee, "full_name", "") or "").strip()
        if name:
            return name
    return (getattr(user, "username", "") or "").strip()


def issued_by_label(receipt) -> str:
    """Who the receipt says issued it: the person behind the receipt
    (client request, 2026-11-26) — the cashier who recorded a counter
    payment, or the staff member who sent the payment link that settled
    online. Only when nobody at all is on record (a student paying from
    the public application form) does it fall back to the institute's
    accounts office, so the line is never blank."""
    user = receipt.received_by if getattr(receipt, "received_by_id", None) else None
    name = user_display_name(user)
    if name:
        return name
    institute = None
    try:
        institute = receipt.enrollment.student.institute
    except AttributeError:
        pass
    inst_name = (getattr(institute, "name", "") or "").strip()
    return f"Accounts Office, {inst_name}" if inst_name else "Accounts Office"


def _mode_label(receipt) -> str:
    """"Online", not "Online (card / netbanking)" — the parenthetical is
    there to help the cashier pick the right mode, and never fits the
    column."""
    return receipt.get_payment_mode_display().split(" (")[0]


#: Column widths from the templates (mm). With the tax split the ten
#: columns fill the 180mm body; without it the seven-column table sits
#: left at 144mm, as on the JD School of Design receipt.
_BASE_W = [12.0, 17.0, 14.0, 28.0, 18.0, 22.0]
_MONEY_W_TWO_TAXES = [17.0, 16.0, 16.0, 20.0]
_NO_TAX_W = [12.0, 20.0, 23.0, 21.0, 22.0, 28.0, 18.0]


def _draw_payment_table(pdf: FPDF, receipt) -> None:
    taxes = _tax_columns(receipt)

    ref_date = (receipt.received_date.strftime("%d-%m-%Y")
                if receipt.received_date else "")
    cols = [
        ("Sl. No", "1"),
        ("Particular", _particular(receipt)),
        ("Mode", _mode_label(receipt)),
        ("Ref. No.", receipt.instrument_ref),
        ("Ref. Date", ref_date),
        ("Bank & Branch", receipt.bank),
    ]
    if taxes:
        cols += ([("Basic Fee", _plain(receipt.basic_fee))]
                 + [(label, _plain(amount)) for label, amount in taxes]
                 + [("Fee Paid", _amount_str(receipt.amount))])
        if len(taxes) == 2:
            money_w = _MONEY_W_TWO_TAXES
        else:
            n = len(taxes) + 2
            money_w = [(_BODY_W - sum(_BASE_W)) / n] * n
        widths = _BASE_W + money_w
    else:
        cols.append(("Fee Paid", _amount_str(receipt.amount)))
        widths = _NO_TAX_W

    # Header row: each label wraps inside its column at 6mm per line,
    # and the row is as tall as the tallest label.
    x0, y0 = _MARGIN, pdf.get_y() + 2
    pdf.set_font("Helvetica", "B", 7)
    line_counts = [
        len(pdf.multi_cell(w, 6, _safe(label), dry_run=True, output="LINES"))
        for (label, _v), w in zip(cols, widths)
    ]
    head_h = 6 * max(line_counts)
    bottom = y0 + head_h
    for (label, _v), w, n in zip(cols, widths, line_counts):
        # Every box is drawn at the full header height; the label is
        # centred vertically inside it.
        pdf.rect(x0, y0, w, head_h)
        pdf.set_xy(x0, y0 + (head_h - 6 * n) / 2)
        pdf.multi_cell(w, 6, _safe(label), align="C",
                       new_x="RIGHT", new_y="TOP", max_line_height=6)
        x0 += w

    # Value row: 10mm tall, values left-aligned. A long value (order ids
    # run to 16 characters) wraps onto a second 5mm line inside the row.
    x0, y1 = _MARGIN, bottom
    pdf.set_font("Helvetica", "", 7)
    row_bottom = y1 + 10
    for (_label, value), w in zip(cols, widths):
        pdf.set_xy(x0, y1)
        pdf.multi_cell(w, 10, _safe(value), border=1, align="L",
                       new_x="RIGHT", new_y="TOP", max_line_height=5)
        x0 += w
    pdf.set_y(row_bottom + 4)


# --- Page 1 ------------------------------------------------------------

def _draw_receipt_page(pdf: FPDF, receipt) -> None:
    enrollment = receipt.enrollment
    student = enrollment.student
    institute = student.institute

    _draw_letterhead(pdf, institute)

    pdf.set_font(SERIF, "B", 12)
    pdf.cell(0, 8, "INVOICE", align="C", new_x="LMARGIN", new_y="NEXT")
    _rule(pdf, gap_before=0, gap_after=4)

    # Two different dates, as on the paper receipts: this line is when
    # the invoice was raised, while the table's "Ref. Date" is when the
    # money was received.
    issued_at = (receipt.created_on.astimezone(_RECEIPT_TZ)
                 if receipt.created_on else None)
    if issued_at:
        date_s = issued_at.strftime("%d-%m-%Y %H:%M:%S")
    elif receipt.received_date:
        date_s = receipt.received_date.strftime("%d-%m-%Y")
    else:
        date_s = ""

    # Date on the left and Receipt No on the right of one line.
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(12, 6, "Date:")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(90, 6, _safe(date_s))
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(28, 6, "Receipt No:")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, _safe(receipt.receipt_no), align="R",
             new_x="LMARGIN", new_y="NEXT")
    _rule(pdf, gap_before=1, gap_after=5)

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
        ("Student ID", student.registration_number or student.application_form_id),
        ("Academic Year", (year.full_name or year.code) if year else ""),
        ("Address", address),
        ("Phone", student.student_mobile),
        ("Course Name", course),
        ("Student Name", student.student_name),
        ("Father's Name", student.father_name),
    ]
    label_w = 36.0 if prints_right(institute) else 34.0
    for label, value in rows:
        _label_value(pdf, label, value or "", label_w=label_w)

    _draw_payment_table(pdf, receipt)

    _label_value(pdf, "Amount in words", amount_in_words(receipt.amount),
                 label_w=36)
    _label_value(pdf, "Issued By", issued_by_label(receipt), label_w=25)

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

    pdf.ln(2)
    pdf.set_x(_MARGIN)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.multi_cell(0, 5, _safe("Cheque/Demand Draft to be made in favor of "
                               f"{institute.cheque_payee}"),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 5, "All Invoices required to be produced by student "
                         "whenever asked for by the institute authorities.",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.multi_cell(0, 5, "FEES ONCE PAID ARE NOT REFUNDABLE/TRANSFERABLE "
                         "UNDER ANY CIRCUMSTANCES",
                   new_x="LMARGIN", new_y="NEXT")

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

    # Page 2: the policies alone. The AGREEMENT clause and the signature
    # boxes belong to the undertaking the student signs; the receipt the
    # institute hands over carries neither.
    program = receipt.enrollment.program
    draw_policy_page(
        pdf,
        policy_for(program.degree_type if program else None, agreement=False,
                   institute=receipt.enrollment.student.institute),
        signatures=False,
    )

    out = pdf.output(dest="S")  # bytearray in fpdf2
    return bytes(out)
