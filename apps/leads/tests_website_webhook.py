"""Website (Forminator) webhook — port of legacy webhooks/webhook.php.

Payloads below are trimmed copies of real rows from the legacy log.txt.
"""

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.leads.models import Lead, WebsiteLeadEvent, WebsiteValueMap
from apps.leads.website_webhook import normalise
from apps.master.models import Campus, Institute, LeadSource, Program

KEY = "test-webhook-key"
URL = "/api/public/website-lead/"


@override_settings(LEAD_INTAKE_API_KEY=KEY)
class WebsiteWebhookTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.blr = Campus.objects.create(name="Bangalore", code="BLR")
        cls.goa = Campus.objects.create(name="Goa", code="GOA")
        cls.dip_fd = Program.objects.create(
            name="Diploma in Fashion Design", code="DIPFD", institute=inst)
        cls.bdes_fd = Program.objects.create(
            name="B.des in Fashion Design", code="BDESFD", institute=inst)
        cls.website = LeadSource.objects.create(name="JDI Website", slug="jdi-website")
        cls.brochure = LeadSource.objects.create(
            name="JDI Brochure Download", slug="jdi-brochure-download")

        M = WebsiteValueMap
        M.objects.create(kind="campus", website_value="bangalore", campus=cls.blr)
        M.objects.create(kind="campus", website_value="goa", campus=cls.goa)
        M.objects.create(kind="campus", website_value="*", campus=cls.blr)
        M.objects.create(kind="program", website_value="fashion designing courses",
                         program=cls.dip_fd)
        M.objects.create(kind="program", website_value="*", program=cls.dip_fd)
        M.objects.create(kind="source", website_value="download brochure popup",
                         source=cls.brochure)
        M.objects.create(kind="source", website_value="course pages form",
                         source=cls.website)
        M.objects.create(kind="source", website_value="*", source=cls.website)

    def setUp(self):
        self.client = APIClient()

    def post(self, payload, key=KEY, **kw):
        return self.client.post(URL + (f"?key={key}" if key else ""),
                                payload, format="json", **kw)

    # -- auth ---------------------------------------------------------------

    def test_rejects_missing_or_wrong_key(self):
        self.assertEqual(self.post({"name_1": "x"}, key=None).status_code, 403)
        self.assertEqual(self.post({"name_1": "x"}, key="nope").status_code, 403)
        self.assertEqual(WebsiteLeadEvent.objects.count(), 0)

    def test_accepts_header_key(self):
        r = self.client.post(URL, {"name_1": "A", "phone_1": "9999999999",
                                   "email_1": "a@x.com"},
                             format="json", HTTP_X_API_KEY=KEY)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["ok"])

    # -- mapping ------------------------------------------------------------

    def test_real_brochure_payload_creates_mapped_lead(self):
        r = self.post({
            "name_1": "Thushaara", "email_1": "thushaara@gmail.com",
            "select_1": "Bangalore", "select_3": "Fashion-Designing-Courses",
            "select_4": "Course-Information", "phone_1": "96067 04123",
            "hidden_1": "google", "hidden_2": "cpc", "hidden_3": "brochure_oct",
            "hidden_8": "36", "current_url": "https://www.jdinstitute.edu.in/course-pricing/",
            "form_title": "Download Brochure - Popup",
        })
        self.assertEqual(r.status_code, 200, r.data)
        lead = Lead.objects.get(pk=r.data["lead_id"])
        self.assertEqual(lead.phone, "9606704123")
        self.assertEqual(lead.campus, self.blr)
        self.assertEqual(lead.program, self.dip_fd)
        self.assertEqual(lead.source, self.brochure)
        self.assertIsNone(lead.created_by)
        self.assertEqual(lead.utm.utm_source, "google")
        self.assertEqual(lead.utm.utm_campaign, "brochure_oct")
        self.assertIn("Download Brochure - Popup", lead.remarks)
        self.assertIn("Fashion-Designing-Courses", lead.remarks)
        self.assertEqual(r.data["warnings"], [])
        ev = WebsiteLeadEvent.objects.get()
        self.assertEqual(ev.status, "created")
        self.assertEqual(ev.lead, lead)
        self.assertEqual(ev.payload["hidden_8"], "36")

    def test_full_course_name_matches_program_without_map_row(self):
        r = self.post({
            "name_1": "H", "phone_1": "9000000001", "email_1": "h@x.com",
            "select_1": "Hyderabad", "select_6": "B.des in Fashion Design - 4 Years",
            "form_title": "Admissions - Hyderabad",
        })
        lead = Lead.objects.get(pk=r.data["lead_id"])
        self.assertEqual(lead.program, self.bdes_fd)
        # Hyderabad campus has no map row → fallback BLR, and it is flagged.
        self.assertEqual(lead.campus, self.blr)
        self.assertEqual(lead.source, self.website)
        self.assertTrue(any("campus" in w for w in r.data["warnings"]))
        self.assertIn("Campus chosen: Hyderabad", lead.remarks)
        self.assertEqual(WebsiteLeadEvent.objects.get().warnings, r.data["warnings"])

    def test_goa_enquiry_type_in_select_4_is_not_treated_as_course(self):
        r = self.post({
            "name_1": "G", "phone_1": "9000000002", "email_1": "g@x.com",
            "select_1": "Goa", "select_3": "Fashion Designing Courses",
            "select_4": "Student-Inquiry", "form_title": "Course pages - Form",
        })
        lead = Lead.objects.get(pk=r.data["lead_id"])
        self.assertEqual(lead.campus, self.goa)
        self.assertEqual(lead.program, self.dip_fd)
        self.assertEqual(r.data["warnings"], [])

    def test_placeholder_values_fall_back_and_lead_is_still_created(self):
        r = self.post({
            "name_1": "P", "phone_1": "9000000003", "email_1": "",
            "select_1": "one", "select_3": "Select Course",
            "form_title": "Walkin - QR code",
        })
        self.assertTrue(r.data["ok"], r.data)
        lead = Lead.objects.get(pk=r.data["lead_id"])
        self.assertEqual(lead.campus, self.blr)
        self.assertEqual(lead.program, self.dip_fd)
        self.assertEqual(len(r.data["warnings"]), 3)  # campus, course, form

    # -- dedupe + failure handling -----------------------------------------

    def test_repeat_submission_is_flagged_duplicate(self):
        base = {"name_1": "D", "phone_1": "9000000004", "email_1": "d@x.com",
                "select_1": "Bangalore", "select_3": "Fashion Designing Courses",
                "form_title": "Apply Online"}
        first = self.post(base)
        second = self.post({**base, "form_title": "Course Pricing Reveal"})
        self.assertFalse(first.data["is_repeated"])
        self.assertTrue(second.data["is_repeated"])
        dup = Lead.objects.get(pk=second.data["lead_id"])
        self.assertEqual(dup.duplicate_of_id, first.data["lead_id"])
        self.assertEqual(
            WebsiteLeadEvent.objects.get(lead=dup).status, "duplicate")

    def test_non_lead_payload_is_recorded_not_lost(self):
        r = self.post({"email": "india2@gmail.com"})   # legacy log1.txt shape
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["ok"])
        ev = WebsiteLeadEvent.objects.get()
        self.assertEqual(ev.status, "failed")
        self.assertIn("name_1", ev.error)
        self.assertEqual(Lead.objects.count(), 0)

    def test_missing_fallback_row_fails_safely(self):
        WebsiteValueMap.objects.filter(kind="program").delete()
        r = self.post({"name_1": "F", "phone_1": "9000000005", "email_1": "f@x.com",
                       "select_1": "Bangalore", "select_3": "Hair-and-Makeup-Courses",
                       "form_title": "Apply Online"})
        self.assertFalse(r.data["ok"])
        self.assertIn("seed_website_maps", WebsiteLeadEvent.objects.get().error)
        self.assertEqual(Lead.objects.count(), 0)

    # -- helper ------------------------------------------------------------

    def test_normalise(self):
        self.assertEqual(normalise("Fashion-Designing-Courses"), "fashion designing courses")
        self.assertEqual(normalise("B.des in Fashion Design - 4 Years"), "b.des in fashion design")
        self.assertEqual(normalise("Certificate Program in Fashion Styling - 3 months"),
                         "certificate program in fashion styling")
        self.assertEqual(normalise("MA in UI/UX"), "ma in ui ux")
        self.assertEqual(normalise("Diploma in Fine Jewellery Design\t1 Year"),
                         "diploma in fine jewellery design")
        self.assertEqual(normalise("Certificate Program in Fashion Photography - 6 weeks"),
                         "certificate program in fashion photography")
        self.assertEqual(normalise(None), "")
