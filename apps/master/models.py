from django.db import models
from django.utils.text import slugify


class Institute(models.Model):
    """Top-level legal entity. One Institute → many Campuses."""

    name = models.CharField(max_length=160, unique=True)
    code = models.CharField(max_length=20, unique=True)
    logo = models.ImageField(
        upload_to="institute/logos/", blank=True, null=True,
        help_text="Used on ID cards and printed reports.",
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
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=20, unique=True, help_text="Short code, e.g. BLR, GOA.")
    institute = models.ForeignKey(
        Institute, on_delete=models.PROTECT,
        related_name="campuses", null=True, blank=True,
        help_text="Parent institute. Optional for legacy data.",
    )
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "Campuses"

    def __str__(self):
        return f"{self.name} ({self.code})"


class Program(models.Model):
    """Academic program. Offered at one or more campuses."""

    name = models.CharField(max_length=160, unique=True)
    code = models.CharField(max_length=30, unique=True)
    degree_type = models.CharField(
        max_length=40, blank=True,
        help_text="e.g. B.Des, M.Des, Diploma.",
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


class Degree(models.Model):
    """UG / PG / Diploma / Certificate."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Course(models.Model):
    """Specific course/track inside a Program (e.g. "B.Des. Fashion Year 1").
    Carries the syllabus/semester structure. Used by Student.course_id and
    Enrollment.course."""

    name = models.CharField(max_length=160)
    code = models.CharField(max_length=30, unique=True)
    program = models.ForeignKey(
        "master.Program", on_delete=models.PROTECT, related_name="courses",
    )
    duration_months = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        unique_together = (("name", "program"),)

    def __str__(self):
        return f"{self.name} ({self.code})"


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
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        unique_together = (("name", "program", "campus", "academic_year"),)

    def __str__(self):
        return f"{self.name} — {self.campus.code} {self.academic_year.code}"


class FeeTemplate(models.Model):
    """Fee structure for an enrollment context (PHP `fee_master`).

    Keyed on (academic_year, campus, program, course). The template
    holds the headline numbers; per-student installments + receipts
    live in the `fees` app.
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
        help_text="Optional — leave blank if the same fee covers the whole program.",
    )

    application_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="One-time non-refundable fee at application time.",
    )
    course_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Tuition / course fee for the period.",
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
