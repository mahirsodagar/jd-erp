"""Fees an applicant can pay straight after the application form.

Client rule (2026-11-03, widening the 2026-11-02 registration-fee step):
every applicant — JD Institute (JDIFT) and JD School of Design (JDSD)
alike — sees a "Pay fees" page the moment the self-fill application form
is submitted. It lists the whole fee structure from the fee template
(application, registration, course and other fee, plus the total) and
offers a pay button on each row the institute collects online at this
stage:

- **Registration fee** — payable for every institute: JDIFT through
  Razorpay (JDIFT Royalty account), JDSD through HDFC SmartGateway into
  JD Educational Trust (client rule 2026-11-06 — a JDSD program never
  touches Razorpay).
- **Course fee** and **other fee** — payable for JDSD only, through HDFC
  SmartGateway into JD Educational Trust, the same route as a JDSD
  installment or ad-hoc fee. JDIFT students pay those at the college, so
  their rows are shown but not payable (`status: OFFLINE`).
- **Application fee** — already settled at the lead stage; shown as paid
  with its receipt number, or with the counsellor's open pay link when
  it is still due.

Which rows get a button is decided by `apps.payments.routing`, not here:
a row is payable when the route table names a gateway for it and that
gateway is switched on for this environment. Amounts come from
`fee_template_for`, which picks the template the way the enrolment
screen does — the first active template for the student's campus,
program and academic year, else the newest for that campus and program —
so what the applicant is asked to pay matches what staff will schedule.

The student has no Enrollment yet, so each request hangs off the Student
(`PaymentRequest.student`) under its own purpose. When the gateway
confirms a charge a receipt number is reserved from the campus series and
the receipt PDF is mailed (`fees.services.registration_receipt`). The
accounts rows are written when the money can be matched to the schedule:

- registration fee → this year's REGISTRATION installment (seeded on the
  spot if missing), as before;
- course fee → the COURSE installments in sequence order until the
  payment is used up, one FeeReceipt per installment, the first under the
  reserved number. Installments are laid down after the enrolment is
  created, so this runs both at enrolment and again when the schedule is
  bulk-created;
- other fee → an OtherFee row created for it on the enrolment, with one
  receipt.

All of it is idempotent on `FeeReceipt.instrument_ref == order_id`, so a
replayed webhook or a repeated enrolment call can't double-post.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from . import routing
from .errors import PaymentGatewayError
from .models import PaymentOrder, PaymentRequest
from .services import (
    NoOnlineRoute, _gateway_label, _payment_mode, gateway_usable,
    open_application_fee_request, pay_url_for, payable_route,
)

logger = logging.getLogger("apps.payments")

ZERO = Decimal("0.00")

#: Row statuses on the fee page.
STATUS_PAID = "PAID"          # settled — receipt details ride along
STATUS_DUE = "DUE"            # payable online now — `pay_url` is set
STATUS_OFFLINE = "OFFLINE"    # shown for information; collected at the college


@dataclass(frozen=True)
class FeeKind:
    purpose: str      # PaymentRequest.Purpose value
    route_fee: str    # routing.FEE_* the route table keys on
    label: str


REGISTRATION = FeeKind(
    PaymentRequest.Purpose.REGISTRATION_FEE, routing.FEE_REGISTRATION,
    "Registration fee",
)
COURSE = FeeKind(
    PaymentRequest.Purpose.COURSE_FEE, routing.FEE_INSTALLMENT, "Course fee",
)
OTHER = FeeKind(
    PaymentRequest.Purpose.OTHER_FEE_APPLICANT, routing.FEE_OTHER, "Other fees",
)

#: Page order.
KINDS = (REGISTRATION, COURSE, OTHER)
BY_PURPOSE = {k.purpose: k for k in KINDS}
APPLICANT_PURPOSES = frozenset(BY_PURPOSE)

#: Name of the OtherFee row an "other fee" paid at application lands on.
OTHER_FEE_DESCRIPTION = "Other fees (paid at application)"


def _d(value) -> Decimal:
    return Decimal(value) if value is not None else ZERO


def _code(obj) -> str:
    return getattr(obj, "code", "") or ""


def institute_code(student) -> str:
    """The institute is recorded on the program, nowhere else."""
    program = getattr(student, "program", None)
    return _code(getattr(program, "institute", None)).upper()


# ---------------------------------------------------------------------
# Eligibility and amounts
# ---------------------------------------------------------------------

def offered_to(student) -> bool:
    """Whether this student's institute collects fees at application
    time. `REGISTRATION_FEE_AT_APPLICATION_INSTITUTES` restricts it to
    the listed institute codes; empty means every institute."""
    code = institute_code(student)
    if not code:
        return False
    allowed = getattr(settings, "REGISTRATION_FEE_AT_APPLICATION_INSTITUTES", None)
    if not allowed:
        return True
    return code in {str(c).upper() for c in allowed}


def fee_template_for(student):
    """The active FeeTemplate for the student's campus and program —
    the student's own academic year when one exists for it, else the
    newest — taking the first row when several match, exactly as the
    enrolment screen does. A template with a program year set counts
    like any other. None when nothing matches."""
    from apps.master.models import FeeTemplate

    if not (student.campus_id and student.program_id):
        return None
    base = FeeTemplate.objects.filter(
        campus_id=student.campus_id, program_id=student.program_id,
        is_active=True,
    ).select_related("academic_year")
    tmpl = None
    if student.academic_year_id:
        tmpl = base.filter(academic_year_id=student.academic_year_id).order_by("id").first()
    return tmpl or base.order_by("-academic_year__id", "id").first()


def fee_amounts(template) -> dict[FeeKind, Decimal]:
    """What each payable row asks for.

    The registration fee is carved OUT of the course fee (see
    `FeeTemplate.registration_fee`), so the course-fee row is the course
    fee less the registration fee — paying both must not collect the
    registration slice twice. A template that carries only a total has
    its course fee read as total − other fee.
    """
    if template is None:
        return {k: ZERO for k in KINDS}
    registration = max(ZERO, _d(template.registration_fee))
    other = max(ZERO, _d(template.other_fee))
    course = _d(template.course_fee)
    if course <= ZERO:
        course = _d(template.total_fee) - other
    return {
        REGISTRATION: registration,
        COURSE: max(ZERO, course - registration),
        OTHER: other,
    }


def route_for(student, kind: FeeKind) -> routing.Route | None:
    program = getattr(student, "program", None)
    return routing.resolve(
        fee=kind.route_fee,
        institute=_code(getattr(program, "institute", None)),
        campus=_code(getattr(student, "campus", None)),
    )


# ---------------------------------------------------------------------
# Raising requests
# ---------------------------------------------------------------------

def _requests(student, kind: FeeKind):
    return PaymentRequest.objects.filter(student=student, purpose=kind.purpose)


def paid_request(student, kind: FeeKind) -> PaymentRequest | None:
    return (
        _requests(student, kind)
        .filter(status=PaymentRequest.Status.PAID)
        .select_related("paid_order")
        .order_by("-paid_at")
        .first()
    )


def open_request(student, kind: FeeKind) -> PaymentRequest | None:
    return (
        _requests(student, kind)
        .filter(status=PaymentRequest.Status.PENDING)
        .order_by("-created_on")
        .first()
    )


def request_for(student, kind: FeeKind, *, amount: Decimal | None = None,
                actor=None) -> PaymentRequest | None:
    """The payable (or already paid) request for this fee, raising one
    when none exists.

    Returns None — quietly — whenever the row should not be payable:
    institute not offered the step, zero amount, no online route (JDIFT
    course and other fees), gateway off or broken. A broken gateway is
    logged, since someone should fix it.

    A pending request whose amount or route no longer matches is
    cancelled, not reused: its token would still open a live payment
    page for the stale figure. Makes no network call.
    """
    if not offered_to(student):
        return None

    paid = paid_request(student, kind)
    if paid is not None:
        return paid

    if amount is None:
        amount = fee_amounts(fee_template_for(student))[kind]
    if amount <= ZERO:
        return None

    try:
        route = payable_route(
            route_for(student, kind),
            f"the {kind.label.lower()} of student {student.pk}",
        )
    except NoOnlineRoute as e:
        logger.info("payments: %s Row shown without a pay button.", e)
        return None
    except PaymentGatewayError as e:
        logger.error("payments: %s Row shown without a pay button.", e)
        return None

    existing = open_request(student, kind)
    if existing is not None:
        if (
            existing.amount == amount
            and existing.gateway == route.gateway
            and existing.account == route.account
        ):
            return existing
        existing.status = PaymentRequest.Status.CANCELLED
        existing.save(update_fields=["status", "updated_on"])

    return PaymentRequest.objects.create(
        purpose=kind.purpose,
        student=student,
        gateway=route.gateway,
        account=route.account,
        amount=amount,
        description=f"{kind.label} — {student.student_name}",
        created_by=actor,
    )


# ---------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------

def _row(kind_key: str, label: str, amount, status: str, **extra) -> dict:
    row = {
        "kind": kind_key,
        "label": label,
        "amount": str(_d(amount)),
        "status": status,
        "request_id": None,
        "pay_url": "",
        "gateway": "",
        "paid_at": None,
        "receipt_no": "",
        "reference": "",
    }
    row.update(extra)
    return row


def _paid_row(kind: FeeKind, pr: PaymentRequest) -> dict:
    order = pr.paid_order
    return _row(
        kind.purpose, kind.label, pr.amount, STATUS_PAID,
        request_id=pr.id, gateway=pr.gateway,
        paid_at=pr.paid_at.isoformat() if pr.paid_at else None,
        receipt_no=pr.receipt_no,
        reference=(order.txn_id or order.order_id) if order else "",
    )


def _due_row(kind_key: str, label: str, pr: PaymentRequest) -> dict | None:
    """A payable row, or None when the gateway can't take the payment
    right now (switched off since the request was raised) — the client
    asked for no half-working "pay" button."""
    if not gateway_usable(pr.gateway, pr.account):
        return None
    try:
        url = pay_url_for(pr)
    except PaymentGatewayError as e:
        logger.error("payments: cannot build pay link for %s: %s", label, e)
        return None
    return _row(
        kind_key, label, pr.amount, STATUS_DUE,
        request_id=pr.id, pay_url=url, gateway=pr.gateway,
    )


def row_for(student, kind: FeeKind, amount: Decimal, *, create: bool) -> dict | None:
    """One fee row for the page, or None when there is nothing to show
    (zero amount and nothing paid). With `create=False` an existing
    request is reported but none is raised — the GET prefill must not
    write."""
    if create:
        pr = request_for(student, kind, amount=amount)
    else:
        pr = paid_request(student, kind) or open_request(student, kind)

    if pr is not None and pr.status == PaymentRequest.Status.PAID:
        return _paid_row(kind, pr)
    if pr is not None:
        due = _due_row(kind.purpose, kind.label, pr)
        if due is not None:
            return due
    if amount <= ZERO:
        return None
    return _row(kind.purpose, kind.label, amount, STATUS_OFFLINE)


def _application_fee_row(student, template) -> dict | None:
    """The lead-stage application fee: paid (with its receipt number),
    payable through the counsellor's open link, or shown for information."""
    lead = getattr(student, "lead_origin", None)
    amount = _d(getattr(template, "application_fee", None))
    label = "Application fee"
    key = PaymentRequest.Purpose.APPLICATION_FEE

    if lead is not None and lead.application_fee_paid_at:
        return _row(
            key, label, _d(lead.application_fee_amount) or amount, STATUS_PAID,
            paid_at=lead.application_fee_paid_at.isoformat(),
            receipt_no=lead.application_fee_receipt_no or "",
            reference=lead.application_fee_ref or "",
        )
    if amount <= ZERO:
        return None
    pr = open_application_fee_request(lead) if lead is not None else None
    if pr is not None:
        due = _due_row(key, label, pr)
        if due is not None:
            return due
    return _row(key, label, amount, STATUS_OFFLINE)


def fee_page_for(student, *, create: bool = False) -> dict | None:
    """What the public form (and staff screens) show after submit::

        {"institute": "JDSD", "template_name": "...", "academic_year": "2026-27",
         "total_fee": "100000.00", "notes": "",
         "rows": [{"kind": "APPLICATION_FEE" | "REGISTRATION_FEE" |
                             "COURSE_FEE" | "OTHER_FEE_APPLICANT",
                   "label": "...", "amount": "10000.00",
                   "status": "PAID" | "DUE" | "OFFLINE",
                   "request_id": int | None, "pay_url": "...", "gateway": "...",
                   "paid_at": iso | None, "receipt_no": "", "reference": ""}]}

    `None` means there is nothing to show at all — no template and
    nothing paid. With `create=True` the payable requests are raised (or
    refreshed) on the spot; the GET prefill passes False.
    """
    template = fee_template_for(student)
    amounts = fee_amounts(template)

    rows = []
    application = _application_fee_row(student, template)
    if application is not None:
        rows.append(application)
    for kind in KINDS:
        row = row_for(student, kind, amounts[kind], create=create)
        if row is not None:
            rows.append(row)
    if not rows:
        return None

    return {
        "institute": institute_code(student),
        "template_name": getattr(template, "name", "") or "",
        "academic_year": str(template.academic_year) if template else "",
        "total_fee": str(_d(getattr(template, "total_fee", None))),
        "notes": getattr(template, "notes", "") or "",
        "rows": rows,
    }


def registration_payment_from(page: dict | None) -> dict | None:
    """The registration row in the shape the older `registration_payment`
    field carries (DUE or PAID only — an OFFLINE row was never reported
    there), so existing screens keep working unchanged."""
    if not page:
        return None
    for row in page["rows"]:
        if row["kind"] == REGISTRATION.purpose and row["status"] != STATUS_OFFLINE:
            return {k: v for k, v in row.items() if k not in ("kind", "label")}
    return None


def due_rows(page: dict | None) -> list[dict]:
    return [r for r in (page or {}).get("rows", []) if r["status"] == STATUS_DUE]


# ---------------------------------------------------------------------
# Settling
# ---------------------------------------------------------------------

def _receipted(order: PaymentOrder) -> bool:
    from apps.fees.models import FeeReceipt
    return FeeReceipt.objects.filter(instrument_ref=order.order_id).exists()


def _current_enrollment(student):
    from apps.admissions.services import current_enrollment
    return current_enrollment(student)


def _reserve_receipt_no(payment_request: PaymentRequest, campus_code: str) -> str:
    from apps.fees.services.receipt_no import generate_receipt_no

    if not payment_request.receipt_no:
        payment_request.receipt_no = generate_receipt_no(campus_code=campus_code)
        payment_request.save(update_fields=["receipt_no", "updated_on"])
    return payment_request.receipt_no


def _receipt_notes(kind: FeeKind, payment_request: PaymentRequest,
                   order: PaymentOrder, suffix: str = "") -> str:
    label = _gateway_label(payment_request)
    return (
        f"{kind.label} paid online at application via {label} "
        f"(order {order.order_id}"
        + (f", txn {order.txn_id}" if order.txn_id else "")
        + (f", {order.payment_method}" if order.payment_method else "")
        + f"){suffix}."
    )


def _create_receipt(payment_request, order, enrollment, *, receipt_no,
                    amount, notes, installment=None, other_fee=None):
    from apps.fees.models import FeeReceipt

    charged_at = order.charged_at or timezone.now()
    return FeeReceipt.objects.create(
        receipt_no=receipt_no,
        enrollment=enrollment,
        installment=installment,
        other_fee=other_fee,
        basic_fee=amount,
        amount=amount,
        payment_mode=_payment_mode(order),
        instrument_ref=order.order_id,
        bank=_gateway_label(payment_request)[:120],
        received_date=timezone.localtime(charged_at).date(),
        notes=notes,
        received_by=None,
    )


def write_registration_receipt(payment_request: PaymentRequest, order: PaymentOrder,
                               enrollment, *, actor=None):
    """The accounts row for a settled registration payment, against this
    year's registration installment. Same shape as a counter receipt so
    balances, reports and the portal all see it as paid. Idempotent on
    `instrument_ref == order_id`."""
    from apps.fees.services.registration import ensure_registration_installment

    if _receipted(order):
        return None

    installment = ensure_registration_installment(enrollment, actor=actor)
    if installment is not None and installment.enrollment_id != enrollment.id:
        # Already charged under an earlier enrollment this year (mid-year
        # promotion). Receipt against that row — it is the one the money
        # pays for.
        enrollment = installment.enrollment

    receipt_no = _reserve_receipt_no(payment_request, enrollment.campus.code)
    return _create_receipt(
        payment_request, order, enrollment, receipt_no=receipt_no,
        amount=order.amount, installment=installment,
        notes=_receipt_notes(REGISTRATION, payment_request, order),
    )


def write_course_fee_receipts(payment_request: PaymentRequest, order: PaymentOrder,
                              enrollment, *, actor=None) -> list:
    """Apply a course fee paid at application to the COURSE installments
    in sequence order until it is used up — one receipt per installment,
    the first under the reserved number. Anything beyond the schedule
    lands on the last installment so no money goes unrecorded. Returns
    [] when the schedule has not been laid down yet; the caller runs
    again once it has."""
    from apps.fees.models import FeeReceipt, Installment
    from apps.fees.services.receipt_no import generate_receipt_no

    if _receipted(order):
        return []
    rows = list(
        Installment.objects
        .filter(enrollment=enrollment, kind=Installment.Kind.COURSE)
        .order_by("sequence", "id")
    )
    if not rows:
        return []

    campus_code = enrollment.campus.code
    first_no = _reserve_receipt_no(payment_request, campus_code)
    remaining = _d(order.amount)
    receipts = []
    for index, installment in enumerate(rows):
        if remaining <= ZERO:
            break
        already = _d(
            FeeReceipt.objects.filter(
                installment=installment, status=FeeReceipt.Status.ACTIVE,
            ).aggregate(s=Sum("amount"))["s"]
        )
        room = max(ZERO, _d(installment.amount) - already)
        last = index == len(rows) - 1
        part = remaining if last else min(room, remaining)
        if part <= ZERO:
            continue
        receipts.append(_create_receipt(
            payment_request, order, enrollment,
            receipt_no=first_no if not receipts else generate_receipt_no(campus_code=campus_code),
            amount=part, installment=installment,
            notes=_receipt_notes(
                COURSE, payment_request, order,
                suffix=f"; applied to installment #{installment.sequence}",
            ),
        ))
        remaining -= part
    return receipts


def write_other_fee_receipt(payment_request: PaymentRequest, order: PaymentOrder,
                            enrollment, *, actor=None):
    """An OtherFee row for the amount paid at application, receipted in
    full. Kept out of the course-fee balance like any other ad-hoc fee."""
    from apps.fees.models import OtherFee

    if _receipted(order):
        return None
    receipt_no = _reserve_receipt_no(payment_request, enrollment.campus.code)
    other_fee = OtherFee.objects.create(
        enrollment=enrollment, name=OTHER_FEE_DESCRIPTION,
        amount=order.amount, created_by=actor,
    )
    return _create_receipt(
        payment_request, order, enrollment, receipt_no=receipt_no,
        amount=order.amount, other_fee=other_fee,
        notes=_receipt_notes(OTHER, payment_request, order),
    )


def write_receipts(payment_request: PaymentRequest, order: PaymentOrder,
                   enrollment, *, actor=None) -> list:
    """The FeeReceipt rows for one settled applicant payment against
    this enrollment — [] when nothing could be written (yet)."""
    kind = BY_PURPOSE.get(payment_request.purpose)
    if kind is REGISTRATION:
        receipt = write_registration_receipt(payment_request, order, enrollment, actor=actor)
        return [receipt] if receipt is not None else []
    if kind is COURSE:
        return write_course_fee_receipts(payment_request, order, enrollment, actor=actor)
    if kind is OTHER:
        receipt = write_other_fee_receipt(payment_request, order, enrollment, actor=actor)
        return [receipt] if receipt is not None else []
    return []


def settle_paid_applicant_fee(payment_request: PaymentRequest, order: PaymentOrder) -> None:
    """Called from `apply_order_body` once the gateway says CHARGED.

    Reserves the receipt number, mails the receipt, and — when the
    student already has an enrollment — writes the FeeReceipt rows now.
    Mail goes after commit so a rollback can't leave the student holding
    a receipt for a payment the ERP never recorded.
    """
    student = payment_request.student
    if student is None or payment_request.purpose not in APPLICANT_PURPOSES:
        return

    _reserve_receipt_no(payment_request, student.campus.code)

    enrollment = _current_enrollment(student)
    if enrollment is not None:
        write_receipts(payment_request, order, enrollment)

    def _mail():
        from apps.fees.services.registration_receipt import (
            send_registration_payment_receipt,
        )
        send_registration_payment_receipt(payment_request, order)

    transaction.on_commit(_mail)


def settle_applicant_payments_on_enrollment(enrollment, *, actor=None) -> list:
    """Hook for enrolment and for schedule creation: every fee the
    student paid at application time becomes receipts on this enrollment.

    Returns the FeeReceipt rows written (possibly none). Never raises —
    a settlement problem must not block the enrolment itself.
    """
    written = []
    for kind in KINDS:
        try:
            pr = paid_request(enrollment.student, kind)
            if pr is None or pr.paid_order is None:
                continue
            written.extend(write_receipts(pr, pr.paid_order, enrollment, actor=actor))
        except Exception:  # noqa: BLE001 — enrolment must still go through
            logger.exception(
                "payments: could not settle the %s paid at application "
                "against enrollment %s.", kind.label.lower(), enrollment.pk,
            )
    return written
