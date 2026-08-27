"""HDFC SmartGateway payment requests, orders and webhook events.

Three tables, and the split between the first two is forced by how
SmartGateway works.

SmartGateway's `/session` API mints a **payment page session** whose
`payment_links.web` URL expires (minutes to hours, set per merchant).
That is fine for a checkout button, but our application fee goes out by
SMS/WhatsApp/email and a lead may pay days later — a URL minted at
send time would be dead on arrival.

So we send a link to *us*, not to the bank:

    PaymentRequest   one per "this lead owes this fee", carries the
                     public `token` embedded in the SMS. Long-lived and
                     stable, so resending doesn't invalidate what the
                     student already has.
        └── PaymentOrder   one per SmartGateway order, minted fresh when
                           the student actually opens the link, and again
                           if they come back after the session expired.

`PaymentOrder.order_id` is what the bank knows us by, and SmartGateway
constrains it hard: under 21 characters, no special characters.

Kept in its own app rather than inside `leads` because none of this is
lead-specific: `PaymentRequest.purpose` is the discriminator, and today
only APPLICATION_FEE is wired up. Student fee installments would add a
purpose and a nullable FK alongside `lead`.
"""

import uuid

from django.conf import settings
from django.db import models


class PaymentRequest(models.Model):
    """A standing request for money from a lead, addressed by a token.

    The token is the only thing that appears in the SMS, so it must stay
    valid for as long as the counsellor is chasing the fee — see the
    module docstring for why the bank's own URL can't play that role.
    """

    class Purpose(models.TextChoices):
        APPLICATION_FEE = "APPLICATION_FEE", "Application fee (lead)"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Awaiting payment"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    token = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False, db_index=True,
        help_text="Embedded in the public pay URL. Never reused.",
    )

    purpose = models.CharField(
        max_length=20, choices=Purpose.choices,
        default=Purpose.APPLICATION_FEE, db_index=True,
    )
    lead = models.ForeignKey(
        "leads.Lead", null=True, blank=True, on_delete=models.CASCADE,
        related_name="payment_requests",
        help_text="Set for APPLICATION_FEE requests.",
    )

    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Rupees. SmartGateway takes this as a 2dp string.",
    )
    currency = models.CharField(max_length=3, default="INR")
    description = models.CharField(max_length=200, blank=True)

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING,
        db_index=True,
    )
    paid_order = models.ForeignKey(
        "PaymentOrder", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
        help_text="The order that actually settled this request.",
    )
    paid_at = models.DateTimeField(null=True, blank=True)

    #: Counts orders minted so far. Drives the order_id suffix, so it
    #: must keep climbing even when an order fails — the bank rejects a
    #: reused order_id.
    attempt_count = models.PositiveSmallIntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="payment_requests_created",
    )
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_on",)
        indexes = [
            models.Index(fields=["lead", "status"]),
            models.Index(fields=["purpose", "status"]),
        ]

    def __str__(self):
        return f"{self.purpose} {self.amount} ({self.status})"

    @property
    def is_open(self) -> bool:
        """Still payable — a new request should not be raised alongside."""
        return self.status == self.Status.PENDING


class PaymentOrder(models.Model):
    """One SmartGateway order — i.e. one trip to the payment page.

    A request can accumulate several of these: the student opens the link,
    wanders off, the session expires, and they come back tomorrow. Only
    one of them ever reaches CHARGED.
    """

    class Status(models.TextChoices):
        # Non-terminal — keep polling.
        NEW = "NEW", "Created, not yet attempted"
        STARTED = "STARTED", "Started"
        PENDING_VBV = "PENDING_VBV", "Authentication in progress"
        AUTHORIZING = "AUTHORIZING", "Awaiting bank response"
        CAPTURE_INITIATED = "CAPTURE_INITIATED", "Capture in progress"
        VOID_INITIATED = "VOID_INITIATED", "Void in progress"
        # Terminal success.
        CHARGED = "CHARGED", "Charged (paid)"
        AUTHORIZED = "AUTHORIZED", "Authorized, awaiting capture"
        # Terminal failure / reversal.
        AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED", "Authentication failed"
        AUTHORIZATION_FAILED = "AUTHORIZATION_FAILED", "Authorization failed"
        JUSPAY_DECLINED = "JUSPAY_DECLINED", "Declined by gateway"
        CAPTURE_FAILED = "CAPTURE_FAILED", "Capture failed"
        VOID_FAILED = "VOID_FAILED", "Void failed"
        VOIDED = "VOIDED", "Voided"
        AUTO_REFUNDED = "AUTO_REFUNDED", "Auto-refunded"

    #: The one status that means money actually moved and stayed moved.
    #: AUTHORIZED is deliberately NOT here: it is a hold, not a capture,
    #: and the application fee is configured for auto-capture.
    PAID_STATUSES = frozenset({Status.CHARGED})

    #: Nothing further will happen to an order in one of these.
    TERMINAL_STATUSES = frozenset({
        Status.CHARGED, Status.AUTHENTICATION_FAILED,
        Status.AUTHORIZATION_FAILED, Status.JUSPAY_DECLINED,
        Status.CAPTURE_FAILED, Status.VOID_FAILED, Status.VOIDED,
        Status.AUTO_REFUNDED,
    })

    request = models.ForeignKey(
        PaymentRequest, on_delete=models.CASCADE, related_name="orders",
    )

    order_id = models.CharField(
        max_length=21, unique=True,
        help_text="Our id for the order, as the bank knows it. "
                  "SmartGateway caps this at 20 chars, alphanumeric only.",
    )
    sg_order_ref = models.CharField(
        max_length=64, blank=True, db_index=True,
        help_text="SmartGateway's own 'ordeh_xxx' id from the session "
                  "response.",
    )
    payment_page_url = models.URLField(
        max_length=500, blank=True,
        help_text="payment_links.web — the hosted page we redirect to.",
    )
    session_expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When payment_page_url stops working. A fresh order is "
                  "minted when a student returns after this.",
    )

    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.NEW,
        db_index=True,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    txn_id = models.CharField(max_length=80, blank=True)
    txn_uuid = models.CharField(max_length=64, blank=True)
    payment_method = models.CharField(
        max_length=40, blank=True, help_text="VISA / MASTERCARD / UPI …",
    )
    payment_method_type = models.CharField(
        max_length=24, blank=True, help_text="CARD / NB / WALLET / UPI …",
    )
    bank_error_code = models.CharField(max_length=64, blank=True)
    bank_error_message = models.CharField(max_length=300, blank=True)

    charged_at = models.DateTimeField(null=True, blank=True)

    #: Last full order body seen, from either the webhook or /orders/.
    last_payload = models.JSONField(null=True, blank=True)

    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_on",)
        indexes = [models.Index(fields=["request", "status"])]

    def __str__(self):
        return f"{self.order_id} ({self.status})"

    @property
    def is_paid(self) -> bool:
        return self.status in self.PAID_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES


class SmartGatewayWebhookEvent(models.Model):
    """Append-only log of every webhook SmartGateway delivered.

    SmartGateway retries until it gets a 200 and warns that a webhook may
    arrive more than once, so `event_id` (the payload's own `id`) is
    unique and replay is a no-op.
    """

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        PROCESSED = "PROCESSED", "Processed"
        SKIPPED = "SKIPPED", "Skipped (event we don't act on)"
        ERROR = "ERROR", "Error"

    event_id = models.CharField(
        max_length=120, unique=True,
        help_text="The payload's `id`, e.g. 'evt_V2_xxx' — our "
                  "idempotency key.",
    )
    event_name = models.CharField(max_length=60, db_index=True)
    payload = models.JSONField()

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.RECEIVED,
    )
    error_message = models.TextField(blank=True)

    order = models.ForeignKey(
        PaymentOrder, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="webhook_events",
    )

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-received_at",)

    def __str__(self):
        return f"{self.event_name} {self.event_id} ({self.status})"
