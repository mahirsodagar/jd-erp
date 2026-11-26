"""Student ID card: single download + batch PDF."""

import io
import shutil
import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.admissions.models import Enrollment, Student
from apps.admissions.services_idcard import (
    CardData, render_batch_id_cards, render_id_card,
)
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, Program, Semester, University,
)
from apps.roles.models import Permission, Role

MEDIA = tempfile.mkdtemp()


def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (120, 160), (200, 120, 90)).save(buf, format="PNG")
    return buf.getvalue()


def _user_with(*keys):
    user = get_user_model().objects.create_user(
        username="hr-" + "-".join(k.split(".")[-1] for k in keys),
        email="hr-" + "-".join(k.split(".")[-1] for k in keys) + "@example.com",
        password="x",
    )
    role = Role.objects.create(name="r-" + user.username)
    for key in keys:
        perm, _ = Permission.objects.get_or_create(
            key=key, defaults={"module": key.split(".")[0], "label": key},
        )
        role.permissions.add(perm)
    user.roles.add(role)
    return user


@override_settings(MEDIA_ROOT=MEDIA)
class IdCardTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.jdift = Institute.objects.create(
            name="JD Institute of Fashion Technology", code="JDIFT",
        )
        cls.jdsd = Institute.objects.create(
            name="JD School of Design", code="JDSD",
        )
        cls.campus = Campus.objects.create(
            name="Bengaluru", code="BLR", city="Bengaluru",
        )
        cls.year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1),
            end_date=date(2027, 5, 31),
        )
        cls.sem = Semester.objects.create(name="Sem 1", number=1)
        cls.p_jdift = Program.objects.create(
            name="Diploma in Interior Design", code="DID",
            institute=cls.jdift, duration_months=16,
        )
        cls.p_jdsd = Program.objects.create(
            name="BSc - Fashion & Apparel Design", code="BSCFAD",
            institute=cls.jdsd, duration_months=40,
            id_card_affiliation="Affiliated to Dr. MS Bengaluru City University",
        )
        cls.b_jdift = Batch.objects.create(
            name="DID JUN 2026", short_name="DID JUN2026",
            program=cls.p_jdift, campus=cls.campus, academic_year=cls.year,
        )
        cls.b_jdsd = Batch.objects.create(
            name="BSc FAD 2026", program=cls.p_jdsd, campus=cls.campus,
            academic_year=cls.year,
        )

    def _student(self, name, institute, program, batch, *, reg="",
                 photo=True, status=Enrollment.Status.ACTIVE):
        n = Student.objects.count() + 1
        s = Student.objects.create(
            application_form_id=f"{institute.code}-2026-{n:04d}",
            student_name=name, gender="F", dob=date(2004, 1, 1),
            nationality="IN", institute=institute, campus=self.campus,
            program=program, academic_year=self.year, blood_group="O+",
            registration_number=reg,
        )
        if photo:
            s.photo.save("p.png", ContentFile(_png()), save=True)
        e = Enrollment.objects.create(
            student=s, program=program, course=None, semester=self.sem,
            campus=self.campus, batch=batch, academic_year=self.year,
            status=status,
        )
        return s, e

    # --- data resolution ------------------------------------------------

    def test_card_data_resolves_fields(self):
        s, e = self._student("Aishwarya S Raj", self.jdift, self.p_jdift,
                             self.b_jdift, reg="2253BBID1JUN2026")
        d = CardData(s, e)
        self.assertEqual(d.institute_code, "JDIFT")
        self.assertEqual(d.id_number, "2253BBID1JUN2026")
        self.assertEqual(d.centre, "Bengaluru")
        # June 2026 + 16 months = October 2027.
        self.assertEqual(d.valid_till, date(2027, 10, 1))

    def test_id_number_falls_back_to_app_id(self):
        s, e = self._student("Aiysha Salim", self.jdsd, self.p_jdsd, self.b_jdsd)
        d = CardData(s, e)
        self.assertEqual(d.id_number, s.application_form_id)
        self.assertEqual(d.batch_label, "BSc FAD 2026")
        self.assertEqual(d.affiliation,
                         "Affiliated to Dr. MS Bengaluru City University")

    def test_affiliation_falls_back_to_the_program_university(self):
        """JDSD cards name the university even when nobody typed an
        affiliation line: it comes off Program.university."""
        # master.0018 seeds the universities, so pick it up rather than
        # colliding with the unique code.
        uni, _ = University.objects.get_or_create(
            code="MSBCU",
            defaults={"name": "Dr. MS Bengaluru City University"})
        p = Program.objects.create(
            name="BSc Interior Design", code="BSCID", institute=self.jdsd,
            duration_months=36, university=uni,
        )
        b = Batch.objects.create(name="BSc ID 2026", program=p,
                                 campus=self.campus, academic_year=self.year)
        s, e = self._student("Y", self.jdsd, p, b)
        self.assertEqual(CardData(s, e).affiliation,
                         f"Affiliated to {uni.name}")
        # JD-certified: no university, no line.
        s2, e2 = self._student("Z", self.jdift, self.p_jdift, self.b_jdift)
        self.assertEqual(CardData(s2, e2).affiliation, "")

    def test_address_block_comes_from_the_centre(self):
        """Each centre's card carries that centre's address; a campus with
        nothing on file keeps the printed Bengaluru block."""
        goa = Campus.objects.create(
            name="Goa", code="GOA", city="Panaji",
            address="2nd Floor, Alfran Plaza\nMG Road, Panaji - 403 001",
            phone="0832 242 0001", phone_alt="+91 98220 00001",
        )
        s, e = self._student("G", self.jdift, self.p_jdift, self.b_jdift)
        Enrollment.objects.filter(pk=e.pk).update(campus=goa)
        e.refresh_from_db()
        self.assertEqual(CardData(s, e).address_lines, (
            "2nd Floor, Alfran Plaza",
            "MG Road, Panaji - 403 001",
            "Contact : 0832 242 0001 / +91 98220 00001",
        ))
        s2, e2 = self._student("H", self.jdsd, self.p_jdsd, self.b_jdsd)
        Enrollment.objects.filter(pk=e2.pk).update(campus=goa)
        e2.refresh_from_db()
        self.assertEqual(CardData(s2, e2).address_lines, (
            "2ND FLOOR, ALFRAN PLAZA",
            "MG ROAD, PANAJI - 403 001",
            "0832 242 0001 / +91 98220 00001",
            "www.jdsd.in",
        ))
        # Nothing on file (the shared Bengaluru fixture) -> reference block.
        s3, e3 = self._student("I", self.jdift, self.p_jdift, self.b_jdift)
        self.assertEqual(CardData(s3, e3).address_lines[-1],
                         "Contact : 080 22279927")
        # And both render.
        for student, enrol in ((s, e), (s2, e2)):
            self.assertTrue(render_id_card(student, enrol).startswith(b"%PDF"))

    def test_long_address_wraps_at_fixed_size_to_three_rows(self):
        """Client 2026-11-26: the font never shrinks for a long address;
        it wraps onto at most three rows, phones share a fourth."""
        from fpdf import FPDF
        from apps.admissions.services_idcard import (
            CARD_W, ContactBlock, wrap_contact_rows,
        )
        block = ContactBlock(
            ("Third Floor, Sunshine Towers, Opposite Central Mall, "
             "Banjara Hills Main Road, Road No. 12, Hyderabad - 500 034, "
             "Telangana, India",),
            ("Contact : 040 2355 0007 / +91 98490 00007",),
        )
        pdf = FPDF(unit="mm", format=(54, 85))
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 8.2)
        rows = wrap_contact_rows(pdf, block, CARD_W - 4)
        # Three address rows, then the contact row (itself wrapped when
        # two numbers are too wide), every row inside the width.
        self.assertTrue(rows[3].startswith("Contact :"))
        self.assertTrue(block[0].startswith(" ".join(rows[:3])))
        for row in rows:
            self.assertLessEqual(pdf.get_string_width(row), CARD_W - 4)
        self.assertEqual(pdf.font_size_pt, 8.2)
        # A short block passes through untouched.
        short = ContactBlock(("No.18, Edward House,",), ("Contact : 080",))
        self.assertEqual(wrap_contact_rows(pdf, short, CARD_W - 4),
                         ["No.18, Edward House,", "Contact : 080"])

    def test_valid_till_without_duration_uses_year_end(self):
        self.p_jdift.duration_months = None
        self.p_jdift.save()
        s, e = self._student("X", self.jdift, self.p_jdift, self.b_jdift)
        self.assertEqual(CardData(s, e).valid_till, date(2027, 5, 31))
        self.p_jdift.duration_months = 16
        self.p_jdift.save()

    # --- rendering ----------------------------------------------------

    def test_render_both_designs(self):
        s1, _ = self._student("Aishwarya S Raj", self.jdift, self.p_jdift,
                              self.b_jdift)
        s2, _ = self._student("Aiysha Salim", self.jdsd, self.p_jdsd,
                              self.b_jdsd, photo=False)
        for s in (s1, s2):
            pdf = render_id_card(s)
            self.assertTrue(pdf.startswith(b"%PDF"))
            pages = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
            self.assertEqual(pages, 2)

    def test_render_without_enrollment(self):
        s = Student.objects.create(
            application_form_id="JDSD-2026-9999",
            student_name="No Batch", gender="M", dob=date(2004, 1, 1),
            nationality="IN", institute=self.jdsd, campus=self.campus,
            program=self.p_jdsd, academic_year=self.year,
        )
        self.assertTrue(render_id_card(s).startswith(b"%PDF"))

    def test_batch_pdf_only_active_students(self):
        self._student("A", self.jdsd, self.p_jdsd, self.b_jdsd)
        self._student("B", self.jdsd, self.p_jdsd, self.b_jdsd)
        self._student("C", self.jdsd, self.p_jdsd, self.b_jdsd,
                      status=Enrollment.Status.DROPPED)
        pdf, n = render_batch_id_cards(self.b_jdsd)
        self.assertEqual(n, 2)
        self.assertTrue(pdf.startswith(b"%PDF"))

    # --- endpoints ----------------------------------------------------

    def test_student_endpoint_needs_id_card_key(self):
        s, _ = self._student("A", self.jdift, self.p_jdift, self.b_jdift)
        url = reverse("student-id-card", args=[s.pk])

        viewer = _user_with("admissions.student.view",
                            "admissions.student.view_all_campuses")
        c = APIClient()
        c.force_authenticate(viewer)
        self.assertEqual(c.get(url).status_code, 403)

        allowed = _user_with("admissions.student.view",
                             "admissions.student.view_all_campuses",
                             "admissions.student.id_card")
        c.force_authenticate(allowed)
        r = c.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("_ID_Card.pdf", r["Content-Disposition"])

    def test_batch_endpoint(self):
        self._student("A", self.jdsd, self.p_jdsd, self.b_jdsd)
        url = reverse("batch-report-id-cards", args=[self.b_jdsd.pk])

        roster_only = _user_with("academics.batch_report.view_roster",
                                 "academics.batch_report.view_all_campuses")
        c = APIClient()
        c.force_authenticate(roster_only)
        self.assertEqual(c.get(url).status_code, 403)

        ok = _user_with("academics.batch_report.view_roster",
                        "academics.batch_report.view_all_campuses",
                        "admissions.student.id_card")
        c.force_authenticate(ok)
        r = c.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("_ID_Cards.pdf", r["Content-Disposition"])
