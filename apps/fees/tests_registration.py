"""Rules around the mandatory yearly registration fee.

Covers the four things that make it "mandatory" rather than decorative:
it is carved out of the total (never added on top), it cannot be waived
by a concession, it is charged once per academic year (not once per
enrollment), and the schedule cannot be built without it.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.admissions.models import Enrollment, Student
from apps.admissions.services import promote_batch
from apps.fees.models import Concession, Installment
from apps.fees.serializers import InstallmentSerializer
from apps.fees.services.balance import enrollment_balance
from apps.fees.services.registration import ensure_registration_installment
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester,
)
from apps.master.serializers import FeeTemplateSerializer


class RegistrationFeeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JD", code="JD")
        cls.campus = Campus.objects.create(
            name="Main", code="MAIN", institute=cls.institute,
        )
        cls.program = Program.objects.create(name="B.Des", code="BDES")
        cls.y1 = AcademicYear.objects.create(
            code="2026-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        cls.y2 = AcademicYear.objects.create(
            code="2027-28", start_date=date(2027, 6, 1),
            end_date=date(2028, 5, 31),
        )
        cls.sem1 = Semester.objects.create(number=1, name="Sem 1")
        cls.sem2 = Semester.objects.create(number=2, name="Sem 2")
        cls.batch1 = Batch.objects.create(
            name="B1", campus=cls.campus, program=cls.program,
            academic_year=cls.y1,
        )
        cls.batch2 = Batch.objects.create(
            name="B2", campus=cls.campus, program=cls.program,
            academic_year=cls.y2,
        )
        cls.student = Student.objects.create(
            student_name="Asha", gender="F", dob=date(2006, 1, 1),
            nationality="Indian", institute=cls.institute,
            campus=cls.campus, program=cls.program, academic_year=cls.y1,
            student_mobile="9000000000", student_email="asha@example.com",
        )

    def _template(self, year, *, total="200000", registration="10000"):
        from apps.master.models import FeeTemplate
        return FeeTemplate.objects.create(
            name=f"BDes {year.code}", academic_year=year, campus=self.campus,
            program=self.program, total_fee=Decimal(total),
            registration_fee=Decimal(registration),
        )

    def _enroll(self, year, batch, semester):
        return Enrollment.objects.create(
            student=self.student, program=self.program, semester=semester,
            campus=self.campus, batch=batch, academic_year=year,
            status=Enrollment.Status.ACTIVE,
        )

    # --- carved out, not added on top ---------------------------------

    def test_registration_does_not_inflate_the_total(self):
        self._template(self.y1, total="200000", registration="10000")
        e = self._enroll(self.y1, self.batch1, self.sem1)
        ensure_registration_installment(e)

        b = enrollment_balance(e)
        # Compared as Decimals: the aggregate-backed keys come back
        # unscaled ("10000") while template-backed ones keep their two
        # decimal places, and that split is pre-existing behaviour.
        self.assertEqual(Decimal(b["total_fee"]), Decimal("200000"))
        self.assertEqual(Decimal(b["registration_fee"]), Decimal("10000"))
        # payable is the total, untouched by the registration line.
        self.assertEqual(Decimal(b["payable"]), Decimal("200000"))
        self.assertEqual(Decimal(b["registration_due"]), Decimal("10000"))
        self.assertEqual(Decimal(b["registration_balance"]), Decimal("10000"))

    def test_template_rejects_registration_above_total(self):
        s = FeeTemplateSerializer(data={
            "name": "Short course", "academic_year": self.y1.id,
            "campus": self.campus.id, "program": self.program.id,
            "total_fee": "8000", "registration_fee": "10000",
        })
        self.assertFalse(s.is_valid())
        self.assertIn("registration_fee", s.errors)

    # --- cannot be waived ---------------------------------------------

    def test_concession_is_capped_at_the_registration_fee(self):
        self._template(self.y1, total="200000", registration="10000")
        e = self._enroll(self.y1, self.batch1, self.sem1)
        ensure_registration_installment(e)
        # A concession larger than the fee-minus-registration ceiling.
        Concession.objects.create(
            enrollment=e, amount=Decimal("195000"), reason="test",
            status=Concession.Status.APPROVED,
        )

        b = enrollment_balance(e)
        self.assertEqual(Decimal(b["concession_total"]), Decimal("195000"))
        # Capped to 200000 − 10000, leaving the registration fee payable.
        self.assertEqual(Decimal(b["concession_applied"]), Decimal("190000"))
        self.assertTrue(b["concession_capped"])
        self.assertEqual(Decimal(b["payable"]), Decimal("10000"))

    # --- once per academic year, not per enrollment ---------------------

    def test_seeding_is_idempotent_within_one_year(self):
        self._template(self.y1)
        e = self._enroll(self.y1, self.batch1, self.sem1)

        first = ensure_registration_installment(e)
        again = ensure_registration_installment(e)
        self.assertEqual(first.id, again.id)
        self.assertEqual(
            Installment.objects.filter(
                kind=Installment.Kind.REGISTRATION,
            ).count(), 1,
        )

    def test_mid_year_semester_promotion_does_not_charge_twice(self):
        """sem 1 → sem 2 inside the SAME academic year is one charge."""
        self._template(self.y1)
        e = self._enroll(self.y1, self.batch1, self.sem1)
        ensure_registration_installment(e)

        promote_batch(
            source_batch=self.batch1, source_semester=self.sem1,
            target_batch=self.batch1, target_semester=self.sem2,
            target_academic_year=self.y1,
        )

        self.assertEqual(
            Installment.objects.filter(
                kind=Installment.Kind.REGISTRATION,
                enrollment__student=self.student,
            ).count(), 1,
        )

    def test_promotion_into_a_new_year_charges_again(self):
        self._template(self.y1)
        self._template(self.y2)
        e = self._enroll(self.y1, self.batch1, self.sem1)
        ensure_registration_installment(e)

        promote_batch(
            source_batch=self.batch1, source_semester=self.sem1,
            target_batch=self.batch2, target_semester=self.sem2,
            target_academic_year=self.y2,
        )

        rows = Installment.objects.filter(
            kind=Installment.Kind.REGISTRATION,
            enrollment__student=self.student,
        )
        self.assertEqual(rows.count(), 2)
        self.assertEqual(
            {r.enrollment.academic_year_id for r in rows},
            {self.y1.id, self.y2.id},
        )

    def test_no_charge_when_the_template_opts_out(self):
        self._template(self.y1, registration="0")
        e = self._enroll(self.y1, self.batch1, self.sem1)
        self.assertIsNone(ensure_registration_installment(e))

    # --- the amount is locked -----------------------------------------

    def test_serializer_rejects_a_wrong_registration_amount(self):
        self._template(self.y1, registration="10000")
        e = self._enroll(self.y1, self.batch1, self.sem1)

        s = InstallmentSerializer(data={
            "enrollment": e.id, "kind": "REGISTRATION", "sequence": 1,
            "due_date": "2026-06-01", "amount": "5000",
        })
        self.assertFalse(s.is_valid())
        self.assertIn("amount", s.errors)

    def test_serializer_rejects_a_second_registration_row(self):
        self._template(self.y1, registration="10000")
        e = self._enroll(self.y1, self.batch1, self.sem1)
        ensure_registration_installment(e)

        s = InstallmentSerializer(data={
            "enrollment": e.id, "kind": "REGISTRATION", "sequence": 9,
            "due_date": "2026-06-01", "amount": "10000",
        })
        self.assertFalse(s.is_valid())
        self.assertIn("kind", s.errors)

    def test_registration_row_cannot_be_relabelled_as_course(self):
        self._template(self.y1, registration="10000")
        e = self._enroll(self.y1, self.batch1, self.sem1)
        row = ensure_registration_installment(e)

        s = InstallmentSerializer(row, data={"kind": "COURSE"}, partial=True)
        self.assertFalse(s.is_valid())
        self.assertIn("kind", s.errors)
