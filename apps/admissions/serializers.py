from rest_framework import serializers

from .models import Enrollment, Student, StudentDocument, StudentRemark


class StudentListSerializer(serializers.ModelSerializer):
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    program_name = serializers.CharField(source="program.name", read_only=True)
    academic_year_code = serializers.CharField(source="academic_year.code", read_only=True)

    class Meta:
        model = Student
        fields = [
            "id", "application_form_id", "registration_number",
            "student_name",
            "campus", "campus_name",
            "program", "program_name",
            "academic_year", "academic_year_code",
            "student_mobile", "student_email",
            "created_on",
        ]
        read_only_fields = fields


class StudentDetailSerializer(serializers.ModelSerializer):
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    program_name = serializers.CharField(source="program.name", read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True, default="")
    institute_name = serializers.CharField(source="institute.name", read_only=True)
    academic_year_code = serializers.CharField(source="academic_year.code", read_only=True)
    current_city_name = serializers.CharField(source="current_city.name", read_only=True, default="")
    current_state_name = serializers.CharField(source="current_state.name", read_only=True, default="")
    permanent_city_name = serializers.CharField(source="permanent_city.name", read_only=True, default="")
    permanent_state_name = serializers.CharField(source="permanent_state.name", read_only=True, default="")
    # Snapshot of the application-fee record on the originating lead.
    # Read-only; the lead is the source of truth — see
    # `apps.leads.views.LeadMarkFeePaidView` for where it gets written.
    application_fee_paid_at = serializers.DateTimeField(
        source="lead_origin.application_fee_paid_at", read_only=True,
    )
    application_fee_amount = serializers.DecimalField(
        source="lead_origin.application_fee_amount",
        max_digits=10, decimal_places=2, read_only=True,
    )
    application_fee_mode = serializers.CharField(
        source="lead_origin.application_fee_mode", read_only=True, default="",
    )
    application_fee_ref = serializers.CharField(
        source="lead_origin.application_fee_ref", read_only=True, default="",
    )
    application_fee_recorded_by_name = serializers.CharField(
        source="lead_origin.application_fee_recorded_by.username",
        read_only=True, default="",
    )
    photo_url = serializers.SerializerMethodField()
    portal_username = serializers.SerializerMethodField()
    portal_temp_password = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id", "application_form_id", "registration_number",
            "student_name", "father_name", "mother_name",
            "gender", "dob", "category", "study_medium",
            "nationality", "blood_group",
            "institute", "institute_name",
            "campus", "campus_name",
            "program", "program_name",
            "course", "course_name",
            "academic_year", "academic_year_code",
            "current_address", "current_city", "current_city_name",
            "current_state", "current_state_name", "current_pincode",
            "permanent_address", "permanent_city", "permanent_city_name",
            "permanent_state", "permanent_state_name", "permanent_pincode",
            "student_mobile", "father_mobile", "mother_mobile",
            "student_email", "father_email", "mother_email", "institute_email",
            "father_occupation", "mother_occupation",
            "photo", "photo_url",
            "user_account", "parent_user_account", "lead_origin",
            "portal_username", "portal_temp_password",
            "application_fee_paid_at", "application_fee_amount",
            "application_fee_mode", "application_fee_ref",
            "application_fee_recorded_by_name",
            "created_by", "created_on", "updated_by", "updated_on",
        ]
        read_only_fields = [
            "id", "application_form_id",
            "user_account", "parent_user_account", "lead_origin",
            "portal_username", "portal_temp_password",
            "created_by", "created_on", "updated_by", "updated_on",
            "campus_name", "program_name", "course_name",
            "institute_name", "academic_year_code", "photo_url",
            "current_city_name", "current_state_name",
            "permanent_city_name", "permanent_state_name",
            "application_fee_paid_at", "application_fee_amount",
            "application_fee_mode", "application_fee_ref",
            "application_fee_recorded_by_name",
        ]

    def get_photo_url(self, obj):
        request = self.context.get("request")
        return request.build_absolute_uri(obj.photo.url) if obj.photo and request else None

    def get_portal_username(self, obj):
        # Only surface to staff — students shouldn't see their own row
        # carrying this. The cred-management UI is staff-only anyway.
        if not self._can_view_credentials(obj):
            return ""
        return getattr(obj.user_account, "username", "") if obj.user_account_id else ""

    def get_portal_temp_password(self, obj):
        if not self._can_view_credentials(obj):
            return ""
        return obj.portal_temp_password or ""

    def _can_view_credentials(self, obj) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        # Hide from the student herself; show to anyone who can edit
        # the student (HR / admissions staff).
        if obj.user_account_id and obj.user_account_id == user.id:
            return False
        return user.roles.filter(
            permissions__key="admissions.student.edit",
        ).exists()


class StudentSelfUpdateSerializer(serializers.ModelSerializer):
    """Fields a student is allowed to edit on their own record.
    No FKs to academic placement (campus/program/year) — those are HR-set."""

    class Meta:
        model = Student
        fields = [
            "student_name", "father_name", "mother_name",
            "gender", "dob", "category", "study_medium",
            "nationality", "blood_group",
            "current_address", "current_city", "current_state", "current_pincode",
            "permanent_address", "permanent_city", "permanent_state", "permanent_pincode",
            "father_mobile", "mother_mobile",
            "father_email", "mother_email",
            "father_occupation", "mother_occupation",
            "photo",
        ]


class StudentHRUpdateSerializer(serializers.ModelSerializer):
    """Fields HR/Admissions can edit. application_form_id stays read-only."""

    class Meta:
        model = Student
        fields = [
            "registration_number",
            "student_name", "father_name", "mother_name",
            "gender", "dob", "category", "study_medium",
            "nationality", "blood_group",
            "institute", "campus", "program", "course", "academic_year",
            "current_address", "current_city", "current_state", "current_pincode",
            "permanent_address", "permanent_city", "permanent_state", "permanent_pincode",
            "student_mobile", "father_mobile", "mother_mobile",
            "student_email", "father_email", "mother_email", "institute_email",
            "father_occupation", "mother_occupation",
            "photo",
        ]


class StudentDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentDocument
        fields = [
            "id", "student", "header",
            "regno_yearpassing", "school_college", "university_board",
            "certificate_no", "percent_obtained",
            "file", "uploaded_by", "uploaded_on",
        ]
        read_only_fields = ["id", "uploaded_by", "uploaded_on"]
        extra_kwargs = {
            # Views always inject the student via save(student=...) so
            # callers don't have to pass it in the body.
            "student": {"required": False},
        }


class StudentRemarkSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default="",
    )

    class Meta:
        model = StudentRemark
        fields = [
            "id", "student", "note", "created_by", "created_by_name",
            "created_on",
        ]
        read_only_fields = [
            "id", "student", "created_by", "created_by_name", "created_on",
        ]


class EnrollmentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.student_name", read_only=True)
    student_application_id = serializers.CharField(source="student.application_form_id", read_only=True)
    program_name = serializers.CharField(source="program.name", read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True, default="")
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    academic_year_code = serializers.CharField(source="academic_year.code", read_only=True)
    semester_name = serializers.CharField(source="semester.name", read_only=True)

    class Meta:
        model = Enrollment
        fields = [
            "id",
            "student", "student_name", "student_application_id",
            "program", "program_name",
            "course", "course_name",
            "semester", "semester_name",
            "campus", "campus_name",
            "batch", "batch_name",
            "academic_year", "academic_year_code",
            "status", "elective_subjects",
            "entry_date", "entry_user",
            "created_on", "updated_on",
        ]
        read_only_fields = [
            "id", "student_name", "student_application_id",
            "program_name", "course_name", "semester_name", "campus_name",
            "batch_name", "academic_year_code",
            "entry_user", "created_on", "updated_on",
        ]


class PromotionResultSerializer(serializers.Serializer):
    """Returned from the lead-promote endpoint."""
    student_id = serializers.IntegerField()
    application_form_id = serializers.CharField()
    user_id = serializers.IntegerField()
    username = serializers.CharField()
    temporary_password = serializers.CharField()
    note = serializers.CharField()
