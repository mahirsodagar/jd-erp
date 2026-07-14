"""Staff-side student-appointment views. The student-side book/list/cancel
flow lives in apps/portal."""

from django.http import Http404
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import StudentAppointment
from .serializers import (
    DecideAppointmentSerializer, StudentAppointmentSerializer,
)


def _has_perm(user, key: str) -> bool:
    return user.is_authenticated and (
        user.is_superuser
        or user.roles.filter(permissions__key=key).exists()
    )


class AppointmentListView(APIView):
    """Staff: list student appointment requests across the system."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_perm(request.user, "appointments.view_all"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        qs = (StudentAppointment.objects
              .select_related("student", "faculty", "decided_by"))
        p = request.query_params
        if v := p.get("status"):
            qs = qs.filter(status=v)
        if v := p.get("team"):
            qs = qs.filter(team=v)
        if v := p.get("faculty"):
            qs = qs.filter(faculty_id=v)
        if v := p.get("student"):
            qs = qs.filter(student_id=v)
        return Response(StudentAppointmentSerializer(qs, many=True).data)


class AppointmentDecideView(APIView):
    """Staff: confirm (optionally reschedule) or decline a request."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _has_perm(request.user, "appointments.decide"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            appt = StudentAppointment.objects.select_related("student").get(pk=pk)
        except StudentAppointment.DoesNotExist as e:
            raise Http404 from e
        s = DecideAppointmentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            services.decide_appointment(
                appointment=appt,
                decision=d["decision"],
                scheduled_date=d.get("scheduled_date"),
                scheduled_time=d.get("scheduled_time"),
                venue=d.get("venue", ""),
                remarks=d.get("remarks", ""),
                decided_by=request.user,
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(StudentAppointmentSerializer(appt).data)


class AppointmentCompleteView(APIView):
    """Staff: mark a confirmed appointment as completed."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _has_perm(request.user, "appointments.decide"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            appt = StudentAppointment.objects.select_related("student").get(pk=pk)
        except StudentAppointment.DoesNotExist as e:
            raise Http404 from e
        try:
            services.complete_appointment(appointment=appt,
                                          decided_by=request.user)
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(StudentAppointmentSerializer(appt).data)
