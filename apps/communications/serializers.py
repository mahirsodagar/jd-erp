import json

from django.utils import timezone
from rest_framework import serializers

from apps.common.file_validation import (
    DOCUMENT_MIMES, IMAGE_MIMES, SecureFileField,
)

from .audience import STUDENT_KINDS
from .models import (
    EmailCampaign, EmailCampaignRecipient, EmailTemplate, Suppression,
)

SOURCES = [s for s, _ in EmailCampaign.Source.choices]


# --- Audience -------------------------------------------------------

class AudienceSerializer(serializers.Serializer):
    """`{"source": "leads", "filters": {...}}` — the Compose step's
    audience block. Filter keys are validated loosely: unknown keys are
    ignored, ids must be ints, and students need at least one address
    kind."""

    source = serializers.ChoiceField(choices=SOURCES)
    filters = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        f = attrs.get("filters") or {}
        if attrs["source"] == "students":
            kinds = f.get("recipients") or []
            if not isinstance(kinds, list) or not kinds:
                raise serializers.ValidationError(
                    {"filters": "Pick at least one address to send to."},
                )
            bad = [k for k in kinds if k not in STUDENT_KINDS]
            if bad:
                raise serializers.ValidationError(
                    {"filters": f"Unknown recipient kind: {bad[0]}."},
                )
        if attrs["source"] == "leads":
            st = f.get("status") or []
            if not isinstance(st, list):
                raise serializers.ValidationError(
                    {"filters": "status must be a list."},
                )
        return attrs


# --- Campaigns ------------------------------------------------------

class CampaignCountsMixin:
    def get_counts(self, obj):
        # Annotated by the view's queryset; fall back to a query when a
        # bare instance is serialised (create response).
        keys = ("total", "sent", "failed", "pending", "unsubscribed", "skipped")
        if hasattr(obj, "n_total"):
            return {k: getattr(obj, f"n_{k}") for k in keys}
        rows = obj.recipients.values_list("status", flat=True)
        counts = dict.fromkeys(keys, 0)
        for s in rows:
            counts["total"] += 1
            counts[s] += 1
        return counts


class CampaignSerializer(CampaignCountsMixin, serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    counts = serializers.SerializerMethodField()

    class Meta:
        model = EmailCampaign
        fields = (
            "id", "subject", "source", "audience_summary", "filter_labels",
            "from_email", "reply_to", "body_html", "include_unsubscribe",
            "attachment_name", "attachment_size", "template", "template_name",
            "status", "scheduled_at", "created_by", "created_by_name",
            "created_at", "started_at", "completed_at", "counts",
        )
        read_only_fields = fields

    def get_created_by_name(self, obj):
        u = obj.created_by
        if not u:
            return ""
        return (u.full_name or u.username)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["template_id"] = data.pop("template")
        return data


class CampaignListSerializer(CampaignSerializer):
    """History rows don't need the body."""

    class Meta(CampaignSerializer.Meta):
        fields = tuple(f for f in CampaignSerializer.Meta.fields if f != "body_html")
        read_only_fields = fields


class CampaignRecipientSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailCampaignRecipient
        fields = ("id", "name", "email", "context", "status", "error", "sent_at")
        read_only_fields = fields


class CampaignCreateSerializer(serializers.Serializer):
    """Multipart: `payload` (JSON string) + optional `attachment` file.
    Sent as multipart so the attachment rides along in one request."""

    payload = serializers.CharField()
    attachment = SecureFileField(
        allowed_mimes=DOCUMENT_MIMES | IMAGE_MIMES, max_size_mb=5,
        required=False, allow_null=True,
    )

    def validate_payload(self, raw):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as e:
            raise serializers.ValidationError("payload must be JSON.") from e
        if not isinstance(data, dict):
            raise serializers.ValidationError("payload must be an object.")

        subject = (data.get("subject") or "").strip()
        if not subject:
            raise serializers.ValidationError({"subject": "Subject is required."})
        if len(subject) > 200:
            raise serializers.ValidationError({"subject": "Subject is too long."})

        body = data.get("body_html") or ""
        import re
        if not re.sub(r"<[^>]*>", "", body).strip():
            raise serializers.ValidationError({"body_html": "Write something in the body."})

        aud = AudienceSerializer(data=data.get("audience") or {})
        aud.is_valid(raise_exception=True)

        reply_to = (data.get("reply_to") or "").strip()
        if reply_to:
            serializers.EmailField().run_validation(reply_to)

        scheduled_at = data.get("scheduled_at") or None
        if scheduled_at:
            dt = serializers.DateTimeField().run_validation(scheduled_at)
            if dt <= timezone.now():
                raise serializers.ValidationError(
                    {"scheduled_at": "Pick a time in the future."},
                )
            scheduled_at = dt

        template_id = data.get("template_id")
        template = None
        if template_id not in (None, ""):
            template = EmailTemplate.objects.filter(pk=template_id).first()

        excluded = data.get("excluded_keys") or []
        if not isinstance(excluded, list):
            raise serializers.ValidationError({"excluded_keys": "Must be a list."})

        labels = data.get("filter_labels") or {}
        if not isinstance(labels, dict):
            labels = {}

        return {
            "subject": subject,
            "audience": aud.validated_data,
            "filter_labels": {str(k): str(v) for k, v in labels.items()},
            "excluded_keys": {str(k) for k in excluded},
            "reply_to": reply_to,
            "body_html": body,
            "include_unsubscribe": bool(data.get("include_unsubscribe", True)),
            "template": template,
            "scheduled_at": scheduled_at,
        }


class TestSendSerializer(serializers.Serializer):
    to = serializers.EmailField()
    subject = serializers.CharField(max_length=200)
    body_html = serializers.CharField(allow_blank=True)


# --- Templates ------------------------------------------------------

class EmailTemplateSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = EmailTemplate
        fields = ("id", "name", "subject", "body_html", "updated_at", "updated_by_name")
        read_only_fields = ("id", "updated_at", "updated_by_name")
        extra_kwargs = {
            "subject": {"allow_blank": True, "required": False},
            "body_html": {"allow_blank": True, "required": False},
        }

    def get_updated_by_name(self, obj):
        u = obj.updated_by or obj.created_by
        if not u:
            return ""
        return (u.full_name or u.username)

    def validate_name(self, v):
        v = v.strip()
        if not v:
            raise serializers.ValidationError("Template name is required.")
        qs = EmailTemplate.objects.filter(name__iexact=v)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A template with this name already exists.")
        return v


# --- Suppression ----------------------------------------------------

class SuppressionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Suppression
        fields = ("id", "email", "reason", "source", "added_at")
        read_only_fields = fields


class SuppressionAddSerializer(serializers.Serializer):
    emails = serializers.ListField(
        child=serializers.CharField(), allow_empty=False, max_length=2000,
    )
