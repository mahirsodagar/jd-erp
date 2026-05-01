from datetime import date as _date

from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.employees.models import Employee
from apps.master.models import Batch

from .models import (
    AdminDailyReport, BatchMentorReport, ComplianceFlag, CourseEndReport,
    FacultyDailyReport, FacultySelfAppraisal, StudentFeedback,
)
from .permissions import has_perm
from .serializers import (
    AdminDailyReportSerializer, BatchMentorReportSerializer,
    ComplianceFlagSerializer, CourseEndReportSerializer,
    CourseEndReviewSerializer, FacultyDailyReportSerializer,
    FacultySelfAppraisalSerializer, ResolveFlagSerializer,
    SelfAppraisalReviewSerializer, StudentFeedbackSerializer,
)
from .services import (
    batch_progression, consolidated_monthly,
    feedback_summary_for_instructor, live_faculty_tracking,
    timetable_adherence,
)


def _emp_of(user) -> Employee | None:
    return getattr(user, "employee", None)


def _student_of(user):
    return getattr(user, "student", None)


# === 1. Faculty Daily Report ========================================

class FacultyDailyReportListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = FacultyDailyReport.objects.select_related("faculty")
        if not (u.is_superuser or has_perm(u, "audit.faculty_daily.view_all")):
            emp = _emp_of(u)
            if emp is None:
                return Response([])
            qs = qs.filter(faculty=emp)
        params = request.query_params
        if v := params.get("faculty"):
            qs = qs.filter(faculty_id=v)
        if v := params.get("from"):
            if d := parse_date(v):
                qs = qs.filter(date__gte=d)
        if v := params.get("to"):
            if d := parse_date(v):
                qs = qs.filter(date__lte=d)
        return Response(FacultyDailyReportSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        s = FacultyDailyReportSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        target = s.validated_data["faculty"]
        emp = _emp_of(u)
        if not (u.is_superuser or has_perm(u, "audit.faculty_daily.submit_for_others")
                or (emp and emp.id == target.id)):
            return Response({"detail": "You can only submit for yourself."},
                            status=http.HTTP_403_FORBIDDEN)
        s.save(submitted_by=u)
        return Response(s.data, status=http.HTTP_201_CREATED)


class FacultyDailyReportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return FacultyDailyReport.objects.get(pk=pk)
        except FacultyDailyReport.DoesNotExist as e:
            raise Http404 from e

    def _can_edit(self, user, obj):
        emp = _emp_of(user)
        return (
            user.is_superuser
            or has_perm(user, "audit.faculty_daily.view_all")
            or (emp and obj.faculty_id == emp.id)
        )

    def get(self, request, pk):
        return Response(FacultyDailyReportSerializer(self._obj(pk)).data)

    def patch(self, request, pk):
        obj = self._obj(pk)
        if not self._can_edit(request.user, obj):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = FacultyDailyReportSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


# === 2. Admin Daily Report ==========================================

class AdminDailyReportListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = AdminDailyReport.objects.select_related("user")
        if not (u.is_superuser or has_perm(u, "audit.admin_daily.view_all")):
            qs = qs.filter(user=u)
        params = request.query_params
        if v := params.get("user"):
            qs = qs.filter(user_id=v)
        if v := params.get("from"):
            if d := parse_date(v):
                qs = qs.filter(rep_date__gte=d)
        if v := params.get("to"):
            if d := parse_date(v):
                qs = qs.filter(rep_date__lte=d)
        return Response(AdminDailyReportSerializer(qs[:500], many=True).data)

    def post(self, request):
        # Always submit for self.
        data = dict(request.data)
        data["user"] = request.user.id
        s = AdminDailyReportSerializer(data=data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=http.HTTP_201_CREATED)


class AdminDailyReportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            obj = AdminDailyReport.objects.get(pk=pk)
        except AdminDailyReport.DoesNotExist as e:
            raise Http404 from e
        if not (request.user.is_superuser or obj.user_id == request.user.id):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = AdminDailyReportSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


# === 3. Course End Report ===========================================

class CourseEndReportListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = CourseEndReport.objects.select_related(
            "instructor", "subject", "batch",
        )
        if not (u.is_superuser or has_perm(u, "audit.course_end.view_all")):
            emp = _emp_of(u)
            qs = qs.filter(instructor=emp) if emp else qs.none()
        params = request.query_params
        if v := params.get("batch"):
            qs = qs.filter(batch_id=v)
        if v := params.get("subject"):
            qs = qs.filter(subject_id=v)
        if v := params.get("hod_status"):
            qs = qs.filter(hod_status=v)
        return Response(CourseEndReportSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        if not has_perm(u, "audit.course_end.submit"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = CourseEndReportSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(submitted_by=u)
        return Response(s.data, status=http.HTTP_201_CREATED)


class CourseEndReportReviewView(APIView):
    """HOD approves / returns the course-end report."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not (u.is_superuser or has_perm(u, "audit.course_end.review")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            obj = CourseEndReport.objects.get(pk=pk)
        except CourseEndReport.DoesNotExist as e:
            raise Http404 from e
        s = CourseEndReviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        obj.hod_status = s.validated_data["hod_status"]
        obj.hod_remarks = s.validated_data.get("hod_remarks", "")
        obj.hod_reviewed_at = timezone.now()
        obj.hod_reviewed_by = u
        obj.save(update_fields=[
            "hod_status", "hod_remarks", "hod_reviewed_at",
            "hod_reviewed_by", "updated_at",
        ])
        return Response(CourseEndReportSerializer(obj).data)


# === 4. Batch Mentor Report =========================================

class BatchMentorReportListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = BatchMentorReport.objects.select_related("batch", "mentor")
        if not (u.is_superuser or has_perm(u, "audit.batch_mentor.view_all")):
            emp = _emp_of(u)
            qs = qs.filter(mentor=emp) if emp else qs.none()
        params = request.query_params
        if v := params.get("batch"):
            qs = qs.filter(batch_id=v)
        if v := params.get("year"):
            qs = qs.filter(year=v)
        return Response(BatchMentorReportSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        s = BatchMentorReportSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        # Mentors can submit for their own batches; auditors override.
        emp = _emp_of(u)
        is_mentor = (s.validated_data["batch"].mentor_id == (emp.id if emp else None))
        if not (u.is_superuser or is_mentor
                or has_perm(u, "audit.batch_mentor.submit_for_others")):
            return Response({"detail": "Only the batch mentor can submit."},
                            status=http.HTTP_403_FORBIDDEN)
        s.save(submitted_by=u)
        return Response(s.data, status=http.HTTP_201_CREATED)


# === 5. Student Feedback ============================================

class StudentFeedbackListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = StudentFeedback.objects.select_related(
            "student", "subject", "instructor", "batch",
        )
        # Visibility: students see their own; auditors see all
        if not (u.is_superuser or has_perm(u, "audit.feedback.view_all")):
            student = _student_of(u)
            qs = qs.filter(student=student) if student else qs.none()
        params = request.query_params
        if v := params.get("instructor"):
            qs = qs.filter(instructor_id=v)
        if v := params.get("subject"):
            qs = qs.filter(subject_id=v)
        if v := params.get("batch"):
            qs = qs.filter(batch_id=v)
        return Response(StudentFeedbackSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        student = _student_of(u)
        if student is None:
            return Response({"detail": "Only students can submit feedback."},
                            status=http.HTTP_403_FORBIDDEN)
        # Force student to self.
        data = dict(request.data)
        data["student"] = student.id
        s = StudentFeedbackSerializer(data=data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=http.HTTP_201_CREATED)


# === 6. Faculty Self-Appraisal ======================================

class FacultySelfAppraisalListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = FacultySelfAppraisal.objects.select_related("faculty")
        if not (u.is_superuser or has_perm(u, "audit.self_appraisal.view_all")):
            emp = _emp_of(u)
            qs = qs.filter(faculty=emp) if emp else qs.none()
        params = request.query_params
        if v := params.get("faculty"):
            qs = qs.filter(faculty_id=v)
        if v := params.get("year"):
            qs = qs.filter(year=v)
        return Response(FacultySelfAppraisalSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        s = FacultySelfAppraisalSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        emp = _emp_of(u)
        target = s.validated_data["faculty"]
        if not (u.is_superuser or (emp and emp.id == target.id)):
            return Response({"detail": "You can only submit for yourself."},
                            status=http.HTTP_403_FORBIDDEN)
        s.save(submitted_by=u)
        return Response(s.data, status=http.HTTP_201_CREATED)


class SelfAppraisalReviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not (u.is_superuser or has_perm(u, "audit.self_appraisal.review")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            obj = FacultySelfAppraisal.objects.get(pk=pk)
        except FacultySelfAppraisal.DoesNotExist as e:
            raise Http404 from e
        s = SelfAppraisalReviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        obj.auditor_remarks = s.validated_data["auditor_remarks"]
        obj.auditor_reviewed_at = timezone.now()
        obj.auditor_reviewed_by = u
        obj.save(update_fields=[
            "auditor_remarks", "auditor_reviewed_at",
            "auditor_reviewed_by", "updated_at",
        ])
        return Response(FacultySelfAppraisalSerializer(obj).data)


# === 7. Compliance Flag =============================================

class ComplianceFlagListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not (u.is_superuser or has_perm(u, "audit.compliance.view")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        qs = ComplianceFlag.objects.select_related(
            "target_faculty", "target_batch", "target_student",
            "raised_by", "resolved_by",
        )
        params = request.query_params
        if params.get("open") == "1":
            qs = qs.filter(resolved_at__isnull=True)
        elif params.get("resolved") == "1":
            qs = qs.filter(resolved_at__isnull=False)
        if v := params.get("category"):
            qs = qs.filter(category=v)
        if v := params.get("severity"):
            qs = qs.filter(severity=v)
        if v := params.get("faculty"):
            qs = qs.filter(target_faculty_id=v)
        return Response(ComplianceFlagSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        if not (u.is_superuser or has_perm(u, "audit.compliance.flag")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = ComplianceFlagSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(raised_by=u)
        return Response(s.data, status=http.HTTP_201_CREATED)


class ComplianceFlagResolveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not (u.is_superuser or has_perm(u, "audit.compliance.resolve")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            obj = ComplianceFlag.objects.get(pk=pk)
        except ComplianceFlag.DoesNotExist as e:
            raise Http404 from e
        if obj.resolved_at:
            return Response({"detail": "Already resolved."},
                            status=http.HTTP_400_BAD_REQUEST)
        s = ResolveFlagSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        obj.resolved_at = timezone.now()
        obj.resolved_by = u
        obj.resolution_remarks = s.validated_data["resolution_remarks"]
        obj.save(update_fields=[
            "resolved_at", "resolved_by", "resolution_remarks", "updated_at",
        ])
        return Response(ComplianceFlagSerializer(obj).data)


# === Dashboard reports ==============================================

def _can_view_dashboards(user) -> bool:
    return (user.is_superuser
            or has_perm(user, "audit.report.consolidated"))


class LiveFacultyTrackingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view_dashboards(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        d = parse_date(request.query_params.get("date") or "") or None
        return Response(live_faculty_tracking(on_date=d))


class TimetableAdherenceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view_dashboards(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        params = request.query_params
        start = parse_date(params.get("start") or "")
        end = parse_date(params.get("end") or "")
        if not start or not end:
            return Response({"detail": "start and end (YYYY-MM-DD) required."},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(timetable_adherence(start=start, end=end))


class BatchProgressionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _can_view_dashboards(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            batch = Batch.objects.select_related("campus", "program").get(pk=pk)
        except Batch.DoesNotExist as e:
            raise Http404 from e
        return Response(batch_progression(batch=batch))


class FeedbackSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _can_view_dashboards(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            instr = Employee.objects.get(pk=pk)
        except Employee.DoesNotExist as e:
            raise Http404 from e
        year = request.query_params.get("year")
        return Response(feedback_summary_for_instructor(
            instructor=instr, year=int(year) if year else None,
        ))


class ConsolidatedMonthlyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view_dashboards(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            year = int(request.query_params.get("year") or 0)
            month = int(request.query_params.get("month") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "year and month required (integers)."},
                            status=http.HTTP_400_BAD_REQUEST)
        if not year or not month:
            now = timezone.now()
            year = year or now.year
            month = month or now.month
        try:
            return Response(consolidated_monthly(year=year, month=month))
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
