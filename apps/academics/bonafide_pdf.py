"""Bonafide Certificate — client letter template (2026-11-19).

Layout, geometry and typography are measured from the client's
original PDF (A4, 595.2 x 841.92 pt, Bookman Old Style) and kept
verbatim from the fpdf2 template they supplied; only the data plumbing
is ours. Everything comes from the certificate snapshot (see
`cert_service.build_snapshot`), so an already-issued certificate
re-renders identically.

Font: Bookman Old Style when installed (macOS Office / Windows),
DejaVu Serif or Liberation Serif on Linux, else the built-in Times.
With a TrueType font loaded the text is Unicode-safe; the Times
fallback goes through `_safe` (latin-1).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from django.utils import timezone
from fpdf import FPDF

from .cert_service import _safe


# ---------------------------------------------------------------------------
# Document configuration (points, measured from the original PDF)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DocumentConfig:
    page_width: float = 595.2
    page_height: float = 841.92

    margin_left: float = 72.02
    margin_right: float = 68.00
    margin_top: float = 72.00
    margin_bottom: float = 72.00

    # Vertical anchors (top-down)
    ref_line_y: float = 182.25
    timestamp_y: float = 213.51
    title_y: float = 247.52
    body_start_y: float = 274.91

    # Line heights and inter-block gaps
    body_line_height: float = 21.14
    gap_after_para1: float = 41.28
    gap_before_signoff: float = 44.89
    gap_for_to_yours: float = 32.42
    gap_yours_to_principal: float = 74.23

    # Typography
    ref_prefix_size: float = 11.04
    ref_number_size: float = 12.96
    timestamp_size: float = 11.04
    title_size: float = 12.96
    body_size: float = 12.00
    signoff_size: float = 11.04

    text_color: Tuple[int, int, int] = (0, 0, 0)

    @property
    def content_width(self) -> float:
        return self.page_width - self.margin_left - self.margin_right

    @property
    def right_edge(self) -> float:
        return self.page_width - self.margin_right


DEFAULT_CONFIG = DocumentConfig()


# Optional image slots (x, y, w, h in pt; 0 keeps aspect). Nothing is
# drawn unless a path is passed via `images={...}` — the client prints
# on letterhead.
IMAGE_SLOTS: Dict[str, Dict[str, float]] = {
    "letterhead": {"x": 36.0, "y": 24.0, "w": 523.2, "h": 0.0},
    "logo": {"x": 72.02, "y": 36.0, "w": 110.0, "h": 0.0},
    "signature": {"x": 72.02, "y": 0.0, "w": 120.0, "h": 0.0},
    "seal": {"x": 235.0, "y": 0.0, "w": 85.0, "h": 0.0},
    "footer": {"x": 36.0, "y": 765.0, "w": 523.2, "h": 0.0},
}


# Bookman Old Style -> DejaVu Serif -> Liberation Serif -> built-in Times
FONT_CANDIDATES: List[Tuple[str, str, str]] = [
    ("BookmanOldStyle",
     "/Library/Fonts/Microsoft/Bookman Old Style.ttf",
     "/Library/Fonts/Microsoft/Bookman Old Style Bold.ttf"),
    ("BookmanOldStyle",
     "/System/Library/Fonts/Supplemental/Bookman Old Style.ttf",
     "/System/Library/Fonts/Supplemental/Bookman Old Style Bold.ttf"),
    ("BookmanOldStyle",
     "C:/Windows/Fonts/BOOKOS.TTF",
     "C:/Windows/Fonts/BOOKOSB.TTF"),
    ("DejaVuSerif",
     "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    ("LiberationSerif",
     "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
]


class BonafideCertificatePDF(FPDF):
    """A4 letter with the client's Bonafide geometry."""

    def __init__(self, config: DocumentConfig = DEFAULT_CONFIG,
                 font_paths: Optional[Dict[str, str]] = None) -> None:
        super().__init__(orientation="P", unit="pt",
                         format=(config.page_width, config.page_height))
        self.config = config
        self.font_family_name = "Times"
        self.unicode_font = False
        self.set_margins(config.margin_left, config.margin_top, config.margin_right)
        self.set_auto_page_break(auto=True, margin=config.margin_bottom)
        # Zero cell padding so edges align exactly to the margins.
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

    # -- primitives -------------------------------------------------------
    def draw_text_line(self, text: str, x: float, y: float, size: float,
                       style: str = "", align: str = "L",
                       width: Optional[float] = None,
                       line_height: Optional[float] = None) -> float:
        self.set_text_color(*self.config.text_color)
        self.set_font(self.font_family_name, style, size)
        w = width if width is not None else self.config.content_width
        h = line_height if line_height is not None else size * 1.2
        self.set_xy(x, y)
        self.cell(w, h, self.txt(text), border=0, align=align)
        return y + h

    def draw_right_aligned_spans(self, spans: List[Tuple[str, str, float]],
                                 right_x: float, y: float,
                                 line_height: float = 14.0) -> float:
        """Inline spans (text, style, size) right-aligned to `right_x`."""
        self.set_text_color(*self.config.text_color)
        measured: List[Tuple[str, str, float, float]] = []
        total_w = 0.0
        max_size = max((sz for _, _, sz in spans), default=12.0)
        for text, style, size in spans:
            text = self.txt(text)
            self.set_font(self.font_family_name, style, size)
            w = self.get_string_width(text)
            measured.append((text, style, size, w))
            total_w += w
        cur_x = right_x - total_w
        for text, style, size, w in measured:
            self.set_font(self.font_family_name, style, size)
            # keep mixed sizes on one visual baseline
            self.set_xy(cur_x, y + (max_size - size) * 0.18)
            self.cell(w, line_height, text, border=0, align="L")
            cur_x += w
        return y + line_height

    def draw_justified_rich_paragraph(self, segments: List[Tuple[str, str]],
                                      x: float, y: float, width: float,
                                      font_size: float, line_height: float,
                                      justify: bool = True) -> float:
        """Multi-line paragraph with inline styles ('' / 'B') and full
        justification on every line but the last. Returns the y below
        the last line."""
        self.set_text_color(*self.config.text_color)

        # Tokenise into words, remembering whether a space preceded each
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

        # Glue parts not separated by a space (e.g. bold word + comma)
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

        # Split any cluster wider than the line
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

        # Greedy wrap
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
            if cur_y + line_height > self.config.page_height - self.config.margin_bottom:
                self.add_page()
                cur_y = self.config.margin_top
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

    def draw_optional_image(self, path, x, y, w=0.0, h=0.0) -> None:
        if path and os.path.isfile(str(path)):
            self.image(str(path), x=x, y=y, w=w, h=h)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
def build_bonafide_certificate(data: Dict[str, str],
                               images: Optional[Dict[str, str]] = None,
                               config: DocumentConfig = DEFAULT_CONFIG,
                               font_paths: Optional[Dict[str, str]] = None) -> bytes:
    """Render the letter from a flat dict of strings and return PDF bytes.

    Keys: ref_prefix, certificate_number, timestamp, student_name,
    relation_prefix, parent_name, registration_number, course, batch,
    academic_year, residential_address, address_1, address_2,
    city_state, pin_code, reason_to_apply, institute_name.
    """
    d = {k: ("" if v is None else str(v)) for k, v in data.items()}
    img = images or {}

    pdf = BonafideCertificatePDF(config=config, font_paths=font_paths)
    pdf.set_title("BONAFIDE CERTIFICATE")
    pdf.set_author(d.get("institute_name") or "JD School of Design")
    pdf.add_page()

    for key in ("letterhead", "logo"):
        if key in img:
            pdf.draw_optional_image(img[key], **IMAGE_SLOTS[key])

    # Reference number (right-aligned, prefix smaller than the number)
    pdf.draw_right_aligned_spans(
        spans=[(d.get("ref_prefix", "JSD/BC Request/"), "", config.ref_prefix_size),
               (d.get("certificate_number", ""), "", config.ref_number_size)],
        right_x=config.right_edge, y=config.ref_line_y, line_height=14.0,
    )
    pdf.draw_text_line(d.get("timestamp", ""), config.margin_left,
                       config.timestamp_y, config.timestamp_size,
                       align="R", line_height=14.0)
    pdf.draw_text_line("BONAFIDE CERTIFICATE", config.margin_left,
                       config.title_y, config.title_size, style="B",
                       align="C", line_height=15.0)

    # Paragraph 1 — identity + address, bold spans as in the original
    address_parts = ", ".join(p for p in [
        d.get("residential_address"), d.get("address_1"),
        d.get("address_2"), d.get("city_state"),
    ] if p)
    pin_suffix = f" {d['pin_code']}." if d.get("pin_code") else "."
    para1 = [
        ("This is to certify that ", ""),
        (f"{d.get('student_name', '')}, {d.get('relation_prefix', 'D/o')} "
         f"{d.get('parent_name', '')}, with Register number "
         f"{d.get('registration_number', '')}", "B"),
        (f" is a Bonafide Student of our Institute, studying "
         f"{d.get('course', '')}, {d.get('batch', '')} for the academic year "
         f"{d.get('academic_year', '')}. As per our record student permanent "
         f"address is ", ""),
        (f"{address_parts}{pin_suffix}", "B"),
    ]
    y = pdf.draw_justified_rich_paragraph(
        para1, config.margin_left, config.body_start_y, config.content_width,
        config.body_size, config.body_line_height,
    )

    # Paragraph 2 — purpose
    reason = d.get("reason_to_apply", "").strip()
    reason_bit = f"Facilities/Grants/ {reason} purpose only." if reason \
        else "Facilities/Grants purpose only."
    para2 = ("This certificate is issued for availing Central-State Government "
             f"{reason_bit} This certificate is issued against a request made "
             "by the student.")
    y = pdf.draw_justified_rich_paragraph(
        [(para2, "")], config.margin_left, y + config.gap_after_para1,
        config.content_width, config.body_size, config.body_line_height,
    )

    # Sign-off block, kept together on one page
    for_y = y + config.gap_before_signoff
    yours_y = for_y + config.gap_for_to_yours
    principal_y = yours_y + config.gap_yours_to_principal
    if principal_y + 20.0 > config.page_height - config.margin_bottom:
        pdf.add_page()
        for_y = config.margin_top
        yours_y = for_y + config.gap_for_to_yours
        principal_y = yours_y + config.gap_yours_to_principal

    pdf.draw_text_line(f"For {d.get('institute_name') or 'JD School of Design'}",
                       config.margin_left, for_y, config.signoff_size,
                       style="B", line_height=14.0)
    pdf.draw_text_line("Yours Faithfully", config.margin_left, yours_y,
                       config.signoff_size, line_height=14.0)
    if "signature" in img:
        s = IMAGE_SLOTS["signature"]
        pdf.draw_optional_image(img["signature"], s["x"], yours_y + 18.0, s["w"], s["h"])
    if "seal" in img:
        s = IMAGE_SLOTS["seal"]
        pdf.draw_optional_image(img["seal"], s["x"], yours_y + 6.0, s["w"], s["h"])
    pdf.draw_text_line("PRINCIPAL", config.margin_left, principal_y,
                       config.signoff_size, style="B", line_height=14.0)

    if "footer" in img:
        pdf.draw_optional_image(img["footer"], **IMAGE_SLOTS["footer"])

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Snapshot -> template data
# ---------------------------------------------------------------------------
def _ref_prefix(institute_code: str) -> str:
    code = (institute_code or "").upper()
    # The client's letter uses "JSD" for JD School of Design.
    short = "JSD" if code == "JDSD" else (code or "JD")
    return f"{short}/BC Request/"


def bonafide_data_from_certificate(certificate) -> Dict[str, str]:
    snap = certificate.snapshot or {}
    student = snap.get("student", {})
    enrl = snap.get("enrollment", {})
    inst = snap.get("institute", {})
    addr = snap.get("address", {})

    gender = (student.get("gender") or "").upper()
    relation = "D/o" if gender == "F" else "S/o"
    parent = student.get("father_name") or student.get("mother_name") or ""

    city = addr.get("city", "")
    state = addr.get("state", "")
    city_state = ", ".join(p for p in (city, state) if p)

    issued = certificate.issued_at
    if issued:
        issued = timezone.localtime(issued)
    stamp = issued.strftime("%d/%m/%Y %H:%M:%S") if issued else ""

    return {
        "institute_name": inst.get("name") or "JD School of Design",
        "ref_prefix": _ref_prefix(inst.get("code", "")),
        "certificate_number": certificate.certificate_no or "",
        "timestamp": stamp,
        "student_name": student.get("name", ""),
        "relation_prefix": relation,
        "parent_name": parent,
        "registration_number": (student.get("registration_number")
                                or student.get("application_form_id") or ""),
        "course": enrl.get("program", ""),
        "batch": enrl.get("batch", ""),
        "academic_year": enrl.get("academic_year", ""),
        "residential_address": addr.get("line", ""),
        "address_1": "",
        "address_2": "",
        "city_state": city_state,
        "pin_code": addr.get("pincode", ""),
        "reason_to_apply": certificate.purpose or "",
    }


def render_bonafide_pdf(certificate) -> bytes:
    return build_bonafide_certificate(bonafide_data_from_certificate(certificate))
