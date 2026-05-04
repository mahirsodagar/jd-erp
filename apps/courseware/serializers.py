from rest_framework import serializers

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
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url


class CoursewareTopicSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    attachments = CoursewareAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = CoursewareTopic
        fields = [
            "id", "subject", "subject_code", "subject_name",
            "batch", "batch_name",
            "name", "description", "is_published",
            "attachments", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "subject_code", "subject_name", "batch_name",
            "attachments", "created_at", "updated_at",
        ]


class PublishTopicSerializer(serializers.Serializer):
    subject = serializers.IntegerField()
    batch = serializers.IntegerField()
    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True,
                                        max_length=4000)
    attachments = serializers.ListField(
        child=serializers.FileField(),
        required=False, allow_empty=True,
    )
    attachment_names = serializers.ListField(
        child=serializers.CharField(max_length=200),
        required=False, allow_empty=True,
    )
