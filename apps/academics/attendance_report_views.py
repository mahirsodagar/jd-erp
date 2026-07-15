"""Attendance Report module — read-only report endpoints (five tabs +
per-module date grid). All gated on `academics.attendance.view_report`.
The per-slot student modal reuses the existing roster endpoint."""

from django.http import Http404
from django.utils.dateparse import parse_date
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.models import Batch

from . import attendance_reports as reports
from .permissions import has_perm


def _can(user) -> bool:
    return user.is_superuser or has_perm(user, "academics.attendance.view_report")


def _deny():
    return Response({"detail": "Permission denied."},
                    status=http.HTTP_403_FORBIDDEN)


def _int(params, key):
    v = params.get(key)
    return int(v) if v and str(v).isdigit() else None


def _common_filters(params) -> dict:
    """Filters shared by the Activity + Instructor-log reports."""
    return {
        "from_date": parse_date(params.get("from") or "") or None,
        "to_date": parse_date(params.get("to") or "") or None,
        "academic_year": _int(params, "academic_year"),
        "campus": _int(params, "campus"),
        "program": _int(params, "program"),
        "batch": _int(params, "batch"),
    }


class ActivityReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can(request.user):
            return _deny()
        return Response(reports.activity_report(**_common_filters(
            request.query_params)))


class InstructorLogView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _can(request.user):
            return _deny()
        p = request.query_params
        return Response(reports.activity_report(
            instructor=pk,
            from_date=parse_date(p.get("from") or "") or None,
            to_date=parse_date(p.get("to") or "") or None,
            academic_year=_int(p, "academic_year"),
            campus=_int(p, "campus"),
        ))


class RemarksReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can(request.user):
            return _deny()
        p = request.query_params
        return Response(reports.remarks_report(
            batch=_int(p, "batch"),
            subject=_int(p, "subject"),
            from_date=parse_date(p.get("from") or "") or None,
            to_date=parse_date(p.get("to") or "") or None,
        ))


class BatchWiseReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _can(request.user):
            return _deny()
        try:
            batch = Batch.objects.get(pk=pk)
        except Batch.DoesNotExist as e:
            raise Http404 from e
        p = request.query_params
        return Response(reports.batch_wise_report(
            batch=batch,
            from_date=parse_date(p.get("from") or "") or None,
            to_date=parse_date(p.get("to") or "") or None,
            semester=_int(p, "semester"),
        ))


class BatchSemestersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _can(request.user):
            return _deny()
        try:
            batch = Batch.objects.get(pk=pk)
        except Batch.DoesNotExist as e:
            raise Http404 from e
        return Response(reports.batch_semesters(batch))


class StudentWiseReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _can(request.user):
            return _deny()
        from apps.admissions.models import Student
        try:
            student = Student.objects.get(pk=pk)
        except Student.DoesNotExist as e:
            raise Http404 from e
        p = request.query_params
        return Response(reports.student_wise_report(
            student=student,
            from_date=parse_date(p.get("from") or "") or None,
            to_date=parse_date(p.get("to") or "") or None,
        ))


class ModuleGridView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can(request.user):
            return _deny()
        p = request.query_params
        subject_id = _int(p, "subject")
        batch_id = _int(p, "batch")
        if not subject_id or not batch_id:
            return Response({"detail": "subject and batch are required."},
                            status=http.HTTP_400_BAD_REQUEST)
        try:
            batch = Batch.objects.get(pk=batch_id)
        except Batch.DoesNotExist as e:
            raise Http404 from e
        return Response(reports.module_grid(
            subject_id=subject_id,
            batch=batch,
            from_date=parse_date(p.get("from") or "") or None,
            to_date=parse_date(p.get("to") or "") or None,
        ))
