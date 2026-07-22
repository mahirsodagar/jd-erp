"""HR / mentor-side student-leave views.

Mirrors the legacy academics/student_leaves.php (mentor approval console,
scoped by batch mentor) and academics/student_leave_report.php (admin
report + delete, campus-scoped). Student-side apply/list lives in
apps/portal.
"""

from django.db.models import Q
from django.http import Http404
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import StudentLeaveApplication
from .serializers import (
    DecideStudentLeaveSerializer, StudentLeaveApplicationSerializer,
)


def _has_perm(user, key: str) -> bool:
    return user.is_authenticated and (
        user.is_superuser
        or user.roles.filter(permissions__key=key).exists()
    )


def _mentor_emails(user) -> list[str]:
    """Emails identifying this user as a batch mentor: the account email plus
    the linked employee's primary email (batch_mentor_email is stored as the
    mentor's Employee.email_primary)."""
    emails = []
    if user.email:
        emails.append(user.email.lower())
    emp = getattr(user, "employee", None)
    if emp and emp.email_primary:
        e = emp.email_primary.lower()
        if e not in emails:
            emails.append(e)
    return emails


class StudentLeaveListView(APIView):
    """Mentor console (default): leaves whose batch mentor is the current
    user. ``?scope=all`` returns every leave for staff holding
    ``student_leaves.view_all`` (used by the report page)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        scope = request.query_params.get("scope", "mine")
        qs = (StudentLeaveApplication.objects
              .select_related("student", "student__campus", "decided_by"))

        if scope == "all":
            if not _has_perm(request.user, "student_leaves.view_all"):
                return Response({"detail": "Permission denied."},
                                status=http.HTTP_403_FORBIDDEN)
        else:
            emails = _mentor_emails(request.user)
            if not emails:
                return Response([])
            q = Q()
            for e in emails:
                q |= Q(batch_mentor_email__iexact=e)
            qs = qs.filter(q)

        if v := request.query_params.get("status"):
            qs = qs.filter(status=v)
        if v := request.query_params.get("student"):
            qs = qs.filter(student_id=v)
        return Response(StudentLeaveApplicationSerializer(qs, many=True).data)


class StudentLeaveReportView(APIView):
    """Admin report — campus-scoped. ``student_leaves.report.view_all`` sees
    all campuses; ``student_leaves.report.view`` is limited to the user's
    campuses (legacy role_id==16 vs campus restriction)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        all_campuses = u.is_superuser or _has_perm(u, "student_leaves.report.view_all")
        if not (all_campuses or _has_perm(u, "student_leaves.report.view")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        qs = (StudentLeaveApplication.objects
              .select_related("student", "student__campus", "decided_by")
              .order_by("-created_at"))
        if not all_campuses:
            qs = qs.filter(student__campus__in=u.campuses.all())

        params = request.query_params
        if v := params.get("status"):
            qs = qs.filter(status=v)
        if v := params.get("campus"):
            qs = qs.filter(student__campus_id=v)
        return Response(StudentLeaveApplicationSerializer(qs[:5000], many=True).data)


class StudentLeaveDecideView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _has_perm(request.user, "student_leaves.decide"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            app = StudentLeaveApplication.objects.select_related("student").get(pk=pk)
        except StudentLeaveApplication.DoesNotExist as e:
            raise Http404 from e
        s = DecideStudentLeaveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.decide_leave(
                application=app,
                decision=s.validated_data["decision"],
                remarks=s.validated_data.get("remarks", ""),
                decided_by=request.user,
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(StudentLeaveApplicationSerializer(app).data)


class StudentLeaveDeleteView(APIView):
    """Legacy student_leave_report.php delete — privileged HR only."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        if not _has_perm(request.user, "student_leaves.delete"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            app = StudentLeaveApplication.objects.get(pk=pk)
        except StudentLeaveApplication.DoesNotExist as e:
            raise Http404 from e
        app.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)
