"""Relieving + experience letter PDF rendering. Same Latin-1 fpdf2
pattern as the Module G.5 certificates."""

from datetime import date as _date

from fpdf import FPDF


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


def _header(pdf: FPDF, institute_name: str, title: str):
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


def _meta_block(pdf: FPDF, *, letter_no: str, issued_on: _date):
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(95, 6, _safe(f"Letter No: {letter_no}"))
    pdf.cell(0, 6, _safe(f"Date: {issued_on:%d-%b-%Y}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)


def _signatures(pdf: FPDF, lines=("HR Manager", "Director")):
    pdf.ln(28)
    col = 200 / max(len(lines), 1)
    y = pdf.get_y()
    pdf.set_font("Helvetica", "", 11)
    for i, label in enumerate(lines):
        x = 10 + i * col
        pdf.set_xy(x, y)
        pdf.cell(col, 5, "_" * 26, align="C", new_x="LEFT", new_y="NEXT")
        pdf.set_xy(x, y + 7)
        pdf.cell(col, 5, _safe(label), align="C")


# --- Relieving letter ----------------------------------------------

def render_relieving_letter(application) -> bytes:
    emp = application.employee
    inst = emp.institute
    issued_on = (application.finalized_at.date()
                 if application.finalized_at else _date.today())

    pdf = _new_pdf()
    _header(pdf, inst.name, "Relieving Letter")
    _meta_block(pdf, letter_no=application.relieving_letter_no,
                issued_on=issued_on)

    last_day = (application.last_working_date_approved
                or application.last_working_date_requested)

    body = [
        f"Dear {emp.full_name},",
        "",
        f"This is to formally acknowledge that your resignation from "
        f"{inst.name} has been accepted and you have been relieved of "
        f"your duties as {emp.designation.name}, "
        f"{emp.department.name} department.",
        "",
        f"Your last working day with the institute is {last_day:%d-%b-%Y}.",
        "",
        "We confirm that you have been cleared of all dues and "
        "responsibilities. You have served the institute with sincerity "
        "and dedication during your tenure with us.",
        "",
        "We thank you for your contribution and wish you the very best "
        "in your future endeavours.",
        "",
        "With warm regards,",
    ]
    pdf.set_font("Helvetica", "", 12)
    pdf.ln(2)
    for line in body:
        if line:
            pdf.multi_cell(0, 7, _safe(line))
        else:
            pdf.ln(3)

    _signatures(pdf)
    return bytes(pdf.output(dest="S"))


# --- Experience letter ---------------------------------------------

def render_experience_letter(application) -> bytes:
    emp = application.employee
    inst = emp.institute
    issued_on = (application.finalized_at.date()
                 if application.finalized_at else _date.today())
    joined_on = emp.date_of_joining
    last_day = (application.last_working_date_approved
                or application.last_working_date_requested)

    pdf = _new_pdf()
    _header(pdf, inst.name, "Experience Letter")
    _meta_block(pdf, letter_no=application.experience_letter_no,
                issued_on=issued_on)

    body = [
        "TO WHOM IT MAY CONCERN",
        "",
        f"This is to certify that {emp.full_name} (Employee Code "
        f"{emp.emp_code}) was associated with {inst.name} as "
        f"{emp.designation.name} in the {emp.department.name} department.",
        "",
        f"He/She served the institute from {joined_on:%d-%b-%Y} to "
        f"{last_day:%d-%b-%Y}.",
        "",
        "During the tenure, his/her conduct was found to be satisfactory, "
        "and the contributions to the institute have been valued.",
        "",
        "We wish him/her the very best in their future undertakings.",
        "",
        "Sincerely,",
    ]
    pdf.set_font("Helvetica", "", 12)
    pdf.ln(2)
    for line in body:
        if line:
            pdf.multi_cell(0, 7, _safe(line))
        else:
            pdf.ln(3)

    _signatures(pdf)
    return bytes(pdf.output(dest="S"))
