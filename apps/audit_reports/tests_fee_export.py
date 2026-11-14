"""Audit > Fee Receipts Export: Tally receipt-voucher rows (2026-11-14)."""

import csv
import io
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.admissions.models import Enrollment, Student
from apps.fees.models import FeeReceipt, Installment, OtherFee
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester,
)
from apps.roles.models import Permission, Role
from apps.roles.seed import seed_permissions

from .fee_export import HEADERS

User = get_user_model()
URL = "/api/audit-reports/fee-receipts/"


class FeeReceiptExportTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.inst = Institute.objects.create(name="JD Institute", code="JDIFT")
        cls.blr = Campus.objects.create(name="Bangalore", code="BLR")
        cls.goa = Campus.objects.create(name="Goa", code="GOA")
        cls.bdes = Program.objects.create(name="B.Des", code="BDES", institute=cls.inst)
        cls.dip = Program.objects.create(name="Diploma", code="DIP", institute=cls.inst)
        cls.year = AcademicYear.objects.create(
            code="2026-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31),
        )
        cls.sem = Semester.objects.create(number=1, name="Sem 1")

        def enrol(name, campus, program):
            seq = Student.objects.count() + 1
            batch = Batch.objects.create(
                name=f"{program.code}-{campus.code}", campus=campus,
                program=program, academic_year=cls.year,
            )
            st = Student.objects.create(
                application_form_id=f"JDIFT-2026-{seq:04d}",
                student_name=name, gender="F", dob=date(2006, 1, 1),
                nationality="Indian", institute=cls.inst, campus=campus,
                program=program, academic_year=cls.year,
                student_mobile="9000000000", student_email=f"{name}@x.in",
            )
            return Enrollment.objects.create(
                student=st, program=program, semester=cls.sem, campus=campus,
                batch=batch, academic_year=cls.year,
                status=Enrollment.Status.ACTIVE,
            )

        cls.abhishek = enrol("Abhishek Ghosh", cls.blr, cls.bdes)
        cls.riya = enrol("Riya Sen", cls.goa, cls.dip)

        reg = Installment.objects.create(
            enrollment=cls.abhishek, kind=Installment.Kind.REGISTRATION,
            sequence=1, due_date=date(2026, 4, 1), amount=Decimal("1500"),
        )
        inst2 = Installment.objects.create(
            enrollment=cls.abhishek, sequence=2, due_date=date(2026, 7, 1),
            amount=Decimal("50000"),
        )
        hostel = OtherFee.objects.create(
            enrollment=cls.riya, name="Hostel Fees", amount=Decimal("8000"),
        )

        # 1 Apr: cash, registration, no tax.
        cls.r1 = FeeReceipt.objects.create(
            receipt_no="JDIFT/2026/00001", enrollment=cls.abhishek,
            installment=reg, basic_fee=Decimal("1500"), amount=Decimal("1500"),
            payment_mode=FeeReceipt.PaymentMode.CASH,
            instrument_ref="UTR012456236", received_date=date(2026, 4, 1),
        )
        # 5 Jul: NEFT via HDFC, course installment with SGST+CGST.
        cls.r2 = FeeReceipt.objects.create(
            receipt_no="JDIFT/2026/00002", enrollment=cls.abhishek,
            installment=inst2, basic_fee=Decimal("10000"),
            sgst=Decimal("900"), cgst=Decimal("900"), amount=Decimal("11800"),
            payment_mode=FeeReceipt.PaymentMode.NEFT, bank="HDFC Bank",
            instrument_ref="N123", received_date=date(2026, 7, 5),
        )
        # 6 Jul: UPI, other fee, no bank named, Goa / Diploma.
        cls.r3 = FeeReceipt.objects.create(
            receipt_no="JDIFT/2026/00003", enrollment=cls.riya,
            other_fee=hostel, basic_fee=Decimal("8000"), amount=Decimal("8000"),
            payment_mode=FeeReceipt.PaymentMode.UPI,
            received_date=date(2026, 7, 6),
        )
        # Cancelled — hidden by default.
        cls.r4 = FeeReceipt.objects.create(
            receipt_no="JDIFT/2026/00004", enrollment=cls.riya,
            basic_fee=Decimal("100"), amount=Decimal("100"),
            payment_mode=FeeReceipt.PaymentMode.CASH,
            received_date=date(2026, 7, 7), status=FeeReceipt.Status.CANCELLED,
        )

        seed_permissions()
        cls.auditor = User.objects.create_user("auditor", "a@x.in", "x")
        role = Role.objects.create(name="Auditor")
        role.permissions.set(Permission.objects.filter(key="audit.fee_export"))
        cls.auditor.roles.add(role)
        cls.nobody = User.objects.create_user("nobody", "n@x.in", "x")

    def setUp(self):
        self.c = APIClient()
        self.c.force_authenticate(self.auditor)

    # --- access -------------------------------------------------------

    def test_needs_the_key(self):
        c = APIClient()
        c.force_authenticate(self.nobody)
        self.assertEqual(c.get(URL).status_code, 403)
        self.assertEqual(c.get(URL + "options/").status_code, 403)

    def test_assigned_campus_scopes_non_superuser(self):
        self.auditor.campuses.add(self.goa)
        rows = self.c.get(URL).json()["rows"]
        self.assertEqual([r["campus_code"] for r in rows], ["GOA"])
        self.auditor.campuses.clear()

    # --- rows ---------------------------------------------------------

    def test_voucher_rows_follow_the_sample_sheet(self):
        data = self.c.get(URL).json()
        self.assertEqual(data["count"], 3)        # cancelled hidden
        self.assertFalse(data["truncated"])
        self.assertEqual(data["total_amount"], "21300.00")
        r1, r2, r3 = data["rows"]

        # Cash, registration, no tax: student credited the full amount.
        self.assertEqual(r1["date"], "1/4/2026")
        self.assertEqual(r1["voucher_no"], 1)
        self.assertEqual(r1["vtype"], "Receipt")
        self.assertEqual(r1["cr_one"], "Abhishek Ghosh")
        self.assertEqual(r1["cr_1_amount"], "1500")
        self.assertEqual((r1["cr_two"], r1["cr_2_amount"]), ("", ""))
        self.assertEqual(r1["dr"], "Cash")
        self.assertEqual(r1["amount"], "1500")
        self.assertEqual(r1["reference_number"], "UTR012456236")
        self.assertIn("Registration Fees", r1["narration"])
        self.assertEqual(r1["cost_centre"], "BLR")
        self.assertEqual(r1["fee_head"], "Registration Fees")

        # Bank receipt with GST: credits sum to the total.
        self.assertEqual(r2["voucher_no"], 2)
        self.assertEqual(r2["cr_1_amount"], "10000")
        self.assertEqual((r2["cr_two"], r2["cr_2_amount"]), ("GST", "1800"))
        self.assertEqual(r2["dr"], "HDFC Bank")
        self.assertEqual(r2["amount"], "11800")
        self.assertIn("Course Fees", r2["narration"])
        self.assertIn("Installment 2", r2["narration"])

        # Other fee, online with no bank named.
        self.assertEqual(r3["dr"], "Bank")
        self.assertEqual(r3["fee_head"], "Hostel Fees")
        self.assertIn("Hostel Fees", r3["narration"])
        self.assertEqual(r3["cost_centre"], "GOA")

    def test_include_cancelled_flag(self):
        rows = self.c.get(URL, {"include_cancelled": "1"}).json()["rows"]
        self.assertEqual(len(rows), 4)
        self.assertIn("[CANCELLED]", rows[-1]["narration"])

    # --- filters ------------------------------------------------------

    def test_filters(self):
        def ids(**params):
            return [r["id"] for r in self.c.get(URL, params).json()["rows"]]

        self.assertEqual(ids(campus=self.goa.id), [self.r3.id])
        self.assertEqual(ids(program=self.bdes.id), [self.r1.id, self.r2.id])
        self.assertEqual(ids(institute=self.inst.id), [self.r1.id, self.r2.id, self.r3.id])
        self.assertEqual(ids(student=self.riya.student_id), [self.r3.id])
        self.assertEqual(ids(q="riya"), [self.r3.id])
        self.assertEqual(ids(q="00002"), [self.r2.id])
        self.assertEqual(ids(start_date="2026-07-01"), [self.r2.id, self.r3.id])
        self.assertEqual(ids(end_date="2026-04-30"), [self.r1.id])
        self.assertEqual(
            self.c.get(URL, {"start_date": "07/01/2026"}).status_code, 400,
        )

    # --- csv ----------------------------------------------------------

    def test_csv_matches_the_sample_columns(self):
        resp = self.c.get(URL, {"output": "csv", "q": "Abhishek"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Receipt Vch.csv", resp["Content-Disposition"])
        text = resp.content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], HEADERS)
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            rows[1],
            ["1/4/2026", "1", "Receipt", "Abhishek Ghosh", "1500", "", "",
             "", "", "Cash", "1500", "UTR012456236",
             "Being Registration Fees received from Abhishek Ghosh — "
             "Receipt JDIFT/2026/00001", "BLR", "", "Receipts"],
        )
        # Voucher numbers restart at 1 for every download.
        self.assertEqual(rows[2][1], "2")

    def test_options(self):
        data = self.c.get(URL + "options/").json()
        self.assertEqual([c["code"] for c in data["campuses"]], ["BLR", "GOA"])
        self.assertEqual({p["code"] for p in data["programs"]}, {"BDES", "DIP"})
        self.assertEqual(data["institutes"][0]["code"], "JDIFT")
