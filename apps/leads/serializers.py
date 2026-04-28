from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.master.models import Campus, LeadSource, Program

from .models import (
    Lead, LeadCommunication, LeadFollowup, LeadStatusHistory, LeadUtm,
)

User = get_user_model()


class LeadUtmSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadUtm
        fields = [
            "utm_source", "utm_campaign", "utm_medium",
            "utm_term", "utm_content",
        ]


class _LeadBaseSerializer(serializers.ModelSerializer):
    """Shared validation: program must be offered at the chosen campus."""

    def validate(self, attrs):
        campus = attrs.get("campus") or getattr(self.instance, "campus", None)
        program = attrs.get("program") or getattr(self.instance, "program", None)
        if campus and program and not program.campuses.filter(pk=campus.pk).exists():
            raise serializers.ValidationError({
                "program": "This program is not offered at the chosen campus.",
            })
        return attrs


class LeadCreateSerializer(_LeadBaseSerializer):
    """Manual create, used by counselors via the Add Lead form."""

    class Meta:
        model = Lead
        fields = [
            "name", "email", "phone",
            "campus", "program", "source", "assign_to",
            "remarks", "city", "state",
        ]


class LeadUpdateSerializer(_LeadBaseSerializer):
    """Edit lead — does NOT include status (use the status endpoint)
    or assign_to (use the reassign endpoint). Those changes are routed
    through services to write history rows."""

    class Meta:
        model = Lead
        fields = [
            "name", "email", "phone",
            "campus", "program", "source",
            "remarks", "city", "state",
        ]


class LeadDetailSerializer(serializers.ModelSerializer):
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    program_name = serializers.CharField(source="program.name", read_only=True)
    source_name = serializers.CharField(source="source.name", read_only=True)
    assign_to_name = serializers.CharField(source="assign_to.username", read_only=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    utm = LeadUtmSerializer(read_only=True)

    class Meta:
        model = Lead
        fields = [
            "id", "name", "email", "phone",
            "campus", "campus_name",
            "program", "program_name",
            "source", "source_name",
            "assign_to", "assign_to_name",
            "status", "remarks", "city", "state",
            "is_repeated", "duplicate_of",
            "created_by", "created_by_name",
            "created_at", "updated_at",
            "utm",
        ]
        read_only_fields = fields


class LeadIntakeSerializer(_LeadBaseSerializer):
    """Payload for the public intake endpoint.

    External callers reference master records by either id or code/slug
    (more forgiving since they may not know our internal ids).
    UTM fields are accepted at the top level.
    """

    campus_code = serializers.CharField(required=False, write_only=True)
    program_code = serializers.CharField(required=False, write_only=True)
    source_slug = serializers.CharField(required=False, write_only=True)
    assign_to_username = serializers.CharField(required=False, write_only=True)

    utm_source = serializers.CharField(required=False, allow_blank=True, write_only=True)
    utm_campaign = serializers.CharField(required=False, allow_blank=True, write_only=True)
    utm_medium = serializers.CharField(required=False, allow_blank=True, write_only=True)
    utm_term = serializers.CharField(required=False, allow_blank=True, write_only=True)
    utm_content = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Lead
        fields = [
            "name", "email", "phone",
            "campus", "campus_code",
            "program", "program_code",
            "source", "source_slug",
            "assign_to", "assign_to_username",
            "remarks", "city", "state",
            "utm_source", "utm_campaign", "utm_medium", "utm_term", "utm_content",
        ]
        extra_kwargs = {
            "campus": {"required": False},
            "program": {"required": False},
            "source": {"required": False},
            "assign_to": {"required": False},
        }

    def _resolve(self, model, *, id_value, lookup_field, lookup_value, label):
        if id_value:
            return id_value
        if lookup_value:
            try:
                return model.objects.get(**{lookup_field: lookup_value})
            except model.DoesNotExist:
                raise serializers.ValidationError({label: f"Unknown {label} '{lookup_value}'."})
        raise serializers.ValidationError({label: f"{label} is required."})

    def validate(self, attrs):
        attrs["campus"] = self._resolve(
            Campus, id_value=attrs.get("campus"),
            lookup_field="code", lookup_value=attrs.pop("campus_code", None),
            label="campus",
        )
        attrs["program"] = self._resolve(
            Program, id_value=attrs.get("program"),
            lookup_field="code", lookup_value=attrs.pop("program_code", None),
            label="program",
        )
        attrs["source"] = self._resolve(
            LeadSource, id_value=attrs.get("source"),
            lookup_field="slug", lookup_value=attrs.pop("source_slug", None),
            label="source",
        )
        attrs["assign_to"] = self._resolve(
            User, id_value=attrs.get("assign_to"),
            lookup_field="username", lookup_value=attrs.pop("assign_to_username", None),
            label="assign_to",
        )
        return super().validate(attrs)

    def split_payload(self):
        """Returns (lead_kwargs, utm_dict) after validation."""
        data = dict(self.validated_data)
        utm = {
            "utm_source": data.pop("utm_source", "") or "",
            "utm_campaign": data.pop("utm_campaign", "") or "",
            "utm_medium": data.pop("utm_medium", "") or "",
            "utm_term": data.pop("utm_term", "") or "",
            "utm_content": data.pop("utm_content", "") or "",
        }
        return data, utm


class StatusChangeSerializer(serializers.Serializer):
    new_status = serializers.ChoiceField(choices=Lead.Status.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=400)


class ReassignSerializer(serializers.Serializer):
    assign_to = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())


class StatusHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source="changed_by.username", read_only=True)

    class Meta:
        model = LeadStatusHistory
        fields = ["id", "old_status", "new_status", "note",
                  "changed_by", "changed_by_name", "changed_at"]
        read_only_fields = fields


class LeadFollowupSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = LeadFollowup
        fields = ["id", "lead", "followup_type", "notes", "next_followup_date",
                  "created_by", "created_by_name", "created_at"]
        read_only_fields = ["id", "created_by", "created_by_name", "created_at"]


class LeadCommunicationSerializer(serializers.ModelSerializer):
    logged_by_name = serializers.CharField(source="logged_by.username", read_only=True)

    class Meta:
        model = LeadCommunication
        fields = ["id", "lead", "type", "subject", "message", "sent_at",
                  "logged_by", "logged_by_name", "logged_at"]
        read_only_fields = ["id", "logged_by", "logged_by_name", "logged_at"]
