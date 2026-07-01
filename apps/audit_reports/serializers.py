from django.utils.dateparse import parse_date, parse_datetime, parse_time
from rest_framework import serializers

from apps.roles.models import Role

from .models import (
    AdminDailyReport, AuditAnswer, AuditForm, AuditFormField, AuditSubmission,
    BatchMentorReport, ComplianceFlag, CourseEndReport,
    FacultyDailyReport, FacultySelfAppraisal, StudentFeedback,
)


class FacultyDailyReportSerializer(serializers.ModelSerializer):
    faculty_name = serializers.CharField(source="faculty.full_name", read_only=True)
    faculty_code = serializers.CharField(source="faculty.emp_code", read_only=True)

    class Meta:
        model = FacultyDailyReport
        fields = [
            "id", "faculty", "faculty_name", "faculty_code", "date",
            "academic_description", "academic_hours",
            "non_academic_description", "non_academic_hours",
            "others_description", "others_hours",
            "submitted_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "faculty_name", "faculty_code",
            "submitted_by", "created_at", "updated_at",
        ]


class AdminDailyReportSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = AdminDailyReport
        fields = ["id", "rep_date", "user", "user_name",
                  "slot1", "slot2", "created_at", "updated_at"]
        read_only_fields = ["id", "user_name", "created_at", "updated_at"]


class CourseEndReportSerializer(serializers.ModelSerializer):
    instructor_name = serializers.CharField(source="instructor.full_name", read_only=True)
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True)

    class Meta:
        model = CourseEndReport
        fields = [
            "id",
            "instructor", "instructor_name",
            "subject", "subject_code",
            "batch", "batch_name",
            "completed_on",
            "summary", "learning_outcomes", "challenges", "suggestions",
            "avg_attendance_pct", "avg_marks_pct",
            "hod_status", "hod_remarks", "hod_reviewed_at", "hod_reviewed_by",
            "submitted_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "instructor_name", "subject_code", "batch_name",
            "hod_status", "hod_remarks", "hod_reviewed_at", "hod_reviewed_by",
            "submitted_by", "created_at", "updated_at",
        ]


class CourseEndReviewSerializer(serializers.Serializer):
    hod_status = serializers.ChoiceField(
        choices=[("APPROVED", "Approved"), ("RETURNED", "Returned")],
    )
    hod_remarks = serializers.CharField(required=False, allow_blank=True)


class BatchMentorReportSerializer(serializers.ModelSerializer):
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    mentor_name = serializers.CharField(source="mentor.full_name", read_only=True)

    class Meta:
        model = BatchMentorReport
        fields = [
            "id",
            "batch", "batch_name",
            "mentor", "mentor_name",
            "year", "month",
            "avg_attendance_pct", "avg_marks_pct",
            "behavioural_notes", "academic_concerns", "dropout_risks",
            "initiatives", "additional_remarks",
            "submitted_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "batch_name", "mentor_name",
            "submitted_by", "created_at", "updated_at",
        ]


class StudentFeedbackSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.student_name", read_only=True)
    instructor_name = serializers.CharField(source="instructor.full_name", read_only=True)
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True)

    class Meta:
        model = StudentFeedback
        fields = [
            "id",
            "student", "student_name",
            "subject", "subject_code",
            "instructor", "instructor_name",
            "batch", "batch_name",
            "type",
            "rating_overall", "rating_clarity", "rating_engagement",
            "rating_responsiveness",
            "what_worked", "suggestions",
            "created_at",
        ]
        read_only_fields = [
            "id", "student_name", "instructor_name", "subject_code",
            "batch_name", "created_at",
        ]


class FacultySelfAppraisalSerializer(serializers.ModelSerializer):
    faculty_name = serializers.CharField(source="faculty.full_name", read_only=True)

    class Meta:
        model = FacultySelfAppraisal
        fields = [
            "id",
            "faculty", "faculty_name",
            "year", "quarter",
            "achievements", "challenges", "plans",
            "green_flags", "red_flags",
            "auditor_remarks", "auditor_reviewed_at", "auditor_reviewed_by",
            "submitted_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "faculty_name",
            "auditor_remarks", "auditor_reviewed_at", "auditor_reviewed_by",
            "submitted_by", "created_at", "updated_at",
        ]


class SelfAppraisalReviewSerializer(serializers.Serializer):
    auditor_remarks = serializers.CharField(allow_blank=True, max_length=2000)


class ComplianceFlagSerializer(serializers.ModelSerializer):
    raised_by_name = serializers.CharField(
        source="raised_by.username", read_only=True, default="",
    )
    resolved_by_name = serializers.CharField(
        source="resolved_by.username", read_only=True, default="",
    )

    class Meta:
        model = ComplianceFlag
        fields = [
            "id",
            "target_faculty", "target_batch", "target_student",
            "target_description",
            "category", "severity", "description",
            "resolved_at", "resolved_by", "resolved_by_name",
            "resolution_remarks",
            "raised_by", "raised_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id",
            "resolved_at", "resolved_by", "resolved_by_name",
            "raised_by", "raised_by_name",
            "created_at", "updated_at",
        ]


class ResolveFlagSerializer(serializers.Serializer):
    resolution_remarks = serializers.CharField(min_length=3, max_length=2000)


# === Dynamic audit form builder =====================================

class AuditFormFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditFormField
        fields = [
            "id", "label", "field_type", "options", "required",
            "help_text", "config", "sort_order",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        ftype = attrs.get("field_type")
        options = attrs.get("options") or []
        choice_types = (
            AuditFormField.SINGLE_CHOICE_TYPES
            | AuditFormField.MULTI_CHOICE_TYPES
        )
        if ftype in choice_types and not options:
            raise serializers.ValidationError(
                {"options": f"{ftype} fields need at least one option."}
            )
        return attrs


class AuditFormRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name"]
        read_only_fields = fields


class AuditFormSerializer(serializers.ModelSerializer):
    fields = AuditFormFieldSerializer(many=True)
    field_count = serializers.IntegerField(
        source="fields.count", read_only=True,
    )
    roles = AuditFormRoleSerializer(many=True, read_only=True)
    role_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Role.objects.all(),
        source="roles", write_only=True, required=False,
    )
    created_by_name = serializers.CharField(
        source="created_by.full_name", read_only=True, default="",
    )

    class Meta:
        model = AuditForm
        fields = [
            "id", "title", "description", "status",
            "roles", "role_ids",
            "fields", "field_count",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "field_count", "roles",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        # A published form must target at least one role, otherwise no
        # regular user could ever see it. On PATCH, fall back to the
        # form's existing roles when role_ids isn't supplied.
        status = attrs.get("status", getattr(self.instance, "status", None))
        if "roles" in attrs:
            roles = attrs["roles"]
        elif self.instance is not None:
            roles = list(self.instance.roles.all())
        else:
            roles = []
        if status == AuditForm.Status.PUBLISHED and not roles:
            raise serializers.ValidationError(
                {"role_ids": "Select at least one role before publishing."}
            )
        return attrs

    def _write_fields(self, form, fields_data):
        form.fields.all().delete()
        AuditFormField.objects.bulk_create([
            AuditFormField(form=form, **fd) for fd in fields_data
        ])

    def create(self, validated_data):
        fields_data = validated_data.pop("fields", [])
        roles = validated_data.pop("roles", None)
        form = AuditForm.objects.create(**validated_data)
        if roles is not None:
            form.roles.set(roles)
        self._write_fields(form, fields_data)
        return form

    def update(self, instance, validated_data):
        fields_data = validated_data.pop("fields", None)
        roles = validated_data.pop("roles", None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if roles is not None:
            instance.roles.set(roles)
        if fields_data is not None:
            self._write_fields(instance, fields_data)
        return instance


class AuditAnswerSerializer(serializers.ModelSerializer):
    field_label = serializers.CharField(source="field.label", read_only=True)
    field_type = serializers.CharField(source="field.field_type", read_only=True)

    class Meta:
        model = AuditAnswer
        fields = ["id", "field", "field_label", "field_type", "value"]
        read_only_fields = fields


class AuditSubmissionSerializer(serializers.ModelSerializer):
    form_title = serializers.CharField(source="form.title", read_only=True)
    submitted_by_name = serializers.CharField(
        source="submitted_by.full_name", read_only=True, default="",
    )
    answers = AuditAnswerSerializer(many=True, read_only=True)

    class Meta:
        model = AuditSubmission
        fields = [
            "id", "form", "form_title",
            "submitted_by", "submitted_by_name",
            "created_at", "answers",
        ]
        read_only_fields = fields


class SubmitAnswerSerializer(serializers.Serializer):
    field = serializers.IntegerField()
    value = serializers.JSONField(required=False, allow_null=True)


class SubmitAuditFormSerializer(serializers.Serializer):
    """Validates a fill against the form's field definitions. Pass the
    AuditForm in the serializer context as `form`."""

    answers = SubmitAnswerSerializer(many=True)

    def validate(self, attrs):
        form = self.context["form"]
        fields = {f.id: f for f in form.fields.all()}
        by_field = {}
        for ans in attrs["answers"]:
            fid = ans["field"]
            if fid not in fields:
                raise serializers.ValidationError(
                    f"Field {fid} does not belong to this form."
                )
            by_field[fid] = self._clean_value(fields[fid], ans.get("value"))

        # Required-field enforcement.
        for fid, field in fields.items():
            if field.required and self._is_empty(by_field.get(fid)):
                raise serializers.ValidationError(
                    {str(fid): f"'{field.label}' is required."}
                )
        attrs["cleaned"] = by_field
        return attrs

    @staticmethod
    def _is_empty(value):
        return value is None or value == "" or value == []

    def _clean_value(self, field, value):
        ftype = field.field_type
        if self._is_empty(value):
            return None
        if ftype in AuditFormField.SINGLE_CHOICE_TYPES:
            if value not in field.options:
                raise serializers.ValidationError(
                    {field.label: f"'{value}' is not a valid option."}
                )
            return value
        if ftype in AuditFormField.MULTI_CHOICE_TYPES:
            if not isinstance(value, list):
                raise serializers.ValidationError(
                    {field.label: "Expected a list of options."}
                )
            bad = [v for v in value if v not in field.options]
            if bad:
                raise serializers.ValidationError(
                    {field.label: f"Invalid option(s): {bad}."}
                )
            return value
        if ftype == "RATING":
            try:
                n = int(value)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {field.label: "Rating must be a number."}
                )
            max_rating = int(field.config.get("max_rating", 5))
            if not (1 <= n <= max_rating):
                raise serializers.ValidationError(
                    {field.label: f"Rating must be 1–{max_rating}."}
                )
            return n
        if ftype in ("DATE", "TIME", "DATETIME"):
            parser = {
                "DATE": parse_date, "TIME": parse_time,
                "DATETIME": parse_datetime,
            }[ftype]
            if not isinstance(value, str) or parser(value) is None:
                raise serializers.ValidationError(
                    {field.label: f"Invalid {ftype.lower()} value."}
                )
            return value
        # TEXT / TEXTAREA
        return str(value)
