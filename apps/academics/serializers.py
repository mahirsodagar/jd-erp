from rest_framework import serializers

from .models import Attendance, ScheduleSlot


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


# --- G.2 — Attendance --------------------------------------------------

class AttendanceSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.student_name", read_only=True)
    application_form_id = serializers.CharField(
        source="student.application_form_id", read_only=True,
    )
    marked_by_name = serializers.CharField(
        source="marked_by.username", read_only=True, default="",
    )

    class Meta:
        model = Attendance
        fields = [
            "id", "schedule_slot", "student",
            "student_name", "application_form_id",
            "status", "note",
            "marked_by", "marked_by_name", "marked_at", "created_at",
        ]
        read_only_fields = [
            "id", "student_name", "application_form_id",
            "marked_by", "marked_by_name", "marked_at", "created_at",
        ]


class AttendanceMarkItemSerializer(serializers.Serializer):
    student = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Attendance.Status.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200)


class BulkMarkAttendanceSerializer(serializers.Serializer):
    marks = AttendanceMarkItemSerializer(many=True)
    notify_absent = serializers.BooleanField(
        required=False, default=False,
        help_text="Queue notifications for absent students after marking.",
    )


class FreezeSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=200)


class RosterEntrySerializer(serializers.Serializer):
    """One row per student in the slot's batch — current attendance
    status if marked, else None."""
    student_id = serializers.IntegerField()
    application_form_id = serializers.CharField()
    name = serializers.CharField()
    status = serializers.CharField(allow_null=True)
    note = serializers.CharField(allow_blank=True)
    attendance_id = serializers.IntegerField(allow_null=True)
