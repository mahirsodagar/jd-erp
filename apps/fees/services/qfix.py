"""Qfix payment-webhook plumbing.

Lifecycle:

    1. Qfix POSTs to `/api/fees/webhooks/qfix/` with a signed JSON body.
    2. `verify_signature` checks `X-Qfix-Signature` against
       HMAC-SHA256(settings.QFIX_WEBHOOK_SECRET, raw_body).
    3. `process_event` deserialises the payload, finds the matching
       Enrollment, and on a success event creates a `FeeReceipt`.
       Every call is recorded in `QfixWebhookEvent` for audit + idempotency.

Until Qfix support sends us their concrete payload schema, the
`_extract_*` helpers use the field names we *expect* (transaction_id /
amount / status / reference). Swap the literal strings in this module
when the docs arrive — the surrounding flow stays the same.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.admissions.models import Enrollment, Student

from ..models import FeeReceipt, QfixWebhookEvent
from .receipt_no import generate_receipt_no

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- signature

def verify_signature(raw_body: bytes, header_value: str | None) -> bool:
    """Constant-time HMAC-SHA256 check.

    Returns True if:
      - the configured secret is empty (sandbox/dev mode — we accept
        any caller but log a warning), OR
      - the signature header matches the computed digest.
    """
    secret = getattr(settings, "QFIX_WEBHOOK_SECRET", "") or ""
    if not secret:
        logger.warning(
            "QFIX_WEBHOOK_SECRET is not set — accepting webhook without "
            "signature verification. Set the env var in production.",
        )
        return True
    if not header_value:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256,
    ).hexdigest()
    # Qfix may prefix the digest with "sha256=" — accept both.
    candidate = header_value.split("=", 1)[1] if "=" in header_value else header_value
    return hmac.compare_digest(expected, candidate.strip())


# ---------------------------------------------------------------- extraction

@dataclass
class ParsedQfixEvent:
    transaction_id: str
    amount: Decimal
    is_success: bool
    enrollment: Enrollment | None
    payment_mode: str  # mapped to FeeReceipt.PaymentMode value
    instrument_ref: str
    received_date: Any  # datetime.date
    raw: dict


def parse_event(payload: dict) -> ParsedQfixEvent:
    """Pull the fields we care about out of the Qfix payload.

    TODO: once Qfix docs are in hand, update each `payload.get(...)`
    key below to match their schema. The current names are placeholders.
    """
    txn_id = str(
        payload.get("transaction_id")
        or payload.get("txn_id")
        or payload.get("id")
        or "",
    ).strip()

    raw_amount = (
        payload.get("amount")
        or payload.get("paid_amount")
        or payload.get("total_amount")
        or "0"
    )
    try:
        amount = Decimal(str(raw_amount))
    except (InvalidOperation, TypeError):
        amount = Decimal("0")

    # Status text we treat as "money landed". Extend this list when
    # Qfix tells us their canonical success codes.
    success_values = {"SUCCESS", "SUCCESSFUL", "CAPTURED", "PAID", "COMPLETED"}
    status_value = str(
        payload.get("status") or payload.get("payment_status") or "",
    ).upper()
    is_success = status_value in success_values

    # Reference that tells us *which* enrollment this payment is for.
    # We control this when we build the prefilled payment URL — so the
    # cleanest pattern is to encode `enrollment_id` directly into a
    # custom merchant field. Fallback: look up by student application_form_id.
    reference = str(
        payload.get("merchant_reference")
        or payload.get("merchant_ref")
        or payload.get("reference")
        or payload.get("custom_ref")
        or "",
    ).strip()
    enrollment = _resolve_enrollment(reference)

    # Qfix's own gateway-level payment mode → map to FeeReceipt.PaymentMode.
    raw_mode = str(
        payload.get("payment_mode") or payload.get("mode") or "",
    ).upper()
    payment_mode = _map_mode(raw_mode)

    # Provider's gateway transaction id — most useful thing to record
    # as `instrument_ref` so accounts can reconcile against Qfix's report.
    instrument_ref = (
        str(payload.get("gateway_ref") or payload.get("rrn") or txn_id)
    )

    paid_at = payload.get("paid_at") or payload.get("received_at")
    received_date = timezone.now().date()
    if paid_at:
        try:
            # Accept either ISO datetime or YYYY-MM-DD; fall back to today.
            received_date = timezone.datetime.fromisoformat(
                str(paid_at).replace("Z", "+00:00"),
            ).date()
        except (ValueError, TypeError):
            pass

    return ParsedQfixEvent(
        transaction_id=txn_id,
        amount=amount,
        is_success=is_success,
        enrollment=enrollment,
        payment_mode=payment_mode,
        instrument_ref=instrument_ref,
        received_date=received_date,
        raw=payload,
    )


def _resolve_enrollment(reference: str) -> Enrollment | None:
    """Find the enrollment a Qfix payment belongs to.

    Three lookup strategies, tried in order:
      1. `ENR:<id>`         — what we'll emit from the prefilled URL builder
      2. plain integer      — enrollment id
      3. application_form_id — the student-facing ID printed on the app form
    """
    if not reference:
        return None
    if reference.upper().startswith("ENR:"):
        reference = reference[4:]
    if reference.isdigit():
        return Enrollment.objects.filter(pk=int(reference)).first()
    student = Student.objects.filter(application_form_id=reference).first()
    if student is None:
        return None
    # Pick the most recent active enrollment for that student.
    return (
        student.enrollments.filter(status=Enrollment.Status.ACTIVE)
        .order_by("-created_on")
        .first()
        or student.enrollments.order_by("-created_on").first()
    )


def _map_mode(raw: str) -> str:
    """Qfix may report e.g. 'UPI', 'NETBANKING', 'CARD', 'WALLET'.
    Map to our FeeReceipt.PaymentMode choices."""
    if "UPI" in raw:
        return FeeReceipt.PaymentMode.UPI
    if "NEFT" in raw:
        return FeeReceipt.PaymentMode.NEFT
    if "RTGS" in raw:
        return FeeReceipt.PaymentMode.RTGS
    return FeeReceipt.PaymentMode.ONLINE


# ---------------------------------------------------------------- processing

@dataclass
class ProcessResult:
    event: QfixWebhookEvent
    created: bool        # whether a new event row was inserted
    receipt_created: bool


def process_event(raw_payload: dict) -> ProcessResult:
    """Idempotently consume one Qfix event.

    Returns the persisted `QfixWebhookEvent` row (newly inserted or the
    pre-existing one if this is a retry).
    """
    parsed = parse_event(raw_payload)
    if not parsed.transaction_id:
        # No id → we can't dedupe, so record but don't post a receipt.
        ev = QfixWebhookEvent.objects.create(
            transaction_id=f"unknown-{timezone.now().timestamp()}",
            raw_payload=raw_payload,
            status=QfixWebhookEvent.Status.ERROR,
            error_message="Payload had no transaction_id-like field.",
            processed_at=timezone.now(),
        )
        return ProcessResult(event=ev, created=True, receipt_created=False)

    with transaction.atomic():
        ev, created = QfixWebhookEvent.objects.get_or_create(
            transaction_id=parsed.transaction_id,
            defaults={
                "raw_payload": raw_payload,
                "status": QfixWebhookEvent.Status.RECEIVED,
            },
        )
        if not created:
            # Already processed once — return without doing anything.
            return ProcessResult(event=ev, created=False, receipt_created=False)

        if not parsed.is_success:
            ev.status = QfixWebhookEvent.Status.SKIPPED
            ev.error_message = (
                "Event status not a success value — no receipt created."
            )
            ev.processed_at = timezone.now()
            ev.save(update_fields=["status", "error_message", "processed_at"])
            return ProcessResult(event=ev, created=True, receipt_created=False)

        if parsed.enrollment is None:
            ev.status = QfixWebhookEvent.Status.ERROR
            ev.error_message = (
                "Could not resolve a matching enrollment for the supplied "
                "reference. Check the merchant-reference field Qfix sent."
            )
            ev.processed_at = timezone.now()
            ev.save(update_fields=["status", "error_message", "processed_at"])
            return ProcessResult(event=ev, created=True, receipt_created=False)

        # Qfix only knows the gross amount; we don't have a GST split,
        # so default basic_fee = amount and taxes = 0. Matches the
        # serializer's validate() which expects basic+taxes==amount.
        receipt = FeeReceipt.objects.create(
            receipt_no=generate_receipt_no(
                campus_code=parsed.enrollment.campus.code,
            ),
            enrollment=parsed.enrollment,
            basic_fee=parsed.amount,
            amount=parsed.amount,
            payment_mode=parsed.payment_mode,
            instrument_ref=parsed.instrument_ref,
            received_date=parsed.received_date,
            notes=f"Auto-created from Qfix webhook {parsed.transaction_id}",
        )

        ev.receipt = receipt
        ev.status = QfixWebhookEvent.Status.PROCESSED
        ev.processed_at = timezone.now()
        ev.save(update_fields=["receipt", "status", "processed_at"])

        return ProcessResult(event=ev, created=True, receipt_created=True)
