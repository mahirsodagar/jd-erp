from rest_framework import serializers

from .models import RelievingApplication, RelievingApproval


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
            "id", "application", "level",
            "approver", "approver_code", "approver_name",
            "status", "decided_at",
            "decided_by", "decided_by_name", "remarks",
            "created_at",
        ]
        read_only_fields = fields


class RelievingApplicationSerializer(serializers.ModelSerializer):
    employee_code = serializers.CharField(source="employee.emp_code", read_only=True)
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
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
            "reason",
            "last_working_date_requested",
            "last_working_date_approved",
            "status",
            "rejected_at_level", "rejection_reason",
            "relieving_letter_no", "experience_letter_no",
            "finalized_at",
            "finalized_by", "finalized_by_name",
            "submitted_by", "submitted_by_name", "submitted_at",
            "updated_at",
            "approvals",
        ]
        read_only_fields = [
            "id", "employee_code", "employee_name",
            "last_working_date_approved",
            "status",
            "rejected_at_level", "rejection_reason",
            "relieving_letter_no", "experience_letter_no",
            "finalized_at",
            "finalized_by", "finalized_by_name",
            "submitted_by", "submitted_by_name", "submitted_at",
            "updated_at",
            "approvals",
        ]


class SubmitRelievingSerializer(serializers.Serializer):
    employee = serializers.IntegerField()
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
