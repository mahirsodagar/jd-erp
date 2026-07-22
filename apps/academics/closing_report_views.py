"""Closing Report module — read endpoint (composite report) plus the
inline awards / portfolio / remarks upsert.

Read is gated on ``academics.closing_report.view``; the awards upsert on
``academics.closing_report.edit``.
"""

from django.http import Http404
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admissions.models import Student
from apps.master.models import Batch

from . import closing_report as reports
from .permissions import has_perm


def _can_view(user) -> bool:
    return user.is_superuser or has_perm(user, "academics.closing_report.view")


def _can_edit(user) -> bool:
    return user.is_superuser or has_perm(user, "academics.closing_report.edit")


def _deny():
    return Response({"detail": "Permission denied."},
                    status=http.HTTP_403_FORBIDDEN)


def _get_batch(pk):
    try:
        return (Batch.objects
                .select_related("program", "campus", "academic_year", "mentor")
                .get(pk=pk))
    except Batch.DoesNotExist as e:
        raise Http404 from e


class ClosingReportView(APIView):
    """GET — full closing report for one batch."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _can_view(request.user):
            return _deny()
        return Response(reports.closing_report(_get_batch(pk)))


class ClosingAwardSaveView(APIView):
    """PATCH — upsert awards / portfolio / remarks for one student in a
    batch. Body: ``{student, batch, awards?, portfolio?, remarks?}`` —
    only the supplied text fields are written."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not _can_edit(request.user):
            return _deny()
        batch = _get_batch(pk)
        data = request.data or {}
        student_id = data.get("student")
        if not student_id:
            return Response({"detail": "student is required."},
                            status=http.HTTP_400_BAD_REQUEST)
        try:
            student = Student.objects.get(pk=student_id)
        except Student.DoesNotExist as e:
            raise Http404 from e

        fields = {k: data[k] for k in ("awards", "portfolio", "remarks")
                  if k in data}
        if not fields:
            return Response({"detail": "Nothing to update."},
                            status=http.HTTP_400_BAD_REQUEST)

        obj = reports.save_award(
            student=student, batch=batch, user=request.user, **fields,
        )
        return Response({
            "student": obj.student_id,
            "batch": obj.batch_id,
            "awards": obj.awards,
            "portfolio": obj.portfolio,
            "remarks": obj.remarks,
        })
