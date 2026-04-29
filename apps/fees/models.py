from decimal import Decimal

from django.conf import settings
from django.db import models


class Installment(models.Model):
    """Per-student installment schedule (PHP `student_installment`).

    Created by HR after enrollment. Multiple receipts can be linked to
    one installment (split payments allowed).
    """

    enrollment = models.ForeignKey(
        "admissions.Enrollment", on_delete=models.CASCADE,
        related_name="installments",
    )
    sequence = models.PositiveSmallIntegerField(
        help_text="1-indexed installment number for this enrollment.",
    )
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=200, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="installments_created",
    )
    created_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("enrollment", "sequence")
        unique_together = (("enrollment", "sequence"),)

    def __str__(self):
        return f"#{self.sequence} ({self.amount}) due {self.due_date}"


class FeeReceipt(models.Model):
    """A payment recorded against an enrollment (PHP `feecollection`)."""

    class PaymentMode(models.TextChoices):
        CASH = "CASH", "Cash"
        CHEQUE = "CHEQUE", "Cheque"
        DD = "DD", "Demand Draft"
        ONLINE = "ONLINE", "Online (card / netbanking)"
        UPI = "UPI", "UPI"
        NEFT = "NEFT", "NEFT"
        RTGS = "RTGS", "RTGS"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CANCELLED = "CANCELLED", "Cancelled"

    receipt_no = models.CharField(max_length=40, unique=True)

    enrollment = models.ForeignKey(
        "admissions.Enrollment", on_delete=models.PROTECT,
        related_name="receipts",
    )
    installment = models.ForeignKey(
        Installment, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="receipts",
        help_text="Optional — receipts can be linked to a specific installment.",
    )

    basic_fee = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Pre-tax amount.",
    )
    sgst = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    cgst = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    igst = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Total received (basic_fee + sgst + cgst + igst).",
    )

    payment_mode = models.CharField(max_length=10, choices=PaymentMode.choices)
    instrument_ref = models.CharField(
        max_length=80, blank=True,
        help_text="Cheque / DD number, bank txn id, UPI ref.",
    )
    bank = models.CharField(max_length=120, blank=True)

    received_date = models.DateField()
    notes = models.TextField(blank=True)

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ACTIVE,
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="receipts_cancelled",
    )
    cancelled_on = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="receipts_received",
    )
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-received_date", "-created_on")
        indexes = [
            models.Index(fields=["enrollment", "status"]),
            models.Index(fields=["receipt_no"]),
            models.Index(fields=["received_date"]),
        ]

    def __str__(self):
        return f"{self.receipt_no} ({self.amount} {self.payment_mode})"


class Concession(models.Model):
    """Discount on the fee total. PHP `student_concession`.

    Single-step approval workflow (per spec Q4): anyone with
    `fees.concession.approve` can decide.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    enrollment = models.ForeignKey(
        "admissions.Enrollment", on_delete=models.CASCADE,
        related_name="concessions",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING,
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="concessions_requested",
    )
    requested_on = models.DateTimeField(auto_now_add=True)

    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="concessions_decided",
    )
    approver_remarks = models.TextField(blank=True)
    decided_on = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-requested_on",)
        indexes = [
            models.Index(fields=["enrollment", "status"]),
        ]

    def __str__(self):
        return f"Concession {self.amount} ({self.status})"
