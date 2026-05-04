from rest_framework import serializers

from apps.academics.models import (
    Assignment, AssignmentSubmission, Test, TestAttempt, TestQuestion,
    TestResponse,
)
from apps.admissions.models import Student, StudentDocument
from apps.courseware.models import CoursewareTopic
from apps.student_leaves.models import StudentLeaveApplication


# --- Profile / me --------------------------------------------------

class PortalProfileSerializer(serializers.ModelSerializer):
    institute_name = serializers.CharField(source="institute.name", read_only=True)
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    program_name = serializers.CharField(source="program.name", read_only=True)
    academic_year_code = serializers.CharField(
        source="academic_year.code", read_only=True,
    )
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id", "application_form_id", "student_name",
            "gender", "dob", "nationality", "blood_group", "category",
            "father_name", "mother_name",
            "father_mobile", "mother_mobile",
            "father_email", "mother_email",
            "student_mobile", "student_email",
            "current_address", "permanent_address",
            "institute_name", "campus_name", "program_name",
            "academic_year_code",
            "photo_url",
        ]
        read_only_fields = fields

    def get_photo_url(self, obj):
        if not obj.photo:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.photo.url) if request else obj.photo.url


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8, max_length=128)


# --- Assignments (student-facing) ----------------------------------

class PortalAssignmentSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    attachment_url = serializers.SerializerMethodField()
    submission = serializers.SerializerMethodField()

    class Meta:
        model = Assignment
        fields = [
            "id", "title", "description", "max_marks", "due_date",
            "subject", "subject_code", "subject_name",
            "attachment", "attachment_url",
            "submission",
        ]
        read_only_fields = fields

    def get_attachment_url(self, obj):
        if not obj.attachment:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.attachment.url) if request else obj.attachment.url

    def get_submission(self, obj):
        sub = self.context.get("submissions_by_assignment", {}).get(obj.id)
        if sub is None:
            return None
        request = self.context.get("request")
        file_url = None
        if sub.file:
            file_url = (request.build_absolute_uri(sub.file.url)
                        if request else sub.file.url)
        return {
            "id": sub.id,
            "status": sub.status,
            "submitted_at": sub.submitted_at,
            "file_url": file_url,
            "grade": str(sub.grade) if sub.grade is not None else None,
            "feedback": sub.feedback,
        }


class SubmitAssignmentSerializer(serializers.Serializer):
    file = serializers.FileField(required=False)
    text_response = serializers.CharField(required=False, allow_blank=True,
                                           max_length=8000)

    def validate(self, attrs):
        if not attrs.get("file") and not attrs.get("text_response"):
            raise serializers.ValidationError(
                "Provide a file or a text_response.",
            )
        if (f := attrs.get("file")) and f.size > 50 * 1024 * 1024:
            raise serializers.ValidationError(
                {"file": "Max 50 MB."},
            )
        return attrs


# --- Courseware (student-facing) -----------------------------------

class PortalCoursewareTopicSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    attachments = serializers.SerializerMethodField()

    class Meta:
        model = CoursewareTopic
        fields = [
            "id", "name", "description",
            "subject", "subject_code", "subject_name",
            "attachments", "created_at",
        ]
        read_only_fields = fields

    def get_attachments(self, obj):
        request = self.context.get("request")
        out = []
        for a in obj.attachments.all():
            url = a.file.url if a.file else None
            if url and request:
                url = request.build_absolute_uri(url)
            out.append({"id": a.id, "name": a.name, "url": url})
        return out


# --- Tests ---------------------------------------------------------

class PortalTestQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestQuestion
        fields = ["id", "description", "type", "options", "marks", "sort_order"]
        read_only_fields = fields


class PortalTestSerializer(serializers.ModelSerializer):
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    attempt_status = serializers.SerializerMethodField()
    window = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()

    class Meta:
        model = Test
        fields = [
            "id", "name", "instructions", "duration_min",
            "subject", "subject_code", "subject_name",
            "total_marks", "status",
            "attempt_status", "window", "label",
        ]
        read_only_fields = fields

    def _attempt(self, obj):
        return self.context.get("attempts_by_test", {}).get(obj.id)

    def get_attempt_status(self, obj):
        a = self._attempt(obj)
        return a.status if a else None

    def get_window(self, obj):
        a = self._attempt(obj)
        return {"start": a.start_dt, "end": a.end_dt} if a else None

    def get_label(self, obj):
        from django.utils import timezone
        a = self._attempt(obj)
        if a is None:
            return "Not Mapped"
        if a.status in (TestAttempt.Status.SUBMITTED, TestAttempt.Status.GRADED):
            return "View Result"
        now = timezone.now()
        if now < a.start_dt:
            return "Coming Soon"
        if now > a.end_dt:
            return "Expired"
        return "Start Test"


class PortalTestDetailSerializer(PortalTestSerializer):
    questions = PortalTestQuestionSerializer(many=True, read_only=True)

    class Meta(PortalTestSerializer.Meta):
        fields = PortalTestSerializer.Meta.fields + ["questions"]
        read_only_fields = fields


class TestSubmitAnswerSerializer(serializers.Serializer):
    question = serializers.IntegerField()
    answer = serializers.CharField(allow_blank=True, max_length=8000)


class TestSubmitSerializer(serializers.Serializer):
    answers = TestSubmitAnswerSerializer(many=True)


# --- Student leaves (portal-facing) --------------------------------

class PortalLeaveSerializer(serializers.ModelSerializer):
    days = serializers.IntegerField(read_only=True)

    class Meta:
        model = StudentLeaveApplication
        fields = [
            "id", "leave_date", "leave_edate", "days",
            "student_remarks", "status",
            "batch_mentor_email", "module_mentor_email", "cc_emails",
            "approver_remarks", "decided_at",
            "created_at",
        ]
        read_only_fields = [
            "id", "days", "status", "approver_remarks", "decided_at",
            "created_at",
        ]


# --- Educational qualifications (StudentDocument reuse) ------------

QUALIFICATION_HEADERS = {
    StudentDocument.Header.SSLC,
    StudentDocument.Header.PUC,
    StudentDocument.Header.DIPLOMA,
    StudentDocument.Header.UG,
    StudentDocument.Header.PG,
}


class PortalQualificationSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = StudentDocument
        fields = [
            "id", "header", "regno_yearpassing", "school_college",
            "university_board", "certificate_no", "percent_obtained",
            "file", "file_url", "uploaded_on",
        ]
        read_only_fields = ["id", "file_url", "uploaded_on"]

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(obj.file.url) if request else obj.file.url


# --- Parent provisioning (admin side) ------------------------------

class ProvisionParentSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, max_length=128)
    full_name = serializers.CharField(max_length=200, required=False,
                                       allow_blank=True)
