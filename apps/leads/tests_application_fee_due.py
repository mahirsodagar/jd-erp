"""The application fee a lead still owes, as the detail API reports it.

The counsellor quotes this number on the phone and the fee-link email
prints it, so the two must come from the same lookup — see
apps/leads/fee_lookup.py.
"""

from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.leads.models import Lead
from apps.leads.serializers import LeadDetailSerializer
from apps.master.models import (
    AcademicYear, Campus, FeeTemplate, Institute, LeadSource, Program,
)


class ApplicationFeeDueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.source = LeadSource.objects.create(name="Website", slug="website")
        cls.blr = Campus.objects.create(name="Bengaluru", code="BLR")
        cls.mum = Campus.objects.create(name="Mumbai", code="MUM")
        cls.prog = Program.objects.create(
            name="B.Des Fashion", code="BDES-F", institute=cls.institute,
        )
        cls.y25 = AcademicYear.objects.create(
            code="2025-26", start_date="2025-06-01", end_date="2026-05-31",
        )
        cls.y26 = AcademicYear.objects.create(
            code="2026-27", start_date="2026-06-01", end_date="2027-05-31",
            is_current=True,
        )
        cls.lead = Lead.objects.create(
            name="Asha", email="asha@example.com", phone="+919900112233",
            campus=cls.blr, program=cls.prog, source=cls.source,
        )

    def _template(self, *, year, campus, fee):
        return FeeTemplate.objects.create(
            name=f"{campus.code} {year.code}", academic_year=year,
            campus=campus, program=self.prog,
            application_fee=Decimal(fee), total_fee=Decimal("100000.00"),
        )

    def _due(self, lead=None):
        return LeadDetailSerializer(lead or self.lead).data["application_fee_due"]

    def test_fee_comes_from_the_template_for_the_leads_campus_and_program(self):
        self._template(year=self.y26, campus=self.blr, fee="5000.00")
        # Same program, different campus — must not leak across.
        self._template(year=self.y26, campus=self.mum, fee="7000.00")
        self.assertEqual(self._due(), "5000.00")

    def test_newest_academic_year_wins(self):
        """A Lead names no academic year, so the current price is the
        only sensible answer — quoting last year's would undercharge."""
        self._template(year=self.y25, campus=self.blr, fee="4000.00")
        self._template(year=self.y26, campus=self.blr, fee="5000.00")
        self.assertEqual(self._due(), "5000.00")

    def test_inactive_template_is_ignored(self):
        tmpl = self._template(year=self.y26, campus=self.blr, fee="5000.00")
        tmpl.is_active = False
        tmpl.save(update_fields=["is_active"])
        self.assertEqual(self._due(), "")

    def test_blank_when_nothing_covers_the_pair(self):
        self.assertEqual(self._due(), "")

    def test_zero_fee_reads_as_nothing_to_quote(self):
        """₹0 due is not a figure worth putting on screen — it would read
        as "collect nothing" when it actually means "not priced yet"."""
        self._template(year=self.y26, campus=self.blr, fee="0.00")
        self.assertEqual(self._due(), "")

    def test_listing_leads_hits_the_fee_table_once(self):
        """The list endpoint serializes up to 500 leads with this same
        serializer, so the lookup must not run per row."""
        self._template(year=self.y26, campus=self.blr, fee="5000.00")
        for i in range(5):
            Lead.objects.create(
                name=f"Lead {i}", email=f"l{i}@example.com",
                phone=f"+91990011{i:04d}", campus=self.blr, program=self.prog,
                source=self.source,
            )
        leads = list(Lead.objects.all())
        with CaptureQueriesContext(connection) as ctx:
            data = LeadDetailSerializer(leads, many=True).data
        fee_queries = [
            q for q in ctx.captured_queries
            if "master_feetemplate" in q["sql"]
        ]
        self.assertEqual(len(fee_queries), 1, fee_queries)
        self.assertEqual(
            {row["application_fee_due"] for row in data}, {"5000.00"},
        )
