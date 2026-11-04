"""Paused / inactive counsellors never receive a lead automatically —
neither from the round-robin nor by being the original owner of a
duplicate."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.academics.tests_electives import make_faculty
from apps.employees.models import Employee
from apps.leads.models import Counsellor, Lead
from apps.leads.services import (
    assign_via_round_robin, can_take_leads, create_lead,
)
from apps.master.models import Campus, Institute, LeadSource, Program

User = get_user_model()


class CounsellorAssignmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Bengaluru", code="BLR")
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.program.campuses.add(cls.campus)
        cls.source = LeadSource.objects.create(name="Website", slug="website")

    def _counsellor(self, code, *, active=True):
        emp = make_faculty(code=code, name=code, campus=self.campus,
                           institute=self.institute)
        user = User.objects.create_user(
            username=code.lower(), email=f"{code.lower()}@u.com", password="x",
        )
        emp.user_account = user
        emp.save(update_fields=["user_account"])
        Counsellor.objects.create(employee=emp, is_active=active,
                                  sort_order=int(code[-1]))
        return user

    def _lead(self, *, email, phone, **extra):
        return create_lead(data={
            "name": "Asha", "email": email, "phone": phone,
            "campus": self.campus, "program": self.program,
            "source": self.source, **extra,
        })

    def test_round_robin_skips_paused(self):
        self._counsellor("C1", active=False)
        active = self._counsellor("C2")
        for _ in range(3):
            self.assertEqual(assign_via_round_robin(), active)

    def test_round_robin_skips_inactive_employee(self):
        gone = self._counsellor("C1")
        gone.employee.set_status(Employee.Status.INACTIVE)
        active = self._counsellor("C2")
        self.assertFalse(can_take_leads(gone))
        self.assertEqual(assign_via_round_robin(), active)

    def test_nobody_eligible_leaves_lead_unassigned(self):
        self._counsellor("C1", active=False)
        lead = self._lead(email="a@e.com", phone="9900112233")
        self.assertIsNone(lead.assign_to)

    def test_duplicate_follows_owner_while_eligible(self):
        owner = self._counsellor("C1")
        self._counsellor("C2")
        first = self._lead(email="a@e.com", phone="9900112233")
        self.assertEqual(first.assign_to, owner)
        dup = self._lead(email="a@e.com", phone="9900112233")
        self.assertEqual(dup.duplicate_of, first)
        self.assertEqual(dup.assign_to, owner)

    def test_duplicate_not_given_to_paused_owner(self):
        owner = self._counsellor("C1")
        other = self._counsellor("C2")
        first = self._lead(email="a@e.com", phone="9900112233")
        self.assertEqual(first.assign_to, owner)

        Counsellor.objects.filter(employee__user_account=owner).update(is_active=False)
        dup = self._lead(email="a@e.com", phone="9900112233")
        self.assertEqual(dup.duplicate_of, first)
        self.assertEqual(dup.assign_to, other)
        # The original lead stays with whoever had it.
        first.refresh_from_db()
        self.assertEqual(first.assign_to, owner)

    def test_duplicate_with_paused_owner_honours_explicit_assignee(self):
        owner = self._counsellor("C1")
        self._counsellor("C2")
        chosen = self._counsellor("C3")
        first = self._lead(email="a@e.com", phone="9900112233")
        Counsellor.objects.filter(employee__user_account=owner).update(is_active=False)
        dup = self._lead(email="a@e.com", phone="9900112233", assign_to=chosen)
        self.assertEqual(dup.assign_to, chosen)

    def test_duplicate_with_paused_owner_and_nobody_else(self):
        owner = self._counsellor("C1")
        first = self._lead(email="a@e.com", phone="9900112233")
        Counsellor.objects.filter(employee__user_account=owner).update(is_active=False)
        dup = self._lead(email="a@e.com", phone="9900112233")
        self.assertEqual(dup.duplicate_of, first)
        self.assertIsNone(dup.assign_to)
        self.assertEqual(Lead.objects.count(), 2)
