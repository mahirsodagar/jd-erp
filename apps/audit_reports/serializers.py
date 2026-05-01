from rest_framework import serializers

from .models import (
    AdminDailyReport, BatchMentorReport, ComplianceFlag, CourseEndReport,
    FacultyDailyReport, FacultySelfAppraisal, StudentFeedback,
)


class FacultyDailyReportSerializer(serializers.ModelSerializer):
    faculty_name = serializers.CharField(source="faculty.full_name", read_only=True)
    faculty_code = serializers.CharField(source="faculty.emp_code", read_only=True)

    class Meta:
        model = FacultyDailyReport
        fields = [
            "id", "faculty", "faculty_name", "faculty_code",
            "date", "description", "hours_taught", "non_academic_hours",
            "remarks",
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
