"""The manual-payment page fee links fall back to (apps.payments.manual)."""

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from .manual import clean_amount, manual_pay_url

DETAILS = {
    "JDIFT": {
        "vpa": "jdift@hdfc", "payee_name": "JD Institute of Fashion Technology",
        "ac_name": "JD INSTITUTE OF FASHION TECHNOLOGY", "ac_no": "123456",
        "ifsc": "HDFC0000001", "bank": "HDFC Bank", "branch": "Bengaluru",
        "default_amount": "1000",
    },
}


@override_settings(
    INSTITUTE_PAYMENT_DETAILS=DETAILS,
    SMARTGATEWAY_PUBLIC_BASE_URL="https://api.jd.test",
)
class ManualPayUrlTests(SimpleTestCase):

    def test_builds_absolute_url_with_amount_and_purpose(self):
        url = manual_pay_url("jdift", amount="1000", purpose="Application fee")
        self.assertEqual(
            url,
            "https://api.jd.test/api/public/pay/manual/JDIFT/"
            "?amount=1000&for=Application+fee",
        )

    def test_no_amount_leaves_it_off(self):
        self.assertEqual(
            manual_pay_url("JDIFT"),
            "https://api.jd.test/api/public/pay/manual/JDIFT/",
        )

    def test_unknown_institute_is_refused(self):
        with self.assertRaises(ValueError):
            manual_pay_url("JDSD")

    @override_settings(SMARTGATEWAY_PUBLIC_BASE_URL="")
    def test_missing_public_origin_is_refused(self):
        with self.assertRaisesRegex(ValueError, "SMARTGATEWAY_PUBLIC_BASE_URL"):
            manual_pay_url("JDIFT")

    def test_clean_amount(self):
        self.assertEqual(clean_amount("1000"), "1000")
        self.assertEqual(clean_amount("1000.50"), "1000.50")
        self.assertEqual(clean_amount("abc"), "")
        self.assertEqual(clean_amount("-5"), "")
        self.assertEqual(clean_amount(""), "")


@override_settings(INSTITUTE_PAYMENT_DETAILS=DETAILS)
class ManualPayPageTests(SimpleTestCase):

    def test_page_shows_qr_upi_id_bank_details_and_amount(self):
        r = self.client.get(
            reverse("public-pay-manual", args=["JDIFT"]),
            {"amount": "1000", "for": "Application fee"},
        )
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("jdift@hdfc", html)
        self.assertIn("123456", html)
        self.assertIn("HDFC0000001", html)
        self.assertIn("&#8377;1000", html)
        self.assertIn("Application fee", html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn('href="upi://pay?pa=jdift%40hdfc', html)
        self.assertIn("am=1000", html)

    def test_lower_case_institute_and_bad_amount_still_render(self):
        r = self.client.get(
            reverse("public-pay-manual", args=["jdift"]), {"amount": "<x>"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("<x>", r.content.decode())

    def test_unknown_institute_is_404(self):
        r = self.client.get(reverse("public-pay-manual", args=["NOPE"]))
        self.assertEqual(r.status_code, 404)

    def test_purpose_is_escaped(self):
        r = self.client.get(
            reverse("public-pay-manual", args=["JDIFT"]),
            {"for": "<script>alert(1)</script>"},
        )
        self.assertNotIn("<script>", r.content.decode())
