from rest_framework import serializers

from .models import ScheduleSlot


class ScheduleSlotSerializer(serializers.ModelSerializer):
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    instructor_name = serializers.CharField(source="instructor.full_name", read_only=True)
    instructor_code = serializers.CharField(source="instructor.emp_code", read_only=True)
    classroom_name = serializers.CharField(source="classroom.name", read_only=True, default="")
    time_slot_label = serializers.CharField(source="time_slot.label", read_only=True)
    start_time = serializers.TimeField(source="time_slot.start_time", read_only=True)
    end_time = serializers.TimeField(source="time_slot.end_time", read_only=True)
    campus_id = serializers.IntegerField(source="batch.campus_id", read_only=True)

    class Meta:
        model = ScheduleSlot
        fields = [
            "id",
            "batch", "batch_name",
            "subject", "subject_name", "subject_code",
            "instructor", "instructor_name", "instructor_code",
            "classroom", "classroom_name",
            "time_slot", "time_slot_label", "start_time", "end_time",
            "date", "status", "notes",
            "classroom_conflict_overridden",
            "campus_id",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "batch_name", "subject_name", "subject_code",
            "instructor_name", "instructor_code", "classroom_name",
            "time_slot_label", "start_time", "end_time", "campus_id",
            "classroom_conflict_overridden",
            "created_by", "created_at", "updated_at",
        ]
        # Disable auto-detected UniqueTogetherValidators — the service
        # layer enforces conflicts and returns a structured 409.
        validators = []


class BulkWeeklyPublishSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    batch = serializers.IntegerField()
    subject = serializers.IntegerField()
    instructor = serializers.IntegerField()
    classroom = serializers.IntegerField(required=False, allow_null=True)
    time_slot = serializers.IntegerField()
    force = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError(
                {"end_date": "Must be on or after start_date."}
            )
        return attrs
