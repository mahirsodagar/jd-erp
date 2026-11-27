"""Email → lead intake (Leads → Email Inbox).

The institute's lead inbox (leads@jdinstitute.edu.in) receives every
lead-bearing email regardless of source: the website's own Forminator
notifications, tawk.to chat transcripts, and whatever a listing portal
sends. A poller (`manage.py fetch_lead_emails`) reads new mail over IMAP,
stores each message raw as an `InboundLeadEmail`, runs it through a
parser, maps the free text to master rows and creates the lead through
`services.create_lead` so dedupe and round-robin apply as usual.

Nothing is deleted or modified in the mailbox; the ERP keeps its own
cursor (`LeadMailSyncState`) and its own copy of every message.
"""

from django.conf import settings
from django.db import models


class LeadMailRule(models.Model):
    """Admin-managed routing: which sender / subject gets which parser,
    lead source and default campus. Rules are tried in `priority` order;
    the first match wins. With no match the AUTO parser runs."""

    class Parser(models.TextChoices):
        AUTO = "auto", "Auto-detect"
        WEBSITE = "website", "Website form notification"
        TAWK = "tawk", "tawk.to chat"
        GENERIC = "generic", "Generic label: value"
        IGNORE = "ignore", "Ignore (not a lead)"

    name = models.CharField(max_length=80)
    match_from = models.CharField(
        max_length=120, blank=True,
        help_text="Text the From address must contain (case-insensitive). Blank = any.",
    )
    match_subject = models.CharField(
        max_length=160, blank=True,
        help_text="Text the Subject must contain (case-insensitive). Blank = any.",
    )
    parser = models.CharField(max_length=10, choices=Parser.choices, default=Parser.AUTO)
    source = models.ForeignKey(
        "master.LeadSource", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
        help_text="Lead source stamped on leads from this rule. Blank = "
                  "resolve from the email (website form title) or the '*' map.",
    )
    default_campus = models.ForeignKey(
        "master.Campus", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
        help_text="Campus used when the email names none. Blank = the '*' campus map.",
    )
    priority = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("priority", "id")

    def __str__(self):
        return self.name

    def matches(self, from_address: str, subject: str) -> bool:
        f = (from_address or "").lower()
        s = (subject or "").lower()
        if self.match_from and self.match_from.lower() not in f:
            return False
        if self.match_subject and self.match_subject.lower() not in s:
            return False
        return bool(self.match_from or self.match_subject)


class LeadMailSyncState(models.Model):
    """One row per mailbox: the IMAP cursor plus last-run health."""

    mailbox = models.CharField(max_length=254, unique=True)
    uidvalidity = models.BigIntegerField(default=0)
    last_uid = models.BigIntegerField(
        default=0, help_text="Highest IMAP UID already fetched.")
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    fetched_total = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.mailbox} (uid {self.last_uid})"


class InboundLeadEmail(models.Model):
    """One row per message pulled from the inbox, stored before parsing
    so a mail that cannot be read is still visible and can be turned
    into a lead by hand."""

    class Status(models.TextChoices):
        CREATED = "created", "Lead created"
        REPEAT = "repeat", "Lead created (repeat enquiry)"
        ALREADY = "already", "Already in ERP"
        UNPARSED = "unparsed", "Could not read — needs manual entry"
        IGNORED = "ignored", "Ignored"
        ERROR = "error", "Error"
        MANUAL = "manual", "Lead created manually"

    mailbox = models.CharField(max_length=254, db_index=True)
    uid = models.BigIntegerField()
    uidvalidity = models.BigIntegerField(default=0)
    message_id = models.CharField(max_length=255, blank=True, db_index=True)

    from_address = models.CharField(max_length=254, blank=True, db_index=True)
    from_name = models.CharField(max_length=160, blank=True)
    subject = models.CharField(max_length=500, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True, db_index=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    text_body = models.TextField(blank=True)
    html_body = models.TextField(blank=True)

    rule = models.ForeignKey(
        LeadMailRule, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="emails")
    parser = models.CharField(max_length=10, blank=True, db_index=True)
    parsed = models.JSONField(
        default=dict, blank=True,
        help_text="Fields the parser extracted (name, phone, campus_raw ...).")
    warnings = models.JSONField(default=list, blank=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.UNPARSED,
        db_index=True)
    error = models.TextField(blank=True)
    lead = models.ForeignKey(
        "leads.Lead", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="inbound_emails")
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
        help_text="Staff member who created the lead by hand or ignored the mail.")

    class Meta:
        ordering = ("-sent_at", "-id")
        unique_together = (("mailbox", "uidvalidity", "uid"),)
        indexes = [models.Index(fields=["status", "sent_at"])]

    def __str__(self):
        return f"{self.sent_at:%Y-%m-%d %H:%M} {self.subject[:60]} [{self.status}]"
