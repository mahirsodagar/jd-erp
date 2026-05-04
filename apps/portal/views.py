"""Portal endpoints — student & parent. All scoping flows through
`request.portal_ctx` (set by IsStudentOrParent / IsStudentOnly), so
views never trust IDs from the request body."""

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import (
    Assignment, AssignmentSubmission, Attendance, ScheduleSlot,
    Test, TestAttempt, TestQuestion, TestResponse,
)
from apps.academics import test_service as test_svc
from apps.admissions.models import Student, StudentDocument
from apps.courseware.models import CoursewareMapping, CoursewareTopic
from apps.master.models import Batch, Subject
from apps.student_leaves import services as leave_svc
from apps.student_leaves.models import StudentLeaveApplication

from .helpers import resolve_portal_context
from .permissions import IsStudentOnly, IsStudentOrParent
from .serializers import (
    ChangePasswordSerializer, PortalAssignmentSerializer,
    PortalCoursewareTopicSerializer, PortalLeaveSerializer,
    PortalProfileSerializer, PortalQualificationSerializer,
    PortalTestDetailSerializer, PortalTestSerializer,
    ProvisionParentSerializer, QUALIFICATION_HEADERS,
    SubmitAssignmentSerializer, TestSubmitSerializer,
)


# --- Profile -------------------------------------------------------

class MeView(APIView):
    permission_classes = [IsStudentOrParent]

    def get(self, request):
        ctx = request.portal_ctx
        data = PortalProfileSerializer(
            ctx.student, context={"request": request},
        ).data
        e = ctx.enrollment
        data["enrollment"] = None if e is None else {
            "id": e.id,
            "batch_id": e.batch_id,
            "batch_name": e.batch.name,
            "semester_id": e.semester_id,
            "semester_number": e.semester.number,
            "course_id": e.course_id,
            "course_name": e.course.name if e.course else None,
            "academic_year": e.academic_year.code,
            "status": e.status,
        }
        data["is_parent"] = ctx.is_parent
        return Response(data)


class ChangePasswordView(APIView):
    permission_classes = [IsStudentOrParent]

    def post(self, request):
        s = ChangePasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(s.validated_data["current_password"]):
            return Response({"current_password": "Incorrect."},
                            status=http.HTTP_400_BAD_REQUEST)
        user.set_password(s.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response({"detail": "Password updated."})


# --- Dashboard -----------------------------------------------------

class DashboardView(APIView):
    permission_classes = [IsStudentOrParent]

    def get(self, request):
        ctx = request.portal_ctx
        student = ctx.student
        e = ctx.enrollment

        present = (Attendance.objects
                   .filter(student=student,
                           status=Attendance.Status.PRESENT)
                   .count())
        total = (Attendance.objects.filter(student=student).count())
        attendance_pct = round((present / total * 100) if total else 0)

        total_assignments = 0
        total_courseware = 0
        if e is not None:
            total_assignments = (Assignment.objects
                                  .filter(batch=e.batch, is_published=True)
                                  .count())
            total_courseware = (CoursewareMapping.objects
                                 .filter(student=student,
                                         topic__is_published=True)
                                 .count())

        todays_classes = 0
        if e is not None:
            todays_classes = (ScheduleSlot.objects
                              .filter(batch=e.batch, date=date.today(),
                                      status=ScheduleSlot.Status.SCHEDULED)
                              .count())

        return Response({
            "attendance_percent": attendance_pct,
            "total_assignments": total_assignments,
            "total_courseware": total_courseware,
            "todays_classes": todays_classes,
        })


# --- Attendance ----------------------------------------------------

_ATT_COLORS = {
    Attendance.Status.PRESENT: "#28a745",
    Attendance.Status.ABSENT: "#dc3545",
    Attendance.Status.LATE: "#fff200",
    Attendance.Status.ON_DUTY: "#17a2b8",
    Attendance.Status.EXCUSED: "#6c757d",
}


class AttendanceCalendarView(APIView):
    permission_classes = [IsStudentOrParent]

    def get(self, request):
        student = request.portal_ctx.student
        rows = (Attendance.objects
                .filter(student=student)
                .select_related("schedule_slot__subject",
                                 "schedule_slot__time_slot"))
        events = []
        for a in rows:
            ss = a.schedule_slot
            events.append({
                "id": a.id,
                "title": f"{ss.subject.code} ({a.status[:1]})",
                "start": f"{ss.date}T{ss.time_slot.start_time}",
                "end": f"{ss.date}T{ss.time_slot.end_time}",
                "color": _ATT_COLORS.get(a.status, "#6c757d"),
                "status": a.status,
            })
        return Response(events)


class AttendanceReportView(APIView):
    permission_classes = [IsStudentOrParent]

    def get(self, request):
        student = request.portal_ctx.student
        rows = (Attendance.objects
                .filter(student=student)
                .select_related("schedule_slot__subject",
                                 "schedule_slot"))
        # group by subject
        agg = {}
        for a in rows:
            sub = a.schedule_slot.subject
            d = agg.setdefault(sub.id, {
                "subject_id": sub.id,
                "subject_code": sub.code,
                "subject_name": sub.name,
                "present": 0, "absent": 0, "late": 0,
                "on_duty": 0, "excused": 0, "total": 0,
                "absent_dates": [], "late_dates": [],
            })
            d["total"] += 1
            ds = a.schedule_slot.date.isoformat()
            if a.status == Attendance.Status.PRESENT:
                d["present"] += 1
            elif a.status == Attendance.Status.ABSENT:
                d["absent"] += 1
                d["absent_dates"].append(ds)
            elif a.status == Attendance.Status.LATE:
                d["late"] += 1
                d["late_dates"].append(ds)
            elif a.status == Attendance.Status.ON_DUTY:
                d["on_duty"] += 1
            elif a.status == Attendance.Status.EXCUSED:
                d["excused"] += 1
        for d in agg.values():
            d["percentage"] = round(
                d["present"] / d["total"] * 100 if d["total"] else 0, 1,
            )
        rows_out = sorted(agg.values(), key=lambda r: r["subject_code"])
        totals = {
            "present": sum(r["present"] for r in rows_out),
            "absent": sum(r["absent"] for r in rows_out),
            "late": sum(r["late"] for r in rows_out),
            "total": sum(r["total"] for r in rows_out),
        }
        totals["percentage"] = round(
            totals["present"] / totals["total"] * 100
            if totals["total"] else 0, 1,
        )
        return Response({"subjects": rows_out, "totals": totals})


# --- Timetable -----------------------------------------------------

class TimetableView(APIView):
    permission_classes = [IsStudentOrParent]

    def get(self, request):
        ctx = request.portal_ctx
        if ctx.enrollment is None:
            return Response([])
        qs = (ScheduleSlot.objects
              .filter(batch=ctx.enrollment.batch,
                      status=ScheduleSlot.Status.SCHEDULED)
              .select_related("subject", "instructor", "classroom",
                               "time_slot"))
        if v := request.query_params.get("from"):
            qs = qs.filter(date__gte=v)
        if v := request.query_params.get("to"):
            qs = qs.filter(date__lte=v)
        events = []
        for s in qs:
            events.append({
                "id": s.id,
                "title": f"{s.subject.code} — {s.subject.name}",
                "start": f"{s.date}T{s.time_slot.start_time}",
                "end": f"{s.date}T{s.time_slot.end_time}",
                "subject_id": s.subject_id,
                "subject_code": s.subject.code,
                "subject_name": s.subject.name,
                "instructor": s.instructor.full_name,
                "classroom": s.classroom.name if s.classroom else "",
                "color": "#0062cc",
            })
        return Response(events)


# --- Assignments ---------------------------------------------------

class AssignmentSubjectsView(APIView):
    permission_classes = [IsStudentOnly]

    def get(self, request):
        e = request.portal_ctx.enrollment
        if e is None:
            return Response([])
        rows = (Assignment.objects
                .filter(batch=e.batch, is_published=True)
                .values("subject_id", "subject__code", "subject__name")
                .annotate(total_assignments=Count("id"))
                .order_by("subject__code"))
        return Response([
            {"subject_id": r["subject_id"],
             "subject_code": r["subject__code"],
             "subject_name": r["subject__name"],
             "total_assignments": r["total_assignments"]}
            for r in rows
        ])


class AssignmentListView(APIView):
    permission_classes = [IsStudentOnly]

    def get(self, request):
        ctx = request.portal_ctx
        e = ctx.enrollment
        if e is None:
            return Response([])
        qs = (Assignment.objects
              .filter(batch=e.batch, is_published=True)
              .select_related("subject"))
        if v := request.query_params.get("subject_id"):
            qs = qs.filter(subject_id=v)
        subs = {
            s.assignment_id: s for s in
            AssignmentSubmission.objects
                .filter(assignment__in=qs, student=ctx.student)
                .select_related("assignment")
        }
        return Response(PortalAssignmentSerializer(
            qs, many=True,
            context={"request": request, "submissions_by_assignment": subs},
        ).data)


class AssignmentSubmitView(APIView):
    permission_classes = [IsStudentOnly]
    parser_classes = [MultiPartParser, FormParser]

    @transaction.atomic
    def post(self, request, pk):
        ctx = request.portal_ctx
        e = ctx.enrollment
        if e is None:
            return Response({"detail": "No active enrollment."},
                            status=http.HTTP_400_BAD_REQUEST)
        try:
            assignment = Assignment.objects.get(
                pk=pk, batch=e.batch, is_published=True,
            )
        except Assignment.DoesNotExist as ex:
            raise Http404 from ex
        s = SubmitAssignmentSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        sub, created = AssignmentSubmission.objects.get_or_create(
            assignment=assignment, student=ctx.student,
            defaults={"status": AssignmentSubmission.Status.SUBMITTED},
        )
        if (not created
                and sub.status == AssignmentSubmission.Status.GRADED):
            return Response(
                {"detail": "Already graded; cannot resubmit."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        if f := s.validated_data.get("file"):
            sub.file = f
        if t := s.validated_data.get("text_response"):
            sub.text_response = t
        sub.submitted_at = timezone.now()
        deadline = sub.extended_due_date or assignment.due_date
        sub.status = (
            AssignmentSubmission.Status.LATE
            if sub.submitted_at > deadline
            else AssignmentSubmission.Status.SUBMITTED
        )
        sub.save()

        return Response(
            PortalAssignmentSerializer(
                assignment,
                context={"request": request,
                          "submissions_by_assignment": {assignment.id: sub}},
            ).data,
            status=http.HTTP_201_CREATED if created else http.HTTP_200_OK,
        )


# --- Courseware ----------------------------------------------------

class CoursewareSubjectsView(APIView):
    permission_classes = [IsStudentOnly]

    def get(self, request):
        student = request.portal_ctx.student
        rows = (CoursewareMapping.objects
                .filter(student=student, topic__is_published=True)
                .values("topic__subject_id",
                        "topic__subject__code",
                        "topic__subject__name")
                .annotate(total_courseware=Count("topic_id"))
                .order_by("topic__subject__code"))
        return Response([
            {"subject_id": r["topic__subject_id"],
             "subject_code": r["topic__subject__code"],
             "subject_name": r["topic__subject__name"],
             "total_courseware": r["total_courseware"]}
            for r in rows
        ])


class CoursewareListView(APIView):
    permission_classes = [IsStudentOnly]

    def get(self, request):
        student = request.portal_ctx.student
        topic_ids = (CoursewareMapping.objects
                     .filter(student=student)
                     .values_list("topic_id", flat=True))
        qs = (CoursewareTopic.objects
              .filter(id__in=topic_ids, is_published=True)
              .select_related("subject")
              .prefetch_related("attachments"))
        if v := request.query_params.get("subject_id"):
            qs = qs.filter(subject_id=v)
        return Response(PortalCoursewareTopicSerializer(
            qs, many=True, context={"request": request},
        ).data)


# --- Tests ---------------------------------------------------------

class TestSubjectsView(APIView):
    permission_classes = [IsStudentOnly]

    def get(self, request):
        student = request.portal_ctx.student
        rows = (TestAttempt.objects
                .filter(student=student,
                        test__status__in=[Test.Status.PUBLISHED,
                                          Test.Status.CLOSED])
                .values("test__subject_id",
                        "test__subject__code",
                        "test__subject__name")
                .annotate(total_tests=Count("test_id", distinct=True))
                .order_by("test__subject__code"))
        return Response([
            {"subject_id": r["test__subject_id"],
             "subject_code": r["test__subject__code"],
             "subject_name": r["test__subject__name"],
             "total_tests": r["total_tests"]}
            for r in rows
        ])


class TestListView(APIView):
    permission_classes = [IsStudentOnly]

    def get(self, request):
        student = request.portal_ctx.student
        attempts = (TestAttempt.objects
                    .filter(student=student,
                            test__status__in=[Test.Status.PUBLISHED,
                                              Test.Status.CLOSED])
                    .select_related("test__subject"))
        if v := request.query_params.get("subject_id"):
            attempts = attempts.filter(test__subject_id=v)
        attempts_by_test = {a.test_id: a for a in attempts}
        tests = [a.test for a in attempts]
        return Response(PortalTestSerializer(
            tests, many=True,
            context={"request": request,
                      "attempts_by_test": attempts_by_test},
        ).data)


class TestDetailView(APIView):
    permission_classes = [IsStudentOnly]

    def get(self, request, pk):
        student = request.portal_ctx.student
        try:
            attempt = (TestAttempt.objects
                       .select_related("test__subject")
                       .prefetch_related("test__questions")
                       .get(test_id=pk, student=student))
        except TestAttempt.DoesNotExist as e:
            raise Http404 from e
        ok, reason = test_svc.can_attempt_now(attempt)
        if not ok:
            return Response(
                {"detail": reason},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if attempt.status == TestAttempt.Status.NOT_STARTED:
            attempt.status = TestAttempt.Status.IN_PROGRESS
            attempt.started_at = timezone.now()
            attempt.save(update_fields=["status", "started_at", "updated_at"])
        return Response(PortalTestDetailSerializer(
            attempt.test,
            context={"request": request,
                      "attempts_by_test": {attempt.test_id: attempt}},
        ).data)


class TestSubmitView(APIView):
    permission_classes = [IsStudentOnly]

    def post(self, request, pk):
        student = request.portal_ctx.student
        try:
            attempt = TestAttempt.objects.select_related("test").get(
                test_id=pk, student=student,
            )
        except TestAttempt.DoesNotExist as e:
            raise Http404 from e
        if attempt.status in (TestAttempt.Status.SUBMITTED,
                              TestAttempt.Status.GRADED):
            return Response({"type": "already"},
                            status=http.HTTP_400_BAD_REQUEST)
        ok, reason = test_svc.can_attempt_now(attempt)
        if not ok:
            return Response({"detail": reason},
                            status=http.HTTP_400_BAD_REQUEST)
        s = TestSubmitSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        result = test_svc.submit_attempt(
            attempt=attempt, answers=s.validated_data["answers"],
        )
        return Response(result)


class TestResultView(APIView):
    permission_classes = [IsStudentOnly]

    def get(self, request, pk):
        student = request.portal_ctx.student
        try:
            attempt = TestAttempt.objects.select_related("test").get(
                test_id=pk, student=student,
            )
        except TestAttempt.DoesNotExist as e:
            raise Http404 from e
        if attempt.status not in (TestAttempt.Status.SUBMITTED,
                                  TestAttempt.Status.GRADED):
            return Response({"detail": "Result not yet available."},
                            status=http.HTTP_400_BAD_REQUEST)
        responses = (attempt.responses
                     .select_related("question")
                     .order_by("question__sort_order", "question_id"))
        items = []
        for r in responses:
            q = r.question
            correct = (q.type == TestQuestion.Type.MCQ
                       and r.answer == q.answer_key)
            items.append({
                "question_id": q.id,
                "description": q.description,
                "type": q.type,
                "options": q.options,
                "answer_key": q.answer_key,
                "your_answer": r.answer,
                "marks_awarded": (str(r.marks_awarded)
                                   if r.marks_awarded is not None else None),
                "max_marks": str(q.marks),
                "is_correct": correct,
                "feedback": r.feedback,
            })
        return Response({
            "test_id": attempt.test_id,
            "test_name": attempt.test.name,
            "total_marks": str(attempt.test.total_marks),
            "total_score": (str(attempt.total_score)
                             if attempt.total_score is not None else None),
            "status": attempt.status,
            "items": items,
        })


# --- Student leaves ------------------------------------------------

class LeaveListCreateView(APIView):
    permission_classes = [IsStudentOnly]

    def get(self, request):
        student = request.portal_ctx.student
        qs = StudentLeaveApplication.objects.filter(student=student)
        return Response(PortalLeaveSerializer(qs, many=True).data)

    def post(self, request):
        student = request.portal_ctx.student
        from .serializers import PortalLeaveSerializer  # noqa
        from apps.student_leaves.serializers import (
            ApplyStudentLeaveSerializer,
        )
        s = ApplyStudentLeaveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            app = leave_svc.apply_leave(
                student=student,
                leave_date=d["leave_date"],
                leave_edate=d["leave_edate"],
                student_remarks=d["student_remarks"],
                batch_mentor_email=d["batch_mentor_email"],
                module_mentor_email=d.get("module_mentor_email", ""),
                cc_emails=d.get("cc_emails", []),
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(PortalLeaveSerializer(app).data,
                        status=http.HTTP_201_CREATED)


# --- Feedback link -------------------------------------------------

class FeedbackLinkView(APIView):
    permission_classes = [IsStudentOnly]

    def get(self, request):
        e = request.portal_ctx.enrollment
        if e is None or not e.batch.feedback_link_enabled:
            return Response({"enabled": False, "url": ""})
        return Response({"enabled": True, "url": e.batch.feedback_link})


# --- Educational qualifications ------------------------------------

class QualificationListCreateView(APIView):
    permission_classes = [IsStudentOnly]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        student = request.portal_ctx.student
        qs = (StudentDocument.objects
              .filter(student=student, header__in=QUALIFICATION_HEADERS)
              .order_by("-uploaded_on"))
        return Response(PortalQualificationSerializer(
            qs, many=True, context={"request": request},
        ).data)

    @transaction.atomic
    def post(self, request):
        student = request.portal_ctx.student
        # Accept either single doc OR arrays of fields/files (multipart).
        items = self._parse_multi(request)
        if not items:
            return Response({"detail": "No qualification rows provided."},
                            status=http.HTTP_400_BAD_REQUEST)
        created = []
        for item in items:
            header = item.get("header")
            if header not in QUALIFICATION_HEADERS:
                continue
            doc = StudentDocument.objects.create(
                student=student,
                header=header,
                regno_yearpassing=item.get("regno_yearpassing", ""),
                school_college=item.get("school_college", ""),
                university_board=item.get("university_board", ""),
                certificate_no=item.get("certificate_no", ""),
                percent_obtained=item.get("percent_obtained") or None,
                file=item.get("file"),
                uploaded_by=request.user,
            )
            created.append(doc)
        return Response(PortalQualificationSerializer(
            created, many=True, context={"request": request},
        ).data, status=http.HTTP_201_CREATED)

    @staticmethod
    def _parse_multi(request) -> list[dict]:
        data = request.data
        files = request.FILES
        # array form: header[0], header[1], etc., or comma-grouped
        # Simpler API: indexed fields header.0, header.1, ...
        keys = [k for k in data.keys() if k.startswith("header.")]
        if not keys:
            # single-doc fallback
            single = {f: data.get(f, "") for f in (
                "header", "regno_yearpassing", "school_college",
                "university_board", "certificate_no", "percent_obtained",
            )}
            single["file"] = files.get("file")
            return [single] if single.get("header") else []
        idxs = sorted({k.split(".", 1)[1] for k in keys}, key=int)
        out = []
        for idx in idxs:
            out.append({
                "header": data.get(f"header.{idx}", ""),
                "regno_yearpassing": data.get(f"regno_yearpassing.{idx}", ""),
                "school_college": data.get(f"school_college.{idx}", ""),
                "university_board": data.get(f"university_board.{idx}", ""),
                "certificate_no": data.get(f"certificate_no.{idx}", ""),
                "percent_obtained": data.get(f"percent_obtained.{idx}", ""),
                "file": files.get(f"file.{idx}"),
            })
        return out


# --- Parent provisioning (admin-side, lives here for cohesion) ----

class ProvisionParentView(APIView):
    """Staff-only: create + link a Parent user account to a student.
    Mounted at /api/admissions/students/<id>/parent/."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.accounts.models import User
        if not (request.user.is_superuser
                or request.user.roles.filter(
                    permissions__key="admissions.parent.manage",
                ).exists()):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            student = Student.objects.get(pk=pk)
        except Student.DoesNotExist as e:
            raise Http404 from e
        s = ProvisionParentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if student.parent_user_account is not None:
            return Response(
                {"detail": "Parent account already linked."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if User.objects.filter(username=d["username"]).exists():
            return Response({"username": "Already taken."},
                            status=http.HTTP_400_BAD_REQUEST)
        if User.objects.filter(email__iexact=d["email"]).exists():
            return Response({"email": "Already taken."},
                            status=http.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            user = User.objects.create_user(
                username=d["username"], email=d["email"],
                full_name=d.get("full_name") or "",
                password=d["password"],
            )
            student.parent_user_account = user
            student.save(update_fields=["parent_user_account", "updated_on"])
        return Response({
            "id": student.id,
            "parent_user_id": user.id,
            "parent_username": user.username,
            "parent_email": user.email,
        }, status=http.HTTP_201_CREATED)
