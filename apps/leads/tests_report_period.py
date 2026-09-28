"""Lead Reports — one period control (preset or custom range) for every
section."""

from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.leads.models import Lead
from apps.leads.reports import REPORT_TZ, BadPeriod, report_window
from apps.master.models import Campus, Institute, LeadSource, Program

User = get_user_model()


class ReportWindowTests(SimpleTestCase):
    # 28-09-26 10:00 IST
    NOW = datetime(2026, 9, 28, 10, 0, tzinfo=REPORT_TZ)

    def w(self, **params):
        return report_window(params, now=self.NOW)

    def test_default_is_last_30_days(self):
        start, end, period = self.w()
        self.assertEqual(period, "30d")
        self.assertEqual(end - start, timedelta(days=30))

    def test_rolling_presets(self):
        self.assertEqual(self.w(period="24h")[0], self.NOW - timedelta(hours=24))
        self.assertEqual(self.w(period="7d")[0], self.NOW - timedelta(days=7))
        self.assertEqual(self.w(period="90d")[0], self.NOW - timedelta(days=90))

    def test_calendar_presets_use_india_midnight(self):
        self.assertEqual(self.w(period="today")[0],
                         datetime(2026, 9, 28, tzinfo=REPORT_TZ))
        self.assertEqual(self.w(period="this_month")[0],
                         datetime(2026, 9, 1, tzinfo=REPORT_TZ))

    def test_custom_range_wins_and_is_inclusive(self):
        start, end, period = self.w(period="24h", start_date="2026-09-01",
                                    end_date="2026-09-10")
        self.assertEqual(period, "custom")
        self.assertEqual(start, datetime(2026, 9, 1, tzinfo=REPORT_TZ))
        self.assertEqual(end, datetime(2026, 9, 11, tzinfo=REPORT_TZ))

    def test_bad_input(self):
        for params in ({"period": "1y"}, {"start_date": "2026-09-01"},
                       {"start_date": "2026-09-10", "end_date": "2026-09-01"}):
            with self.assertRaises(BadPeriod):
                self.w(**params)


class ReportPeriodApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        program = Program.objects.create(
            name="Diploma", code="DFD", institute=institute,
            degree_type="Diploma",
        )
        source = LeadSource.objects.create(name="Web", slug="web")
        now = timezone.now()
        # Two enquiries from one phone 2 days ago; one lead 20 days ago.
        for i, age in enumerate((2, 2, 20)):
            lead = Lead.objects.create(
                name=f"L{i}", phone="9999999999" if age == 2 else "8888888888",
                email=f"l{i}@e.com", campus=campus, program=program,
                source=source,
            )
            Lead.objects.filter(pk=lead.pk).update(
                created_at=now - timedelta(days=age),
                phone_normalized=lead.phone)
        cls.admin = User.objects.create_superuser(
            username="admin", password="x", email="a@example.com",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    # Paths, not reverse(): apps.leaves also names a URL "report-summary".
    PATHS = {
        "report-summary": "/api/leads/reports/summary/",
        "report-funnel": "/api/leads/reports/funnel/",
        "report-duplicates": "/api/leads/reports/duplicates/",
    }

    def get(self, name, **params):
        return self.client.get(self.PATHS[name], params)

    def test_every_kpi_follows_the_period(self):
        week = self.get("report-summary", period="7d").data
        month = self.get("report-summary", period="30d").data
        self.assertEqual((week["leads_in"], month["leads_in"]), (2, 3))
        self.assertEqual(week["period"], "7d")
        funnel = self.get("report-funnel", period="7d").data
        self.assertEqual(funnel["funnel"]["total_leads"], 2)

    def test_custom_range(self):
        today = timezone.now().astimezone(REPORT_TZ).date()
        res = self.get("report-funnel",
                       start_date=str(today - timedelta(days=25)),
                       end_date=str(today - timedelta(days=10))).data
        self.assertEqual(res["period"], "custom")
        self.assertEqual(res["funnel"]["total_leads"], 1)

    def test_duplicates_follow_the_period(self):
        rows = self.get("report-duplicates", period="7d").data["rows"]
        self.assertEqual([r["phone_normalized"] for r in rows], ["9999999999"])
        self.assertEqual(self.get("report-duplicates", period="24h")
                         .data["rows"], [])

    def test_bad_period_is_400(self):
        self.assertEqual(self.get("report-summary", period="1y").status_code,
                         400)
