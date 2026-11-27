from rest_framework import serializers
from apps.common.media_urls import signed_media_url

from .models import CoursewareAttachment, CoursewareTopic


class CoursewareAttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = CoursewareAttachment
        fields = ["id", "name", "file", "file_url", "created_at"]
        read_only_fields = ["id", "created_at", "file_url"]

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        return signed_media_url(request, obj.file)


class CoursewareTopicSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    attachments = CoursewareAttachmentSerializer(many=True, read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = CoursewareTopic
        fields = [
            "id", "subject", "subject_code", "subject_name",
            "batch", "batch_name",
            "name", "description", "image", "image_url", "is_published",
            "attachments", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "subject_code", "subject_name", "batch_name",
            "image_url", "attachments", "created_at", "updated_at",
        ]

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        return signed_media_url(request, obj.image)


class PublishTopicSerializer(serializers.Serializer):
    subject = serializers.IntegerField()
    batch = serializers.IntegerField()
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True,
                                        max_length=4000)
    image = serializers.ImageField(required=False, allow_null=True)
    attachments = serializers.ListField(
        child=serializers.FileField(),
        required=False, allow_empty=True,
    )
    attachment_names = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False, allow_empty=True,
    )

    def validate_attachments(self, files):
        # PDF / image / video only (client, 2026-11-26).
        from .files import validate_attachment
        for f in files:
            validate_attachment(f)
        return files
