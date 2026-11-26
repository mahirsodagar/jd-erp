"""Entrance exam grading (client 2026-11-26): staff enter every mark on the
grading page and decide Pass / Fail in one action; the matching result
mail goes out once. Nothing is mailed on grading alone."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.leads.exam_models import (
    EntranceExam, EntranceExamAttempt, EntranceExamQuestion, EntranceExamResponse,
)
from apps.leads.exam_service import grade_attempt, review_response, submit_attempt
from apps.leads.models import Lead, LeadCommunication
from apps.master.models import Campus, Institute, LeadSource, Program
from apps.notifications.models import NotificationDispatchLog

User = get_user_model()
PASS_KEY = "lead.entrance_exam_result.email"
FAIL_KEY = "lead.entrance_exam_fail.email"


class ExamResultMailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(
            username="staff", password="x", email="s@e.com")
        inst = Institute.objects.create(name="JDIFT", code="JDIFT", phone="080 1111")
        cls.campus = Campus.objects.create(name="Main", code="MAIN", phone="080 2222")
        cls.program = Program.objects.create(name="B.Des", code="BDES", institute=inst)
        cls.source = LeadSource.objects.create(name="Web", slug="web")

    def _exam(self, pass_marks=None, with_short=False):
        exam = EntranceExam.objects.create(
            name="Aptitude", duration_min=30, program=self.program,
            status=EntranceExam.Status.PUBLISHED, pass_marks=pass_marks,
        )
        self.q1 = EntranceExamQuestion.objects.create(
            exam=exam, description="2+2", type=EntranceExamQuestion.Type.MCQ,
            options=["3", "4"], answer_key="4", marks=Decimal("5"), sort_order=1)
        if with_short:
            self.q2 = EntranceExamQuestion.objects.create(
                exam=exam, description="Essay", type=EntranceExamQuestion.Type.SHORT,
                marks=Decimal("5"), sort_order=2)
        exam.total_marks = Decimal("10") if with_short else Decimal("5")
        exam.save()
        return exam

    def _attempt(self, exam, email="cand@example.com"):
        lead = Lead.objects.create(
            name="Asha Rao", phone="9999999999", email=email,
            campus=self.campus, program=self.program, source=self.source)
        now = timezone.now()
        return EntranceExamAttempt.objects.create(
            exam=exam, lead=lead, start_dt=now - timedelta(hours=1),
            end_dt=now + timedelta(days=1))

    def _submit(self, a, short=True):
        answers = [{"question": self.q1.id, "answer": "4"}]
        if short:
            answers.append({"question": self.q2.id, "answer": "text"})
        with self.captureOnCommitCallbacks(execute=True):
            submit_attempt(attempt=a, answers=answers)
        a.refresh_from_db()
        return a

    def _logs(self, key=None):
        qs = NotificationDispatchLog.objects.filter(
            template_key__in=[PASS_KEY, FAIL_KEY])
        return qs.filter(template_key=key) if key else qs

    def _grade(self, a, result, marks=None, user=None):
        c = APIClient()
        c.force_authenticate(user or self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            r = c.post(reverse("exam-attempt-grade", args=[a.pk]),
                       {"result": result, "marks": marks or []}, format="json")
        a.refresh_from_db()
        return r

    def test_grading_alone_mails_nothing(self):
        exam = self._exam(with_short=True)
        a = self._submit(self._attempt(exam))
        self.assertEqual(a.status, EntranceExamAttempt.Status.SUBMITTED)
        r = EntranceExamResponse.objects.get(attempt=a, question=self.q2)
        with self.captureOnCommitCallbacks(execute=True):
            review_response(response=r, marks_awarded=Decimal("3"),
                            feedback="", reviewed_by=self.staff)
        a.refresh_from_db()
        self.assertEqual(a.status, EntranceExamAttempt.Status.GRADED)
        self.assertEqual(a.result, "")
        self.assertEqual(self._logs().count(), 0)

    def test_mcq_only_auto_grade_waits_for_the_decision(self):
        a = self._submit(self._attempt(self._exam(pass_marks=Decimal("5"))), short=False)
        self.assertEqual(a.status, EntranceExamAttempt.Status.GRADED)
        self.assertEqual(self._logs().count(), 0)
        self.assertIsNone(a.result_mailed_at)

    def test_pass_saves_marks_and_mails_congratulations_once(self):
        exam = self._exam(with_short=True)
        a = self._submit(self._attempt(exam))
        short = EntranceExamResponse.objects.get(attempt=a, question=self.q2)
        r = self._grade(a, "PASS", marks=[
            {"response": short.id, "marks_awarded": "4", "feedback": "Good"}])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(a.status, EntranceExamAttempt.Status.GRADED)
        self.assertEqual(a.total_score, Decimal("9"))
        self.assertEqual(a.result, "PASS")
        self.assertEqual(a.result_decided_by, self.staff)
        short.refresh_from_db()
        self.assertEqual((short.marks_awarded, short.feedback), (Decimal("4"), "Good"))
        log = self._logs(PASS_KEY).get()
        self.assertEqual(log.recipient, "cand@example.com")
        self.assertIn("Entrance Exam Result", log.subject)
        self.assertIn("080 2222", log.body)
        self.assertIsNotNone(a.result_mailed_at)
        self.assertIn("(Pass)", LeadCommunication.objects.get(lead=a.lead).subject)
        # Deciding PASS again (e.g. tweaking marks) must not mail twice.
        r = self._grade(a, "PASS", marks=[
            {"response": short.id, "marks_awarded": "5"}])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._logs().count(), 1)
        self.assertEqual(a.total_score, Decimal("10"))

    def test_fail_mails_the_regret_note_with_exam_and_date(self):
        exam = self._exam()
        a = self._submit(self._attempt(exam), short=False)
        r = self._grade(a, "FAIL")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(a.result, "FAIL")
        log = self._logs(FAIL_KEY).get()
        self.assertIn("Entrance Exam Results", log.subject)
        self.assertIn("Aptitude", log.subject)
        self.assertIn("regret to inform you", log.body)
        self.assertIn(timezone.localdate().strftime("%d-%m-%Y"), log.body)
        self.assertEqual(self._logs(PASS_KEY).count(), 0)

    def test_result_cannot_flip_after_it_was_mailed(self):
        a = self._submit(self._attempt(self._exam()), short=False)
        self._grade(a, "FAIL")
        r = self._grade(a, "PASS")
        self.assertEqual(r.status_code, 400)
        self.assertIn("already been mailed", r.json()["detail"])
        self.assertEqual(a.result, "FAIL")

    def test_every_short_answer_needs_a_mark_first(self):
        exam = self._exam(with_short=True)
        a = self._submit(self._attempt(exam))
        r = self._grade(a, "PASS")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Q2", r.json()["detail"])
        self.assertEqual(a.result, "")
        self.assertEqual(self._logs().count(), 0)

    def test_marks_above_question_max_are_refused(self):
        exam = self._exam(with_short=True)
        a = self._submit(self._attempt(exam))
        short = EntranceExamResponse.objects.get(attempt=a, question=self.q2)
        r = self._grade(a, "PASS", marks=[{"response": short.id, "marks_awarded": "9"}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("exceeds", r.json()["detail"])

    def test_unsubmitted_attempt_cannot_be_graded(self):
        a = self._attempt(self._exam())
        r = self._grade(a, "PASS")
        self.assertEqual(r.status_code, 400)

    def test_no_email_on_lead_decides_but_skips_mail(self):
        a = self._submit(self._attempt(self._exam(), email=""), short=False)
        with self.captureOnCommitCallbacks(execute=True):
            grade_attempt(attempt=a, marks=[], result="PASS", actor=self.staff)
        self.assertEqual(a.result, "PASS")
        self.assertEqual(self._logs().count(), 0)
        self.assertIsNone(a.result_mailed_at)
