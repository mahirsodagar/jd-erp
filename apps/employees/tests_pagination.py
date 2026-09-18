"""The employee list pages through every row — nothing past the first
100 is dropped, and no row repeats or goes missing between pages."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.employees.models import Employee
from apps.master.models import Campus, Institute
from apps.relieving.tests_notifications import make_employee

User = get_user_model()


class EmployeeListPaginationTests(TestCase):
    TOTAL = 130

    @classmethod
    def setUpTestData(cls):
        institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        for i in range(cls.TOTAL):
            make_employee(f"E{i:03d}", institute=institute, campus=campus)
        # Same timestamp on every row, as a bulk import leaves them —
        # the default `-created_on` order alone can't page these stably.
        Employee.objects.update(created_on=timezone.now())
        cls.admin = User.objects.create_superuser(
            username="admin", email="a@e.com", password="x",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _page(self, page, size):
        r = self.client.get("/api/employees/", {"page": page, "page_size": size})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_count_is_the_full_total(self):
        self.assertEqual(self._page(1, 100)["count"], self.TOTAL)

    def test_walking_the_pages_returns_every_employee_once(self):
        seen = []
        page = 1
        while True:
            data = self._page(page, 50)
            seen += [row["id"] for row in data["results"]]
            if not data["next"]:
                break
            page += 1
        self.assertEqual(page, 3)
        self.assertEqual(len(seen), self.TOTAL)
        self.assertEqual(len(set(seen)), self.TOTAL)
