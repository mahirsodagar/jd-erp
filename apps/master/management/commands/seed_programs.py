"""Seed the 60 programs from the lead-process PDF + categorize existing.

Idempotent: existing programs are preserved (looked up by code), only
their category/certification/duration are updated; new ones get codes
generated deterministically from name.
"""

import re

from django.core.management.base import BaseCommand

from apps.master.models import Program


def _code(name: str, prefix: str = "") -> str:
    """Stable, collision-resistant code from name (max 28 chars).

    Always appends a 3-char hash of the full name as a suffix so two
    long names that would otherwise truncate to the same prefix stay
    distinct. The hash is derived from the original name (so it is
    stable across runs).
    """
    import hashlib

    suffix = ""
    n = name
    if re.search(r"\(weekend\)", n, re.I):
        suffix = "_WE"
        n = re.sub(r"\(weekend\)", "", n, flags=re.I)
    elif re.search(r"\(regular\)", n, re.I):
        suffix = "_REG"
        n = re.sub(r"\(regular\)", "", n, flags=re.I)

    h = hashlib.md5(name.encode("utf-8")).hexdigest()[:3].upper()
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", n).strip("_").upper()
    # Reserve 4 chars (suffix or hash) — guarantee uniqueness via hash.
    keep = 28 - len(suffix) - 4  # leading prefix + "_" + 3-char hash
    base = cleaned[:keep]
    code = (f"{prefix}_{base}_{h}{suffix}" if prefix
            else f"{base}_{h}{suffix}")[:28]
    return code


# (name, duration_months, certification, code_override_or_None)
REGULAR = [
    ("M.sc in Fashion design and Management", 24, "BESTIU", None),
    ("M.des in Fashion design",                 24, "BESTIU", None),
    ("M.sc in Interior Design",                 24, "BESTIU", None),
    ("M.des in Interior Design",                24, "BESTIU", None),
    ("Ma in Fashion communication",             24, "BESTIU", None),
    ("MBA in Fashion Business and Event Management", 24, "BESTIU", None),
    ("M.des in Visual Communication",           24, "BESTIU", None),
    ("MA in UI/UX",                             24, "BESTIU", None),
    ("B.sc in Fashion and Apparel Design",      36, "BCU",    None),
    ("B.des in Fashion Design",                 48, "BESTIU", "BDESFD"),    # existing
    ("B.sc in Interior Design and Decoration",  36, "BCU",    None),
    ("B.des in Interior Design",                48, "BESTIU", "BDESID"),    # existing
    ("B.sc in Jewellery Design",                36, "BESTIU", None),
    ("B.des in Visual Communication",           48, "BESTIU", None),
    ("Advanced Diploma in Fashion Design",      36, "JD",     None),
    ("Advanced Diploma in Interior Design",     36, "JD",     None),
    ("Advanced Diploma in Jewellery Design",    36, "JD",     None),
    ("PG Diploma in Fashion design and Management",  24, "JD", None),
    ("PG Diploma in Interior Design",           24, "JD",     None),
    ("PG Diploma in Fashion communication",     24, "JD",     None),
    ("PG Diploma in Fashion Business and Event Management", 24, "JD", None),
    ("PG Diploma in Visual Communication",      24, "JD",     None),
    ("PG Diploma in UI/ UX",                    24, "JD",     None),
    ("Diploma in Fashion Design",               12, "JD",     None),
    ("Diploma in Interior Design",              12, "JD",     None),
    ("Diploma in Fine Jewellery Design",        12, "JD",     None),
    ("Diploma in Fashion Business Management",  12, "JD",     None),
    ("Diploma in Graphic Design",               12, "JD",     None),
    ("Diploma in Fashion Technology",           12, "JD",     None),
    ("Diploma in Fashion Design (Weekend)",     12, "JD",     None),
    ("Diploma in Interior Design (Weekend)",    12, "JD",     None),
]

SHORT = [
    ("Certificate Program in Social Media and influencer marketing", 3, "JD", None),
    ("Certificate Program in Fashion Cad",              6, "JD", None),
    ("Certifcate Program in Interior Decorationa and Styling", 6, "JD", None),
    ("Certificate Program in CAD Jewellery Design",     6, "JD", None),
    ("Certificate Program in Lingerie Design",          6, "JD", None),
    ("Certificate Program in Fashion Styling",          3, "JD", None),
    ("Certificate Program in Fashion Photography",      2, "JD", None),  # ~6 weeks
    ("Certificate Program in Modular Interior Design",  3, "JD", None),
    ("Certificate Program in Interior Decoration",      3, "JD", None),
    ("Certificate Program in Branding and Visual Design", 3, "JD", None),
    ("Certificate Program in Filmmaking and Editing",   3, "JD", None),
    ("Certificate Program in Motion Graphics",          1, "JD", None),
    ("Certificate Program in Furniture Design",         3, "JD", None),
    ("Certificate Program in Interior Styling",         3, "JD", None),
    ("Certificate Program in Vastu Science",            3, "JD", None),
    ("Certificate program in Landscape Design (Regular)", 6, "JD", None),
    ("Certificate program in Landscape Design (weekend)", 6, "JD", None),
    ("Certificate program in Set Design",               6, "JD", None),
]

NEW = [
    ("M.des in Interior Ecodesign and Bioarchitecture", 24, "BESTIU", None),
    ("Bachelors in Animation & Multimedia",             36, "BESTIU", None),
    ("Bachelors in Immersive Design",                   36, "BESTIU", None),
    ("Diploma in Set design",                           12, "JD",     None),
    ("Diploma in Architectural Design & Visualization", 12, "JD",     None),
    ("Diploma in Furniture & Interior Product Design",  12, "JD",     None),
    ("Diploma in Animation & Multimedia",               12, "JD",     None),
    ("Diploma in VFX and Compositing",                  12, "JD",     None),
    ("Diploma in Animation & Multimedia (weekend)",     12, "JD",     None),
    ("Diploma in VFX and Compositing (weekend)",        12, "JD",     None),
    ("Diploma in Web design & development",             12, "JD",     None),
]


def _degree_from_name(name: str) -> str:
    n = name.lower()
    if n.startswith("m.sc"): return "M.Sc"
    if n.startswith("m.des"): return "M.Des"
    if n.startswith("ma in"): return "MA"
    if n.startswith("mba"): return "MBA"
    if n.startswith("b.sc"): return "B.Sc"
    if n.startswith("b.des"): return "B.Des"
    if n.startswith("bachelors"): return "Bachelors"
    if "advanced diploma" in n: return "Advanced Diploma"
    if "pg diploma" in n: return "PG Diploma"
    if n.startswith("diploma"): return "Diploma"
    if "certificate" in n: return "Certificate"
    return ""


class Command(BaseCommand):
    help = "Seed all 60 programs with category/certification + new lead sources."

    def handle(self, *args, **opts):
        count = 0
        for category, items in [
            (Program.Category.REGULAR, REGULAR),
            (Program.Category.SHORT, SHORT),
            (Program.Category.NEW, NEW),
        ]:
            for name, dur, cert, code_override in items:
                code = code_override or _code(name)
                Program.objects.update_or_create(
                    code=code,
                    defaults={
                        "name": name,
                        "degree_type": _degree_from_name(name),
                        "category": category,
                        "certification": cert,
                        "duration_months": dur,
                    },
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f"Seeded / updated {count} programs."))
