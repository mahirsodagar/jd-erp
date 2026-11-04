"""Student ID card (fpdf2) — the 2026 printed card, one design per
institute.

Both cards are CR-80 portrait (54 x 85 mm), two pages: front, back.
Page 1 of the JDIFT card is the magenta block with the photo, the name,
program, ID number, centre and validity, over a white strip with the
cube logo and the "Since 1988" mark. The JDSD card is the white
Avenir-set design with the vertical name beside the photo, the program
and the affiliation line, and the address block on the back.

Everything printed is measured off the two reference PDFs (Aishwarya /
Aiysha, Nov 2026). Address, phone and website are the printed ones —
deliberately NOT `Institute.address` / `.phone`, which hold the
letterhead address (Swan House) and the admissions mobile.

Fonts: the JDIFT card is Arial Bold, for which fpdf2's built-in
Helvetica-Bold is metric-compatible. The JDSD card is Avenir, which is
proprietary; Nunito Sans (SIL OFL, bundled under idcard_assets/fonts)
stands in for it at matching weights.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from fpdf import FPDF

from apps.common.pdf_theme import safe

from .models import Enrollment, Student

CARD_W = 54.0
CARD_H = 85.0

_ASSETS = Path(__file__).resolve().parent / "idcard_assets"
_FONTS = _ASSETS / "fonts"

#: Magenta of the JDIFT card block, CMYK (4, 88, 0, 0) as printed.
JDIFT_MAGENTA = (192, 40, 124)
#: JDSD brand pink used for the affiliation line and the back header.
JDSD_PINK = (227, 28, 95)
JDSD_GREY = (70, 70, 70)

#: Printed on the cards, verbatim from the reference set.
JDIFT_ADDRESS = (
    "No.18, Edward House,",
    "Brigade Road, Bangalore - 560 001.",
    "Contact : 080 22279927",
)
JDSD_ADDRESS = (
    "NO. 18 EDWARD HOUSE",
    "BRIGADE RD, BENGALURU 560001",
    "+91 80 2559 4142",
    "www.jdsd.in",
)

RULES = (
    "Identity card must be carried for all official duties in & outside "
    "the campus.",
    "Card holder solely responsible for preserve & use of this card, in "
    "case of misuse, the Institute / Trust / Principal shall not be "
    "responsible.",
)


# --- Data ---------------------------------------------------------------

class CardData:
    """Everything a card prints, resolved once per student."""

    def __init__(self, student: Student, enrollment: Enrollment | None):
        self.student = student
        self.enrollment = enrollment
        program = (enrollment.program if enrollment else None) or student.program
        self.program = program
        self.institute = (
            (program.institute if program else None) or student.institute
        )
        self.institute_code = (self.institute.code if self.institute else "").upper()
        self.campus = (enrollment.campus if enrollment else None) or student.campus
        self.batch = enrollment.batch if enrollment else None

    @property
    def name(self) -> str:
        return (self.student.student_name or "").strip()

    @property
    def program_name(self) -> str:
        return self.program.name if self.program else ""

    @property
    def id_number(self) -> str:
        """Registration number once HR has set it, else the App ID."""
        return (self.student.registration_number
                or self.student.application_form_id or "")

    @property
    def centre(self) -> str:
        if not self.campus:
            return ""
        return self.campus.city or self.campus.name

    @property
    def batch_label(self) -> str:
        if not self.batch:
            return ""
        return self.batch.short_name or self.batch.name

    @property
    def blood_group(self) -> str:
        return self.student.blood_group or ""

    @property
    def affiliation(self) -> str:
        return (self.program.id_card_affiliation if self.program else "") or ""

    @property
    def valid_till(self) -> date | None:
        """Batch start plus the program's duration. The batch has no start
        date of its own; its academic year's start is the intake month.
        Falls back to the academic year's end when the program has no
        duration, and to nothing when there is no enrolment."""
        if not self.batch:
            return None
        year = self.batch.academic_year
        start = year.start_date if year else None
        months = self.program.duration_months if self.program else None
        if start and months:
            return _add_months(start, months)
        return year.end_date if year else None

    def photo_bytes(self) -> bytes | None:
        photo = self.student.photo
        if not photo:
            return None
        try:
            with photo.open("rb") as fh:
                return fh.read()
        except (FileNotFoundError, OSError, ValueError):
            return None


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, 1)


def _mon_year(d: date | None) -> str:
    return d.strftime("%b %Y") if d else ""


# --- Drawing helpers ------------------------------------------------------

def _photo_image(data: bytes | None, w: float, h: float):
    """Cover-crop the photo to the slot's aspect ratio. Returns a BytesIO
    for fpdf2, or None when there is no usable photo."""
    if not data:
        return None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:  # noqa: BLE001 — a corrupt upload must not kill the card
        return None
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    target = w / h
    iw, ih = im.size
    if iw / ih > target:
        nw = int(ih * target)
        off = (iw - nw) // 2
        im = im.crop((off, 0, off + nw, ih))
    else:
        nh = int(iw / target)
        off = (ih - nh) // 2
        im = im.crop((0, off, iw, off + nh))
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=90)
    out.seek(0)
    return out


def _photo_slot(pdf: FPDF, data: bytes | None, x: float, y: float,
                w: float, h: float) -> None:
    img = _photo_image(data, w, h)
    if img is not None:
        pdf.image(img, x=x, y=y, w=w, h=h)
        return
    pdf.set_fill_color(235, 235, 235)
    pdf.rect(x, y, w, h, style="F")
    pdf.set_text_color(130, 130, 130)
    pdf.set_font("Helvetica", "", 6)
    pdf.set_xy(x, y + h / 2 - 2)
    pdf.cell(w, 4, "NO PHOTO", align="C")


def _fit_size(pdf: FPDF, text: str, max_w: float, size: float,
              min_size: float = 5.0) -> float:
    """Largest font size <= `size` at which `text` fits in `max_w`."""
    family, style = pdf.font_family, pdf.font_style
    while size > min_size:
        pdf.set_font(family, style, size)
        if pdf.get_string_width(text) <= max_w:
            break
        size -= 0.25
    pdf.set_font(family, style, size)
    return size


def _centred(pdf: FPDF, y: float, text: str, size: float, *,
             style: str = "", family: str | None = None,
             color=(0, 0, 0), max_w: float = CARD_W - 4) -> None:
    pdf.set_font(family or pdf.font_family, style, size)
    pdf.set_text_color(*color)
    _fit_size(pdf, text, max_w, size)
    pdf.set_xy(2, y)
    pdf.cell(CARD_W - 4, size * 0.4, text, align="C")


def _numbered_rules(pdf: FPDF, y: float, size: float, line_h: float,
                    *, x: float = 3.5, width: float = CARD_W - 7,
                    gap: float = 1.2) -> float:
    """The two card rules with a hanging indent. Returns the y after."""
    for i, rule in enumerate(RULES, start=1):
        pdf.set_xy(x, y)
        pdf.cell(3.2, line_h, f"{i}.")
        pdf.set_xy(x + 3.2, y)
        pdf.multi_cell(width - 3.2, line_h, safe(rule), align="L")
        y = pdf.get_y() + gap
    return y


def _hrule(pdf: FPDF, y: float, *, x0: float = 4.0, x1: float = CARD_W - 4.0,
           width: float = 0.3, color=(0, 0, 0)) -> None:
    pdf.set_draw_color(*color)
    pdf.set_line_width(width)
    pdf.line(x0, y, x1, y)


# --- JDIFT -----------------------------------------------------------------

def _jdift_front(pdf: FPDF, d: CardData) -> None:
    pdf.add_page()
    pdf.set_fill_color(*JDIFT_MAGENTA)
    pdf.rect(0, 0, CARD_W, 56.5, style="F")

    _photo_slot(pdf, d.photo_bytes(), x=18.0, y=7.8, w=18.0, h=24.0)

    pdf.set_font("Helvetica", "B", 10)
    _centred(pdf, 35.8, safe(d.name.upper()), 10, style="B",
             family="Helvetica", color=(255, 255, 255), max_w=48)
    _centred(pdf, 39.6, safe(d.program_name), 8.2, style="B",
             family="Helvetica", color=(255, 255, 255), max_w=48)
    _centred(pdf, 43.5, safe(d.id_number), 9.2, style="B",
             family="Helvetica", color=(255, 255, 255), max_w=48)
    centre = f"{d.centre} Centre" if d.centre else ""
    _centred(pdf, 47.2, safe(centre), 9, style="B",
             family="Helvetica", color=(255, 255, 255), max_w=48)
    valid = _mon_year(d.valid_till)
    _centred(pdf, 51.0, safe(f"Valid Till {valid}" if valid else ""), 9,
             style="B", family="Helvetica", color=(255, 255, 255), max_w=48)

    # --- white strip: cube lockup | Since 1988 ---
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.25)
    pdf.line(28.7, 59.0, 28.7, 80.7)

    pdf.image(str(_ASSETS / "jdift-cube.png"), x=11.5, y=59.4, w=10.2, h=10.2)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 7.2)
    pdf.set_stretching(78)
    pdf.set_xy(2, 70.2)
    pdf.cell(24.7, 2.8, "JD INSTITUTE OF", align="C")
    pdf.set_xy(2, 72.9)
    pdf.cell(24.7, 2.8, "FASHION TECHNOLOGY", align="C")
    pdf.set_stretching(100)
    # "Welcome to Imagination" — "nation" picked out in magenta.
    pdf.set_font("Helvetica", "", 5.4)
    w1 = pdf.get_string_width("Welcome to Imagi")
    w2 = pdf.get_string_width("nation")
    x = 2 + (24.7 - (w1 + w2)) / 2
    pdf.set_xy(x, 76.0)
    pdf.cell(w1, 2.4, "Welcome to Imagi")
    pdf.set_text_color(*JDIFT_MAGENTA)
    pdf.cell(w2, 2.4, "nation")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 5)
    pdf.set_xy(2, 79.0)
    pdf.cell(24.7, 2.4, "jdinstitute.edu.in", align="C")

    pdf.set_font("Times", "I", 8)
    pdf.set_xy(30.5, 61.2)
    pdf.cell(21, 3, "Since", align="C")
    pdf.image(str(_ASSETS / "since-1988.png"), x=31.4, y=64.0, w=17.0)
    pdf.set_line_width(0.25)
    pdf.line(31.4, 74.6, 48.4, 74.6)
    pdf.set_font("Helvetica", "", 7.4)
    wa = pdf.get_string_width("Leading ")
    pdf.set_font("Helvetica", "B", 7.4)
    wb = pdf.get_string_width("Change")
    x = 30.5 + (21 - (wa + wb)) / 2
    pdf.set_xy(x, 76.2)
    pdf.set_font("Helvetica", "", 7.4)
    pdf.cell(wa, 3, "Leading ")
    pdf.set_font("Helvetica", "B", 7.4)
    pdf.cell(wb, 3, "Change")


def _jdift_back(pdf: FPDF, d: CardData) -> None:
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 8.2)
    y = 4.4
    pdf.set_xy(2, y)
    pdf.cell(CARD_W - 4, 3.4, safe(f"Blood Group : {d.blood_group}"), align="C")
    y += 3.5
    for line in JDIFT_ADDRESS:
        pdf.set_xy(2, y)
        pdf.cell(CARD_W - 4, 3.0, safe(line), align="C")
        y += 3.2
    _hrule(pdf, 19.5, x0=0, x1=CARD_W, width=0.8)

    pdf.set_font("Helvetica", "B", 6.8)
    _numbered_rules(pdf, 22.4, 6.8, 2.9)

    pdf.image(str(_ASSETS / "principal-signature.png"), x=37.5, y=66.8, w=11.0)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(4.5, 77.0)
    pdf.cell(26, 4, "Student Signature")
    pdf.set_xy(37.0, 77.0)
    pdf.cell(14, 4, "Principal")


# --- JDSD ------------------------------------------------------------------

def _register_avenir(pdf: FPDF) -> None:
    """Nunito Sans at Avenir's weights: Medium=500, Heavy=800, Black=900."""
    pdf.add_font("AvenirM", "", str(_FONTS / "NunitoSans-500.ttf"))
    pdf.add_font("AvenirM", "B", str(_FONTS / "NunitoSans-700.ttf"))
    pdf.add_font("AvenirH", "", str(_FONTS / "NunitoSans-800.ttf"))
    pdf.add_font("AvenirK", "", str(_FONTS / "NunitoSans-900.ttf"))


def _jdsd_front(pdf: FPDF, d: CardData) -> None:
    pdf.add_page()
    pdf.image(str(_ASSETS / "jdsd-logo.png"), x=4.8, y=5.3, w=44.6)

    photo_x, photo_y, photo_w, photo_h = 15.2, 30.1, 27.7, 34.5
    _photo_slot(pdf, d.photo_bytes(), x=photo_x, y=photo_y, w=photo_w, h=photo_h)

    # Vertical name, reading bottom-to-top, foot aligned to the photo's
    # bottom edge, set just left of the photo.
    name = d.name.upper()
    pdf.set_font("AvenirM", "", 10.5)
    pdf.set_text_color(*JDSD_GREY)
    size = _fit_size(pdf, name, photo_h, 10.5)
    with pdf.rotation(90, x=13.8, y=photo_y + photo_h):
        pdf.set_xy(13.8, photo_y + photo_h - size * 0.42)
        pdf.cell(photo_h, size * 0.42, name)

    _hrule(pdf, 67.7, x0=4.3, x1=CARD_W - 4.3, width=0.3, color=JDSD_GREY)
    _centred(pdf, 69.6, d.program_name, 10.6, family="AvenirM",
             color=JDSD_GREY, max_w=46)
    _hrule(pdf, 74.2, x0=4.3, x1=CARD_W - 4.3, width=0.3, color=JDSD_GREY)
    if d.affiliation:
        _centred(pdf, 76.7, d.affiliation, 7.4, family="AvenirM",
                 color=JDSD_PINK, max_w=48)
    _hrule(pdf, 81.0, x0=4.3, x1=CARD_W - 4.3, width=0.3, color=JDSD_GREY)


def _jdsd_back(pdf: FPDF, d: CardData) -> None:
    pdf.add_page()
    pdf.image(str(_ASSETS / "jdsd-mark.png"), x=5.3, y=5.9, w=9.0)
    pdf.set_font("AvenirM", "", 8.6)
    pdf.set_text_color(*JDSD_PINK)
    pdf.set_xy(16.4, 5.6)
    pdf.cell(35, 3.4, "JD SCHOOL OF DESIGN")
    pdf.set_font("AvenirM", "", 5.7)
    pdf.set_text_color(*JDSD_GREY)
    y = 9.4
    for line in JDSD_ADDRESS:
        pdf.set_xy(16.4, y)
        pdf.cell(35, 2.6, line)
        y += 2.55
    _hrule(pdf, 21.0, x0=5.0, x1=CARD_W - 5.0, width=0.3, color=JDSD_GREY)

    valid = _mon_year(d.valid_till).upper()
    rows = (
        f"BATCH : {d.batch_label}",
        f"VALID TILL : {valid}",
        f"BLOOD GROUP :  {d.blood_group}",
    )
    y = 24.0
    for row in rows:
        _centred(pdf, y, row, 8.2, family="AvenirM", color=JDSD_GREY)
        y += 3.1

    pdf.set_font("AvenirM", "", 6.2)
    pdf.set_text_color(*JDSD_GREY)
    _numbered_rules(pdf, 50.0, 6.2, 2.6, x=3.5, width=CARD_W - 7)
    _hrule(pdf, 67.7, x0=4.3, x1=CARD_W - 4.3, width=0.3, color=JDSD_GREY)

    pdf.image(str(_ASSETS / "principal-signature.png"), x=21.4, y=69.3, w=11.0)
    _centred(pdf, 80.0, "PRINCIPAL", 6.9, family="AvenirM", color=JDSD_GREY)


# --- Entry points ----------------------------------------------------------

def _new_pdf() -> FPDF:
    pdf = FPDF(unit="mm", format=(CARD_W, CARD_H))
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)
    pdf.set_title("Student ID card")
    _register_avenir(pdf)
    return pdf


def _draw_card(pdf: FPDF, d: CardData) -> None:
    if d.institute_code == "JDSD":
        _jdsd_front(pdf, d)
        _jdsd_back(pdf, d)
    else:
        _jdift_front(pdf, d)
        _jdift_back(pdf, d)


def card_data(student: Student, enrollment: Enrollment | None = None) -> CardData:
    if enrollment is None:
        from .services import current_enrollment
        enrollment = current_enrollment(student)
    return CardData(student, enrollment)


def render_id_card(student: Student, enrollment: Enrollment | None = None) -> bytes:
    """One student's card: a 2-page PDF (front, back)."""
    pdf = _new_pdf()
    _draw_card(pdf, card_data(student, enrollment))
    return bytes(pdf.output())


def render_batch_id_cards(batch) -> tuple[bytes, int]:
    """Every ACTIVE student in the batch, front then back, one after the
    other, ordered by name. Returns (pdf bytes, number of cards)."""
    enrolments = (
        Enrollment.objects
        .filter(batch=batch, status=Enrollment.Status.ACTIVE)
        .select_related(
            "student", "student__campus", "student__institute",
            "student__program", "program", "program__institute",
            "campus", "batch", "batch__academic_year",
        )
        .order_by("student__student_name")
    )
    pdf = _new_pdf()
    n = 0
    for e in enrolments:
        _draw_card(pdf, CardData(e.student, e))
        n += 1
    if n == 0:
        pdf.add_page()
        pdf.set_font("Helvetica", "", 8)
        pdf.set_xy(2, 40)
        pdf.cell(CARD_W - 4, 4, "No active students", align="C")
    return bytes(pdf.output()), n
