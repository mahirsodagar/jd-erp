"""Terms, consent, and the application PDF.

The consent tests are the important ones. A student who has already
agreed must come back to a form that says so — the previous behaviour
reset both checkboxes on every visit, which silently blocked "Save
changes" until they re-agreed to terms they had already accepted.
"""

import uuid
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.admissions.application_terms import DECLARATION_TEXT, terms_for
from apps.admissions.models import Student, StudentDocument
from apps.admissions.services import submit_application_from_lead
from apps.admissions.services_application_pdf import render_application_pdf
from apps.leads.models import Lead
from apps.master.models import (
    AcademicYear, Campus, Institute, LeadSource, Program,
)


class TermsBundleTests(TestCase):

    def test_known_institute_gets_its_own_payee_and_disclaimer(self):
        jdsd = terms_for("JDSD")
        self.assertEqual(jdsd["fee_recipient"], "JD EDUCATIONAL TRUST")
        self.assertIn("JD EDUCATIONAL TRUST", jdsd["rules"][0]["subs"][0])
        self.assertIsNotNone(jdsd["disclaimer"])
        # The institute-specific extra fee rule is spliced in before the
        # closing "failing to pay" line, not appended after it.
        subs = jdsd["rules"][0]["subs"]
        self.assertIn(
            "Examination fees for each semester are payable by the students.",
            subs,
        )
        self.assertTrue(subs[-1].startswith("Students failing to pay fees"))

    def test_jdift_has_no_disclaimer_and_its_own_payee(self):
        jdift = terms_for("JDIFT")
        self.assertIsNone(jdift["disclaimer"])
        self.assertEqual(
            jdift["fee_recipient"], "JD INSTITUTE OF FASHION TECHNOLOGY",
        )

    def test_an_unknown_institute_still_gets_usable_terms(self):
        """A newly-added institute must show generic terms, not a blank
        section — the form is unusable without rules to accept."""
        terms = terms_for("BRAND-NEW")
        self.assertEqual(terms["declaration"], DECLARATION_TEXT)
        self.assertGreater(len(terms["rules"]), 10)
        self.assertIsNone(terms["disclaimer"])

    def test_every_rule_has_the_same_shape(self):
        for rule in terms_for("JDSD")["rules"]:
            self.assertEqual(set(rule), {"text", "subs", "emphasis"})
            self.assertIsInstance(rule["subs"], list)

    def test_only_the_fees_rule_is_emphasised(self):
        rules = terms_for("JDSD")["rules"]
        self.assertTrue(rules[0]["emphasis"])
        self.assertEqual(rules[0]["text"], "Fees:")
        self.assertFalse(any(r["emphasis"] for r in rules[1:]))


class _LeadFixture(TestCase):
    """Shared setup for the public-form tests below."""

    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JD School of Design",
                                                 code="JDSD")
        cls.campus = Campus.objects.create(
            name="Main", code="MAIN",
        )
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.program.campuses.add(cls.campus)
        cls.year = AcademicYear.objects.create(
            code="2026-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31), is_current=True,
        )
        cls.source = LeadSource.objects.create(name="Website", slug="website")
        cls.lead = Lead.objects.create(
            name="Asha Rao", email="asha@example.com", phone="9000000000",
            campus=cls.campus, program=cls.program, source=cls.source,
            # submit_application_from_lead refuses a lead with no token —
            # the link is what authorises the submission.
            application_token=uuid.uuid4(),
        )

    def _payload(self, **overrides):
        base = {
            "student_name": "Asha Rao",
            "dob": "2006-01-01",
            "gender": "F",
            "student_mobile": "9000000000",
            "student_email": "asha@example.com",
            "documents": [],
        }
        base.update(overrides)
        return base


class ConsentTests(_LeadFixture):

    def test_consent_is_stamped_on_first_submit(self):
        student, _ = submit_application_from_lead(
            lead=self.lead,
            payload=self._payload(
                declaration_accepted=True, rules_accepted=True,
            ),
        )
        self.assertIsNotNone(student.declaration_accepted_at)
        self.assertIsNotNone(student.rules_accepted_at)

    def test_the_form_comes_back_pre_ticked(self):
        """The bug: re-opening a submitted form showed both boxes clear,
        so the student had to re-agree before they could save an edit."""
        submit_application_from_lead(
            lead=self.lead,
            payload=self._payload(
                declaration_accepted=True, rules_accepted=True,
            ),
        )
        body = self.client.get(
            reverse("public-application", args=[self.lead.application_token]),
        ).json()
        self.assertIsNotNone(body["student"]["declaration_accepted_at"])
        self.assertIsNotNone(body["student"]["rules_accepted_at"])

    def test_a_later_submit_cannot_un_agree(self):
        student, _ = submit_application_from_lead(
            lead=self.lead,
            payload=self._payload(
                declaration_accepted=True, rules_accepted=True,
            ),
        )
        first_stamp = student.declaration_accepted_at

        submit_application_from_lead(
            lead=self.lead,
            payload=self._payload(
                declaration_accepted=False, rules_accepted=False,
            ),
        )
        student.refresh_from_db()
        self.assertEqual(student.declaration_accepted_at, first_stamp)
        self.assertIsNotNone(student.rules_accepted_at)

    def test_a_second_yes_does_not_move_the_original_timestamp(self):
        student, _ = submit_application_from_lead(
            lead=self.lead,
            payload=self._payload(declaration_accepted=True),
        )
        first_stamp = student.declaration_accepted_at
        submit_application_from_lead(
            lead=self.lead,
            payload=self._payload(declaration_accepted=True),
        )
        student.refresh_from_db()
        self.assertEqual(student.declaration_accepted_at, first_stamp)

    def test_consent_not_given_stays_null(self):
        student, _ = submit_application_from_lead(
            lead=self.lead, payload=self._payload(),
        )
        self.assertIsNone(student.declaration_accepted_at)
        self.assertIsNone(student.rules_accepted_at)

    def test_multipart_string_booleans_are_understood(self):
        """Multipart sends "false" as a *string*, which is truthy in
        Python — a naive read would record consent nobody gave."""
        url = reverse("public-application", args=[self.lead.application_token])
        self.client.post(url, {
            "student_name": "Asha Rao", "dob": "2006-01-01", "gender": "F",
            "student_mobile": "9000000000",
            "student_email": "asha@example.com",
            "documents": "[]",
            "declaration_accepted": "false",
            "rules_accepted": "true",
        })
        student = Student.objects.get(lead_origin=self.lead)
        self.assertIsNone(student.declaration_accepted_at)
        self.assertIsNotNone(student.rules_accepted_at)


class PublicPrefillTermsTests(_LeadFixture):

    def test_the_prefill_carries_the_institutes_terms(self):
        body = self.client.get(
            reverse("public-application", args=[self.lead.application_token]),
        ).json()
        self.assertEqual(body["terms"]["declaration"], DECLARATION_TEXT)
        self.assertEqual(body["terms"]["fee_recipient"], "JD EDUCATIONAL TRUST")
        self.assertIsNotNone(body["terms"]["disclaimer"])


class ApplicationPdfTests(_LeadFixture):

    def setUp(self):
        self.student, _ = submit_application_from_lead(
            lead=self.lead,
            payload=self._payload(
                declaration_accepted=True,
                rules_accepted=True,
                father_name="Ramesh Rao",
                current_address="12 Residency Road, a deliberately long "
                                "address line that has to wrap in the PDF "
                                "without running off the page",
                documents=[{
                    "header": "SSLC",
                    "school_college": "St. Joseph's",
                    "university_board": "CBSE",
                    "percent_obtained": "88.50",
                }],
            ),
        )
        # Reload so the field types are what the DB gives back (`dob` a
        # date, not the ISO string the payload carried).
        self.student.refresh_from_db()
        self.user = get_user_model().objects.create_user(
            username="asha", email="asha@example.com", password="pw",
        )
        self.student.user_account = self.user
        self.student.save(update_fields=["user_account"])

        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

    def test_renders_a_pdf(self):
        pdf = render_application_pdf(self.student)
        self.assertTrue(pdf.startswith(b"%PDF"))
        # A one-page render would mean the terms page never got drawn.
        self.assertGreater(len(pdf), 5000)

    def test_renders_for_an_institute_with_no_disclaimer(self):
        self.institute.code = "JDIFT"
        self.institute.save(update_fields=["code"])
        self.student.refresh_from_db()
        self.assertTrue(render_application_pdf(self.student).startswith(b"%PDF"))

    def test_renders_without_consent_or_documents(self):
        self.student.declaration_accepted_at = None
        self.student.rules_accepted_at = None
        self.student.save(update_fields=[
            "declaration_accepted_at", "rules_accepted_at",
        ])
        StudentDocument.objects.filter(student=self.student).delete()
        self.assertTrue(render_application_pdf(self.student).startswith(b"%PDF"))

    def test_portal_serves_it_as_a_pdf_attachment(self):
        r = self.api.get(reverse("portal-application-pdf"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn(self.student.application_form_id, r["Content-Disposition"])
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_portal_payload_carries_terms_and_consent(self):
        body = self.api.get(reverse("portal-application")).json()
        self.assertEqual(body["terms"]["declaration"], DECLARATION_TEXT)
        self.assertIsNotNone(body["consent"]["declaration_accepted_at"])
        self.assertIsNotNone(body["consent"]["rules_accepted_at"])

    def test_the_pdf_needs_authentication(self):
        self.assertEqual(
            APIClient().get(reverse("portal-application-pdf")).status_code, 401,
        )

    def test_another_students_pdf_is_not_reachable(self):
        """The endpoint takes no id — it always renders the caller's own
        form — so an outsider gets a 403, not someone else's record."""
        outsider = get_user_model().objects.create_user(
            username="nobody", email="nobody@example.com", password="pw",
        )
        api = APIClient()
        api.force_authenticate(user=outsider)
        self.assertEqual(
            api.get(reverse("portal-application-pdf")).status_code, 403,
        )


class ConsentStampTimeTests(_LeadFixture):

    def test_the_stamp_is_a_real_timestamp(self):
        before = timezone.now()
        student, _ = submit_application_from_lead(
            lead=self.lead,
            payload=self._payload(rules_accepted=True),
        )
        self.assertGreaterEqual(student.rules_accepted_at, before)
        self.assertLessEqual(student.rules_accepted_at, timezone.now())
