from datetime import date

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Department, Designation, Employee
from .services import PHOTO_MAX_BYTES, validate_photo

User = get_user_model()


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class DesignationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Designation
        fields = ["id", "name", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class EmployeeListSerializer(serializers.ModelSerializer):
    """Compact list payload — no addresses, no manager chain."""

    full_name = serializers.CharField(read_only=True)
    designation = serializers.CharField(source="designation.name", read_only=True)
    department = serializers.CharField(source="department.name", read_only=True)
    campus = serializers.CharField(source="campus.name", read_only=True)
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            "id", "emp_code", "full_name",
            "designation", "department", "campus",
            "email_primary", "mobile_primary",
            "photo_url", "status", "date_of_joining",
        ]
        read_only_fields = fields

    def get_photo_url(self, obj):
        request = self.context.get("request")
        if obj.photo and request:
            return request.build_absolute_uri(obj.photo.url)
        return None


class EmployeeDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    designation_name = serializers.CharField(source="designation.name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    institute_name = serializers.CharField(source="institute.name", read_only=True)

    photo_url = serializers.SerializerMethodField()
    qr_url = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            "id", "emp_code",
            "first_name", "middle_name", "family_name", "full_name",
            "dob", "nationality", "blood_group", "gender", "qualification",
            "employment_type", "date_of_appointment", "date_of_joining",
            "designation", "designation_name",
            "department", "department_name",
            "campus", "campus_name",
            "institute", "institute_name",
            "reporting_manager_1", "reporting_manager_2",
            "reporting_manager_3", "reporting_manager_4",
            "current_address", "current_city", "current_state",
            "permanent_address", "permanent_city", "permanent_state",
            "mobile_primary", "mobile_alternate",
            "email_primary", "email_alternate",
            "photo_url", "qr_url",
            "status", "is_deleted",
            "user_account",
            "created_by", "created_on", "updated_by", "updated_on",
        ]
        read_only_fields = fields

    def get_photo_url(self, obj):
        request = self.context.get("request")
        return request.build_absolute_uri(obj.photo.url) if obj.photo and request else None

    def get_qr_url(self, obj):
        request = self.context.get("request")
        return request.build_absolute_uri(obj.qr_code.url) if obj.qr_code and request else None


class _EmployeeWriteBase(serializers.ModelSerializer):
    """Shared validators for create/update."""

    photo = serializers.ImageField(required=False, allow_null=True,
                                   max_length=PHOTO_MAX_BYTES)

    def validate_photo(self, file):
        if file is None:
            return file
        try:
            validate_photo(file)
        except ValueError as e:
            raise serializers.ValidationError(str(e))
        return file

    def validate(self, attrs):
        dob = attrs.get("dob") or getattr(self.instance, "dob", None)
        doj = attrs.get("date_of_joining") or getattr(self.instance, "date_of_joining", None)
        doa = attrs.get("date_of_appointment") or getattr(self.instance, "date_of_appointment", None)

        if dob and dob >= date.today():
            raise serializers.ValidationError({"dob": "DOB must be in the past."})
        if dob and doj:
            age = (doj - dob).days // 365
            if age < 18:
                raise serializers.ValidationError(
                    {"dob": "Employee must be at least 18 years old at joining."}
                )
        if doa and doj and doj < doa:
            raise serializers.ValidationError(
                {"date_of_joining": "Cannot be earlier than date_of_appointment."}
            )

        # State/city consistency
        for prefix in ("current", "permanent"):
            city = attrs.get(f"{prefix}_city") or getattr(self.instance, f"{prefix}_city", None)
            state = attrs.get(f"{prefix}_state") or getattr(self.instance, f"{prefix}_state", None)
            if city and state and city.state_id != state.id:
                raise serializers.ValidationError(
                    {f"{prefix}_city": f"City does not belong to {state.name}."}
                )

        # Manager != self
        if self.instance:
            for f in ("reporting_manager_1", "reporting_manager_2",
                      "reporting_manager_3", "reporting_manager_4"):
                mgr = attrs.get(f)
                if mgr and mgr.id == self.instance.id:
                    raise serializers.ValidationError(
                        {f: "Reporting manager cannot be the employee themselves."}
                    )
        return attrs


class EmployeeCreateSerializer(_EmployeeWriteBase):
    class Meta:
        model = Employee
        fields = [
            "emp_code",
            "first_name", "middle_name", "family_name",
            "dob", "nationality", "blood_group", "gender", "qualification",
            "employment_type", "date_of_appointment", "date_of_joining",
            "designation", "department", "campus", "institute",
            "reporting_manager_1", "reporting_manager_2",
            "reporting_manager_3", "reporting_manager_4",
            "current_address", "current_city", "current_state",
            "permanent_address", "permanent_city", "permanent_state",
            "mobile_primary", "mobile_alternate",
            "email_primary", "email_alternate",
            "photo",
        ]
        extra_kwargs = {
            "emp_code": {"required": False, "allow_blank": True},
            # Model is nullable to allow a single top-level director with no
            # manager, but normal API creates must supply one.
            "reporting_manager_1": {"required": True, "allow_null": False},
        }


class EmployeeUpdateSerializer(_EmployeeWriteBase):
    """HR/admin update — `emp_code` is read-only after create."""

    class Meta:
        model = Employee
        fields = [
            "first_name", "middle_name", "family_name",
            "dob", "nationality", "blood_group", "gender", "qualification",
            "employment_type", "date_of_appointment", "date_of_joining",
            "designation", "department", "campus", "institute",
            "reporting_manager_1", "reporting_manager_2",
            "reporting_manager_3", "reporting_manager_4",
            "current_address", "current_city", "current_state",
            "permanent_address", "permanent_city", "permanent_state",
            "mobile_primary", "mobile_alternate",
            "email_primary", "email_alternate",
            "photo",
        ]


class EmployeeSelfUpdateSerializer(_EmployeeWriteBase):
    """Self-edit — strict allow-list per scope §3.4."""

    class Meta:
        model = Employee
        fields = [
            "mobile_alternate", "email_alternate",
            "permanent_address", "photo",
        ]


class StatusToggleSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5, max_length=400, required=False, allow_blank=True)


class PortalAccountSerializer(serializers.Serializer):
    username = serializers.CharField(min_length=3, max_length=64)
    role_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False,
    )
    send_credentials = serializers.BooleanField(required=False, default=False)
