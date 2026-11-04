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
    AcademicYear, Batch, Campus, Institute, Program, Semester,
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
        self.assertIn("id-card-", r["Content-Disposition"])

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
        self.assertIn("id-cards.pdf", r["Content-Disposition"])
