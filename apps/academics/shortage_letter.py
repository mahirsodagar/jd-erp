"""Shortage of Attendance letter (Attendance Report → Batch-Wise).

A one-page letter to the parent of a student below 75% overall, printed
on letterhead (so the top of the page is left blank). Follows the
client's "Updated Format of shortage of attendance" PDF, which replaced
the legacy academics/aget.php:3778 wording. Legacy only offered it to
JD School of Design; here every institute gets it, signed for the
student's own institute and campus city.

The percentage is taken from `batch_wise_report` with the same filters
the user is looking at, so the letter always matches the table.
"""

from datetime import date

from fpdf import FPDF, FontFace

from apps.admissions.models import Enrollment

from .attendance_reports import batch_wise_report
from .cert_service import _safe

FONT = "Times"
# Letter body size / line height — sized so the full letter fits one
# A4 page under the letterhead, as in the client's format.
SIZE = 11
LINE = 5.5


def _pct_text(pct: float) -> str:
    return f"{pct:.2f}".rstrip("0").rstrip(".")


def _address(s) -> str:
    parts = [s.current_address,
             getattr(s.current_city, "name", ""),
             getattr(s.current_state, "name", "")]
    text = ", ".join(p.strip() for p in parts if p and p.strip())
    if s.current_pincode:
        text = f"{text} - {s.current_pincode}" if text else s.current_pincode
    return text


def shortage_rows(*, batch, from_date=None, to_date=None, semester=None,
                  student_id=None) -> tuple[list[dict], list[dict]]:
    """(subjects, batch-wise rows flagged `shortage`), optionally one
    student."""
    report = batch_wise_report(batch=batch, from_date=from_date,
                               to_date=to_date, semester=semester)
    rows = [r for r in report["rows"] if r["shortage"]]
    if student_id is not None:
        rows = [r for r in rows if r["student_id"] == student_id]
    return report["subjects"], rows


def _period(from_date: date | None, as_of: date) -> str:
    till = as_of.strftime("%d-%m-%y")
    if from_date:
        return f"{from_date.strftime('%d-%m-%y')} to {till}"
    return f"till {till}"


def _summary(pdf: FPDF, *, batch, rows: list[dict], period: str):
    """Closing page of the bulk PDF: every student below 75%."""
    pdf.add_page()
    pdf.set_font(FONT, "B", 14)
    pdf.cell(0, 8, "Attendance Report - Students below 75%", align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT, "", 11)
    pdf.cell(0, 7, _safe(f"Batch: {batch.name}    Period: {period}"),
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font(FONT, "", 10)
    with pdf.table(col_widths=(10, 30, 60, 30, 20),
                   text_align=("CENTER", "LEFT", "LEFT", "CENTER", "RIGHT"),
                   line_height=6) as table:
        table.row(["#", "App ID", "Student", "Present / Total", "Overall %"])
        for i, r in enumerate(sorted(rows, key=lambda r: r["overall_pct"]),
                              start=1):
            table.row([str(i), _safe(r["application_form_id"] or "-"),
                       _safe(r["name"]),
                       f"{r['total_present']} / {r['total_marked']}",
                       f"{_pct_text(r['overall_pct'])}%"])


_ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
          "XI", "XII"]


def _roman(n: int) -> str:
    return _ROMAN[n] if 0 < n < len(_ROMAN) else str(n)


def _low_subjects(subjects: list[dict], row: dict) -> list[tuple[str, str]]:
    """(subject name, pct text) for every taught subject under 75%,
    lowest first."""
    low = [(subj["name"], row["cells"][subj["id"]]["pct"])
           for subj in subjects
           if row["cells"][subj["id"]]["total"]
           and row["cells"][subj["id"]]["pct"] < 75]
    return [(name, f"{_pct_text(pct)}%")
            for name, pct in sorted(low, key=lambda x: x[1])]


def _letter(pdf: FPDF, *, enrollment, subjects: list[dict], row: dict,
            as_of: date):
    """The client's "Updated Format of shortage of attendance" letter:
    ref, address, subject line, body, low-subject table, Principal's
    sign-off."""
    s = enrollment.student
    program = enrollment.program
    institute = getattr(program, "institute", None) or s.institute
    city = getattr(enrollment.batch.campus, "city", "") or ""
    semester = _roman(enrollment.semester.number)
    female = s.gender == "F"
    title = "Ms." if female else "Mr."
    pronoun = "her" if female else "his"

    pdf.add_page()
    # Letterhead space, as legacy (four blank paragraphs).
    pdf.set_y(45)
    pdf.set_font(FONT, "", SIZE)
    pdf.cell(0, LINE, _safe(f"{institute.name}/Attnc/"), align="R",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    pdf.set_font(FONT, "B", SIZE)
    pdf.cell(0, LINE, "To,", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, LINE, _safe(s.father_name or "The Parent / Guardian"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT, "", SIZE)
    addr = _address(s)
    if addr:
        pdf.multi_cell(120, LINE, _safe(addr), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font(FONT, "B", SIZE)
    pdf.multi_cell(0, LINE, _safe(f"Subject: Attendance Shortage – "
                               f"{program.name}, Semester {semester}"),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.cell(0, LINE, "Dear Parent,", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font(FONT, "", SIZE)

    para = dict(w=0, h=LINE, align="J", markdown=True,
                new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(text=_safe(
        f"This is to inform you that your ward, **{title} {s.student_name}**, "
        f"studying in **Semester {semester}, {program.name}, "
        f"{enrollment.batch.name}**, has secured overall "
        f"**{_pct_text(row['overall_pct'])}% attendance as on "
        f"{as_of.day} {as_of.strftime('%B %Y')}**. As per the University "
        f"guidelines, a student is required to maintain a **minimum of 75% "
        f"attendance and 40% Internal Assessment marks in each subject** to "
        f"be eligible to appear for the University examinations, including "
        f"both **Theory and Practical examinations**."
    ), **para)
    pdf.ln(4)
    pdf.multi_cell(text=_safe(
        f"You are therefore requested to ensure that your ward attends all "
        f"classes regularly and improves {pronoun} attendance to meet the "
        f"prescribed requirement. **If the required attendance and Internal "
        f"Assessment criteria are not fulfilled, the student may not be "
        f"permitted to appear for the University Examination. The College "
        f"shall not be responsible for any academic loss arising due to "
        f"shortage of attendance or failure to meet the prescribed "
        f"eligibility requirements.**"
    ), **para)
    pdf.ln(4)

    low = _low_subjects(subjects, row)
    if low:
        pdf.multi_cell(text="The subject-wise attendance details for "
                            "subjects with lower attendance are given below "
                            "for your reference:", **para)
        pdf.ln(4)
        with pdf.table(width=100, col_widths=(50, 50), align="LEFT",
                       line_height=6, padding=(0, 6),
                       headings_style=FontFace(emphasis="BOLD")) as table:
            table.row(["Subject", "Attendance"])
            for name, pct in low:
                table.row([_safe(name), pct])
        pdf.ln(4)

    pdf.multi_cell(text="You are requested to take this matter seriously "
                        "and advise your ward to attend all classes "
                        "regularly from now onwards.", **para)
    pdf.multi_cell(text="For any clarification regarding attendance or "
                        "examination eligibility, kindly meet the **HoD / "
                        "Vice-Principal / Principal**.", **para)
    pdf.ln(4)
    pdf.set_font(FONT, "B", SIZE)
    pdf.cell(0, LINE, "Thanking you,", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, LINE, "Principal", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(FONT, "", SIZE)
    pdf.cell(0, LINE, _safe(institute.name), new_x="LMARGIN", new_y="NEXT")
    if city:
        pdf.cell(0, LINE, _safe(city), new_x="LMARGIN", new_y="NEXT")


def render_shortage_letters(*, batch, subjects: list[dict], rows: list[dict],
                            as_of: date | None = None, from_date=None,
                            summary: bool = False) -> bytes:
    """One letter per row (subjects/rows from `shortage_rows`), each
    listing that student's subjects under 75%. `summary` adds a
    closing page listing every row — only for the bulk PDF, so a single
    parent's letter never shows other students."""
    as_of = as_of or date.today()
    period = _period(from_date, as_of)
    enrollments = {
        e.student_id: e
        for e in Enrollment.objects.filter(
            batch=batch, status=Enrollment.Status.ACTIVE,
            student_id__in=[r["student_id"] for r in rows],
        ).select_related(
            "student", "student__institute", "student__current_city",
            "student__current_state", "program", "program__institute",
            "program__university", "semester", "batch", "batch__campus",
        )
    }
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.set_auto_page_break(auto=True, margin=12)
    for r in rows:
        e = enrollments.get(r["student_id"])
        if e is not None:
            _letter(pdf, enrollment=e, subjects=subjects, row=r,
                    as_of=as_of)
    if summary:
        _summary(pdf, batch=batch, rows=rows, period=period)
    return bytes(pdf.output())
