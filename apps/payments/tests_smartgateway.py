"""HDFC SmartGateway application-fee flow.

Covers the parts that are silently wrong rather than loudly broken: the
webhook's Basic credentials, a redelivered event not double-settling, a
webhook payload not being trusted on its own word, order_id staying
inside the gateway's 20-char alphanumeric limit, session expiry forcing a
fresh order, and a webhook arriving after accounts already reconciled by
hand.

No network: `create_session` / `fetch_order` are patched.
"""

import base64
import json
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.leads.models import Lead
from apps.master.models import Campus, Institute, LeadSource, Program
from apps.payments import services
from apps.payments.gateway import (
    ORDER_ID_MAX_LENGTH,
    SmartGatewayError,
    check_webhook_auth,
    format_amount,
    is_enabled,
    missing_settings,
    normalise_phone,
    signature_payload,
    validate_order_id,
    verify_return_signature,
)
from apps.payments.models import (
    PaymentOrder, PaymentRequest, SmartGatewayWebhookEvent,
)

WEBHOOK_USER = "jderp"
WEBHOOK_PASS = "sg-webhook-pass"
RESPONSE_KEY = "BB91D6440A14724BB1AFC1C44A830C"


def _sign(params: dict, key: str = RESPONSE_KEY) -> str:
    """Sign params the way SmartGateway does, for round-trip tests.

    Written straight from the reference PHP rather than by calling our
    own `signature_payload`, so a mistake in that helper can't cancel
    itself out here.
    """
    import hashlib
    import hmac as _hmac
    from urllib.parse import quote_plus

    def enc(v):
        return quote_plus(str(v), safe="").replace("~", "%7E")

    joined = "&".join(f"{enc(k)}={enc(params[k])}" for k in sorted(params))
    digest = _hmac.new(
        key.encode(), enc(joined).encode(), hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode()


SG_ON = dict(
    SMARTGATEWAY_ENABLED=True,
    SMARTGATEWAY_SANDBOX=True,
    SMARTGATEWAY_API_KEY="sg_test_key",
    SMARTGATEWAY_MERCHANT_ID="testhdfc1",
    SMARTGATEWAY_CLIENT_ID="hdfcmaster",
    SMARTGATEWAY_WEBHOOK_USERNAME=WEBHOOK_USER,
    SMARTGATEWAY_WEBHOOK_PASSWORD=WEBHOOK_PASS,
    SMARTGATEWAY_RESPONSE_KEY=RESPONSE_KEY,
    SMARTGATEWAY_PUBLIC_BASE_URL="https://api.jd.test",
    SMARTGATEWAY_AUTOSEND_APPLICATION_LINK=False,
    SMARTGATEWAY_TRUST_WEBHOOK_PAYLOAD=False,
)


def _session_response(order_id="AF1N01", expiry=None, **overrides):
    """A /session response, shaped like the documented one."""
    body = {
        "status": "NEW",
        "id": "ordeh_3b0bf151fb4944221ab0f",
        "order_id": order_id,
        "payment_links": {
            "web": f"https://smartgateway.hdfcuat.bank.in/orders/{order_id}/payment-page",
            "expiry": expiry or "2099-01-01T00:00:00Z",
        },
    }
    body.update(overrides)
    return body


def _order_body(order_id="AF1N01", status="CHARGED", **overrides):
    """An /orders/{id} response body."""
    body = {
        "order_id": order_id,
        "id": "ordeh_3b0bf151fb4944221ab0f",
        "status": status,
        "amount": 1000,
        "currency": "INR",
        "txn_id": "jd-AF1N01-1",
        "txn_uuid": "moziqFZtYKQkTsRFGXX",
        "payment_method": "VISA",
        "payment_method_type": "CARD",
    }
    body.update(overrides)
    return body


class ValueHelperTests(TestCase):

    def test_amount_is_formatted_to_two_decimals(self):
        self.assertEqual(format_amount(Decimal("1000")), "1000.00")
        self.assertEqual(format_amount("1500.5"), "1500.50")

    def test_sub_paise_amount_is_rejected_not_rounded(self):
        # Silently rounding would under- or over-charge a student.
        with self.assertRaises(SmartGatewayError):
            format_amount(Decimal("100.005"))

    def test_non_positive_amount_is_rejected(self):
        with self.assertRaises(SmartGatewayError):
            format_amount(Decimal("0.00"))

    def test_order_id_must_be_short_and_alphanumeric(self):
        validate_order_id("AF12N01")
        # SmartGateway rejects special characters — the old Razorpay-style
        # reference would have failed at the bank, not here.
        with self.assertRaises(SmartGatewayError):
            validate_order_id("APPFEE-L12-01")
        with self.assertRaises(SmartGatewayError):
            validate_order_id("A" * (ORDER_ID_MAX_LENGTH + 1))

    def test_phone_is_reduced_to_ten_digits(self):
        self.assertEqual(normalise_phone("+91 98765 43210"), "9876543210")
        self.assertEqual(normalise_phone("09876543210"), "9876543210")
        # Too short to be a real number — better absent than malformed.
        self.assertEqual(normalise_phone("12345"), "")


@override_settings(**SG_ON)
class WebhookAuthTests(TestCase):

    def _header(self, user, password):
        raw = base64.b64encode(f"{user}:{password}".encode()).decode()
        return f"Basic {raw}"

    def test_correct_credentials_pass(self):
        self.assertTrue(
            check_webhook_auth(self._header(WEBHOOK_USER, WEBHOOK_PASS)),
        )

    def test_wrong_password_fails(self):
        self.assertFalse(
            check_webhook_auth(self._header(WEBHOOK_USER, "nope")),
        )

    def test_wrong_username_fails(self):
        self.assertFalse(
            check_webhook_auth(self._header("someone", WEBHOOK_PASS)),
        )

    def test_malformed_headers_fail(self):
        for header in ["", "Basic", "Bearer abc", "Basic !!!not-base64!!!"]:
            self.assertFalse(check_webhook_auth(header), header)

    @override_settings(SMARTGATEWAY_WEBHOOK_PASSWORD="")
    def test_unconfigured_credentials_reject_everything(self):
        # Fail closed: with no password set we cannot authenticate anyone.
        self.assertFalse(
            check_webhook_auth(self._header(WEBHOOK_USER, "")),
        )


@override_settings(**SG_ON)
class ReturnSignatureTests(TestCase):
    """The RESPONSE_KEY HMAC on the return_url params."""

    def _params(self, **overrides):
        params = {
            "order_id": "AF1N01",
            "status": "CHARGED",
            "status_id": "21",
        }
        params.update(overrides)
        return params

    def test_double_encoding_is_applied(self):
        """Each pair is encoded, then the joined string is encoded AGAIN.
        Skipping the second pass is the classic way this silently fails."""
        payload = signature_payload({"a": "1", "b": "x y"})
        # 'a=1&b=x+y' encoded once more → separators become %3D / %26.
        self.assertEqual(payload, "a%3D1%26b%3Dx%2By")

    def test_params_are_sorted_by_key(self):
        # Same content, different insertion order → same payload.
        self.assertEqual(
            signature_payload({"b": "2", "a": "1"}),
            signature_payload({"a": "1", "b": "2"}),
        )

    def test_valid_signature_passes(self):
        params = self._params()
        params["signature"] = _sign(params)
        params["signature_algorithm"] = "HMAC-SHA256"
        self.assertTrue(verify_return_signature(params))

    def test_tampered_status_fails(self):
        """The whole point — a payer can't flip AUTHORIZATION_FAILED to
        CHARGED in their address bar."""
        params = self._params(status="AUTHORIZATION_FAILED")
        params["signature"] = _sign(params)
        params["signature_algorithm"] = "HMAC-SHA256"
        params["status"] = "CHARGED"
        self.assertFalse(verify_return_signature(params))

    def test_wrong_response_key_fails(self):
        params = self._params()
        params["signature"] = _sign(params, key="not-the-right-key")
        params["signature_algorithm"] = "HMAC-SHA256"
        self.assertFalse(verify_return_signature(params))

    def test_extra_param_is_included_in_the_signed_set(self):
        # Anything the gateway adds must be signed over too, or a valid
        # signature would cover only part of the redirect.
        params = self._params(udf1="42")
        params["signature"] = _sign(params)
        params["signature_algorithm"] = "HMAC-SHA256"
        self.assertTrue(verify_return_signature(params))

        params["udf1"] = "43"
        self.assertFalse(verify_return_signature(params))

    def test_missing_or_unknown_algorithm_fails(self):
        params = self._params()
        params["signature"] = _sign(params)
        # An algorithm we don't implement must not silently pass.
        params["signature_algorithm"] = "HMAC-SHA512"
        self.assertFalse(verify_return_signature(params))

    def test_absent_signature_fails(self):
        self.assertFalse(verify_return_signature(self._params()))

    @override_settings(SMARTGATEWAY_RESPONSE_KEY="")
    def test_unconfigured_response_key_rejects_everything(self):
        params = self._params()
        params["signature"] = _sign(params)
        params["signature_algorithm"] = "HMAC-SHA256"
        # Fail closed, same as the webhook credentials.
        self.assertFalse(verify_return_signature(params))


class _LeadFixture(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JD Fashion", code="JDIFT")
        cls.campus = Campus.objects.create(
            name="Bengaluru", code="BLR",
        )
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.source = LeadSource.objects.create(name="Website", slug="website")
        cls.lead = Lead.objects.create(
            name="Asha Rao", phone="9999999999", email="asha@example.com",
            campus=cls.campus, program=cls.program, source=cls.source,
        )


@override_settings(**SG_ON)
class RequestCreationTests(_LeadFixture):

    def test_raising_a_request_makes_no_network_call(self):
        """The bank is only contacted when the student opens the link —
        that's what keeps the SMS URL valid indefinitely."""
        with patch.object(services, "create_session") as mocked:
            req = services.application_fee_request_for(
                lead=self.lead, amount=Decimal("1000.00"),
            )

        mocked.assert_not_called()
        self.assertEqual(req.status, PaymentRequest.Status.PENDING)
        self.assertEqual(req.orders.count(), 0)

    def test_pay_url_points_at_us_not_the_bank(self):
        req = services.application_fee_request_for(
            lead=self.lead, amount=Decimal("1000.00"),
        )
        url = services.pay_url_for(req)
        self.assertEqual(
            url, f"https://api.jd.test/api/public/pay/{req.token}/",
        )

    def test_resend_reuses_the_open_request(self):
        """A second send must not invalidate the URL already sitting in
        the student's SMS."""
        first = services.application_fee_request_for(
            lead=self.lead, amount=Decimal("1000.00"),
        )
        second = services.application_fee_request_for(
            lead=self.lead, amount=Decimal("1000.00"),
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.token, second.token)

    def test_changed_amount_raises_a_fresh_request(self):
        first = services.application_fee_request_for(
            lead=self.lead, amount=Decimal("1000.00"),
        )
        second = services.application_fee_request_for(
            lead=self.lead, amount=Decimal("1500.00"), reuse=False,
        )
        self.assertNotEqual(first.pk, second.pk)
        self.assertNotEqual(first.token, second.token)

    def test_missing_amount_is_refused(self):
        with self.assertRaises(SmartGatewayError):
            services.application_fee_request_for(lead=self.lead, amount=None)

    @override_settings(SMARTGATEWAY_ENABLED=False)
    def test_disabled_gateway_refuses_to_raise(self):
        with self.assertRaises(SmartGatewayError):
            services.application_fee_request_for(
                lead=self.lead, amount=Decimal("1000.00"),
            )

    @override_settings(SMARTGATEWAY_PUBLIC_BASE_URL="")
    def test_missing_public_base_url_disables_the_gateway(self):
        """Without it the pay link would be built off the SPA host and
        404 for every lead it reached. Fall back instead."""
        self.assertIn("SMARTGATEWAY_PUBLIC_BASE_URL", missing_settings())
        self.assertFalse(is_enabled())

    @override_settings(SMARTGATEWAY_PUBLIC_BASE_URL="")
    def test_pay_url_refuses_to_guess_a_host(self):
        req = PaymentRequest.objects.create(
            purpose=PaymentRequest.Purpose.APPLICATION_FEE,
            lead=self.lead, amount=Decimal("1000.00"),
        )
        # Must raise, NOT silently fall back to FRONTEND_BASE_URL.
        with self.assertRaises(SmartGatewayError):
            services.pay_url_for(req)
        with self.assertRaises(SmartGatewayError):
            services.return_url_for(req)

    @override_settings(SMARTGATEWAY_API_KEY="")
    def test_partial_config_reports_what_is_missing(self):
        self.assertEqual(missing_settings(), ["SMARTGATEWAY_API_KEY"])
        self.assertFalse(is_enabled())

    def test_full_config_reports_nothing_missing(self):
        self.assertEqual(missing_settings(), [])
        self.assertTrue(is_enabled())


@override_settings(**SG_ON)
class OrderMintingTests(_LeadFixture):

    def setUp(self):
        self.req = services.application_fee_request_for(
            lead=self.lead, amount=Decimal("1000.00"),
        )

    def test_opening_the_link_mints_an_order_and_redirects(self):
        with patch.object(
            services, "create_session", return_value=_session_response(),
        ) as mocked:
            resp = self.client.get(
                reverse("public-pay", args=[self.req.token]),
            )

        self.assertEqual(resp.status_code, 302)
        self.assertIn("payment-page", resp["Location"])
        order = self.req.orders.get()
        self.assertEqual(order.sg_order_ref, "ordeh_3b0bf151fb4944221ab0f")

        # order_id must satisfy the gateway's own rules.
        validate_order_id(order.order_id)
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["order_id"], order.order_id)
        self.assertEqual(
            kwargs["return_url"],
            f"https://api.jd.test/api/public/pay/{self.req.token}/return/",
        )

    def test_reopening_reuses_a_live_session(self):
        with patch.object(
            services, "create_session", return_value=_session_response(),
        ) as mocked:
            self.client.get(reverse("public-pay", args=[self.req.token]))
            self.client.get(reverse("public-pay", args=[self.req.token]))

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(self.req.orders.count(), 1)

    def test_expired_session_mints_a_fresh_order(self):
        """The whole reason the public link is indirect: the bank's page
        dies, the SMS URL must not."""
        past = "2020-01-01T00:00:00Z"
        with patch.object(
            services, "create_session",
            side_effect=[
                _session_response(order_id="AF1N01", expiry=past),
                _session_response(order_id="AF1N02"),
            ],
        ) as mocked:
            self.client.get(reverse("public-pay", args=[self.req.token]))
            self.client.get(reverse("public-pay", args=[self.req.token]))

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(self.req.orders.count(), 2)
        # Distinct order ids — the bank rejects a reused one.
        ids = set(self.req.orders.values_list("order_id", flat=True))
        self.assertEqual(len(ids), 2)

    def test_attempt_counter_climbs_even_when_the_session_fails(self):
        with patch.object(
            services, "create_session",
            side_effect=SmartGatewayError("gateway down"),
        ):
            resp = self.client.get(
                reverse("public-pay", args=[self.req.token]),
            )

        self.assertEqual(resp.status_code, 302)
        self.assertIn("status=unavailable", resp["Location"])
        self.req.refresh_from_db()
        self.assertEqual(self.req.attempt_count, 1)

    def test_already_paid_request_does_not_mint_another_order(self):
        self.req.status = PaymentRequest.Status.PAID
        self.req.save()

        with patch.object(services, "create_session") as mocked:
            resp = self.client.get(
                reverse("public-pay", args=[self.req.token]),
            )

        mocked.assert_not_called()
        self.assertIn("status=alreadypaid", resp["Location"])

    def test_unknown_token_is_not_an_error_page(self):
        resp = self.client.get(
            reverse("public-pay",
                    args=["00000000-0000-0000-0000-000000000000"]),
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("status=notfound", resp["Location"])


@override_settings(**SG_ON)
class WebhookProcessingTests(_LeadFixture):

    def setUp(self):
        self.req = services.application_fee_request_for(
            lead=self.lead, amount=Decimal("1000.00"),
        )
        self.order = PaymentOrder.objects.create(
            request=self.req, order_id="AF1N01", amount=Decimal("1000.00"),
            sg_order_ref="ordeh_3b0bf151fb4944221ab0f",
            status=PaymentOrder.Status.PENDING_VBV,
        )

    def _body(self, event_name="ORDER_SUCCEEDED", status="CHARGED", **kw):
        return {
            "id": kw.pop("event_id", "evt_V2_b737837102414514ae0e9717a9f2"),
            "event_name": event_name,
            "date_created": "2026-08-27T07:00:48Z",
            "content": {"order": _order_body(
                order_id=self.order.order_id, status=status, **kw,
            )},
        }

    def _post(self, body, *, user=WEBHOOK_USER, password=WEBHOOK_PASS):
        raw = base64.b64encode(f"{user}:{password}".encode()).decode()
        return self.client.post(
            reverse("smartgateway-webhook"),
            data=json.dumps(body),
            content_type="application/json",
            headers={"authorization": f"Basic {raw}"},
        )

    def test_success_webhook_settles_and_marks_lead(self):
        with patch.object(
            services, "fetch_order", return_value=_order_body(),
        ):
            resp = self._post(self._body())

        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.req.refresh_from_db()
        self.lead.refresh_from_db()

        self.assertEqual(self.order.status, PaymentOrder.Status.CHARGED)
        self.assertEqual(self.req.status, PaymentRequest.Status.PAID)
        self.assertEqual(self.req.paid_order_id, self.order.id)
        # This is the gate that unlocks send_application_link.
        self.assertIsNotNone(self.lead.application_fee_paid_at)
        self.assertEqual(self.lead.application_fee_mode, "ONLINE")
        self.assertEqual(self.lead.application_fee_ref, "jd-AF1N01-1")
        self.assertEqual(self.lead.application_fee_amount, Decimal("1000.00"))

    def test_webhook_payload_is_not_trusted_on_its_own(self):
        """SmartGateway doesn't sign webhook bodies, so a CHARGED claim
        must be confirmed against /orders/ before money is believed."""
        with patch.object(
            services, "fetch_order",
            return_value=_order_body(status="AUTHORIZATION_FAILED"),
        ) as fetched:
            self._post(self._body(status="CHARGED"))

        fetched.assert_called_once()
        self.order.refresh_from_db()
        self.lead.refresh_from_db()
        self.assertEqual(
            self.order.status, PaymentOrder.Status.AUTHORIZATION_FAILED,
        )
        self.assertIsNone(self.lead.application_fee_paid_at)

    @override_settings(SMARTGATEWAY_TRUST_WEBHOOK_PAYLOAD=True)
    def test_trusting_the_payload_skips_the_refetch(self):
        with patch.object(services, "fetch_order") as fetched:
            self._post(self._body())

        fetched.assert_not_called()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, PaymentOrder.Status.CHARGED)

    def test_upi_payment_records_mode_upi(self):
        with patch.object(
            services, "fetch_order",
            return_value=_order_body(
                payment_method="UPI", payment_method_type="UPI",
            ),
        ):
            self._post(self._body())

        self.lead.refresh_from_db()
        self.assertEqual(self.lead.application_fee_mode, "UPI")

    def test_redelivery_is_a_no_op(self):
        """SmartGateway retries until it sees a 200, and warns a webhook
        may arrive twice — replay must not double-settle."""
        with patch.object(
            services, "fetch_order", return_value=_order_body(),
        ):
            self._post(self._body())
            self.order.refresh_from_db()
            first_charged_at = self.order.charged_at

            resp = self._post(self._body())

        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.charged_at, first_charged_at)
        self.assertEqual(SmartGatewayWebhookEvent.objects.count(), 1)

    def test_bad_credentials_are_rejected_and_nothing_recorded(self):
        resp = self._post(self._body(), password="wrong")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(SmartGatewayWebhookEvent.objects.count(), 0)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, PaymentOrder.Status.PENDING_VBV)

    def test_unhandled_event_is_recorded_as_skipped(self):
        resp = self._post(self._body(event_name="MANDATE_CREATED"))

        self.assertEqual(resp.status_code, 200)
        event = SmartGatewayWebhookEvent.objects.get()
        self.assertEqual(event.status, SmartGatewayWebhookEvent.Status.SKIPPED)

    def test_unknown_order_is_recorded_as_error_but_still_200s(self):
        # A non-2xx here would make SmartGateway retry forever over a
        # payload that will never match anything.
        body = self._body()
        body["content"]["order"]["order_id"] = "AF999N99"
        resp = self._post(body)

        self.assertEqual(resp.status_code, 200)
        event = SmartGatewayWebhookEvent.objects.get()
        self.assertEqual(event.status, SmartGatewayWebhookEvent.Status.ERROR)

    def test_failure_webhook_leaves_the_lead_alone(self):
        with patch.object(
            services, "fetch_order",
            return_value=_order_body(status="AUTHENTICATION_FAILED"),
        ):
            self._post(self._body(event_name="ORDER_FAILED"))

        self.order.refresh_from_db()
        self.lead.refresh_from_db()
        self.assertEqual(
            self.order.status, PaymentOrder.Status.AUTHENTICATION_FAILED,
        )
        self.assertIsNone(self.lead.application_fee_paid_at)
        self.assertEqual(self.req.status, PaymentRequest.Status.PENDING)

    def test_manual_mark_paid_is_not_overwritten(self):
        """Accounts reconciled it by hand before the webhook landed —
        their reference is the record of truth, not ours."""
        self.lead.application_fee_paid_at = timezone.now()
        self.lead.application_fee_ref = "MANUAL-NEFT-77"
        self.lead.application_fee_mode = "NEFT"
        self.lead.save()

        with patch.object(
            services, "fetch_order", return_value=_order_body(),
        ):
            self._post(self._body())

        self.lead.refresh_from_db()
        self.assertEqual(self.lead.application_fee_ref, "MANUAL-NEFT-77")
        self.assertEqual(self.lead.application_fee_mode, "NEFT")
        # The order itself still settles — only the lead fields are held.
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, PaymentOrder.Status.CHARGED)


@override_settings(**SG_ON)
class ReturnUrlTests(_LeadFixture):

    def setUp(self):
        self.req = services.application_fee_request_for(
            lead=self.lead, amount=Decimal("1000.00"),
        )
        self.order = PaymentOrder.objects.create(
            request=self.req, order_id="AF1N01", amount=Decimal("1000.00"),
            sg_order_ref="ordeh_x", status=PaymentOrder.Status.PENDING_VBV,
        )

    def test_return_url_reconciles_rather_than_trusting_the_redirect(self):
        with patch.object(
            services, "fetch_order", return_value=_order_body(),
        ) as fetched:
            resp = self.client.get(
                reverse("public-pay-return", args=[self.req.token]),
            )

        fetched.assert_called_once()
        self.assertIn("status=success", resp["Location"])
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.application_fee_paid_at)

    def test_failed_order_shows_failure(self):
        with patch.object(
            services, "fetch_order",
            return_value=_order_body(status="AUTHORIZATION_FAILED"),
        ):
            resp = self.client.get(
                reverse("public-pay-return", args=[self.req.token]),
            )
        self.assertIn("status=failed", resp["Location"])

    def test_gateway_error_shows_pending_not_failure(self):
        """The payment may well have succeeded — the webhook will settle
        it. Don't tell the student it failed."""
        with patch.object(
            services, "fetch_order",
            side_effect=SmartGatewayError("timeout"),
        ):
            resp = self.client.get(
                reverse("public-pay-return", args=[self.req.token]),
            )
        self.assertIn("status=pending", resp["Location"])

    def test_signed_status_is_the_fallback_when_the_api_read_fails(self):
        """A valid RESPONSE_KEY signature is authenticated, so it beats
        showing 'pending' when /orders/ is unreachable."""
        params = {"order_id": self.order.order_id, "status": "CHARGED",
                  "status_id": "21"}
        params["signature"] = _sign(params)
        params["signature_algorithm"] = "HMAC-SHA256"

        with patch.object(
            services, "fetch_order",
            side_effect=SmartGatewayError("timeout"),
        ):
            resp = self.client.get(
                reverse("public-pay-return", args=[self.req.token]),
                params,
            )
        self.assertIn("status=success", resp["Location"])

    def test_unsigned_claim_does_not_get_that_fallback(self):
        """Same request without a valid signature stays 'pending' — the
        query string on its own proves nothing."""
        with patch.object(
            services, "fetch_order",
            side_effect=SmartGatewayError("timeout"),
        ):
            resp = self.client.get(
                reverse("public-pay-return", args=[self.req.token]),
                {"order_id": self.order.order_id, "status": "CHARGED"},
            )
        self.assertIn("status=pending", resp["Location"])


@override_settings(**SG_ON)
class FeeLinkIntegrationTests(_LeadFixture):
    """`send_fee_link` should hand out the SmartGateway pay URL when the
    gateway is up, and silently fall back when it isn't."""

    def test_pay_url_is_used_when_enabled(self):
        from apps.leads.send_links import send_fee_link

        result = send_fee_link(lead=self.lead, institute_key="JDIFT")

        self.assertEqual(result["gateway"], "smartgateway")
        self.assertIsNotNone(result["payment_request_id"])
        self.assertIn("/api/public/pay/", result["url"])

    def test_falls_back_to_static_url_when_request_cannot_be_raised(self):
        from apps.leads.send_links import send_fee_link

        with patch.object(
            services, "application_fee_request_for",
            side_effect=SmartGatewayError("misconfigured"),
        ):
            result = send_fee_link(lead=self.lead, institute_key="JDIFT")

        self.assertEqual(result["gateway"], "manual")
        self.assertIsNone(result["payment_request_id"])
        self.assertTrue(result["url"].startswith("http"))

    @override_settings(SMARTGATEWAY_ENABLED=False)
    def test_disabled_gateway_uses_static_url(self):
        from apps.leads.send_links import send_fee_link

        result = send_fee_link(lead=self.lead, institute_key="JDIFT")
        self.assertEqual(result["gateway"], "manual")
        self.assertEqual(PaymentRequest.objects.count(), 0)

    @override_settings(SMARTGATEWAY_PUBLIC_BASE_URL="")
    def test_enabled_but_misconfigured_falls_back_and_says_so(self):
        """The dangerous case: switched on, but the pay link would be
        built off the wrong host. Must send the manual link, loudly."""
        from apps.leads.send_links import send_fee_link

        with self.assertLogs("apps.leads", level="ERROR") as logs:
            result = send_fee_link(lead=self.lead, institute_key="JDIFT")

        self.assertEqual(result["gateway"], "manual")
        self.assertEqual(PaymentRequest.objects.count(), 0)
        self.assertIn("SMARTGATEWAY_PUBLIC_BASE_URL", "\n".join(logs.output))
