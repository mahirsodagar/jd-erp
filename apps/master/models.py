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
