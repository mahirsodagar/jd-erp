"""A recorded fee payment emails the receipt PDF to the student with the
campus receipts inbox in CC — for receipts keyed at the counter and for
online portal payments alike."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.fees.models import FeeReceipt, Installment
from apps.fees.services.receipt_email import campus_inbox_for, send_receipt_email
from apps.fees.tests_receipt_pdf import _fixture, _receipt
from apps.master.models import Campus
from apps.notifications.models import NotificationDispatchLog

User = get_user_model()

INBOXES = {
    "BNG": "dkul.receipts@jdinstitute.edu.in",
    "GOA": "dkul.goareceipts@jdinstitute.edu.in",
}


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_SMTP_OUTBOUND_ENABLED=True,
    FEE_RECEIPT_CAMPUS_INBOXES=INBOXES,
    ACCOUNTS_INBOX="",
    EMAIL_SMTP_BY_DOMAIN={},
)
class ReceiptEmailTests(TestCase):

    def test_service_sends_pdf_to_student_cc_campus(self):
        enrollment = _fixture()
        r = _receipt(enrollment, amount=Decimal("11800"))

        log = send_receipt_email(r)

        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, [enrollment.student.student_email])
        self.assertEqual(m.cc, ["dkul.receipts@jdinstitute.edu.in"])
        self.assertIn(r.receipt_no, m.subject)
        self.assertEqual(len(m.attachments), 1)
        name, content, mimetype = m.attachments[0]
        self.assertEqual(name, f"{r.receipt_no}.pdf")
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(content.startswith(b"%PDF"))

        self.assertIsNotNone(log)
        self.assertEqual(log.status, NotificationDispatchLog.Status.SENT)
        self.assertEqual(log.template_key, "fees.receipt.email")

    def test_campus_inbox_lookup_is_by_code(self):
        self.assertEqual(campus_inbox_for(Campus(code="GOA")),
                         "dkul.goareceipts@jdinstitute.edu.in")
        self.assertEqual(campus_inbox_for(Campus(code="bng")),
                         "dkul.receipts@jdinstitute.edu.in")
        self.assertEqual(campus_inbox_for(Campus(code="HYD")), "")

    def test_campus_without_inbox_still_mails_the_student(self):
        enrollment = _fixture()
        enrollment.campus.code = "HYD"
        enrollment.campus.save(update_fields=["code"])
        send_receipt_email(_receipt(enrollment))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].cc, [])

    def test_student_without_email_mails_the_campus_only(self):
        enrollment = _fixture()
        enrollment.student.student_email = ""
        enrollment.student.save(update_fields=["student_email"])
        send_receipt_email(_receipt(enrollment))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["dkul.receipts@jdinstitute.edu.in"])
        self.assertEqual(mail.outbox[0].cc, [])

    def test_counter_receipt_api_sends_it(self):
        enrollment = _fixture()
        inst = Installment.objects.create(
            enrollment=enrollment, sequence=1, due_date="2026-08-01",
            amount=Decimal("5000"), description="Installment 1",
        )
        admin = User.objects.create_superuser(
            username="acc", email="acc@e.com", password="x",
        )
        c = APIClient()
        c.force_authenticate(admin)
        r = c.post("/api/fees/receipts/", {
            "enrollment": enrollment.id, "installment": inst.id,
            "basic_fee": "5000", "amount": "5000",
            "payment_mode": "CASH", "received_date": "2026-08-19",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)

        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, [enrollment.student.student_email])
        self.assertEqual(m.cc, ["dkul.receipts@jdinstitute.edu.in"])
        self.assertEqual(m.attachments[0][0],
                         f"{FeeReceipt.objects.get().receipt_no}.pdf")

    @override_settings(EMAIL_SMTP_OUTBOUND_ENABLED=False)
    def test_no_smtp_egress_logs_but_does_not_send(self):
        log = send_receipt_email(_receipt(_fixture()))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(log.status, NotificationDispatchLog.Status.QUEUED)
        self.assertIn("SMTP", log.error)
