"""Email → lead intake: parsers, mapping, dedupe window, fetcher, API.

Fixtures are anonymised copies of real mails from leads@jdinstitute.edu.in
(layouts verbatim, names/contacts replaced).
"""

from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.leads import mail_fetch, mail_parsers as mp
from apps.leads.mail_intake import process_email
from apps.leads.models import (
    InboundLeadEmail, Lead, LeadMailRule, LeadMailSyncState, WebsiteValueMap,
)
from apps.master.models import Campus, Institute, LeadSource, Program
from apps.roles.models import Permission, Role

WEBSITE_HTML = """
<html><body><p>You have a new website form submission:</p>
<table>
<tr><td><b>Name</b></td></tr><tr><td>Asha Rao</td></tr>
<tr><td><b>Email Address</b></td></tr><tr><td>asha@example.com</td></tr>
<tr><td><b>Date of Birth</b></td></tr><tr><td>19-09-2006</td></tr>
<tr><td><b>Educational Qualification</b></td></tr><tr><td>PUC</td></tr>
<tr><td><b>Select</b></td></tr><tr><td>Bangalore</td></tr>
<tr><td><b>Select</b></td></tr><tr><td>Web Search</td></tr>
<tr><td><b>Phone</b></td></tr><tr><td>99001 12233</td></tr>
<tr><td><b>Alternate Number</b></td></tr>
<tr><td><b>Select</b></td></tr><tr><td>B.des in Fashion Design - 4 Years</td></tr>
<tr><td><b>utm_source</b></td></tr><tr><td><b>utm_medium</b></td></tr>
<tr><td><b>source</b></td></tr><tr><td>21</td></tr>
<tr><td><b>IP</b></td></tr><tr><td>1.2.3.4</td></tr>
<tr><td><b>URL</b></td></tr><tr><td>https://www.jdinstitute.edu.in/apply-online/</td></tr>
</table><p>---</p><p>Sent from https://www.jdinstitute.edu.in .</p>
<p>DISCLAIMER : This email and any files ... Phone 0000000000</p>
</body></html>
"""

WEBSITE_PLAIN = """Full Name
-------------------------
Ravi Kumar
Email Address
-------------------------
ravi@example.com
Phone Number
-------------------------
+91-98765 43210
Alternate Number
-------------------------
8296219348
Date of Birth
-------------------------
11/30/2001
Educational Qualification
-------------------------
PUC
Select Campus
-------------------------
Goa
Course of Interest
-------------------------
Diploma in Fashion Design – 1 Year
 How did you first hear about JD Institute?
-------------------------
Others
Others
-------------------------
Cousin studied here
--
----------------------------------------------------------------------------------------------------------------------------
"""

LANDING_HTML = """
<table><tr><th>NAME</th></tr><tr><td>Zaman</td></tr>
<tr><th>PHONE NO.</th></tr><tr><td>7902552490</td></tr>
<tr><th>PHONE NO. 2</th></tr><tr><td>7902552490</td></tr>
<tr><th>EMAIL ID</th></tr><tr><td>zaman@example.com</td></tr>
<tr><th>CENTER</th></tr><tr><td>Bengaluru</td></tr>
<tr><th>COURSE</th></tr><tr><td>Advanced Diploma in Interior Design</td></tr></table>
"""

TAWK_PLAIN = """Missed chat from www.jdinstitute.edu.in
 Need help answering chats? Get help here https://www.tawk.to/services/hire-chat-agents/
========================================================================
Conversation started on : Sunday, April 16, 2023, at 05:11 (GMT+0)
 [05:11] Customer Support: Welcome To Our Site
For Any Assistance, Click Here
 [05:14] Harshita S: Name : Harshita S
Phone : 9612661330
Email : harshita@example.com
Question : I want to do interior design in Hyderabad.
Can I join from January?
 Missed chats = Missed Opportunities. Hire Chat Agents ($1/hour). https://www.tawk.to/services/hire-chat-agents/
"""

TAWK_OFFLINE = """Offline message sent by Pournika
=======================================================================
Offline message sent on Monday, July 08, 2024, at 07:39 (GMT+0)

Site : www.jdinstitute.edu.in
Submitted from : https://www.jdinstitute.edu.in/diploma-in-interior-design-1-year/
Name : Pournika
Phone : 9848566627
Email : pournika@example.com
Message : May I know the fee structure of Diploma in Interior Design(1 year) in Hyderabad
"""

JDSD_BROCHURE_HTML = """
<p>You have a Brochure download below are the form submission:</p>
<p>Name</p><p>Sahana B</p>
<p>Email Address</p><p>sahana@example.com</p>
<p>Phone Number</p><p>07204233502</p>
<p>Intrested Course</p><p>Jewellery Design Course</p>
<p>Preferred Centre</p><p>Bengaluru</p>
<p>utm_source</p><p>utm_medium</p><p>gclid</p>
<p>URL</p><p>https://www.jdsd.in/bsc-in-fashion-and-apparel-design/</p>
<p>IP</p><p>106.216.179.105</p>
<p>source</p><p>27</p>
<p>---</p><p>This message was sent from https://www.jdsd.in .</p>
"""

CONTACT_HTML = """
<p>You have a new website form submission:</p>
<p>Name</p><p>Amaal R</p>
<p>Email Address</p><p>amaal@example.com</p>
<p>Phone</p><p>099619 88958</p>
<p>Select Campus</p><p>Kochi</p>
<p>Message</p><p>Wanted to know the course fees and duration</p>
<p>utm_source</p><p>utm_medium</p>
<p>source</p><p>5</p>
<p>URL</p><p>https://www.jdinstitute.edu.in/contact/</p>
"""

PORTAL_PLAIN = """Dear Partner,

You have received a new lead from Shiksha.

Student Name: Meera Nair
Mobile Number: +91 9876501234
Email ID: meera@example.com
Course Interested: Diploma in Fashion Design
Preferred City: Kochi
Message: Looking for weekend batch

Regards,
Shiksha Team
"""


class ParserTests(TestCase):
    def test_website_html_select_classified_by_content(self):
        parser, out = mp.parse("auto", from_address="webmaster@jdinstitute.edu.in",
                               subject="JD INSTITUTE - ADMISSIONS OPEN - ALL COURSE PAGES - application number #9 for",
                               text_body="", html_body=WEBSITE_HTML)
        self.assertEqual(parser, "website")
        self.assertTrue(out["ok"])
        self.assertEqual(out["name"], "Asha Rao")
        self.assertEqual(out["email"], "asha@example.com")
        self.assertEqual(out["phone"], "99001 12233")
        self.assertEqual(out["alt_phone"], "")
        self.assertEqual(out["campus_raw"], "Bangalore")
        self.assertEqual(out["how_known"], "Web Search")
        self.assertEqual(out["course_raw"], "B.des in Fashion Design - 4 Years")
        self.assertEqual(out["source_raw"], "21")
        self.assertEqual(out["form_title"], "ADMISSIONS OPEN - ALL COURSE PAGES")
        self.assertEqual(out["page_url"], "https://www.jdinstitute.edu.in/apply-online/")

    def test_website_plain_dashes_layout(self):
        parser, out = mp.parse("auto", from_address="webmaster@jdinstitute.edu.in",
                               subject="New Enquiry Apply Online South",
                               text_body=WEBSITE_PLAIN, html_body="")
        self.assertEqual(parser, "website")
        self.assertEqual(out["name"], "Ravi Kumar")
        self.assertEqual(out["phone"], "+91-98765 43210")
        self.assertEqual(out["alt_phone"], "8296219348")
        self.assertEqual(out["campus_raw"], "Goa")
        self.assertEqual(out["course_raw"], "Diploma in Fashion Design – 1 Year")
        self.assertEqual(out["how_known"], "Cousin studied here")
        self.assertEqual(out["form_title"], "Apply Online South")

    def test_landing_page_uppercase_labels(self):
        _, out = mp.parse("website", from_address="webmaster@jdinstitute.edu.in",
                          subject="New Enquiry ADMISSIONS OPEN - Landing Page",
                          text_body="", html_body=LANDING_HTML)
        self.assertEqual(out["name"], "Zaman")
        self.assertEqual(out["phone"], "7902552490")
        self.assertEqual(out["alt_phone"], "7902552490")
        self.assertEqual(out["email"], "zaman@example.com")
        self.assertEqual(out["campus_raw"], "Bengaluru")
        self.assertEqual(out["course_raw"], "Advanced Diploma in Interior Design")

    def test_jdsd_brochure_download_layout(self):
        parser, out = mp.parse("auto", from_address="webmaster@jdinstitute.edu.in",
                               subject="Course page Brochure Downloads #2449",
                               text_body="", html_body=JDSD_BROCHURE_HTML)
        self.assertEqual(parser, "website")
        self.assertEqual(out["name"], "Sahana B")
        self.assertEqual(out["phone"], "07204233502")
        self.assertEqual(out["course_raw"], "Jewellery Design Course")
        self.assertEqual(out["campus_raw"], "Bengaluru")
        self.assertEqual(out["form_title"], "Course page Brochure Downloads")
        self.assertIn("jdsd.in", out["page_url"])

    def test_contact_form_layout_and_title(self):
        _, out = mp.parse("auto", from_address="webmaster@jdinstitute.edu.in",
                          subject="New Form Entry #9285 for contact us",
                          text_body="", html_body=CONTACT_HTML)
        self.assertEqual(out["name"], "Amaal R")
        self.assertEqual(out["campus_raw"], "Kochi")
        self.assertEqual(out["message"], "Wanted to know the course fees and duration")
        self.assertEqual(out["form_title"], "contact us")
        self.assertEqual(mp.course_slug(out["page_url"]), "")   # /contact/ is not a course

    def test_tawk_missed_chat(self):
        parser, out = mp.parse("auto", from_address="noreply@jd-institute-south.p.tawk.email",
                               subject="Missed chat on www.jdinstitute.edu.in at Sunday",
                               text_body=TAWK_PLAIN, html_body="")
        self.assertEqual(parser, "tawk")
        self.assertEqual(out["name"], "Harshita S")
        self.assertEqual(out["phone"], "9612661330")
        self.assertEqual(out["email"], "harshita@example.com")
        self.assertIn("Can I join from January?", out["message"])
        self.assertNotIn("Missed chats", out["message"])
        self.assertEqual(out["campus_raw"], "Hyderabad")

    def test_tawk_offline_message_uses_page_for_course(self):
        _, out = mp.parse("auto", from_address="noreply@x.tawk.email",
                          subject="Offline message sent by Pournika",
                          text_body=TAWK_OFFLINE, html_body="")
        self.assertEqual(out["course_raw"], "diploma in interior design 1 year")
        self.assertEqual(out["campus_raw"], "Hyderabad")
        self.assertTrue(out["page_url"].endswith("/diploma-in-interior-design-1-year/"))

    def test_generic_portal_mail(self):
        parser, out = mp.parse("auto", from_address="leads@shiksha.com",
                               subject="New lead for JD Institute",
                               text_body=PORTAL_PLAIN, html_body="")
        self.assertEqual(parser, "generic")
        self.assertTrue(out["ok"])
        self.assertEqual(out["name"], "Meera Nair")
        self.assertEqual(out["phone"], "+91 9876501234")
        self.assertEqual(out["email"], "meera@example.com")
        self.assertEqual(out["course_raw"], "Diploma in Fashion Design")
        self.assertEqual(out["campus_raw"], "Kochi")
        self.assertEqual(out["message"], "Looking for weekend batch")

    def test_generic_falls_back_to_regex_contacts(self):
        _, out = mp.parse("generic", from_address="x@y.com", subject="s",
                          text_body="Name: Kiran\nReach me on 9900011122 or kiran@example.com",
                          html_body="")
        self.assertEqual(out["name"], "Kiran")
        self.assertEqual(out["phone"], "9900011122")
        self.assertEqual(out["email"], "kiran@example.com")

    def test_not_a_lead(self):
        _, out = mp.parse("auto", from_address="no-reply@accounts.google.com",
                          subject="Security alert", text_body="A new sign-in on Mac.",
                          html_body="")
        self.assertFalse(out["ok"])


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.blr = Campus.objects.create(name="Bangalore", code="BLR")
        cls.hyd = Campus.objects.create(name="Hyderabad", code="HYD")
        cls.dip_fd = Program.objects.create(name="Diploma in Fashion Design", code="DIPFD", institute=inst)
        cls.bdes = Program.objects.create(name="B.des in Fashion Design", code="BDESFD", institute=inst)
        cls.dip_id = Program.objects.create(name="Diploma in Interior Design", code="DIPID", institute=inst)
        for p in (cls.dip_fd, cls.bdes, cls.dip_id):
            p.campuses.add(cls.blr, cls.hyd)
        cls.website = LeadSource.objects.create(name="JDI Website", slug="jdi-website")
        cls.chatbot = LeadSource.objects.create(name="Chatbot", slug="chatbot")
        cls.shiksha = LeadSource.objects.create(name="Shiksha", slug="shiksha")
        M = WebsiteValueMap
        M.objects.create(kind="campus", website_value="bangalore", campus=cls.blr)
        M.objects.create(kind="campus", website_value="hyderabad", campus=cls.hyd)
        M.objects.create(kind="campus", website_value="*", campus=cls.blr)
        M.objects.create(kind="program", website_value="*", program=cls.dip_fd)
        M.objects.create(kind="source", website_value="*", source=cls.website)
        LeadMailRule.objects.create(name="web", match_from="webmaster@", parser="website", priority=10)
        LeadMailRule.objects.create(name="tawk", match_from="tawk.email", parser="tawk",
                                    source=cls.chatbot, priority=20)
        LeadMailRule.objects.create(name="google", match_from="accounts.google.com",
                                    parser="ignore", priority=1)
        LeadMailRule.objects.create(name="shiksha", match_from="shiksha.com", parser="generic",
                                    source=cls.shiksha, default_campus=cls.hyd, priority=30)

    def mail(self, *, frm, subject, text="", html="", uid=None, sent=None):
        return InboundLeadEmail.objects.create(
            mailbox="leads@test", uid=uid or InboundLeadEmail.objects.count() + 1,
            uidvalidity=1, from_address=frm, subject=subject, text_body=text,
            html_body=html, sent_at=sent or timezone.now())


class IntakeTests(_Base):
    def test_website_mail_creates_lead_with_mapping(self):
        row = self.mail(frm="webmaster@jdinstitute.edu.in",
                        subject="JD INSTITUTE - ADMISSIONS OPEN - ALL COURSE PAGES - application number #9 for",
                        html=WEBSITE_HTML)
        process_email(row)
        self.assertEqual(row.status, "created", row.error)
        lead = row.lead
        self.assertEqual(lead.name, "Asha Rao")
        self.assertEqual(lead.campus, self.blr)
        self.assertEqual(lead.program, self.bdes)      # exact Program name after dropping "- 4 Years"
        self.assertEqual(lead.source, self.website)    # '*' source map
        self.assertIn("How did you know: Web Search", lead.remarks)
        self.assertEqual(lead.utm.utm_content, "ADMISSIONS OPEN - ALL COURSE PAGES")

    def test_jdsd_page_picks_jdsd_source(self):
        jdsd = LeadSource.objects.create(name="JDSD Brochure Download",
                                         slug="jdsd-brochure-download")
        row = self.mail(frm="webmaster@jdinstitute.edu.in",
                        subject="Course page Brochure Downloads #2449", html=JDSD_BROCHURE_HTML)
        process_email(row)
        self.assertEqual(row.status, "created", row.error)
        self.assertEqual(row.lead.source, jdsd)
        self.assertEqual(row.lead.campus, self.blr)   # "Bengaluru" unmapped here → '*' row
        self.assertEqual(row.lead.program, self.dip_fd)  # unmapped course → '*' row

    def test_contact_page_slug_not_used_as_course(self):
        row = self.mail(frm="webmaster@jdinstitute.edu.in",
                        subject="New Form Entry #9285 for contact us", html=CONTACT_HTML)
        process_email(row)
        self.assertEqual(row.status, "created", row.error)
        self.assertFalse(any("'contact'" in w for w in row.warnings), row.warnings)
        self.assertIn("Message: Wanted to know", row.lead.remarks)

    def test_tawk_mail_uses_rule_source_and_sniffed_campus(self):
        row = self.mail(frm="noreply@jd-institute-south.p.tawk.email",
                        subject="Offline message sent by Pournika", text=TAWK_OFFLINE)
        process_email(row)
        self.assertEqual(row.status, "created", row.error)
        self.assertEqual(row.lead.source, self.chatbot)
        self.assertEqual(row.lead.campus, self.hyd)
        self.assertEqual(row.lead.program, self.dip_id)   # from the page slug
        self.assertIn("fee structure", row.lead.remarks)

    def test_rule_default_campus_when_mail_names_unknown_city(self):
        row = self.mail(frm="leads@shiksha.com", subject="New lead", text=PORTAL_PLAIN)
        process_email(row)
        self.assertEqual(row.status, "created", row.error)
        self.assertEqual(row.lead.source, self.shiksha)
        self.assertEqual(row.lead.campus, self.hyd)       # Kochi unmapped → rule default
        self.assertTrue(any("rule default" in w for w in row.warnings))

    def test_ignore_rule(self):
        row = self.mail(frm="no-reply@accounts.google.com", subject="Security alert",
                        text="New sign-in")
        process_email(row)
        self.assertEqual(row.status, "ignored")
        self.assertIsNone(row.lead)

    def test_unparsed_when_nothing_usable(self):
        row = self.mail(frm="someone@gmail.com", subject="hello", text="just saying hi")
        process_email(row)
        self.assertEqual(row.status, "unparsed")
        self.assertEqual(Lead.objects.count(), 0)

    def test_already_in_erp_within_window(self):
        Lead.objects.create(name="Asha Rao", email="asha@example.com", phone="9900112233",
                            phone_normalized="9900112233", campus=self.blr,
                            program=self.bdes, source=self.website)
        row = self.mail(frm="webmaster@jdinstitute.edu.in",
                        subject="JD INSTITUTE - Apply Online - application number #1 for",
                        html=WEBSITE_HTML)
        process_email(row)
        self.assertEqual(row.status, "already")
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(row.lead, Lead.objects.get())

    def test_repeat_when_older_lead_exists(self):
        old = Lead.objects.create(name="Asha Rao", email="asha@example.com", phone="9900112233",
                                  phone_normalized="9900112233", campus=self.blr,
                                  program=self.bdes, source=self.website)
        Lead.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=3))
        row = self.mail(frm="webmaster@jdinstitute.edu.in",
                        subject="JD INSTITUTE - Apply Online - application number #1 for",
                        html=WEBSITE_HTML)
        process_email(row)
        self.assertEqual(row.status, "repeat")
        self.assertEqual(Lead.objects.count(), 2)
        self.assertTrue(row.lead.is_repeated)
        self.assertEqual(row.lead.duplicate_of, old)

    @override_settings(LEAD_MAIL_DUP_WINDOW_HOURS=0)
    def test_window_zero_disables_already(self):
        Lead.objects.create(name="Asha Rao", email="asha@example.com", phone="9900112233",
                            phone_normalized="9900112233", campus=self.blr,
                            program=self.bdes, source=self.website)
        row = self.mail(frm="webmaster@jdinstitute.edu.in",
                        subject="JD INSTITUTE - Apply Online - application number #1 for",
                        html=WEBSITE_HTML)
        process_email(row)
        self.assertEqual(row.status, "repeat")

    def test_process_is_idempotent(self):
        row = self.mail(frm="webmaster@jdinstitute.edu.in",
                        subject="New Enquiry ADMISSIONS OPEN - Landing Page", html=LANDING_HTML)
        process_email(row)
        process_email(row)
        process_email(row, force=True)
        self.assertEqual(Lead.objects.count(), 1)


# --- fetcher with a fake IMAP server ----------------------------------------

RAW_MAIL = (
    b"From: JD Institute <webmaster@jdinstitute.edu.in>\r\n"
    b"To: leads@test\r\n"
    b"Subject: New Enquiry ADMISSIONS OPEN - Landing Page\r\n"
    b"Date: Fri, 17 Apr 2026 05:58:29 +0000\r\n"
    b"Message-ID: <m%d@jd>\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n\r\n"
)


class FakeIMAP:
    """Just enough of imaplib for mail_fetch: UID SEARCH / UID FETCH."""

    uids: list[int] = []
    bodies: dict[int, bytes] = {}
    uidvalidity = 777

    def __init__(self, host, port):
        self.logged = False

    def login(self, u, p):
        self.logged = True

    def select(self, folder, readonly=False):
        return "OK", [b"5"]

    def response(self, code):
        return "OK", [str(self.uidvalidity).encode()]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            query = args[1]
            if query == "ALL":
                hits = self.uids
            elif query.startswith("UID "):
                lo = int(query[4:].split(":")[0])
                hits = [u for u in self.uids if u >= lo]
            else:
                hits = self.uids
            return "OK", [" ".join(str(u) for u in hits).encode()]
        if cmd == "FETCH":
            wanted = [int(x) for x in args[0].split(",")]
            out = []
            for u in wanted:
                if u in self.bodies:
                    out.append((f"{u} (UID {u} BODY[] {{{len(self.bodies[u])}}}".encode(),
                                self.bodies[u]))
                    out.append(b")")
            return "OK", out
        return "NO", []

    def logout(self):
        pass


@override_settings(LEAD_MAIL_IMAP_HOST="imap.test", LEAD_MAIL_IMAP_USER="leads@test",
                   LEAD_MAIL_IMAP_PASSWORD="pw")
class FetchTests(_Base):
    def setUp(self):
        FakeIMAP.uids = [10, 11, 12]
        FakeIMAP.bodies = {u: (RAW_MAIL % u) + LANDING_HTML.encode() for u in FakeIMAP.uids}
        self.patch = mock.patch.object(mail_fetch.imaplib, "IMAP4_SSL", FakeIMAP)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_first_run_parks_cursor(self):
        res = mail_fetch.fetch_new()
        self.assertEqual(res.fetched, 0)
        self.assertEqual(res.parked_at, 12)
        state = LeadMailSyncState.objects.get(mailbox="leads@test")
        self.assertEqual(state.last_uid, 12)
        self.assertEqual(state.uidvalidity, 777)
        self.assertEqual(state.last_error, "")
        self.assertIsNotNone(state.last_success_at)

    def test_second_run_reads_only_newer_and_creates(self):
        mail_fetch.fetch_new()
        FakeIMAP.uids = [10, 11, 12, 13, 14]
        FakeIMAP.bodies[13] = (RAW_MAIL % 13) + LANDING_HTML.encode()
        FakeIMAP.bodies[14] = (RAW_MAIL % 14) + LANDING_HTML.replace(
            "7902552490", "7000000001").encode()
        res = mail_fetch.fetch_new()
        self.assertEqual(res.fetched, 2)
        self.assertEqual(res.created, 1)
        self.assertEqual(res.already, 1)     # same person twice within the window
        self.assertEqual(InboundLeadEmail.objects.count(), 2)
        self.assertEqual(LeadMailSyncState.objects.get().last_uid, 14)
        row = InboundLeadEmail.objects.get(uid=13)
        self.assertEqual(row.from_address, "webmaster@jdinstitute.edu.in")
        self.assertEqual(row.subject, "New Enquiry ADMISSIONS OPEN - Landing Page")
        self.assertEqual(row.message_id, "<m13@jd>")
        self.assertEqual(row.sent_at.year, 2026)

    def test_backfill_reads_everything_once(self):
        res = mail_fetch.fetch_new(backfill_days=3650)
        self.assertEqual(res.fetched, 3)
        res = mail_fetch.fetch_new(backfill_days=3650)
        self.assertEqual(res.fetched, 0)
        self.assertEqual(res.skipped_existing, 3)

    def test_uidvalidity_change_resets_cursor(self):
        mail_fetch.fetch_new()
        FakeIMAP.uidvalidity = 778
        FakeIMAP.uids = [1, 2]
        FakeIMAP.bodies = {u: (RAW_MAIL % u) + LANDING_HTML.encode() for u in FakeIMAP.uids}
        try:
            res = mail_fetch.fetch_new()
        finally:
            FakeIMAP.uidvalidity = 777
        self.assertEqual(res.fetched, 0)
        self.assertEqual(res.parked_at, 2)
        self.assertTrue(any("UIDVALIDITY" in m for m in res.messages))

    def test_login_failure_recorded(self):
        def boom(*a, **k):
            raise mail_fetch.imaplib.IMAP4.error("AUTHENTICATIONFAILED")
        with mock.patch.object(FakeIMAP, "login", boom):
            res = mail_fetch.fetch_new()
        self.assertIn("AUTHENTICATIONFAILED", res.error)
        self.assertIn("AUTHENTICATIONFAILED", LeadMailSyncState.objects.get().last_error)

    @override_settings(LEAD_MAIL_IMAP_PASSWORD="")
    def test_unconfigured_raises(self):
        with self.assertRaises(mail_fetch.MailConfigError):
            mail_fetch.fetch_new()


# --- API --------------------------------------------------------------------

class ApiTests(_Base):
    def setUp(self):
        self.client = APIClient()
        self.viewer = self._user("viewer", ["leads.mail.view"])
        self.manager = self._user("manager", ["leads.mail.view", "leads.mail.manage"])
        self.nobody = self._user("nobody", [])

    def _user(self, name, keys):
        u = User.objects.create_user(username=name, email=f"{name}@test.in", password="x")
        role = Role.objects.create(name=f"r-{name}")
        for k in keys:
            perm, _ = Permission.objects.get_or_create(
                key=k, defaults={"module": "leads", "label": k})
            role.permissions.add(perm)
        u.roles.add(role)
        return u

    def test_list_requires_view_perm(self):
        self.client.force_authenticate(self.nobody)
        self.assertEqual(self.client.get("/api/leads/mail/").status_code, 403)
        self.client.force_authenticate(self.viewer)
        r = self.client.get("/api/leads/mail/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("results", r.data)

    def test_summary(self):
        row = self.mail(frm="x@y.com", subject="hi", text="hi")
        process_email(row)
        self.client.force_authenticate(self.viewer)
        r = self.client.get("/api/leads/mail/summary/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["counts"]["unparsed"], 1)
        self.assertEqual(r.data["needs_attention"], 1)

    def test_manual_create_from_unparsed(self):
        row = self.mail(frm="x@y.com", subject="hi", text="hi")
        process_email(row)
        self.client.force_authenticate(self.viewer)
        r = self.client.post(f"/api/leads/mail/{row.pk}/create/", {}, format="json")
        self.assertEqual(r.status_code, 403)
        self.client.force_authenticate(self.manager)
        r = self.client.post(f"/api/leads/mail/{row.pk}/create/", {
            "name": "By Hand", "phone": "9000000001", "campus": self.blr.pk,
            "program": self.dip_fd.pk, "source": self.website.pk,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        row.refresh_from_db()
        self.assertEqual(row.status, "manual")
        self.assertEqual(row.lead.name, "By Hand")
        self.assertEqual(row.lead.created_by, self.manager)
        self.assertEqual(row.processed_by, self.manager)
        self.assertIn("Email lead (manual)", row.lead.remarks)
        # Second create is refused.
        r = self.client.post(f"/api/leads/mail/{row.pk}/create/", {
            "name": "Again", "phone": "9000000002", "campus": self.blr.pk,
            "program": self.dip_fd.pk, "source": self.website.pk,
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_ignore_and_retry(self):
        row = self.mail(frm="x@y.com", subject="hi", text="hi")
        process_email(row)
        self.client.force_authenticate(self.manager)
        r = self.client.post(f"/api/leads/mail/{row.pk}/ignore/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "ignored")
        # Fix the body (as if a mapping fix made it parseable) and retry.
        InboundLeadEmail.objects.filter(pk=row.pk).update(text_body=PORTAL_PLAIN,
                                                          from_address="leads@shiksha.com")
        r = self.client.post(f"/api/leads/mail/{row.pk}/retry/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "created")

    def test_rules_crud_perm(self):
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.get("/api/leads/mail/rules/").status_code, 200)
        r = self.client.post("/api/leads/mail/rules/", {"name": "n", "match_from": "a@b"},
                             format="json")
        self.assertEqual(r.status_code, 403)
        rules_user = self._user("rules", ["leads.mail.view", "leads.mail.rules"])
        self.client.force_authenticate(rules_user)
        r = self.client.post("/api/leads/mail/rules/", {"name": "n", "match_from": "",
                                                        "match_subject": ""}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/leads/mail/rules/", {
            "name": "CollegeDunia", "match_from": "collegedunia.com", "parser": "generic",
            "source": self.shiksha.pk, "priority": 40}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        rid = r.data["id"]
        r = self.client.patch(f"/api/leads/mail/rules/{rid}/", {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["is_active"])
        self.assertEqual(self.client.delete(f"/api/leads/mail/rules/{rid}/").status_code, 204)

    @override_settings(LEAD_MAIL_IMAP_PASSWORD="")
    def test_fetch_now_unconfigured(self):
        self.client.force_authenticate(self.manager)
        r = self.client.post("/api/leads/mail/fetch/")
        self.assertEqual(r.status_code, 503)
