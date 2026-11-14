"""Duplicating an audit form copies its questions and roles into a new
draft owned by the caller, leaving the original and its responses alone."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.audit_reports.models import (
    AuditAnswer, AuditForm, AuditFormField, AuditSubmission,
)
from apps.roles.models import Permission, Role
from apps.roles.seed import seed_permissions

User = get_user_model()


class FormDuplicateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_permissions()
        cls.owner = User.objects.create_user("own", "own@e.com", "x")
        cls.maker = User.objects.create_user("mk", "mk@e.com", "x")
        role = Role.objects.create(name="T-Maker")
        role.permissions.add(Permission.objects.get(key="audit.form.add"))
        cls.maker.roles.add(role)
        cls.plain = User.objects.create_user("pl", "pl@e.com", "x")

        cls.target = Role.objects.create(name="T-Faculty")
        cls.form = AuditForm.objects.create(
            title="Lab Safety", description="Quarterly check",
            status="PUBLISHED", created_by=cls.owner)
        cls.form.roles.add(cls.target)
        AuditFormField.objects.create(
            form=cls.form, label="Lab", field_type="TEXT", required=True,
            help_text="Which lab", sort_order=2)
        AuditFormField.objects.create(
            form=cls.form, label="Issues", field_type="CHECKBOX",
            options=["Wiring", "Spill"], config={"max": 2}, sort_order=1)
        s = AuditSubmission.objects.create(form=cls.form, submitted_by=cls.owner)
        AuditAnswer.objects.create(submission=s, field=cls.form.fields.first(), value="x")

    def _dup(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c.post(f"/api/audit-reports/forms/{self.form.id}/duplicate/")

    def test_copies_fields_and_roles_as_a_fresh_draft(self):
        r = self._dup(self.maker)
        self.assertEqual(r.status_code, 201, r.content)
        copy = AuditForm.objects.get(pk=r.data["id"])
        self.assertEqual(copy.title, "Lab Safety (Copy)")
        self.assertEqual(copy.description, "Quarterly check")
        self.assertEqual(copy.status, "DRAFT")
        self.assertEqual(copy.created_by, self.maker)
        self.assertEqual(list(copy.roles.all()), [self.target])

        src = list(self.form.fields.all())
        got = list(copy.fields.all())
        self.assertEqual([f.label for f in got], [f.label for f in src])
        self.assertEqual([f.sort_order for f in got], [f.sort_order for f in src])
        self.assertEqual(got[0].options, ["Wiring", "Spill"])
        self.assertEqual(got[0].config, {"max": 2})
        self.assertTrue(got[1].required)
        self.assertEqual(got[1].help_text, "Which lab")

        # Nothing about the original moved, and no responses were copied.
        self.form.refresh_from_db()
        self.assertEqual(self.form.status, "PUBLISHED")
        self.assertEqual(self.form.submissions.count(), 1)
        self.assertEqual(copy.submissions.count(), 0)

    def test_second_copy_gets_a_numbered_title(self):
        self._dup(self.maker)
        r = self._dup(self.maker)
        self.assertEqual(r.data["title"], "Lab Safety (Copy 2)")

    def test_needs_form_add(self):
        self.assertEqual(self._dup(self.plain).status_code, 403)
