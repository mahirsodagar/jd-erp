"""Employee (staff) ID card — fpdf2, CR-80 portrait 54 x 85 mm, two
pages (front, back), one design per institute, the same way the student
card works (`apps.admissions.services_idcard`).

JDIFT staff card (reference: "Jugal Majhi, Office Assistant"): black
front with the photo, name, designation and "Employee ID :", over a
white strip with the cube lockup and the "Since 1988" mark; the back
lists DOB / blood group / contact / guardian number, the office address
and contacts, the two rules, and the employee + principal signatures.

JDSD staff card (reference: "Nealesh Dalal, Professor"): white front
with the logo, a large photo, the name set vertically on the left edge
and the designation + department vertically on the right edge; the back
has the mark, address, the ID, the rules and the principal's signature.

Address, phone and website are the printed ones, hardcoded like the
student card — NOT `Institute.address` / `.phone`. Logos, the "Since
1988" mark, the principal's signature and the Avenir stand-in fonts are
shared with the student card (admissions/idcard_assets).
"""

from __future__ import annotations

from datetime import date

from fpdf import FPDF

from apps.common.pdf_theme import safe

from .models import Employee

CARD_W = 54.0
CARD_H = 85.0

#: Near-black of the JDIFT staff card front.
JDIFT_BLACK = (33, 31, 32)

#: Printed on the JDIFT staff card back, verbatim from the reference.
JDIFT_ADDRESS = (
    "No.18, Edward House,",
    "Brigade Road, Bengaluru - 560 001.",
)
JDIFT_OFFICE_CONTACTS = ("+91 99450 31100", "+91 94803 23232")


def _lib():
    """The student-card module: shared assets, fonts and helpers. Imported
    lazily so this module never participates in an app-load cycle."""
    from apps.admissions import services_idcard as lib
    return lib


# --- Data ---------------------------------------------------------------

class StaffCardData:
    def __init__(self, employee: Employee):
        self.employee = employee
        inst = employee.institute
        self.institute_code = (inst.code if inst else "").upper()

    @property
    def name(self) -> str:
        return self.employee.full_name.strip()

    @property
    def designation(self) -> str:
        obj = self.employee.designation
        return obj.name if obj else ""

    @property
    def department(self) -> str:
        obj = self.employee.department
        return obj.name if obj else ""

    @property
    def emp_code(self) -> str:
        return self.employee.emp_code or ""

    @property
    def dob(self) -> str:
        d: date | None = self.employee.dob
        return f"{d.day}/{d.month}/{d.year}" if d else ""

    @property
    def blood_group(self) -> str:
        return self.employee.blood_group or ""

    @property
    def contact(self) -> str:
        return self.employee.mobile_primary or ""

    @property
    def guardian_contact(self) -> str:
        return self.employee.mobile_alternate or ""

    def photo_bytes(self) -> bytes | None:
        photo = self.employee.photo
        if not photo:
            return None
        try:
            with photo.open("rb") as fh:
                return fh.read()
        except (FileNotFoundError, OSError, ValueError):
            return None


# --- JDIFT -----------------------------------------------------------------

def _jdift_strip(pdf: FPDF, top: float) -> None:
    """The white strip of the JDIFT card: cube lockup | Since 1988.
    Same artwork as the student card, placed under `top`."""
    lib = _lib()
    dy = top - 56.5  # student card's strip starts at 56.5
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.25)
    pdf.line(28.7, 59.0 + dy, 28.7, 80.7 + dy)

    pdf.image(str(lib._ASSETS / "jdift-cube.png"), x=11.5, y=59.4 + dy,
              w=10.2, h=10.2)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 7.2)
    pdf.set_stretching(78)
    pdf.set_xy(2, 70.2 + dy)
    pdf.cell(24.7, 2.8, "JD INSTITUTE OF", align="C")
    pdf.set_xy(2, 72.9 + dy)
    pdf.cell(24.7, 2.8, "FASHION TECHNOLOGY", align="C")
    pdf.set_stretching(100)
    pdf.set_font("Helvetica", "", 5.4)
    w1 = pdf.get_string_width("Welcome to Imagi")
    w2 = pdf.get_string_width("nation")
    x = 2 + (24.7 - (w1 + w2)) / 2
    pdf.set_xy(x, 76.0 + dy)
    pdf.cell(w1, 2.4, "Welcome to Imagi")
    pdf.set_text_color(*lib.JDIFT_MAGENTA)
    pdf.cell(w2, 2.4, "nation")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 5)
    pdf.set_xy(2, 79.0 + dy)
    pdf.cell(24.7, 2.4, "jdinstitute.edu.in", align="C")

    pdf.set_font("Times", "I", 8)
    pdf.set_xy(30.5, 61.2 + dy)
    pdf.cell(21, 3, "Since", align="C")
    pdf.image(str(lib._ASSETS / "since-1988.png"), x=31.4, y=64.0 + dy, w=17.0)
    pdf.set_line_width(0.25)
    pdf.line(31.4, 74.6 + dy, 48.4, 74.6 + dy)
    pdf.set_font("Helvetica", "", 7.4)
    wa = pdf.get_string_width("Leading ")
    pdf.set_font("Helvetica", "B", 7.4)
    wb = pdf.get_string_width("Change")
    x = 30.5 + (21 - (wa + wb)) / 2
    pdf.set_xy(x, 76.2 + dy)
    pdf.set_font("Helvetica", "", 7.4)
    pdf.cell(wa, 3, "Leading ")
    pdf.set_font("Helvetica", "B", 7.4)
    pdf.cell(wb, 3, "Change")


def _jdift_front(pdf: FPDF, d: StaffCardData) -> None:
    lib = _lib()
    pdf.add_page()
    pdf.set_fill_color(*JDIFT_BLACK)
    pdf.rect(0, 0, CARD_W, 60.0, style="F")

    lib._photo_slot(pdf, d.photo_bytes(), x=17.0, y=10.0, w=20.0, h=26.0)

    white = (255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    lib._centred(pdf, 39.5, safe(d.name), 10, style="B",
                 family="Helvetica", color=white, max_w=50)
    lib._centred(pdf, 44.5, safe(d.designation), 8.5, style="B",
                 family="Helvetica", color=white, max_w=50)
    lib._centred(pdf, 49.5, safe(f"Employee ID : {d.emp_code}"), 8,
                 style="B", family="Helvetica", color=white, max_w=50)

    _jdift_strip(pdf, top=60.0)


def _jdift_back(pdf: FPDF, d: StaffCardData) -> None:
    lib = _lib()
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 6.1)
    rows = (
        ("Date of Birth", d.dob),
        ("Blood Group", d.blood_group),
        ("Contact No", d.contact),
        ("Guardian No", d.guardian_contact),
    )
    y = 8.0
    for label, value in rows:
        pdf.set_xy(4, y)
        pdf.cell(19, 5.2, label)
        pdf.set_xy(23, y)
        pdf.cell(2, 5.2, ":")
        pdf.set_xy(25, y)
        pdf.cell(26, 5.2, safe(value))
        y += 5.2

    y += 2
    lines = (
        *JDIFT_ADDRESS,
        f"Contact : {JDIFT_OFFICE_CONTACTS[0]}",
        JDIFT_OFFICE_CONTACTS[1],
    )
    for line in lines:
        pdf.set_xy(2, y)
        pdf.cell(50, 4, line, align="C")
        y += 4

    pdf.set_font("Helvetica", "", 5.8)
    lib._numbered_rules(pdf, y + 3, 5.8, 2.9)

    # Signatures: employee (left, blank for pen) and principal (right).
    pdf.image(str(lib._ASSETS / "principal-signature.png"), x=35.0, y=69.5, w=11.0)
    pdf.set_font("Helvetica", "", 4.8)
    pdf.set_xy(2, 81)
    pdf.cell(23, 2, "Employee Signature", align="C")
    pdf.set_xy(29, 81)
    pdf.cell(23, 2, "Principal", align="C")


# --- JDSD ------------------------------------------------------------------

def _vertical(pdf: FPDF, x: float, bottom: float, text: str, size: float,
              max_len: float) -> None:
    """Text reading bottom-to-top, its foot at (x, bottom); the glyphs sit
    to the left of x."""
    size = _lib()._fit_size(pdf, text, max_len, size)
    with pdf.rotation(90, x=x, y=bottom):
        pdf.set_xy(x, bottom - size * 0.42)
        pdf.cell(max_len, size * 0.42, text)


def _jdsd_front(pdf: FPDF, d: StaffCardData) -> None:
    lib = _lib()
    pdf.add_page()
    pdf.image(str(lib._ASSETS / "jdsd-logo.png"), x=4.8, y=5.3, w=44.6)

    photo_x, photo_y, photo_w, photo_h = 7.0, 28.0, 38.0, 50.0
    lib._photo_slot(pdf, d.photo_bytes(), x=photo_x, y=photo_y, w=photo_w, h=photo_h)
    bottom = photo_y + photo_h

    # Name on the left edge, designation and department on the right.
    pdf.set_text_color(*lib.JDSD_GREY)
    pdf.set_font("AvenirM", "", 9)
    _vertical(pdf, photo_x - 1.4, bottom, d.name.upper(), 9, photo_h)

    pdf.set_font("AvenirM", "", 4.8)
    _vertical(pdf, photo_x + photo_w + 3.4, bottom, d.designation.upper(), 4.8, photo_h)
    _vertical(pdf, photo_x + photo_w + 6.2, bottom, d.department.upper(), 4.8, photo_h)

    lib._hrule(pdf, 81.0, x0=4.3, x1=CARD_W - 4.3, width=0.3, color=lib.JDSD_GREY)


def _jdsd_back(pdf: FPDF, d: StaffCardData) -> None:
    lib = _lib()
    pdf.add_page()
    pdf.image(str(lib._ASSETS / "jdsd-mark.png"), x=5.3, y=5.9, w=9.0)
    pdf.set_font("AvenirM", "", 8.6)
    pdf.set_text_color(*lib.JDSD_PINK)
    pdf.set_xy(16.4, 5.6)
    pdf.cell(35, 3.4, "JD SCHOOL OF DESIGN")
    pdf.set_font("AvenirM", "", 5.7)
    pdf.set_text_color(*lib.JDSD_GREY)
    y = 9.4
    for line in lib.JDSD_ADDRESS:
        pdf.set_xy(16.4, y)
        pdf.cell(35, 2.6, line)
        y += 2.55
    lib._hrule(pdf, 21.0, x0=5.0, x1=CARD_W - 5.0, width=0.3, color=lib.JDSD_GREY)

    lib._centred(pdf, 24.0, f"ID : {d.emp_code}", 8.6, family="AvenirM",
                 color=lib.JDSD_PINK)

    pdf.set_font("AvenirM", "", 6.2)
    pdf.set_text_color(*lib.JDSD_GREY)
    lib._numbered_rules(pdf, 50.0, 6.2, 2.6, x=3.5, width=CARD_W - 7)
    lib._hrule(pdf, 67.7, x0=4.3, x1=CARD_W - 4.3, width=0.3, color=lib.JDSD_GREY)

    pdf.image(str(lib._ASSETS / "principal-signature.png"), x=21.4, y=69.3, w=11.0)
    lib._centred(pdf, 80.0, "PRINCIPAL", 6.9, family="AvenirM", color=lib.JDSD_GREY)


# --- Entry point -----------------------------------------------------------

def render_id_card(employee: Employee) -> bytes:
    """One employee's card: a 2-page PDF (front, back), design by institute."""
    lib = _lib()
    pdf = FPDF(unit="mm", format=(CARD_W, CARD_H))
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)
    pdf.set_title("Employee ID card")
    lib._register_avenir(pdf)

    d = StaffCardData(employee)
    if d.institute_code == "JDSD":
        _jdsd_front(pdf, d)
        _jdsd_back(pdf, d)
    else:
        _jdift_front(pdf, d)
        _jdift_back(pdf, d)
    return bytes(pdf.output())
