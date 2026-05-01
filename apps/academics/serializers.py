from rest_framework import serializers

from .models import (
    AlumniRecord, Assignment, AssignmentSubmission, Attendance, Certificate,
    MarksEntry, ScheduleSlot,
)


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


# === G.3 — Assignments + Marks ======================================

class AssignmentSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    submission_count = serializers.SerializerMethodField()
    graded_count = serializers.SerializerMethodField()

    class Meta:
        model = Assignment
        fields = [
            "id", "subject", "subject_name", "subject_code",
            "batch", "batch_name",
            "title", "description", "max_marks",
            "due_date", "attachment", "is_published",
            "submission_count", "graded_count",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "subject_name", "subject_code", "batch_name",
            "submission_count", "graded_count",
            "created_by", "created_at", "updated_at",
        ]

    def get_submission_count(self, obj):
        return obj.submissions.count()

    def get_graded_count(self, obj):
        return obj.submissions.filter(
            status=AssignmentSubmission.Status.GRADED
        ).count()


class AssignmentSubmissionSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.student_name", read_only=True)
    application_form_id = serializers.CharField(
        source="student.application_form_id", read_only=True,
    )
    assignment_title = serializers.CharField(source="assignment.title", read_only=True)
    assignment_due = serializers.DateTimeField(source="assignment.due_date", read_only=True)
    max_marks = serializers.DecimalField(
        source="assignment.max_marks", max_digits=5, decimal_places=1,
        read_only=True,
    )
    graded_by_name = serializers.CharField(
        source="graded_by.username", read_only=True, default="",
    )

    class Meta:
        model = AssignmentSubmission
        fields = [
            "id", "assignment", "assignment_title", "assignment_due", "max_marks",
            "student", "student_name", "application_form_id",
            "file", "text_response",
            "submitted_at", "extended_due_date",
            "status", "grade", "feedback",
            "graded_by", "graded_by_name", "graded_at",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "assignment_title", "assignment_due", "max_marks",
            "student_name", "application_form_id",
            "status", "graded_by", "graded_by_name", "graded_at",
            "created_at", "updated_at",
        ]


class SubmissionGradeSerializer(serializers.Serializer):
    grade = serializers.DecimalField(max_digits=5, decimal_places=1)
    feedback = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class MarksEntrySerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.student_name", read_only=True)
    application_form_id = serializers.CharField(
        source="student.application_form_id", read_only=True,
    )
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    semester_number = serializers.IntegerField(source="semester.number", read_only=True)
    semester_name = serializers.CharField(source="semester.name", read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    total_marks = serializers.FloatField(read_only=True)
    total_max = serializers.FloatField(read_only=True)
    percentage = serializers.FloatField(read_only=True)
    published_by_name = serializers.CharField(
        source="published_by.username", read_only=True, default="",
    )

    class Meta:
        model = MarksEntry
        fields = [
            "id",
            "student", "student_name", "application_form_id",
            "subject", "subject_name", "subject_code",
            "batch", "batch_name",
            "semester", "semester_number", "semester_name",
            "ia_marks", "ia_max", "ea_marks", "ea_max",
            "total_marks", "total_max", "percentage",
            "published", "published_at",
            "published_by", "published_by_name",
            "entered_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "student_name", "application_form_id",
            "subject_name", "subject_code",
            "batch_name", "semester_number", "semester_name",
            "total_marks", "total_max", "percentage",
            "published", "published_at",
            "published_by", "published_by_name",
            "entered_by", "created_at", "updated_at",
        ]
        # Disable auto unique-validators — we let the model's
        # IntegrityError surface as 400 / 409 from the view.
        validators = []

    def validate(self, attrs):
        ia = attrs.get("ia_marks", getattr(self.instance, "ia_marks", None))
        ia_max = attrs.get("ia_max", getattr(self.instance, "ia_max", 0))
        ea = attrs.get("ea_marks", getattr(self.instance, "ea_marks", None))
        ea_max = attrs.get("ea_max", getattr(self.instance, "ea_max", 0))
        if ia is not None and ia_max is not None and float(ia) > float(ia_max):
            raise serializers.ValidationError(
                {"ia_marks": f"IA {ia} exceeds max {ia_max}."}
            )
        if ea is not None and ea_max is not None and float(ea) > float(ea_max):
            raise serializers.ValidationError(
                {"ea_marks": f"EA {ea} exceeds max {ea_max}."}
            )
        return attrs


class StudentSubmitSerializer(serializers.Serializer):
    file = serializers.FileField(required=False, allow_null=True)
    text_response = serializers.CharField(required=False, allow_blank=True)


# === G.5 — Certificates + Alumni ====================================

class CertificateSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.student_name", read_only=True)
    application_form_id = serializers.CharField(
        source="student.application_form_id", read_only=True,
    )
    program_name = serializers.CharField(
        source="enrollment.program.name", read_only=True, default="",
    )
    batch_name = serializers.CharField(
        source="enrollment.batch.name", read_only=True, default="",
    )
    requested_by_name = serializers.CharField(
        source="requested_by.username", read_only=True, default="",
    )
    issued_by_name = serializers.CharField(
        source="issued_by.username", read_only=True, default="",
    )

    class Meta:
        model = Certificate
        fields = [
            "id", "student", "student_name", "application_form_id",
            "enrollment", "program_name", "batch_name",
            "type", "status", "certificate_no",
            "purpose", "remarks", "snapshot",
            "requested_by", "requested_by_name", "requested_on",
            "issued_by", "issued_by_name", "issued_at",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "student_name", "application_form_id",
            "program_name", "batch_name",
            "status", "certificate_no", "snapshot",
            "requested_by", "requested_by_name", "requested_on",
            "issued_by", "issued_by_name", "issued_at",
            "created_at", "updated_at",
        ]


class CertificateRequestSerializer(serializers.Serializer):
    student = serializers.IntegerField()
    enrollment = serializers.IntegerField(required=False, allow_null=True)
    type = serializers.ChoiceField(choices=Certificate.Type.choices)
    purpose = serializers.CharField(required=False, allow_blank=True, max_length=200)
    remarks = serializers.CharField(required=False, allow_blank=True)


class CertificateIssueSerializer(serializers.Serializer):
    remarks = serializers.CharField(required=False, allow_blank=True)
    override_eligibility = serializers.BooleanField(default=False)


class CertificateRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=400)


class AlumniRecordSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.student_name", read_only=True)
    application_form_id = serializers.CharField(
        source="student.application_form_id", read_only=True,
    )
    program_name = serializers.CharField(source="final_program.name", read_only=True)
    batch_name = serializers.CharField(source="final_batch.name", read_only=True)

    class Meta:
        model = AlumniRecord
        fields = [
            "id", "student", "student_name", "application_form_id",
            "graduation_year",
            "final_program", "program_name",
            "final_batch", "batch_name",
            "final_percentage",
            "current_status", "workplace", "job_title",
            "linkedin_url", "last_known_email", "last_known_phone",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "student_name", "application_form_id",
            "program_name", "batch_name",
            "created_at", "updated_at",
        ]


class AlumniSelfUpdateSerializer(serializers.ModelSerializer):
    """What an alumnus can update on their own record."""

    class Meta:
        model = AlumniRecord
        fields = [
            "current_status", "workplace", "job_title",
            "linkedin_url", "last_known_email", "last_known_phone",
        ]
