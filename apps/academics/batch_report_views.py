"""Batch Report module — read endpoints (batch list + student roster)
plus the two feedback-link mutations (edit link, toggle enable).

Read is gated on ``academics.batch_report.view``; the feedback-link
mutation on ``academics.batch_report.edit_feedback``.
"""

from django.http import Http404
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.models import Batch

from . import batch_report as reports
from .permissions import has_perm


def _can_view(user) -> bool:
    return user.is_superuser or has_perm(user, "academics.batch_report.view")


def _can_edit(user) -> bool:
    return user.is_superuser or has_perm(user, "academics.batch_report.edit_feedback")


def _deny():
    return Response({"detail": "Permission denied."},
                    status=http.HTTP_403_FORBIDDEN)


def _int(params, key):
    v = params.get(key)
    return int(v) if v and str(v).isdigit() else None


def _get_batch(pk):
    try:
        return Batch.objects.select_related("program", "campus").get(pk=pk)
    except Batch.DoesNotExist as e:
        raise Http404 from e


class BatchReportListView(APIView):
    """GET — batch list filtered by academic_year / campus / program."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view(request.user):
            return _deny()
        p = request.query_params
        return Response(reports.batch_list(
            academic_year=_int(p, "academic_year"),
            campus=_int(p, "campus"),
            program=_int(p, "program"),
        ))


class BatchRosterView(APIView):
    """GET — full student roster for one batch (modal)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _can_view(request.user):
            return _deny()
        return Response(reports.batch_roster(_get_batch(pk)))


class BatchFeedbackView(APIView):
    """PATCH — update ``feedback_link`` and/or ``feedback_link_enabled``
    for one batch. Accepts either field; both optional."""

    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if not _can_edit(request.user):
            return _deny()
        batch = _get_batch(pk)
        data = request.data or {}
        updated = []
        if "feedback_link" in data:
            batch.feedback_link = (data.get("feedback_link") or "").strip()
            updated.append("feedback_link")
        if "feedback_link_enabled" in data:
            batch.feedback_link_enabled = bool(data.get("feedback_link_enabled"))
            updated.append("feedback_link_enabled")
        if not updated:
            return Response(
                {"detail": "Nothing to update."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        batch.save(update_fields=[*updated, "updated_at"])
        return Response({
            "batch_id": batch.id,
            "feedback_link": batch.feedback_link,
            "feedback_link_enabled": batch.feedback_link_enabled,
        })
