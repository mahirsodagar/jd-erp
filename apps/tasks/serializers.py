from rest_framework import serializers

from .models import Task


class TaskSerializer(serializers.ModelSerializer):
    assignee_name = serializers.CharField(
        source="assignee.full_name", read_only=True, default="",
    )
    assignee_username = serializers.CharField(
        source="assignee.username", read_only=True,
    )
    assignee_email = serializers.CharField(
        source="assignee.email", read_only=True,
    )
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default="",
    )
    created_by_username = serializers.CharField(
        source="created_by.username", read_only=True,
    )

    class Meta:
        model = Task
        fields = [
            "id",
            "name", "description", "end_date",
            "assignee", "assignee_name", "assignee_username", "assignee_email",
            "assignee_remarks",
            "status", "completed_at",
            "created_by", "created_by_name", "created_by_username",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "completed_at",
            "assignee_name", "assignee_username", "assignee_email",
            "created_by", "created_by_name", "created_by_username",
            "created_at", "updated_at",
        ]


class TaskCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = ["name", "description", "end_date", "assignee"]

    def validate(self, attrs):
        # Block "Task Name Already Submitted" early with a clean field
        # error rather than a 500 from the DB unique constraint.
        if Task.objects.filter(
            name=attrs["name"], assignee=attrs["assignee"],
        ).exists():
            raise serializers.ValidationError(
                {"name": "Task with this name already assigned to that user."},
            )
        return attrs


class CompleteTaskSerializer(serializers.Serializer):
    """Assignee marks a task done. The PHP UI requires assignee_remarks
    to be non-empty before calling this; we re-validate server-side."""

    assignee_remarks = serializers.CharField(min_length=1, max_length=4000)
