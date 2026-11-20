"""The staff ID card: one 2-page PDF per employee, design by institute,
behind `employees.employee.id_card`."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.employees.services_idcard import render_id_card
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee
from apps.roles.models import Permission, Role

User = get_user_model()


class EmployeeIdCardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        campus = Campus.objects.create(name="Main", code="MAIN")
        jdift = Institute.objects.create(name="JDIFT", code="JDIFT")
        jdsd = Institute.objects.create(name="JDSD", code="JDSD")
        cls.jdift_emp = make_employee("JUGAL", institute=jdift, campus=campus,
                                      mobile_alternate="+919113945281")
        cls.jdsd_emp = make_employee("NEALESH", institute=jdsd, campus=campus)
        cls.admin = User.objects.create_superuser(
            username="hr", email="hr@e.com", password="x", full_name="HR",
        )
        cls.viewer = User.objects.create_user(
            username="v", email="v@e.com", password="x", full_name="Viewer",
        )
        cls.viewer.campuses.add(campus)
        role = Role.objects.create(name="Viewer")
        view_perm, _ = Permission.objects.get_or_create(
            key="employees.employee.view", defaults={"module": "employees", "label": "View"},
        )
        role.permissions.add(view_perm)
        cls.viewer.roles.add(role)

    def test_each_institute_renders_a_two_page_pdf(self):
        for emp in (self.jdift_emp, self.jdsd_emp):
            pdf = render_id_card(emp)
            self.assertTrue(pdf.startswith(b"%PDF"))
            self.assertEqual(pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page\r"), 2, emp)

    def test_endpoint_serves_pdf_to_admin(self):
        c = APIClient()
        c.force_authenticate(user=self.admin)
        r = c.get(f"/api/employees/{self.jdift_emp.id}/id-card.pdf")
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertIn("Jugal_ID_Card.pdf", r["Content-Disposition"])

    def test_endpoint_needs_the_id_card_key(self):
        c = APIClient()
        c.force_authenticate(user=self.viewer)
        r = c.get(f"/api/employees/{self.jdift_emp.id}/id-card.pdf")
        self.assertEqual(r.status_code, 403)
