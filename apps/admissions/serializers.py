from django.core.exceptions import ValidationError as DjangoValidationError
from apps.common.media_urls import signed_media_url
from rest_framework import serializers

from apps.common.file_validation import (
    PHOTO_OR_PDF_MIMES, PILLOW_IMAGE_MIMES, SecureFileField, validate_file,
)

from .models import (
    BatchTransfer, Enrollment, Student, StudentDocument, StudentRemark,
    StudentStatusChange,
)


class StudentListSerializer(serializers.ModelSerializer):
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    program_name = serializers.CharField(source="program.name", read_only=True)
    academic_year_code = serializers.CharField(source="academic_year.code", read_only=True)
    # Annotated by StudentListView (legacy "Active" / "Dropout" badge).
    is_dropout = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = Student
        fields = [
            "id", "application_form_id", "registration_number",
            "student_name", "is_dropout",
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
    # Display names for the linkage ids on the detail page's Record card
    # (ids alone meant nothing to staff — client 2026-11-21).
    user_account_name = serializers.SerializerMethodField()
    lead_origin_name = serializers.CharField(
        source="lead_origin.name", read_only=True, default="",
    )
    portal_username = serializers.SerializerMethodField()
    portal_password = serializers.SerializerMethodField()
    is_dropout = serializers.SerializerMethodField()
    # Registration fee paid (or due) online at application time. Null
    # when the step doesn't apply to this student.
    registration_payment = serializers.SerializerMethodField()
    # The whole "Pay fees" page the applicant saw after submitting —
    # every row with its paid/due state. Null when there is none.
    applicant_fees = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id", "application_form_id", "registration_number",
            "student_name", "is_dropout", "father_name", "mother_name",
            "gender", "dob", "category", "study_medium",
            "nationality", "aadhaar_number", "blood_group",
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
            "user_account", "user_account_name",
            "parent_user_account", "lead_origin", "lead_origin_name",
            "portal_username", "portal_password",
            "application_fee_paid_at", "application_fee_amount",
            "application_fee_mode", "application_fee_ref",
            "application_fee_recorded_by_name",
            "registration_payment", "applicant_fees",
            "created_by", "created_on", "updated_by", "updated_on",
        ]
        read_only_fields = [
            "id", "application_form_id",
            "user_account", "user_account_name",
            "parent_user_account", "lead_origin", "lead_origin_name",
            "portal_username", "portal_password", "is_dropout",
            "registration_payment",
            "applicant_fees",
            "created_by", "created_on", "updated_by", "updated_on",
            "campus_name", "program_name", "course_name",
            "institute_name", "academic_year_code", "photo_url",
            "current_city_name", "current_state_name",
            "permanent_city_name", "permanent_state_name",
            "application_fee_paid_at", "application_fee_amount",
            "application_fee_mode", "application_fee_ref",
            "application_fee_recorded_by_name",
        ]

    # Personal, family and address fields. Withheld from staff who lack
    # `admissions.student.view_sensitive` — the student's own name,
    # mobile and email stay visible so the record is still identifiable.
    SENSITIVE_FIELDS = (
        "father_name", "mother_name",
        "gender", "dob", "category", "study_medium",
        "nationality", "aadhaar_number", "blood_group",
        "current_address", "current_city", "current_city_name",
        "current_state", "current_state_name", "current_pincode",
        "permanent_address", "permanent_city", "permanent_city_name",
        "permanent_state", "permanent_state_name", "permanent_pincode",
        "father_mobile", "mother_mobile",
        "father_email", "mother_email",
        "father_occupation", "mother_occupation",
    )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._can_view_sensitive(instance):
            for f in self.SENSITIVE_FIELDS:
                data.pop(f, None)
        return data

    def _can_view_sensitive(self, obj) -> bool:
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        # A student always sees their own record in full — the `me/`
        # panel and the self-fill form depend on it.
        if obj.user_account_id and obj.user_account_id == user.id:
            return True
        return user.roles.filter(
            permissions__key="admissions.student.view_sensitive",
        ).exists()

    def get_photo_url(self, obj):
        request = self.context.get("request")
        return signed_media_url(request, obj.photo)

    def get_is_dropout(self, obj):
        from .services import is_dropout
        return is_dropout(obj)

    def get_registration_payment(self, obj):
        from apps.payments.registration_fee import registration_payment_summary
        return registration_payment_summary(obj)

    def get_applicant_fees(self, obj):
        from apps.payments.applicant_fees import fee_page_for
        return fee_page_for(obj)

    def get_user_account_name(self, obj):
        if not obj.user_account_id:
            return ""
        u = obj.user_account
        return (u.full_name or "").strip() or u.username

    def get_portal_username(self, obj):
        # Only surface to staff — students shouldn't see their own row
        # carrying this. The cred-management UI is staff-only anyway.
        if not self._can_view_credentials(obj):
            return ""
        return getattr(obj.user_account, "username", "") if obj.user_account_id else ""

    def get_portal_password(self, obj):
        # Plain-text copy kept on the row; same staff-only gate as the
        # username.
        if not obj.user_account_id or not self._can_view_credentials(obj):
            return ""
        return obj.portal_password or ""

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
            permissions__key="admissions.student.send_credentials",
        ).exists()


def _validate_student_photo(file):
    """Shared by the self / HR student serializers: real image bytes
    Pillow can open, 5 MB cap (the ID card and transcript render it)."""
    if file is None:
        return file
    try:
        validate_file(
            file, allowed_mimes=PILLOW_IMAGE_MIMES,
            max_size_bytes=5 * 1024 * 1024, field="photo",
        )
    except DjangoValidationError as e:
        raise serializers.ValidationError(e.message_dict.get("photo", e.messages))
    return file


class StudentSelfUpdateSerializer(serializers.ModelSerializer):
    """Fields a student is allowed to edit on their own record.
    No FKs to academic placement (campus/program/year) — those are HR-set."""

    #: Printed on ID cards, certificates and transcripts: once the
    #: student is enrolled only HR may change them (2026-11-27).
    _IDENTITY_FIELDS = ("student_name", "dob", "aadhaar_number", "gender")

    def validate_photo(self, file):
        return _validate_student_photo(file)

    def validate(self, attrs):
        student = self.instance
        if student is not None and student.enrollments.exists():
            changed = [
                f for f in self._IDENTITY_FIELDS
                if f in attrs and attrs[f] != getattr(student, f)
            ]
            if changed:
                raise serializers.ValidationError({
                    f: "Locked after enrolment — ask the office to correct this."
                    for f in changed
                })
        return attrs

    class Meta:
        model = Student
        fields = [
            "student_name", "father_name", "mother_name",
            "gender", "dob", "category", "study_medium",
            "nationality", "aadhaar_number", "blood_group",
            "current_address", "current_city", "current_state", "current_pincode",
            "permanent_address", "permanent_city", "permanent_state", "permanent_pincode",
            "father_mobile", "mother_mobile",
            "father_email", "mother_email",
            "father_occupation", "mother_occupation",
            "photo",
        ]


class StudentHRUpdateSerializer(serializers.ModelSerializer):
    """Fields HR/Admissions can edit. application_form_id stays read-only."""

    def validate_photo(self, file):
        return _validate_student_photo(file)

    class Meta:
        model = Student
        fields = [
            "registration_number",
            "student_name", "father_name", "mother_name",
            "gender", "dob", "category", "study_medium",
            "nationality", "aadhaar_number", "blood_group",
            "institute", "campus", "program", "course", "academic_year",
            "current_address", "current_city", "current_state", "current_pincode",
            "permanent_address", "permanent_city", "permanent_state", "permanent_pincode",
            "student_mobile", "father_mobile", "mother_mobile",
            "student_email", "father_email", "mother_email", "institute_email",
            "father_occupation", "mother_occupation",
            "photo",
        ]


class StudentDocumentSerializer(serializers.ModelSerializer):
    # Magic-byte validated: certificates / marksheets are PDFs or photos
    # of them. HTML/SVG/executables renamed to .pdf are refused before
    # they reach storage (nginx serves /media/ publicly).
    file = SecureFileField(
        allowed_mimes=PHOTO_OR_PDF_MIMES, max_size_mb=10,
        required=False, allow_null=True,
    )

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

    #: Fixed once the enrollment exists (2026-11-27). Dropping out goes
    #: through the Drop Out action (`admissions.student.dropout`), moving
    #: campus through Transfer (`admissions.student.transfer`); a plain
    #: edit must not reach either.
    _LOCKED_ON_UPDATE = ("status", "student", "campus")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is not None:
            for name in self._LOCKED_ON_UPDATE:
                self.fields[name].read_only = True


class PromotionResultSerializer(serializers.Serializer):
    """Returned from the lead-promote endpoint."""
    student_id = serializers.IntegerField()
    application_form_id = serializers.CharField()
    user_id = serializers.IntegerField()
    username = serializers.CharField()
    temporary_password = serializers.CharField()
    note = serializers.CharField()


class StudentStatusChangeSerializer(serializers.ModelSerializer):
    action_label = serializers.CharField(
        source="get_action_display", read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default="",
    )

    class Meta:
        model = StudentStatusChange
        fields = [
            "id", "action", "action_label", "remarks", "enrollments",
            "created_by_name", "created_on",
        ]
        read_only_fields = fields


class StudentStatusChangeInputSerializer(serializers.Serializer):
    remarks = serializers.CharField(max_length=1000)



class BatchTransferSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.student_name", read_only=True)
    student_application_id = serializers.CharField(
        source="student.application_form_id", read_only=True,
    )
    from_batch_name = serializers.CharField(source="from_batch.name", read_only=True)
    from_program_name = serializers.CharField(source="from_program.name", read_only=True)
    from_campus_name = serializers.CharField(source="from_campus.name", read_only=True)
    from_semester_name = serializers.CharField(source="from_semester.name", read_only=True)
    from_academic_year_code = serializers.CharField(
        source="from_academic_year.code", read_only=True,
    )
    to_batch_name = serializers.CharField(source="to_batch.name", read_only=True)
    to_program_name = serializers.CharField(source="to_program.name", read_only=True)
    to_campus_name = serializers.CharField(source="to_campus.name", read_only=True)
    to_semester_name = serializers.CharField(source="to_semester.name", read_only=True)
    to_academic_year_code = serializers.CharField(
        source="to_academic_year.code", read_only=True,
    )
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default="",
    )

    class Meta:
        model = BatchTransfer
        fields = [
            "id", "student", "student_name", "student_application_id",
            "enrollment",
            "from_batch", "from_batch_name", "from_program", "from_program_name",
            "from_campus", "from_campus_name", "from_semester", "from_semester_name",
            "from_academic_year", "from_academic_year_code",
            "to_batch", "to_batch_name", "to_program", "to_program_name",
            "to_campus", "to_campus_name", "to_semester", "to_semester_name",
            "to_academic_year", "to_academic_year_code",
            "remarks", "created_by_name", "created_on",
        ]
        read_only_fields = fields
