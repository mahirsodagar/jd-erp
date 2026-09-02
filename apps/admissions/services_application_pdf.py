"""Application form → PDF.

What the student filled in, plus the terms they accepted and when, laid
out as a printable record. Rendered on demand and never stored: the
source data is all in the DB, so a re-render is idempotent.

fpdf2, matching the receipt and undertaking renderers — the built-in
fonts are Latin-1 only, hence `_safe()`.
"""

from __future__ import annotations

from fpdf import FPDF

from .application_terms import terms_for
from .models import Student, StudentDocument

_UNICODE_FALLBACKS = {
    "–": "-",
    "—": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    "₹": "INR ",
    "·": "-",
}

#: Page geometry. The body sits between these margins; `_LABEL_W` is the
#: left column of every two-column row.
_MARGIN = 15.0
_PAGE_W = 210.0
_BODY_W = _PAGE_W - 2 * _MARGIN
_LABEL_W = 55.0


def _safe(text) -> str:
    if text is None:
        return ""
    s = str(text)
    for k, v in _UNICODE_FALLBACKS.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _fmt_date(value, fmt: str = "%d-%b-%Y") -> str:
    """Format a date/datetime, tolerating one that is still a string.

    An unsaved Student carries whatever the form posted — `dob` is an
    ISO string until Django coerces it on refresh. Printing it raw beats
    failing the whole download over a formatting nicety.
    """
    if not value:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime(fmt)
    return str(value)


class _ApplicationPDF(FPDF):
    """Adds the page footer. Everything else is drawn by the functions
    below so the layout reads top-to-bottom."""

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(130, 130, 130)
        self.cell(0, 6, f"Page {self.page_no()} of {{nb}}", align="C")


def _section(pdf: FPDF, title: str) -> None:
    pdf.ln(3)
    pdf.set_x(_MARGIN)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(238, 238, 242)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(_BODY_W, 7, f"  {_safe(title)}", fill=True,
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)


def _row(pdf: FPDF, label: str, value) -> None:
    """One label/value line. `multi_cell` on the value so a long address
    wraps instead of running off the page."""
    text = _safe(value) if value not in (None, "") else "-"
    pdf.set_x(_MARGIN)
    top = pdf.get_y()
    pdf.set_font("Helvetica", "B", 9)
    pdf.multi_cell(_LABEL_W, 5.5, _safe(label), border="LTB",
                   new_x="RIGHT", new_y="TOP", max_line_height=5.5)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(_MARGIN + _LABEL_W, top)
    pdf.multi_cell(_BODY_W - _LABEL_W, 5.5, text, border="RTB",
                   new_x="LMARGIN", new_y="NEXT", max_line_height=5.5)


def _pairs(pdf: FPDF, rows: list[tuple[str, object]]) -> None:
    for label, value in rows:
        _row(pdf, label, value)


def _header(pdf: FPDF, student: Student) -> None:
    institute = student.institute
    pdf.set_fill_color(20, 60, 120)
    pdf.rect(0, 0, _PAGE_W, 22, style="F")
    pdf.set_y(5)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 8, _safe(getattr(institute, "name", "") or "Application"),
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _safe(student.campus.name), align="C")

    pdf.set_y(26)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Student Application Form", align="C",
             new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    ref = student.application_form_id or "-"
    if student.registration_number:
        ref += f"   |   Reg. No: {student.registration_number}"
    pdf.cell(0, 5, _safe(ref), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(
        0, 5,
        _safe(f"Submitted: {_fmt_date(student.created_on, '%d-%b-%Y %H:%M')}"),
        align="C", new_x="LMARGIN", new_y="NEXT",
    )
    pdf.set_text_color(0, 0, 0)


def _photo(pdf: FPDF, student: Student) -> None:
    """Top-right passport photo. A missing or unreadable file is not
    worth failing a download over — the box is simply left empty."""
    if not student.photo:
        return
    try:
        pdf.image(student.photo.path, x=_PAGE_W - _MARGIN - 25, y=26,
                  w=25, h=30)
    except Exception:
        return


def _terms(pdf: FPDF, student: Student) -> None:
    terms = terms_for(getattr(student.institute, "code", "") or "")

    # The bundle carries its own heading — JDSD's 2026 document calls
    # this section "Undertaking by the student", the earlier wording a
    # declaration.
    heading = terms.get("declaration_title") or "Declaration"
    _section(pdf, heading)
    pdf.set_x(_MARGIN)
    pdf.set_font("Helvetica", "", 8.5)
    # `multi_cell` honours the blank lines between the undertaking's
    # paragraphs, so no per-paragraph loop is needed.
    pdf.multi_cell(_BODY_W, 4.5, _safe(terms["declaration"]))
    _accepted_line(pdf, f"{heading} accepted", student.declaration_accepted_at)

    _section(pdf, "Terms & Conditions - Rules and Regulations")
    pdf.set_font("Helvetica", "", 8.5)
    alpha = terms.get("list_style") == "upper-alpha"
    for n, rule in enumerate(terms["rules"], start=1):
        # JDIFT's document letters its sections A-I; JDSD's numbers them.
        marker = chr(ord("A") + n - 1) if alpha else str(n)
        pdf.set_x(_MARGIN)
        pdf.set_font("Helvetica", "B" if rule["emphasis"] else "", 8.5)
        pdf.multi_cell(_BODY_W, 4.5, _safe(f"{marker}. {rule['text']}"))
        pdf.set_font("Helvetica", "", 8.5)
        if rule.get("intro"):
            pdf.set_x(_MARGIN + 3)
            pdf.multi_cell(_BODY_W - 3, 4.5, _safe(rule["intro"]))
        for j, sub in enumerate(rule["subs"], start=1):
            # An unordered section (JDIFT's C) is bulleted, not numbered.
            label = f"{marker}.{j}" if rule.get("ordered", True) else "-"
            pdf.set_x(_MARGIN + 6)
            pdf.multi_cell(_BODY_W - 6, 4.5, _safe(f"{label} {sub['text']}"))
            for bullet in sub["bullets"]:
                pdf.set_x(_MARGIN + 12)
                pdf.multi_cell(_BODY_W - 12, 4.5, _safe(f"- {bullet}"))
            if sub.get("after"):
                pdf.set_x(_MARGIN + 6)
                pdf.multi_cell(_BODY_W - 6, 4.5, _safe(sub["after"]))
        pdf.ln(0.8)

    fee_note = terms.get("fee_note") or []
    if fee_note:
        pdf.ln(0.8)
        pdf.set_font("Helvetica", "I", 8)
        for line in fee_note:
            pdf.set_x(_MARGIN)
            pdf.multi_cell(_BODY_W, 4.5, _safe(line))
        pdf.set_font("Helvetica", "", 8.5)

    _accepted_line(pdf, "Rules & Regulations accepted", student.rules_accepted_at)

    disclaimer = terms.get("disclaimer")
    if disclaimer:
        _disclaimer(pdf, disclaimer)


def _accepted_line(pdf: FPDF, label: str, accepted_at) -> None:
    """States plainly whether consent is on record, and when. Never
    claims acceptance the database cannot evidence."""
    pdf.ln(1.5)
    pdf.set_x(_MARGIN)
    pdf.set_font("Helvetica", "B", 8.5)
    if accepted_at:
        pdf.set_text_color(20, 100, 60)
        text = (
            f"[X] {label} by the student on "
            f"{_fmt_date(accepted_at, '%d-%b-%Y %H:%M')}"
        )
    else:
        pdf.set_text_color(150, 60, 20)
        text = f"[ ] {label} - not recorded"
    pdf.multi_cell(_BODY_W, 5, _safe(text))
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 9)


def _disclaimer(pdf: FPDF, disclaimer: dict) -> None:
    _section(pdf, disclaimer["title"])
    pdf.set_font("Helvetica", "I", 8)
    if disclaimer.get("note"):
        pdf.set_x(_MARGIN)
        pdf.multi_cell(_BODY_W, 4.5, _safe(f"Note:- {disclaimer['note']}"))
    pdf.set_font("Helvetica", "", 8.5)
    if disclaimer.get("intro"):
        pdf.set_x(_MARGIN)
        pdf.multi_cell(_BODY_W, 4.5, _safe(disclaimer["intro"]))
    for n, section in enumerate(disclaimer.get("sections") or [], start=1):
        pdf.ln(1)
        pdf.set_x(_MARGIN)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.multi_cell(_BODY_W, 4.5, _safe(f"{n}. {section['heading']}"))
        pdf.set_font("Helvetica", "", 8.5)
        for bullet in section["bullets"]:
            pdf.set_x(_MARGIN + 6)
            pdf.multi_cell(_BODY_W - 6, 4.5, _safe(f"- {bullet}"))
    for line in disclaimer.get("footer_lines") or []:
        pdf.set_x(_MARGIN)
        pdf.multi_cell(_BODY_W, 4.5, _safe(line))


def _documents(pdf: FPDF, student: Student) -> None:
    _section(pdf, "Education History")
    docs = list(student.documents.all().order_by("id"))
    if not docs:
        pdf.set_x(_MARGIN)
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(_BODY_W, 5.5, "No education records were submitted.")
        return

    headers = dict(StudentDocument.Header.choices)
    widths = [26, 26, 44, 44, 20, 20]
    titles = ["Type", "Reg / Year", "School / College",
              "Board / University", "Cert no.", "%"]

    pdf.set_x(_MARGIN)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(245, 245, 248)
    for w, title in zip(widths, titles):
        pdf.cell(w, 6, _safe(title), border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for d in docs:
        cells = [
            headers.get(d.header, d.header),
            d.regno_yearpassing or "-",
            d.school_college or "-",
            d.university_board or "-",
            d.certificate_no or "-",
            str(d.percent_obtained) if d.percent_obtained is not None else "-",
        ]
        pdf.set_x(_MARGIN)
        for w, value in zip(widths, cells):
            # Truncation rather than wrapping: a fixed-height row keeps
            # the table readable, and the full value is always in the
            # portal.
            text = _safe(value)
            while text and pdf.get_string_width(text) > w - 2:
                text = text[:-1]
            pdf.cell(w, 5.5, text, border=1)
        pdf.ln()


def _signatures(pdf: FPDF) -> None:
    pdf.ln(10)
    y = pdf.get_y()
    pdf.set_font("Helvetica", "", 9)
    for x, label in ((_MARGIN, "Signature of the Student"),
                     (_PAGE_W - _MARGIN - 60, "Signature of the Parent / Guardian")):
        pdf.line(x, y, x + 60, y)
        pdf.set_xy(x, y + 1)
        pdf.cell(60, 5, _safe(label), align="C")


def render_application_pdf(student: Student) -> bytes:
    """The student's application form as a PDF, terms included."""
    pdf = _ApplicationPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
    pdf.alias_nb_pages()
    pdf.add_page()

    _header(pdf, student)
    _photo(pdf, student)
    pdf.set_y(48)

    _section(pdf, "Placement")
    _pairs(pdf, [
        ("Institute", student.institute.name),
        ("Campus", student.campus.name),
        ("Program", student.program.name),
        ("Course", getattr(student.course, "name", None)),
        ("Academic year", student.academic_year.code),
    ])

    _section(pdf, "Personal Details")
    _pairs(pdf, [
        ("Full name", student.student_name),
        ("Date of birth", _fmt_date(student.dob)),
        ("Gender", student.get_gender_display()),
        ("Category", student.get_category_display()),
        ("Study medium", student.get_study_medium_display()),
        ("Nationality", student.get_nationality_display()),
        ("Blood group", student.blood_group),
    ])

    _section(pdf, "Contact")
    _pairs(pdf, [
        ("Mobile", student.student_mobile),
        ("Email", student.student_email),
        ("Institute email", student.institute_email),
    ])

    _section(pdf, "Family")
    _pairs(pdf, [
        ("Father's name", student.father_name),
        ("Father's mobile", student.father_mobile),
        ("Father's email", student.father_email),
        ("Father's occupation", student.father_occupation),
        ("Mother's name", student.mother_name),
        ("Mother's mobile", student.mother_mobile),
        ("Mother's email", student.mother_email),
        ("Mother's occupation", student.mother_occupation),
    ])

    _section(pdf, "Current Address")
    _pairs(pdf, [
        ("Address", student.current_address),
        ("City", getattr(student.current_city, "name", None)),
        ("State", getattr(student.current_state, "name", None)),
        ("PIN code", student.current_pincode),
    ])

    _section(pdf, "Permanent Address")
    _pairs(pdf, [
        ("Address", student.permanent_address),
        ("City", getattr(student.permanent_city, "name", None)),
        ("State", getattr(student.permanent_state, "name", None)),
        ("PIN code", student.permanent_pincode),
    ])

    _documents(pdf, student)

    # Terms start on their own page: they run long, and a form split
    # mid-declaration reads badly when printed.
    pdf.add_page()
    _terms(pdf, student)
    _signatures(pdf)

    return bytes(pdf.output(dest="S"))
