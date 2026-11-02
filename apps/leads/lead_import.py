"""Bulk lead import from a fixed-format CSV (Leads page → Import CSV).

Format — one header row, columns in any order:

    name,email,phone,campus,program,source,father_mobile,father_email,
    assign_to,city,state,remarks

- `name`, `email`, `phone`      required
- `campus`                      campus code or exact name (case-insensitive)
- `program`                     program code or exact name; must be offered
                                at the campus
- `source`                      lead source name (case-insensitive)
- `father_mobile`/`father_email` optional here (the Add Lead form requires
                                them, but bulk sheets from events rarely
                                have them)
- `assign_to`                   optional counsellor — portal username,
                                emp code or employee email. Blank → the
                                usual round-robin.
- `city`, `state`, `remarks`    optional

Every row is created through `services.create_lead`, so the normal
duplicate detection applies: a row matching an existing lead by email or
phone becomes a repeated lead attached to the original counsellor, exactly
as if it had been keyed in by hand. The preview flags those as "repeat".

All-or-nothing: if any row has an error, nothing is written.
"""

import csv
import io
import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q

from apps.master.models import Campus, LeadSource, Program

from .models import Lead
from .services import create_lead, eligible_counsellors, normalize_phone

COLUMNS = ["name", "email", "phone", "campus", "program", "source",
           "father_mobile", "father_email", "assign_to",
           "city", "state", "remarks"]
REQUIRED = {"name", "email", "phone", "campus", "program", "source"}

MAX_ROWS = 2000


class ImportFileError(ValueError):
    """The file as a whole is unusable (encoding, header, size)."""


@dataclass
class RowResult:
    line: int
    name: str = ""
    email: str = ""
    phone: str = ""
    campus: str = ""
    program: str = ""
    source: str = ""
    assign_to: str = ""
    action: str = ""          # create | repeat | error
    errors: list[str] = field(default_factory=list)
    # Validated payload for create_lead; not serialised.
    _data: dict = field(default_factory=dict)

    def as_dict(self):
        return {
            "line": self.line, "name": self.name, "email": self.email,
            "phone": self.phone, "campus": self.campus,
            "program": self.program, "source": self.source,
            "assign_to": self.assign_to,
            "action": self.action, "errors": self.errors,
        }


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z]+", "_", (h or "").strip().lower()).strip("_")


# Common spreadsheet headings people will have, mapped to our columns.
_ALIASES = {
    "full_name": "name", "student_name": "name", "lead_name": "name",
    "e_mail": "email", "email_id": "email", "mail": "email",
    "mobile": "phone", "mobile_number": "phone", "phone_number": "phone",
    "contact": "phone", "contact_number": "phone",
    "course": "program", "programme": "program",
    "lead_source": "source",
    "counsellor": "assign_to", "counselor": "assign_to", "assigned_to": "assign_to",
    "owner": "assign_to",
    "father_phone": "father_mobile", "father_contact": "father_mobile",
    "parent_mobile": "father_mobile", "parent_email": "father_email",
    "remark": "remarks", "notes": "remarks", "note": "remarks",
}


def read_rows(data: bytes) -> list[dict]:
    """Decode and parse; header names are normalised to COLUMNS."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel on Windows saves "CSV" as cp1252 unless told otherwise.
        text = data.decode("cp1252", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ImportFileError("The file is empty.")
    header: dict[str, str] = {}
    for h in reader.fieldnames:
        key = _norm_header(h)
        key = _ALIASES.get(key, key)
        header.setdefault(key, h)
    missing = REQUIRED - header.keys()
    if missing:
        raise ImportFileError(
            f"Missing column(s): {', '.join(sorted(missing))}. "
            f"Expected header: {','.join(COLUMNS)}"
        )
    rows = []
    for raw in reader:
        row = {col: (raw.get(header[col]) or "").strip()
               for col in COLUMNS if col in header}
        if not any(row.values()):
            continue  # blank line
        row["_line"] = reader.line_num
        rows.append(row)
    if len(rows) > MAX_ROWS:
        raise ImportFileError(f"Too many rows ({len(rows)}); max {MAX_ROWS}.")
    return rows


def _valid_email(value: str) -> bool:
    try:
        validate_email(value)
    except ValidationError:
        return False
    return True


def _counsellor_lookup() -> dict[str, object]:
    """username / emp_code / email (all lower-cased) → User."""
    out: dict[str, object] = {}
    for c in eligible_counsellors():
        user = c.employee.user_account
        for key in (user.username, c.employee.emp_code,
                    c.employee.email_primary, user.email):
            if key:
                out.setdefault(key.lower(), user)
    return out


def plan(rows: list[dict]) -> list[RowResult]:
    """Validate every row and decide what it would do. Writes nothing."""
    campuses = list(Campus.objects.all())
    campus_by = {c.code.lower(): c for c in campuses}
    campus_by.update({c.name.lower(): c for c in campuses})
    programs = list(Program.objects.prefetch_related("campuses"))
    program_by = {p.code.lower(): p for p in programs}
    program_by.update({p.name.lower(): p for p in programs})
    offered = {(p.pk, c.pk) for p in programs for c in p.campuses.all()}
    sources = {s.name.lower(): s for s in LeadSource.objects.filter(is_active=True)}
    counsellors = _counsellor_lookup()

    results = []
    seen_emails: dict[str, int] = {}
    seen_phones: dict[str, int] = {}
    for i, row in enumerate(rows, start=2):
        line = row.get("_line", i)
        r = RowResult(line=line)
        results.append(r)

        r.name = row.get("name", "")
        if not r.name:
            r.errors.append("name is required")
        elif len(r.name) > 160:
            r.errors.append("name is longer than 160 characters")

        r.email = row.get("email", "").lower()
        if not r.email:
            r.errors.append("email is required")
        elif not _valid_email(r.email):
            r.errors.append(f'bad email "{r.email}"')

        r.phone = row.get("phone", "")
        phone_norm = normalize_phone(r.phone)
        if not r.phone:
            r.errors.append("phone is required")
        elif len(phone_norm) != 10:
            r.errors.append(f'phone must have 10 digits, got "{r.phone}"')

        r.campus = row.get("campus", "")
        campus = campus_by.get(r.campus.lower())
        if not r.campus:
            r.errors.append("campus is required")
        elif not campus:
            r.errors.append(f'unknown campus "{r.campus}"')

        r.program = row.get("program", "")
        program = program_by.get(r.program.lower())
        if not r.program:
            r.errors.append("program is required")
        elif not program:
            r.errors.append(f'unknown program "{r.program}"')
        elif campus and (program.pk, campus.pk) not in offered:
            r.errors.append(
                f'"{program.name}" is not offered at {campus.name}')

        r.source = row.get("source", "")
        source = sources.get(r.source.lower())
        if not r.source:
            r.errors.append("source is required")
        elif not source:
            r.errors.append(f'unknown source "{r.source}"')

        father_mobile = row.get("father_mobile", "")
        if father_mobile and len(normalize_phone(father_mobile)) != 10:
            r.errors.append(f'father_mobile must have 10 digits, got "{father_mobile}"')
        father_email = row.get("father_email", "").lower()
        if father_email and not _valid_email(father_email):
            r.errors.append(f'bad father_email "{father_email}"')

        r.assign_to = row.get("assign_to", "")
        assign_to = None
        if r.assign_to:
            assign_to = counsellors.get(r.assign_to.lower())
            if assign_to is None:
                r.errors.append(
                    f'"{r.assign_to}" is not a counsellor who can take leads')

        for fld, limit in (("city", 80), ("state", 80)):
            if len(row.get(fld, "")) > limit:
                r.errors.append(f"{fld} is longer than {limit} characters")

        if r.errors:
            r.action = "error"
            continue

        r._data = {
            "name": r.name, "email": r.email, "phone": r.phone,
            "father_mobile": father_mobile, "father_email": father_email,
            "campus": campus, "program": program, "source": source,
            "assign_to": assign_to,
            "city": row.get("city", ""), "state": row.get("state", ""),
            "remarks": row.get("remarks", ""),
        }

        # Would this row land as a repeated lead? Either it matches a lead
        # already in the system, or an earlier row of the same file.
        in_db = Lead.objects.filter(
            Q(email__iexact=r.email) | Q(phone_normalized=phone_norm)
        ).exists()
        in_file = r.email in seen_emails or phone_norm in seen_phones
        r.action = "repeat" if (in_db or in_file) else "create"
        seen_emails.setdefault(r.email, line)
        seen_phones.setdefault(phone_norm, line)
    return results


def summarise(results: list[RowResult]) -> dict:
    counts = {"create": 0, "repeat": 0, "error": 0}
    for r in results:
        counts[r.action] += 1
    return {**counts, "total": len(results)}


@transaction.atomic
def apply(results: list[RowResult], *, created_by) -> list[Lead]:
    """Write a plan that has no errors. Caller must check first."""
    assert not any(r.action == "error" for r in results)
    created = []
    for r in results:
        created.append(create_lead(data=r._data, created_by=created_by))
    return created
