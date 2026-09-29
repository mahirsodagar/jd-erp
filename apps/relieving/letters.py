"""Relieving + experience letter PDFs (fpdf2), laid out like the legacy
`hr/hrsave.php` letters: the institute's letterhead header and footer
artwork, the address block, the legacy wording, and the HR signatory's
signature beside the institute seal.

Artwork lives in `letter_assets/<variant>/` (header.jpg, footer.jpg,
seal.png) plus the shared `hr_signature.png`. Legacy chose the JD School
of Design artwork for entity 2 and the JD Institute artwork otherwise;
here that is the institute code. A missing file is skipped, never fatal.
"""

from datetime import date as _date
from pathlib import Path

from django.conf import settings
from fpdf import FPDF
from PIL import Image

from apps.common.pdf_theme import letterhead_lines, safe

_ASSETS = Path(__file__).resolve().parent / "letter_assets"

PAGE_W, PAGE_H = 210.0, 297.0
MARGIN = 20.0
BODY_W = PAGE_W - 2 * MARGIN
LINE_H = 7.0  # 12pt at the legacy 1.5 line-height


def _asset(institute, name: str) -> Path | None:
    variant = "JDSD" if (institute.code or "").upper() == "JDSD" else "JDIFT"
    path = _ASSETS / variant / name
    return path if path.is_file() else None


def _full_width_image(pdf: FPDF, path: Path | None, *, y: float | None = None,
                      bottom: float | None = None) -> float:
    """Draw `path` edge to edge, top at `y` or ending at `bottom`.
    Returns its rendered height (0 when there is no artwork)."""
    if path is None:
        return 0.0
    try:
        w_px, h_px = Image.open(path).size
        h = PAGE_W * h_px / w_px
        pdf.image(str(path), x=0, y=y if y is not None else bottom - h,
                  w=PAGE_W, h=h)
        return h
    except Exception:  # noqa: BLE001 — bad artwork must not 500 the letter
        return 0.0


def _b(value) -> str:
    """A value for a **bold** markdown run, with fpdf2's markdown
    markers (** __ --) defused so a name cannot toggle styles."""
    s = str(value or "")
    for marker in ("**", "__", "--"):
        s = s.replace(marker, marker[0])
    return f"**{safe(s)}**"


def _article(word: str) -> str:
    return "an" if (word or "")[:1].lower() in "aeiou" else "a"


def _department(emp) -> str:
    name = getattr(emp.department, "name", "") or ""
    return name if name.lower().endswith("department") else f"{name} department"


def _fmt(d) -> str:
    return f"{d:%d %b %Y}" if d else "-"


def _letter(application, *, title: str, title_size: float, letter_no: str,
            paragraphs: list[str]) -> bytes:
    emp = application.employee
    inst = emp.institute
    issued_on = (application.finalized_at.date()
                 if application.finalized_at else _date.today())

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.add_page()

    header_h = _full_width_image(pdf, _asset(inst, "header.jpg"), y=0)
    # The header artwork carries its own whitespace below the logo.
    pdf.set_y(max(header_h - 8, MARGIN))

    pdf.set_font("Helvetica", "B", title_size)
    pdf.cell(0, LINE_H + 1, safe(title), align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, safe(f"Ref: {letter_no}"), align="R",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    # Institute + address block.
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 6, safe(inst.name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    for line in letterhead_lines(inst):
        pdf.cell(0, 5.5, safe(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    pdf.set_font("Helvetica", "", 12)
    for para in paragraphs:
        pdf.multi_cell(BODY_W, LINE_H, para, markdown=True,
                       new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, LINE_H, "Sincerely,", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Signature beside the seal, as in the legacy letter.
    y = pdf.get_y()
    sig = _ASSETS / "hr_signature.png"
    seal = _asset(inst, "seal.png")
    for path, x, w in ((sig, MARGIN, 21.0), (seal, MARGIN + 25, 26.0)):
        if path and path.is_file():
            try:
                pdf.image(str(path), x=x, y=y, w=w)
            except Exception:  # noqa: BLE001
                pass
    pdf.set_y(y + 28)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 6, safe(settings.RELIEVING_LETTER_SIGNATORY),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 6, safe(settings.RELIEVING_LETTER_SIGNATORY_TITLE),
             new_x="LMARGIN", new_y="NEXT")

    # Footer artwork pinned to the bottom, date of issue beneath it.
    _full_width_image(pdf, _asset(inst, "footer.jpg"), bottom=PAGE_H - 10)
    pdf.set_xy(MARGIN, PAGE_H - 9)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(BODY_W, 5, safe(f"Date of issue:- {issued_on:%d-%m-%Y}"),
             align="R")

    return bytes(pdf.output())


# --- Relieving letter ----------------------------------------------

def render_relieving_letter(application) -> bytes:
    emp = application.employee
    last_day = (application.last_working_date_approved
                or application.last_working_date_requested)
    designation = getattr(emp.designation, "name", "") or ""
    return _letter(
        application, title="Relieving Letter", title_size=13,
        letter_no=application.relieving_letter_no,
        paragraphs=[
            f"This is to certify that {_b(emp.full_name)} was working as "
            f"{_article(designation)} {_b(designation)} in the "
            f"{_b(_department(emp))}, since {_b(_fmt(emp.date_of_joining))} "
            "and has been relieved from all the duties, services and "
            f"responsibilities with effect from {_b(_fmt(last_day))}.",
            "We wish all the best in future endeavors.",
        ],
    )


# --- Experience letter ---------------------------------------------

def render_experience_letter(application) -> bytes:
    emp = application.employee
    inst = emp.institute
    last_day = (application.last_working_date_approved
                or application.last_working_date_requested)
    designation = getattr(emp.designation, "name", "") or ""
    return _letter(
        application, title="Certificate of Experience", title_size=16,
        letter_no=application.experience_letter_no,
        paragraphs=[
            f"I hereby confirm that {_b(emp.full_name)} served as "
            f"{_article(designation)} {_b(designation)} in the "
            f"{_b(_department(emp))} at {_b(inst.name)}, Bengaluru, from "
            f"{_b(_fmt(emp.date_of_joining))} to {_b(_fmt(last_day))}.",
            f"Throughout the tenure, {_b(emp.full_name)} demonstrated "
            "commendable efficiency, diligence, and integrity in the role.",
            f"We extend our best wishes to {_b(emp.full_name)} for future "
            "endeavors and trust they will continue to excel.",
        ],
    )
