"""Receipt PDF renderer (fpdf2). Pure Python — works on PA free.

Receipt is rendered on demand; we don't store the file. Re-render gives
the same output (status flag included, so cancelled receipts watermark
clearly)."""

import io
from decimal import Decimal

from fpdf import FPDF


_UNICODE_FALLBACKS = {
    "–": "-",   # en dash
    "—": "-",   # em dash
    "‘": "'",   # left single quote
    "’": "'",   # right single quote
    "“": '"',   # left double quote
    "”": '"',   # right double quote
    "…": "...", # ellipsis
    "₹": "INR ",  # rupee sign — fpdf2 built-in fonts are Latin-1
}


def _safe(text) -> str:
    """Coerce arbitrary user-supplied strings to Latin-1 by replacing
    common Unicode punctuation. fpdf2's built-in Helvetica is Latin-1
    only; for full Unicode we'd need to ship a TTF."""
    if text is None:
        return ""
    s = str(text)
    for k, v in _UNICODE_FALLBACKS.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _money(v) -> str:
    return f"INR {Decimal(v):,.2f}"


def render_receipt_pdf(receipt) -> bytes:
    enrollment = receipt.enrollment
    student = enrollment.student
    campus = enrollment.campus
    institute = student.institute

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
    pdf.cell(0, 10, _safe(institute.name), align="C")

    # Title
    pdf.set_y(28)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Fee Receipt", align="C")

    if receipt.status == receipt.Status.CANCELLED:
        # CANCELLED watermark across the page
        pdf.set_text_color(220, 0, 0)
        pdf.set_font("Helvetica", "B", 60)
        pdf.set_xy(20, 110)
        pdf.cell(170, 30, "CANCELLED", align="C")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 11)

    # Top-line meta
    pdf.set_xy(15, 42)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(95, 6, _safe(f"Receipt No:  {receipt.receipt_no}"))
    pdf.cell(0, 6, f"Date:  {receipt.received_date.strftime('%d-%b-%Y')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(95, 6, _safe(f"Campus:  {campus.name}"))
    pdf.cell(0, 6, _safe(f"Status:  {receipt.get_status_display()}"), new_x="LMARGIN", new_y="NEXT")

    # Student block
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "Student", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, _safe(f"  Name:        {student.student_name}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _safe(f"  Application: {student.application_form_id}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, _safe(f"  Program:     {enrollment.program.name}"), new_x="LMARGIN", new_y="NEXT")
    if enrollment.batch:
        pdf.cell(0, 6, _safe(f"  Batch:       {enrollment.batch.name}"), new_x="LMARGIN", new_y="NEXT")

    # Fee breakup table
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(120, 8, "Description", border=1, fill=False)
    pdf.cell(60, 8, "Amount", border=1, align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    desc_lines = []
    if receipt.installment:
        desc_lines.append((f"Installment #{receipt.installment.sequence} - "
                           + (receipt.installment.description or ""), receipt.basic_fee))
    else:
        desc_lines.append(("Fee payment", receipt.basic_fee))

    if receipt.sgst:
        desc_lines.append(("SGST", receipt.sgst))
    if receipt.cgst:
        desc_lines.append(("CGST", receipt.cgst))
    if receipt.igst:
        desc_lines.append(("IGST", receipt.igst))

    for label, amt in desc_lines:
        pdf.cell(120, 7, _safe("  " + label), border=1)
        pdf.cell(60, 7, _money(amt), border=1, align="R",
                 new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(120, 8, "Total received", border=1)
    pdf.cell(60, 8, _money(receipt.amount), border=1, align="R",
             new_x="LMARGIN", new_y="NEXT")

    # Payment details
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, "Payment", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, _safe(f"  Mode:       {receipt.get_payment_mode_display()}"),
             new_x="LMARGIN", new_y="NEXT")
    if receipt.instrument_ref:
        pdf.cell(0, 6, _safe(f"  Reference:  {receipt.instrument_ref}"),
                 new_x="LMARGIN", new_y="NEXT")
    if receipt.bank:
        pdf.cell(0, 6, _safe(f"  Bank:       {receipt.bank}"),
                 new_x="LMARGIN", new_y="NEXT")
    if receipt.notes:
        pdf.cell(0, 6, _safe(f"  Notes:      {receipt.notes}"),
                 new_x="LMARGIN", new_y="NEXT")

    if receipt.status == receipt.Status.CANCELLED:
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(220, 0, 0)
        pdf.cell(0, 6, "Cancellation", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 11)
        when = receipt.cancelled_on.strftime("%d-%b-%Y") if receipt.cancelled_on else ""
        pdf.cell(0, 6, _safe(f"  Reason:     {receipt.cancellation_reason}"),
                 new_x="LMARGIN", new_y="NEXT")
        if when:
            pdf.cell(0, 6, f"  Cancelled:  {when}", new_x="LMARGIN", new_y="NEXT")

    # Footer
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    received_by = (
        receipt.received_by.username if receipt.received_by_id else "system"
    )
    pdf.cell(0, 5, _safe(f"Received by: {received_by}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, "This is a system-generated receipt. "
                   "Cancelled receipts are marked above; treat them as void.",
             new_x="LMARGIN", new_y="NEXT")

    out = pdf.output(dest="S")  # bytearray in fpdf2
    return bytes(out)
