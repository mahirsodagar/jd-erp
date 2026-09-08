"""The fee overview the undertaking prints.

The PDF itself is binary, so these assert the numbers and the wording of
each money row — which installment counts as the up-front payment, that
a paid row says when and how it was paid while an unpaid one says when
it is due, and that the balance excludes what was already taken.
"""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.admissions.models import Enrollment, Student
from apps.admissions.services_undertaking import (
    fee_overview, render_undertaking_pdf,
)
from apps.fees.models import Concession, FeeReceipt, Installment
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester,
)


class UndertakingTests(TestCase):

    def setUp(self):
        self.enrollment = _fixture()

    # --- schedule --------------------------------------------------

    def test_registration_is_the_up_front_row_and_leaves_the_balance(self):
        _installment(self.enrollment, 1, "30000", kind=Installment.Kind.REGISTRATION,
                     due=date(2025, 9, 4))
        _installment(self.enrollment, 2, "72500", due=date(2026, 11, 18))
        _installment(self.enrollment, 3, "72500", due=date(2026, 12, 18))

        o = fee_overview(self.enrollment)
        self.assertEqual(o["total_fee"], Decimal("175000"))
        self.assertEqual(o["balance_due"], Decimal("145000"))
        self.assertEqual(o["balance_lines"], [
            "72500 to be paid on 18/11/2026",
            "72500 to be paid on 18/12/2026",
        ])

    def test_paid_rows_say_when_and_how(self):
        reg = _installment(self.enrollment, 1, "30000",
                           kind=Installment.Kind.REGISTRATION)
        _installment(self.enrollment, 2, "72500", due=date(2026, 11, 18))
        _receipt(self.enrollment, reg, "30000", date(2025, 9, 4))

        o = fee_overview(self.enrollment)
        self.assertEqual(o["upfront_line"], "30000 Paid on 04/09/2025 - Online")

    def test_cancelled_receipts_do_not_mark_a_row_paid(self):
        reg = _installment(self.enrollment, 1, "30000",
                           kind=Installment.Kind.REGISTRATION,
                           due=date(2025, 9, 4))
        _receipt(self.enrollment, reg, "30000", date(2025, 9, 4),
                 status=FeeReceipt.Status.CANCELLED)

        o = fee_overview(self.enrollment)
        self.assertEqual(o["upfront_line"], "30000 to be paid on 04/09/2025")

    def test_down_payment_stands_in_when_there_is_no_registration_row(self):
        _installment(self.enrollment, 1, "50000", description="Down payment")
        _installment(self.enrollment, 2, "50000", due=date(2026, 11, 18))

        o = fee_overview(self.enrollment)
        self.assertEqual(o["balance_due"], Decimal("50000"))
        self.assertEqual(len(o["balance_lines"]), 1)

    def test_concession_counts_towards_the_total_fee(self):
        _installment(self.enrollment, 1, "30000",
                     kind=Installment.Kind.REGISTRATION)
        Concession.objects.create(enrollment=self.enrollment,
                                  amount=Decimal("5000"), reason="Merit",
                                  status=Concession.Status.APPROVED)

        o = fee_overview(self.enrollment)
        self.assertEqual(o["total_fee"], Decimal("35000"))
        self.assertEqual(o["concession"], Decimal("5000"))

    def test_pending_concession_is_ignored(self):
        _installment(self.enrollment, 1, "30000",
                     kind=Installment.Kind.REGISTRATION)
        Concession.objects.create(enrollment=self.enrollment,
                                  amount=Decimal("5000"), reason="Merit")

        self.assertEqual(fee_overview(self.enrollment)["total_fee"],
                         Decimal("30000"))

    # --- rendering -------------------------------------------------

    def test_renders_diploma(self):
        _installment(self.enrollment, 1, "30000",
                     kind=Installment.Kind.REGISTRATION)
        _installment(self.enrollment, 2, "72500", due=date(2026, 11, 18))
        out = render_undertaking_pdf(self.enrollment, remarks="Batch shifted",
                                     submitted_by="Kutheja Sarwath")
        self.assertTrue(out.startswith(b"%PDF"))
        self.assertGreater(len(out), 2000)

    def test_renders_degree_program_with_no_schedule_at_all(self):
        """An enrollment with no installments yet must still print — the
        counsellor generates the undertaking while setting the fee up."""
        e = _fixture(degree_type="M.Sc", code_suffix="2")
        self.assertTrue(render_undertaking_pdf(e).startswith(b"%PDF"))


# --- fixtures ----------------------------------------------------------

def _fixture(*, degree_type="Diploma", code_suffix=""):
    institute, _ = Institute.objects.get_or_create(
        code="JDI", defaults={
            "name": "JD Institute of Fashion Technology",
            "letterhead_title": "Corporate Center",
            "address": "#40, Swan house, 4th cross,\nResidency Road, Bangalore-560025",
            "phone": "+91 99019 99903", "email": "jdfashion@jdindia.com",
            "gstin": "29AAEPD3991M2Z8",
        },
    )
    campus, _ = Campus.objects.get_or_create(code="BNG",
                                             defaults={"name": "Bangalore"})
    program = Program.objects.create(
        name=f"Diploma in Fashion Design{code_suffix}",
        code=f"DFD{code_suffix}", institute=institute,
        degree_type=degree_type, duration_months=12,
    )
    year, _ = AcademicYear.objects.get_or_create(
        code="2026-27", defaults={
            "full_name": "2026-27", "start_date": date(2026, 6, 1),
            "end_date": date(2027, 5, 31),
        },
    )
    student = Student.objects.create(
        application_form_id=f"JDI-2026-000{code_suffix or '1'}",
        student_name="Kuruva Srujan", gender="M", dob=date(2006, 1, 1),
        nationality="Indian", institute=institute, campus=campus,
        program=program, academic_year=year, student_mobile="6300757263",
        student_email=f"srujan{code_suffix}@example.com",
    )
    semester = Semester.objects.create(number=1, name="Semester 1",
                                       program=program)
    batch = Batch.objects.create(
        name=f"Nov 2026{code_suffix}", campus=campus, program=program,
        academic_year=year, start_semester=semester,
    )
    return Enrollment.objects.create(
        student=student, program=program, campus=campus, batch=batch,
        semester=semester, academic_year=year,
        status=Enrollment.Status.ACTIVE,
    )


def _installment(enrollment, sequence, amount, *, kind=None, due=None,
                 description=""):
    return Installment.objects.create(
        enrollment=enrollment, sequence=sequence, amount=Decimal(amount),
        kind=kind or Installment.Kind.COURSE, due_date=due or date(2026, 11, 18),
        description=description or f"Installment {sequence}",
    )


def _receipt(enrollment, installment, amount, received, *, status=None):
    return FeeReceipt.objects.create(
        enrollment=enrollment, installment=installment,
        receipt_no=f"JDBNG{FeeReceipt.objects.count() + 1:04d}-2026",
        basic_fee=Decimal(amount), amount=Decimal(amount),
        payment_mode=FeeReceipt.PaymentMode.ONLINE, received_date=received,
        status=status or FeeReceipt.Status.ACTIVE,
    )
