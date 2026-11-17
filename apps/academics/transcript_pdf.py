"""Academic Transcript + Marks Card PDFs (fpdf2).

Ports of the two printed documents the legacy PHP ERP produced from
`academics/aget.php`:

- `academic_transcript.php`  -> **Academic Assessment Record** (the
  transcript), re-laid out in 2026-11 on the institute's 234 x 321 mm
  framed template: logo, program, the candidate's name / registration
  number / centre / year, one Code / Course / Grade table per semester,
  the A-F grade system and the scrutiny / principal signature block.
- `academic_report.php`      -> **Marks Card** ("Student Academic
  Record"): institute, student number + photo, name, program, batch,
  academic year, one Course / Grade table across every subject, the
  attendance %, then the A+ .. F grade system with comments.

Both score a subject the legacy way::

    score = round(ia / ia_max * 40 + ea / ea_max * 40 + present / total * 20)

where present / total is the student's attendance in that subject
across every class marked (not just the semester). A subject with no
IA, no EA or no attendance on file grades "NA", as it did in PHP. The
two documents use *different* grade bands (below); that is deliberate
and matches the originals.

Only PUBLISHED marks appear. These are official documents handed to
the student, so a draft sheet never prints.
"""

from __future__ import annotations

import io
from pathlib import Path

from django.db.models import Count, Q
from fpdf import FPDF

from apps.common.pdf_theme import logo_path, safe

from .attendance_reports import PRESENT_LIKE
from .models import Attendance, MarksEntry

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

#: (lower bound, grade, grade points) — the Academic Transcript scale.
TRANSCRIPT_SCALE = (
    (90, "A", "10"),
    (80, "B", "9"),
    (70, "C", "8"),
    (60, "D", "7"),
    (50, "E", "6"),
    (0, "F", "5"),
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

def _attendance_by_subject(student) -> dict[int, tuple[int, int]]:
    """{subject_id: (present, total)} over every class marked for the
    student, the way the legacy query grouped `attendance_master`."""
    rows = (
        Attendance.objects
        .filter(student=student)
        .values("schedule_slot__subject_id")
        .annotate(
            present=Count("id", filter=Q(status__in=PRESENT_LIKE)),
            total=Count("id"),
        )
    )
    return {r["schedule_slot__subject_id"]: (r["present"], r["total"])
            for r in rows}


def legacy_score(entry: MarksEntry, present: int, total: int) -> int | None:
    """The legacy 40 / 40 / 20 composite, rounded; None when any part
    is missing (PHP's NULL arithmetic)."""
    if entry.ia_marks is None or entry.ea_marks is None:
        return None
    if not entry.ia_max or not entry.ea_max or not total:
        return None
    score = (
        float(entry.ia_marks) / float(entry.ia_max) * 40
        + float(entry.ea_marks) / float(entry.ea_max) * 40
        + present / total * 20
    )
    # PHP round(): halves away from zero.
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
    att = _attendance_by_subject(student)
    out = []
    for m in qs:
        present, total = att.get(m.subject_id, (0, 0))
        out.append((m, legacy_score(m, present, total), present, total))
    return out


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
        "program_name": program.name if program else "",
        "campus_name": (campus.city or campus.name) if campus else "",
        "batch_name": (batch.short_name or batch.name) if batch else "",
        "academic_year": year.code if year else "",
        "registration_no": (student.registration_number
                            or student.application_form_id or ""),
        "student_name": (student.student_name or "").strip(),
    }


def transcript_document(student, *, only_published: bool = True) -> dict:
    ctx = _context(student)
    by_sem: dict[int, dict] = {}
    for m, score, _p, _t in _graded_entries(student, only_published=only_published):
        sem = m.semester
        bucket = by_sem.setdefault(sem.id, {
            "semester_id": sem.id,
            "semester_number": sem.number,
            "semester_name": sem.name,
            "rows": [],
        })
        bucket["rows"].append({
            "subject_code": m.subject.code,
            "subject_name": m.subject.name,
            "score": score,
            "grade": grade_for(score, TRANSCRIPT_SCALE),
        })
    ctx["semesters"] = sorted(by_sem.values(),
                              key=lambda b: b["semester_number"])
    return ctx


def marks_card_document(student, *, only_published: bool = True) -> dict:
    ctx = _context(student)
    rows = []
    tot_present = tot_total = 0
    for m, score, present, total in _graded_entries(
            student, only_published=only_published):
        tot_present += present
        tot_total += total
        rows.append({
            "subject_code": m.subject.code,
            "subject_name": m.subject.name,
            "score": score,
            "grade": grade_for(score, MARKS_CARD_SCALE),
        })
    ctx["rows"] = rows
    ctx["attendance_pct"] = (
        int(tot_present / tot_total * 100 + 0.5) if tot_total else None
    )
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
# Layout from the 2026 "Academic Assessment Record" template: a
# 234 x 321 mm sheet with a thick blue frame, a faint diagonal
# institute-name watermark, the logo lockup centred at the top, the
# program and record titles, the candidate block, one navy-headed
# Code / Course / Grade table per semester, the grade system bottom-left
# and the scrutiny / principal signature block bottom-right, closed by
# a navy footer strip with the campus contact line.

T_PAGE_W, T_PAGE_H = 234.0, 321.0
T_NAVY = (24, 86, 158)
T_BLUE = (33, 104, 178)
T_PINK = (194, 62, 127)
T_TEXT = (35, 45, 58)
T_RULE = (120, 145, 170)
T_WATERMARK = (239, 242, 246)

#: Optional "Since 1988" artwork printed beside the logo when present.
_ANNIVERSARY_ART = _ASSETS / "since-1988.png"
#: Printed under the logo lockup.
TRANSCRIPT_WEBSITE = "jdinstitute.edu.in"
#: Names in the signature block. From the supplied template; change here
#: when the scrutineer or principal changes.
TRANSCRIPT_SCRUTINISED_BY = "Dr. Anusuya K"
TRANSCRIPT_PRINCIPAL = "Babu Rajendra Prasadh R"
#: Footer fallbacks when `Institute.address` / phone / email are blank.
TRANSCRIPT_CAMPUS_ADDRESS = "#18, Edward Brigade Road, Bangalore - 560001, India."
TRANSCRIPT_PHONE = "+91 80 22279927, +91 9901999903"
TRANSCRIPT_EMAIL = "jdfashion@jdindia.com"

_T_TABLE_X, _T_TABLE_W = 22.0, 190.0
_T_ROW_H = 6.6
_T_TABLES_TOP = 96.0
#: Tables may run down to here; the grade / signature block is fixed below.
_T_TABLES_BOTTOM = 240.0
_T_CONT_TOP = 20.0   # first table on a continuation page


def _t_page(pdf: FPDF, watermark: str) -> None:
    """Frame, watermark and footer-less chrome shared by every page."""
    pdf.add_page()
    pdf.set_draw_color(*T_BLUE)
    pdf.set_line_width(4.2)
    pdf.rect(5.5, 5.5, T_PAGE_W - 11, T_PAGE_H - 11)
    pdf.set_text_color(*T_WATERMARK)
    pdf.set_font("Helvetica", "B", 8)
    for y in range(58, 275, 18):
        for x in range(-35, 255, 55):
            with pdf.rotation(38, x + 20, y):
                pdf.text(x, y, watermark)


def _t_footer(pdf: FPDF, institute) -> None:
    address = " ".join(
        line.strip() for line in (getattr(institute, "address", "") or "").splitlines()
        if line.strip()
    ) or TRANSCRIPT_CAMPUS_ADDRESS
    phone = getattr(institute, "phone", "") or TRANSCRIPT_PHONE
    email = getattr(institute, "email", "") or TRANSCRIPT_EMAIL
    pdf.set_fill_color(*T_NAVY)
    pdf.rect(9, 308, T_PAGE_W - 18, 7, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "", 5.7)
    pdf.set_xy(12, 309.5)
    pdf.cell(T_PAGE_W - 24, 4,
             safe(f"Campus: {address}    Tel: {phone}    e-mail: {email}"),
             align="C")


def _t_header(pdf: FPDF, doc: dict) -> None:
    logo = _logo_file(doc["institute"])
    art = str(_ANNIVERSARY_ART) if _ANNIVERSARY_ART.is_file() else None
    try:
        if logo and art:
            pdf.image(logo, x=79, y=10, w=30, h=27, keep_aspect_ratio=True)
            pdf.set_draw_color(120, 130, 145)
            pdf.set_line_width(0.25)
            pdf.line(117, 10, 117, 39)
            pdf.image(art, x=122, y=10, w=35, h=27, keep_aspect_ratio=True)
        elif logo:
            # No anniversary artwork on file: the logo alone, centred.
            pdf.image(logo, x=T_PAGE_W / 2 - 25, y=10, w=50, h=27,
                      keep_aspect_ratio=True)
    except Exception:  # noqa: BLE001 — a corrupt logo must not 500
        pass

    pdf.set_text_color(*T_NAVY)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(75, 37)
    pdf.cell(84, 3.5, TRANSCRIPT_WEBSITE, align="C")

    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(18, 46)
    pdf.cell(T_PAGE_W - 36, 7, _fit(pdf, safe(doc["program_name"]).upper(),
                                   T_PAGE_W - 36), align="C")
    pdf.set_draw_color(*T_NAVY)
    pdf.set_line_width(0.35)
    pdf.line(38, 54, T_PAGE_W - 38, 54)

    pdf.set_text_color(*T_PINK)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_xy(20, 58)
    pdf.cell(T_PAGE_W - 40, 8, "ACADEMIC ASSESSMENT RECORD", align="C")
    pdf.set_draw_color(*T_PINK)
    pdf.line(38, 67, T_PAGE_W - 38, 67)

    def label(x, y, w, text):
        pdf.set_text_color(*T_NAVY)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_xy(x, y)
        pdf.cell(w, 6, text)

    def value(x, y, w, text, size=7.5):
        pdf.set_text_color(*T_TEXT)
        pdf.set_font("Helvetica", "", size)
        pdf.set_xy(x, y)
        pdf.cell(w, 6, _fit(pdf, safe(text), w))

    label(20, 73, 42, "Name of the Candidate:")
    value(62, 73, 145, doc["student_name"], size=8)
    pdf.set_draw_color(*T_RULE)
    pdf.set_line_width(0.2)
    pdf.line(62, 80, 207, 80)

    label(20, 84, 38, "Registration No.:")
    value(58, 84, 61, doc["registration_no"])
    label(122, 84, 20, "Centre:")
    value(142, 84, 35, doc["campus_name"])
    label(179, 84, 15, "Year:")
    value(194, 84, 25, doc["academic_year"])
    pdf.line(20, 91, 219, 91)


def _t_table_height(rows: int) -> float:
    return 7.3 + 7 + rows * _T_ROW_H


def _t_semester_table(pdf: FPDF, title: str, rows, x: float, y: float,
                      width: float) -> float:
    code_w, grade_w = 36.0, 22.0
    course_w = width - code_w - grade_w
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    pdf.set_fill_color(*T_NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(x, y)
    pdf.cell(width, 7.3, safe(title), border=1, fill=True, align="C")
    y += 7.3

    pdf.set_fill_color(245, 248, 252)
    pdf.set_text_color(*T_NAVY)
    pdf.set_font("Helvetica", "B", 7.6)
    pdf.set_xy(x, y)
    pdf.cell(code_w, 7, "Subject code", border=1, fill=True)
    pdf.cell(course_w, 7, "Course", border=1, fill=True)
    pdf.cell(grade_w, 7, "Grade", border=1, fill=True, align="C")
    y += 7

    pdf.set_text_color(*T_TEXT)
    pdf.set_font("Helvetica", "", 7.6)
    for code, course, grade in rows:
        pdf.set_xy(x, y)
        pdf.cell(code_w, _T_ROW_H, _fit(pdf, safe(code), code_w), border=1)
        pdf.cell(course_w, _T_ROW_H, _fit(pdf, safe(course), course_w),
                 border=1)
        pdf.cell(grade_w, _T_ROW_H, safe(grade), border=1, align="C")
        y += _T_ROW_H
    return y


def _t_grade_table(pdf: FPDF, x: float, y: float, row_h: float = 4.4) -> None:
    widths = (18, 33, 22)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.2)
    pdf.set_fill_color(*T_NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 5.8)
    pdf.set_xy(x, y)
    for w, head in zip(widths, ("Grade", "Range", "Grade Points")):
        pdf.cell(w, 6, head, border=1, fill=True, align="C")
    y += 6
    pdf.set_text_color(*T_TEXT)
    pdf.set_font("Helvetica", "", 6)
    for i, (lower, grade, points) in enumerate(TRANSCRIPT_SCALE):
        upper = 100 if i == 0 else TRANSCRIPT_SCALE[i - 1][0]
        pdf.set_xy(x, y)
        for w, text in zip(widths, (grade, f"{lower:.2f} - {upper:.2f}", points)):
            pdf.cell(w, row_h, text, border=1, align="C")
        y += row_h


def _t_bottom_block(pdf: FPDF, institute) -> None:
    """Grade system (left) and the scrutiny / principal signatures
    (right), at the template's fixed positions above the footer."""
    pdf.set_text_color(*T_NAVY)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_xy(22, 245)
    pdf.cell(73, 5, "GRADE SYSTEM", align="C")
    _t_grade_table(pdf, 22, 250)

    pdf.set_text_color(*T_NAVY)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_xy(145, 250)
    pdf.cell(70, 5, "Scrutinised by")
    pdf.set_draw_color(*T_RULE)
    pdf.set_line_width(0.2)
    pdf.line(145, 259, 215, 259)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(145, 260)
    pdf.cell(70, 5, "Signature :")
    pdf.set_xy(145, 268)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.cell(70, 5, safe("Name : " + TRANSCRIPT_SCRUTINISED_BY))

    # Principal: the institute's signature artwork when on file, else
    # the space is left clear for a wet signature.
    from apps.common.pdf_theme import signature_path
    if sig := signature_path(institute):
        try:
            pdf.image(sig, x=95, y=263, w=35, h=15, keep_aspect_ratio=True)
        except Exception:  # noqa: BLE001
            pass
    pdf.set_xy(92, 284)
    pdf.set_text_color(*T_NAVY)
    pdf.set_font("Helvetica", "B", 7)
    pdf.cell(42, 5, safe(TRANSCRIPT_PRINCIPAL), align="C")
    pdf.set_xy(99, 289)
    pdf.set_font("Helvetica", "", 6.5)
    pdf.cell(28, 4, "Principal", align="C")


def render_transcript_pdf(student, *, only_published: bool = True) -> bytes:
    doc = transcript_document(student, only_published=only_published)
    institute = doc["institute"]
    watermark = safe(doc["institute_name"]).upper() or "JD INSTITUTE"

    pdf = FPDF(orientation="P", unit="mm", format=(T_PAGE_W, T_PAGE_H))
    pdf.set_margins(0, 0, 0)
    pdf.set_auto_page_break(False)
    pdf.set_title("Academic Assessment Record")

    _t_page(pdf, watermark)
    _t_footer(pdf, institute)
    _t_header(pdf, doc)

    y = _T_TABLES_TOP
    if not doc["semesters"]:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(90, 90, 90)
        pdf.set_xy(_T_TABLE_X, y)
        pdf.cell(_T_TABLE_W, 7, "No published marks on record.", align="C")
    for sem in doc["semesters"]:
        height = _t_table_height(len(sem["rows"]))
        if y + height > _T_TABLES_BOTTOM and y != _T_CONT_TOP:
            # Too tall for the space left: continue on a fresh page.
            _t_page(pdf, watermark)
            _t_footer(pdf, institute)
            y = _T_CONT_TOP
        y = _t_semester_table(
            pdf, f"SEMESTER {sem['semester_number']}",
            [(r["subject_code"], r["subject_name"], r["grade"])
             for r in sem["rows"]],
            _T_TABLE_X, y, _T_TABLE_W,
        ) + 6
    if y > _T_TABLES_BOTTOM:
        _t_page(pdf, watermark)
        _t_footer(pdf, institute)
    _t_bottom_block(pdf, institute)

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

    headers = [("Course", 150, "L"), ("Grade", 30, "C")]
    if doc["rows"]:
        _table(pdf, headers, [[r["subject_name"], r["grade"]]
                              for r in doc["rows"]])
    else:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(BODY_W, 7, "No published marks on record.",
                 new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Current GPA ..... Attendance (legacy printed GPA as N/A).
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*LABEL_BLUE)
    pdf.cell(28, 6, "Current GPA: ")
    pdf.set_text_color(0, 0, 0)
    pdf.cell(62, 6, "N/A")
    pdf.set_text_color(*LABEL_BLUE)
    pdf.cell(26, 6, "Attendance: ")
    pdf.set_text_color(200, 0, 0)
    att = doc["attendance_pct"]
    pdf.cell(0, 6, f"{att}%" if att is not None else "N/A",
             new_x="LMARGIN", new_y="NEXT")
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
