"""Razorpay Payment Links — JDSD's application fee.

What matters: the fee lands on Razorpay (not SmartGateway) for JDSD, a
callback or webhook can't settle anything without a valid signature, the
lead is marked paid from the API's answer, and a superseded link is
cancelled so nobody pays twice. No network — the client is patched.
"""

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.leads.models import Lead
from apps.master.models import Campus, Institute, LeadSource, Program
from apps.payments import razorpay, services
from apps.payments.models import (
    PaymentOrder, PaymentRequest, SmartGatewayWebhookEvent,
)

KEY_SECRET = "rzp_secret_for_tests"
WEBHOOK_SECRET = "rzp_webhook_secret"

RZP_ON = dict(
    RAZORPAY_ENABLED=True,
    RAZORPAY_KEY_ID="rzp_test_abc",
    RAZORPAY_KEY_SECRET=KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET,
    SMARTGATEWAY_PUBLIC_BASE_URL="https://api.jd.test",
    SMARTGATEWAY_ENABLED=False,
    SMARTGATEWAY_AUTOSEND_APPLICATION_LINK=False,
)


def _link(status="created", *, link_id="plink_1", ref="AF1N01", payments=None):
    return {
        "id": link_id, "reference_id": ref, "status": status,
        "short_url": f"https://rzp.io/i/{link_id}",
        "expire_by": int((timezone.now() + timedelta(days=1)).timestamp()),
        "payments": payments,
    }


PAID_UPI = [{
    "payment_id": "pay_ABC", "method": "upi", "status": "captured",
    "amount": 50000, "created_at": 1757900000,
}]


class HelperTests(TestCase):

    def test_amount_goes_out_in_paise(self):
        self.assertEqual(razorpay.to_paise("500"), 50000)
        self.assertEqual(razorpay.to_paise(Decimal("1.50")), 150)

    def test_sub_paise_and_below_minimum_are_refused(self):
        for bad in ("1.005", "0.50", "abc"):
            with self.assertRaises(razorpay.RazorpayError, msg=bad):
                razorpay.to_paise(bad)

    def test_paid_link_normalises_to_a_charged_upi_order(self):
        body = razorpay.normalise_link(_link("paid", payments=PAID_UPI))
        self.assertEqual(body["status"], "CHARGED")
        self.assertEqual(body["txn_id"], "pay_ABC")
        self.assertEqual(body["payment_method_type"], "UPI")
        self.assertTrue(body["date_created"].startswith("2025-"))

    def test_unpaid_link_carries_no_payment(self):
        body = razorpay.normalise_link(_link("expired"))
        self.assertEqual((body["status"], body["txn_id"]), ("EXPIRED", ""))

    @override_settings(**RZP_ON)
    def test_callback_signature_round_trip(self):
        params = {
            "razorpay_payment_id": "pay_ABC",
            "razorpay_payment_link_id": "plink_1",
            "razorpay_payment_link_reference_id": "AF1N01",
            "razorpay_payment_link_status": "paid",
        }
        params["razorpay_signature"] = hmac.new(
            KEY_SECRET.encode(),
            b"plink_1|AF1N01|paid|pay_ABC", hashlib.sha256,
        ).hexdigest()
        self.assertTrue(razorpay.verify_callback_signature(params))

        tampered = {**params, "razorpay_payment_link_status": "PAID "}
        self.assertFalse(razorpay.verify_callback_signature(tampered))
        self.assertFalse(razorpay.verify_callback_signature(
            {k: v for k, v in params.items() if k != "razorpay_payment_id"},
        ))

    @override_settings(**RZP_ON)
    def test_webhook_signature_is_over_the_raw_bytes(self):
        raw = b'{"event": "payment_link.paid"}'
        sig = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        self.assertTrue(razorpay.verify_webhook_signature(raw, sig))
        self.assertFalse(razorpay.verify_webhook_signature(
            b'{"event":"payment_link.paid"}', sig,
        ))

    @override_settings(**{**RZP_ON, "RAZORPAY_WEBHOOK_SECRET": ""})
    def test_unset_webhook_secret_rejects_everything(self):
        self.assertFalse(razorpay.verify_webhook_signature(b"{}", "anything"))

    @override_settings(**RZP_ON)
    def test_link_payload_turns_off_razorpays_own_notifications(self):
        with patch.object(razorpay, "_request", return_value={}) as req:
            razorpay.create_payment_link(
                reference_id="AF1N01", amount="500",
                callback_url="https://api.jd.test/cb/",
                customer_phone="+91 99999 99999",
            )
        payload = req.call_args.kwargs["payload"]
        self.assertEqual(payload["notify"], {"sms": False, "email": False})
        self.assertFalse(payload["accept_partial"])
        self.assertEqual(payload["customer"]["contact"], "+919999999999")

    @override_settings(**RZP_ON)
    def test_rejected_prefill_is_dropped_rather_than_losing_the_payment(self):
        """Seen live in test mode: Razorpay 400s on 9999999999."""
        refusal = razorpay.RazorpayError(
            "Recurring digits in customer contact are disallowed", status=400,
        )
        with patch.object(
            razorpay, "_request", side_effect=[refusal, {"id": "plink_1"}],
        ) as req:
            link = razorpay.create_payment_link(
                reference_id="AF1N01", amount="500",
                callback_url="https://api.jd.test/cb/",
                customer_phone="9999999999",
            )
        self.assertEqual(link["id"], "plink_1")
        self.assertNotIn("customer", req.call_args_list[1].kwargs["payload"])

    @override_settings(**RZP_ON)
    def test_other_errors_are_not_retried(self):
        with patch.object(
            razorpay, "_request",
            side_effect=razorpay.RazorpayError("Authentication failed", status=401),
        ) as req, self.assertRaises(razorpay.RazorpayError):
            razorpay.create_payment_link(
                reference_id="AF1N01", amount="500",
                callback_url="https://api.jd.test/cb/", customer_phone="98765 43210",
            )
        self.assertEqual(req.call_count, 1)


@override_settings(**RZP_ON)
class JdsdApplicationFeeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.jdsd = Institute.objects.create(name="JDSD", code="JDSD")
        cls.campus = Campus.objects.create(name="Bangalore", code="BLR")
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.jdsd,
        )
        cls.source = LeadSource.objects.create(name="Website", slug="website")

    def setUp(self):
        self.lead = Lead.objects.create(
            name="Asha Rao", phone="9999999999", email="asha@example.com",
            campus=self.campus, program=self.program, source=self.source,
        )

    def _request(self):
        return services.application_fee_request_for(
            self.lead, amount="500", institute_key="JDSD",
        )

    def _open(self, pr, link):
        with patch.object(razorpay, "create_payment_link", return_value=link) as c:
            resp = self.client.get(reverse("public-pay", args=[pr.token]))
        return resp, c

    # --- raising and opening -----------------------------------------

    def test_fee_link_uses_razorpay_on_the_trust_account(self):
        from apps.leads.send_links import send_fee_link

        result = send_fee_link(lead=self.lead, institute_key="JDSD")
        self.assertEqual(result["gateway"], "razorpay")
        pr = PaymentRequest.objects.get(pk=result["payment_request_id"])
        self.assertEqual((pr.gateway, pr.account), ("razorpay", "JDSD_TRUST"))
        self.assertIn("/api/public/pay/", result["url"])

    @override_settings(RAZORPAY_ENABLED=False)
    def test_razorpay_switched_off_sends_the_manual_link_quietly(self):
        from apps.leads.send_links import send_fee_link

        with self.assertNoLogs("apps.leads", level="ERROR"):
            result = send_fee_link(lead=self.lead, institute_key="JDSD")
        self.assertEqual(result["gateway"], "manual")
        self.assertEqual(PaymentRequest.objects.count(), 0)

    @override_settings(RAZORPAY_KEY_SECRET="")
    def test_switched_on_but_misconfigured_falls_back_loudly(self):
        from apps.leads.send_links import send_fee_link

        with self.assertLogs("apps.leads", level="ERROR") as logs:
            result = send_fee_link(lead=self.lead, institute_key="JDSD")
        self.assertEqual(result["gateway"], "manual")
        self.assertIn("RAZORPAY_KEY_SECRET", "\n".join(logs.output))

    def test_opening_the_link_mints_a_razorpay_link_and_redirects(self):
        pr = self._request()
        resp, create = self._open(pr, _link(ref="AF%dN01" % pr.pk))

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "https://rzp.io/i/plink_1")
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["reference_id"], f"AF{pr.pk}N01")
        self.assertTrue(kwargs["callback_url"].endswith(f"/pay/{pr.token}/return/"))
        order = pr.orders.get()
        self.assertEqual(order.sg_order_ref, "plink_1")
        self.assertEqual(order.status, PaymentOrder.Status.NEW)

    def test_reopening_reuses_a_live_link(self):
        pr = self._request()
        self._open(pr, _link())
        resp, create = self._open(pr, _link(link_id="plink_2"))
        create.assert_not_called()
        self.assertEqual(resp["Location"], "https://rzp.io/i/plink_1")

    def test_expired_link_is_cancelled_before_a_new_one_is_minted(self):
        pr = self._request()
        self._open(pr, _link())
        pr.orders.update(session_expires_at=timezone.now() - timedelta(minutes=1))

        with patch.object(razorpay, "fetch_payment_link", return_value=_link()), \
                patch.object(
                    razorpay, "cancel_payment_link",
                    return_value=_link("cancelled"),
                ) as cancel:
            resp, create = self._open(pr, _link(link_id="plink_2"))

        cancel.assert_called_once_with("plink_1")
        create.assert_called_once()
        self.assertEqual(resp["Location"], "https://rzp.io/i/plink_2")
        statuses = list(pr.orders.order_by("created_on").values_list("status", flat=True))
        self.assertEqual(statuses, ["CANCELLED", "NEW"])

    def test_old_link_found_paid_is_settled_not_replaced(self):
        pr = self._request()
        self._open(pr, _link())
        pr.orders.update(session_expires_at=timezone.now() - timedelta(minutes=1))

        with patch.object(
            razorpay, "fetch_payment_link",
            return_value=_link("paid", payments=PAID_UPI),
        ), patch.object(razorpay, "cancel_payment_link") as cancel:
            _, create = self._open(pr, _link(link_id="plink_2"))

        cancel.assert_not_called()
        create.assert_not_called()
        pr.refresh_from_db()
        self.assertEqual(pr.status, PaymentRequest.Status.PAID)

    # --- settling ----------------------------------------------------

    def _signed_callback(self, ref, status="paid"):
        params = {
            "razorpay_payment_id": "pay_ABC",
            "razorpay_payment_link_id": "plink_1",
            "razorpay_payment_link_reference_id": ref,
            "razorpay_payment_link_status": status,
        }
        msg = f"plink_1|{ref}|{status}|pay_ABC".encode()
        params["razorpay_signature"] = hmac.new(
            KEY_SECRET.encode(), msg, hashlib.sha256,
        ).hexdigest()
        return params

    def test_callback_reconciles_and_marks_the_lead_paid(self):
        pr = self._request()
        self._open(pr, _link())
        order = pr.orders.get()

        with patch.object(
            razorpay, "fetch_payment_link",
            return_value=_link("paid", payments=PAID_UPI),
        ):
            resp = self.client.get(
                reverse("public-pay-return", args=[pr.token]),
                self._signed_callback(order.order_id),
            )

        self.assertIn("status=success", resp["Location"])
        self.lead.refresh_from_db()
        self.assertIsNotNone(self.lead.application_fee_paid_at)
        self.assertEqual(self.lead.application_fee_mode, "UPI")
        self.assertEqual(self.lead.application_fee_ref, "pay_ABC")
        self.assertIn("Razorpay — JD Educational Trust", self.lead.application_fee_notes)

    def test_signed_callback_is_the_fallback_when_the_api_read_fails(self):
        pr = self._request()
        self._open(pr, _link())
        order = pr.orders.get()

        with patch.object(
            razorpay, "fetch_payment_link",
            side_effect=razorpay.RazorpayError("timeout"),
        ):
            resp = self.client.get(
                reverse("public-pay-return", args=[pr.token]),
                self._signed_callback(order.order_id),
            )
        self.assertIn("status=success", resp["Location"])
        # A redirect alone never settles anything.
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.application_fee_paid_at)

    def test_forged_callback_gets_no_fallback(self):
        pr = self._request()
        self._open(pr, _link())
        params = self._signed_callback(pr.orders.get().order_id)
        params["razorpay_signature"] = "0" * 64

        with patch.object(
            razorpay, "fetch_payment_link",
            side_effect=razorpay.RazorpayError("timeout"),
        ):
            resp = self.client.get(
                reverse("public-pay-return", args=[pr.token]), params,
            )
        self.assertIn("status=pending", resp["Location"])

    def _webhook(self, body, *, secret=WEBHOOK_SECRET, event_id="evt_1"):
        raw = json.dumps(body).encode()
        sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return self.client.post(
            reverse("razorpay-webhook"), raw, content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=sig, HTTP_X_RAZORPAY_EVENT_ID=event_id,
        )

    def _paid_event(self, order):
        return {
            "event": "payment_link.paid",
            "payload": {"payment_link": {"entity": {
                "id": order.sg_order_ref, "reference_id": order.order_id,
                "status": "paid",
            }}},
        }

    def test_webhook_settles_from_the_api_and_replay_is_a_no_op(self):
        pr = self._request()
        self._open(pr, _link())
        order = pr.orders.get()

        with patch.object(
            razorpay, "fetch_payment_link",
            return_value=_link("paid", payments=PAID_UPI),
        ) as fetch:
            first = self._webhook(self._paid_event(order))
            second = self._webhook(self._paid_event(order))

        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(SmartGatewayWebhookEvent.objects.get().status, "PROCESSED")
        pr.refresh_from_db()
        self.assertEqual(pr.status, PaymentRequest.Status.PAID)

    def test_webhook_with_bad_signature_is_rejected_and_not_recorded(self):
        pr = self._request()
        self._open(pr, _link())
        resp = self._webhook(self._paid_event(pr.orders.get()), secret="wrong")
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(SmartGatewayWebhookEvent.objects.exists())

    def test_webhook_payload_alone_does_not_settle(self):
        """A signed 'paid' event whose link the API says is unpaid."""
        pr = self._request()
        self._open(pr, _link())
        with patch.object(razorpay, "fetch_payment_link", return_value=_link()):
            self._webhook(self._paid_event(pr.orders.get()))
        pr.refresh_from_db()
        self.assertEqual(pr.status, PaymentRequest.Status.PENDING)
