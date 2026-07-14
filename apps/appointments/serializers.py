from rest_framework import serializers

from apps.employees.models import Employee

from .models import StudentAppointment


class StudentAppointmentSerializer(serializers.ModelSerializer):
    """Staff-side read serializer."""

    student_name = serializers.CharField(source="student.student_name",
                                         read_only=True)
    application_form_id = serializers.CharField(
        source="student.application_form_id", read_only=True,
    )
    team_label = serializers.CharField(source="get_team_display",
                                       read_only=True)
    faculty_name = serializers.CharField(source="faculty.full_name",
                                         read_only=True, default="")
    target_label = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source="get_status_display",
                                         read_only=True)
    decided_by_name = serializers.CharField(
        source="decided_by.username", read_only=True, default="",
    )

    class Meta:
        model = StudentAppointment
        fields = [
            "id", "student", "student_name", "application_form_id",
            "team", "team_label", "faculty", "faculty_name", "target_label",
            "reason",
            "preferred_date", "preferred_time",
            "status", "status_label",
            "scheduled_date", "scheduled_time", "venue",
            "staff_remarks",
            "decided_by", "decided_by_name", "decided_at",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class RequestAppointmentSerializer(serializers.Serializer):
    team = serializers.ChoiceField(
        choices=StudentAppointment.Team.choices,
        required=False, allow_blank=True,
    )
    faculty = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.filter(status=Employee.Status.ACTIVE),
        required=False, allow_null=True,
    )
    reason = serializers.CharField(min_length=5, max_length=2000)
    preferred_date = serializers.DateField()
    preferred_time = serializers.TimeField()

    def validate(self, attrs):
        has_team = bool(attrs.get("team"))
        has_faculty = attrs.get("faculty") is not None
        if has_team == has_faculty:
            raise serializers.ValidationError(
                "Pick either a team or a faculty member, not both."
            )
        return attrs


class DecideAppointmentSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[("CONFIRMED", "Confirmed"), ("DECLINED", "Declined")],
    )
    scheduled_date = serializers.DateField(required=False, allow_null=True)
    scheduled_time = serializers.TimeField(required=False, allow_null=True)
    venue = serializers.CharField(required=False, allow_blank=True,
                                  max_length=200)
    remarks = serializers.CharField(required=False, allow_blank=True,
                                    max_length=2000)
