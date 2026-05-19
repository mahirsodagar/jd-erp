from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Task
from .serializers import (
    CompleteTaskSerializer, TaskCreateSerializer, TaskSerializer,
)
from .services import notify_task_assigned, notify_task_completed


def _scope_for(user):
    """Default visibility — match JD_ERP's `created_by=$userid OR
    task_assign=$userid`. Superusers and users with `tasks.view_all`
    see everything (mirrors the All-Tasks report)."""
    base = Task.objects.select_related("assignee", "created_by")
    if user.is_superuser:
        return base
    if user.roles.filter(permissions__key="tasks.view_all").exists():
        return base
    return base.filter(Q(created_by=user) | Q(assignee=user))


class TaskListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = _scope_for(request.user)

        # ?status=pending|completed (default returns both, newest first)
        s = request.query_params.get("status")
        if s == "pending":
            qs = qs.filter(status=Task.Status.PENDING)
        elif s == "completed":
            qs = qs.filter(status=Task.Status.COMPLETED)

        # ?scope=mine_created | mine_assigned filters the user's own slice.
        scope = request.query_params.get("scope")
        if scope == "mine_created":
            qs = qs.filter(created_by=request.user)
        elif scope == "mine_assigned":
            qs = qs.filter(assignee=request.user)

        # ?all=1 forces the unscoped report view (still gated by perms in
        # _scope_for — non-perm users just get their normal scope).
        return Response(TaskSerializer(qs, many=True).data)

    def post(self, request):
        s = TaskCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        task = Task.objects.create(
            **s.validated_data, created_by=request.user,
        )
        # Best-effort email — never block the API on it.
        try:
            notify_task_assigned(task=task)
        except Exception:
            pass
        return Response(
            TaskSerializer(task).data, status=http.HTTP_201_CREATED,
        )


class TaskDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self, pk: int, user) -> Task:
        try:
            return _scope_for(user).get(pk=pk)
        except Task.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        return Response(TaskSerializer(self._obj(pk, request.user)).data)

    def patch(self, request, pk):
        """PHP allowed the creator to edit name/description/end_date
        inline; the assignee separately edits their own `assignee_remarks`.
        We enforce the same rule per-field here."""
        task = self._obj(pk, request.user)
        if task.status == Task.Status.COMPLETED:
            return Response(
                {"detail": "Completed tasks cannot be edited."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        is_creator = (task.created_by_id == request.user.id
                      or request.user.is_superuser)
        is_assignee = task.assignee_id == request.user.id
        data = request.data

        creator_fields = {"name", "description", "end_date"}
        assignee_fields = {"assignee_remarks"}

        sent = set(data.keys())
        disallowed = set()
        if not is_creator:
            disallowed |= (sent & creator_fields)
        if not is_assignee and not is_creator:
            disallowed |= (sent & assignee_fields)
        # Reassignment is creator-only.
        if "assignee" in sent and not is_creator:
            disallowed.add("assignee")

        if disallowed:
            return Response(
                {"detail": f"Cannot edit: {sorted(disallowed)}."},
                status=http.HTTP_403_FORBIDDEN,
            )

        for f in ("name", "description", "end_date",
                  "assignee_remarks", "assignee"):
            if f in data:
                setattr(task, f, data[f])
        task.save()
        return Response(TaskSerializer(task).data)

    def delete(self, request, pk):
        task = self._obj(pk, request.user)
        if not (request.user.is_superuser
                or task.created_by_id == request.user.id
                or task.assignee_id == request.user.id):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        task.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


class TaskCompleteView(APIView):
    """Assignee marks the task done. Saves a `task_assign_remarks`
    note at the same time, like the PHP screen."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            task = Task.objects.select_related(
                "assignee", "created_by",
            ).get(pk=pk)
        except Task.DoesNotExist as e:
            raise Http404 from e

        if task.assignee_id != request.user.id and not request.user.is_superuser:
            return Response({"detail": "Only the assignee can complete this task."},
                            status=http.HTTP_403_FORBIDDEN)
        if task.status == Task.Status.COMPLETED:
            return Response({"detail": "Task is already completed."},
                            status=http.HTTP_400_BAD_REQUEST)

        s = CompleteTaskSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        task.assignee_remarks = s.validated_data["assignee_remarks"]
        task.status = Task.Status.COMPLETED
        task.completed_at = timezone.now()
        task.save(update_fields=[
            "assignee_remarks", "status", "completed_at", "updated_at",
        ])
        try:
            notify_task_completed(task=task)
        except Exception:
            pass
        return Response(TaskSerializer(task).data)
