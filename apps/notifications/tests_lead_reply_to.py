"""Lead automation mail (welcome, HOT follow-up, cold drip, enrolled,
escalation) replies to the assigned counsellor, else the campus
admissions inbox, else the default (user decision 2026-11-20)."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.leads.models import Lead, LeadFollowup
from apps.master.models import Campus, Institute, LeadSource, Program
from apps.notifications.models import ScheduledNotification
from apps.notifications.reply_to import resolve_reply_to

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_DEFAULT_REPLY_TO="webmaster@dkul.in",
    ADMISSIONS_CAMPUS_INBOXES={"MAIN": "main@jdinstitute.edu.in"},
    APPLICATION_ACK_CAMPUS_INBOXES={"MAIN": "acknowledgement.main@jdinstitute.edu.in"},
    EMAIL_REPLY_TO_POLICY={
        "lead_welcome_email": "CAMPUS_LEADS",
        "hot_why_join_jd": "CAMPUS_LEADS",
        "cold_drip_30": "CAMPUS_LEADS",
        "manager_overdue_hot_lead": "CAMPUS_LEADS",
    },
)
class LeadAutomationReplyToTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.counsellor = User.objects.create_user(
            username="c1", password="x", email="counsellor@jdinstitute.edu.in",
        )
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(
            name="Diploma in Fashion", code="DFD",
            institute=institute, degree_type="Diploma",
        )
        cls.source = LeadSource.objects.create(name="Web", slug="web")
        from apps.notifications.models import NotificationTemplate

        NotificationTemplate.objects.create(
            key="cold_drip_30", channel=NotificationTemplate.Channel.EMAIL,
            subject_template="Still thinking, {name}?", body_template="Hi {name}",
        )

    def _lead(self, **extra):
        return Lead.objects.create(
            name="Asha Rao", phone="9999999999", email="asha@example.com",
            campus=self.campus, program=self.program, source=self.source,
            **extra,
        )

    def test_welcome_and_followup_context_carry_counsellor_and_campus(self):
        lead = self._lead(assign_to=self.counsellor)
        LeadFollowup.objects.create(
            lead=lead, followup_type="CALL",
            outcome_category=LeadFollowup.Outcome.COLD,
        )
        sched = ScheduledNotification.objects.get(template_key="cold_drip_30")
        self.assertEqual(sched.context["reply_to"], "counsellor@jdinstitute.edu.in")
        self.assertEqual(sched.context["campus_code"], "MAIN")
        self.assertEqual(resolve_reply_to("cold_drip_30", sched.context),
                         "counsellor@jdinstitute.edu.in")

    def test_unassigned_lead_falls_back_to_campus_admissions_inbox(self):
        lead = self._lead()
        LeadFollowup.objects.create(
            lead=lead, followup_type="CALL",
            outcome_category=LeadFollowup.Outcome.COLD,
        )
        sched = ScheduledNotification.objects.get(template_key="cold_drip_30")
        self.assertEqual(sched.context["reply_to"], "")
        self.assertEqual(resolve_reply_to("cold_drip_30", sched.context),
                         "main@jdinstitute.edu.in")
        # A campus with no admissions inbox uses its acknowledgement inbox.
        with override_settings(ADMISSIONS_CAMPUS_INBOXES={"MAIN": ""}):
            self.assertEqual(resolve_reply_to("cold_drip_30", sched.context),
                             "acknowledgement.main@jdinstitute.edu.in")

    def test_escalation_mail_replies_to_the_counsellor(self):
        from apps.leads.send_links import _reply_context

        lead = self._lead(assign_to=self.counsellor)
        self.assertEqual(
            resolve_reply_to("manager_overdue_hot_lead", _reply_context(lead)),
            "counsellor@jdinstitute.edu.in",
        )
        lead.assign_to = None
        self.assertEqual(
            resolve_reply_to("manager_overdue_hot_lead", _reply_context(lead)),
            "main@jdinstitute.edu.in",
        )
