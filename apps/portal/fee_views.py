"""Portal fee module — what the student owes, and paying it online.

Two ideas carry this file:

**The schedule is the source of truth.** Everything shown here is derived
from the `Installment` rows accounts laid down for the enrollment, and the
receipts written against them. The portal never invents a figure; if the
schedule has not been built yet the student is told exactly that rather
than shown a zero.

**Installments are paid in order.** Only the earliest row still carrying a
balance is payable, so a student cannot skip ahead and leave an older
installment behind — the same rule the counter follows. `_pay_state`
computes it once and both the list and the pay endpoint read it, so the
button the student sees and the check the server enforces can never
disagree.

Parents may view *and* pay: in practice they are the ones paying, and the
action is not destructive.
"""

from decimal import Decimal

from django.db.models import Sum
from rest_framework import status as http
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.fees.models import FeeReceipt, Installment, OtherFee
from apps.fees.services.balance import enrollment_balance
from apps.payments.gateway import SmartGatewayError, is_enabled
from apps.payments.services import installment_request_for, pay_url_for

from .permissions import IsStudentOrParent

ZERO = Decimal("0.00")


def _d(v) -> Decimal:
    return Decimal(v) if v is not None else ZERO


def _paid_by_installment(enrollment) -> dict[int, Decimal]:
    """`{installment_id: received}` in one query.

    Only ACTIVE receipts count — a cancelled one must put the money back
    on the balance, or the student would be told they had paid something
    accounts had since voided.
    """
    rows = (
        FeeReceipt.objects
        .filter(
            enrollment=enrollment,
            status=FeeReceipt.Status.ACTIVE,
            installment__isnull=False,
        )
        .values("installment_id")
        .annotate(total=Sum("amount"))
    )
    return {r["installment_id"]: _d(r["total"]) for r in rows}


def _pay_state(enrollment):
    """`(installments, paid_map, next_payable)` for one enrollment.

    `next_payable` is the lowest-sequence row with an outstanding
    balance — the only one the student is allowed to pay — or None when
    everything scheduled has been settled.
    """
    installments = list(
        Installment.objects.filter(enrollment=enrollment).order_by("sequence", "id")
    )
    paid_map = _paid_by_installment(enrollment)
    next_payable = next(
        (
            i for i in installments
            if _d(i.amount) - paid_map.get(i.id, ZERO) > ZERO
        ),
        None,
    )
    return installments, paid_map, next_payable


def _installment_row(inst, paid: Decimal, next_payable_id: int | None) -> dict:
    balance = _d(inst.amount) - paid
    if balance <= ZERO:
        state = "PAID"
    elif paid > ZERO:
        state = "PARTIAL"
    else:
        state = "DUE"
    return {
        "id": inst.id,
        "kind": inst.kind,
        "sequence": inst.sequence,
        "due_date": inst.due_date.isoformat(),
        "description": inst.description,
        "amount": str(_d(inst.amount)),
        "paid": str(paid),
        "balance": str(max(ZERO, balance)),
        "state": state,
        # The one row the student may pay right now. Everything later is
        # locked until this one clears.
        "is_payable": inst.id == next_payable_id,
    }


class FeeSummaryView(APIView):
    """`GET /api/portal/fees/` — the student's whole fee picture."""

    permission_classes = [IsStudentOrParent]

    def get(self, request):
        ctx = request.portal_ctx
        enrollment = ctx.enrollment
        if enrollment is None:
            return Response({
                "enrollment": None,
                "summary": None,
                "installments": [],
                "receipts": [],
                "other_fees": [],
                "next_installment_id": None,
                "online_payment_enabled": False,
                "message": "You are not enrolled yet, so no fee schedule "
                           "exists. Please contact the admissions office.",
            })

        installments, paid_map, next_payable = _pay_state(enrollment)
        next_id = next_payable.id if next_payable else None

        receipts = (
            FeeReceipt.objects
            .filter(enrollment=enrollment, status=FeeReceipt.Status.ACTIVE)
            .order_by("-received_date", "-id")
        )
        other_fees = OtherFee.objects.filter(enrollment=enrollment).order_by("id")
        other_paid = {
            r["other_fee_id"]: _d(r["total"])
            for r in (
                FeeReceipt.objects
                .filter(
                    enrollment=enrollment,
                    status=FeeReceipt.Status.ACTIVE,
                    other_fee__isnull=False,
                )
                .values("other_fee_id")
                .annotate(total=Sum("amount"))
            )
        }

        return Response({
            "enrollment": {
                "id": enrollment.id,
                "academic_year": enrollment.academic_year.code,
                "program_name": enrollment.program.name,
                "batch_name": getattr(enrollment.batch, "name", None),
                "status": enrollment.status,
            },
            "summary": enrollment_balance(enrollment),
            "installments": [
                _installment_row(i, paid_map.get(i.id, ZERO), next_id)
                for i in installments
            ],
            "next_installment_id": next_id,
            "receipts": [
                {
                    "id": r.id,
                    "receipt_no": r.receipt_no,
                    "amount": str(r.amount),
                    "payment_mode": r.payment_mode,
                    "instrument_ref": r.instrument_ref,
                    "received_date": r.received_date.isoformat(),
                    "installment_id": r.installment_id,
                    "other_fee_id": r.other_fee_id,
                }
                for r in receipts
            ],
            "other_fees": [
                {
                    "id": f.id,
                    "name": f.name,
                    "amount": str(_d(f.amount)),
                    "paid": str(other_paid.get(f.id, ZERO)),
                    "balance": str(
                        max(ZERO, _d(f.amount) - other_paid.get(f.id, ZERO)),
                    ),
                }
                for f in other_fees
            ],
            # Drives whether the UI offers "Pay now" at all — the gateway
            # can be switched off per environment.
            "online_payment_enabled": is_enabled(),
        })


class InstallmentPayView(APIView):
    """`POST /api/portal/fees/installments/<pk>/pay/`

    Raises (or reuses) a `PaymentRequest` for the installment's remaining
    balance and hands back the public pay URL. The browser is then sent
    to that URL, which mints a fresh SmartGateway session and 302s to the
    hosted payment page — the same path the application-fee SMS link
    takes, so settlement, webhooks and reconciliation all work unchanged.

    No money moves here, and nothing is marked paid: the receipt is
    written only when the gateway confirms the charge.
    """

    permission_classes = [IsStudentOrParent]

    def post(self, request, pk):
        ctx = request.portal_ctx
        enrollment = ctx.enrollment
        if enrollment is None:
            return Response(
                {"detail": "You are not enrolled yet, so there is no fee to pay."},
                status=http.HTTP_409_CONFLICT,
            )

        installments, paid_map, next_payable = _pay_state(enrollment)
        # Scoped to the student's own enrollment — an id from the request
        # body is never trusted to point anywhere else.
        target = next((i for i in installments if i.id == pk), None)
        if target is None:
            return Response(
                {"detail": "Installment not found."},
                status=http.HTTP_404_NOT_FOUND,
            )

        balance = _d(target.amount) - paid_map.get(target.id, ZERO)
        if balance <= ZERO:
            return Response(
                {"detail": "This installment is already fully paid."},
                status=http.HTTP_409_CONFLICT,
            )
        if next_payable is not None and target.id != next_payable.id:
            return Response(
                {"detail": (
                    f"Installments must be paid in order. Please clear "
                    f"installment #{next_payable.sequence} "
                    f"(due {next_payable.due_date.isoformat()}) first."
                )},
                status=http.HTTP_409_CONFLICT,
            )

        label = (
            "Registration fee"
            if target.kind == Installment.Kind.REGISTRATION
            else f"Installment #{target.sequence}"
        )
        try:
            payment_request = installment_request_for(
                target,
                amount=balance,
                description=f"{label} — {ctx.student.student_name}",
                actor=request.user,
            )
            url = pay_url_for(payment_request)
        except SmartGatewayError as e:
            return Response(
                {"detail": str(e)}, status=http.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({
            "pay_url": url,
            "amount": str(balance),
            "installment_id": target.id,
            "payment_request_id": payment_request.id,
        })
