"""No Due Certificate — two-page clearance sheet (client template, 2026-11-18).

Page 1: certificate statement + departmental clearance grid
        (Account Dept, Library, one row per subject, overall attendance,
        class mentor's remark).
Page 2: hall-ticket receipt + three signature lines.

Layout, wording and row heights follow the client's fpdf2 template
file verbatim; only the data plumbing is ours. Everything comes from
the certificate snapshot (see `cert_service.build_snapshot`), so an
already-issued certificate re-renders identically.
"""

from fpdf import FPDF

# cert_service imports this module lazily inside the renderer, so the
# top-level import here is not circular.
from .cert_service import _safe

# Column widths (mm) and header labels from the client template.
_WIDTHS = [62, 38, 35, 32, 33]
_HEADERS = [
    "Department/Module", "Faculty",
    "Blue Book/\nRecord\nSubmission\nYes/No",
    "Attendance %", "Remarks/Signature",
]

# Grid origin and the vertical budget below the header row. The client
# template fits 7 subject rows at 13 mm; more subjects shrink the row
# height so the sheet stays on one page.
_GRID_X, _GRID_Y = 5, 43
_HEADER_H = 22
_MIN_SUBJECT_ROWS = 7
# Client template had 64 mm here; trimmed on request (2026-11-18).
_ACCOUNT_ROW_H = 18
_SUBJECT_ROW_H = 13
_PAGE_BOTTOM = 285


class _NoDuePDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(0, 0, 0)
        self.set_auto_page_break(False)

    def draw_grid(self, rows, x=_GRID_X, y=_GRID_Y):
        xx = x
        for head, w in zip(_HEADERS, _WIDTHS):
            self.rect(xx, y, w, _HEADER_H)
            self.set_xy(xx, y + 1)
            self.set_font("Helvetica", "B", 7.5)
            self.multi_cell(w, 4.5, head, align="C",
                            new_x="RIGHT", new_y="TOP")
            xx += w
        y += _HEADER_H
        for row in rows:
            rh = float(row.get("row_height", 12))
            vals = [row.get("department", ""), row.get("faculty", ""),
                    row.get("blue_book", ""), row.get("attendance", ""),
                    row.get("remarks", "")]
            xx = x
            for i, (value, w) in enumerate(zip(vals, _WIDTHS)):
                self.rect(xx, y, w, rh)
                self.set_xy(xx + 1.5, y + 1.5)
                self.set_font("Helvetica", "B" if i == 0 else "", 7.2)
                self.multi_cell(w - 3, 3.7, _safe(value), align="L")
                xx += w
            y += rh
        return y


def _fmt_pct(v) -> str:
    if v is None or v == "":
        return ""
    try:
        return f"{float(v):.0f}%"
    except (TypeError, ValueError):
        return str(v)


def build_rows(no_dues: dict) -> list[dict]:
    """Turn the snapshot's `no_dues` block into grid rows."""
    subjects = no_dues.get("subjects") or []
    n = max(len(subjects), _MIN_SUBJECT_ROWS)
    # Fixed rows: Account 18 + Library 9 + overall 9 + mentor 9 + 9 + 18.
    fixed = _ACCOUNT_ROW_H + 9 + 9 + 9 + 9 + 18
    avail = _PAGE_BOTTOM - _GRID_Y - _HEADER_H - fixed
    row_h = min(_SUBJECT_ROW_H, max(avail / n, 6))

    rows = [
        {"department": "Account Dept.", "faculty": "", "blue_book": "",
         "attendance": "", "remarks": no_dues.get("accounts_remark", ""),
         "row_height": _ACCOUNT_ROW_H},
        {"department": "Library", "faculty": "", "blue_book": "",
         "attendance": "", "remarks": "", "row_height": 9},
    ]
    for s in subjects:
        rows.append({
            "department": s.get("name", ""),
            "faculty": s.get("faculty", ""),
            "blue_book": "",
            "attendance": _fmt_pct(s.get("attendance_pct")),
            "remarks": "",
            "row_height": row_h,
        })
    for _ in range(n - len(subjects)):
        rows.append({"department": "", "faculty": "", "blue_book": "",
                     "attendance": "", "remarks": "", "row_height": row_h})
    mentor = no_dues.get("class_mentor", "")
    rows += [
        {"department": "Overall attendance %", "faculty": "",
         "blue_book": "",
         "attendance": _fmt_pct(no_dues.get("overall_attendance_pct")),
         "remarks": "", "row_height": 9},
        {"department": "Class Mentor's Remark", "faculty": mentor,
         "blue_book": "", "attendance": "", "remarks": "", "row_height": 9},
        {"department": "", "faculty": "", "blue_book": "",
         "attendance": "", "remarks": "", "row_height": 9},
        {"department": "Class Mentor's Remark", "faculty": "",
         "blue_book": "", "attendance": "", "remarks": "", "row_height": 18},
    ]
    return rows


def render_no_dues_pdf(certificate) -> bytes:
    snap = certificate.snapshot or {}
    student = snap.get("student", {})
    enrl = snap.get("enrollment", {})
    nd = snap.get("no_dues", {})
    institute = snap.get("institute", {}).get("name") or "JD Institute"

    pdf = _NoDuePDF()

    # Page 1: certificate statement and clearance table
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(10, 8)
    pdf.cell(190, 6, _safe(institute), align="C")
    pdf.set_xy(10, 15)
    pdf.cell(190, 7, "No Due Certificate", align="C")
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_xy(10, 22)
    issued = certificate.issued_at.strftime("%d-%m-%Y") if certificate.issued_at else ""
    # No certificate number on this sheet (client, 2026-11-25); the
    # number stays on the record and in the file name.
    pdf.cell(190, 5, _safe(f"Date: {issued}"), align="C")

    pdf.set_font("Helvetica", "", 8.5)
    name = student.get("name") or "_________________________________"
    enrollment_no = (student.get("registration_number")
                     or student.get("application_form_id")
                     or "____________")
    course = enrl.get("program") or "________________________"
    semester = nd.get("semester") or "_____"
    pdf.set_xy(6, 29)
    pdf.multi_cell(198, 5.5, _safe(
        f"This is to certify that Mr./Ms. {name}    "
        f"Enrollment Number {enrollment_no}"
    ))
    pdf.set_xy(6, 35)
    pdf.multi_cell(198, 5.5, _safe(
        f"of {course}, Semester {semester} has no dues from the following "
        "departments, hall ticket can be issued."
    ))

    pdf.draw_grid(build_rows(nd))

    # Page 2: hall-ticket receipt and signatures
    pdf.add_page()
    ticket = nd.get("hall_ticket_number") or "________________"
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(10, 35)
    pdf.multi_cell(190, 7, _safe(
        f"I {name} have Received the Original Hall Ticket Number {ticket} "
        "for the examination"
    ))

    y = 255
    for label, x, w in [
        ("Signature Of the Student", 8, 55),
        ("Head of the Dept", 77, 55),
        ("Principal/Vice Principal", 145, 57),
    ]:
        pdf.line(x, y, x + w, y)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_xy(x, y + 3)
        pdf.cell(w, 6, label, align="C")

    return bytes(pdf.output(dest="S"))
