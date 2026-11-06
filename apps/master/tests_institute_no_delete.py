"""An Institute can be disabled but never deleted (user rule 2026-11-06).

The API has no DELETE, the admin refuses, and the ORM refuses at both
the instance and the queryset level so nothing cascades through
programs, enrolments and receipts by accident.
"""

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from rest_framework.test import APIClient

from apps.master.models import Institute, InstituteDeletionRefused

User = get_user_model()


class InstituteNoDeleteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="a", email="a@e.com", password="x",
        )
        cls.inst = Institute.objects.create(name="Inst", code="INST")

    def test_instance_delete_refuses(self):
        with self.assertRaises(InstituteDeletionRefused):
            self.inst.delete()
        self.assertTrue(Institute.objects.filter(pk=self.inst.pk).exists())

    def test_queryset_delete_refuses(self):
        with self.assertRaises(InstituteDeletionRefused):
            Institute.objects.filter(pk=self.inst.pk).delete()
        with self.assertRaises(InstituteDeletionRefused):
            Institute.objects.all().delete()
        self.assertTrue(Institute.objects.filter(pk=self.inst.pk).exists())

    def test_api_has_no_delete_but_can_disable(self):
        c = APIClient()
        c.force_authenticate(self.admin)
        url = f"/api/master/institutes/{self.inst.pk}/"
        r = c.delete(url)
        self.assertEqual(r.status_code, 405, r.content)
        self.inst.refresh_from_db()
        self.assertTrue(self.inst.is_active)

        r = c.patch(url, {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.inst.refresh_from_db()
        self.assertFalse(self.inst.is_active)

        r = c.patch(url, {"is_active": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.inst.refresh_from_db()
        self.assertTrue(self.inst.is_active)

    def test_admin_refuses_delete(self):
        model_admin = site._registry[Institute]
        request = RequestFactory().get("/admin/")
        request.user = self.admin
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request, self.inst))
