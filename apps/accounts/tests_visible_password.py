"""Admin -> Users shows each user's CURRENT password (client decision
2026-11-24): every path that sets a password writes the plain-text copy,
and only `accounts.user.reset_password` holders can read it."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.roles.models import Permission, Role

User = get_user_model()


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class VisiblePasswordTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="admin", password="Admin#Pass1", email="admin@example.com")
        cls.staff = User.objects.create_user(
            username="fac1", password="First#Pass1", email="fac1@example.com",
            full_name="Ann Rao")
        # Can list users but not reset passwords.
        cls.viewer = User.objects.create_user(
            username="viewer", password="Viewer#Pass1", email="v@example.com")
        role = Role.objects.create(name="Viewer")
        for key in ("accounts.user.view",):
            perm, _ = Permission.objects.get_or_create(
                key=key, defaults={"module": "accounts", "label": key})
            role.permissions.add(perm)
        cls.viewer.roles.add(role)

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def _shown(self, viewer, target):
        r = self._client(viewer).get(reverse("user-detail", args=[target.pk]))
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["visible_password"]

    def test_create_records_the_temporary_password(self):
        self.staff.refresh_from_db()
        self.assertEqual(self.staff.visible_password, "First#Pass1")
        self.assertTrue(self.staff.check_password("First#Pass1"))

    def test_admin_reset_updates_the_copy_and_the_detail_shows_it(self):
        r = self._client(self.admin).post(
            reverse("user-reset-password", args=[self.staff.pk]),
            {"new_password": "Temp#Pass2026"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._shown(self.admin, self.staff), "Temp#Pass2026")
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.check_password("Temp#Pass2026"))

    def test_self_change_updates_the_copy(self):
        r = self._client(self.staff).post(
            reverse("change-password"),
            {"current_password": "First#Pass1", "new_password": "Mine#Pass2026"},
            format="json")
        self.assertIn(r.status_code, (200, 204), r.content)
        self.assertEqual(self._shown(self.admin, self.staff), "Mine#Pass2026")

    def test_only_reset_permission_holders_see_it(self):
        self.assertEqual(self._shown(self.viewer, self.staff), "")
        # Not even one's own, without the key.
        r = self._client(self.staff).get(reverse("me"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("visible_password", ""), "")

    def test_list_carries_it_for_admins_only(self):
        rows = self._client(self.admin).get(reverse("user-list-create")).json()
        by_name = {u["username"]: u for u in rows}
        self.assertEqual(by_name["fac1"]["visible_password"], "First#Pass1")
        rows = self._client(self.viewer).get(reverse("user-list-create")).json()
        by_name = {u["username"]: u for u in rows}
        self.assertEqual(by_name["fac1"]["visible_password"], "")
