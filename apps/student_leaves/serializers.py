from rest_framework import serializers

from .models import StudentLeaveApplication


class StudentLeaveApplicationSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.student_name",
                                         read_only=True)
    application_form_id = serializers.CharField(
        source="student.application_form_id", read_only=True,
    )
    decided_by_name = serializers.CharField(
        source="decided_by.username", read_only=True, default="",
    )
    days = serializers.IntegerField(read_only=True)

    class Meta:
        model = StudentLeaveApplication
        fields = [
            "id", "student", "student_name", "application_form_id",
            "leave_date", "leave_edate", "days",
            "student_remarks", "status",
            "batch_mentor_email", "module_mentor_email", "cc_emails",
            "approver_remarks",
            "decided_by", "decided_by_name", "decided_at",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "student", "student_name", "application_form_id",
            "days", "status",
            "approver_remarks",
            "decided_by", "decided_by_name", "decided_at",
            "created_at", "updated_at",
        ]


class ApplyStudentLeaveSerializer(serializers.Serializer):
    leave_date = serializers.DateField()
    leave_edate = serializers.DateField()
    student_remarks = serializers.CharField(min_length=5, max_length=2000)
    batch_mentor_email = serializers.EmailField()
    module_mentor_email = serializers.EmailField(required=False, allow_blank=True)
    cc_emails = serializers.ListField(
        child=serializers.EmailField(), required=False, allow_empty=True,
    )


class DecideStudentLeaveSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[("APPROVED", "Approved"),
                                                ("REJECTED", "Rejected")])
    remarks = serializers.CharField(required=False, allow_blank=True,
                                    max_length=2000)
