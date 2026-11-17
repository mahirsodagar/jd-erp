"""Turn a Compose-step filter dict into a list of recipients.

One function per source. Each returns plain dicts (no model instances)
so the same output feeds both the preview endpoint and the campaign
snapshot. Rules shared by every source:

- blank / missing email → counted in `skipped_blank`, not listed
- same email twice (case-insensitive) → first wins, rest counted in
  `skipped_duplicate`
- email on the suppression list → listed with `suppressed=True` so the
  sender can see who is being left out; never included in a campaign
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q
from django.utils.dateparse import parse_date

from apps.admissions.models import Enrollment, Student
from apps.employees.models import Employee
from apps.leads.models import Lead

from .models import Suppression

STUDENT_KINDS = ("student", "institute", "father", "mother")
STUDENT_KIND_LABELS = {
    "student": "Student personal email",
    "institute": "Institute email",
    "father": "Father's email",
    "mother": "Mother's email",
}


@dataclass
class Audience:
    recipients: list[dict] = field(default_factory=list)
    skipped_blank: int = 0
    skipped_duplicate: int = 0
    suppressed: int = 0

    def as_dict(self) -> dict:
        return {
            "recipients": self.recipients,
            "skipped_blank": self.skipped_blank,
            "skipped_duplicate": self.skipped_duplicate,
            "suppressed": self.suppressed,
        }


class _Collector:
    def __init__(self):
        self.out = Audience()
        self._seen: set[str] = set()
        self._suppressed = set(
            Suppression.objects.values_list("email", flat=True),
        )

    def add(self, *, key: str, name: str, email: str, context: str,
            kind: str | None = None):
        addr = Suppression.normalise(email)
        if not addr:
            self.out.skipped_blank += 1
            return
        if addr in self._seen:
            self.out.skipped_duplicate += 1
            return
        self._seen.add(addr)
        suppressed = addr in self._suppressed
        if suppressed:
            self.out.suppressed += 1
        row = {
            "key": key, "name": name, "email": addr, "context": context,
            "suppressed": suppressed,
        }
        if kind:
            row["kind"] = kind
        self.out.recipients.append(row)

    def finish(self) -> Audience:
        self.out.recipients.sort(key=lambda r: (r["name"].lower(), r["email"]))
        return self.out


def _int(v) -> int | None:
    if v in ("", None):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# --- Leads ----------------------------------------------------------

def leads_audience(f: dict) -> Audience:
    qs = Lead.objects.select_related("program", "campus")
    if (v := _int(f.get("campus"))) is not None:
        qs = qs.filter(campus_id=v)
    if (v := _int(f.get("program"))) is not None:
        qs = qs.filter(program_id=v)
    if (v := _int(f.get("source"))) is not None:
        qs = qs.filter(source_id=v)
    if (v := _int(f.get("counsellor"))) is not None:
        qs = qs.filter(assign_to_id=v)
    statuses = [s for s in (f.get("status") or []) if s]
    if statuses:
        qs = qs.filter(status__in=statuses)
    if d := parse_date(f.get("created_from") or ""):
        qs = qs.filter(created_at__date__gte=d)
    if d := parse_date(f.get("created_to") or ""):
        qs = qs.filter(created_at__date__lte=d)

    c = _Collector()
    for lead in qs.order_by("id").iterator(chunk_size=500):
        c.add(
            key=f"lead:{lead.id}",
            name=lead.name,
            email=lead.email,
            context=f"{lead.program.name} · {lead.campus.name}",
        )
    return c.finish()


# --- Students -------------------------------------------------------

def students_audience(f: dict) -> Audience:
    kinds = [k for k in (f.get("recipients") or []) if k in STUDENT_KINDS]
    if not kinds:
        kinds = ["student"]

    qs = Student.objects.select_related("program", "campus")
    if (v := _int(f.get("institute"))) is not None:
        qs = qs.filter(institute_id=v)
    if (v := _int(f.get("campus"))) is not None:
        qs = qs.filter(campus_id=v)
    if (v := _int(f.get("program"))) is not None:
        qs = qs.filter(program_id=v)

    # Batch / year / status live on the enrollment, not the student.
    enr = Q()
    if (v := _int(f.get("batch"))) is not None:
        enr &= Q(enrollments__batch_id=v)
    if (v := _int(f.get("academic_year"))) is not None:
        enr &= Q(enrollments__academic_year_id=v)
    if (v := _int(f.get("enrollment_status"))) is not None:
        enr &= Q(enrollments__status=v)
    if enr:
        qs = qs.filter(enr).distinct()

    # Latest batch per student for the context column.
    batch_filter = _int(f.get("batch"))
    latest_batch: dict[int, str] = {}
    enr_qs = Enrollment.objects.select_related("batch").order_by("student_id", "-id")
    if batch_filter is not None:
        enr_qs = enr_qs.filter(batch_id=batch_filter)
    for e in enr_qs.filter(student__in=qs).iterator(chunk_size=500):
        latest_batch.setdefault(e.student_id, e.batch.name)

    c = _Collector()
    for s in qs.order_by("id").iterator(chunk_size=500):
        base_ctx = s.program.name
        if b := latest_batch.get(s.id):
            base_ctx += f" · {b}"
        else:
            base_ctx += f" · {s.campus.name}"
        for kind in kinds:
            if kind == "student":
                name, email = s.student_name, s.student_email
            elif kind == "institute":
                name, email = s.student_name, s.institute_email
            elif kind == "father":
                name = f"{s.father_name} (father)" if s.father_name else f"Parent of {s.student_name}"
                email = s.father_email
            else:
                name = f"{s.mother_name} (mother)" if s.mother_name else f"Parent of {s.student_name}"
                email = s.mother_email
            c.add(
                key=f"student:{s.id}:{kind}",
                name=name,
                email=email,
                context=base_ctx,
                kind=kind,
            )
    return c.finish()


# --- Employees ------------------------------------------------------

def employees_audience(f: dict) -> Audience:
    qs = Employee.objects.select_related("designation", "department")
    if (v := _int(f.get("institute"))) is not None:
        qs = qs.filter(institute_id=v)
    if (v := _int(f.get("campus"))) is not None:
        qs = qs.filter(campus_id=v)
    if (v := _int(f.get("department"))) is not None:
        qs = qs.filter(department_id=v)
    if (v := _int(f.get("designation"))) is not None:
        qs = qs.filter(designation_id=v)
    if (v := _int(f.get("status"))) is not None:
        qs = qs.filter(status=v)

    c = _Collector()
    for e in qs.order_by("id").iterator(chunk_size=500):
        c.add(
            key=f"employee:{e.id}",
            name=e.full_name,
            email=e.email_primary,
            context=f"{e.designation.name} · {e.department.name}",
        )
    return c.finish()


BUILDERS = {
    "leads": leads_audience,
    "students": students_audience,
    "employees": employees_audience,
}


def build_audience(source: str, filters: dict) -> Audience:
    try:
        builder = BUILDERS[source]
    except KeyError as e:
        raise ValueError(f"Unknown audience source '{source}'.") from e
    return builder(filters or {})
