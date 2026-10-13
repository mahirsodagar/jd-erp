"""Shortage of Attendance letter (Attendance Report → Batch-Wise).

Port of legacy academics/aget.php:3778 ("format of shortage of
attendance.pdf"): a one-page letter to the parent of a student below
75% overall, printed on letterhead (so the top of the page is left
blank). Legacy only offered it to JD School of Design and hard-coded
"Bengaluru City University"; here every institute gets it, with the
student's own institute and their program's university.

The percentage is taken from `batch_wise_report` with the same filters
the user is looking at, so the letter always matches the table.
"""

from datetime import date

from fpdf import FPDF, FontFace

from apps.admissions.models import Enrollment

from .attendance_reports import batch_wise_report
from .cert_service import _safe

FONT = "Times"


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


def _student_report(pdf: FPDF, *, subjects: list[dict], row: dict,
                    period: str):
    """Subject-wise attendance of the letter's student, under the
    signatures."""
    pdf.ln(10)
    pdf.set_font(FONT, "B", 12)
    pdf.cell(0, 7, _safe(f"Attendance Report ({period})"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font(FONT, "", 10)
    with pdf.table(col_widths=(20, 80, 30, 20),
                   text_align=("LEFT", "LEFT", "CENTER", "RIGHT"),
                   line_height=6) as table:
        table.row(["Code", "Subject", "Present / Total", "%"])
        for subj in subjects:
            c = row["cells"][subj["id"]]
            if not c["total"]:
                continue
            table.row([_safe(subj["code"]), _safe(subj["name"]),
                       f"{c['present']} / {c['total']}",
                       f"{_pct_text(c['pct'])}%"])
        table.row(["", "Overall",
                   f"{row['total_present']} / {row['total_marked']}",
                   f"{_pct_text(row['overall_pct'])}%"],
                  style=FontFace(emphasis="BOLD"))
    pdf.set_font(FONT, "", 12)


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


def _letter(pdf: FPDF, *, enrollment, pct: float, as_of: date):
    s = enrollment.student
    program = enrollment.program
    university = getattr(getattr(program, "university", None), "name", "")
    institute = getattr(program, "institute", None) or s.institute

    pdf.add_page()
    # Letterhead space, as legacy (four blank paragraphs).
    pdf.set_y(45)
    pdf.set_font(FONT, "", 12)
    pdf.cell(0, 7, _safe(f"{institute.name}/Attnc/"), align="R",
             new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, _safe(f"Date: {as_of.strftime('%d-%m-%y')}"), align="R",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.cell(0, 7, "To,", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, _safe(s.father_name or "The Parent / Guardian"),
             new_x="LMARGIN", new_y="NEXT")
    addr = _address(s)
    if addr:
        pdf.multi_cell(110, 6, _safe(addr), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    pdf.cell(0, 7, "Dear Parent,", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    exam = (f"{university} Examination" if university
            else "the University Examination")
    body = (
        f"This is to inform you that your ward **{s.student_name}** studying "
        f"in Semester {enrollment.semester.number} {enrollment.batch.name}, "
        f"has only **{_pct_text(pct)}%** of attendance till "
        f"{as_of.strftime('%d-%m-%y')}. He/she will **not be eligible for "
        f"{exam}** in case he/she fails to obtain minimum **75% attendance "
        f"and 40% Internal Marks** in each Subject. As per University "
        f"guidelines such students shall not be allowed to write the "
        f"examination (Practical and Theory). The College shall not be "
        f"responsible for any academic losses."
    )
    pdf.multi_cell(0, 7.5, _safe(body), align="J", markdown=True,
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.multi_cell(0, 7, "Kindly meet the HoD / Vice-Principal / Principal "
                         "for further clarifications.",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.cell(0, 7, "Thanking you,", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(24)
    pdf.cell(95, 7, "Class Mentor")
    pdf.cell(0, 7, "HoD / Vice Principal / Principal", align="R",
             new_x="LMARGIN", new_y="NEXT")


def render_shortage_letters(*, batch, subjects: list[dict], rows: list[dict],
                            as_of: date | None = None, from_date=None,
                            summary: bool = False) -> bytes:
    """One letter per row (subjects/rows from `shortage_rows`), each
    ending with that student's subject-wise attendance. `summary` adds a
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
            "program__university", "semester", "batch",
        )
    }
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(25, 20, 25)
    pdf.set_auto_page_break(auto=True, margin=20)
    for r in rows:
        e = enrollments.get(r["student_id"])
        if e is not None:
            _letter(pdf, enrollment=e, pct=r["overall_pct"], as_of=as_of)
            _student_report(pdf, subjects=subjects, row=r, period=period)
    if summary:
        _summary(pdf, batch=batch, rows=rows, period=period)
    return bytes(pdf.output())
