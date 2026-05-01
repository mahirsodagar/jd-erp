from rest_framework import serializers

from .models import (
    AcademicYear, Batch, Campus, City, Classroom, Course, CourseSubject,
    Degree, FeeTemplate, Institute, LeadSource, Program, Semester,
    State, Subject, TimeSlot,
)


class CampusSerializer(serializers.ModelSerializer):
    program_count = serializers.SerializerMethodField()

    class Meta:
        model = Campus
        fields = [
            "id", "name", "code", "city", "state",
            "is_active", "program_count", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "program_count", "created_at", "updated_at"]

    def get_program_count(self, obj):
        return obj.programs.count()


class ProgramSerializer(serializers.ModelSerializer):
    campus_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Campus.objects.all(),
        source="campuses", write_only=True, required=False,
    )
    campuses = CampusSerializer(many=True, read_only=True)

    class Meta:
        model = Program
        fields = [
            "id", "name", "code", "degree_type", "duration_months",
            "description", "is_active",
            "campuses", "campus_ids",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "campuses", "created_at", "updated_at"]


class InstituteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Institute
        fields = ["id", "name", "code", "logo", "is_active",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class StateSerializer(serializers.ModelSerializer):
    class Meta:
        model = State
        fields = ["id", "name", "code", "is_union_territory"]
        read_only_fields = ["id"]


class CitySerializer(serializers.ModelSerializer):
    state_name = serializers.CharField(source="state.name", read_only=True)

    class Meta:
        model = City
        fields = ["id", "name", "state", "state_name", "is_active"]
        read_only_fields = ["id", "state_name"]


class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = ["id", "code", "full_name", "start_date", "end_date", "is_current"]
        read_only_fields = ["id"]


class DegreeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Degree
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = ["id"]


class CourseSerializer(serializers.ModelSerializer):
    program_name = serializers.CharField(source="program.name", read_only=True)

    class Meta:
        model = Course
        fields = ["id", "name", "code", "program", "program_name",
                  "duration_months", "is_active",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "program_name", "created_at", "updated_at"]


class SemesterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Semester
        fields = ["id", "name", "number", "is_active"]
        read_only_fields = ["id"]


class BatchSerializer(serializers.ModelSerializer):
    program_name = serializers.CharField(source="program.name", read_only=True)
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    academic_year_code = serializers.CharField(source="academic_year.code", read_only=True)
    mentor_name = serializers.CharField(source="mentor.full_name", read_only=True, default="")

    class Meta:
        model = Batch
        fields = ["id", "name", "short_name",
                  "program", "program_name",
                  "campus", "campus_name",
                  "academic_year", "academic_year_code",
                  "mentor", "mentor_name",
                  "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "program_name", "campus_name",
                            "academic_year_code", "mentor_name",
                            "created_at", "updated_at"]


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ["id", "name", "code", "credits", "is_active",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class CourseSubjectSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True)

    class Meta:
        model = CourseSubject
        fields = ["id", "course", "course_name", "subject", "subject_name",
                  "sort_order", "is_active"]
        read_only_fields = ["id", "course_name", "subject_name"]


class ClassroomSerializer(serializers.ModelSerializer):
    campus_name = serializers.CharField(source="campus.name", read_only=True)

    class Meta:
        model = Classroom
        fields = ["id", "name", "code", "campus", "campus_name",
                  "capacity", "description", "is_active",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "campus_name", "created_at", "updated_at"]


class TimeSlotSerializer(serializers.ModelSerializer):
    academic_year_code = serializers.CharField(source="academic_year.code", read_only=True)

    class Meta:
        model = TimeSlot
        fields = ["id", "label", "start_time", "end_time",
                  "academic_year", "academic_year_code",
                  "is_active", "sort_order"]
        read_only_fields = ["id", "academic_year_code"]

    def validate(self, attrs):
        start = attrs.get("start_time") or getattr(self.instance, "start_time", None)
        end = attrs.get("end_time") or getattr(self.instance, "end_time", None)
        if start and end and end <= start:
            raise serializers.ValidationError(
                {"end_time": "Must be later than start_time."}
            )
        return attrs


class FeeTemplateSerializer(serializers.ModelSerializer):
    academic_year_code = serializers.CharField(source="academic_year.code", read_only=True)
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    program_name = serializers.CharField(source="program.name", read_only=True)
    course_name = serializers.CharField(source="course.name", read_only=True, default="")

    class Meta:
        model = FeeTemplate
        fields = [
            "id", "name",
            "academic_year", "academic_year_code",
            "campus", "campus_name",
            "program", "program_name",
            "course", "course_name",
            "application_fee", "course_fee", "other_fee", "total_fee",
            "notes", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "academic_year_code", "campus_name", "program_name",
            "course_name", "created_at", "updated_at",
        ]


class LeadSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadSource
        fields = ["id", "name", "slug", "is_active", "sort_order"]
        read_only_fields = ["id", "slug"]
