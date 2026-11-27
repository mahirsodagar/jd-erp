"""Turn a lead email into a flat dict of raw fields.

Every parser returns a `Parsed` dict with the same keys (missing ones
blank); the mapping to master rows happens later in `mail_intake`.

Parsers, chosen by `LeadMailRule.parser` or auto-detected:

  website  Forminator notification from the JD website. Two layouts:
           HTML label/value rows ("Name" / "Asha", "Select Campus" /
           "Goa" ...) and the older plain-text "Label\\n-----\\nvalue".
           Bare "Select" labels are positional: campus, course, how-known.
  tawk     tawk.to missed-chat / transcript / offline-message mail; the
           pre-chat form is "Name : x / Phone : y / Email : z /
           Question : ...". Campus is sniffed from the message text,
           course from the page the visitor was on.
  generic  Anything with "Label: value" lines or alternating label /
           value lines using common aliases, plus a last-resort regex
           for an email address and a 10-digit phone anywhere in the
           body. Covers listing-portal mails until a dedicated parser
           exists.

A parser never raises; it returns what it found and `ok` tells the
caller whether that is enough (name + phone) to make a lead.
"""

import html as html_lib
import re
from urllib.parse import urlparse

FIELDS = (
    "name", "email", "phone", "alt_phone", "campus_raw", "course_raw",
    "source_raw", "form_title", "dob", "qualification", "how_known",
    "message", "page_url", "utm_source", "utm_medium", "utm_campaign",
    "utm_content",
)

CAMPUS_WORDS = (
    "bangalore", "bengaluru", "goa", "panjim", "cochin", "kochi",
    "hyderabad", "vijayawada", "mumbai",
)


def empty() -> dict:
    return {k: "" for k in FIELDS}


# --- text helpers ------------------------------------------------------

_BLOCK = re.compile(
    r"<\s*(br|/p|/tr|/div|/h\d|/li|/td|/th|/table|/section)[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_STYLE = re.compile(r"<(style|script|head)[^>]*>.*?</\1>", re.I | re.S)
_DASHES = re.compile(r"^[\s\-=_–—]{4,}$")
_CUT = re.compile(r"^(DISCLAIMER\b|Sent from https?://|--\s*$)", re.I)


def html_to_lines(html: str) -> list[str]:
    s = _STYLE.sub("", html or "")
    s = _BLOCK.sub("\n", s)
    s = _TAGS.sub(" ", s)
    s = html_lib.unescape(s).replace("\xa0", " ")
    return clean_lines(s)


def clean_lines(text: str) -> list[str]:
    out = []
    for raw in (text or "").splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line or _DASHES.match(line):
            continue
        if _CUT.match(line):
            break
        out.append(line)
    return out


def body_lines(text_body: str, html_body: str) -> list[str]:
    """Prefer the plain part; fall back to the HTML part."""
    if text_body and text_body.strip():
        lines = clean_lines(text_body)
        if len(lines) >= 2:
            return lines
    return html_to_lines(html_body)


def clean_phone(raw: str) -> str:
    raw = (raw or "").strip()
    digits = re.sub(r"\D+", "", raw)
    return raw if len(digits) >= 10 else (raw if digits else "")


def sniff_campus(text: str) -> str:
    low = (text or "").lower()
    for w in CAMPUS_WORDS:
        if re.search(rf"\b{w}\b", low):
            return w.title()
    return ""


def slug_to_words(url: str) -> str:
    """'/diploma-in-interior-design-1-year/' → 'diploma in interior design 1 year'."""
    try:
        path = urlparse(url).path
    except ValueError:
        return ""
    seg = [p for p in path.split("/") if p]
    if not seg:
        return ""
    return re.sub(r"[-_]+", " ", seg[-1]).strip()


# --- website (Forminator) -----------------------------------------------

WEBSITE_LABELS = {
    "name": "name", "full name": "name", "student name": "name",
    "email": "email", "email address": "email", "email id": "email",
    "phone": "phone", "phone no.": "phone", "phone no": "phone",
    "phone number": "phone", "mobile": "phone", "mobile number": "phone",
    "contact number": "phone",
    "phone no. 2": "alt_phone", "alternate number": "alt_phone",
    "alternate phone": "alt_phone", "alternate mobile": "alt_phone",
    "date of birth": "dob", "dob": "dob",
    "educational qualification": "qualification", "qualification": "qualification",
    "select campus": "campus_raw", "campus": "campus_raw", "center": "campus_raw",
    "centre": "campus_raw", "preferred campus": "campus_raw",
    "preferred centre": "campus_raw", "preferred center": "campus_raw",
    "select centre": "campus_raw", "select center": "campus_raw",
    "select course": "course_raw", "course of interest": "course_raw",
    "course": "course_raw", "program": "course_raw", "programme": "course_raw",
    "interested course": "course_raw", "intrested course": "course_raw",
    "course interested": "course_raw", "course interested in": "course_raw",
    "how did you first hear about jd institute?": "how_known",
    "how did you hear about us?": "how_known", "how did you know": "how_known",
    "others": "how_known_other",
    "message": "message", "query": "message", "question": "message",
    "remarks": "message", "comments": "message",
    "utm_source": "utm_source", "utm_medium": "utm_medium",
    "utm_campaign": "utm_campaign", "utm_content": "utm_content",
    "utm_term": "_skip", "gclid": "_skip", "ip": "_skip",
    "url": "page_url", "source": "source_raw",
}
# Values of an unlabelled "Select" dropdown are classified by content:
# a campus word → campus, one of these → how-known, anything else → course.
HOW_KNOWN_WORDS = {
    "friends", "friend", "family", "relatives", "instagram", "facebook", "youtube",
    "google", "web search", "website", "internet", "social media", "newspaper",
    "hoarding", "hoardings", "radio", "tv", "television", "advertisement", "ads",
    "reference", "referral", "alumni", "ex student", "ex-student", "walk in",
    "walk-in", "walkin", "others", "other", "linkedin", "twitter", "whatsapp",
    "email", "sms", "exhibition", "career fair", "school", "college", "counsellor",
    "consultant", "consultants", "event", "workshop", "seminar", "flyer", "leaflet",
    "banner", "bus", "auto", "magazine",
}
_SUBMISSION = re.compile(
    r"you have a (?:new )?(.*?)(?:below are the )?form submission", re.I)

# Page slugs that are not a course (used only as a last-resort course hint).
NOT_A_COURSE_SLUG = {
    "", "contact", "contact us", "apply online", "customised courses", "home",
    "about", "about us", "admissions", "admission", "blog", "careers", "career",
    "gallery", "events", "placements", "faculty", "campus", "campuses", "fees",
    "scholarship", "scholarships", "faq", "faqs", "privacy policy", "thank you",
}


def course_slug(url: str) -> str:
    """The page slug as words when it looks like a course page, else ''."""
    words = slug_to_words(url)
    return "" if words.lower() in NOT_A_COURSE_SLUG else words


def classify_select(value: str, out: dict) -> str | None:
    low = re.sub(r"\s+", " ", value.lower()).strip()
    if sniff_campus(low) and len(low.split()) <= 3 and not out.get("campus_raw"):
        return "campus_raw"
    if low in HOW_KNOWN_WORDS and not out.get("how_known"):
        return "how_known"
    if not out.get("course_raw"):
        return "course_raw"
    if not out.get("how_known"):
        return "how_known"
    return None
_SUBJECT_TITLE = [
    re.compile(r"^new enquiry\s+(.+)$", re.I),
    re.compile(r"^jd institute\s*-\s*(.+?)\s*-\s*application number", re.I),
    re.compile(r"^jd institute\s*-\s*(.+)$", re.I),
    re.compile(r"^new form entry\s*#?\d*\s*for\s+(.+)$", re.I),
    # "Course page Brochure Downloads #2449" → "Course page Brochure Downloads"
    re.compile(r"^(.+?)\s*#\d+\s*$", re.I),
]


def form_title_from_subject(subject: str) -> str:
    s = re.sub(r"\s+", " ", subject or "").strip()
    for rx in _SUBJECT_TITLE:
        m = rx.match(s)
        if m:
            return m.group(1).strip(" -")
    return ""


def looks_like_website(from_address: str, subject: str, lines: list[str]) -> bool:
    if "webmaster@" in (from_address or "").lower():
        return True
    if any(_SUBMISSION.search(l) for l in lines[:3]):
        return True
    s = (subject or "").lower()
    return s.startswith(("new enquiry", "jd institute", "new form entry")) \
        or "form submission" in s or "brochure download" in s


def parse_website(subject: str, lines: list[str]) -> dict:
    out = empty()
    out["form_title"] = form_title_from_subject(subject)
    pending = None
    for line in lines:
        m = _SUBMISSION.search(line)
        if m:
            t = re.sub(r"\s+", " ", m.group(1)).strip(" :-")
            if t and t.lower() not in ("website", "new"):
                out["form_title"] = out["form_title"] or t
            continue
        key = line.lower().rstrip(":").strip()
        if key == "select":
            pending = "_select"
            continue
        if key in WEBSITE_LABELS:
            pending = WEBSITE_LABELS[key]
            continue
        if pending is None:
            continue
        if pending == "_skip":
            pending = None
            continue
        if pending == "_select":
            # Unlabelled dropdown — decide from the value itself.
            pending = classify_select(line, out)
            if pending is None:
                continue
        if pending == "how_known_other":
            if out["how_known"].lower() in ("", "others", "other"):
                out["how_known"] = line
            pending = None
            continue
        if pending in ("phone", "alt_phone"):
            line = clean_phone(line)
        if not out.get(pending):
            out[pending] = line
        pending = None
    out["ok"] = bool(out["name"] and (out["phone"] or out["email"]))
    return out


# --- tawk.to ------------------------------------------------------------

_TAWK_FIELD = re.compile(
    r"(?im)^\s*(?:\[\d\d:\d\d\]\s*)?(?:[^:\n]{0,80}:\s*)?(Name|Phone|Email|Question|Message)\s*:\s*(.*)$")
_TAWK_FROM = re.compile(r"(?im)^\s*Submitted from\s*:\s*(\S+)")
_TAWK_SITE = re.compile(r"(?im)^\s*Site\s*:\s*(\S+)")
_TAWK_EVENT = re.compile(r"^\s*\[\d\d:\d\d\]")


def looks_like_tawk(from_address: str, subject: str) -> bool:
    f = (from_address or "").lower()
    s = (subject or "").lower()
    return "tawk" in f or s.startswith(("missed chat", "chat transcript",
                                        "offline message"))


def parse_tawk(subject: str, lines: list[str]) -> dict:
    out = empty()
    s = re.sub(r"\s+", " ", subject or "")
    if s.lower().startswith("missed chat"):
        out["form_title"] = "Missed chat"
    elif s.lower().startswith("offline message"):
        out["form_title"] = "Offline message"
    else:
        out["form_title"] = "Chat transcript"

    text = "\n".join(lines)
    capturing = None
    for line in lines:
        m = _TAWK_FIELD.match(line)
        if m:
            key, val = m.group(1).lower(), m.group(2).strip()
            if key == "name" and not out["name"]:
                out["name"] = val
            elif key == "phone" and not out["phone"]:
                out["phone"] = clean_phone(val)
            elif key == "email" and not out["email"]:
                out["email"] = val
            elif key in ("question", "message"):
                out["message"] = val
                capturing = "message"
                continue
            capturing = None
            continue
        if capturing == "message":
            # The question runs until the next chat event / footer line.
            if _TAWK_EVENT.match(line) or "tawk.to" in line.lower() \
                    or line.lower().startswith(("missed chats", "need help")):
                capturing = None
            else:
                out["message"] += " " + line
    m = _TAWK_FROM.search(text)
    if m:
        out["page_url"] = m.group(1)
        out["course_raw"] = course_slug(m.group(1))
    out["campus_raw"] = sniff_campus(out["message"])
    out["message"] = out["message"].strip()
    out["ok"] = bool(out["name"] and (out["phone"] or out["email"]))
    return out


# --- generic -----------------------------------------------------------

GENERIC_ALIASES = {
    "name": ("name", "full name", "student name", "candidate name", "lead name",
             "applicant name", "customer name", "contact name"),
    "email": ("email", "email id", "email address", "e-mail", "mail id"),
    "phone": ("phone", "mobile", "mobile no", "mobile number", "phone number",
              "contact", "contact no", "contact number", "phone no", "whatsapp",
              "whatsapp number"),
    "alt_phone": ("alternate number", "alternate phone", "alt phone",
                  "secondary phone"),
    "course_raw": ("course", "courses", "program", "programme", "course interested",
                   "interested course", "course of interest", "interested in",
                   "course name", "specialization", "stream"),
    "campus_raw": ("campus", "centre", "center", "city", "location",
                   "preferred campus", "preferred centre", "preferred city",
                   "college", "institute"),
    "message": ("message", "query", "question", "remarks", "comments",
                "requirement", "description", "enquiry"),
    "dob": ("dob", "date of birth"),
    "qualification": ("qualification", "educational qualification", "education"),
    "how_known": ("source", "how did you hear about us", "lead source"),
}
_ALIAS_TO_FIELD = {a: f for f, als in GENERIC_ALIASES.items() for a in als}
_KV = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 .'/()_\-]{0,40}?)\s*[:\-–]\s+(.+?)\s*$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")


def parse_generic(subject: str, lines: list[str]) -> dict:
    out = empty()
    out["form_title"] = re.sub(r"\s+", " ", subject or "")[:200]
    pending = None
    for line in lines:
        m = _KV.match(line)
        if m and m.group(1).lower().strip() in _ALIAS_TO_FIELD:
            field = _ALIAS_TO_FIELD[m.group(1).lower().strip()]
            val = m.group(2).strip()
            if field in ("phone", "alt_phone"):
                val = clean_phone(val)
            if not out.get(field):
                out[field] = val
            pending = None
            continue
        key = line.lower().rstrip(":").strip()
        if key in _ALIAS_TO_FIELD:
            pending = _ALIAS_TO_FIELD[key]
            continue
        if pending:
            val = clean_phone(line) if pending in ("phone", "alt_phone") else line
            if not out.get(pending):
                out[pending] = val
            pending = None
    text = "\n".join(lines)
    if not out["email"]:
        m = _EMAIL.search(text)
        if m:
            out["email"] = m.group(0)
    if not out["phone"]:
        m = _PHONE.search(text)
        if m:
            out["phone"] = m.group(0)
    if not out["campus_raw"]:
        out["campus_raw"] = sniff_campus(text)
    out["ok"] = bool(out["name"] and (out["phone"] or out["email"]))
    return out


# --- dispatcher ---------------------------------------------------------

def detect_parser(from_address: str, subject: str, lines: list[str]) -> str:
    if looks_like_tawk(from_address, subject):
        return "tawk"
    if looks_like_website(from_address, subject, lines):
        return "website"
    return "generic"


def parse(parser: str, *, from_address: str, subject: str,
          text_body: str, html_body: str) -> tuple[str, dict]:
    """Return (parser_used, fields). `parser` may be "auto"."""
    lines = body_lines(text_body, html_body)
    if parser in ("", "auto"):
        parser = detect_parser(from_address, subject, lines)
    if parser == "tawk":
        return parser, parse_tawk(subject, lines)
    if parser == "website":
        out = parse_website(subject, lines)
        if not out["ok"]:
            # Layout drifted — see if the generic pass does better.
            alt = parse_generic(subject, lines)
            if alt["ok"]:
                alt["form_title"] = out["form_title"] or alt["form_title"]
                return "generic", alt
        return parser, out
    return "generic", parse_generic(subject, lines)
