"""Leave report CSV matches the legacy JD_ERP "Leave Report.csv" export."""

import csv
import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

User = get_user_model()

REPORT = "/api/leaves/reports/summary/?start_date=2026-06-01&end_date=2027-05-31"


class LeaveReportCsvTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(
            User.objects.create_superuser(username="root", email="r@e.com",
                                          password="x"),
        )

    def test_csv_download(self):
        r = self.client.get(REPORT + "&output=csv")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("text/csv"))
        self.assertIn('filename="Leave Report.csv"', r["Content-Disposition"])
        body = r.content.decode("utf-8")
        self.assertTrue(body.startswith("﻿"))
        header = next(csv.reader(io.StringIO(body.lstrip("﻿"))))
        self.assertEqual(header[:3], ["Sl No.", "Employee Code", "Employee Name"])
        self.assertIn("Leave Status", header)

    def test_csv_needs_auth(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(REPORT + "&output=csv").status_code, 401)
