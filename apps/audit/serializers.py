from auditlog.models import LogEntry
from rest_framework import serializers

from .models import AuthLog


class AuthLogSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(source="actor.username", read_only=True)
    target_username = serializers.CharField(source="target.username", read_only=True)

    class Meta:
        model = AuthLog
        fields = [
            "id", "event", "actor", "actor_username",
            "target", "target_username", "identifier",
            "ip_address", "user_agent", "metadata", "created_at",
        ]
        read_only_fields = fields


class DataAuditSerializer(serializers.ModelSerializer):
    """Wraps django-auditlog's LogEntry."""

    actor_username = serializers.SerializerMethodField()
    object_repr = serializers.CharField(read_only=True)
    content_type = serializers.SerializerMethodField()

    class Meta:
        model = LogEntry
        fields = [
            "id", "action", "object_id", "object_repr",
            "content_type", "actor", "actor_username",
            "changes", "remote_addr", "timestamp",
        ]
        read_only_fields = fields

    def get_actor_username(self, obj):
        return getattr(obj.actor, "username", None)

    def get_content_type(self, obj):
        ct = obj.content_type
        return f"{ct.app_label}.{ct.model}" if ct else None
