"""Course Completion Certificate — client "CCC UG/PG" template (2026-11-19).

Layout, geometry and typography are measured from the client's
original PDF (A4 596 x 842 pt, Bookman Old Style) and kept verbatim
from the fpdf2 template they supplied; only the data plumbing is ours.
Everything comes from the certificate snapshot (see
`cert_service.build_snapshot`), so an already-issued certificate
re-renders identically.

Header block (UUCMS / AISHE codes, phone, e-mail, footer address,
principal) is the JD School of Design letterhead from the template.
Other institutes get a neutral header until the client supplies theirs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fpdf import FPDF

from .bonafide_pdf import FONT_CANDIDATES
from .cert_service import _safe

_SEED_ASSETS = Path(__file__).resolve().parents[1] / "master" / "seed_assets"


@dataclass(frozen=True)
class DocumentConfig:
    page_width: float = 596.0
    page_height: float = 842.0

    margin_left: float = 72.0
    margin_right: float = 75.5
    margin_top: float = 72.0
    margin_bottom: float = 50.0

    body_left_x: float = 76.50
    body_width: float = 444.00
    right_edge_x: float = 520.50

    header_start_y: float = 72.42
    header_line_height: float = 12.15
    header_font_size: float = 9.0

    divider_x1: float = 75.00
    divider_x2: float = 520.00
    header_divider_y: float = 189.50
    footer_divider_y: float = 760.50
    divider_line_width: float = 0.75
    divider_color: Tuple[int, int, int] = (136, 136, 136)

    ref_line_y: float = 222.89
    reg_line_y: float = 237.74
    title_y: float = 286.48
    body_start_y: float = 355.43
    body_line_height: float = 28.17
    note_gap_after_body: float = 12.00
    note_min_y: float = 478.29

    principal_name_y: float = 700.62
    principal_title_y: float = 714.71
    footer_text_y: float = 777.62

    ref_font_size: float = 11.0
    title_font_size: float = 18.0
    body_font_size: float = 12.0
    note_font_size: float = 9.0
    signoff_font_size: float = 12.0
    footer_font_size: float = 10.0

    text_color: Tuple[int, int, int] = (0, 0, 0)
    link_color: Tuple[int, int, int] = (17, 85, 204)

    @property
    def content_width(self) -> float:
        return self.page_width - self.margin_left - self.margin_right


DEFAULT_CONFIG = DocumentConfig()

# Exact bounding boxes from the source PDF (pt).
IMAGE_SLOTS: Dict[str, Dict[str, float]] = {
    # The template box (x 440.25, w 63.75) was drawn for a portrait mark;
    # the institute logos are landscape (~2.5:1) and came out ~25pt tall,
    # so the slot is widened to 110pt with the same right edge (504pt).
    "logo": {"x": 394.00, "y": 57.65, "w": 110.00, "h": 44.00},
    "signature": {"x": 77.25, "y": 641.39, "w": 84.00, "h": 48.00},
    "seal": {"x": 334.50, "y": 656.88, "w": 164.25, "h": 98.00},
}

# Letterhead text per institute code. JDSD is verbatim from the client
# template; anything else prints a neutral header.
INSTITUTE_LETTERHEAD: Dict[str, Dict[str, object]] = {
    "JDSD": {
        "header_lines": [
            "Office of the Principal",
            "Affiliated to Dr MS Bengaluru City University",
            "UUCMS :- P20GDQ0095",
            "Code Code 3007",
            "AISHE Code:- C-20714",
            "9845653000",
        ],
        "email": "principal@jdinstitute.edu.in",
        "principal_name": "PROF. BR PRASAD",
        "principal_title": "PRINCIPAL",
        "footer_address": ("No 18, Edward House, Brigade Road, Shanthala Nagar, "
                           "Bengaluru, Karnataka 560001"),
        "logo": _SEED_ASSETS / "jdsd-logo.png",
    },
}


def _letterhead(institute_code: str, institute_name: str,
                affiliation: str) -> Dict[str, object]:
    code = (institute_code or "").upper()
    if code in INSTITUTE_LETTERHEAD:
        return INSTITUTE_LETTERHEAD[code]
    lines = ["Office of the Principal"]
    if affiliation:
        lines.append(affiliation)
    logo = _SEED_ASSETS / f"{code.lower()}-logo.png"
    return {
        "header_lines": lines,
        "email": "",
        "principal_name": "",
        "principal_title": "PRINCIPAL",
        "footer_address": institute_name,
        "logo": logo if logo.is_file() else None,
    }


class CourseCompletionCertificatePDF(FPDF):
    def __init__(self, config: DocumentConfig = DEFAULT_CONFIG,
                 font_paths: Optional[Dict[str, str]] = None) -> None:
        super().__init__(orientation="P", unit="pt",
                         format=(config.page_width, config.page_height))
        self.config = config
        self.font_family_name = "Times"
        self.unicode_font = False
        self.set_margins(config.margin_left, config.margin_top, config.margin_right)
        self.set_auto_page_break(auto=False)
        self.c_margin = 0.0
        self._configure_fonts(font_paths)

    def _configure_fonts(self, font_paths: Optional[Dict[str, str]]) -> None:
        candidates = list(FONT_CANDIDATES)
        if font_paths and font_paths.get("regular") and font_paths.get("bold"):
            candidates.insert(0, ("CustomSerif", font_paths["regular"], font_paths["bold"]))
        for family, reg, bold in candidates:
            if os.path.isfile(reg) and os.path.isfile(bold):
                self.add_font(family, "", reg)
                self.add_font(family, "B", bold)
                self.font_family_name = family
                self.unicode_font = True
                return
        self.font_family_name = "Times"

    def txt(self, text: str) -> str:
        return text if self.unicode_font else _safe(text)

    def draw_text_line(self, text: str, x: float, y: float, size: float,
                       style: str = "", align: str = "L",
                       width: Optional[float] = None,
                       line_height: Optional[float] = None,
                       color: Optional[Tuple[int, int, int]] = None,
                       link: str = "") -> float:
        self.set_text_color(*(color or self.config.text_color))
        self.set_font(self.font_family_name, style, size)
        w = width if width is not None else self.config.content_width
        h = line_height if line_height is not None else size * 1.2
        self.set_xy(x, y)
        self.cell(w, h, self.txt(text), border=0, align=align, link=link)
        return y + h

    def draw_horizontal_line(self, x1: float, y: float, x2: float,
                             line_width: float = 0.75,
                             color: Tuple[int, int, int] = (136, 136, 136)) -> None:
        self.set_draw_color(*color)
        self.set_line_width(line_width)
        self.line(x1, y, x2, y)

    def draw_image(self, path, x: float, y: float, w: float) -> None:
        """Fit the image to the slot width, keeping aspect; skip if missing."""
        if path and os.path.isfile(str(path)):
            self.image(str(path), x=x, y=y, w=w)

    def draw_justified_rich_paragraph(self, segments: List[Tuple[str, str]],
                                      x: float, y: float, width: float,
                                      font_size: float, line_height: float,
                                      justify: bool = True) -> float:
        """Mixed '' / 'B' spans, fully justified on all but the last line."""
        self.set_text_color(*self.config.text_color)

        raw_parts: List[Tuple[str, str, bool]] = []
        pending_space = False
        for seg_text, seg_style in segments:
            seg_text = self.txt(seg_text)
            i, n = 0, len(seg_text)
            while i < n:
                if seg_text[i].isspace():
                    pending_space = True
                    while i < n and seg_text[i].isspace():
                        i += 1
                else:
                    start = i
                    while i < n and not seg_text[i].isspace():
                        i += 1
                    raw_parts.append((seg_text[start:i], seg_style, pending_space))
                    pending_space = False

        clusters: List[List[Tuple[str, str, float]]] = []
        for word, style, has_space_before in raw_parts:
            self.set_font(self.font_family_name, style, font_size)
            w = self.get_string_width(word)
            if not clusters or has_space_before:
                clusters.append([(word, style, w)])
            else:
                clusters[-1].append((word, style, w))

        def cluster_w(c):
            return sum(item[2] for item in c)

        safe_clusters: List[List[Tuple[str, str, float]]] = []
        for cluster in clusters:
            if cluster_w(cluster) <= width:
                safe_clusters.append(cluster)
                continue
            for text, style, _ in cluster:
                self.set_font(self.font_family_name, style, font_size)
                buf = ""
                for ch in text:
                    if buf and self.get_string_width(buf + ch) > width:
                        safe_clusters.append([(buf, style, self.get_string_width(buf))])
                        buf = ch
                    else:
                        buf += ch
                if buf:
                    safe_clusters.append([(buf, style, self.get_string_width(buf))])

        self.set_font(self.font_family_name, "", font_size)
        base_space = self.get_string_width(" ")
        lines: List[List[List[Tuple[str, str, float]]]] = []
        line: List[List[Tuple[str, str, float]]] = []
        line_w = 0.0
        for cluster in safe_clusters:
            cw = cluster_w(cluster)
            needed = cw if not line else base_space + cw
            if line and line_w + needed > width:
                lines.append(line)
                line, line_w = [cluster], cw
            else:
                line.append(cluster)
                line_w += needed
        if line:
            lines.append(line)

        cur_y = y
        for idx, line_clusters in enumerate(lines):
            last = idx == len(lines) - 1
            gaps = len(line_clusters) - 1
            words_w = sum(cluster_w(c) for c in line_clusters)
            gap_w = ((width - words_w) / gaps
                     if justify and not last and gaps > 0 else base_space)
            cur_x = x
            for c_idx, cluster in enumerate(line_clusters):
                for text, style, tw in cluster:
                    self.set_font(self.font_family_name, style, font_size)
                    self.set_xy(cur_x, cur_y)
                    self.cell(tw, font_size * 1.15, text, border=0, align="L")
                    cur_x += tw
                if c_idx < gaps:
                    cur_x += gap_w
            cur_y += line_height
        return cur_y


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
def build_course_completion_certificate(data: Dict[str, str],
                                        images: Optional[Dict[str, object]] = None,
                                        config: DocumentConfig = DEFAULT_CONFIG,
                                        font_paths: Optional[Dict[str, str]] = None) -> bytes:
    """Render the certificate from a flat dict and return PDF bytes.

    Keys: ref_prefix, ccc_number, registration_number, title,
    student_name, university, exam, degree, course, header_lines (list),
    email, principal_name, principal_title, footer_address.
    Images: logo, signature, seal (paths; missing ones are skipped).
    """
    d = {k: v for k, v in data.items() if v is not None}
    img = images or {}

    pdf = CourseCompletionCertificatePDF(config=config, font_paths=font_paths)
    pdf.set_title("COURSE COMPLETION CERTIFICATE")
    pdf.set_author(str(d.get("institute_name") or "JD School of Design"))
    pdf.add_page()

    # 1. Top-left letterhead block
    cur_y = config.header_start_y
    for line in d.get("header_lines", []):
        pdf.draw_text_line(str(line), config.margin_left, cur_y,
                           config.header_font_size, width=260.0,
                           line_height=config.header_line_height)
        cur_y += config.header_line_height
    email = str(d.get("email") or "")
    if email:
        pdf.set_font(pdf.font_family_name, "", config.header_font_size)
        email_w = pdf.get_string_width(email)
        pdf.draw_text_line(email, config.margin_left, cur_y,
                           config.header_font_size, width=email_w,
                           line_height=config.header_line_height,
                           color=config.link_color, link=f"mailto:{email}")
        pdf.draw_horizontal_line(config.margin_left,
                                 cur_y + config.header_font_size + 1.2,
                                 config.margin_left + email_w,
                                 line_width=0.6, color=config.link_color)

    # 2. Top-right logo
    s = IMAGE_SLOTS["logo"]
    pdf.draw_image(img.get("logo"), s["x"], s["y"], s["w"])

    # 3. Header divider
    pdf.draw_horizontal_line(config.divider_x1, config.header_divider_y,
                             config.divider_x2, config.divider_line_width,
                             config.divider_color)

    # 4. Reference and registration numbers (right-aligned, bold)
    ref_w = config.right_edge_x - config.margin_left
    pdf.draw_text_line(f"{d.get('ref_prefix', 'JDSD|CCC|')}{d.get('ccc_number', '')}",
                       config.margin_left, config.ref_line_y,
                       config.ref_font_size, style="B", align="R",
                       width=ref_w, line_height=14.0)
    pdf.draw_text_line(f"Reg. No:- {d.get('registration_number', '')}",
                       config.margin_left, config.reg_line_y,
                       config.ref_font_size, style="B", align="R",
                       width=ref_w, line_height=14.0)

    # 5. Title
    pdf.draw_text_line("COURSE COMPLETION CERTIFICATE", 0.0, config.title_y,
                       config.title_font_size, style="B", align="C",
                       width=config.page_width, line_height=22.0)

    # 6. Body
    university = str(d.get("university", ""))
    body = [
        ("This is to certify that ", ""),
        (f"{d.get('title', '')} {d.get('student_name', '')}".strip(), "B"),
        (" has successfully completed the course of studies approved by "
         f"the {university} held in ", ""),
        (str(d.get("exam", "")), "B"),
        (f" and has successfully completed the {d.get('degree', '')} under "
         "the discipline of ", ""),
        (str(d.get("course", "")), "B"),
    ]
    y_after = pdf.draw_justified_rich_paragraph(
        body, config.body_left_x, config.body_start_y, config.body_width,
        config.body_font_size, config.body_line_height,
    )

    # 7. Original-certificate note
    note_y = max(config.note_min_y, y_after + config.note_gap_after_body)
    pdf.draw_text_line(f"Original Certificate will be issued by the {university}",
                       config.body_left_x, note_y, config.note_font_size,
                       align="C", width=config.body_width, line_height=12.0)

    # 8. Signature, principal, seal
    s = IMAGE_SLOTS["signature"]
    pdf.draw_image(img.get("signature"), s["x"], s["y"], s["w"])
    pdf.draw_text_line(str(d.get("principal_name", "")), config.margin_left,
                       config.principal_name_y, config.signoff_font_size,
                       style="B", width=220.0, line_height=14.0)
    pdf.draw_text_line(str(d.get("principal_title", "PRINCIPAL")),
                       config.margin_left, config.principal_title_y,
                       config.signoff_font_size, width=220.0, line_height=14.0)
    s = IMAGE_SLOTS["seal"]
    pdf.draw_image(img.get("seal"), s["x"], s["y"], s["w"])

    # 9. Footer divider and address
    pdf.draw_horizontal_line(config.divider_x1, config.footer_divider_y,
                             config.divider_x2, config.divider_line_width,
                             config.divider_color)
    pdf.draw_text_line(str(d.get("footer_address", "")), 0.0,
                       config.footer_text_y, config.footer_font_size,
                       align="C", width=config.page_width, line_height=13.0)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Snapshot -> template data
# ---------------------------------------------------------------------------
def completion_data_from_certificate(certificate) -> Tuple[Dict[str, object], Dict[str, object]]:
    snap = certificate.snapshot or {}
    student = snap.get("student", {})
    enrl = snap.get("enrollment", {})
    inst = snap.get("institute", {})
    code = inst.get("code", "")

    gender = (student.get("gender") or "").upper()
    title = "Ms." if gender == "F" else "Mr."

    # The ERP has no exam-session field. Staff may type it into the
    # request's purpose (e.g. "May 2026"); otherwise the academic year.
    exam = (certificate.purpose or "").strip() \
        or enrl.get("academic_year_full") or enrl.get("academic_year", "")

    affiliation = enrl.get("id_card_affiliation", "")
    university = enrl.get("university", "")
    if not university and affiliation:
        university = affiliation.replace("Affiliated to", "").strip()

    lh = _letterhead(code, inst.get("name", ""), affiliation)
    data: Dict[str, object] = {
        "institute_name": inst.get("name", ""),
        "ref_prefix": f"{(code or 'JD').upper()}|CCC|",
        "ccc_number": certificate.certificate_no or "",
        "registration_number": (student.get("registration_number")
                                or student.get("application_form_id") or ""),
        "title": title,
        "student_name": student.get("name", ""),
        "university": university,
        "exam": exam,
        "degree": enrl.get("degree") or enrl.get("degree_type") or "",
        "course": enrl.get("program", ""),
        "header_lines": lh["header_lines"],
        "email": lh["email"],
        "principal_name": lh["principal_name"],
        "principal_title": lh["principal_title"],
        "footer_address": lh["footer_address"],
    }
    images = {"logo": lh.get("logo")}
    return data, images


def render_completion_pdf(certificate) -> bytes:
    data, images = completion_data_from_certificate(certificate)
    return build_course_completion_certificate(data, images)
