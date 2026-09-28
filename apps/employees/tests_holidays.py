"""HR → Holiday Calendar (legacy hr/holiday_calender.php)."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.academics.tests_electives import make_faculty
from apps.employees.models import Holiday
from apps.master.models import Campus, Institute

User = get_user_model()


class HolidayCalendarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.main = Campus.objects.create(name="Main", code="MAIN")
        cls.other = Campus.objects.create(name="North", code="NORTH")
        cls.faculty = make_faculty(
            code="E1", name="Ann", campus=cls.main, institute=institute,
        )
        cls.user = User.objects.create_user(username="ann", email="ann@example.com", password="x")
        cls.faculty.user_account = cls.user
        cls.faculty.save(update_fields=["user_account"])
        cls.admin = User.objects.create_superuser(
            username="admin", password="x", email="a@example.com",
        )
        Holiday.objects.create(campus=cls.main, date=date(2026, 10, 2),
                               name="Gandhi Jayanti")
        Holiday.objects.create(campus=cls.main, date=date(2027, 1, 26),
                               name="Republic Day")
        Holiday.objects.create(campus=cls.other, date=date(2026, 10, 20),
                               name="Diwali")

    def setUp(self):
        self.client = APIClient()
        self.list_url = reverse("holiday-list-create")

    def test_employee_sees_own_campus_for_the_year(self):
        self.client.force_authenticate(self.user)
        res = self.client.get(self.list_url, {"year": 2026})
        self.assertEqual(res.status_code, 200)
        self.assertEqual([h["name"] for h in res.data], ["Gandhi Jayanti"])

    def test_other_campus_by_param(self):
        self.client.force_authenticate(self.user)
        res = self.client.get(self.list_url,
                              {"year": 2026, "campus": self.other.id})
        self.assertEqual([h["name"] for h in res.data], ["Diwali"])

    def test_employee_cannot_add(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(self.list_url, {
            "campus": self.main.id, "date": "2026-12-25", "name": "Christmas",
        }, format="json")
        self.assertEqual(res.status_code, 403)

    def test_admin_add_edit_delete(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(self.list_url, {
            "campus": self.main.id, "date": "2026-12-25", "name": "Christmas",
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        url = reverse("holiday-detail", args=[res.data["id"]])
        res = self.client.patch(url, {"name": "Xmas"}, format="json")
        self.assertEqual(res.data["name"], "Xmas")
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_one_holiday_per_campus_per_date(self):
        self.client.force_authenticate(self.admin)
        res = self.client.post(self.list_url, {
            "campus": self.main.id, "date": "2026-10-02", "name": "Dup",
        }, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("date", res.data)
        # Same date on another campus is fine.
        res = self.client.post(self.list_url, {
            "campus": self.other.id, "date": "2026-10-02", "name": "Gandhi",
        }, format="json")
        self.assertEqual(res.status_code, 201)
