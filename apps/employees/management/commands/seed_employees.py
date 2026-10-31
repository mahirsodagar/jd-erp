"""Seed employees campus-wise from the legacy "Employee Master" CSV exports.

The exports live in `apps/employees/seed_data/<campus>.csv`, one file per
campus, exactly as downloaded from the legacy HRMS (title row, header
row, then one employee per line). Pass `--dir` to read them from
somewhere else, or `--file` to load a single export.

What the command does with each row:

- Campus comes from the row's `Campus` column (HYDERABAD → HYD, …);
  missing campuses are created. Institute comes from `Entity`.
- Department and Designation are matched by name (case- and
  whitespace-insensitive) and created when absent.
- City / State are matched against `master.State` / `master.City`;
  unknown cities are created under their state. Blank location fields
  fall back to the campus's own city/state.
- Status is read off the legacy `Actions` column: a row whose action
  button says "Inactive" is currently ACTIVE, and vice versa.
- Reporting managers are resolved by full name AFTER every file has
  been loaded, so cross-campus managers (Suma M, Nealesh Dalal, …)
  link correctly regardless of file order. Names that match nobody
  are left blank and listed at the end.
- Phone numbers are normalised to +91XXXXXXXXXX. Rows with no usable
  primary mobile, DOB or email are skipped and listed.
- Duplicate emp_codes within the export (the legacy system allowed
  them) get a `-2`, `-3` suffix so they can still be loaded; duplicate
  emails (the same person exported under two campuses) keep the first
  row seen and skip the rest. Both are reported.

Idempotent on `emp_code`: a row whose emp_code already exists is
skipped, so re-running after HR has edited records is safe. Use
`--update` to overwrite those rows from the CSV instead.

No portal users are created here. Run `backfill_employee_users
--apply` afterwards to provision logins for the imported staff.

Usage:
    python manage.py seed_employees                 # dry-run, all campuses
    python manage.py seed_employees --apply
    python manage.py seed_employees --apply --file path/to/Goa.csv
    python manage.py seed_employees --apply --update
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.employees.models import Department, Designation, Employee
from apps.employees.services import generate_emp_code, regenerate_qr
from apps.master.models import Campus, City, Institute, State

_SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data"

#: Legacy campus label → (code, name, city, state). Codes follow the
#: airport/short style already used for BLR and GOA.
CAMPUSES = {
    "BENGALURU": ("BLR", "Bangalore", "Bengaluru", "Karnataka"),
    "BANGALORE": ("BLR", "Bangalore", "Bengaluru", "Karnataka"),
    "GOA": ("GOA", "Goa", "Panaji", "Goa"),
    "HYDERABAD": ("HYD", "Hyderabad", "Hyderabad", "Telangana"),
    "VIJAYAWADA": ("BZA", "Vijayawada", "Vijayawada", "Andhra Pradesh"),
    "COCHIN": ("COK", "Cochin", "Kochi", "Kerala"),
    "KOCHI": ("COK", "Cochin", "Kochi", "Kerala"),
}

INSTITUTES = {
    "JD INSTITUTE OF FASHION TECHNOLOGY": "JDIFT",
    "JD SCHOOL OF DESIGN": "JDSD",
}

_BLOOD = {
    "A+": "A+", "A-": "A-", "B+": "B+", "B-": "B-",
    "O+": "O+", "O-": "O-", "AB+": "AB+", "AB-": "AB-",
}

_STATE_ALIASES = {
    "CHATTISGARH": "Chhattisgarh",
    "HARAYANA": "Haryana",
    "ANDRA PRADESH": "Andhra Pradesh",
    "TAMILNADU": "Tamil Nadu",
}


def _ws(s: str | None) -> str:
    """Collapse runs of whitespace and strip."""
    return re.sub(r"\s+", " ", (s or "")).strip()


def _key(s: str | None) -> str:
    return _ws(s).lower()


def _is_blank(s: str | None) -> bool:
    """Legacy forms were filled with '.', '-', '...', 'same', 'NA' for
    unknown values."""
    v = _ws(s)
    return not v or v.strip(".-_*x ").lower() in ("", "na", "n/a", "same", "nil")


def _phone(raw: str | None) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if not digits or digits[0] == "0":
        return None
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    if 9 <= len(digits) <= 15:
        # Foreign or malformed-but-non-empty number: keep what was given
        # so nothing is invented. It still passes PHONE_VALIDATOR.
        return "+" + digits
    return None


def _date(raw: str | None) -> date | None:
    v = _ws(raw)
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def _blood(raw: str | None) -> str:
    v = _ws(raw).upper().replace(" ", "")
    v = re.sub(r"(VE|POSITIVE|NEGATIVE)$", "", v)
    v = v.replace("0", "O")  # "0+" typed for "O+"
    return _BLOOD.get(v, "")


def _nationality(raw: str | None) -> str:
    return (Employee.Nationality.OTHERS
            if _key(raw) in ("others", "other", "foreign")
            else Employee.Nationality.INDIAN)


def _status(actions: str | None) -> int:
    """The Actions cell holds the *toggle* button, so "Inactive" means
    the employee is currently active."""
    text = _ws(actions).lower()
    if "inactive" in text:
        return Employee.Status.ACTIVE
    if "active" in text:
        return Employee.Status.INACTIVE
    return Employee.Status.ACTIVE


@dataclass
class Row:
    file: str
    line: int
    data: dict
    emp_code: str = ""
    managers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Command(BaseCommand):
    help = "Seed employees campus-wise from the legacy Employee Master CSV exports."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write to the database (default is a dry-run report).",
        )
        parser.add_argument(
            "--update", action="store_true",
            help="Overwrite employees whose emp_code already exists "
                 "(default: leave them untouched).",
        )
        parser.add_argument(
            "--dir", default=str(_SEED_DIR),
            help=f"Folder of campus CSV exports (default: {_SEED_DIR}).",
        )
        parser.add_argument(
            "--file", action="append", default=[],
            help="Load only this CSV (repeatable). Overrides --dir.",
        )
        parser.add_argument(
            "--no-qr", action="store_true",
            help="Skip QR-code generation (faster; QR is made on first view anyway).",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        self.apply = opts["apply"]
        self.update = opts["update"]
        self.make_qr = not opts["no_qr"]
        self.skipped: list[tuple[str, str]] = []
        self.warnings: list[str] = []
        self.unresolved_managers: dict[str, list[str]] = {}

        paths = [Path(p) for p in opts["file"]] or sorted(
            Path(opts["dir"]).glob("*.csv"),
        )
        if not paths:
            raise CommandError(f"No CSV files found in {opts['dir']}")

        rows: list[Row] = []
        for p in paths:
            if not p.is_file():
                raise CommandError(f"Not a file: {p}")
            rows.extend(self._read(p))
        # Active rows first so, when one person was exported twice, the
        # active record wins the unique-email race.
        rows.sort(key=lambda r: _status(r.data.get("Actions")))
        self._dedupe_codes(rows)

        self.stdout.write(
            f"{len(rows)} rows across {len(paths)} file(s)"
            + ("" if self.apply else "  [DRY RUN — pass --apply to write]")
        )

        created = updated = unchanged = 0
        by_code: dict[str, Employee] = {}
        per_campus: dict[str, int] = {}
        seen_emails: set[str] = set()

        with transaction.atomic():
            for row in rows:
                try:
                    with transaction.atomic():
                        emp, action = self._upsert(row, seen_emails)
                except _Skip as e:
                    who = _ws(f"{row.data.get('First Name', '')} {row.data.get('Family Name', '')}")
                    self.skipped.append((f"{row.file}:{row.line} {row.emp_code} ({who})", str(e)))
                    continue
                if action == "created":
                    created += 1
                elif action == "updated":
                    updated += 1
                else:
                    unchanged += 1
                per_campus[emp.campus.code] = per_campus.get(emp.campus.code, 0) + 1
                by_code[row.emp_code] = emp
                row.emp = emp

            self._link_managers(rows, by_code)

            if not self.apply:
                transaction.set_rollback(True)

        self._report(created, updated, unchanged, per_campus)

    # ------------------------------------------------------------------
    def _read(self, path: Path) -> list[Row]:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            header = None
            out = []
            for i, cells in enumerate(reader, start=1):
                if header is None:
                    if cells and cells[0].strip() == "SL NO":
                        header = [c.strip() for c in cells]
                    continue
                if not any(c.strip() for c in cells):
                    continue
                data = dict(zip(header, cells))
                out.append(Row(file=path.name, line=i, data=data,
                               emp_code=_ws(data.get("ID")).upper()))
            if header is None:
                raise CommandError(f"{path}: no 'SL NO' header row found")
        self.stdout.write(f"  {path.name}: {len(out)} rows")
        return out

    def _dedupe_codes(self, rows: list[Row]) -> None:
        seen: dict[str, int] = {}
        for row in rows:
            code = row.emp_code
            if not re.fullmatch(r"[A-Z0-9-]+", code):
                continue  # handled (skipped) in _upsert
            n = seen.get(code, 0) + 1
            seen[code] = n
            if n > 1:
                new = f"{code}-{n}"
                self.warnings.append(
                    f"{row.file}:{row.line}: duplicate emp_code {code} "
                    f"({_ws(row.data.get('First Name'))} {_ws(row.data.get('Family Name'))}) "
                    f"stored as {new} — fix in HR → Employees"
                )
                row.emp_code = new

    # ------------------------------------------------------------------
    def _campus(self, label: str) -> Campus:
        spec = CAMPUSES.get(_key(label).upper())
        if not spec:
            raise _Skip(f"unknown campus {label!r}")
        code, name, city, state = spec
        campus = Campus.objects.filter(code=code).first()
        if campus is None:
            campus = Campus.objects.create(code=code, name=name, city=city, state=state)
            self.warnings.append(f"created campus {code} ({name})")
        return campus

    def _institute(self, label: str) -> Institute:
        code = INSTITUTES.get(_key(label).upper())
        inst = Institute.objects.filter(code=code).first() if code else None
        if inst is None:
            raise _Skip(f"unknown entity {label!r} (run seed_institutes)")
        return inst

    def _named(self, model, name: str, fallback: str):
        name = _ws(name) or fallback
        obj = model.objects.filter(name__iexact=name).first()
        if obj is None:
            obj = model.objects.create(name=name)
            self.warnings.append(f"created {model.__name__.lower()} {name!r}")
        return obj

    def _state(self, raw: str, campus: Campus) -> State:
        name = _ws(raw)
        name = _STATE_ALIASES.get(name.upper(), name)
        st = State.objects.filter(name__iexact=name).first() if name else None
        if st is None:
            st = State.objects.filter(name__iexact=campus.state).first()
            if st is None:
                raise _Skip(f"state {raw!r} not in master.State and campus has no state")
        return st

    def _city(self, raw: str, state: State, campus: Campus) -> City:
        name = _ws(raw)
        if _is_blank(name):
            name = campus.city
        city = City.objects.filter(name__iexact=name, state=state).first()
        if city is None:
            # The legacy state dropdown defaulted to West Bengal, so
            # "Bengaluru, West Bengal" is common. Prefer an existing city
            # of that name anywhere over inventing a wrong pairing.
            city = City.objects.filter(name__iexact=name).first()
        if city is None:
            city = City.objects.create(name=name, state=state)
            self.warnings.append(f"created city {name!r} in {state.name}")
        return city

    # ------------------------------------------------------------------
    def _upsert(self, row: Row, seen_emails: set[str]) -> tuple[Employee, str]:
        d = row.data
        g = lambda k: _ws(d.get(k))  # noqa: E731

        email = g("Email").lower()
        if not email or "@" not in email:
            raise _Skip("no primary email")
        if email in seen_emails:
            raise _Skip(f"email {email} already loaded from another row")

        dob = _date(g("DOB"))
        doa = _date(g("DOA"))
        doj = _date(g("DOJ"))
        if not dob:
            raise _Skip(f"invalid DOB {g('DOB')!r}")
        doj = doj or doa
        doa = doa or doj
        if not doj:
            raise _Skip("no DOA/DOJ")

        mobile = _phone(g("Mobile No"))
        if not mobile:
            raise _Skip(f"invalid mobile {g('Mobile No')!r}")
        alt_mobile = _phone(g("Alt.Mobile No")) or ""
        if alt_mobile == mobile:
            alt_mobile = ""

        campus = self._campus(g("Campus"))
        institute = self._institute(g("Entity"))

        if not re.fullmatch(r"[A-Z0-9-]+", row.emp_code):
            # Legacy let HR save a row without an ID ("......."). Give it
            # a real code the same way the Employees page would.
            if existing_by_email := Employee.all_objects.filter(
                    email_primary__iexact=email).first():
                row.emp_code = existing_by_email.emp_code
            else:
                row.emp_code = generate_emp_code(campus_code=campus.code, year=doj.year)
            row.notes.append(f"emp_code {g('ID')!r} invalid in export; assigned {row.emp_code}")
        designation = self._named(Designation, g("Designation"), "Staff")
        department = self._named(Department, g("Department"), "General")

        cur_state = self._state(g("State"), campus)
        cur_city = self._city(g("City"), cur_state, campus)
        perm_state = self._state(g("Permanent State"), campus) if not _is_blank(g("Permanent State")) else cur_state
        perm_city = self._city(g("Permanent City"), perm_state, campus) if not _is_blank(g("Permanent City")) else cur_city

        cur_addr = "" if _is_blank(g("Address")) else g("Address")
        perm_addr = "" if _is_blank(g("Permanent address")) else g("Permanent address")
        if not cur_addr and not perm_addr:
            cur_addr = perm_addr = campus.city
            row.notes.append("no address in export; set to campus city")
        cur_addr = cur_addr or perm_addr
        perm_addr = perm_addr or cur_addr

        blood = _blood(g("Blood Group"))
        if not blood:
            row.notes.append(f"blood group {g('Blood Group')!r} not recognised; left blank")

        qualification = "" if _is_blank(g("Qualification")) else g("Qualification")
        if len(qualification) > 120:
            row.notes.append("qualification truncated to 120 chars")
            qualification = qualification[:117] + "..."

        alt_email = g("Alt.Email").lower()
        if alt_email == email or "@" not in alt_email:
            alt_email = ""

        middle = "" if _is_blank(g("Middle Name")) else g("Middle Name")
        family = "" if _is_blank(g("Family Name")) else g("Family Name")
        first = g("First Name")
        if not first:
            raise _Skip("no first name")

        status = _status(d.get("Actions"))

        values = dict(
            first_name=first[:60], middle_name=middle[:60], family_name=family[:60],
            dob=dob, nationality=_nationality(g("Nationality")),
            blood_group=blood, gender=(g("Gender").upper()[:1] or "O"),
            qualification=qualification,
            employment_type=(Employee.EmploymentType.PART_TIME
                             if "part" in _key(g("Employment Type"))
                             else Employee.EmploymentType.FULL_TIME),
            date_of_appointment=doa, date_of_joining=doj,
            designation=designation, department=department,
            campus=campus, institute=institute,
            current_address=cur_addr, current_city=cur_city, current_state=cur_state,
            permanent_address=perm_addr, permanent_city=perm_city, permanent_state=perm_state,
            mobile_primary=mobile, mobile_alternate=alt_mobile,
            email_primary=email, email_alternate=alt_email,
            status=status,
        )

        existing = Employee.all_objects.filter(emp_code=row.emp_code).first()
        if existing is not None and not self.update:
            seen_emails.add(existing.email_primary.lower())
            return existing, "unchanged"

        if existing is None and Employee.all_objects.filter(email_primary__iexact=email).exists():
            raise _Skip(f"email {email} already belongs to another employee in the DB")

        emp = existing or Employee(emp_code=row.emp_code)
        for k, v in values.items():
            setattr(emp, k, v)
        if existing is None or existing.status != status:
            emp.status_reason = "Imported from legacy Employee Master export"
            emp.status_changed_at = timezone.now()

        exclude = ["photo", "qr_code", "blood_group"] if not blood else ["photo", "qr_code"]
        try:
            emp.full_clean(exclude=exclude, validate_unique=False)
        except ValidationError as e:
            raise _Skip("; ".join(f"{k}: {' '.join(v)}" for k, v in e.message_dict.items()))

        emp.save()
        if self.make_qr and self.apply and not emp.qr_code:
            regenerate_qr(emp)
        seen_emails.add(email)

        row.managers = [g(f"Reporting Manager level {n}") for n in (1, 2, 3, 4)]
        for n in row.notes:
            self.warnings.append(f"{row.file}:{row.line} {row.emp_code}: {n}")
        return emp, ("updated" if existing else "created")

    # ------------------------------------------------------------------
    def _link_managers(self, rows: list[Row], by_code: dict[str, Employee]) -> None:
        # Name → employee, across everything just loaded plus whatever
        # was already in the DB. Active records win on a name clash.
        index: dict[str, Employee] = {}
        pool = list(Employee.all_objects.filter(is_deleted=False)
                    .order_by("-status", "created_on"))
        for e in pool:
            index[_key(e.full_name)] = e
            # Legacy sometimes drops the middle name or the honorific.
            index.setdefault(_key(f"{e.first_name} {e.family_name}"), e)
            index.setdefault(_key(e.full_name.replace("Dr.", "").replace("Dr ", "")), e)

        linked = 0
        for row in rows:
            emp = getattr(row, "emp", None)
            if emp is None or not row.managers:
                continue
            changed = []
            for n, name in enumerate(row.managers, start=1):
                if not name:
                    continue
                mgr = index.get(_key(name)) or index.get(_key(name.replace("Dr.", "").replace("Dr ", "")))
                if mgr is None or mgr.pk == emp.pk:
                    if mgr is None:
                        self.unresolved_managers.setdefault(_ws(name), []).append(emp.emp_code)
                    continue
                field_name = f"reporting_manager_{n}"
                if getattr(emp, f"{field_name}_id") != mgr.pk:
                    setattr(emp, field_name, mgr)
                    changed.append(field_name)
            if changed:
                emp.save(update_fields=changed + ["updated_on"])
                linked += 1
        self.stdout.write(f"  reporting managers linked on {linked} employee(s)")

    # ------------------------------------------------------------------
    def _report(self, created, updated, unchanged, per_campus):
        w = self.stdout.write
        w("")
        w(self.style.SUCCESS(
            f"{'Would create' if not self.apply else 'Created'} {created}, "
            f"{'would update' if not self.apply else 'updated'} {updated}, "
            f"left {unchanged} existing untouched, skipped {len(self.skipped)}."
        ))
        for code, n in sorted(per_campus.items()):
            w(f"  {code}: {n}")

        if self.skipped:
            w("")
            w(self.style.WARNING(f"Skipped rows ({len(self.skipped)}):"))
            for where, why in self.skipped:
                w(f"  {where}: {why}")

        if self.unresolved_managers:
            w("")
            w(self.style.WARNING(
                f"Reporting managers not found ({len(self.unresolved_managers)} names) — "
                "left blank; set them in HR → Employees:"
            ))
            for name, codes in sorted(self.unresolved_managers.items()):
                w(f"  {name}: {', '.join(codes)}")

        if self.warnings:
            w("")
            w(self.style.NOTICE(f"Notes ({len(self.warnings)}):"))
            for msg in self.warnings:
                w(f"  {msg}")

        if not self.apply:
            w("")
            w(self.style.WARNING("Dry-run only — nothing was written. Re-run with --apply."))


class _Skip(Exception):
    """Row cannot be loaded; reason is the message."""
