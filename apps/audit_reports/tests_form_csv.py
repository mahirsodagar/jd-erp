"""Every form built in the Audit Forms builder can have its responses
downloaded as CSV: one row per submission, one column per question."""

import csv
import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit_reports.models import (
    AuditAnswer, AuditForm, AuditFormField, AuditSubmission,
)
from apps.roles.models import Permission, Role
from apps.roles.seed import seed_permissions

User = get_user_model()


class FormResponsesCsvTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_permissions()
        cls.auditor = User.objects.create_user("aud", "aud@e.com", "x", full_name="Aud Itor")
        role = Role.objects.create(name="T-Auditor")
        role.permissions.add(Permission.objects.get(key="audit.submission.view_all"))
        cls.auditor.roles.add(role)
        cls.filler = User.objects.create_user("fac", "fac@e.com", "x", full_name="Fay Culty")

        cls.form = AuditForm.objects.create(title="Lab Safety / Q3", status="PUBLISHED")
        cls.f_text = AuditFormField.objects.create(
            form=cls.form, label="Lab name", field_type="TEXT", sort_order=1)
        cls.f_multi = AuditFormField.objects.create(
            form=cls.form, label="Issues seen", field_type="CHECKBOX",
            options=["Wiring", "Spill", "Other"], sort_order=2)
        cls.f_rating = AuditFormField.objects.create(
            form=cls.form, label="Rating", field_type="RATING", sort_order=3)

        s = AuditSubmission.objects.create(form=cls.form, submitted_by=cls.filler)
        AuditAnswer.objects.create(submission=s, field=cls.f_text, value="Textile lab, 2nd floor")
        AuditAnswer.objects.create(submission=s, field=cls.f_multi, value=["Wiring", "Spill"])
        AuditAnswer.objects.create(submission=s, field=cls.f_rating, value=4)
        # A second, partial submission: rating left blank.
        s2 = AuditSubmission.objects.create(form=cls.form, submitted_by=cls.filler)
        AuditAnswer.objects.create(submission=s2, field=cls.f_text, value='Says "ok"')

    def _csv(self, user, **params):
        c = APIClient()
        c.force_authenticate(user)
        r = c.get(f"/api/audit-reports/forms/{self.form.id}/responses.csv", params)
        return r

    def test_one_row_per_submission_one_column_per_question(self):
        r = self._csv(self.auditor)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("Lab Safety _ Q3 - Responses.csv", r["Content-Disposition"])
        body = r.content.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(body)))
        self.assertEqual(rows[0], ["Sr No", "Submitted by", "Emp code", "Submitted on",
                                   "Lab name", "Issues seen", "Rating"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][1], "Fay Culty")
        self.assertEqual(rows[1][4:], ["Textile lab, 2nd floor", "Wiring; Spill", "4"])
        self.assertEqual(rows[2][4:], ['Says "ok"', "", ""])

    def test_requires_view_all(self):
        self.assertEqual(self._csv(self.filler).status_code, 403)

    def test_date_filter(self):
        r = self._csv(self.auditor, **{"from": "2099-01-01"})
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 1)  # header only
