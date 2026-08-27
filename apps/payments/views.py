"""SmartGateway public endpoints + a small read API for the ERP UI.

Three of these are unauthenticated by JWT, for three different reasons:

* `PayRedirectView`    — the student clicking a link in an SMS. Bearer
                         auth is the token in the URL.
* `PayReturnView`      — SmartGateway bouncing the payer's browser back.
* `SmartGatewayWebhookView` — server-to-server, authenticated by the
                         Basic credentials configured in the dashboard.

All three declare `authentication_classes = []` so DRF's SessionAuth
doesn't enforce CSRF on requests that can't carry a CSRF token.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.shortcuts import redirect
from rest_framework import status as http
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .gateway import (
    SmartGatewayError,
    check_webhook_auth,
    is_enabled,
    is_sandbox,
    verify_return_signature,
)
from .models import PaymentOrder, PaymentRequest
from .permissions import CanReconcilePayments, CanViewPaymentRequests
from .serializers import PaymentRequestSerializer
from .services import (
    process_webhook_event,
    reconcile_order,
    start_or_resume_order,
)

logger = logging.getLogger("apps.payments")


def _form_params(request) -> dict:
    """Form-encoded body params, when the return_url is set to POST.

    SmartGateway sends the return_url as GET by default, but the
    dashboard has a flag to switch it to POST — handle both so flipping
    that setting doesn't silently break signature validation.
    """
    if request.method != "POST":
        return {}
    try:
        return request.POST.dict()
    except Exception:
        return {}


def _result_redirect(outcome: str, token=None):
    """Bounce the payer to the SPA's result page.

    The SPA owns the "thanks / that failed" screen; this endpoint only
    decides which outcome to name.
    """
    base = getattr(settings, "FRONTEND_BASE_URL", "").rstrip("/")
    suffix = f"&ref={token}" if token else ""
    return redirect(f"{base}/#/payment/result?status={outcome}{suffix}")


class PayRedirectView(APIView):
    """`GET /api/public/pay/<token>/` — what the student's SMS points at.

    Mints a SmartGateway session on the spot and 302s to the hosted
    payment page. Deliberately indirect: the bank's page expires, this
    URL doesn't, so the same SMS still works days later.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        payment_request = (
            PaymentRequest.objects
            .select_related("lead", "lead__campus")
            .filter(token=token)
            .first()
        )
        if payment_request is None:
            return _result_redirect("notfound")

        if payment_request.status == PaymentRequest.Status.PAID:
            return _result_redirect("alreadypaid", token)
        if payment_request.status == PaymentRequest.Status.CANCELLED:
            return _result_redirect("cancelled", token)

        if not is_enabled():
            logger.error(
                "payments: pay link opened for request %s but SmartGateway "
                "is disabled.", payment_request.pk,
            )
            return _result_redirect("unavailable", token)

        try:
            order = start_or_resume_order(payment_request)
        except SmartGatewayError as e:
            logger.warning(
                "payments: could not start order for request %s: %s",
                payment_request.pk, e,
            )
            return _result_redirect("unavailable", token)

        return redirect(order.payment_page_url)


class PayReturnView(APIView):
    """`GET/POST /api/public/pay/<token>/return/` — SmartGateway's return_url.

    A browser redirect is not evidence of payment (the payer can close
    the tab, or forge the hop), so this never trusts its own parameters:
    it re-reads the order from `/orders/{id}` and reports whatever that
    says. The webhook remains the primary settlement path; this just
    means the student sees the right screen immediately.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        return self._handle(request, token)

    def post(self, request, token):
        return self._handle(request, token)

    def _handle(self, request, token):
        payment_request = PaymentRequest.objects.filter(token=token).first()
        if payment_request is None:
            return _result_redirect("notfound")

        order = payment_request.orders.order_by("-created_on").first()
        if order is None:
            return _result_redirect("unknown", token)

        # SmartGateway signs these params with the RESPONSE_KEY, so unlike
        # a bare redirect they can actually be trusted. We still prefer a
        # fresh read of the order below — a signed "CHARGED" can still be
        # followed by a failed capture — but a valid signature gives us
        # something to fall back on if that read fails.
        params = {
            k: v for k, v in
            {**request.GET.dict(), **_form_params(request)}.items()
        }
        signed_ok = verify_return_signature(params) if params else False
        if params.get("signature") and not signed_ok:
            # Someone hand-edited the redirect, or RESPONSE_KEY is wrong.
            # Not fatal — we re-read the order anyway — but it should
            # never happen in a healthy integration.
            logger.warning(
                "payments: return_url signature did NOT validate for %s "
                "(order %s). Check SMARTGATEWAY_RESPONSE_KEY.",
                token, order.order_id,
            )

        try:
            order = reconcile_order(order)
        except SmartGatewayError as e:
            logger.warning(
                "payments: return_url reconcile failed for %s: %s",
                order.order_id, e,
            )
            # Fall back to the signed status when we have one — it is
            # authenticated, just possibly not the final word.
            if signed_ok:
                signed_status = str(params.get("status") or "").upper()
                if signed_status in PaymentOrder.PAID_STATUSES:
                    return _result_redirect("success", token)
                if signed_status in PaymentOrder.TERMINAL_STATUSES:
                    return _result_redirect("failed", token)
            # The payment may well have succeeded — the webhook or the
            # reconcile cron will settle it. Don't tell the student it
            # failed.
            return _result_redirect("pending", token)

        if order.is_paid:
            return _result_redirect("success", token)
        if order.is_terminal:
            return _result_redirect("failed", token)
        return _result_redirect("pending", token)


class SmartGatewayWebhookView(APIView):
    """POST target for SmartGateway's webhook.

    Answers 200 for anything it has durably recorded — including events
    it chose to skip and events that failed to apply — because a non-2xx
    makes SmartGateway retry, and retrying won't fix a payload we've
    already stored. Only bad credentials or an unparseable body get a 4xx.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not check_webhook_auth(request.headers.get("Authorization", "")):
            logger.warning(
                "payments: rejected SmartGateway webhook with bad/missing "
                "Basic credentials.",
            )
            return Response(
                {"detail": "Invalid credentials."},
                status=http.HTTP_401_UNAUTHORIZED,
            )

        try:
            body = json.loads(request.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            return Response(
                {"detail": f"Malformed JSON: {e}"},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(body, dict):
            return Response(
                {"detail": "Expected a JSON object."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        # SmartGateway stamps `id` on every event; fall back to a
        # composite so a payload missing it still can't be applied twice.
        content_order = (body.get("content") or {}).get("order") or {}
        event_id = str(
            body.get("id")
            or f"{body.get('event_name')}:{content_order.get('order_id')}:"
               f"{body.get('date_created')}",
        )

        event = process_webhook_event(event_id=event_id, body=body)
        return Response(
            {"status": event.status, "event_id": event.event_id},
            status=http.HTTP_200_OK,
        )


class PaymentRequestListView(APIView):
    """Payment requests for one lead — `?lead=<id>`.

    Read-only: requests are raised as a side effect of sending a fee
    link, never directly from the UI.
    """

    permission_classes = [IsAuthenticated, CanViewPaymentRequests]

    def get(self, request):
        qs = PaymentRequest.objects.select_related("lead").prefetch_related(
            "orders",
        )
        lead_id = request.query_params.get("lead")
        if lead_id:
            qs = qs.filter(lead_id=lead_id)
        purpose = request.query_params.get("purpose")
        if purpose:
            qs = qs.filter(purpose=purpose)
        return Response(PaymentRequestSerializer(qs[:100], many=True).data)


class PaymentRequestReconcileView(APIView):
    """Re-read this request's latest order from SmartGateway.

    The manual escape hatch for a webhook that never arrived — a
    counsellor can force the check instead of waiting on support.
    """

    permission_classes = [IsAuthenticated, CanReconcilePayments]

    def post(self, request, pk):
        payment_request = PaymentRequest.objects.filter(pk=pk).first()
        if payment_request is None:
            return Response(
                {"detail": "Payment request not found."},
                status=http.HTTP_404_NOT_FOUND,
            )

        order = payment_request.orders.order_by("-created_on").first()
        if order is None:
            return Response(
                {"detail": "The student has not opened the payment link yet, "
                           "so there is nothing to check."},
                status=http.HTTP_409_CONFLICT,
            )
        try:
            reconcile_order(order)
        except SmartGatewayError as e:
            return Response(
                {"detail": str(e)}, status=http.HTTP_502_BAD_GATEWAY,
            )
        payment_request.refresh_from_db()
        return Response(PaymentRequestSerializer(payment_request).data)


class SmartGatewayStatusView(APIView):
    """Whether the gateway is configured, and in which mode.

    Lets the UI show "SmartGateway: sandbox" next to the fee-link button
    so nobody mistakes a test payment for a real one.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        enabled = is_enabled()
        return Response({
            "enabled": enabled,
            "mode": ("sandbox" if is_sandbox() else "production") if enabled else None,
            "webhook_configured": bool(
                getattr(settings, "SMARTGATEWAY_WEBHOOK_USERNAME", "")
                and getattr(settings, "SMARTGATEWAY_WEBHOOK_PASSWORD", ""),
            ),
            "autosend_application_link": bool(
                getattr(settings, "SMARTGATEWAY_AUTOSEND_APPLICATION_LINK", False),
            ),
        })
