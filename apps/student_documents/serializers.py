from rest_framework import serializers

from .models import DocumentRequest


class DocumentRequestSerializer(serializers.ModelSerializer):
    """Staff-facing view of a document request."""

    student_name = serializers.CharField(source="student.student_name",
                                         read_only=True)
    application_form_id = serializers.CharField(
        source="student.application_form_id", read_only=True,
    )
    doc_type_label = serializers.CharField(read_only=True)
    attachment_url = serializers.SerializerMethodField()
    decided_by_name = serializers.CharField(
        source="decided_by.username", read_only=True, default="",
    )

    class Meta:
        model = DocumentRequest
        fields = [
            "id", "student", "student_name", "application_form_id",
            "doc_type", "doc_type_other", "doc_type_label",
            "purpose", "status",
            "attachment", "attachment_url",
            "approver_remarks",
            "decided_by", "decided_by_name", "decided_at",
            "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_attachment_url(self, obj):
        if not obj.attachment:
            return None
        request = self.context.get("request")
        return (request.build_absolute_uri(obj.attachment.url)
                if request else obj.attachment.url)


class PortalDocumentRequestSerializer(serializers.ModelSerializer):
    """Student-facing view (no internal decided_by user id)."""

    doc_type_label = serializers.CharField(read_only=True)
    attachment_url = serializers.SerializerMethodField()

    class Meta:
        model = DocumentRequest
        fields = [
            "id", "doc_type", "doc_type_other", "doc_type_label",
            "purpose", "status",
            "attachment_url", "approver_remarks", "decided_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_attachment_url(self, obj):
        if not obj.attachment:
            return None
        request = self.context.get("request")
        return (request.build_absolute_uri(obj.attachment.url)
                if request else obj.attachment.url)


class ApplyDocumentSerializer(serializers.Serializer):
    doc_type = serializers.ChoiceField(choices=DocumentRequest.DocType.choices)
    doc_type_other = serializers.CharField(
        required=False, allow_blank=True, max_length=160,
    )
    purpose = serializers.CharField(min_length=5, max_length=2000)


class DecideDocumentSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[("APPROVED", "Approved"),
                                                ("REJECTED", "Rejected")])
    remarks = serializers.CharField(required=False, allow_blank=True,
                                    max_length=2000)
    attachment = serializers.FileField(required=False, allow_null=True)
