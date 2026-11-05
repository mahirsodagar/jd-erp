"""Application form → PDF (the "Application form Acknowledgement").

What the student filled in, plus the terms they accepted and when, laid
out like the acknowledgement the institutes issue: the institute's
stacked logo, two centred titles, plain capitalised section headings
over grey-label rows, a qualifications table, the rules on their own
page with a signature / date / accept line, and the declaration last.

Rendered on demand and never stored: the source data is all in the DB,
so a re-render is idempotent. fpdf2, matching the receipt and
undertaking renderers — the built-in fonts are Latin-1 only, hence
`_safe()`.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from PIL import Image

from .application_terms import institute_code_for_student, terms_for
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

_ASSETS = Path(__file__).resolve().parent / "application_assets"

#: Page geometry. The body sits between these margins; `_LABEL_W` is the
#: left column of every two-column row.
_MARGIN = 20.0
_PAGE_W = 210.0
_BODY_W = _PAGE_W - 2 * _MARGIN
_LABEL_W = 70.0
_ROW_H = 9.0
_LINE_H = 4.5


def _safe(text) -> str:
    if text is None:
        return ""
    s = str(text)
    for k, v in _UNICODE_FALLBACKS.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _fmt_aadhaar(value: str) -> str:
    """Print Aadhaar in the 4-4-4 grouping people expect. Anything that
    isn't a full 12 digits is printed as-is rather than mis-grouped."""
    digits = "".join(c for c in (value or "") if c.isdigit())
    if len(digits) != 12:
        return value or ""
    return f"{digits[:4]} {digits[4:8]} {digits[8:]}"


def _fmt_date(value, fmt: str = "%d-%m-%Y") -> str:
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


# --- Building blocks ------------------------------------------------

def _heading(pdf: FPDF, title: str) -> None:
    """Section heading: bold capitals, no fill, as on the issued form."""
    pdf.ln(5)
    pdf.set_x(_MARGIN)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(_BODY_W, 7, _safe(title).upper(), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.5)


def _row(pdf: FPDF, label: str, value) -> None:
    """One bordered label/value row. The label cell is tinted; the value
    wraps so a long address grows the row instead of running off."""
    text = _safe(value) if value not in (None, "") else "-"
    pdf.set_font("Helvetica", "", 8.5)
    lines = pdf.multi_cell(_BODY_W - _LABEL_W - 4, _LINE_H, text,
                           dry_run=True, output="LINES")
    h = max(_ROW_H, len(lines) * _LINE_H + 4)
    if pdf.get_y() + h > pdf.page_break_trigger:
        pdf.add_page()

    x, y = _MARGIN, pdf.get_y()
    pdf.set_fill_color(247, 247, 247)
    pdf.rect(x, y, _LABEL_W, h, style="F")
    pdf.rect(x, y, _LABEL_W, h)
    pdf.rect(x + _LABEL_W, y, _BODY_W - _LABEL_W, h)

    pdf.set_xy(x + 2.5, y + (h - _LINE_H) / 2)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.cell(_LABEL_W - 3, _LINE_H, _safe(label))

    pdf.set_xy(x + _LABEL_W + 2.5, y + (h - len(lines) * _LINE_H) / 2)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.multi_cell(_BODY_W - _LABEL_W - 4, _LINE_H, text, align="L")
    pdf.set_y(y + h)


def _pairs(pdf: FPDF, rows: list[tuple[str, object]]) -> None:
    for label, value in rows:
        _row(pdf, label, value)


def _logo_path(student: Student) -> Path | None:
    code = (institute_code_for_student(student) or "").lower()
    for candidate in (_ASSETS / f"{code}-logo.png",):
        if candidate.is_file():
            return candidate
    logo = getattr(student.institute, "logo", None)
    if logo:
        try:
            return Path(logo.path)
        except Exception:  # noqa: BLE001
            return None
    return None


def _header(pdf: FPDF, student: Student) -> None:
    """Centred logo, then the institute name and form title."""
    y = 15.0
    path = _logo_path(student)
    if path is not None:
        try:
            w_px, h_px = Image.open(path).size
            h = 36.0
            w = h * w_px / h_px
            if w > 90:
                w, h = 90.0, 90.0 * h_px / w_px
            pdf.image(str(path), x=(_PAGE_W - w) / 2, y=y, w=w, h=h)
            y += h + 10
        except Exception:  # noqa: BLE001 — bad artwork must not 500 the form
            pass

    pdf.set_y(y)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    name = getattr(student.institute, "name", "") or "JD Institute"
    pdf.cell(0, 8, _safe(name).upper(), align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.cell(0, 8, "STUDENT APPLICATION FORM", align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)


def _documents(pdf: FPDF, student: Student) -> None:
    _heading(pdf, "Educational Qualifications")
    docs = list(student.documents.all().order_by("id"))
    if not docs:
        pdf.set_x(_MARGIN)
        pdf.set_font("Helvetica", "I", 8.5)
        pdf.multi_cell(_BODY_W, 5.5, "No education records were submitted.")
        return

    headers = dict(StudentDocument.Header.choices)
    widths = [26, 27, 36, 36, 25, 20]
    titles = ["Qualifying Exam", "Reg No./Month & Year of Passing",
              "School/College", "University/Board", "Certificate No.",
              "% Obtained"]

    def table_row(cells, bold: bool) -> None:
        pdf.set_font("Helvetica", "B" if bold else "", 7.5)
        wrapped = [
            pdf.multi_cell(w - 3, 3.8, _safe(c), dry_run=True, output="LINES")
            for w, c in zip(widths, cells)
        ]
        h = max(len(ls) for ls in wrapped) * 3.8 + 4
        if pdf.get_y() + h > pdf.page_break_trigger:
            pdf.add_page()
        x, y = _MARGIN, pdf.get_y()
        for w, c in zip(widths, cells):
            if bold:
                pdf.set_fill_color(247, 247, 247)
                pdf.rect(x, y, w, h, style="F")
            pdf.rect(x, y, w, h)
            pdf.set_xy(x + 1.5, y + 2)
            pdf.multi_cell(w - 3, 3.8, _safe(c), align="L")
            x += w
        pdf.set_y(y + h)

    table_row(titles, bold=True)
    for d in docs:
        table_row([
            headers.get(d.header, d.header),
            d.regno_yearpassing or "-",
            d.school_college or "-",
            d.university_board or "-",
            d.certificate_no or "-",
            str(d.percent_obtained) if d.percent_obtained is not None else "-",
        ], bold=False)


# --- Rules & declaration ---------------------------------------------

def _para(pdf: FPDF, text: str, *, bold: bool = False, indent: float = 0,
          size: float = 8.0) -> None:
    pdf.set_x(_MARGIN + indent)
    pdf.set_font("Helvetica", "B" if bold else "", size)
    pdf.multi_cell(_BODY_W - indent, _LINE_H - 0.5, _safe(text))


def _rules(pdf: FPDF, student: Student, terms: dict) -> None:
    _heading(pdf, "Rules & Regulations")
    if terms.get("preamble"):
        _para(pdf, terms["preamble"])
        pdf.ln(2)

    alpha = terms.get("list_style") == "upper-alpha"
    for n, rule in enumerate(terms["rules"], start=1):
        marker = rule.get("label") or (
            chr(ord("A") + n - 1) if alpha else str(n)
        )
        # Top-level rules print bold, their sub-points plain, as on the
        # issued form.
        _para(pdf, f"{marker}. {rule['text']}", bold=True)
        if rule.get("intro"):
            _para(pdf, rule["intro"], indent=3)
        for j, sub in enumerate(rule["subs"], start=1):
            if rule.get("ordered", True):
                label = chr(ord("A") + j - 1) if j <= 26 else str(j)
            else:
                label = "-"
            _para(pdf, f"{label}. {sub['text']}" if label != "-"
                  else f"- {sub['text']}")
            for bullet in sub["bullets"]:
                _para(pdf, f"- {bullet}", indent=6)
            if sub.get("after"):
                _para(pdf, sub["after"])
        pdf.ln(2.5)

    for line in terms.get("fee_note") or []:
        pdf.set_font("Helvetica", "I", 7.5)
        pdf.set_x(_MARGIN)
        pdf.multi_cell(_BODY_W, _LINE_H - 0.5, _safe(line))

    disclaimer = terms.get("disclaimer")
    if disclaimer:
        _disclaimer(pdf, disclaimer)

    # Signature / date / accept line.
    if pdf.get_y() + 40 > pdf.page_break_trigger:
        pdf.add_page()
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_x(_MARGIN)
    pdf.cell(0, 6, "Signature: _________________________",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_x(_MARGIN)
    pdf.cell(0, 6, "Date: _________________________",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    _accept_line(pdf, "I Accept above mentioned Rules & Regulations",
                 student.rules_accepted_at)


def _accept_line(pdf: FPDF, label: str, accepted_at) -> None:
    """A checkbox, ticked only when consent is on record. Never claims
    acceptance the database cannot evidence."""
    x, y = _MARGIN, pdf.get_y()
    pdf.rect(x, y + 0.5, 5, 5)
    if accepted_at:
        pdf.set_line_width(0.5)
        pdf.line(x + 1, y + 3, x + 2.2, y + 4.5)
        pdf.line(x + 2.2, y + 4.5, x + 4.3, y + 1.3)
        pdf.set_line_width(0.2)
    pdf.set_xy(x + 6.5, y)
    pdf.set_font("Helvetica", "B", 9)
    text = _safe(label)
    if accepted_at:
        text += f"  (accepted on {_fmt_date(accepted_at, '%d-%m-%Y %H:%M')})"
    pdf.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")


def _disclaimer(pdf: FPDF, disclaimer: dict) -> None:
    _heading(pdf, disclaimer["title"])
    if disclaimer.get("note"):
        pdf.set_font("Helvetica", "I", 7.5)
        pdf.set_x(_MARGIN)
        pdf.multi_cell(_BODY_W, _LINE_H - 0.5, _safe(f"Note:- {disclaimer['note']}"))
    if disclaimer.get("intro"):
        _para(pdf, disclaimer["intro"])
    for n, section in enumerate(disclaimer.get("sections") or [], start=1):
        pdf.ln(1)
        _para(pdf, f"{n}. {section['heading']}", bold=True)
        for bullet in section["bullets"]:
            _para(pdf, f"- {bullet}", indent=6)
    for line in disclaimer.get("footer_lines") or []:
        _para(pdf, line)


def _declaration(pdf: FPDF, student: Student, terms: dict) -> None:
    pdf.add_page()
    _heading(pdf, terms.get("declaration_title") or "Declaration")
    _para(pdf, terms["declaration"])
    pdf.ln(4)
    pdf.set_x(_MARGIN)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(12, 6, "Date:")
    pdf.set_font("Helvetica", "", 9)
    accepted = student.declaration_accepted_at
    pdf.cell(0, 6, _fmt_date(accepted) if accepted
             else "_________________________",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_x(_MARGIN)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Signature: _________________________",
             new_x="LMARGIN", new_y="NEXT")
    if not accepted:
        pdf.ln(2)
        pdf.set_x(_MARGIN)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(150, 60, 20)
        pdf.cell(0, 5, "Declaration not yet accepted on record.",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)


# --- Entry point -----------------------------------------------------

def render_application_pdf(student: Student) -> bytes:
    """The student's application form as a PDF, terms included."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(_MARGIN, _MARGIN, _MARGIN)
    pdf.add_page()

    _header(pdf, student)

    personal = [
        ("Name of Candidate:", student.student_name),
        ("Date of Birth:", _fmt_date(student.dob)),
        ("Gender:", student.get_gender_display()),
        ("Blood Group:", student.blood_group),
        ("Nationality:", student.get_nationality_display()),
        ("Category:", student.get_category_display()),
        ("Mobile Number:", student.student_mobile),
        ("Email:", student.student_email),
    ]
    if student.aadhaar_number:
        personal.append(("Aadhaar:", _fmt_aadhaar(student.aadhaar_number)))
    _heading(pdf, "Personal Information")
    _pairs(pdf, personal)

    _heading(pdf, "Academic Information")
    _pairs(pdf, [
        ("Academic Year:", getattr(student.academic_year, "full_name", "")
         or student.academic_year.code),
        ("Campus:", (student.campus.name or "").upper()),
        ("Program:", student.program.name),
        ("Course:", getattr(student.course, "name", None)),
    ])

    pdf.add_page()
    _heading(pdf, "Parent/Guardian Information")
    _pairs(pdf, [
        ("Father/Guardian Name:", student.father_name),
        ("Father/Guardian Mobile:", student.father_mobile),
        ("Father/Guardian Email:", student.father_email),
        ("Father/Guardian Occupation:", student.father_occupation),
        ("Mother/Spouse Name:", student.mother_name),
        ("Mother/Spouse Mobile:", student.mother_mobile),
        ("Mother/Spouse Email:", student.mother_email),
        ("Mother/Spouse Occupation:", student.mother_occupation),
    ])

    _heading(pdf, "Address Information")
    _pairs(pdf, [
        ("Correspondence Address:", student.current_address),
        ("Correspondence State:", getattr(student.current_state, "name", None)),
        ("Correspondence City:", getattr(student.current_city, "name", None)),
        ("Correspondence Pincode:", student.current_pincode),
        ("Permanent Address:", student.permanent_address),
        ("Permanent State:", getattr(student.permanent_state, "name", None)),
        ("Permanent City:", getattr(student.permanent_city, "name", None)),
        ("Permanent Pincode:", student.permanent_pincode),
    ])

    _documents(pdf, student)

    # Terms start on their own page: they run long, and a form split
    # mid-rule reads badly when printed.
    terms = terms_for(institute_code_for_student(student))
    pdf.add_page()
    _rules(pdf, student, terms)
    _declaration(pdf, student, terms)

    return bytes(pdf.output(dest="S"))
