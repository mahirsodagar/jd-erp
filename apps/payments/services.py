"""Business logic around SmartGateway payment requests.

Entry points that matter:

* `application_fee_request_for(lead, ...)` — called from
  `leads.send_links.send_fee_link` to get a stable pay URL for a lead.
* `start_or_resume_order(request)` — called when the student opens that
  URL; mints a SmartGateway session and hands back the page to redirect
  to.
* `process_webhook_event(...)` — called from the webhook view once the
  Basic credentials check out.
* `reconcile_order(order)` — pulls the truth from `/orders/{id}`.

Everything that writes to `Lead` lives here rather than in a view, so the
webhook, the return_url handler and the reconcile command all settle a
payment through exactly the same path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .gateway import (
    ORDER_ID_MAX_LENGTH,
    SmartGatewayError,
    create_session,
    fetch_order,
    is_enabled,
)
from .models import PaymentOrder, PaymentRequest, SmartGatewayWebhookEvent

logger = logging.getLogger("apps.payments")

#: Webhook events we act on. We subscribe narrowly in the dashboard, but
#: anyone can widen that, so the receiver must not assume.
HANDLED_EVENTS = {
    "ORDER_SUCCEEDED",
    "ORDER_FAILED",
    "TXN_CHARGED",
    "TXN_FAILED",
    "ORDER_REFUNDED",
    "AUTO_REFUND_SUCCEEDED",
}

#: How long before a session's stated expiry we stop trusting it. Guards
#: against handing a student a page that dies mid-payment.
EXPIRY_SAFETY_MARGIN = timedelta(minutes=2)


# ---------------------------------------------------------------------
# Raising a request
# ---------------------------------------------------------------------

def _customer_id_for(lead) -> str:
    """A stable per-lead customer id for SmartGateway.

    Alphanumeric for the same reason order ids are — the gateway is
    fussy about identifiers.
    """
    return f"LEAD{lead.id}"


def _student_of(payment_request: PaymentRequest):
    """The Student behind a FEE_INSTALLMENT request, or None."""
    installment = payment_request.installment
    if installment is None:
        return None
    return installment.enrollment.student


def _payer(payment_request: PaymentRequest) -> dict:
    """Who SmartGateway should bill, whatever the request's purpose.

    Both branches produce the same shape so `start_or_resume_order` never
    has to know which kind of request it is looking at. The customer_id
    is namespaced per party type (LEAD… / STU…) because leads and
    students are separate id spaces that would otherwise collide.
    """
    lead = payment_request.lead
    if lead is not None:
        return {
            "customer_id": _customer_id_for(lead),
            "email": lead.email or "",
            "phone": lead.phone or "",
            "name": lead.name or "",
            "udf1": str(lead.id),
        }

    student = _student_of(payment_request)
    if student is not None:
        return {
            "customer_id": f"STU{student.id}",
            "email": student.student_email or "",
            "phone": student.student_mobile or "",
            "name": student.student_name or "",
            "udf1": str(student.id),
        }

    # No party attached — still payable, just anonymous to the bank.
    return {
        "customer_id": f"REQ{payment_request.pk}",
        "email": "", "phone": "", "name": "", "udf1": "",
    }


def open_application_fee_request(lead) -> PaymentRequest | None:
    """The lead's still-payable application-fee request, if any."""
    return (
        PaymentRequest.objects
        .filter(
            lead=lead,
            purpose=PaymentRequest.Purpose.APPLICATION_FEE,
            status=PaymentRequest.Status.PENDING,
        )
        .order_by("-created_on")
        .first()
    )


def _public_api_base() -> str:
    """Origin of THIS API as the outside world reaches it.

    Deliberately has no fallback to FRONTEND_BASE_URL: that is the SPA
    host, which does not serve `/api/`, so falling back would mint a link
    that 404s for every lead it reached — silently, and only for real
    people. Better to refuse to build the URL at all.
    """
    base = (getattr(settings, "SMARTGATEWAY_PUBLIC_BASE_URL", "") or "").strip()
    if not base:
        raise SmartGatewayError(
            "SMARTGATEWAY_PUBLIC_BASE_URL is not set. It must be the "
            "public HTTPS origin of this API (the bank has to reach the "
            "return_url, and leads have to reach the pay link).",
        )
    return base.rstrip("/")


def pay_url_for(payment_request: PaymentRequest) -> str:
    """The public URL we put in the SMS/WhatsApp/email.

    Points at *us*, not the bank: the bank's page expires, this doesn't.
    """
    return f"{_public_api_base()}/api/public/pay/{payment_request.token}/"


def application_fee_request_for(
    lead, *, amount, description: str = "", actor=None, reuse: bool = True,
) -> PaymentRequest:
    """Get (or raise) a payable request for this lead's application fee.

    Reuses an existing unpaid request by default so resending the fee link
    doesn't invalidate the URL already sitting in the student's SMS. Pass
    `reuse=False` when the amount has changed.

    Raises `SmartGatewayError` when the gateway is off/misconfigured or
    the amount can't be resolved; callers decide whether that's fatal or
    a reason to fall back to manual instructions.

    Note this makes NO network call — the bank is only contacted when the
    student actually opens the link.
    """
    if not is_enabled():
        raise SmartGatewayError(
            "SmartGateway is not enabled. Set SMARTGATEWAY_ENABLED=True "
            "and the API key / merchant id / client id in the environment.",
        )
    if amount in (None, ""):
        raise SmartGatewayError(
            f"No application fee amount resolved for lead {lead.id}. Set "
            f"FeeTemplate.application_fee for the lead's campus/program, "
            f"or a default_amount in INSTITUTE_PAYMENT_DETAILS.",
        )

    amount = Decimal(str(amount))
    if reuse:
        existing = open_application_fee_request(lead)
        if existing and existing.amount == amount:
            return existing

    return PaymentRequest.objects.create(
        purpose=PaymentRequest.Purpose.APPLICATION_FEE,
        lead=lead,
        amount=amount,
        description=description or f"Application fee — {lead.name}",
        created_by=actor,
    )


def open_installment_request(installment) -> PaymentRequest | None:
    """The still-payable request against this installment, if any."""
    return (
        PaymentRequest.objects
        .filter(
            installment=installment,
            purpose=PaymentRequest.Purpose.FEE_INSTALLMENT,
            status=PaymentRequest.Status.PENDING,
        )
        .order_by("-created_on")
        .first()
    )


def installment_request_for(
    installment, *, amount, description: str = "", actor=None,
) -> PaymentRequest:
    """Get (or raise) a payable request for one fee installment.

    `amount` is the installment's *outstanding balance* at click time,
    not its face value — a student who part-paid at the counter should
    only be asked online for what is left.

    A pending request whose amount no longer matches is cancelled rather
    than left lying around: its token would otherwise still redirect to a
    live payment page for the stale figure.

    Raises `SmartGatewayError` when the gateway is off or the amount is
    not a positive number. Makes no network call.
    """
    if not is_enabled():
        raise SmartGatewayError(
            "Online payment is not available right now. Please contact the "
            "accounts office.",
        )

    amount = Decimal(str(amount))
    if amount <= Decimal("0"):
        raise SmartGatewayError("There is nothing left to pay on this installment.")

    existing = open_installment_request(installment)
    if existing is not None:
        if existing.amount == amount:
            return existing
        existing.status = PaymentRequest.Status.CANCELLED
        existing.save(update_fields=["status", "updated_on"])

    student = installment.enrollment.student
    return PaymentRequest.objects.create(
        purpose=PaymentRequest.Purpose.FEE_INSTALLMENT,
        installment=installment,
        amount=amount,
        description=description or (
            f"Installment #{installment.sequence} — {student.student_name}"
        ),
        created_by=actor,
    )


# ---------------------------------------------------------------------
# Minting an order (the student opened the link)
# ---------------------------------------------------------------------

#: Order-id prefix per purpose, so a glance at the bank's dashboard says
#: what was being paid. Two letters each, keeping the id well inside the
#: gateway's 20-character cap.
_ORDER_ID_PREFIX = {
    PaymentRequest.Purpose.APPLICATION_FEE: "AF",
    PaymentRequest.Purpose.FEE_INSTALLMENT: "FI",
}


def _build_order_id(payment_request: PaymentRequest, attempt: int) -> str:
    """`{XX}{request}N{attempt}` — alphanumeric, under 20 chars.

    Keyed on the request's own pk rather than the payer's so that two
    requests for one lead or student can't collide. Truncation is
    impossible in practice (a 10-digit pk with a 99-attempt suffix is 15
    chars) but the gateway validates it again before the call goes out.
    """
    prefix = _ORDER_ID_PREFIX.get(payment_request.purpose, "PR")
    order_id = f"{prefix}{payment_request.pk}N{attempt:02d}"
    return order_id[:ORDER_ID_MAX_LENGTH]


def _session_still_valid(order: PaymentOrder) -> bool:
    """Whether an existing order's hosted page can be reused."""
    if not order.payment_page_url or order.is_terminal:
        return False
    if order.session_expires_at is None:
        # No stated expiry — trust it, the gateway will reject it if not.
        return True
    return timezone.now() + EXPIRY_SAFETY_MARGIN < order.session_expires_at


def _parse_expiry(value) -> datetime | None:
    """Parse SmartGateway's ISO-8601 `...Z` expiry into an aware datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("payments: unparseable session expiry %r", value)
        return None


def return_url_for(payment_request: PaymentRequest) -> str:
    """Where SmartGateway sends the payer's browser after payment.

    SmartGateway requires this to be an HTTPS endpoint reachable from the
    bank's servers, which is why it shares `_public_api_base()` with the
    pay link rather than guessing.
    """
    return (
        f"{_public_api_base()}/api/public/pay/{payment_request.token}/return/"
    )


def start_or_resume_order(payment_request: PaymentRequest) -> PaymentOrder:
    """Give the payer a live hosted payment page.

    Reuses the latest order's page while its session is still good, and
    mints a fresh order otherwise — which is the whole reason the public
    link points at us instead of at the bank.

    Raises `SmartGatewayError` if the session can't be created.
    """
    latest = payment_request.orders.order_by("-created_on").first()
    if latest is not None and _session_still_valid(latest):
        return latest

    attempt = payment_request.attempt_count + 1
    order_id = _build_order_id(payment_request, attempt)
    payer = _payer(payment_request)

    order = PaymentOrder.objects.create(
        request=payment_request,
        order_id=order_id,
        amount=payment_request.amount,
    )
    # Bumped before the call, not after: a failed session still burns the
    # order_id as far as the bank is concerned, and reusing one is an error.
    payment_request.attempt_count = attempt
    payment_request.save(update_fields=["attempt_count", "updated_on"])

    first_name, _, last_name = payer["name"].strip().partition(" ")

    try:
        response = create_session(
            order_id=order_id,
            amount=payment_request.amount,
            customer_id=payer["customer_id"],
            return_url=return_url_for(payment_request),
            customer_email=payer["email"],
            customer_phone=payer["phone"],
            first_name=first_name,
            last_name=last_name,
            description=payment_request.description,
            currency=payment_request.currency,
            udf={"udf1": payer["udf1"], "udf2": payment_request.purpose},
        )
    except SmartGatewayError:
        order.status = PaymentOrder.Status.JUSPAY_DECLINED
        order.bank_error_message = "Session creation failed."
        order.save(update_fields=[
            "status", "bank_error_message", "updated_on",
        ])
        raise

    links = response.get("payment_links") or {}
    order.sg_order_ref = response.get("id") or ""
    order.payment_page_url = links.get("web") or ""
    order.session_expires_at = _parse_expiry(links.get("expiry"))
    order.status = response.get("status") or PaymentOrder.Status.NEW
    order.last_payload = response
    order.save(update_fields=[
        "sg_order_ref", "payment_page_url", "session_expires_at",
        "status", "last_payload", "updated_on",
    ])

    if not order.payment_page_url:
        raise SmartGatewayError(
            f"SmartGateway returned no payment_links.web for {order_id}.",
        )
    return order


# ---------------------------------------------------------------------
# Settling
# ---------------------------------------------------------------------

def _payment_mode(order: PaymentOrder) -> str:
    """SmartGateway's method type → the ERP's payment-mode vocabulary.

    Both `Lead.application_fee_mode` and `FeeReceipt.payment_mode` use
    CASH / CHEQUE / DD / ONLINE / UPI / NEFT / RTGS, so only UPI maps
    across; cards, netbanking and wallets all collapse to ONLINE. The
    finer detail survives on the order.
    """
    return "UPI" if (order.payment_method_type or "").upper() == "UPI" else "ONLINE"


def _mark_lead_fee_paid(payment_request: PaymentRequest, order: PaymentOrder) -> None:
    """Stamp the lead's application-fee fields from a settled order.

    This is the same state `LeadMarkFeePaidView` writes by hand, which is
    what unlocks `send_application_link`. Never overwrites an existing
    manual mark-paid — if accounts already reconciled it, a webhook
    arriving late must not clobber their reference.
    """
    lead = payment_request.lead
    if lead is None or lead.application_fee_paid_at is not None:
        return

    lead.application_fee_paid_at = order.charged_at or timezone.now()
    lead.application_fee_amount = order.amount
    lead.application_fee_mode = _payment_mode(order)
    lead.application_fee_ref = order.txn_id or order.order_id
    lead.application_fee_notes = (
        f"Paid online via HDFC SmartGateway (order {order.order_id}"
        + (f", {order.payment_method}" if order.payment_method else "")
        + ")."
    )
    # Left as None deliberately: no human recorded this one.
    lead.application_fee_recorded_by = None
    lead.save(update_fields=[
        "application_fee_paid_at", "application_fee_amount",
        "application_fee_mode", "application_fee_ref",
        "application_fee_notes", "application_fee_recorded_by",
    ])


def _record_installment_receipt(
    payment_request: PaymentRequest, order: PaymentOrder,
) -> None:
    """Write the FeeReceipt for a settled portal installment payment.

    This is the online twin of what accounts keys by hand in
    `FeeReceiptListCreateView`, and it deliberately produces the same
    shape of row — same numbering series, same `installment` link — so
    the balance maths, the collection reports and the receipt PDF all
    treat an online payment as an ordinary receipt.

    Idempotent on `instrument_ref == order.order_id`: order ids are
    unique, so a replayed webhook or a manual reconcile can't double-post.
    No GST is split out — the gateway charges the gross amount and the
    counter flow leaves those at zero for the same reason.
    """
    from apps.fees.models import FeeReceipt
    from apps.fees.services.receipt_no import generate_receipt_no

    installment = payment_request.installment
    if installment is None:
        return
    if FeeReceipt.objects.filter(instrument_ref=order.order_id).exists():
        return

    enrollment = installment.enrollment
    charged_at = order.charged_at or timezone.now()
    FeeReceipt.objects.create(
        receipt_no=generate_receipt_no(campus_code=enrollment.campus.code),
        enrollment=enrollment,
        installment=installment,
        basic_fee=order.amount,
        amount=order.amount,
        payment_mode=_payment_mode(order),
        # The bank's order id, not the txn id: it is what makes this
        # write idempotent, and it is what support will quote back.
        instrument_ref=order.order_id,
        bank="HDFC SmartGateway",
        received_date=timezone.localtime(charged_at).date(),
        notes=(
            f"Paid online by the student via HDFC SmartGateway "
            f"(order {order.order_id}"
            + (f", txn {order.txn_id}" if order.txn_id else "")
            + (f", {order.payment_method}" if order.payment_method else "")
            + ")."
        ),
        # Left as None deliberately: no human received this one.
        received_by=None,
    )


def _institute_key_for(lead) -> str:
    """The INSTITUTE_PAYMENT_DETAILS key for this lead's campus.

    Falls back to the single configured institute when there's exactly
    one, which is the common single-tenant case.
    """
    code = getattr(getattr(lead.campus, "institute", None), "code", "") or ""
    cfg = getattr(settings, "INSTITUTE_PAYMENT_DETAILS", {}) or {}
    if code in cfg:
        return code
    return next(iter(cfg)) if len(cfg) == 1 else ""


def _maybe_autosend_application_link(lead) -> None:
    """Send the application form link the moment the fee lands.

    Off by default — this messages a real person with no human in the
    loop, so it stays opt-in per environment via
    SMARTGATEWAY_AUTOSEND_APPLICATION_LINK. Failures are logged, never
    raised: the payment is already settled and must not be un-settled by
    a flaky SMS gateway.
    """
    if not getattr(settings, "SMARTGATEWAY_AUTOSEND_APPLICATION_LINK", False):
        return
    try:
        from apps.leads.send_links import send_application_link

        institute_key = _institute_key_for(lead)
        if not institute_key:
            logger.warning(
                "payments: cannot autosend application link for lead %s — "
                "no institute resolved.", lead.id,
            )
            return
        send_application_link(lead=lead, institute_key=institute_key)
    except Exception as e:
        logger.exception(
            "payments: autosend of application link failed for lead %s: %s",
            lead.id, e,
        )


def _charged_at_from(body: dict) -> datetime | None:
    """Prefer the gateway's own timestamp over our clock."""
    for key in ("date_created", "last_updated", "created"):
        raw = body.get(key)
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)
    return None


@transaction.atomic
def apply_order_body(order: PaymentOrder, body: dict) -> PaymentOrder:
    """Update a `PaymentOrder` from a SmartGateway order object.

    The one place order state is written, shared by the webhook, the
    return_url handler and the reconcile command so all three produce
    identical results. Idempotent: re-applying a CHARGED body is a no-op.
    """
    if order.is_paid:
        return order

    status = str(body.get("status") or "").upper()
    valid = set(PaymentOrder.Status.values)
    if status and status not in valid:
        logger.warning(
            "payments: unknown order status %r on %s — recorded as-is.",
            status, order.order_id,
        )
    if status:
        order.status = status[:24]

    order.txn_id = str(body.get("txn_id") or order.txn_id or "")[:80]
    order.txn_uuid = str(body.get("txn_uuid") or order.txn_uuid or "")[:64]
    order.payment_method = str(
        body.get("payment_method") or order.payment_method or "",
    )[:40]
    order.payment_method_type = str(
        body.get("payment_method_type") or order.payment_method_type or "",
    )[:24]
    order.sg_order_ref = str(body.get("id") or order.sg_order_ref or "")[:64]

    gateway_response = body.get("payment_gateway_response") or {}
    order.bank_error_code = str(
        body.get("bank_error_code")
        or gateway_response.get("resp_code")
        or order.bank_error_code
        or "",
    )[:64]
    order.bank_error_message = str(
        body.get("bank_error_message")
        or gateway_response.get("resp_message")
        or order.bank_error_message
        or "",
    )[:300]

    order.last_payload = body
    if order.is_paid and order.charged_at is None:
        order.charged_at = _charged_at_from(body) or timezone.now()
    order.save()

    if not order.is_paid:
        return order

    # Settle the parent request exactly once.
    payment_request = order.request
    if payment_request.status != PaymentRequest.Status.PAID:
        payment_request.status = PaymentRequest.Status.PAID
        payment_request.paid_order = order
        payment_request.paid_at = order.charged_at
        payment_request.save(update_fields=[
            "status", "paid_order", "paid_at", "updated_on",
        ])

    if payment_request.installment_id:
        _record_installment_receipt(payment_request, order)

    if payment_request.lead_id:
        _mark_lead_fee_paid(payment_request, order)
        # After commit so the lead is definitely marked paid before
        # send_application_link re-reads it — that helper refuses to send
        # while the fee still looks unpaid.
        lead = payment_request.lead
        transaction.on_commit(lambda: _maybe_autosend_application_link(lead))

    return order


def reconcile_order(order: PaymentOrder) -> PaymentOrder:
    """Pull an order's current state from SmartGateway and apply it.

    Also the trust step after a webhook: SmartGateway authenticates
    webhooks with shared credentials rather than signing the body, so the
    payload alone is not proof that money moved.
    """
    body = fetch_order(
        order.order_id,
        customer_id=_payer(order.request)["customer_id"],
    )
    return apply_order_body(order, body)


# ---------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------

def _order_from_payload(content: dict) -> PaymentOrder | None:
    order_body = content.get("order") or content.get("txn") or {}
    order_id = order_body.get("order_id") or order_body.get("orderId")
    if order_id:
        return PaymentOrder.objects.filter(order_id=order_id).first()
    sg_ref = order_body.get("id")
    if sg_ref:
        return PaymentOrder.objects.filter(sg_order_ref=sg_ref).first()
    return None


def process_webhook_event(
    *, event_id: str, body: dict, trust_payload: bool | None = None,
) -> SmartGatewayWebhookEvent:
    """Record and act on one authenticated webhook delivery.

    Idempotent on `event_id`: a redelivery returns the existing row
    untouched, so the caller can always answer 200 and stop the retries.

    By default the payload is treated as a *notification*, not as
    evidence — the order is re-fetched from `/orders/{id}` and that
    answer is what gets applied. SmartGateway does not sign webhook
    bodies, so anyone who learns the webhook credentials could otherwise
    mark fees paid. Set SMARTGATEWAY_TRUST_WEBHOOK_PAYLOAD=True to skip
    the re-fetch (and accept that).
    """
    event_name = str(body.get("event_name") or "")

    existing = SmartGatewayWebhookEvent.objects.filter(
        event_id=event_id,
    ).first()
    if existing is not None:
        return existing

    event = SmartGatewayWebhookEvent.objects.create(
        event_id=event_id, event_name=event_name, payload=body,
    )

    if event_name not in HANDLED_EVENTS:
        event.status = SmartGatewayWebhookEvent.Status.SKIPPED
        event.processed_at = timezone.now()
        event.save(update_fields=["status", "processed_at"])
        return event

    content = body.get("content") or {}
    order = _order_from_payload(content)
    if order is None:
        event.status = SmartGatewayWebhookEvent.Status.ERROR
        event.error_message = (
            f"No PaymentOrder matches the payload's order "
            f"{(content.get('order') or {}).get('order_id')!r}."
        )
        event.processed_at = timezone.now()
        event.save(update_fields=["status", "error_message", "processed_at"])
        return event

    event.order = order
    if trust_payload is None:
        trust_payload = bool(
            getattr(settings, "SMARTGATEWAY_TRUST_WEBHOOK_PAYLOAD", False),
        )

    try:
        if trust_payload:
            apply_order_body(order, content.get("order") or {})
        else:
            reconcile_order(order)
    except Exception as e:
        logger.exception("payments: webhook %s failed: %s", event_id, e)
        event.status = SmartGatewayWebhookEvent.Status.ERROR
        event.error_message = f"{type(e).__name__}: {e}"
    else:
        event.status = SmartGatewayWebhookEvent.Status.PROCESSED
    event.processed_at = timezone.now()
    event.save(update_fields=[
        "order", "status", "error_message", "processed_at",
    ])
    return event
