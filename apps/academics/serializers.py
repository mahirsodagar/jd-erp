from rest_framework import serializers

from .models import (
    AlumniRecord, Assignment, AssignmentSubmission, Attendance, Certificate,
    Lesson, MarksEntry, ScheduleSlot,
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


class _GridCellSerializer(serializers.Serializer):
    """One cell in the weekly grid editor — a (weekday × time_slot)
    position assigned to a subject/instructor/classroom."""

    weekday = serializers.IntegerField(min_value=0, max_value=6)
    time_slot = serializers.IntegerField()
    subject = serializers.IntegerField()
    instructor = serializers.IntegerField()
    classroom = serializers.IntegerField(required=False, allow_null=True)


class WeeklyGridPublishSerializer(serializers.Serializer):
    """Payload for `POST /schedule/bulk-weekly-grid/` — the PHP-style
    "publish whole grid" action. The cells list holds all populated
    (weekday × time_slot) positions for the batch; the server expands
    each over the date range matching its weekday and inserts the
    resulting ScheduleSlot rows in one transaction."""

    batch = serializers.IntegerField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    force = serializers.BooleanField(required=False, default=False)
    cells = _GridCellSerializer(many=True)

    def validate(self, attrs):
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError(
                {"end_date": "Must be on or after start_date."}
            )
        if not attrs["cells"]:
            raise serializers.ValidationError(
                {"cells": "Provide at least one filled cell."}
            )
        # Reject duplicates within the submitted grid — two cells with
        # the same (weekday, time_slot) collide before we even hit the
        # DB conflict check.
        seen: set[tuple[int, int]] = set()
        for i, c in enumerate(attrs["cells"]):
            key = (c["weekday"], c["time_slot"])
            if key in seen:
                raise serializers.ValidationError(
                    {"cells": (
                        f"Duplicate cell at index {i}: weekday "
                        f"{c['weekday']} × time_slot {c['time_slot']} "
                        "already specified."
                    )}
                )
            seen.add(key)
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
    program_name = serializers.CharField(source="program.name", read_only=True,
                                         default="")
    batch_name = serializers.CharField(source="batch.name", read_only=True,
                                       default="")
    submission_count = serializers.SerializerMethodField()
    graded_count = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Assignment
        fields = [
            "id", "subject", "subject_name", "subject_code",
            "program", "program_name", "batch", "batch_name",
            "title", "description", "max_marks",
            "due_date", "attachment", "image", "image_url", "is_published",
            "submission_count", "graded_count",
            "created_by", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "subject_name", "subject_code", "program_name", "batch_name",
            "image_url",
            "submission_count", "graded_count",
            "created_by", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        # `program` is required; `batch` is optional. On a partial update
        # fall back to the instance's current values.
        program = attrs.get("program") or getattr(self.instance, "program", None)
        batch = attrs.get("batch")
        if batch is None and self.instance is not None and "batch" not in attrs:
            batch = self.instance.batch
        if program is None:
            raise serializers.ValidationError(
                {"program": "This field is required."}
            )
        # When a batch is chosen it must belong to the selected program —
        # otherwise the targeting is contradictory.
        if batch is not None and batch.program_id != program.id:
            raise serializers.ValidationError(
                {"batch": "Batch does not belong to the selected program."}
            )
        return attrs

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        return (request.build_absolute_uri(obj.image.url)
                if request else obj.image.url)

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


# === G.4 — Online Tests =============================================

from .models import Test, TestAttempt, TestQuestion, TestResponse  # noqa: E402


class TestQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestQuestion
        fields = ["id", "test", "description", "type", "options",
                  "answer_key", "marks", "sort_order"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        qtype = attrs.get("type") or getattr(self.instance, "type", "")
        opts = attrs.get("options") or getattr(self.instance, "options", [])
        key = attrs.get("answer_key") or getattr(self.instance, "answer_key", "")
        if qtype == TestQuestion.Type.MCQ:
            if not isinstance(opts, list) or len(opts) < 2:
                raise serializers.ValidationError(
                    {"options": "MCQ needs at least 2 options."}
                )
            if not key:
                raise serializers.ValidationError(
                    {"answer_key": "MCQ requires an answer_key (option index)."}
                )
            try:
                idx = int(key)
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    {"answer_key": "MCQ answer_key must be an option index."}
                )
            if idx < 0 or idx >= len(opts):
                raise serializers.ValidationError(
                    {"answer_key": f"Index out of range (have {len(opts)} options)."}
                )
        return attrs


class TestQuestionStudentSerializer(serializers.ModelSerializer):
    """Question shape exposed to students — no answer_key leaked."""
    class Meta:
        model = TestQuestion
        fields = ["id", "description", "type", "options", "marks", "sort_order"]
        read_only_fields = fields


class TestSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    question_count = serializers.SerializerMethodField()

    class Meta:
        model = Test
        fields = ["id", "name", "instructions", "duration_min",
                  "subject", "subject_name", "subject_code",
                  "program", "academic_year",
                  "status", "total_marks", "question_count",
                  "created_by", "created_at", "updated_at"]
        read_only_fields = ["id", "subject_name", "subject_code",
                            "status", "total_marks", "question_count",
                            "created_by", "created_at", "updated_at"]

    def get_question_count(self, obj):
        return obj.questions.count()


class TestAttemptSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.student_name", read_only=True)
    application_form_id = serializers.CharField(
        source="student.application_form_id", read_only=True,
    )
    test_name = serializers.CharField(source="test.name", read_only=True)
    duration_min = serializers.IntegerField(source="test.duration_min", read_only=True)
    total_marks = serializers.DecimalField(
        source="test.total_marks", max_digits=5, decimal_places=1, read_only=True,
    )

    class Meta:
        model = TestAttempt
        fields = ["id", "test", "test_name", "duration_min", "total_marks",
                  "student", "student_name", "application_form_id",
                  "start_dt", "end_dt",
                  "started_at", "submitted_at", "status", "total_score",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "test_name", "duration_min", "total_marks",
                            "student_name", "application_form_id",
                            "started_at", "submitted_at", "status", "total_score",
                            "created_at", "updated_at"]


class MapTestSerializer(serializers.Serializer):
    student_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=False,
    )
    start_dt = serializers.DateTimeField()
    end_dt = serializers.DateTimeField()

    def validate(self, attrs):
        if attrs["end_dt"] <= attrs["start_dt"]:
            raise serializers.ValidationError(
                {"end_dt": "end_dt must be after start_dt."}
            )
        return attrs


class SubmitAnswerSerializer(serializers.Serializer):
    question = serializers.IntegerField()
    answer = serializers.CharField(allow_blank=True)


class SubmitAttemptSerializer(serializers.Serializer):
    answers = SubmitAnswerSerializer(many=True)


class TestResponseSerializer(serializers.ModelSerializer):
    question_description = serializers.CharField(
        source="question.description", read_only=True,
    )
    question_type = serializers.CharField(source="question.type", read_only=True)
    question_marks = serializers.DecimalField(
        source="question.marks", max_digits=5, decimal_places=1, read_only=True,
    )
    student_name = serializers.CharField(
        source="attempt.student.student_name", read_only=True,
    )

    class Meta:
        model = TestResponse
        fields = ["id", "attempt", "question",
                  "question_description", "question_type", "question_marks",
                  "student_name",
                  "answer", "marks_awarded", "is_auto_graded", "feedback",
                  "reviewed_by", "reviewed_at",
                  "created_at", "updated_at"]
        read_only_fields = fields


class ReviewResponseSerializer(serializers.Serializer):
    marks_awarded = serializers.DecimalField(max_digits=5, decimal_places=1)
    feedback = serializers.CharField(required=False, allow_blank=True, max_length=2000)


# === Lessons ========================================================

class LessonSerializer(serializers.ModelSerializer):
    """Staff-facing lesson plan, including both review states."""

    batch_name = serializers.CharField(source="batch.name", read_only=True)
    hod_name = serializers.CharField(source="hod.full_name", read_only=True)
    class_mentor_name = serializers.CharField(
        source="class_mentor.full_name", read_only=True,
    )
    overall_status = serializers.CharField(read_only=True)
    is_visible_to_students = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(
        source="created_by.username", read_only=True, default="",
    )

    class Meta:
        model = Lesson
        fields = [
            "id", "batch", "batch_name",
            "unit", "assignment",
            "submission_due_date", "submission_due_desc",
            "hod", "hod_name", "class_mentor", "class_mentor_name",
            "module_project", "module_project_due",
            "sem_end_project", "sem_end_project_due",
            "display_date", "visits_workshops",
            "hod_status", "hod_remarks", "hod_decided_at",
            "mentor_status", "mentor_remarks", "mentor_decided_at",
            "overall_status", "is_visible_to_students",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "batch_name", "hod_name", "class_mentor_name",
            "hod_status", "hod_remarks", "hod_decided_at",
            "mentor_status", "mentor_remarks", "mentor_decided_at",
            "overall_status", "is_visible_to_students",
            "created_by", "created_by_name", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        # At least one form of submission deadline must be provided. On a
        # partial update, fall back to the instance's existing values.
        inst = self.instance
        due_date = attrs.get(
            "submission_due_date",
            getattr(inst, "submission_due_date", None),
        )
        due_desc = attrs.get(
            "submission_due_desc",
            getattr(inst, "submission_due_desc", ""),
        )
        if not due_date and not (due_desc or "").strip():
            raise serializers.ValidationError({
                "submission_due_desc": (
                    "Provide a submission date or a descriptive note "
                    "(e.g. 'after the 4th session')."
                ),
            })
        return attrs


class LessonReviewSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=[("HOD", "HOD"),
                                            ("MENTOR", "Mentor")])
    decision = serializers.ChoiceField(
        choices=[("APPROVED", "Approved"), ("REJECTED", "Rejected"),
                 ("IMPROVE", "Needs improvement")],
    )
    remarks = serializers.CharField(required=False, allow_blank=True,
                                    max_length=2000)


class PortalLessonSerializer(serializers.ModelSerializer):
    """Read-only lesson plan for students of an approved lesson's batch."""

    batch_name = serializers.CharField(source="batch.name", read_only=True)

    class Meta:
        model = Lesson
        fields = [
            "id", "batch", "batch_name",
            "unit", "assignment",
            "submission_due_date", "submission_due_desc",
            "module_project", "module_project_due",
            "sem_end_project", "sem_end_project_due",
            "display_date", "visits_workshops",
            "created_at",
        ]
        read_only_fields = fields
