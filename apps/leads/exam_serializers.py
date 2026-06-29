"""Entrance-exam serializers. Mirrors the academics Test serializers
(apps/academics/serializers.py:405-545), retargeted to leads.Lead."""

from rest_framework import serializers

from .exam_models import (
    EntranceExam, EntranceExamAttempt, EntranceExamQuestion,
    EntranceExamResponse,
)


class EntranceExamQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EntranceExamQuestion
        fields = ["id", "exam", "description", "type", "options",
                  "answer_key", "marks", "sort_order"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        qtype = attrs.get("type") or getattr(self.instance, "type", "")
        opts = attrs.get("options") or getattr(self.instance, "options", [])
        key = attrs.get("answer_key") or getattr(self.instance, "answer_key", "")
        if qtype == EntranceExamQuestion.Type.MCQ:
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


class EntranceExamQuestionPublicSerializer(serializers.ModelSerializer):
    """Question shape exposed to candidates — no answer_key leaked."""
    class Meta:
        model = EntranceExamQuestion
        fields = ["id", "description", "type", "options", "marks", "sort_order"]
        read_only_fields = fields


class EntranceExamSerializer(serializers.ModelSerializer):
    program_name = serializers.CharField(source="program.name", read_only=True)
    question_count = serializers.SerializerMethodField()

    class Meta:
        model = EntranceExam
        fields = ["id", "name", "instructions", "duration_min",
                  "program", "program_name", "academic_year",
                  "status", "total_marks", "question_count",
                  "created_by", "created_at", "updated_at"]
        read_only_fields = ["id", "program_name",
                            "status", "total_marks", "question_count",
                            "created_by", "created_at", "updated_at"]

    def get_question_count(self, obj):
        return obj.questions.count()


class EntranceExamAttemptSerializer(serializers.ModelSerializer):
    lead_name = serializers.CharField(source="lead.name", read_only=True)
    lead_email = serializers.CharField(source="lead.email", read_only=True)
    exam_name = serializers.CharField(source="exam.name", read_only=True)
    duration_min = serializers.IntegerField(source="exam.duration_min", read_only=True)
    total_marks = serializers.DecimalField(
        source="exam.total_marks", max_digits=5, decimal_places=1, read_only=True,
    )

    class Meta:
        model = EntranceExamAttempt
        fields = ["id", "exam", "exam_name", "duration_min", "total_marks",
                  "lead", "lead_name", "lead_email", "access_token",
                  "start_dt", "end_dt",
                  "started_at", "submitted_at", "status", "total_score",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "exam_name", "duration_min", "total_marks",
                            "lead_name", "lead_email", "access_token",
                            "started_at", "submitted_at", "status", "total_score",
                            "created_at", "updated_at"]


class MapExamSerializer(serializers.Serializer):
    lead_ids = serializers.ListField(
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


class EntranceExamResponseSerializer(serializers.ModelSerializer):
    question_description = serializers.CharField(
        source="question.description", read_only=True,
    )
    question_type = serializers.CharField(source="question.type", read_only=True)
    question_marks = serializers.DecimalField(
        source="question.marks", max_digits=5, decimal_places=1, read_only=True,
    )
    lead_name = serializers.CharField(
        source="attempt.lead.name", read_only=True,
    )

    class Meta:
        model = EntranceExamResponse
        fields = ["id", "attempt", "question",
                  "question_description", "question_type", "question_marks",
                  "lead_name",
                  "answer", "marks_awarded", "is_auto_graded", "feedback",
                  "reviewed_by", "reviewed_at",
                  "created_at", "updated_at"]
        read_only_fields = fields


class ReviewResponseSerializer(serializers.Serializer):
    marks_awarded = serializers.DecimalField(max_digits=5, decimal_places=1)
    feedback = serializers.CharField(required=False, allow_blank=True, max_length=2000)
