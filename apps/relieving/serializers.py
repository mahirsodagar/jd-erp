from rest_framework import serializers

from .models import RelievingApplication, RelievingApproval, RelievingManager


class RelievingManagerSerializer(serializers.ModelSerializer):
    institute_code = serializers.CharField(source="institute.code", read_only=True)
    institute_name = serializers.CharField(source="institute.name", read_only=True)
    approver_code = serializers.CharField(
        source="approver.emp_code", read_only=True, default="",
    )
    approver_name = serializers.CharField(
        source="approver.full_name", read_only=True, default="",
    )
    approver_email = serializers.CharField(
        source="approver.email_primary", read_only=True, default="",
    )
    approver_active = serializers.SerializerMethodField()

    class Meta:
        model = RelievingManager
        fields = [
            "id", "institute", "institute_code", "institute_name",
            "level", "label",
            "approver", "approver_code", "approver_name", "approver_email",
            "approver_active", "updated_at",
        ]
        read_only_fields = fields

    def get_approver_active(self, obj) -> bool:
        return bool(obj.approver and obj.approver.status == 0)


class RelievingManagerLevelInput(serializers.Serializer):
    level = serializers.ChoiceField(choices=[(l, f"L{l}") for l in RelievingManager.LEVELS])
    approver = serializers.IntegerField(allow_null=True)
    label = serializers.CharField(required=False, allow_blank=True, max_length=60)


class SaveRelievingManagersSerializer(serializers.Serializer):
    levels = RelievingManagerLevelInput(many=True)

    def validate_levels(self, value):
        seen = set()
        for item in value:
            if item["level"] in seen:
                raise serializers.ValidationError(
                    f"Level {item['level']} given more than once."
                )
            seen.add(item["level"])
        if not value:
            raise serializers.ValidationError("No levels given.")
        return value


class RelievingApprovalSerializer(serializers.ModelSerializer):
    approver_code = serializers.CharField(
        source="approver.emp_code", read_only=True, default="",
    )
    approver_name = serializers.CharField(
        source="approver.full_name", read_only=True, default="",
    )
    decided_by_name = serializers.CharField(
        source="decided_by.username", read_only=True, default="",
    )

    class Meta:
        model = RelievingApproval
        fields = [
            "id", "application", "level", "label",
            "approver", "approver_code", "approver_name",
            "status", "decided_at",
            "decided_by", "decided_by_name", "remarks",
            "created_at",
        ]
        read_only_fields = fields


class RelievingApplicationSerializer(serializers.ModelSerializer):
    employee_code = serializers.CharField(source="employee.emp_code", read_only=True)
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    institute = serializers.IntegerField(source="employee.institute_id", read_only=True)
    institute_code = serializers.CharField(
        source="employee.institute.code", read_only=True,
    )
    application_type_label = serializers.CharField(
        source="get_application_type_display", read_only=True,
    )
    submitted_by_name = serializers.CharField(
        source="submitted_by.username", read_only=True, default="",
    )
    finalized_by_name = serializers.CharField(
        source="finalized_by.username", read_only=True, default="",
    )
    approvals = RelievingApprovalSerializer(many=True, read_only=True)

    class Meta:
        model = RelievingApplication
        fields = [
            "id",
            "employee", "employee_code", "employee_name",
            "institute", "institute_code",
            "application_type", "application_type_label",
            "reason",
            "last_working_date_requested",
            "last_working_date_approved",
            "status",
            "rejected_at_level", "rejection_reason",
            "relieving_letter_no", "experience_letter_no",
            "experience_letter_sent_at",
            "finalized_at",
            "finalized_by", "finalized_by_name",
            "submitted_by", "submitted_by_name", "submitted_at",
            "updated_at",
            "approvals",
        ]
        read_only_fields = fields


class SubmitRelievingSerializer(serializers.Serializer):
    employee = serializers.IntegerField()
    application_type = serializers.ChoiceField(
        choices=RelievingApplication.Type.choices,
        default=RelievingApplication.Type.RELIEVING,
    )
    reason = serializers.CharField(min_length=10, max_length=4000)
    last_working_date_requested = serializers.DateField()


class DecideSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[("APPROVED", "Approved"),
                                                ("REJECTED", "Rejected")])
    remarks = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class FinalizeSerializer(serializers.Serializer):
    last_working_date_approved = serializers.DateField()
    set_inactive = serializers.BooleanField(default=True)


class WithdrawSerializer(serializers.Serializer):
    remarks = serializers.CharField(required=False, allow_blank=True, max_length=400)
