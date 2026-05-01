from django.conf import settings
from django.db import models


class Lead(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        APPLICATION_SUBMITTED = "application_submitted", "Application Submitted"
        ENROLLED = "enrolled", "Enrolled"

    class Occurrence(models.IntegerChoices):
        PRIMARY = 1, "Primary"
        SECONDARY = 2, "Secondary"
        TERTIARY = 3, "Tertiary"
        REPEATED = 4, "Repeated (4+)"

    name = models.CharField(max_length=160)
    email = models.EmailField()
    phone = models.CharField(max_length=32)
    phone_normalized = models.CharField(
        max_length=20, blank=True, db_index=True,
        help_text="Last 10 digits of phone, used for dedup matching.",
    )
    alternative_phone = models.CharField(max_length=32, blank=True)
    alternative_email = models.EmailField(blank=True)
    occurrence_number = models.PositiveSmallIntegerField(
        default=1, db_index=True,
        help_text="1=Primary, 2=Secondary, 3=Tertiary, 4+=Repeated.",
    )

    campus = models.ForeignKey(
        "master.Campus", on_delete=models.PROTECT, related_name="leads",
    )
    program = models.ForeignKey(
        "master.Program", on_delete=models.PROTECT, related_name="leads",
    )
    source = models.ForeignKey(
        "master.LeadSource", on_delete=models.PROTECT, related_name="leads",
    )

    assign_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_leads",
        help_text="Counsellor handling this lead. Auto-filled by round-robin "
                  "when omitted; null if the pool was empty at create time.",
    )

    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.ACTIVE, db_index=True,
    )

    remarks = models.TextField(blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)

    is_repeated = models.BooleanField(default=False, db_index=True)
    duplicate_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="duplicates",
        help_text="If is_repeated, points to the earliest matching lead.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leads_created",
        help_text="Null for automated leads from the intake endpoint.",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["phone"]),
            models.Index(fields=["status", "assign_to"]),
        ]

    def __str__(self):
        return f"{self.name} <{self.email}>"


class CounsellorPool(models.Model):
    """One pool per Program.Category. Counsellors round-robin within their
    pool. The `pointer` is the index of the next counsellor to assign."""

    class Category(models.TextChoices):
        REGULAR = "REGULAR", "Regular Course"
        SHORT = "SHORT", "Short Course"
        NEW = "NEW", "Newly launched"

    name = models.CharField(max_length=80, unique=True)
    category = models.CharField(
        max_length=10, choices=Category.choices, unique=True,
        help_text="One pool per program category.",
    )
    is_active = models.BooleanField(default=True)
    pointer = models.PositiveIntegerField(
        default=0,
        help_text="Round-robin offset; advanced after each assignment.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("category",)

    def __str__(self):
        return self.name


class CounsellorPoolMembership(models.Model):
    """Through table: a User can be in multiple pools."""

    pool = models.ForeignKey(
        CounsellorPool, on_delete=models.CASCADE, related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="pool_memberships",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=100,
        help_text="Stable order within the pool — counsellors with lower "
                  "sort_order get leads first. Used for fairness when "
                  "rotating.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("pool", "sort_order")
        unique_together = (("pool", "user"),)

    def __str__(self):
        return f"{self.user} in {self.pool.name}"


class LeadFollowup(models.Model):
    class Type(models.TextChoices):
        PHONE_CALL = "phone_call", "Phone call"
        EMAIL = "email", "Email"
        WHATSAPP = "whatsapp", "WhatsApp"
        SMS = "sms", "SMS"
        VISIT = "visit", "Campus visit"
        MEETING = "meeting", "Meeting"
        OTHER = "other", "Other"

    class Outcome(models.TextChoices):
        """Per JD Lead-to-Admission Process PDF, Phase 4."""
        HOT = "HOT", "Hot"
        WARM = "WARM", "Warm"
        COLD = "COLD", "Cold"
        NOT_ANSWERING = "NOT_ANSWERING", "Not Answering"
        NOT_CONNECTED = "NOT_CONNECTED", "Not Connected"
        ENROLLED = "ENROLLED", "Enrolled"

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="followups")
    followup_type = models.CharField(max_length=32, choices=Type.choices)
    notes = models.TextField(blank=True)
    next_followup_date = models.DateField(null=True, blank=True, db_index=True)

    # F.4 — mandatory outcome on every interaction.
    outcome_category = models.CharField(
        max_length=20, choices=Outcome.choices, blank=True, db_index=True,
        help_text="Required after Module F.4. Drives drip automation.",
    )
    outcome_disposition = models.CharField(
        max_length=80, blank=True,
        help_text="Sub-disposition within the category, e.g. 'feels Fees is high'.",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="followups_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["lead", "outcome_category"]),
        ]


class LeadStatusHistory(models.Model):
    """Append-only log of every status change. Written automatically
    by the status-change service — no manual API."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="status_history")
    old_status = models.CharField(max_length=32, blank=True)
    new_status = models.CharField(max_length=32)
    note = models.CharField(max_length=400, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="status_changes",
    )
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-changed_at",)
        verbose_name_plural = "Lead status histories"


class LeadCommunication(models.Model):
    """Record-only log of communications counselors have sent.
    No outbound delivery — that's a future module."""

    class Type(models.TextChoices):
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"
        CALL = "call", "Phone call"
        OTHER = "other", "Other"

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="communications")
    type = models.CharField(max_length=20, choices=Type.choices)
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField(blank=True)
    sent_at = models.DateTimeField(
        help_text="When the communication was actually sent.",
    )
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="communications_logged",
    )
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-sent_at",)


class LeadUtm(models.Model):
    """Marketing attribution data. One-to-one with Lead."""

    lead = models.OneToOneField(Lead, on_delete=models.CASCADE, related_name="utm")
    utm_source = models.CharField(max_length=120, blank=True)
    utm_campaign = models.CharField(max_length=160, blank=True)
    utm_medium = models.CharField(max_length=120, blank=True)
    utm_term = models.CharField(max_length=160, blank=True)
    utm_content = models.CharField(max_length=200, blank=True)
