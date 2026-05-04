"""HR-side student-leave views. Student-side apply/list lives in apps/portal."""

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


class StudentLeaveListView(APIView):
    """Staff/HR: list student leaves across the system."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_perm(request.user, "student_leaves.view_all"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        qs = (StudentLeaveApplication.objects
              .select_related("student", "decided_by"))
        if v := request.query_params.get("status"):
            qs = qs.filter(status=v)
        if v := request.query_params.get("student"):
            qs = qs.filter(student_id=v)
        return Response(StudentLeaveApplicationSerializer(qs, many=True).data)


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
