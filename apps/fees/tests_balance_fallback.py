"""What the balance reports when no FeeTemplate resolves.

The fee report read `total_fee` straight off the active FeeTemplate for
(academic_year, campus, program). When that lookup missed — template
deactivated, fee revised into a new row, enrollment moved to a
campus/program the template doesn't cover — the total came back 0, so
`payable` was 0 and `balance` went negative the moment a receipt was
recorded: a 0 total against a minus due on the report.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.admissions.models import Enrollment, Student
from apps.fees.models import Concession, FeeReceipt, Installment
from apps.fees.services.balance import enrollment_balance
from apps.master.models import (
    AcademicYear, Batch, Campus, FeeTemplate, Institute, Program, Semester,
)


class BalanceWithoutTemplateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JD", code="JD")
        cls.campus = Campus.objects.create(name="Main", code="MAIN")
        cls.program = Program.objects.create(
            name="B.Des", code="BDES", institute=cls.institute,
        )
        cls.year = AcademicYear.objects.create(
            code="2026-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        cls.sem = Semester.objects.create(number=1, name="Sem 1")
        cls.batch = Batch.objects.create(
            name="B1", campus=cls.campus, program=cls.program,
            academic_year=cls.year,
        )
        cls.student = Student.objects.create(
            student_name="Asha", gender="F", dob=date(2006, 1, 1),
            nationality="Indian", institute=cls.institute,
            campus=cls.campus, program=cls.program, academic_year=cls.year,
            student_mobile="9000000000", student_email="asha@example.com",
        )
        cls.enrollment = Enrollment.objects.create(
            student=cls.student, program=cls.program, semester=cls.sem,
            campus=cls.campus, batch=cls.batch, academic_year=cls.year,
            status=Enrollment.Status.ACTIVE,
        )

    def _schedule(self, *amounts, registration="10000"):
        seq = 0
        if registration:
            seq += 1
            Installment.objects.create(
                enrollment=self.enrollment, kind=Installment.Kind.REGISTRATION,
                sequence=seq, due_date=date(2026, 6, 1),
                amount=Decimal(registration), description="Registration fee",
            )
        for amt in amounts:
            seq += 1
            Installment.objects.create(
                enrollment=self.enrollment, sequence=seq,
                due_date=date(2026, 6, 1), amount=Decimal(amt),
            )

    def _receipt(self, amount, no="R1"):
        return FeeReceipt.objects.create(
            receipt_no=no, enrollment=self.enrollment,
            basic_fee=Decimal(amount), amount=Decimal(amount),
            payment_mode=FeeReceipt.PaymentMode.CASH,
            received_date=date(2026, 6, 5),
        )

    # --- the reported bug ---------------------------------------------

    def test_due_is_not_negative_when_no_template_matches(self):
        self._schedule("50000", "140000")   # + 10000 registration = 200000
        self._receipt("50000")

        b = enrollment_balance(self.enrollment)
        self.assertEqual(b["total_fee_source"], "schedule")
        self.assertEqual(Decimal(b["total_fee"]), Decimal("200000"))
        self.assertEqual(Decimal(b["registration_fee"]), Decimal("10000"))
        self.assertEqual(Decimal(b["paid_total"]), Decimal("50000"))
        self.assertEqual(Decimal(b["balance"]), Decimal("150000"))

    def test_fallback_adds_back_approved_concessions(self):
        # Installments carry only what the student actually owes, so the
        # discounted amount has to be added back to recover the headline
        # fee — the identity the undertaking PDF prints.
        self._schedule("40000", "120000")   # 170000 scheduled
        Concession.objects.create(
            enrollment=self.enrollment, amount=Decimal("30000"),
            reason="Merit", status=Concession.Status.APPROVED,
        )
        self._receipt("40000")

        b = enrollment_balance(self.enrollment)
        self.assertEqual(Decimal(b["total_fee"]), Decimal("200000"))
        self.assertEqual(Decimal(b["concession_applied"]), Decimal("30000"))
        self.assertEqual(Decimal(b["payable"]), Decimal("170000"))
        self.assertEqual(Decimal(b["balance"]), Decimal("130000"))

    # --- the template still wins where it exists -----------------------

    def test_active_template_takes_precedence_over_the_schedule(self):
        FeeTemplate.objects.create(
            name="BDes 2026-27", academic_year=self.year, campus=self.campus,
            program=self.program, total_fee=Decimal("200000"),
            registration_fee=Decimal("10000"),
        )
        # A schedule that disagrees (partly built) must not move the total.
        self._schedule("20000")
        self._receipt("20000")

        b = enrollment_balance(self.enrollment)
        self.assertEqual(b["total_fee_source"], "template")
        self.assertEqual(Decimal(b["total_fee"]), Decimal("200000"))
        self.assertEqual(Decimal(b["balance"]), Decimal("180000"))

    def test_no_template_and_no_schedule_still_reports_zero(self):
        # Nothing to fall back on — the money is genuinely unaccounted
        # for, and the report should not invent a total.
        self._receipt("5000")

        b = enrollment_balance(self.enrollment)
        self.assertEqual(b["total_fee_source"], "template")
        self.assertEqual(Decimal(b["total_fee"]), Decimal("0"))
        self.assertEqual(Decimal(b["balance"]), Decimal("-5000"))
