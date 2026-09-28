"""`?output=csv` on the Student and Lead lists — legacy JD_ERP
"Student Data.csv" / "Lead Master.csv"."""

import csv
import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.admissions.models import Student
from apps.leads.models import Lead, LeadUtm
from apps.master.models import AcademicYear, Campus, Institute, LeadSource, Program
from apps.roles.models import Permission, Role
from apps.roles.seed import seed_permissions

User = get_user_model()


def _read(resp):
    body = resp.content.decode("utf-8")
    assert body.startswith("﻿")
    return list(csv.reader(io.StringIO(body.lstrip("﻿"))))


class ListCsvExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.campus = Campus.objects.create(name="Bengaluru", code="BLR")
        program = Program.objects.create(
            name="B.Des Fashion", code="BDES-F", institute=institute,
        )
        year = AcademicYear.objects.create(
            code="2026-27", start_date="2026-06-01", end_date="2027-05-31",
        )
        Student.objects.create(
            institute=institute, campus=cls.campus, program=program,
            academic_year=year, student_name="Asha", gender="F",
            dob="2006-01-02", nationality="INDIAN", father_name="Ravi",
            student_mobile="9900112233", student_email="asha@example.com",
        )
        source = LeadSource.objects.create(name="Website", slug="website")
        lead = Lead.objects.create(
            name="Kiran", email="kiran@example.com", phone="+919900112244",
            campus=cls.campus, program=program, source=source,
        )
        LeadUtm.objects.create(lead=lead, utm_source="google")
        Lead.objects.create(  # no UTM row
            name="Meera", email="meera@example.com", phone="+919900112255",
            campus=cls.campus, program=program, source=source,
        )
        cls.root = User.objects.create_superuser(
            username="root", email="r@e.com", password="x",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.root)

    def test_student_data_csv(self):
        r = self.client.get("/api/admissions/students/?output=csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="Student Data.csv"', r["Content-Disposition"])
        rows = _read(r)
        head = rows[0]
        self.assertEqual(head[:3], ["SL NO", "Student ID", "Registration No"])
        self.assertIn("Father Name", head)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][head.index("Name")], "Asha")
        self.assertEqual(rows[1][head.index("Father Name")], "Ravi")
        self.assertEqual(rows[1][head.index("DOB")], "02-01-2006")

    def test_student_csv_hides_sensitive_columns_without_permission(self):
        seed_permissions()
        perm = Permission.objects.get(key="admissions.student.view")
        role = Role.objects.create(name="Viewer")
        role.permissions.add(perm)
        user = User.objects.create_user(username="v", email="v@e.com",
                                        password="x")
        user.roles.add(role)
        user.campuses.add(self.campus)
        self.client.force_authenticate(user)
        rows = _read(self.client.get("/api/admissions/students/?output=csv"))
        for col in ("DOB", "Father Name", "Current Address", "Gender"):
            self.assertNotIn(col, rows[0])
        self.assertIn("Phone No", rows[0])
        self.assertEqual(len(rows), 2)

    def test_lead_master_csv(self):
        r = self.client.get("/api/leads/?output=csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn('filename="Lead Master.csv"', r["Content-Disposition"])
        rows = _read(r)
        head = rows[0]
        self.assertEqual(head[:4], ["Sl no", "Created on", "Assigned To", "Name"])
        by_name = {row[head.index("Name")]: row for row in rows[1:]}
        self.assertEqual(by_name["Kiran"][head.index("utm_source")], "google")
        self.assertEqual(by_name["Meera"][head.index("utm_source")], "")


class ListFilterTests(TestCase):
    """Batch filter on students, created-date range on leads."""

    @classmethod
    def setUpTestData(cls):
        from datetime import datetime, timezone as tz

        from apps.admissions.models import Enrollment
        from apps.master.models import Batch, Semester

        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Bengaluru", code="BLR")
        program = Program.objects.create(
            name="B.Des Fashion", code="BDES-F", institute=institute,
        )
        year = AcademicYear.objects.create(
            code="2026-27", start_date="2026-06-01", end_date="2027-05-31",
        )
        cls.batch = Batch.objects.create(
            name="BDES-A", program=program, campus=campus, academic_year=year,
        )
        common = dict(institute=institute, campus=campus, program=program,
                      academic_year=year, gender="F", dob="2006-01-02",
                      nationality="INDIAN")
        asha = Student.objects.create(
            student_name="Asha", student_mobile="9900112233",
            student_email="asha@example.com", application_form_id="T-1",
            **common,
        )
        Student.objects.create(
            student_name="Bina", student_mobile="9900112234",
            student_email="bina@example.com", application_form_id="T-2",
            **common,
        )
        Enrollment.objects.create(
            student=asha, program=program,
            semester=Semester.objects.create(name="Sem 1", number=1),
            campus=campus, batch=cls.batch, academic_year=year,
            status=Enrollment.Status.ACTIVE,
        )

        source = LeadSource.objects.create(name="Website", slug="website")
        for name, phone, when in (
            ("Old", "+919900112244", datetime(2026, 1, 10, 6, tzinfo=tz.utc)),
            ("New", "+919900112255", datetime(2026, 9, 10, 6, tzinfo=tz.utc)),
        ):
            lead = Lead.objects.create(
                name=name, email=f"{name}@example.com", phone=phone,
                campus=campus, program=program, source=source,
            )
            Lead.objects.filter(pk=lead.pk).update(created_at=when)
        cls.root = User.objects.create_superuser(
            username="root", email="r@e.com", password="x",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.root)

    def test_students_filter_by_batch(self):
        url = f"/api/admissions/students/?batch={self.batch.pk}"
        names = [s["student_name"] for s in self.client.get(url).data]
        self.assertEqual(names, ["Asha"])
        rows = _read(self.client.get(url + "&output=csv"))
        self.assertEqual(len(rows), 2)

    def test_leads_filter_by_created_range(self):
        url = "/api/leads/?created_after=2026-09-01&created_before=2026-09-30"
        self.assertEqual([l["name"] for l in self.client.get(url).data], ["New"])
        rows = _read(self.client.get(url + "&output=csv"))
        self.assertEqual([r[3] for r in rows[1:]], ["New"])
