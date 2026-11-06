"""Routing comes from the per-institute Relieving Managers master
(L1–L4); only the snapshotted approver can decide a level; the final
(L4) approval completes the application — letters for RELIEVING,
nothing but the record for PART_TIME."""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.employees.models import Employee
from apps.master.models import Campus, Institute
from apps.relieving import services
from apps.relieving.models import (
    RelievingApplication, RelievingApproval, RelievingManager,
)
from apps.roles.models import Permission, Role
from apps.roles.seed import seed_permissions

from .tests_notifications import make_employee

User = get_user_model()


def set_managers(institute, by_level: dict, user=None):
    services.save_managers(
        institute=institute, updated_by=user,
        levels=[{"level": lvl, "approver": emp} for lvl, emp in by_level.items()],
    )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class RelievingWorkflowTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.inst = Institute.objects.create(name="JD School of Design", code="JDSD")
        cls.other = Institute.objects.create(name="JDIFT", code="JDIFT")
        campus = Campus.objects.create(name="Main", code="MAIN")
        kw = dict(institute=cls.inst, campus=campus)

        def with_login(code, **extra):
            emp = make_employee(code, **kw, **extra)
            emp.user_account = User.objects.create_user(
                code.lower(), emp.email_primary, "x")
            emp.save(update_fields=["user_account"])
            return emp

        cls.m1 = with_login("MGR1")
        cls.m2 = with_login("MGR2")
        cls.principal = with_login("PRINCIPAL")
        cls.hr = with_login("TRUPTI")
        cls.rm = with_login("RM")  # the employee's reporting manager — NOT in the chain
        cls.emp = with_login("EMP1", reporting_manager_1=cls.rm)
        seed_permissions()
        cls.hr_user = User.objects.create_user("hrmanager", "hrm@x.in", "x")
        role = Role.objects.create(name="HR-M")
        role.permissions.set(Permission.objects.filter(
            key__in=["hr.relieving.managers", "hr.relieving.finalize"]))
        cls.hr_user.roles.add(role)

    def setUp(self):
        set_managers(self.inst, {1: self.m1, 2: self.m2,
                                 3: self.principal, 4: self.hr})

    def _client(self, emp_or_user):
        c = APIClient()
        c.force_authenticate(getattr(emp_or_user, "user_account", emp_or_user))
        return c

    def _submit(self, application_type="RELIEVING", expect=201):
        r = self._client(self.emp).post("/api/hr/relieving/", {
            "employee": self.emp.id,
            "application_type": application_type,
            "reason": "Moving on to further studies.",
            "last_working_date_requested": "2026-10-31",
        }, format="json")
        self.assertEqual(r.status_code, expect, r.data)
        return r.data["id"] if expect == 201 else r.data

    def _decide(self, approver, pk, level, decision="APPROVED", expect=200):
        r = self._client(approver).post(
            f"/api/hr/relieving/{pk}/decide/{level}/",
            {"decision": decision, "remarks": f"ok {level}"}, format="json",
        )
        self.assertEqual(r.status_code, expect, r.data)
        return r.data

    def _chain(self, pk):
        return list(RelievingApproval.objects.filter(application_id=pk)
                    .order_by("level").values_list("approver_id", flat=True))

    # --- routing ----------------------------------------------------

    def test_chain_comes_from_the_institute_master_not_reporting_managers(self):
        pk = self._submit()
        self.assertEqual(self._chain(pk), [
            self.m1.id, self.m2.id, self.principal.id, self.hr.id,
        ])
        labels = list(RelievingApproval.objects.filter(application_id=pk)
                      .order_by("level").values_list("label", flat=True))
        self.assertEqual(labels, ["Academic Manager", "Vice Principal",
                                  "Principal", "Operations / HR"])

    def test_unset_level_blocks_submission(self):
        set_managers(self.inst, {2: None})
        data = self._submit(expect=400)
        self.assertIn("L2 (Vice Principal) is not set", data["detail"])
        self.assertFalse(RelievingApplication.objects.exists())

    def test_inactive_approver_blocks_submission(self):
        self.principal.set_status(Employee.Status.INACTIVE)
        data = self._submit(expect=400)
        self.assertIn("PRINCIPAL", data["detail"].upper())

    def test_master_edit_does_not_reroute_pending_application(self):
        pk = self._submit()
        set_managers(self.inst, {1: self.rm})
        self.assertEqual(self._chain(pk)[0], self.m1.id)

    def test_other_institute_has_its_own_chain(self):
        set_managers(self.other, {1: self.hr, 2: self.hr, 3: self.hr, 4: self.hr})
        self.emp.institute = self.other
        self.emp.save(update_fields=["institute"])
        pk = self._submit()
        self.assertEqual(self._chain(pk), [self.hr.id] * 4)

    def test_applicant_holding_a_level_is_skipped_not_blocked(self):
        set_managers(self.inst, {3: self.emp})
        pk = self._submit()
        rows = {a.level: a for a in RelievingApproval.objects.filter(application_id=pk)}
        self.assertEqual(rows[3].status, "SKIPPED")
        self._decide(self.m1, pk, 1)
        self._decide(self.m2, pk, 2)
        data = self._decide(self.hr, pk, 4)
        self.assertEqual(data["status"], "COMPLETED")

    # --- who may decide ---------------------------------------------

    def test_only_the_snapshotted_approver_can_decide(self):
        pk = self._submit()
        self._decide(self.m2, pk, 1, expect=403)      # wrong level
        self._decide(self.rm, pk, 1, expect=403)      # reporting manager, not in chain
        superuser = User.objects.create_superuser("root", "r@x.in", "x")
        self._decide(superuser, pk, 1, expect=403)    # no override, even for root
        self._decide(self.hr_user, pk, 1, expect=403) # HR without a level
        self._decide(self.m1, pk, 1)

    def test_levels_decide_in_order(self):
        pk = self._submit()
        self._decide(self.m2, pk, 2, expect=400)
        self._decide(self.m1, pk, 1)
        self._decide(self.m2, pk, 2)

    def test_any_level_can_reject(self):
        pk = self._submit()
        self._decide(self.m1, pk, 1)
        self._decide(self.m2, pk, 2)
        data = self._decide(self.principal, pk, 3, decision="REJECTED")
        self.assertEqual(data["status"], "REJECTED")
        self.assertEqual(data["rejected_at_level"], 3)
        self.assertEqual(data["rejection_reason"], "ok 3")
        self._decide(self.hr, pk, 4, expect=400)

    def test_direct_accept_endpoint_is_gone(self):
        pk = self._submit()
        r = self._client(self.hr_user).post(f"/api/hr/relieving/{pk}/accept/", {
            "last_working_date_approved": "2026-10-15"}, format="json")
        self.assertEqual(r.status_code, 404)

    # --- completion -------------------------------------------------

    def test_l4_approval_issues_letters_and_deactivates(self):
        pk = self._submit()
        self._decide(self.m1, pk, 1)
        self._decide(self.m2, pk, 2)
        data = self._decide(self.principal, pk, 3)
        self.assertEqual(data["status"], "IN_REVIEW")

        mail.outbox.clear()
        data = self._decide(self.hr, pk, 4)

        self.assertEqual(data["status"], "COMPLETED")
        self.assertTrue(data["relieving_letter_no"].startswith("REL-JDSD-"))
        self.assertTrue(data["experience_letter_no"].startswith("EXP-JDSD-"))
        self.assertEqual(data["last_working_date_approved"], "2026-10-31")

        app = RelievingApplication.objects.get(pk=pk)
        self.assertEqual(app.finalized_by, self.hr.user_account)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.status, Employee.Status.INACTIVE)
        self.assertEqual(len(mail.outbox), 1)  # relieving only; experience is HR's button

        r = self._client(self.emp).get(
            f"/api/hr/relieving/{pk}/relieving-letter.pdf")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_approval_before_final_level_does_not_issue_letters(self):
        pk = self._submit()
        self._decide(self.m1, pk, 1)
        r = self._client(self.emp).get(
            f"/api/hr/relieving/{pk}/relieving-letter.pdf")
        self.assertEqual(r.status_code, 400)

    def test_part_time_runs_the_same_chain_but_issues_nothing(self):
        pk = self._submit("PART_TIME")
        self.assertEqual(self._chain(pk), [
            self.m1.id, self.m2.id, self.principal.id, self.hr.id,
        ])
        for who, level in ((self.m1, 1), (self.m2, 2), (self.principal, 3)):
            self._decide(who, pk, level)
        mail.outbox.clear()
        data = self._decide(self.hr, pk, 4)

        self.assertEqual(data["status"], "COMPLETED")
        self.assertEqual(data["application_type"], "PART_TIME")
        self.assertEqual(data["relieving_letter_no"], "")
        self.assertEqual(data["experience_letter_no"], "")
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.status, Employee.Status.ACTIVE)
        self.assertEqual(self.emp.employment_type, Employee.EmploymentType.FULL_TIME)

        msg, = mail.outbox
        self.assertIn("Part-time Approved", msg.subject)
        self.assertEqual(msg.to, ["emp1@jdinstitute.edu.in"])

        r = self._client(self.emp).get(f"/api/hr/relieving/{pk}/relieving-letter.pdf")
        self.assertEqual(r.status_code, 400)
        r = self._client(self.hr_user).post(
            f"/api/hr/relieving/{pk}/send-experience-letter/")
        self.assertEqual(r.status_code, 400)

    def test_part_time_refused_for_an_already_part_time_employee(self):
        self.emp.employment_type = Employee.EmploymentType.PART_TIME
        self.emp.save(update_fields=["employment_type"])
        data = self._submit("PART_TIME", expect=400)
        self.assertIn("already part-time", data["application_type"])


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class RelievingManagersMasterTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.inst = Institute.objects.create(name="JDSD", code="JDSD")
        cls.inactive_inst = Institute.objects.create(
            name="Old", code="OLD", is_active=False)
        campus = Campus.objects.create(name="Main", code="MAIN")
        kw = dict(institute=cls.inst, campus=campus)
        cls.a = make_employee("A", **kw)
        cls.b = make_employee("B", **kw)
        cls.gone = make_employee("GONE", **kw)
        cls.gone.set_status(Employee.Status.INACTIVE)
        cls.staff = make_employee("STAFF", **kw)
        cls.staff.user_account = User.objects.create_user("staff", "s@x.in", "x")
        cls.staff.save(update_fields=["user_account"])

        seed_permissions()
        cls.hr_user = User.objects.create_user("hrmanager", "hrm@x.in", "x")
        role = Role.objects.create(name="HR-M")
        role.permissions.set(Permission.objects.filter(key="hr.relieving.managers"))
        cls.hr_user.roles.add(role)

    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_list_creates_four_empty_rows_per_active_institute(self):
        r = self._client(self.staff.user_account).get("/api/hr/relieving/managers/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["level"] for x in r.data], [1, 2, 3, 4])
        self.assertTrue(all(x["institute"] == self.inst.id for x in r.data))
        self.assertEqual([x["label"] for x in r.data],
                         ["Academic Manager", "Vice Principal", "Principal",
                          "Operations / HR"])
        self.assertTrue(all(x["approver"] is None for x in r.data))
        self.assertEqual(RelievingManager.objects.count(), 4)

    def test_put_needs_the_managers_permission(self):
        r = self._client(self.staff.user_account).put(
            f"/api/hr/relieving/managers/{self.inst.id}/",
            {"levels": [{"level": 1, "approver": self.a.id}]}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_put_upserts_levels_and_labels(self):
        r = self._client(self.hr_user).put(
            f"/api/hr/relieving/managers/{self.inst.id}/",
            {"levels": [
                {"level": 1, "approver": self.a.id, "label": "Academic Head"},
                {"level": 4, "approver": self.b.id},
            ]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        by = {x["level"]: x for x in r.data}
        self.assertEqual(by[1]["approver"], self.a.id)
        self.assertEqual(by[1]["label"], "Academic Head")
        self.assertEqual(by[1]["approver_name"], self.a.full_name)
        self.assertTrue(by[1]["approver_active"])
        self.assertIsNone(by[2]["approver"])
        self.assertEqual(by[4]["approver"], self.b.id)
        self.assertEqual(RelievingManager.objects.get(institute=self.inst, level=1)
                         .updated_by, self.hr_user)

        # Clearing a level
        r = self._client(self.hr_user).put(
            f"/api/hr/relieving/managers/{self.inst.id}/",
            {"levels": [{"level": 1, "approver": None}]}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIsNone({x["level"]: x for x in r.data}[1]["approver"])

    def test_put_rejects_inactive_employee_and_duplicates(self):
        r = self._client(self.hr_user).put(
            f"/api/hr/relieving/managers/{self.inst.id}/",
            {"levels": [{"level": 1, "approver": self.gone.id}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not an active employee", r.data["detail"])

        r = self._client(self.hr_user).put(
            f"/api/hr/relieving/managers/{self.inst.id}/",
            {"levels": [{"level": 1, "approver": self.a.id},
                        {"level": 1, "approver": self.b.id}]}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_mine_returns_my_institute_chain(self):
        self._client(self.hr_user).put(
            f"/api/hr/relieving/managers/{self.inst.id}/",
            {"levels": [{"level": 1, "approver": self.a.id}]}, format="json")
        r = self._client(self.staff.user_account).get(
            "/api/hr/relieving/managers/mine/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[0]["approver"], self.a.id)
