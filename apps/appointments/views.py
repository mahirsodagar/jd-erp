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


def _my_employee_id(user):
    """The Employee id a faculty request would be addressed to, if any."""
    emp = getattr(user, "employee", None)
    return emp.id if emp is not None else None


def _addressed_to_me(user, appt) -> bool:
    """True when this request names the caller as the faculty member.

    Team-addressed requests (no `faculty`) are never "mine" — there is
    no team-membership model to resolve them against, so they are
    visible only with `appointments.view_all`.
    """
    emp_id = _my_employee_id(user)
    return emp_id is not None and appt.faculty_id == emp_id


def _in_scope(user, appt) -> bool:
    return _has_perm(user, "appointments.view_all") or _addressed_to_me(user, appt)


class AppointmentListView(APIView):
    """Staff: list student appointment requests across the system."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = (StudentAppointment.objects
              .select_related("student", "faculty", "decided_by"))
        if not _has_perm(u, "appointments.view_all"):
            # Self-service: a faculty member sees requests addressed to
            # them, and nothing if none are.
            emp_id = _my_employee_id(u)
            if emp_id is None:
                return Response([])
            qs = qs.filter(faculty_id=emp_id)
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
        try:
            appt = StudentAppointment.objects.select_related("student").get(pk=pk)
        except StudentAppointment.DoesNotExist as e:
            raise Http404 from e

        s = DecideAppointmentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        needed = (
            "appointments.confirm"
            if d["decision"] == StudentAppointment.Status.CONFIRMED
            else "appointments.decline"
        )
        if not _has_perm(request.user, needed):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        # Same scope as the list — otherwise a request addressed to a
        # colleague could still be answered by id.
        if not _in_scope(request.user, appt):
            return Response(
                {"detail": "This request is not addressed to you."},
                status=http.HTTP_403_FORBIDDEN,
            )

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
        if not _has_perm(request.user, "appointments.complete"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            appt = StudentAppointment.objects.select_related("student").get(pk=pk)
        except StudentAppointment.DoesNotExist as e:
            raise Http404 from e
        if not _in_scope(request.user, appt):
            return Response(
                {"detail": "This request is not addressed to you."},
                status=http.HTTP_403_FORBIDDEN,
            )
        try:
            services.complete_appointment(appointment=appt,
                                          decided_by=request.user)
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(StudentAppointmentSerializer(appt).data)
