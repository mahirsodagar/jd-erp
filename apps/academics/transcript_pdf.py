"""Academic Transcript + Marks Card PDFs (fpdf2).

Ports of the two printed documents the legacy PHP ERP produced from
`academics/aget.php`:

- `academic_transcript.php`  -> **Academic Transcript**: logo, program,
  the candidate's registration number / name / centre, then one
  Code / Course / Grade table per semester, then the A-F grade system.
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


# --- Academic Transcript ------------------------------------------------

def render_transcript_pdf(student, *, only_published: bool = True) -> bytes:
    doc = transcript_document(student, only_published=only_published)
    pdf = _new_pdf("Academic Transcript")

    if logo := _logo_file(doc["institute"]):
        try:
            pdf.image(logo, x=PAGE_W / 2 - 20, y=12, h=40)
        except Exception:  # noqa: BLE001 — a corrupt logo must not 500
            pass
    pdf.set_y(56)
    _heading(pdf, doc["program_name"], 20, underline=True, h=11)
    _heading(pdf, "ACADEMIC TRANSCRIPT", 16, h=9)
    pdf.ln(5)

    _labelled(pdf, "Registration No. ", doc["registration_no"])
    _labelled(pdf, "Name of the Candidate: ", doc["student_name"])
    _labelled(pdf, "Center: ", doc["campus_name"])
    pdf.ln(5)

    headers = [("Code", 35, "L"), ("Course", 120, "L"), ("Grade", 25, "C")]
    if not doc["semesters"]:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(BODY_W, 7, "No published marks on record.",
                 new_x="LMARGIN", new_y="NEXT")
    for sem in doc["semesters"]:
        if pdf.get_y() + 30 > pdf.page_break_trigger:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(BODY_W, 8, safe(f"Semester {sem['semester_number']}"),
                 new_x="LMARGIN", new_y="NEXT")
        _table(pdf, headers, [
            [r["subject_code"], r["subject_name"], r["grade"]]
            for r in sem["rows"]
        ])
        pdf.ln(4)

    # Grade system legend.
    if pdf.get_y() + 60 > pdf.page_break_trigger:
        pdf.add_page()
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(BODY_W, 7, "Grade System", align="C", new_x="LMARGIN",
             new_y="NEXT")
    legend = [("Grade", 35, "L"), ("Range", 45, "L"), ("Grade Points", 40, "L")]
    rows = []
    for i, (lower, grade, points) in enumerate(TRANSCRIPT_SCALE):
        upper = 100 if i == 0 else TRANSCRIPT_SCALE[i - 1][0]
        rows.append([grade, f"{lower:.2f} - {upper:.2f}", points])
    _table(pdf, legend, rows, x=MARGIN + (BODY_W - 120) / 2,
           head_fill=TABLE_HEAD_FILL)

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
