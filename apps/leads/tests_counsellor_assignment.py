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

    def _counsellor(self, code, *, active=True, campus=None):
        emp = make_faculty(code=code, name=code, campus=campus or self.campus,
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
            self.assertEqual(assign_via_round_robin(self.campus), active)

    def test_round_robin_skips_inactive_employee(self):
        gone = self._counsellor("C1")
        gone.employee.set_status(Employee.Status.INACTIVE)
        active = self._counsellor("C2")
        self.assertFalse(can_take_leads(gone))
        self.assertEqual(assign_via_round_robin(self.campus), active)

    # --- Campus-wise assignment -------------------------------------

    def _other_campus(self):
        goa = Campus.objects.create(name="Goa", code="GOA")
        self.program.campuses.add(goa)
        return goa

    def test_round_robin_only_rotates_within_the_leads_campus(self):
        goa = self._other_campus()
        blr1 = self._counsellor("C1")
        blr2 = self._counsellor("C2")
        goa_c = self._counsellor("C3", campus=goa)

        picks = [self._lead(email=f"b{i}@e.com", phone=f"990011220{i}").assign_to
                 for i in range(4)]
        self.assertEqual(picks, [blr1, blr2, blr1, blr2])
        self.assertNotIn(goa_c, picks)

        goa_lead = self._lead(email="g@e.com", phone="9900112299", campus=goa)
        self.assertEqual(goa_lead.assign_to, goa_c)

    def test_each_campus_keeps_its_own_pointer(self):
        goa = self._other_campus()
        blr1 = self._counsellor("C1")
        self._counsellor("C2")
        goa1 = self._counsellor("C3", campus=goa)
        self._counsellor("C4", campus=goa)

        self.assertEqual(assign_via_round_robin(self.campus), blr1)
        # Goa's rotation has not moved because Bengaluru's did.
        self.assertEqual(assign_via_round_robin(goa), goa1)

    def test_campus_with_no_counsellor_leaves_lead_unassigned(self):
        goa = self._other_campus()
        self._counsellor("C1")  # Bengaluru only
        lead = self._lead(email="g@e.com", phone="9900112299", campus=goa)
        self.assertIsNone(lead.assign_to)

    def test_duplicate_keeps_root_owner_even_from_another_campus(self):
        goa = self._other_campus()
        owner = self._counsellor("C1")
        self._counsellor("C2", campus=goa)
        first = self._lead(email="a@e.com", phone="9900112233")
        dup = self._lead(email="a@e.com", phone="9900112233", campus=goa)
        self.assertEqual(dup.assign_to, owner)

    def test_manual_assignment_must_match_the_leads_campus(self):
        from rest_framework.exceptions import ValidationError
        from apps.leads.serializers import validate_assign_to_is_counsellor

        goa = self._other_campus()
        goa_c = self._counsellor("C3", campus=goa)
        self.assertEqual(validate_assign_to_is_counsellor(goa_c, goa), goa_c)
        with self.assertRaises(ValidationError):
            validate_assign_to_is_counsellor(goa_c, self.campus)
        # No campus given → only the "is a counsellor" rule applies.
        self.assertEqual(validate_assign_to_is_counsellor(goa_c), goa_c)

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
