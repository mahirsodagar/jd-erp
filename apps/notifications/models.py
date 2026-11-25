from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class NotificationTemplate(models.Model):
    """Reusable email / WhatsApp / SMS / in-CRM templates. Body uses
    Python str.format() with named placeholders from the context dict
    passed at queue-time."""

    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        WHATSAPP = "WHATSAPP", "WhatsApp"
        SMS = "SMS", "SMS"
        IN_CRM = "IN_CRM", "In-CRM"

    key = models.CharField(
        max_length=80, unique=True,
        help_text="Stable id, e.g. 'lead_welcome', 'hot_why_join_jd'.",
    )
    channel = models.CharField(max_length=10, choices=Channel.choices)
    subject_template = models.CharField(max_length=200, blank=True)
    body_template = models.TextField()
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("key", "channel")

    def __str__(self):
        return f"{self.key} [{self.channel}]"


class ScheduledNotification(models.Model):
    """Future-dated notification waiting to be processed by the
    `process_notifications` management command.

    On PA free we have no Celery / cron — this table acts as the queue.
    Run the command on whatever schedule the host supports (manual,
    PythonAnywhere Tasks, OS cron once you upgrade).
    """

    template_key = models.CharField(max_length=80, db_index=True)
    channel = models.CharField(max_length=10, choices=NotificationTemplate.Channel.choices)
    recipient = models.CharField(max_length=200)
    cc = models.CharField(max_length=400, blank=True)
    context = models.JSONField(default=dict, blank=True)

    fire_at = models.DateTimeField(db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    # Generic relation to whatever object triggered this notification
    # (a Lead, a LeadFollowup, an Enrollment, etc.).
    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL,
    )
    object_id = models.CharField(max_length=64, blank=True, default="")
    related_object = GenericForeignKey("content_type", "object_id")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("fire_at",)
        indexes = [
            models.Index(fields=["fire_at", "processed_at"]),
        ]

    def __str__(self):
        return f"{self.template_key} → {self.recipient} @ {self.fire_at:%Y-%m-%d %H:%M}"


class NotificationDispatchLog(models.Model):
    """One row per intended dispatch. On PA free no real provider call is
    made — the row stays at status='QUEUED' forever and a future
    drainer (when SMTP / MSG91 hostname is reachable) will flip them to
    'SENT' or 'FAILED'."""

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    channel = models.CharField(max_length=10, choices=NotificationTemplate.Channel.choices)
    template_key = models.CharField(max_length=80, db_index=True)
    recipient = models.CharField(max_length=200)
    cc = models.CharField(max_length=400, blank=True)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True,
    )
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL,
    )
    object_id = models.CharField(max_length=64, blank=True, default="")
    related_object = GenericForeignKey("content_type", "object_id")

    scheduled = models.ForeignKey(
        ScheduledNotification, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="dispatches",
    )
    # Which saved revision of a system e-mail template produced this
    # mail (null = the code default, or a non-template channel).
    template_version = models.ForeignKey(
        "notifications.SystemEmailTemplateVersion", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="dispatches",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]


# --- System e-mail templates (Communication → System Emails) -----------
#
# Every mail the system sends is a trigger in `apps.notifications.registry`
# with a code default. These rows hold what an admin customised: one
# optional global row per trigger plus one optional row per institute,
# resolved institute → global → code default at send time. A row never
# deletes history: every save appends a `SystemEmailTemplateVersion`.


class EditorMode(models.TextChoices):
    VISUAL = "visual", "Visual editor"
    HTML = "html", "HTML source"


class SystemEmailTemplate(models.Model):
    trigger_key = models.CharField(max_length=80, db_index=True)
    institute = models.ForeignKey(
        "master.Institute", null=True, blank=True, on_delete=models.CASCADE,
        related_name="system_email_templates",
        help_text="Blank = the global template; set = an override for one institute.",
    )
    subject = models.CharField(max_length=200)
    body_html = models.TextField()
    # Overrides the per-trigger Reply-To policy when set.
    reply_to = models.CharField(max_length=200, blank=True)
    # Comma-separated addresses added to CC on every send.
    cc_extra = models.CharField(max_length=600, blank=True)
    # Wrap the body in the institute header/footer layout.
    use_layout = models.BooleanField(default=True)
    editor_mode = models.CharField(
        max_length=8, choices=EditorMode.choices, default=EditorMode.VISUAL,
    )
    # An inactive institute override falls back to the global template.
    is_active = models.BooleanField(default=True)

    updated_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("trigger_key", "institute_id")
        constraints = [
            models.UniqueConstraint(
                fields=["trigger_key", "institute"],
                name="uniq_system_email_template_per_scope",
            ),
            # Postgres/SQLite treat NULLs as distinct in a plain unique
            # constraint, so the global row needs its own guard.
            models.UniqueConstraint(
                fields=["trigger_key"], condition=models.Q(institute__isnull=True),
                name="uniq_system_email_template_global",
            ),
        ]

    def __str__(self):
        scope = self.institute.code if self.institute_id else "global"
        return f"{self.trigger_key} [{scope}]"


class SystemEmailTemplateVersion(models.Model):
    """Immutable snapshot taken on every save of a SystemEmailTemplate.
    `number` counts up per template; revert copies a version forward as
    a new one, so history is append-only."""

    template = models.ForeignKey(
        SystemEmailTemplate, on_delete=models.CASCADE, related_name="versions",
    )
    number = models.PositiveIntegerField()
    subject = models.CharField(max_length=200)
    body_html = models.TextField()
    reply_to = models.CharField(max_length=200, blank=True)
    cc_extra = models.CharField(max_length=600, blank=True)
    use_layout = models.BooleanField(default=True)
    editor_mode = models.CharField(max_length=8, default=EditorMode.VISUAL)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-number",)
        constraints = [
            models.UniqueConstraint(
                fields=["template", "number"], name="uniq_system_email_version_no",
            ),
        ]

    def __str__(self):
        return f"{self.template_id} v{self.number}"


def _template_attachment_path(instance, filename):
    return f"notifications/template_attachments/{instance.template_id or 'new'}/{filename}"


class SystemEmailAttachment(models.Model):
    """A fixed file an admin attached to a template (brochure, policy…);
    sent with every mail of that trigger on top of whatever the code
    attaches itself (receipt PDF, letters)."""

    template = models.ForeignKey(
        SystemEmailTemplate, on_delete=models.CASCADE, related_name="attachments",
    )
    file = models.FileField(upload_to=_template_attachment_path)
    filename = models.CharField(max_length=200)
    content_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return self.filename


class EmailLayout(models.Model):
    """Header / footer every templated mail slots into (`use_layout`).
    One row per institute plus one global row (institute NULL) used by
    mail that has no institute or whose institute has no layout."""

    institute = models.OneToOneField(
        "master.Institute", null=True, blank=True, on_delete=models.CASCADE,
        related_name="email_layout",
    )
    header_html = models.TextField(blank=True)
    footer_html = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Email layout [{self.institute.code if self.institute_id else 'global'}]"

    @classmethod
    def global_row(cls):
        """The single institute-less layout (created blank on demand;
        `institute=None` is not unique at the DB level, so always go
        through here)."""
        row = cls.objects.filter(institute__isnull=True).order_by("pk").first()
        return row or cls.objects.create(institute=None)


class EmailLayoutVersion(models.Model):
    layout = models.ForeignKey(
        EmailLayout, on_delete=models.CASCADE, related_name="versions",
    )
    number = models.PositiveIntegerField()
    header_html = models.TextField(blank=True)
    footer_html = models.TextField(blank=True)
    is_enabled = models.BooleanField(default=True)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-number",)
        constraints = [
            models.UniqueConstraint(
                fields=["layout", "number"], name="uniq_email_layout_version_no",
            ),
        ]


class InAppNotification(models.Model):
    """One line in a user's notification bell. Written best-effort by
    the modules (tasks, timetable, leaves); never on the request's
    critical path. `link` is a frontend route the bell navigates to."""

    class Kind(models.TextChoices):
        TASK = "TASK", "Task"
        TIMETABLE = "TIMETABLE", "Timetable"
        LEAVE = "LEAVE", "Leave"
        OTHER = "OTHER", "Other"

    recipient = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE,
        related_name="inapp_notifications",
    )
    kind = models.CharField(
        max_length=12, choices=Kind.choices, default=Kind.OTHER,
    )
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500, blank=True)
    link = models.CharField(max_length=200, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["recipient", "is_read", "created_at"]),
        ]

    def __str__(self):
        return f"[{self.kind}] {self.title} → {self.recipient_id}"
