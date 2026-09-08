"""Shared furniture for the printed student documents (fpdf2).

The fee receipt and the fee undertaking are two halves of the same
stationery set: same institute letterhead off `master.Institute`, same
program-policy page on the back, same Latin-1 constraint from fpdf2's
built-in Helvetica. This module owns those pieces so the two renderers
cannot drift apart.

Page geometry is A4 portrait with 15mm side margins throughout.
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

from .program_policies import SIGNATORIES

MARGIN = 15.0
PAGE_W = 210.0
BODY_W = PAGE_W - 2 * MARGIN  # 180mm

#: The magenta used for the UNDERTAKING banner, sampled from the printed
#: stationery.
BRAND_MAGENTA = (196, 18, 90)

_UNICODE_FALLBACKS = {
    "–": "-",   # en dash
    "—": "-",   # em dash
    "‘": "'",   # left single quote
    "’": "'",   # right single quote
    "“": '"',   # left double quote
    "”": '"',   # right double quote
    "…": "...", # ellipsis
    "•": "-",   # bullet
    "₹": "INR ",  # rupee sign — fpdf2 built-in fonts are Latin-1
}


def safe(text) -> str:
    """Coerce arbitrary user-supplied strings to Latin-1 by replacing
    common Unicode punctuation. fpdf2's built-in Helvetica is Latin-1
    only; for full Unicode we'd need to ship a TTF."""
    if text is None:
        return ""
    s = str(text)
    for k, v in _UNICODE_FALLBACKS.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def fit(pdf: FPDF, text: str, width: float) -> str:
    """Trim `text` (adding an ellipsis) until it fits `width`. Table
    cells are single-line by design — a 40-character bank name must not
    push the row into the next column."""
    text = safe(text)
    usable = width - 2
    if pdf.get_string_width(text) <= usable:
        return text
    while text and pdf.get_string_width(text + "...") > usable:
        text = text[:-1]
    return text + "..." if text else ""


def rule(pdf: FPDF, gap_before: float = 2.0, gap_after: float = 2.0) -> None:
    pdf.ln(gap_before)
    pdf.set_draw_color(190, 190, 190)
    y = pdf.get_y()
    pdf.line(MARGIN, y, PAGE_W - MARGIN, y)
    pdf.set_draw_color(0, 0, 0)
    pdf.ln(gap_after)


# --- Letterhead --------------------------------------------------------

def logo_path(institute) -> str | None:
    """Institute logo as a local path, or None when unset/missing.

    Guarded because the file can be absent on a fresh environment (media
    isn't in the repo) and a storage backend need not expose `.path` at
    all — a document must still render without its logo.
    """
    logo = getattr(institute, "logo", None)
    if not logo:
        return None
    try:
        path = Path(logo.path)
    except (NotImplementedError, ValueError):
        return None
    return str(path) if path.is_file() else None


def letterhead_lines(institute) -> list[str]:
    """Address block as printed: title, address lines, phone, email,
    GSTIN. Every part is optional — a blank institute yields []."""
    lines: list[str] = []
    if getattr(institute, "letterhead_title", ""):
        lines.append(institute.letterhead_title)
    lines += [
        ln.strip()
        for ln in (getattr(institute, "address", "") or "").splitlines()
        if ln.strip()
    ]
    if getattr(institute, "phone", ""):
        lines.append(f"M: {institute.phone}")
    if getattr(institute, "email", ""):
        lines.append(f"E: {institute.email}")
    if getattr(institute, "gstin", ""):
        lines.append(f"GSTIN: {institute.gstin}")
    return lines


def draw_letterhead_block(pdf: FPDF, institute, *, x: float, y: float,
                          width: float = 90.0, align: str = "R",
                          size: float = 8.5) -> float:
    """Draw the address block at (x, y). Returns the y below it."""
    pdf.set_font("Helvetica", "", size)
    pdf.set_text_color(60, 60, 60)
    line_h = size * 0.53
    for line in letterhead_lines(institute):
        pdf.set_xy(x, y)
        pdf.cell(width, line_h, safe(line), align=align)
        y += line_h
    pdf.set_text_color(0, 0, 0)
    return y


def draw_logo(pdf: FPDF, institute, *, x: float, y: float,
              height: float = 16.0, fallback_width: float = 90.0) -> float:
    """Logo at (x, y), falling back to the institute name in bold when
    no usable image is on file. Returns the y below whatever was drawn.
    """
    if path := logo_path(institute):
        try:
            pdf.image(path, x=x, y=y, h=height)
            return y + height
        except Exception:  # noqa: BLE001 — a corrupt logo must not 500 the document
            pass
    pdf.set_xy(x, y)
    pdf.set_font("Helvetica", "B", 13)
    pdf.multi_cell(fallback_width, 6, safe(getattr(institute, "name", "")))
    return pdf.get_y()


# --- Policy page (page 2 of both documents) ----------------------------

def draw_policy_page(pdf: FPDF, blocks: list[tuple]) -> None:
    """Render a `program_policies` document on a fresh page, followed by
    the three signature boxes.

    Block kinds are documented in `apps.common.program_policies`.
    """
    pdf.add_page()
    for block in blocks:
        kind, args = block[0], block[1:]
        if kind == "h1":
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, safe(args[0]), align="C", new_x="LMARGIN", new_y="NEXT")
        elif kind == "h2":
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, safe(args[0]), new_x="LMARGIN", new_y="NEXT")
        elif kind == "h3":
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 5, safe(args[0]), new_x="LMARGIN", new_y="NEXT")
        elif kind == "p":
            pdf.set_font("Helvetica", "", 8.5)
            pdf.multi_cell(BODY_W, 4.5, safe(args[0]),
                           new_x="LMARGIN", new_y="NEXT")
        elif kind == "li":
            lead, rest = args
            indent = 6.0
            pdf.set_x(MARGIN + indent)
            pdf.set_font("Helvetica", "B", 8.5)
            prefix = f"- {lead}" if lead else "- "
            lead_w = pdf.get_string_width(prefix) + 1
            pdf.cell(lead_w, 4.5, safe(prefix))
            pdf.set_font("Helvetica", "", 8.5)
            pdf.multi_cell(BODY_W - indent - lead_w, 4.5, safe(rest),
                           new_x="LMARGIN", new_y="NEXT")
        elif kind == "li2":
            indent = 14.0
            pdf.set_x(MARGIN + indent)
            pdf.set_font("Helvetica", "", 8.5)
            pdf.multi_cell(BODY_W - indent, 4.5, safe(f"- {args[0]}"),
                           new_x="LMARGIN", new_y="NEXT")

    pdf.ln(4)
    w = BODY_W / len(SIGNATORIES)
    pdf.set_font("Helvetica", "B", 8.5)
    for name in SIGNATORIES:
        pdf.cell(w, 8, safe(name), border=1, align="C")
    pdf.ln(8)
    for _ in SIGNATORIES:
        pdf.cell(w, 16, "", border=1)
    pdf.ln(16)
