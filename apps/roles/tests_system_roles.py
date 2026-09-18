"""Faculty, HOD and HR are permanent roles, like Admin: they can't be
deleted or renamed, but their description and permissions stay editable."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.roles.models import Role

User = get_user_model()


class SystemRoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="root", email="root@e.com", password="x",
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_roles_exist_and_are_system(self):
        for name in ("Faculty", "HOD", "HR"):
            self.assertTrue(Role.objects.get(name=name).is_system, name)

    def test_cannot_delete(self):
        for name in ("Faculty", "HOD", "HR"):
            role = Role.objects.get(name=name)
            r = self.client.delete(f"/api/roles/{role.id}/")
            self.assertEqual(r.status_code, 400, name)
            self.assertTrue(Role.objects.filter(pk=role.id).exists())

    def test_cannot_rename(self):
        role = Role.objects.get(name="HOD")
        r = self.client.patch(f"/api/roles/{role.id}/", {"name": "Head"},
                              format="json")
        self.assertEqual(r.status_code, 400)
        role.refresh_from_db()
        self.assertEqual(role.name, "HOD")

    def test_description_still_editable(self):
        role = Role.objects.get(name="HR")
        r = self.client.patch(f"/api/roles/{role.id}/",
                              {"name": "HR", "description": "People team"},
                              format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_ordinary_role_still_deletable(self):
        role = Role.objects.create(name="Temp")
        self.assertEqual(self.client.delete(f"/api/roles/{role.id}/").status_code, 204)
