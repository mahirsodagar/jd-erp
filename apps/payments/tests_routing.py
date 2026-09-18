"""Fee → gateway → settlement-account routing (client rule of 2026-09-11).

The expensive mistakes here are silent ones: a JDSD fee settling into
the JDIFT account, an in-flight order checked against the wrong
merchant, or an account going live just because the shared credentials
happen to be filled in. No network — the HTTP layer is patched.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admissions.models import Enrollment, Student
from apps.fees.models import Installment
from apps.leads.models import Lead
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, LeadSource, Program, Semester,
)
from apps.payments import gateway, routing, services
from apps.payments.models import PaymentOrder, PaymentRequest
from apps.payments.routing import (
    FEE_APPLICATION, FEE_INSTALLMENT, FEE_REGISTRATION, Route,
)

ACCOUNT_KEYS = ("JDSD_TRUST", "JDIFT_MAIN", "JDIFT_ROYALTY")

SG_ON = dict(
    SMARTGATEWAY_ENABLED=True,
    SMARTGATEWAY_API_KEY="shared_key",
    SMARTGATEWAY_MERCHANT_ID="shared_mid",
    SMARTGATEWAY_CLIENT_ID="hdfcmaster",
    SMARTGATEWAY_RESPONSE_KEY="shared_rk",
    SMARTGATEWAY_WEBHOOK_USERNAME="shared_user",
    SMARTGATEWAY_WEBHOOK_PASSWORD="shared_pass",
    SMARTGATEWAY_PUBLIC_BASE_URL="https://api.jd.test",
    SMARTGATEWAY_AUTOSEND_APPLICATION_LINK=False,
    SMARTGATEWAY_ACCOUNTS={a: {"live": True} for a in ACCOUNT_KEYS},
    # Pinned off so a developer's .env can't change what these assert;
    # tests_razorpay.py covers the switched-on path.
    RAZORPAY_ENABLED=False,
)


def _sg(account):
    return Route(routing.GATEWAY_SMARTGATEWAY, account)


class RouteTableTests(TestCase):
    """The client's table, rule by rule."""

    def test_jdsd_application_fee_goes_to_razorpay_trust(self):
        self.assertEqual(
            routing.resolve(fee=FEE_APPLICATION, institute="JDSD", campus="BLR"),
            Route(routing.GATEWAY_RAZORPAY, "JDSD_TRUST"),
        )

    def test_jdsd_registration_and_installments_go_to_trust_at_any_centre(self):
        for fee in (FEE_REGISTRATION, FEE_INSTALLMENT):
            for campus in ("BLR", "GOA", "PUNE", ""):
                self.assertEqual(
                    routing.resolve(fee=fee, institute="JDSD", campus=campus),
                    _sg("JDSD_TRUST"), (fee, campus),
                )

    def test_jdift_registration_goes_to_royalty_at_every_centre(self):
        for campus in ("BLR", "GOA", "PUNE", ""):
            self.assertEqual(
                routing.resolve(
                    fee=FEE_REGISTRATION, institute="JDIFT", campus=campus,
                ),
                _sg("JDIFT_ROYALTY"), campus,
            )

    def test_jdift_app_fee_and_installments_at_blr_goa_go_to_main(self):
        for fee in (FEE_APPLICATION, FEE_INSTALLMENT):
            for campus in ("BLR", "GOA", "goa"):
                self.assertEqual(
                    routing.resolve(fee=fee, institute="JDIFT", campus=campus),
                    _sg("JDIFT_MAIN"), (fee, campus),
                )

    def test_jdift_app_fee_and_installments_elsewhere_are_on_hold(self):
        for fee in (FEE_APPLICATION, FEE_INSTALLMENT):
            self.assertIsNone(
                routing.resolve(fee=fee, institute="JDIFT", campus="PUNE"),
            )

    def test_program_without_institute_has_no_route(self):
        self.assertIsNone(
            routing.resolve(fee=FEE_INSTALLMENT, institute="", campus="BLR"),
        )

    @override_settings(PAYMENT_ROUTES=[
        {"fee": FEE_INSTALLMENT, "gateway": "smartgateway", "account": "X"},
    ])
    def test_table_is_overridable_per_environment(self):
        self.assertEqual(
            routing.resolve(fee=FEE_INSTALLMENT, institute="ANY", campus=""),
            _sg("X"),
        )


@override_settings(**SG_ON)
class MerchantConfigTests(TestCase):

    def test_blank_account_fields_fall_back_to_shared(self):
        cfg = gateway.merchant_config("JDIFT_MAIN")
        self.assertEqual(cfg.api_key, "shared_key")
        self.assertEqual(cfg.merchant_id, "shared_mid")
        self.assertTrue(cfg.live)

    @override_settings(SMARTGATEWAY_ACCOUNTS={
        "JDSD_TRUST": {
            "live": True, "api_key": "trust_key", "merchant_id": "trust_mid",
        },
    })
    def test_account_fields_override_shared(self):
        cfg = gateway.merchant_config("JDSD_TRUST")
        self.assertEqual((cfg.api_key, cfg.merchant_id), ("trust_key", "trust_mid"))
        self.assertEqual(cfg.client_id, "hdfcmaster")

    @override_settings(SMARTGATEWAY_ACCOUNTS={"JDSD_TRUST": {"api_key": "k"}})
    def test_account_is_not_usable_until_marked_live(self):
        """Full shared credentials must not, on their own, make an account
        take money."""
        self.assertFalse(gateway.is_enabled("JDSD_TRUST"))
        self.assertIn("SMARTGATEWAY_JDSD_TRUST_LIVE",
                      gateway.missing_settings("JDSD_TRUST"))
        self.assertFalse(gateway.is_enabled("JDIFT_MAIN"))
        # The legacy single-merchant config is unaffected.
        self.assertTrue(gateway.is_enabled(""))

    @override_settings(
        SMARTGATEWAY_API_KEY="",
        SMARTGATEWAY_ACCOUNTS={"JDIFT_ROYALTY": {"live": True}},
    )
    def test_missing_settings_name_the_account_variable(self):
        self.assertEqual(
            gateway.missing_settings("JDIFT_ROYALTY"),
            ["SMARTGATEWAY_JDIFT_ROYALTY_API_KEY"],
        )

    @override_settings(SMARTGATEWAY_ACCOUNTS={
        "JDIFT_ROYALTY": {
            "live": True, "merchant_id": "roy_mid",
            "gateway_reference_id": "JDIFT_ROYALTY_TID",
        },
    })
    def test_session_carries_account_merchant_and_reference_id(self):
        with patch.object(gateway, "_request", return_value={}) as req:
            gateway.create_session(
                order_id="FI1N01", amount="10.00", customer_id="STU1",
                return_url="https://api.jd.test/r/", account="JDIFT_ROYALTY",
            )
        cfg = req.call_args.kwargs["cfg"]
        payload = req.call_args.kwargs["payload"]
        self.assertEqual(cfg.merchant_id, "roy_mid")
        self.assertEqual(
            payload["metadata.JUSPAY:gateway_reference_id"], "JDIFT_ROYALTY_TID",
        )
        self.assertEqual(
            gateway._base_headers(cfg)["x-merchantid"], "roy_mid",
        )

    def test_legacy_config_sends_no_reference_id(self):
        with patch.object(gateway, "_request", return_value={}) as req:
            gateway.create_session(
                order_id="AF1N01", amount="10.00", customer_id="LEAD1",
                return_url="https://api.jd.test/r/",
            )
        self.assertNotIn(
            "metadata.JUSPAY:gateway_reference_id",
            req.call_args.kwargs["payload"],
        )

    @override_settings(SMARTGATEWAY_ACCOUNTS={
        "JDSD_TRUST": {
            "live": True, "webhook_username": "trust_u",
            "webhook_password": "trust_p",
        },
    })
    def test_webhook_accepts_any_configured_accounts_credentials(self):
        import base64

        def basic(u, p):
            return "Basic " + base64.b64encode(f"{u}:{p}".encode()).decode()

        self.assertTrue(gateway.check_webhook_auth(basic("trust_u", "trust_p")))
        self.assertTrue(gateway.check_webhook_auth(basic("shared_user", "shared_pass")))
        self.assertFalse(gateway.check_webhook_auth(basic("trust_u", "shared_pass")))


class _Fixture(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.jdift = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.jdsd = Institute.objects.create(name="JDSD", code="JDSD")
        cls.blr = Campus.objects.create(name="Bangalore", code="BLR")
        cls.pune = Campus.objects.create(name="Pune", code="PUNE")
        cls.diploma = Program.objects.create(
            name="Diploma in Fashion Design", code="DFD", institute=cls.jdift,
        )
        cls.bdes = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.jdsd,
        )
        cls.source = LeadSource.objects.create(name="Website", slug="website")

    def _lead(self, program, campus):
        return Lead.objects.create(
            name="Asha Rao", phone="9999999999", email="asha@example.com",
            campus=campus, program=program, source=self.source,
        )


@override_settings(**SG_ON)
class ApplicationFeeRoutingTests(_Fixture):

    def test_jdift_blr_lead_request_is_frozen_to_main(self):
        pr = services.application_fee_request_for(
            self._lead(self.diploma, self.blr), amount="500",
            institute_key="JDIFT",
        )
        self.assertEqual((pr.gateway, pr.account), ("smartgateway", "JDIFT_MAIN"))

    def test_jdsd_lead_never_gets_a_smartgateway_link(self):
        """JDSD's application fee belongs to Razorpay; with Razorpay off
        it must fall back to the manual link, not onto SmartGateway."""
        from apps.leads.send_links import send_fee_link

        result = send_fee_link(
            lead=self._lead(self.bdes, self.blr), institute_key="JDSD",
        )
        self.assertEqual(result["gateway"], "manual")
        self.assertEqual(PaymentRequest.objects.count(), 0)

    def test_jdift_lead_at_another_centre_gets_the_manual_link(self):
        from apps.leads.send_links import send_fee_link

        result = send_fee_link(
            lead=self._lead(self.diploma, self.pune), institute_key="JDIFT",
        )
        self.assertEqual(result["gateway"], "manual")
        self.assertEqual(PaymentRequest.objects.count(), 0)

    def test_institute_the_link_was_sent_for_wins_over_program(self):
        lead = self._lead(self.diploma, self.blr)
        self.assertEqual(
            routing.route_for_lead(lead, "JDSD").account, "JDSD_TRUST",
        )
        self.assertEqual(routing.route_for_lead(lead).account, "JDIFT_MAIN")

    @override_settings(SMARTGATEWAY_ACCOUNTS={})
    def test_account_not_live_falls_back_loudly(self):
        from apps.leads.send_links import send_fee_link

        with self.assertLogs("apps.leads", level="ERROR") as logs:
            result = send_fee_link(
                lead=self._lead(self.diploma, self.blr), institute_key="JDIFT",
            )
        self.assertEqual(result["gateway"], "manual")
        self.assertIn("SMARTGATEWAY_JDIFT_MAIN_LIVE", "\n".join(logs.output))

    def test_open_request_on_another_account_is_not_reused(self):
        lead = self._lead(self.diploma, self.blr)
        legacy = PaymentRequest.objects.create(
            lead=lead, amount=Decimal("500"), account="",
        )
        pr = services.application_fee_request_for(
            lead, amount="500", institute_key="JDIFT",
        )
        self.assertNotEqual(pr.pk, legacy.pk)
        self.assertEqual(pr.account, "JDIFT_MAIN")

    def test_order_and_status_check_use_the_requests_account(self):
        pr = services.application_fee_request_for(
            self._lead(self.diploma, self.blr), amount="500",
            institute_key="JDIFT",
        )
        session = {"id": "ordeh_1", "status": "NEW", "payment_links": {
            "web": "https://bank.test/pay", "expiry": None,
        }}
        with patch.object(services, "create_session", return_value=session) as cs:
            order = services.start_or_resume_order(pr)
        self.assertEqual(cs.call_args.kwargs["account"], "JDIFT_MAIN")
        self.assertEqual(cs.call_args.kwargs["udf"]["udf3"], "JDIFT_MAIN")

        with patch.object(
            services, "fetch_order", return_value={"status": "CHARGED"},
        ) as fo:
            services.reconcile_order(order)
        self.assertEqual(fo.call_args.kwargs["account"], "JDIFT_MAIN")
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.Status.CHARGED)

    def test_legacy_request_still_pays_on_the_shared_merchant(self):
        """Rows raised before routing existed have account='' and must
        keep working unchanged."""
        pr = PaymentRequest.objects.create(
            lead=self._lead(self.diploma, self.blr), amount=Decimal("500"),
        )
        session = {"id": "o", "payment_links": {"web": "https://bank.test/p"}}
        with patch.object(services, "create_session", return_value=session):
            resp = self.client.get(reverse("public-pay", args=[pr.token]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "https://bank.test/p")


@override_settings(**SG_ON)
class InstallmentRoutingTests(_Fixture):

    def _installment(self, program, campus, kind=Installment.Kind.COURSE):
        year, _ = AcademicYear.objects.get_or_create(
            code="2026-27",
            defaults={"start_date": date(2026, 6, 1), "end_date": date(2027, 5, 31)},
        )
        sem, _ = Semester.objects.get_or_create(number=1, defaults={"name": "Sem 1"})
        batch = Batch.objects.create(
            name=f"B-{program.code}-{campus.code}", campus=campus,
            program=program, academic_year=year,
        )
        user = get_user_model().objects.create_user(
            username=f"s-{program.code}-{campus.code}-{kind}",
            email=f"{program.code}-{campus.code}-{kind}@example.com".lower(),
            password="pw-not-used",
        )
        student = Student.objects.create(
            student_name="Asha Rao", gender="F", dob=date(2006, 1, 1),
            nationality="INDIAN", institute=program.institute, campus=campus,
            program=program, academic_year=year, student_mobile="9000000000",
            student_email="asha@example.com", user_account=user,
        )
        enrollment = Enrollment.objects.create(
            student=student, program=program, semester=sem, campus=campus,
            batch=batch, academic_year=year, status=Enrollment.Status.ACTIVE,
        )
        inst = Installment.objects.create(
            enrollment=enrollment, kind=kind, sequence=1,
            due_date=date(2026, 7, 1), amount=Decimal("10000"),
        )
        return inst, user

    def test_jdsd_registration_settles_to_trust(self):
        inst, _ = self._installment(
            self.bdes, self.pune, Installment.Kind.REGISTRATION,
        )
        pr = services.installment_request_for(inst, amount="10000")
        self.assertEqual(pr.account, "JDSD_TRUST")

    def test_jdift_registration_at_any_centre_settles_to_royalty(self):
        inst, _ = self._installment(
            self.diploma, self.pune, Installment.Kind.REGISTRATION,
        )
        pr = services.installment_request_for(inst, amount="10000")
        self.assertEqual(pr.account, "JDIFT_ROYALTY")

    def test_jdift_course_installment_at_blr_settles_to_main(self):
        inst, _ = self._installment(self.diploma, self.blr)
        pr = services.installment_request_for(inst, amount="10000")
        self.assertEqual(pr.account, "JDIFT_MAIN")

    def test_jdift_course_installment_elsewhere_is_not_payable_online(self):
        inst, user = self._installment(self.diploma, self.pune)
        client = APIClient()
        client.force_authenticate(user=user)

        summary = client.get(reverse("portal-fees")).json()
        self.assertFalse(summary["online_payment_enabled"])

        resp = client.post(
            reverse("portal-fee-installment-pay", args=[inst.id]),
        )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(PaymentRequest.objects.count(), 0)

    def test_receipt_names_the_settlement_account(self):
        from apps.fees.models import FeeReceipt

        inst, _ = self._installment(
            self.diploma, self.blr, Installment.Kind.REGISTRATION,
        )
        pr = services.installment_request_for(inst, amount="10000")
        order = PaymentOrder.objects.create(
            request=pr, order_id="FI1N01", amount=pr.amount,
        )
        services.apply_order_body(order, {"status": "CHARGED"})

        receipt = FeeReceipt.objects.get(instrument_ref="FI1N01")
        self.assertIn("Royalty", receipt.bank)
