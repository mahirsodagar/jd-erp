from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Institute(models.Model):
    """Top-level legal entity.

    An Institute owns Programs (legacy `program_master.inst_id`); it does
    NOT own Campuses. A campus hosts whichever programs are offered
    there, so a single campus can serve several institutes at once —
    reach them via `Campus.institutes`.
    """

    name = models.CharField(max_length=160, unique=True)
    code = models.CharField(max_length=20, unique=True)
    logo = models.ImageField(
        upload_to="institute/logos/", blank=True, null=True,
        help_text="Used on ID cards and printed reports.",
    )
    email_domain = models.CharField(
        max_length=120, blank=True,
        help_text=(
            "Domain used for personalised student portal emails — e.g. "
            "`jdift.in`. When blank, falls back to `<code>.in` "
            "lowercased."
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class State(models.Model):
    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(
        max_length=4, unique=True,
        help_text="ISO-style state code (e.g. KA, GA, MH).",
    )
    is_union_territory = models.BooleanField(default=False)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class City(models.Model):
    name = models.CharField(max_length=120)
    state = models.ForeignKey(State, on_delete=models.PROTECT, related_name="cities")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        unique_together = (("name", "state"),)

    def __str__(self):
        return f"{self.name}, {self.state.code}"


class Campus(models.Model):
    """A physical location. Institute-agnostic, as in legacy
    `campus_master` — which stored only (campus_name, campus_shname).

    A campus belongs to no single institute: it hosts programs, and each
    program names its own institute. Use `Campus.institutes` for the set
    of institutes present at this campus.
    """

    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=20, unique=True, help_text="Short code, e.g. BLR, GOA.")
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    image = models.ImageField(
        upload_to="campus/images/", blank=True, null=True,
        help_text="Shown on the dashboard campus cards (PHP `campus_img`).",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "Campuses"

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def institutes(self):
        """Institutes with at least one active program at this campus.

        Derived, not stored — the same fact legacy expressed by joining
        `program_master` on FIND_IN_SET(campus_id) and reading inst_id.
        """
        return (Institute.objects
                .filter(programs__campuses=self, programs__is_active=True)
                .distinct()
                .order_by("name"))


class Program(models.Model):
    """Academic program — the join between an Institute and its campuses.

    Ports legacy `program_master`: `institute` is inst_id, `degree` is
    degree_id, and `campuses` replaces the comma-separated campus_id
    column that was queried with FIND_IN_SET.

    This is the ONLY place the institute is recorded for academic data.
    Resolve a student's / lead's institute through their program, never
    through their campus.
    """

    class Category(models.TextChoices):
        REGULAR = "REGULAR", "Regular Course (1-4 yrs)"
        SHORT = "SHORT", "Short Course (3-11 mo)"
        NEW = "NEW", "Newly launched"

    name = models.CharField(max_length=160, unique=True)
    code = models.CharField(max_length=30, unique=True)
    institute = models.ForeignKey(
        Institute, on_delete=models.PROTECT,
        related_name="programs", null=True, blank=True,
        help_text="Owning institute (legacy `program_master.inst_id`). "
                  "Nullable only for legacy rows that could not be "
                  "backfilled — set it on every new program.",
    )
    degree = models.ForeignKey(
        "master.Degree", on_delete=models.PROTECT,
        related_name="programs", null=True, blank=True,
        help_text="Legacy `program_master.degree_id`.",
    )
    degree_type = models.CharField(
        max_length=40, blank=True,
        help_text="Free-text degree label, e.g. B.Des, M.Des, Diploma. "
                  "Kept alongside `degree` because notifications.sender "
                  "routes the outgoing mail domain off this string "
                  "(is_diploma()) — do not drop it.",
    )
    category = models.CharField(
        max_length=10, choices=Category.choices, default=Category.REGULAR,
        db_index=True,
        help_text="Reporting / grouping only. Lead assignment rotates over "
                  "all counsellors regardless of category.",
    )
    certification = models.CharField(
        max_length=20, blank=True,
        help_text="e.g. BESTIU, BCU, JD.",
    )
    duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    campuses = models.ManyToManyField(
        Campus, related_name="programs", blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} ({self.code})"


class AcademicYear(models.Model):
    """e.g. 2026-27. Most reports filter by this."""

    code = models.CharField(max_length=10, unique=True, help_text="e.g. 26-27")
    full_name = models.CharField(max_length=20, blank=True, help_text="e.g. 2026-2027")
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ("-start_date",)

    def __str__(self):
        return self.full_name or self.code


class Course(models.Model):
    """A PROGRAM YEAR — one year of a Program, spanning its semesters.

    This is legacy `course_master`, whose screen is titled "Add Program
    year" (masters/course.php:83): `course_name` is the year's label
    ("Year 1"), `program_id` its program, and `sem_id` a COMMA-SEPARATED
    list of the semester numbers the year covers. PHP resolved the year
    for a semester with:

        SELECT * FROM course_master
        WHERE FIND_IN_SET(<sem>, sem_id) AND program_id = <program>

    `semesters` below is that CSV, normalised. The model keeps the name
    `Course` because Student.course, Enrollment.course and
    FeeTemplate.course all point at it; everything user-facing says
    "Program year".
    """

    name = models.CharField(
        max_length=160,
        help_text='Year label, e.g. "Year 1" (legacy `course_name`).',
    )
    code = models.CharField(max_length=30, unique=True)
    program = models.ForeignKey(
        "master.Program", on_delete=models.PROTECT, related_name="courses",
    )
    semesters = models.ManyToManyField(
        "master.Semester", related_name="courses", blank=True,
        help_text="Semesters this year covers — the normalised form of "
                  "legacy `course_master.sem_id`, which held them as a "
                  "comma-separated list queried with FIND_IN_SET.",
    )
    duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        unique_together = (("name", "program"),)
        verbose_name = "Program year"
        verbose_name_plural = "Program years"

    def __str__(self):
        return f"{self.name} ({self.code})"

    @classmethod
    def for_semester(cls, *, program, semester):
        """The program year covering `semester`, or None.

        Django equivalent of the PHP FIND_IN_SET lookup above. Returns
        the first match — legacy allowed several rows to claim the same
        semester and simply took them in id order.
        """
        return (cls.objects
                .filter(program=program, semesters=semester, is_active=True)
                .order_by("pk")
                .first())


class Degree(models.Model):
    """UG / PG / Diploma / Certificate."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Semester(models.Model):
    """Sem 1..N. Numbered for sorting."""

    name = models.CharField(max_length=40, unique=True, help_text="e.g. Semester 1")
    number = models.PositiveSmallIntegerField(unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("number",)

    def __str__(self):
        return self.name


class Batch(models.Model):
    """Cohort: students who started together at a campus in a program/year."""

    name = models.CharField(max_length=120)
    short_name = models.CharField(max_length=30, blank=True)
    program = models.ForeignKey(
        "master.Program", on_delete=models.PROTECT, related_name="batches",
    )
    campus = models.ForeignKey(
        "master.Campus", on_delete=models.PROTECT, related_name="batches",
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="batches",
    )
    mentor = models.ForeignKey(
        "employees.Employee", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="mentored_batches",
        help_text="Class / batch mentor.",
    )
    feedback_link = models.URLField(blank=True)
    feedback_link_enabled = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        unique_together = (("name", "program", "campus", "academic_year"),)

    def __str__(self):
        return f"{self.name} — {self.campus.code} {self.academic_year.code}"


class Subject(models.Model):
    """Taught entity. The curriculum linkage — which subjects belong to
    which Program, at which Semester, and who teaches them — is explicit
    via `CurriculumMapping` (legacy `instur_program_sem_sub`)."""

    name = models.CharField(max_length=160)
    code = models.CharField(max_length=30, unique=True)
    credits = models.PositiveSmallIntegerField(null=True, blank=True)
    is_elective = models.BooleanField(
        default=False,
        help_text="Legacy `subject_master.iselective`. Elective subjects "
                  "may share one timetable slot with other electives, and "
                  "their attendance roster is limited to the students who "
                  "chose them (Enrollment.elective_subjects).",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} ({self.code})"


class CurriculumMapping(models.Model):
    """Which Subject is taught in which (Program, Semester), and by whom.

    Ports legacy `instur_program_sem_sub` — the table the PHP subject
    dropdowns filtered on (`where program_id=... and instur_id=...`).

    `instructor` is nullable so the same table serves both jobs: rows
    without one describe the curriculum (this subject belongs to this
    program/semester), rows with one also record the teaching
    assignment. Legacy always set it.
    """

    program = models.ForeignKey(
        "master.Program", on_delete=models.CASCADE,
        related_name="curriculum",
    )
    semester = models.ForeignKey(
        "master.Semester", on_delete=models.PROTECT,
        related_name="curriculum",
    )
    subject = models.ForeignKey(
        "master.Subject", on_delete=models.PROTECT,
        related_name="curriculum",
    )
    instructor = models.ForeignKey(
        "employees.Employee", on_delete=models.SET_NULL,
        related_name="curriculum", null=True, blank=True,
        help_text="Legacy `instur_id`. Null = curriculum row only.",
    )

    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="curriculum_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("program", "semester__number", "subject__name")
        verbose_name = "Curriculum mapping"
        verbose_name_plural = "Curriculum mappings"
        constraints = [
            models.UniqueConstraint(
                fields=["program", "semester", "subject", "instructor"],
                condition=models.Q(instructor__isnull=False),
                name="uniq_curriculum_prog_sem_sub_instr",
            ),
            # NULLs compare as distinct in SQL, so the constraint above
            # would not stop duplicate curriculum-only rows. Cover them
            # with a partial unique index of their own.
            models.UniqueConstraint(
                fields=["program", "semester", "subject"],
                condition=models.Q(instructor__isnull=True),
                name="uniq_curriculum_prog_sem_sub_noinstr",
            ),
        ]
        indexes = [
            models.Index(fields=["program", "semester"]),
            models.Index(fields=["instructor", "program"]),
        ]

    def __str__(self):
        who = self.instructor_id or "—"
        return f"{self.program.code} S{self.semester.number} {self.subject.code} ({who})"


class Classroom(models.Model):
    """Physical room. Per-campus."""

    name = models.CharField(max_length=80)
    code = models.CharField(max_length=20)
    campus = models.ForeignKey(
        "master.Campus", on_delete=models.PROTECT, related_name="classrooms",
    )
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("campus", "name")
        unique_together = (("code", "campus"),)

    def __str__(self):
        return f"{self.name} ({self.campus.code})"


class TimeSlot(models.Model):
    """Reusable time blocks for scheduling, per academic year (timings
    can shift year-to-year)."""

    label = models.CharField(max_length=40, help_text="e.g. Slot 1, Forenoon")
    start_time = models.TimeField()
    end_time = models.TimeField()
    academic_year = models.ForeignKey(
        "master.AcademicYear", on_delete=models.PROTECT,
        related_name="time_slots",
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ("academic_year", "sort_order", "start_time")
        unique_together = (("label", "academic_year"),)

    def __str__(self):
        # `start_time` / `end_time` may be a `datetime.time` (loaded
        # from DB) or a plain string (just-assigned). Coerce safely.
        return f"{self.label} ({self.start_time}-{self.end_time})"


class FeeTemplate(models.Model):
    """Fee structure for an enrollment context (PHP `fee_master`).

    Keyed on (academic_year, campus, program). The template holds the
    headline numbers; per-student installments + receipts live in the
    `fees` app.
    """

    name = models.CharField(max_length=200)
    academic_year = models.ForeignKey(
        "master.AcademicYear", on_delete=models.PROTECT, related_name="fee_templates",
    )
    campus = models.ForeignKey(
        "master.Campus", on_delete=models.PROTECT, related_name="fee_templates",
    )
    program = models.ForeignKey(
        "master.Program", on_delete=models.PROTECT, related_name="fee_templates",
    )
    course = models.ForeignKey(
        "master.Course", null=True, blank=True,
        on_delete=models.PROTECT, related_name="fee_templates",
        help_text="Optional — leave blank for program-wide fee.",
    )

    application_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="One-time non-refundable fee at application time.",
    )
    course_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Tuition / course fee for the period.",
    )
    registration_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("10000.00"),
        help_text="Mandatory yearly registration charge, CARVED OUT of "
                  "total_fee (not added on top) — it is part of the course "
                  "fee, scheduled as its own installment and payable in "
                  "full every academic year. Concessions cannot reduce it. "
                  "Set to 0 to disable for this template.",
    )
    other_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Misc fees (uniform, transport, etc.).",
    )
    total_fee = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="The sum payable. Stored explicitly (not computed) "
                  "so admins can override after concessions/discounts.",
    )

    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-academic_year__start_date", "campus", "program")
        indexes = [
            models.Index(fields=["academic_year", "campus", "program"]),
        ]

    def __str__(self):
        return self.name


class LeadSource(models.Model):
    """Master list of where a lead came from (Website, Walk-in, etc.).
    Admin-managed so values can be added/disabled without code changes.
    """

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ("sort_order", "name")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
