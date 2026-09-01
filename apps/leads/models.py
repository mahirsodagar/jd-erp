from django.conf import settings
from django.db import models


class Lead(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        NON_RESPONSIVE = "non_responsive", "Non Responsive"
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

    # Parent contact captured at lead creation. Required by the Add Lead
    # form (validated at the API layer in LeadCreateSerializer); kept
    # `blank=True` on the model so historical rows stay valid and
    # subsequent edits via LeadUpdateSerializer aren't forced to refill.
    father_mobile = models.CharField(max_length=32, blank=True)
    father_email = models.EmailField(blank=True)

    # Self-fill application form token. Generated when staff clicks
    # "Send application link". The link stays valid for re-edits so the
    # student can add missing details after a counsellor review — close
    # the form via `application_locked_for_student` to stop that.
    application_token = models.UUIDField(
        null=True, blank=True, unique=True, db_index=True,
        help_text="UUID embedded in the public application link.",
    )
    application_token_sent_at = models.DateTimeField(null=True, blank=True)

    # Counsellor-controlled kill switch. While True, the public POST is
    # rejected with 403 ("form closed by counsellor"); GET still works so
    # the student can see what was submitted. Staff edits via the
    # authenticated admissions endpoints are unaffected.
    application_locked_for_student = models.BooleanField(
        default=False, db_index=True,
    )
    application_locked_at = models.DateTimeField(null=True, blank=True)
    application_locked_by = models.ForeignKey(
        "accounts.User", null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="application_locks_set",
    )

    # --- Application fee (manual reconciliation) ---------------------
    # Counsellor sends a fee link (UPI / QR / bank email) → student pays
    # → counsellor or accounts marks it paid here. Application form link
    # is gated on `application_fee_paid_at` being non-null.
    application_fee_paid_at = models.DateTimeField(null=True, blank=True)
    application_fee_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
    application_fee_mode = models.CharField(
        max_length=10, blank=True,
        help_text="CASH / CHEQUE / DD / ONLINE / UPI / NEFT / RTGS",
    )
    application_fee_ref = models.CharField(
        max_length=120, blank=True,
        help_text="UPI txn id / cheque no / bank ref / receipt no.",
    )
    application_fee_notes = models.TextField(blank=True)
    application_fee_recorded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="application_fees_recorded",
    )
    # Stamped each time the fee-payment link (UPI / QR / bank email) is
    # sent. Mirrors `application_token_sent_at`; lets the UI show
    # "Resend fee link" once the first one has gone out.
    fee_link_sent_at = models.DateTimeField(null=True, blank=True)

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


class Counsellor(models.Model):
    """An employee flagged as a counsellor.

    Replaces the per-category counsellor pools: there is now one flat
    list. Every counsellor is an Employee, and the Employee must have a
    portal `user_account` — `Lead.assign_to` points at a User, so an
    employee with no login cannot hold a lead. New leads rotate through
    the active counsellors, and the lead-assignment pickers show only
    the people listed here.
    """

    employee = models.OneToOneField(
        "employees.Employee", on_delete=models.CASCADE,
        related_name="counsellor",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=100,
        help_text="Stable rotation order — counsellors with a lower "
                  "sort_order get leads first.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Paused counsellors are skipped by the round-robin but "
                  "keep the leads they already hold.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "id")

    def __str__(self):
        return self.employee.full_name

    @property
    def user(self):
        """The portal account leads get assigned to. None if HR has not
        provisioned one (or cleared it after the fact)."""
        return self.employee.user_account


class CounsellorRotation(models.Model):
    """Single-row table holding the round-robin pointer.

    The pool model carried its pointer on the pool row; with one flat
    list there is no such row, so this stands in as the thing
    `select_for_update` locks — that lock is what stops two concurrent
    lead creates handing the same counsellor both leads.
    """

    SINGLETON_PK = 1

    pointer = models.PositiveIntegerField(
        default=0,
        help_text="Round-robin offset; advanced after each assignment.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Counsellor rotation @ {self.pointer}"


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


# Entrance Exam models live in a separate module for readability; re-export
# them here so Django registers them under the `leads` app_label.
from .exam_models import (  # noqa: E402,F401
    EntranceExam,
    EntranceExamAttempt,
    EntranceExamQuestion,
    EntranceExamResponse,
)
