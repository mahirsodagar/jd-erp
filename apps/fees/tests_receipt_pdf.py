"""Receipt PDF + receipt number format.

The PDF is binary, so these assert the things that actually break in
production — the amount-in-words wording, which columns the tax split
adds, that a missing logo or blank letterhead still renders, and that
the number sequence keeps counting per campus-year without tripping over
legacy `RCP-` numbers.
"""

import io
from datetime import date
from decimal import Decimal

from django.core.files.base import ContentFile
from django.test import TestCase

from apps.admissions.models import Enrollment, Student
from apps.common.program_policies import policy_for
from apps.fees.models import FeeReceipt
from apps.fees.services.pdf import amount_in_words, render_receipt_pdf
from apps.fees.services.receipt_no import generate_receipt_no
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester,
)


class AmountInWordsTests(TestCase):

    def test_matches_paper_receipts(self):
        self.assertEqual(amount_in_words(65000),
                         "Sixty Five Thousand Rupees Only/-")
        self.assertEqual(amount_in_words(75000),
                         "Seventy Five Thousand Rupees Only/-")

    def test_lakhs_and_crores_use_indian_grouping(self):
        self.assertEqual(amount_in_words(150000),
                         "One Lakh Fifty Thousand Rupees Only/-")
        self.assertEqual(amount_in_words(12500000),
                         "One Crore Twenty Five Lakh Rupees Only/-")

    def test_paise_and_zero(self):
        self.assertEqual(amount_in_words(Decimal("100.50")),
                         "One Hundred Rupees and Fifty Paise Only/-")
        self.assertEqual(amount_in_words(0), "Zero Rupees Only/-")


class ReceiptNumberTests(TestCase):

    def test_format_and_sequence_per_campus_year(self):
        self.assertEqual(generate_receipt_no(campus_code="bng", year=2026),
                         "JDBNG0001-2026")

    def test_ignores_legacy_and_other_campus_numbers(self):
        base = _fixture()
        _receipt(base, receipt_no="RCP-BNG-2026-00042")
        _receipt(base, receipt_no="JDBNG0007-2026")
        _receipt(base, receipt_no="JDBNG0009-2025")   # different year
        _receipt(base, receipt_no="JDGOA0011-2026")   # different campus
        self.assertEqual(generate_receipt_no(campus_code="BNG", year=2026),
                         "JDBNG0008-2026")

    def test_serial_widens_past_four_digits(self):
        base = _fixture()
        _receipt(base, receipt_no="JDBNG9999-2026")
        self.assertEqual(generate_receipt_no(campus_code="BNG", year=2026),
                         "JDBNG10000-2026")


class PolicyPageTests(TestCase):

    def test_diploma_vs_degree_document(self):
        self.assertEqual(policy_for("Diploma")[0][1],
                         "DIPLOMA PROGRAM POLICIES")
        self.assertEqual(policy_for("M.Sc")[0][1], "BSC/MSC PROGRAM POLICIES")
        self.assertEqual(policy_for("")[0][1], "BSC/MSC PROGRAM POLICIES")


class RenderTests(TestCase):

    def test_renders_with_tax_split(self):
        base = _fixture(gstin="29AAEPD3991M2Z8")
        r = _receipt(base, basic_fee=Decimal("55084"), sgst=Decimal("4958"),
                     cgst=Decimal("4958"), amount=Decimal("65000"))
        out = render_receipt_pdf(r)
        self.assertTrue(out.startswith(b"%PDF"))
        self.assertGreater(len(out), 2000)

    def test_renders_without_tax(self):
        base = _fixture(payee_name="JD Educational Trust")
        r = _receipt(base, basic_fee=Decimal("75000"), amount=Decimal("75000"))
        self.assertTrue(render_receipt_pdf(r).startswith(b"%PDF"))

    def test_renders_with_blank_letterhead_and_no_logo(self):
        """A freshly seeded institute has no address, no GSTIN, no logo —
        the receipt must still come out rather than 500."""
        base = _fixture(letterhead=False)
        r = _receipt(base, amount=Decimal("1000"))
        self.assertTrue(render_receipt_pdf(r).startswith(b"%PDF"))

    def test_uploaded_logo_is_embedded(self):
        """The logo prints once a file is actually on the institute.

        Institutes ship with `logo` empty, which is why receipts came out
        with the name in text — so assert the image reaches the PDF, not
        just that rendering survives.
        """
        base = _fixture()
        institute = base.student.institute
        institute.logo.save("logo.png", ContentFile(_png_bytes()), save=True)
        self.addCleanup(institute.logo.delete, save=False)

        out = render_receipt_pdf(_receipt(base, amount=Decimal("1000")))
        # fpdf2 writes embedded raster images as /Image XObjects.
        self.assertIn(b"/Subtype /Image", out)

    def test_a_logo_row_whose_file_went_missing_still_renders(self):
        """Media can be wiped independently of the database — a dangling
        path must fall back to the name, not 500 the download."""
        base = _fixture()
        institute = base.student.institute
        institute.logo.name = "institute/logos/gone.png"
        institute.save(update_fields=["logo"])

        out = render_receipt_pdf(_receipt(base, amount=Decimal("1000")))
        self.assertTrue(out.startswith(b"%PDF"))
        self.assertNotIn(b"/Subtype /Image", out)

    def test_renders_cancelled(self):
        base = _fixture()
        r = _receipt(base, status=FeeReceipt.Status.CANCELLED,
                     cancellation_reason="Duplicate entry")
        self.assertTrue(render_receipt_pdf(r).startswith(b"%PDF"))


# --- fixtures ----------------------------------------------------------

def _png_bytes() -> bytes:
    """A tiny real PNG — fpdf2 decodes the image, so a stub won't do."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 0, 128)).save(buf, format="PNG")
    return buf.getvalue()


def _fixture(*, gstin="", payee_name="", letterhead=True, degree_type="Diploma"):
    institute = Institute.objects.create(
        name="JD Institute of Fashion Technology", code="JDI",
        letterhead_title="Corporate Center" if letterhead else "",
        address="#40, Swan house, 4th cross,\nResidency Road, Bangalore-560025"
                if letterhead else "",
        phone="+91 99019 99903" if letterhead else "",
        email="jdfashion@jdindia.com" if letterhead else "",
        gstin=gstin, payee_name=payee_name,
    )
    campus = Campus.objects.create(name="Bangalore", code="BNG")
    program = Program.objects.create(
        name="Diploma in Fashion Business Management", code="DFBM",
        institute=institute, degree_type=degree_type,
    )
    year = AcademicYear.objects.create(
        code="2026-27", full_name="2026-27", start_date=date(2026, 6, 1),
        end_date=date(2027, 5, 31),
    )
    student = Student.objects.create(
        student_name="Anjalishree BK", father_name="BK Prasanna Kumar",
        gender="F", dob=date(2006, 1, 1), nationality="Indian",
        institute=institute, campus=campus, program=program,
        academic_year=year, current_address="#123, Snehal Residence",
        student_mobile="6366280706", student_email="a@example.com",
    )
    semester = Semester.objects.create(number=1, name="Semester 1",
                                       program=program)
    batch = Batch.objects.create(
        name="DFBM Aug 2026", campus=campus, program=program,
        academic_year=year, start_semester=semester,
    )
    enrollment = Enrollment.objects.create(
        student=student, program=program, campus=campus, batch=batch,
        semester=semester, academic_year=year,
        status=Enrollment.Status.ACTIVE,
    )
    return enrollment


def _receipt(enrollment, **kwargs):
    kwargs.setdefault("receipt_no", f"JDBNG{FeeReceipt.objects.count() + 100}-2026")
    kwargs.setdefault("basic_fee", Decimal("1000"))
    kwargs.setdefault("amount", kwargs["basic_fee"])
    kwargs.setdefault("payment_mode", FeeReceipt.PaymentMode.ONLINE)
    kwargs.setdefault("instrument_ref", "IN42623155106395")
    kwargs.setdefault("received_date", date(2026, 8, 19))
    return FeeReceipt.objects.create(enrollment=enrollment, **kwargs)
