"""Program/campus flows downstream, never back up.

Three places name a program and they are filled at different times:
the counsellor picks one on the Lead, the student may change it on the
application form, and HR may enrol them into a third. The rule is that
the later stage wins and the earlier record follows it, so nobody has to
remember which screen holds the truth.
"""

import uuid

from django.test import TestCase

from apps.admissions.models import Enrollment, Student, StudentRemark
from apps.admissions.services import (
    current_enrollment, submit_application_from_lead,
    sync_student_placement_from_enrollment,
)
from apps.leads.models import Lead, LeadStatusHistory
from apps.master.models import (
    AcademicYear, Batch, Campus, Institute, LeadSource, Program, Semester,
    University,
)


class PlacementSyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.other_institute = Institute.objects.create(name="JDSA", code="JDSA")
        cls.campus = Campus.objects.create(name="Bengaluru", code="BLR")
        cls.campus2 = Campus.objects.create(name="Mumbai", code="MUM")

        cls.prog_a = Program.objects.create(
            name="B.Des Fashion", code="BDES-F", institute=cls.institute,
        )
        cls.prog_b = Program.objects.create(
            name="B.Des Interior", code="BDES-I", institute=cls.institute,
        )
        cls.prog_c = Program.objects.create(
            name="M.Des", code="MDES", institute=cls.other_institute,
        )
        for p in (cls.prog_a, cls.prog_b, cls.prog_c):
            p.campuses.set([cls.campus, cls.campus2])

        cls.year = AcademicYear.objects.create(
            code="2026-27", start_date="2026-06-01", end_date="2027-05-31",
            is_current=True,
        )
        cls.source = LeadSource.objects.create(name="Website", slug="website")
        cls.sem1 = Semester.objects.create(name="Sem 1", number=1)
        cls.batch_c = Batch.objects.create(
            name="MDES-A", program=cls.prog_c, campus=cls.campus2,
            academic_year=cls.year,
        )

    def _lead(self):
        return Lead.objects.create(
            name="Asha", email="asha@example.com", phone="+919900112233",
            campus=self.campus, program=self.prog_a, source=self.source,
            application_token=uuid.uuid4(),
        )

    def _payload(self, **over):
        base = {
            "dob": "2004-03-11",
            "gender": "F",
            "current_address": "12 MG Road",
            "student_mobile": "+919900112233",
            "student_email": "asha@example.com",
        }
        base.update(over)
        return base

    # --- Application form → Lead ---------------------------------------

    def test_application_program_change_moves_the_lead(self):
        lead = self._lead()
        submit_application_from_lead(
            lead=lead, payload=self._payload(program=self.prog_b.pk),
        )
        lead.refresh_from_db()
        self.assertEqual(lead.program, self.prog_b)

        note = LeadStatusHistory.objects.filter(
            lead=lead, note__startswith="Program",
        ).get()
        self.assertIn("B.Des Fashion", note.note)
        self.assertIn("B.Des Interior", note.note)
        # A note, not a stage move — the pill must not read as a transition.
        self.assertEqual(note.old_status, "")

    def test_campus_change_moves_the_lead_too(self):
        lead = self._lead()
        submit_application_from_lead(
            lead=lead, payload=self._payload(campus=self.campus2.pk),
        )
        lead.refresh_from_db()
        self.assertEqual(lead.campus, self.campus2)
        self.assertEqual(lead.program, self.prog_a)

    def test_unchanged_application_writes_no_note(self):
        lead = self._lead()
        submit_application_from_lead(
            lead=lead,
            payload=self._payload(program=self.prog_a.pk, campus=self.campus.pk),
        )
        self.assertFalse(
            LeadStatusHistory.objects.filter(lead=lead).exclude(note="")
            .exclude(note__startswith="Self-submitted").exists(),
        )

    def test_resubmit_without_program_keeps_the_change(self):
        """The bug this guards: a partial re-submit used to default back
        to the lead's original program and silently undo the student's
        own choice."""
        lead = self._lead()
        submit_application_from_lead(
            lead=lead, payload=self._payload(program=self.prog_b.pk),
        )
        lead.refresh_from_db()
        submit_application_from_lead(
            lead=lead, payload=self._payload(father_name="Ravi"),
        )
        student = Student.objects.get(lead_origin=lead)
        self.assertEqual(student.program, self.prog_b)
        self.assertEqual(student.father_name, "Ravi")

    def test_program_not_offered_at_the_campus_is_rejected(self):
        self.prog_b.campuses.set([self.campus2])
        lead = self._lead()
        with self.assertRaises(ValueError):
            submit_application_from_lead(
                lead=lead,
                payload=self._payload(
                    program=self.prog_b.pk, campus=self.campus.pk,
                ),
            )

    def test_campus_only_change_is_validated_against_the_program(self):
        """Changing just the campus can strand the program as surely as
        changing just the program."""
        self.prog_a.campuses.set([self.campus])
        lead = self._lead()
        with self.assertRaises(ValueError):
            submit_application_from_lead(
                lead=lead, payload=self._payload(campus=self.campus2.pk),
            )

    # --- Enrollment → Student ------------------------------------------

    def _student(self):
        lead = self._lead()
        student, _ = submit_application_from_lead(
            lead=lead, payload=self._payload(),
        )
        return student

    def test_enrolling_into_another_program_moves_the_student(self):
        student = self._student()
        self.assertEqual(student.program, self.prog_a)
        Enrollment.objects.create(
            student=student, program=self.prog_c, semester=self.sem1,
            campus=self.campus2, batch=self.batch_c, academic_year=self.year,
            status=Enrollment.Status.ACTIVE,
        )
        self.assertTrue(sync_student_placement_from_enrollment(student))
        student.refresh_from_db()
        self.assertEqual(student.program, self.prog_c)
        self.assertEqual(student.campus, self.campus2)
        # Institute is derived from the program everywhere else.
        self.assertEqual(student.institute, self.other_institute)
        self.assertTrue(
            StudentRemark.objects.filter(
                student=student, note__contains="M.Des",
            ).exists(),
        )

    def test_sync_is_a_no_op_without_an_enrollment(self):
        student = self._student()
        self.assertFalse(sync_student_placement_from_enrollment(student))
        self.assertFalse(StudentRemark.objects.filter(student=student).exists())

    def test_current_enrollment_prefers_the_live_row(self):
        """Batch promotion leaves a PROMOTED row behind; the newest live
        one is what the profile must follow."""
        student = self._student()
        batch_a = Batch.objects.create(
            name="BDES-A", program=self.prog_a, campus=self.campus,
            academic_year=self.year,
        )
        old = Enrollment.objects.create(
            student=student, program=self.prog_a, semester=self.sem1,
            campus=self.campus, batch=batch_a, academic_year=self.year,
            status=Enrollment.Status.PROMOTED,
        )
        live = Enrollment.objects.create(
            student=student, program=self.prog_c, semester=self.sem1,
            campus=self.campus2, batch=self.batch_c, academic_year=self.year,
            status=Enrollment.Status.ACTIVE,
        )
        self.assertEqual(current_enrollment(student), live)

        # With no live row left, fall back to the newest of any status so
        # a dropped-out student still shows where they were.
        live.status = Enrollment.Status.DROPPED
        live.save(update_fields=["status"])
        self.assertEqual(current_enrollment(student), live)
        self.assertNotEqual(current_enrollment(student), old)


class ApplicationUniversityDropdownTests(TestCase):
    """The form asks for the university before the program, so the
    university list has to stay a faithful index of what is actually on
    offer — including the programs no university confers."""

    @classmethod
    def setUpTestData(cls):
        cls.institute = Institute.objects.create(name="JDIFT", code="JDIFT")
        cls.source = LeadSource.objects.create(name="Website", slug="website")
        cls.blr = Campus.objects.create(name="Bengaluru", code="BLR")
        cls.mum = Campus.objects.create(name="Mumbai", code="MUM")
        # Codes that migration 0018's seed doesn't already claim.
        cls.uni_a = University.objects.create(name="Alpha University", code="TU-A")
        cls.uni_b = University.objects.create(name="Beta University", code="TU-B")

        cls.degree_prog = Program.objects.create(
            name="B.Des Fashion", code="BDES-F", institute=cls.institute,
            university=cls.uni_a,
        )
        cls.degree_prog.campuses.set([cls.blr])
        # JD-certified: no university, and there is no University row it
        # could ever point at.
        cls.jd_prog = Program.objects.create(
            name="Certificate in Styling", code="CERT-ST",
            institute=cls.institute, certification="JD",
        )
        cls.jd_prog.campuses.set([cls.blr, cls.mum])
        # Offered nowhere the student can reach.
        cls.mumbai_only = Program.objects.create(
            name="M.Des", code="MDES", institute=cls.institute,
            university=cls.uni_b,
        )
        cls.mumbai_only.campuses.set([cls.mum])

        AcademicYear.objects.create(
            code="2026-27", start_date="2026-06-01", end_date="2027-05-31",
            is_current=True,
        )
        cls.lead = Lead.objects.create(
            name="Asha", email="asha@example.com", phone="+919900112233",
            campus=cls.blr, program=cls.degree_prog, source=cls.source,
            application_token=uuid.uuid4(),
        )

    def _get(self):
        return self.client.get(
            f"/api/public/application/{self.lead.application_token}/",
        ).json()

    def test_every_program_carries_its_university(self):
        data = self._get()
        by_code = {p["code"]: p for p in data["programs"]}
        self.assertEqual(by_code["BDES-F"]["university"], self.uni_a.id)
        self.assertEqual(by_code["BDES-F"]["university_name"], "Alpha University")
        # The JD bucket is labelled, not left blank — the dropdown has to
        # show the student something they can pick.
        self.assertIsNone(by_code["CERT-ST"]["university"])
        self.assertEqual(by_code["CERT-ST"]["university_code"], "JD")

    def test_jd_bucket_is_offered_and_pinned_last(self):
        options = self._get()["universities"]
        self.assertEqual(
            [u["code"] for u in options], ["TU-A", "TU-B", "JD"],
        )
        self.assertIsNone(options[-1]["id"])

    def test_only_universities_with_a_live_program_are_listed(self):
        """An option that filters the program list to nothing is a dead
        end, so it must not be offered at all."""
        self.mumbai_only.is_active = False
        self.mumbai_only.save(update_fields=["is_active"])
        self.assertEqual(
            [u["code"] for u in self._get()["universities"]],
            ["TU-A", "JD"],
        )

    def test_no_jd_bucket_when_every_program_is_affiliated(self):
        self.jd_prog.is_active = False
        self.jd_prog.save(update_fields=["is_active"])
        self.assertNotIn(
            "JD", [u["code"] for u in self._get()["universities"]],
        )
