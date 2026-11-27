"""Academic Transcript + Marks Card PDFs (fpdf2).

Ports of the two printed documents the legacy PHP ERP produced from
`academics/aget.php`:

- `academic_transcript.php`  -> **Academic Assessment Record** (the
  transcript), re-laid out in 2026-11 on the institute's 234 x 321 mm
  framed template and, from 2026-11-27, printed as ONE SHEET PER YEAR
  OF STUDY (semesters 1+2 = Year I, 3+4 = Year II, ...): logo and
  "Since 1988" artwork, program + year, the candidate's name /
  registration number / centre / year, two fixed Code / Course / Grade
  boxes, the eight-band O..F grade system and the scrutiny / principal
  signature block.
- `academic_report.php`      -> **Marks Card** ("Student Academic
  Record"): institute, student number + photo, name, program, batch,
  academic year, one Course / Grade table across every subject, then
  the A+ .. F grade system with comments.

Both score a subject on its marks alone (client rule 2026-11-24)::

    score = round((ia + ea) / (ia_max + ea_max) * 100)

Attendance is NOT part of the score — the legacy PHP folded present /
total into a 40 / 40 / 20 composite, which the client dropped. From
2026-11-24 to 2026-11-25 each row also printed an attendance %, and
the client then asked for that column to go too: neither document
mentions attendance any more. A subject with no IA or no EA on file
grades "NA". The two documents use *different* grade bands (below);
that is deliberate and matches the originals.

Only PUBLISHED marks appear. These are official documents handed to
the student, so a draft sheet never prints.
"""

from __future__ import annotations

import io
from pathlib import Path

from fpdf import FPDF

from apps.common.pdf_theme import logo_path, safe

from .models import MarksEntry

_ASSETS = Path(__file__).resolve().parent / "transcript_assets"
#: The legacy documents carried the JD Institute logo regardless of
#: institute. Used when `Institute.logo` is not on file.
_FALLBACK_LOGO = _ASSETS / "jdi-logo.png"

#: Headings and labels in the legacy documents: Word-export blue.
HEADING_BLUE = (0, 78, 129)
LABEL_BLUE = (11, 82, 148)
TABLE_HEAD_FILL = (199, 226, 250)

PAGE_W = 210.0
MARGIN = 15.0
BODY_W = PAGE_W - 2 * MARGIN

#: (lower bound, grade, grade points, printed range) — the Academic
#: Assessment Record scale. From the client's 2026-11-27 per-year
#: template ("monal y1"): eight bands, O at the top, P = exactly 40 %.
#: Replaces the legacy six-band A-F scale.
TRANSCRIPT_SCALE = (
    (90, "O", "10", "90% and Above"),
    (80, "A+", "9", "80% to 89.99%"),
    (70, "A", "8", "70% to 79.99%"),
    (60, "B+", "7", "60% to 69.99%"),
    (50, "B", "6", "50% to 59.99%"),
    (41, "C", "5", "41% to 49.99%"),
    (40, "P", "4", "40%"),
    (0, "F", "0", "Below 40%"),
)

#: (lower bound, grade, grade points, comment) — the Marks Card scale.
#: Legacy printed its legend with B and B+ swapped against the code
#: that assigned them; the code's order (B+ above B) is kept here.
MARKS_CARD_SCALE = (
    (85, "A+", "10.00", "Excellent"),
    (75, "A", "8.50", "Good"),
    (65, "B+", "7.50", "Average"),
    (55, "B", "6.50", "Fair"),
    (45, "C", "5.50", "Needs Improvement"),
    (0, "F", "0.00", "Fail"),
)


# --- Scoring ------------------------------------------------------------

def marks_score(entry: MarksEntry) -> int | None:
    """IA + EA as a percentage of IA max + EA max, rounded half up; None
    when either mark is missing or the maxima are zero. Attendance plays
    no part — see the module docstring."""
    if entry.ia_marks is None or entry.ea_marks is None:
        return None
    max_total = float(entry.ia_max or 0) + float(entry.ea_max or 0)
    if not max_total:
        return None
    score = (float(entry.ia_marks) + float(entry.ea_marks)) / max_total * 100
    return int(score + 0.5) if score >= 0 else -int(-score + 0.5)


def grade_for(score: int | None, scale) -> str:
    if score is None or score < 0 or score > 100:
        return "NA"
    for lower, grade, *_ in scale:
        if score >= lower:
            return grade
    return "NA"


def _graded_entries(student, *, only_published: bool):
    qs = (MarksEntry.objects
          .filter(student=student)
          .select_related("subject", "semester")
          .order_by("semester__number", "subject__code"))
    if only_published:
        qs = qs.filter(published=True)
    return [(m, marks_score(m)) for m in qs]


def _row(m: MarksEntry, score: int | None, scale) -> dict:
    return {
        "subject_code": m.subject.code,
        "subject_name": m.subject.name,
        "score": score,
        "grade": grade_for(score, scale),
    }


# --- Document data ------------------------------------------------------

def _context(student) -> dict:
    """Program / campus / batch / year the document prints, from the
    live enrollment (or the newest one) with the application as the
    fallback, as the ID card does."""
    from apps.admissions.services import current_enrollment

    enrollment = current_enrollment(student)
    program = (enrollment.program if enrollment else None) or student.program
    institute = (program.institute if program else None) or student.institute
    campus = (enrollment.campus if enrollment else None) or student.campus
    batch = enrollment.batch if enrollment else None
    year = (
        (enrollment.academic_year if enrollment else None)
        or student.academic_year
    )
    return {
        "institute": institute,
        "institute_name": institute.name if institute else "",
        "program": program,
        "program_name": program.name if program else "",
        "campus_name": (campus.city or campus.name) if campus else "",
        "batch_name": (batch.short_name or batch.name) if batch else "",
        "academic_year": year.code if year else "",
        "registration_no": (student.registration_number
                            or student.application_form_id or ""),
        "student_name": (student.student_name or "").strip(),
    }


def year_of_semester(number: int) -> int:
    """Year of study a semester belongs to: two semesters per year."""
    return (int(number) + 1) // 2


def roman(n: int) -> str:
    out = ""
    for value, sym in ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += sym
            n -= value
    return out


def transcript_document(student, *, only_published: bool = True) -> dict:
    """Semesters grouped by year of study. `semesters` is the flat list
    of semesters with graded rows; `years` is what the per-year sheets
    print: every semester the program defines for that year (so a
    semester with nothing published yet still gets its box), for each
    year that has at least one graded row."""
    ctx = _context(student)
    program = ctx.pop("program")
    by_num: dict[int, dict] = {}
    for m, score in _graded_entries(student, only_published=only_published):
        sem = m.semester
        bucket = by_num.setdefault(sem.number, {
            "semester_id": sem.id,
            "semester_number": sem.number,
            "semester_name": sem.name,
            "rows": [],
        })
        bucket["rows"].append(_row(m, score, TRANSCRIPT_SCALE))
    ctx["semesters"] = [by_num[n] for n in sorted(by_num)]

    defined = set(by_num)
    if program is not None:
        defined |= set(program.semesters.values_list("number", flat=True))
    years: dict[int, dict] = {}
    for n in sorted(defined):
        y = year_of_semester(n)
        years.setdefault(y, {"year": y, "label": f"Year {roman(y)}",
                             "semesters": []})
        years[y]["semesters"].append(by_num.get(n) or {
            "semester_id": None, "semester_number": n,
            "semester_name": f"Semester {n}", "rows": [],
        })
    ctx["years"] = [
        y for y in years.values()
        if any(s["rows"] for s in y["semesters"])
    ]
    return ctx


def marks_card_document(student, *, only_published: bool = True) -> dict:
    ctx = _context(student)
    ctx.pop("program")
    ctx["rows"] = [
        _row(m, score, MARKS_CARD_SCALE)
        for m, score in _graded_entries(student, only_published=only_published)
    ]
    return ctx


# --- Drawing helpers ----------------------------------------------------

def _new_pdf(title: str) -> FPDF:
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(MARGIN, MARGIN, MARGIN)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_title(title)
    pdf.add_page()
    return pdf


def _logo_file(institute) -> str | None:
    return logo_path(institute) or (
        str(_FALLBACK_LOGO) if _FALLBACK_LOGO.is_file() else None
    )


def _heading(pdf: FPDF, text: str, size: float, *, underline: bool = False,
             h: float | None = None) -> None:
    pdf.set_font("Helvetica", "BU" if underline else "B", size)
    pdf.set_text_color(*HEADING_BLUE)
    pdf.cell(BODY_W, h or size * 0.5, safe(text), align="C",
             new_x="LMARGIN", new_y="NEXT")


def _labelled(pdf: FPDF, label: str, value: str, *, size: float = 12,
              x: float | None = None, width: float = BODY_W) -> None:
    pdf.set_font("Helvetica", "", size)
    if x is not None:
        pdf.set_x(x)
    pdf.set_text_color(*LABEL_BLUE)
    lw = pdf.get_string_width(safe(label)) + 1
    pdf.cell(lw, size * 0.55, safe(label))
    pdf.set_text_color(0, 0, 0)
    pdf.cell(width - lw, size * 0.55, safe(value), new_x="LMARGIN",
             new_y="NEXT")


def _table(pdf: FPDF, headers: list[tuple[str, float, str]],
           rows: list[list[str]], *, x: float = MARGIN, size: float = 11,
           head_fill=None) -> None:
    """Bordered table starting at `x`. `headers` = (label, width mm,
    align)."""
    line_h = size * 0.6
    pdf.set_font("Helvetica", "B", size)
    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    if head_fill:
        pdf.set_fill_color(*head_fill)
    pdf.set_x(x)
    for label, w, align in headers:
        pdf.cell(w, line_h, safe(label), border=1, align=align,
                 fill=bool(head_fill))
    pdf.ln(line_h)
    pdf.set_font("Helvetica", "", size)
    for row in rows:
        if pdf.get_y() + line_h > pdf.page_break_trigger:
            pdf.add_page()
        pdf.set_x(x)
        for (_label, w, align), text in zip(headers, row):
            pdf.cell(w, line_h, _fit(pdf, safe(text), w), border=1,
                     align=align)
        pdf.ln(line_h)


def _fit(pdf: FPDF, text: str, width: float) -> str:
    usable = width - 2
    if pdf.get_string_width(text) <= usable:
        return text
    while text and pdf.get_string_width(text + "...") > usable:
        text = text[:-1]
    return text + "..." if text else ""


def _photo_image(data: bytes | None, w: float, h: float):
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


def _student_photo_bytes(student) -> bytes | None:
    photo = getattr(student, "photo", None)
    if not photo:
        return None
    try:
        with photo.open("rb") as fh:
            return fh.read()
    except (FileNotFoundError, OSError, ValueError):
        return None


# --- Academic Assessment Record (the transcript) -----------------------
#
# Layout from the client's 2026-11-27 per-year template ("monal y1"):
# a 234 x 321 mm sheet with a thick blue frame, a diagonal institute-name
# watermark, the logo lockup and "Since 1988" artwork centred at the
# top, the program + year title, the record title, the candidate block,
# then TWO fixed-height navy-headed Subject code / Course / Grade boxes
# (the year's two semesters), the eight-band grade system bottom-left,
# the scrutiny / principal signature block bottom-right, and a navy
# footer strip with the campus contact line.
#
# ONE SHEET PER YEAR OF STUDY (client decision 2026-11-27): Year I is
# semesters 1 + 2, Year II is 3 + 4, and so on. Every position below is
# measured off the template in mm; nothing floats.

T_PAGE_W, T_PAGE_H = 234.0, 321.0
T_NAVY = (24, 86, 158)
T_BLUE = (33, 104, 178)
T_FRAME_OUTER = (18, 62, 140)
T_FRAME_INNER = (41, 141, 212)
T_PINK = (221, 34, 133)
T_TEXT = (35, 31, 32)
T_RULE = (33, 104, 178)
T_WATERMARK = (228, 232, 238)

#: "Since 1988 / Leading Change" artwork printed beside the logo
#: (cropped from the client's template).
_ANNIVERSARY_ART = _ASSETS / "since-1988.png"
#: Printed under the logo lockup when the institute's own logo is used
#: (the bundled lockup already carries it).
TRANSCRIPT_WEBSITE = "jdinstitute.edu.in"
#: Names in the signature block. From the supplied template; change here
#: when the scrutineer or principal changes.
TRANSCRIPT_SCRUTINISED_BY = "Dr. Anusuya K"
TRANSCRIPT_PRINCIPAL = "Babu Rajendra Prasadh R"
#: Footer fallbacks when `Institute.address` / phone / email are blank.
TRANSCRIPT_CAMPUS_ADDRESS = "#18, Edward House, Brigade Road, Bangalore - 560001, India."
TRANSCRIPT_PHONE = "+91 80 22279927, +91 9901999903"
TRANSCRIPT_EMAIL = "jdfashion@jdindia.com"

# Table geometry (mm). Columns: code | course | grade.
_T_X0, _T_X1, _T_X2, _T_X3 = 22.6, 56.4, 190.6, 212.1
_T_STRIP_H = 6.7      # navy "SEMESTER n" strip
_T_HEAD_H = 6.5       # Subject code / Course / Grade header band
_T_ROW_PITCH = 5.45   # row baseline pitch at the template's five rows
#: (top, bottom) of the two semester boxes on a sheet.
_T_BOXES = ((105.1, 166.3), (166.3, 238.6))


def _tx(pdf: FPDF, baseline: float, text: str, *, x: float | None = None,
        center: float | None = None, right: float | None = None) -> None:
    """Put `text` with its baseline at `baseline`, left at `x`, centred
    on `center`, or ending at `right`."""
    text = safe(text)
    if center is not None:
        x = center - pdf.get_string_width(text) / 2
    elif right is not None:
        x = right - pdf.get_string_width(text)
    pdf.text(x or 0, baseline, text)


def _t_page(pdf: FPDF, watermark: str) -> None:
    """Frame + watermark shared by every sheet."""
    pdf.add_page()
    # Watermark: diagonal lines of the institute name, as on the template.
    pdf.set_text_color(*T_WATERMARK)
    pdf.set_font("Helvetica", "B", 7)
    unit = watermark + "   "
    # Long enough to cross the whole sheet diagonally from off-page left.
    repeats = max(2, int(420 / max(pdf.get_string_width(unit), 1.0)) + 1)
    line = unit * repeats
    with pdf.rect_clip(13.6, 13.6, T_PAGE_W - 27.2, T_PAGE_H - 27.2):
        for y in range(20, 480, 11):
            with pdf.rotation(38, -60, y):
                pdf.text(-60, y, line)
    # Frame: 9.0 .. 13.6 mm, darker outside, lighter inside.
    pdf.set_draw_color(*T_FRAME_OUTER)
    pdf.set_line_width(2.6)
    pdf.rect(10.3, 10.3, T_PAGE_W - 20.6, T_PAGE_H - 20.6)
    pdf.set_draw_color(*T_FRAME_INNER)
    pdf.set_line_width(2.0)
    pdf.rect(12.6, 12.6, T_PAGE_W - 25.2, T_PAGE_H - 25.2)


def _t_footer(pdf: FPDF, institute) -> None:
    address = " ".join(
        line.strip() for line in (getattr(institute, "address", "") or "").splitlines()
        if line.strip()
    ) or TRANSCRIPT_CAMPUS_ADDRESS
    phone = getattr(institute, "phone", "") or TRANSCRIPT_PHONE
    email = getattr(institute, "email", "") or TRANSCRIPT_EMAIL
    pdf.set_fill_color(*T_NAVY)
    pdf.rect(13.6, 298.7, T_PAGE_W - 27.2, 13.1, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "", 6)
    text = f"Campus :  {address}         Tel:  {phone}.        e-mail : {email}"
    _tx(pdf, 303.8, _fit(pdf, text, T_PAGE_W - 42), x=21.8)


def _t_header(pdf: FPDF, doc: dict, title: str) -> None:
    logo = _logo_file(doc["institute"])
    art = str(_ANNIVERSARY_ART) if _ANNIVERSARY_ART.is_file() else None
    try:
        if logo and art:
            pdf.image(logo, x=80, y=15, w=37, h=33, keep_aspect_ratio=True)
            pdf.set_draw_color(120, 130, 145)
            pdf.set_line_width(0.25)
            pdf.line(118.8, 17.6, 118.8, 53.8)
            pdf.image(art, x=121, y=15, w=39, h=37, keep_aspect_ratio=True)
        elif logo:
            pdf.image(logo, x=T_PAGE_W / 2 - 25, y=15, w=50, h=36,
                      keep_aspect_ratio=True)
    except Exception:  # noqa: BLE001 — a corrupt logo must not 500
        pass
    if logo and str(logo) != str(_FALLBACK_LOGO):
        pdf.set_text_color(*T_TEXT)
        pdf.set_font("Helvetica", "", 6.5)
        _tx(pdf, 52.0, TRANSCRIPT_WEBSITE, center=98.5)

    # Program + year of study, then the record title, each over a rule.
    pdf.set_text_color(3, 91, 168)
    pdf.set_font("Helvetica", "B", 13)
    _tx(pdf, 63.5, _fit(pdf, title, T_PAGE_W - 40), center=T_PAGE_W / 2)
    pdf.set_draw_color(*T_NAVY)
    pdf.set_line_width(0.35)
    pdf.line(38.8, 65.4, 195.4, 65.4)

    pdf.set_text_color(*T_PINK)
    pdf.set_font("Helvetica", "B", 15)
    _tx(pdf, 75.6, "ACADEMIC ASSESSMENT RECORD", center=T_PAGE_W / 2)
    pdf.set_draw_color(*T_PINK)
    pdf.set_line_width(0.3)
    pdf.line(47.6, 77.6, 185.0, 77.6)

    # Candidate block.
    def label(x, baseline, text):
        pdf.set_text_color(22, 81, 159)
        pdf.set_font("Helvetica", "B", 8.5)
        _tx(pdf, baseline, text, x=x)

    def value(x, baseline, text, width):
        pdf.set_text_color(*T_TEXT)
        pdf.set_font("Helvetica", "", 8)
        _tx(pdf, baseline, _fit(pdf, text, width), x=x)

    pdf.set_draw_color(*T_RULE)
    pdf.set_line_width(0.2)
    label(22.6, 88.7, "Name of the Candidate :")
    value(72.7, 87.6, doc["student_name"].upper(), 139)
    pdf.line(70.5, 88.2, 211.6, 88.2)

    label(22.6, 100.2, "Registration No.")
    label(57.5, 100.2, ":")
    value(61.7, 99.1, doc["registration_no"], 47)
    pdf.line(58.0, 99.8, 109.0, 99.8)
    label(110.2, 100.2, "Centre")
    label(123.3, 100.2, ":")
    value(127.9, 99.1, doc["campus_name"], 40)
    pdf.line(125.0, 99.8, 168.0, 99.8)
    label(168.8, 100.2, "Year")
    label(178.0, 100.2, ":")
    value(182.0, 99.1, doc["academic_year"], 30)
    pdf.line(180.0, 99.8, 212.1, 99.8)


def _t_semester_box(pdf: FPDF, title: str, rows, top: float, bottom: float) -> None:
    """One fixed-height navy-headed box. Rows have no horizontal rules;
    the pitch (then the font) shrinks when a semester carries more
    subjects than the template's five-row spacing fits."""
    pdf.set_draw_color(*T_RULE)
    pdf.set_line_width(0.25)
    pdf.set_fill_color(*T_NAVY)
    pdf.rect(_T_X0, top, _T_X3 - _T_X0, _T_STRIP_H, style="F")
    pdf.rect(_T_X0, top, _T_X3 - _T_X0, bottom - top)
    head_bottom = top + _T_STRIP_H + _T_HEAD_H
    pdf.line(_T_X0, head_bottom, _T_X3, head_bottom)
    pdf.line(_T_X1, top + _T_STRIP_H, _T_X1, bottom)
    pdf.line(_T_X2, top + _T_STRIP_H, _T_X2, bottom)

    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9.5)
    _tx(pdf, top + 5.0, title, center=(_T_X0 + _T_X3) / 2)

    pdf.set_text_color(0, 79, 159)
    pdf.set_font("Helvetica", "B", 7.6)
    head_base = head_bottom - 1.9
    _tx(pdf, head_base, "Subject code", x=_T_X0 + 4.0)
    _tx(pdf, head_base, "Course", x=_T_X1 + 4.0)
    _tx(pdf, head_base, "Grade", center=(_T_X2 + _T_X3) / 2)

    if not rows:
        return
    avail = bottom - head_bottom
    pitch = min(_T_ROW_PITCH, (avail - 2.0) / len(rows))
    size = 7.6 if pitch >= 4.0 else max(5.0, 7.6 * pitch / 4.0)
    pdf.set_font("Helvetica", "", size)
    # First baseline sits a little lower than one pitch (template: 10.8
    # mm under the header rule at the 5.45 pitch).
    baseline = head_bottom + min(10.8, pitch + 2.0) - (_T_ROW_PITCH - pitch) * 0.4
    for code, course, grade in rows:
        pdf.set_text_color(*T_TEXT)
        _tx(pdf, baseline, _fit(pdf, code, _T_X1 - _T_X0 - 6), x=_T_X0 + 4.0)
        _tx(pdf, baseline, _fit(pdf, course, _T_X2 - _T_X1 - 8), x=_T_X1 + 4.0)
        pdf.set_text_color(0, 0, 0)
        _tx(pdf, baseline, grade, center=(_T_X2 + _T_X3) / 2)
        baseline += pitch


def _t_grade_table(pdf: FPDF) -> None:
    x = (22.6, 34.2, 55.2, 72.3)
    top, head_h, pitch = 262.0, 4.3, 3.56
    pdf.set_draw_color(*T_RULE)
    pdf.set_line_width(0.2)
    pdf.set_fill_color(*T_NAVY)
    pdf.rect(x[0], top, x[3] - x[0], head_h, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 4.6)
    _tx(pdf, top + 3.1, "Grade", center=(x[0] + x[1]) / 2)
    _tx(pdf, top + 3.1, "Range", x=x[1] + 1.9)
    _tx(pdf, top + 3.1, "Grade Points", x=x[2] + 2.3)
    bottom = top + head_h + pitch * len(TRANSCRIPT_SCALE)
    pdf.rect(x[0], top, x[3] - x[0], bottom - top)
    for xx in x[1:3]:
        pdf.line(xx, top + head_h, xx, bottom)
    pdf.set_text_color(22, 81, 159)
    pdf.set_font("Helvetica", "", 4.8)
    y = top + head_h
    for _lower, grade, points, label in TRANSCRIPT_SCALE:
        y += pitch
        pdf.line(x[0], y, x[3], y)
        _tx(pdf, y - 1.0, grade, center=(x[0] + x[1]) / 2)
        _tx(pdf, y - 1.0, label, x=x[1] + 1.9)
        _tx(pdf, y - 1.0, points, center=(x[2] + x[3]) / 2)


def _t_bottom_block(pdf: FPDF, institute) -> None:
    """Grade system (left), principal (centre) and scrutineer (right),
    at the template's fixed positions."""
    pdf.set_text_color(22, 81, 159)
    pdf.set_font("Helvetica", "B", 7.5)
    _tx(pdf, 260.9, "GRADE SYSTEM", center=47.5)
    _t_grade_table(pdf)

    pdf.set_text_color(22, 81, 159)
    pdf.set_font("Helvetica", "B", 7.5)
    _tx(pdf, 271.8, "Scrutinised by", x=145.8)
    pdf.set_font("Helvetica", "", 7)
    _tx(pdf, 278.5, "Signature  :", x=145.8)
    pdf.set_draw_color(*T_RULE)
    pdf.set_line_width(0.2)
    pdf.line(164.0, 277.4, 212.1, 277.4)
    _tx(pdf, 288.0, "Name :", x=145.8)
    pdf.set_font("Helvetica", "B", 7.7)
    _tx(pdf, 287.6, TRANSCRIPT_SCRUTINISED_BY, x=171.5)

    # Principal: the institute's signature artwork when on file, else
    # the space is left clear for a wet signature.
    from apps.common.pdf_theme import signature_path
    if sig := signature_path(institute):
        try:
            pdf.image(sig, x=96.0, y=270.5, w=36, h=14, keep_aspect_ratio=True)
        except Exception:  # noqa: BLE001
            pass
    pdf.set_text_color(22, 81, 159)
    pdf.set_font("Helvetica", "B", 7.2)
    _tx(pdf, 289.5, TRANSCRIPT_PRINCIPAL, center=116.5)
    pdf.set_font("Helvetica", "", 6.8)
    _tx(pdf, 294.4, "Principal", center=116.5)


def _t_sheet(pdf: FPDF, doc: dict, year: dict, watermark: str) -> None:
    institute = doc["institute"]
    _t_page(pdf, watermark)
    _t_footer(pdf, institute)
    title = f"{safe(doc['program_name']).upper()} - {year['label']}"
    _t_header(pdf, doc, title)
    for sem, (top, bottom) in zip(year["semesters"], _T_BOXES):
        _t_semester_box(
            pdf, f"SEMESTER {sem['semester_number']}",
            [(r["subject_code"], r["subject_name"], r["grade"])
             for r in sem["rows"]],
            top, bottom,
        )
    _t_bottom_block(pdf, institute)


class NoTranscriptYear(LookupError):
    """The requested year of study has no published marks."""


def render_transcript_pdf(student, *, only_published: bool = True,
                          year: int | None = None) -> bytes:
    """One sheet per year of study with published marks; `year` limits
    the PDF to that year's sheet (NoTranscriptYear when it has none)."""
    doc = transcript_document(student, only_published=only_published)
    watermark = safe(doc["institute_name"]).upper() or "JD INSTITUTE"
    years = doc["years"]
    if year is not None:
        years = [y for y in years if y["year"] == year]
        if not years:
            raise NoTranscriptYear(year)

    pdf = FPDF(orientation="P", unit="mm", format=(T_PAGE_W, T_PAGE_H))
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)
    pdf.set_title("Academic Assessment Record")

    if not years:
        # Nothing published: a blank Year I sheet with a note.
        empty = {"year": 1, "label": "Year I", "semesters": [
            {"semester_number": 1, "rows": []},
            {"semester_number": 2, "rows": []},
        ]}
        _t_sheet(pdf, doc, empty, watermark)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(90, 90, 90)
        _tx(pdf, 140.0, "No published marks on record.",
            center=(_T_X0 + _T_X3) / 2)
    for y in years:
        _t_sheet(pdf, doc, y, watermark)

    return bytes(pdf.output())


# --- Marks Card ("Student Academic Record") -----------------------------

def render_marks_card_pdf(student, *, only_published: bool = True) -> bytes:
    doc = marks_card_document(student, only_published=only_published)
    pdf = _new_pdf("Marks Card")

    # The logo lockup is wide (it carries the institute name), so it sits
    # centred above the heading rather than beside it as in the legacy
    # Word export, where the two overlapped.
    if logo := _logo_file(doc["institute"]):
        try:
            pdf.image(logo, x=PAGE_W / 2 - 14, y=10, h=28)
        except Exception:  # noqa: BLE001
            pass
    pdf.set_y(42)
    _heading(pdf, doc["institute_name"], 20, underline=True, h=11)
    _heading(pdf, "Student Academic Record", 15, h=9)
    pdf.ln(6)

    # Photo on the right, the detail block beside it.
    photo_w, photo_h = 25.0, 32.0
    photo_x = PAGE_W - MARGIN - photo_w
    photo_y = pdf.get_y()
    img = _photo_image(_student_photo_bytes(student), photo_w, photo_h)
    if img is not None:
        pdf.image(img, x=photo_x, y=photo_y, w=photo_w, h=photo_h)
    else:
        pdf.set_fill_color(235, 235, 235)
        pdf.rect(photo_x, photo_y, photo_w, photo_h, style="F")
        pdf.set_text_color(130, 130, 130)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_xy(photo_x, photo_y + photo_h / 2 - 2)
        pdf.cell(photo_w, 4, "NO PHOTO", align="C")
        pdf.set_y(photo_y)

    text_w = BODY_W - photo_w - 6
    _labelled(pdf, "Student Number: ", doc["registration_no"], width=text_w)
    _labelled(pdf, "Student Name: ", doc["student_name"], width=text_w)
    _labelled(pdf, "Program: ", doc["program_name"], width=text_w)
    _labelled(pdf, "Batch: ", doc["batch_name"], width=text_w)
    _labelled(pdf, "Academic Year: ", doc["academic_year"], width=text_w)
    pdf.set_y(max(pdf.get_y(), photo_y + photo_h) + 6)

    headers = [("Course", 140, "L"), ("Grade", 40, "C")]
    if doc["rows"]:
        _table(pdf, headers,
               [[r["subject_name"], r["grade"]] for r in doc["rows"]])
    else:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(BODY_W, 7, "No published marks on record.",
                 new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Current GPA / Cumulative GPA (legacy printed both as N/A). The
    # overall attendance that used to sit on this line was dropped with
    # the column (client, 2026-11-25).
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*LABEL_BLUE)
    pdf.cell(28, 6, "Current GPA: ")
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 6, "N/A", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*LABEL_BLUE)
    pdf.cell(34, 6, "Cumulative GPA: ")
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 6, "N/A", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    if pdf.get_y() + 60 > pdf.page_break_trigger:
        pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(BODY_W, 7, "Grades", align="C", new_x="LMARGIN", new_y="NEXT")
    legend = [("Grade", 25, "L"), ("Range", 40, "L"),
              ("Grade Points", 35, "L"), ("Comments", 60, "L")]
    rows = []
    for i, (lower, grade, points, comment) in enumerate(MARKS_CARD_SCALE):
        upper = 100 if i == 0 else MARKS_CARD_SCALE[i - 1][0]
        rows.append([grade, f"{lower:.2f} - {upper:.2f}", points, comment])
    _table(pdf, legend, rows, x=MARGIN + (BODY_W - 160) / 2,
           head_fill=TABLE_HEAD_FILL)

    return bytes(pdf.output())
