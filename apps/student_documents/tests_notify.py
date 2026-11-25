"""Bell notifications for document requests (TC / Bonafide / Bank
Letter / …): request → campus deciders, decision → the student."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.admissions.models import Student
from apps.master.models import AcademicYear, Campus, Institute, Program
from apps.notifications.models import InAppNotification
from apps.roles.models import Permission, Role
from apps.student_documents import services
from apps.student_documents.models import DocumentRequest

User = get_user_model()


class DocumentRequestNotifyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        inst = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.blr = Campus.objects.create(name="Bengaluru", code="BLR")
        cls.goa = Campus.objects.create(name="Goa", code="GOA")
        program = Program.objects.create(name="B.Des", code="BDES", institute=inst)
        year = AcademicYear.objects.create(
            code="26-27", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31))

        def perm(key):
            return Permission.objects.get_or_create(
                key=key, defaults={"module": "student_documents", "label": key})[0]

        decide = Role.objects.create(name="Doc Desk")
        decide.permissions.add(perm("student_documents.approve"),
                               perm("student_documents.reject"))
        decide_all = Role.objects.create(name="Doc Desk HQ")
        decide_all.permissions.add(perm("student_documents.approve"),
                                   perm("student_documents.view_all"))
        viewer = Role.objects.create(name="Doc Viewer")
        viewer.permissions.add(perm("student_documents.view"))

        def staff(username, role, campus=None):
            u = User.objects.create_user(username=username, password="x",
                                         email=f"{username}@example.com")
            u.roles.add(role)
            if campus is not None:
                u.campuses.add(campus)
            return u

        cls.blr_desk = staff("blr-desk", decide, cls.blr)
        cls.goa_desk = staff("goa-desk", decide, cls.goa)
        cls.hq_desk = staff("hq-desk", decide_all)
        cls.blr_viewer = staff("blr-viewer", viewer, cls.blr)

        cls.portal_user = User.objects.create_user(
            username="asha@jdift.in", password="x", email="asha@jdift.in")
        cls.student = Student.objects.create(
            application_form_id="AF-1", student_name="Asha",
            student_email="asha@example.com", gender="F", dob="2000-01-01",
            nationality="INDIAN", category="GENERAL", institute=inst,
            campus=cls.blr, program=program, academic_year=year,
            user_account=cls.portal_user,
        )

    def _titles_for(self, user):
        return list(InAppNotification.objects.filter(recipient=user)
                    .values_list("title", flat=True))

    def test_request_rings_campus_deciders_only(self):
        services.apply_document(student=self.student, doc_type="BANK_LETTER",
                                purpose="Education loan")
        self.assertEqual(self._titles_for(self.blr_desk), ["Bank Letter requested"])
        self.assertEqual(self._titles_for(self.hq_desk), ["Bank Letter requested"])
        self.assertEqual(self._titles_for(self.goa_desk), [])
        self.assertEqual(self._titles_for(self.blr_viewer), [])
        self.assertEqual(self._titles_for(self.portal_user), [])
        n = InAppNotification.objects.get(recipient=self.blr_desk)
        self.assertIn("Asha (AF-1)", n.body)
        self.assertIn("Education loan", n.body)
        self.assertEqual(n.link, "/student-documents")

    def test_other_type_uses_the_free_text_label(self):
        services.apply_document(student=self.student, doc_type="OTHER",
                                doc_type_other="Fee structure letter",
                                purpose="Visa")
        self.assertEqual(self._titles_for(self.blr_desk),
                         ["Fee structure letter requested"])

    def test_decision_rings_the_student(self):
        req = services.apply_document(student=self.student, doc_type="TC",
                                      purpose="Transfer")
        InAppNotification.objects.all().delete()
        services.decide_document(request_obj=req, decision="REJECTED",
                                 remarks="Dues pending", decided_by=self.blr_desk)
        self.assertEqual(self._titles_for(self.portal_user),
                         ["Transfer Certificate request rejected"])
        n = InAppNotification.objects.get(recipient=self.portal_user)
        self.assertEqual(n.body, "Dues pending")
        self.assertEqual(n.link, "/portal/documents")
        self.assertEqual(self._titles_for(self.blr_desk), [])

    def test_approval_without_portal_login_is_silent(self):
        self.student.user_account = None
        self.student.save(update_fields=["user_account"])
        req = services.apply_document(student=self.student, doc_type="BONAFIDE",
                                      purpose="Bank")
        InAppNotification.objects.all().delete()
        services.decide_document(request_obj=req, decision="APPROVED",
                                 decided_by=self.hq_desk)
        self.assertEqual(req.status, DocumentRequest.Status.APPROVED)
        self.assertEqual(InAppNotification.objects.count(), 0)
