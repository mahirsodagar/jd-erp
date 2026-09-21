"""Bulk subject import from a fixed-format CSV.

Used by both the Subjects page upload (`SubjectImportView`) and the
`import_subjects` management command, so a file that previews cleanly in
the UI seeds identically from the shell.

Format — one header row, columns in any order:

    program,semester,subject_code,subject_name,credits,is_elective

- `program`      program code, or its exact name (case-insensitive)
- `semester`     number: `3`, `Sem 3`, `Semester 3` or roman `III`
- `subject_code` globally unique; the row is matched on it (upsert)
- `subject_name` required
- `credits`      optional whole number
- `is_elective`  optional: yes/no, true/false, 1/0, elective/core

All-or-nothing: if any row has an error, nothing is written. A semester
the program does not have yet is created as "Semester N".
"""

import csv
import io
import re
from dataclasses import dataclass, field

from django.db import transaction

from .models import Program, Semester, Subject

COLUMNS = ["program", "semester", "subject_code", "subject_name",
           "credits", "is_elective"]
REQUIRED = {"program", "semester", "subject_code", "subject_name"}

MAX_ROWS = 5000

_TRUE = {"yes", "y", "true", "1", "elective"}
_FALSE = {"", "no", "n", "false", "0", "core"}
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7,
          "VIII": 8, "IX": 9, "X": 10, "XI": 11, "XII": 12}


class ImportFileError(ValueError):
    """The file as a whole is unusable (encoding, header, size)."""


@dataclass
class RowResult:
    line: int
    program: str = ""
    semester: int | None = None
    code: str = ""
    name: str = ""
    credits: int | None = None
    is_elective: bool = False
    action: str = ""          # create | update | unchanged | error
    errors: list[str] = field(default_factory=list)
    # Resolved objects; not serialised.
    _program: Program | None = None

    def as_dict(self):
        return {
            "line": self.line, "program": self.program,
            "semester": self.semester, "code": self.code, "name": self.name,
            "credits": self.credits, "is_elective": self.is_elective,
            "action": self.action, "errors": self.errors,
        }


def _norm_header(h: str) -> str:
    return re.sub(r"[^a-z]+", "_", (h or "").strip().lower()).strip("_")


def _parse_semester(raw: str) -> int | None:
    raw = raw.strip()
    if m := re.search(r"(\d+)\s*$", raw):
        return int(m.group(1))
    # Uppercase only, so a stray "x" or "v" isn't read as 10 or 5.
    tail = raw.split()[-1] if raw.split() else ""
    return _ROMAN.get(tail)


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
    header = {_norm_header(h): h for h in reader.fieldnames}
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


def plan(rows: list[dict]) -> list[RowResult]:
    """Validate every row and decide what it would do. Writes nothing."""
    programs = list(Program.objects.all())
    by_code = {p.code.lower(): p for p in programs}
    by_name = {p.name.lower(): p for p in programs}
    # Matched case-insensitively, so "ds101" updates "DS101" rather than
    # tripping the unique constraint. The table is small enough to load.
    existing = {s.code.lower(): s for s in
                Subject.objects.select_related("program")}
    semesters = {(s.program_id, s.number): s
                 for s in Semester.objects.exclude(program=None)}

    seen: dict[str, int] = {}
    results = []
    # Line 1 is the header.
    for i, row in enumerate(rows, start=2):
        line = row.get("_line", i)
        r = RowResult(line=line)
        results.append(r)

        r.program = row.get("program", "")
        prog = by_code.get(r.program.lower()) or by_name.get(r.program.lower())
        if not r.program:
            r.errors.append("program is required")
        elif not prog:
            r.errors.append(f'unknown program "{r.program}"')
        r._program = prog

        sem_raw = row.get("semester", "")
        r.semester = _parse_semester(sem_raw) if sem_raw else None
        if not sem_raw:
            r.errors.append("semester is required")
        elif not r.semester or r.semester < 1:
            r.errors.append(f'bad semester "{sem_raw}"')

        r.code = row.get("subject_code", "")
        r.name = row.get("subject_name", "")
        if not r.code:
            r.errors.append("subject_code is required")
        elif len(r.code) > 30:
            r.errors.append("subject_code is longer than 30 characters")
        if not r.name:
            r.errors.append("subject_name is required")
        elif len(r.name) > 160:
            r.errors.append("subject_name is longer than 160 characters")

        if r.code:
            key = r.code.lower()
            if key in seen:
                r.errors.append(f"duplicate subject_code (also on line {seen[key]})")
            else:
                seen[key] = line

        credits_raw = row.get("credits", "")
        if credits_raw:
            try:
                val = float(credits_raw)
                if val < 0 or val != int(val):
                    raise ValueError
                r.credits = int(val)
            except ValueError:
                r.errors.append(f'credits must be a whole number, got "{credits_raw}"')

        elective_raw = row.get("is_elective", "").lower()
        if elective_raw in _TRUE:
            r.is_elective = True
        elif elective_raw not in _FALSE:
            r.errors.append(f'is_elective must be yes/no, got "{row["is_elective"]}"')

        current = existing.get(r.code.lower()) if r.code else None
        if current and prog and current.program_id and current.program_id != prog.pk:
            r.errors.append(
                f'code "{current.code}" already belongs to another program '
                f'({current.program.code if current.program else "?"})'
            )

        if r.errors:
            r.action = "error"
        elif not current:
            r.action = "create"
        else:
            sem = semesters.get((prog.pk, r.semester))
            same = (current.name == r.name
                    and current.program_id == prog.pk
                    and sem is not None and current.semester_id == sem.pk
                    and current.credits == r.credits
                    and current.is_elective == r.is_elective)
            r.action = "unchanged" if same else "update"
    return results


def new_semesters(results: list[RowResult]) -> list[tuple[Program, int]]:
    """(program, number) pairs the import would have to create."""
    have = set(Semester.objects.exclude(program=None)
               .values_list("program_id", "number"))
    wanted = {(r._program.pk, r.semester): r._program for r in results
              if r.action in ("create", "update")}
    return sorted(((p, n) for (pid, n), p in wanted.items()
                   if (pid, n) not in have),
                  key=lambda t: (t[0].code, t[1]))


def summarise(results: list[RowResult]) -> dict:
    counts = {"create": 0, "update": 0, "unchanged": 0, "error": 0}
    for r in results:
        counts[r.action] += 1
    return {
        **counts,
        "total": len(results),
        "new_semesters": [f"{p.code} · Semester {n}"
                          for p, n in new_semesters(results)],
    }


@transaction.atomic
def apply(results: list[RowResult]) -> None:
    """Write a plan that has no errors. Caller must check first."""
    assert not any(r.action == "error" for r in results)
    for program, number in new_semesters(results):
        Semester.objects.get_or_create(
            program=program, number=number,
            defaults={"name": f"Semester {number}"},
        )
    semesters = {(s.program_id, s.number): s
                 for s in Semester.objects.exclude(program=None)}
    for r in results:
        if r.action not in ("create", "update"):
            continue
        subject = (Subject.objects.filter(code__iexact=r.code).first()
                   if r.action == "update" else Subject(code=r.code))
        subject.name = r.name
        subject.program = r._program
        subject.semester = semesters[(r._program.pk, r.semester)]
        subject.credits = r.credits
        subject.is_elective = r.is_elective
        subject.save()
