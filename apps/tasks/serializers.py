import os

from rest_framework import serializers

from apps.common.file_validation import (
    DOCUMENT_MIMES, IMAGE_MIMES, SecureFileField,
)

from .models import Task

ATTACHMENT_MIMES = IMAGE_MIMES | DOCUMENT_MIMES


class TaskSerializer(serializers.ModelSerializer):
    attachment_url = serializers.SerializerMethodField()
    attachment_name = serializers.SerializerMethodField()
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
            "attachment_url", "attachment_name",
            "status", "completed_at",
            "created_by", "created_by_name", "created_by_username",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "completed_at",
            "assignee_name", "assignee_username", "assignee_email",
            "attachment_url", "attachment_name",
            "created_by", "created_by_name", "created_by_username",
            "created_at", "updated_at",
        ]

    def get_attachment_url(self, obj):
        if not obj.attachment:
            return None
        request = self.context.get("request")
        url = obj.attachment.url
        return request.build_absolute_uri(url) if request else url

    def get_attachment_name(self, obj):
        return os.path.basename(obj.attachment.name) if obj.attachment else ""


class TaskCreateSerializer(serializers.ModelSerializer):
    # Content-sniffed (not just by extension), capped at 25 MB; rejected
    # uploads never reach storage.
    attachment = SecureFileField(
        allowed_mimes=ATTACHMENT_MIMES, max_size_mb=25,
        required=False, allow_null=True,
    )

    class Meta:
        model = Task
        fields = ["name", "description", "end_date", "assignee", "attachment"]

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


class LateStatusSerializer(serializers.Serializer):
    """Assignee records an overdue task as Incomplete or Overdue, with a
    note explaining why (same remarks rule as completing)."""

    status = serializers.ChoiceField(choices=[
        (Task.Status.INCOMPLETE, "Incomplete"),
        (Task.Status.OVERDUE, "Overdue"),
    ])
    assignee_remarks = serializers.CharField(min_length=1, max_length=4000)
