from datetime import date as _date
from decimal import Decimal

from rest_framework import serializers

from apps.employees.models import Employee

from .models import (
    CompOffApplication, EmailDispatchLog, Holiday,
    LeaveAllocation, LeaveApplication, LeaveType, Session,
)


# --- Master ------------------------------------------------------------

class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = ["id", "code", "name", "category",
                  "half_day_allowed", "is_active",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = ["id", "code", "start_date", "end_date", "is_current"]
        read_only_fields = ["id"]


class HolidaySerializer(serializers.ModelSerializer):
    campus_name = serializers.CharField(source="campus.name", read_only=True, default="")

    class Meta:
        model = Holiday
        fields = ["id", "date", "name", "campus", "campus_name", "is_optional"]
        read_only_fields = ["id", "campus_name"]


# --- Allocations -------------------------------------------------------

class LeaveAllocationSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    leave_type_code = serializers.CharField(source="leave_type.code", read_only=True)
    session_code = serializers.CharField(source="session.code", read_only=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = LeaveAllocation
        fields = [
            "id", "employee", "employee_name",
            "session", "session_code",
            "leave_type", "leave_type_code",
            "count", "start_date", "end_date",
            "created_by", "created_by_name", "created_on",
        ]
        read_only_fields = [
            "id", "employee_name", "session_code", "leave_type_code",
            "created_by", "created_by_name", "created_on",
        ]

    def validate(self, attrs):
        lt = attrs.get("leave_type") or getattr(self.instance, "leave_type", None)
        if lt and lt.category != LeaveType.Category.LEAVE:
            raise serializers.ValidationError(
                {"leave_type": "Only LEAVE-category types can be allocated."}
            )
        if attrs.get("end_date") and attrs.get("start_date"):
            if attrs["end_date"] < attrs["start_date"]:
                raise serializers.ValidationError(
                    {"end_date": "Must be on/after start_date."}
                )
        return attrs


class BulkAllocationSerializer(serializers.Serializer):
    session = serializers.PrimaryKeyRelatedField(queryset=Session.objects.all())
    leave_type = serializers.PrimaryKeyRelatedField(queryset=LeaveType.objects.all())
    count = serializers.DecimalField(max_digits=5, decimal_places=1)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    employee_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False,
    )
    skip_existing = serializers.BooleanField(default=True)

    def validate(self, attrs):
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError(
                {"end_date": "Must be on/after start_date."}
            )
        if attrs["leave_type"].category != LeaveType.Category.LEAVE:
            raise serializers.ValidationError(
                {"leave_type": "Only LEAVE-category types can be allocated."}
            )
        return attrs


# --- Leave applications ------------------------------------------------

class LeaveApplicationSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_code = serializers.CharField(source="employee.emp_code", read_only=True)
    leave_type_code = serializers.CharField(source="leave_type.code", read_only=True)
    leave_type_name = serializers.CharField(source="leave_type.name", read_only=True)
    leave_type_category = serializers.CharField(source="leave_type.category", read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.full_name",
                                             read_only=True, default="")

    class Meta:
        model = LeaveApplication
        fields = [
            "id", "employee", "employee_name", "employee_code",
            "leave_type", "leave_type_code", "leave_type_name", "leave_type_category",
            "from_date", "to_date", "from_session", "count",
            "reason", "manager_email", "cc_emails",
            "status", "approver_remarks",
            "approved_by", "approved_by_name",
            "applied_on", "decided_on",
        ]
        read_only_fields = [
            "id", "count", "status", "approver_remarks", "approved_by", "approved_by_name",
            "applied_on", "decided_on",
            "employee_name", "employee_code",
            "leave_type_code", "leave_type_name", "leave_type_category",
        ]


class LeaveApplyInputSerializer(serializers.Serializer):
    leave_type = serializers.PrimaryKeyRelatedField(queryset=LeaveType.objects.all())
    from_date = serializers.DateField()
    to_date = serializers.DateField()
    from_session = serializers.IntegerField(min_value=1, max_value=4)
    reason = serializers.CharField(min_length=3, max_length=2000)
    manager_email = serializers.EmailField(required=False, allow_blank=True)
    cc_emails = serializers.CharField(required=False, allow_blank=True, max_length=255)
    force = serializers.BooleanField(required=False, default=False)
    backdate = serializers.BooleanField(required=False, default=False)
    employee = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(), required=False,
        help_text="HR-only: apply on behalf of another employee.",
    )

    def validate(self, attrs):
        if attrs["to_date"] < attrs["from_date"]:
            raise serializers.ValidationError(
                {"to_date": "Must be on/after from_date."}
            )
        lt = attrs["leave_type"]
        if lt.code == "PERMISSION" and attrs["from_session"] not in (3, 4):
            raise serializers.ValidationError(
                {"from_session": "Permission leaves use sessions 3 or 4 only."}
            )
        if lt.code == "SATURDAY_OFF" and attrs["from_session"] != 2:
            raise serializers.ValidationError(
                {"from_session": "Saturday Off must be a full day."}
            )
        return attrs


class DecisionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[(2, "Approved"), (3, "Rejected")])
    remarks = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class CancelOrWithdrawSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5, max_length=400)


# --- Comp-off ----------------------------------------------------------

class CompOffApplicationSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    approver_name = serializers.CharField(source="approver.full_name",
                                          read_only=True, default="")

    class Meta:
        model = CompOffApplication
        fields = [
            "id", "employee", "employee_name",
            "worked_date", "worked_session_1", "worked_session_2", "count",
            "reason", "status",
            "approver", "approver_name", "approver_remarks",
            "applied_on", "decided_on",
        ]
        read_only_fields = [
            "id", "count", "status", "approver", "approver_name",
            "approver_remarks", "applied_on", "decided_on",
            "employee_name",
        ]


class CompOffApplyInputSerializer(serializers.Serializer):
    worked_date = serializers.DateField()
    worked_session_1 = serializers.IntegerField(min_value=0, max_value=1)
    worked_session_2 = serializers.IntegerField(min_value=0, max_value=1)
    reason = serializers.CharField(min_length=3, max_length=2000)
    employee = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(), required=False,
    )

    def validate(self, attrs):
        s1, s2 = attrs["worked_session_1"], attrs["worked_session_2"]
        if (s1, s2) == (0, 0):
            raise serializers.ValidationError(
                {"worked_session_1": "At least one session must be 1."}
            )
        return attrs


# --- Email dispatch log ------------------------------------------------

class EmailDispatchLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailDispatchLog
        fields = [
            "id", "template", "to", "cc", "subject", "body",
            "status", "created_at", "sent_at", "error",
            "related_application", "related_compoff",
        ]
        read_only_fields = fields
