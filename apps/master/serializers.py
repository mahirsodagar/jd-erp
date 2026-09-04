from rest_framework import serializers

from .models import (
    AcademicYear, Batch, Campus, City, Classroom, Course, CurriculumMapping,
    Degree, FeeTemplate, Institute, LeadSource, Program, Semester,
    State, Subject, TimeSlot, University,
)


class CampusSerializer(serializers.ModelSerializer):
    # A campus has no institute of its own — it hosts programs, and each
    # program names its institute. `institutes` is therefore derived and
    # read-only; it lists every institute present at this campus.
    institutes = serializers.SerializerMethodField()
    institute_names = serializers.SerializerMethodField()
    program_count = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Campus
        fields = [
            "id", "name", "code",
            "institutes", "institute_names",
            "city", "state",
            "image", "image_url",
            "is_active", "program_count", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "institutes", "institute_names", "image_url",
            "program_count", "created_at", "updated_at",
        ]
        extra_kwargs = {"image": {"write_only": True, "required": False}}

    def get_institutes(self, obj):
        return [{"id": i.id, "code": i.code, "name": i.name}
                for i in obj.institutes]

    def get_institute_names(self, obj):
        """Comma-joined labels, for grids that want a single cell."""
        return ", ".join(i.name for i in obj.institutes)

    def get_program_count(self, obj):
        return obj.programs.count()

    def get_image_url(self, obj):
        """Absolute URL so the SPA can use it directly. Mirrors
        `EmployeeSerializer.get_photo_url` — needs `request` in context."""
        request = self.context.get("request")
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        return obj.image.url if obj.image else None


class ProgramSerializer(serializers.ModelSerializer):
    campus_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Campus.objects.all(),
        source="campuses", write_only=True, required=False,
    )
    campuses = CampusSerializer(many=True, read_only=True)
    institute_name = serializers.CharField(
        source="institute.name", read_only=True, default="",
    )
    institute_code = serializers.CharField(
        source="institute.code", read_only=True, default="",
    )
    degree_name = serializers.CharField(
        source="degree.name", read_only=True, default="",
    )
    university_name = serializers.CharField(
        source="university.name", read_only=True, default="",
    )
    university_code = serializers.CharField(
        source="university.code", read_only=True, default="",
    )

    class Meta:
        model = Program
        fields = [
            "id", "name", "code",
            "institute", "institute_name", "institute_code",
            "university", "university_name", "university_code",
            "certification",
            "degree", "degree_name", "degree_type",
            "duration_months",
            "description", "is_active",
            "campuses", "campus_ids",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "campuses", "institute_name", "institute_code",
            "university_name", "university_code",
            "degree_name", "created_at", "updated_at",
        ]


class UniversitySerializer(serializers.ModelSerializer):
    program_count = serializers.SerializerMethodField()

    class Meta:
        model = University
        fields = ["id", "name", "code", "is_active", "program_count",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "program_count", "created_at", "updated_at"]

    def get_program_count(self, obj):
        return obj.programs.count()


class InstituteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Institute
        fields = ["id", "name", "code", "logo", "email_domain", "is_active",
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


class SemesterSerializer(serializers.ModelSerializer):
    program_name = serializers.CharField(
        source="program.name", read_only=True, default="",
    )

    class Meta:
        model = Semester
        fields = ["id", "program", "program_name", "name", "number",
                  "is_active"]
        read_only_fields = ["id", "program_name"]
        # DRF derives a UniqueTogetherValidator from the model's
        # (program, number) and (program, name) constraints, so a clash
        # already comes back as a 400 rather than a database error.


class CourseSerializer(serializers.ModelSerializer):
    """A Program Year (legacy `course_master`)."""

    program_name = serializers.CharField(source="program.name", read_only=True)
    # A year spans several semesters — the normalised `sem_id` CSV.
    semester_names = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = ["id", "name", "code", "program", "program_name",
                  "semesters", "semester_names",
                  "duration_months", "is_active",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "program_name", "semester_names",
                            "created_at", "updated_at"]

    def get_semester_names(self, obj):
        return ", ".join(
            s.name for s in obj.semesters.all().order_by("number")
        )


class CurriculumMappingSerializer(serializers.ModelSerializer):
    program_name = serializers.CharField(source="program.name", read_only=True)
    semester_name = serializers.CharField(source="semester.name", read_only=True)
    semester_number = serializers.IntegerField(
        source="semester.number", read_only=True,
    )
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    subject_code = serializers.CharField(source="subject.code", read_only=True)
    instructor_name = serializers.CharField(
        source="instructor.full_name", read_only=True, default="",
    )

    class Meta:
        model = CurriculumMapping
        fields = [
            "id",
            "program", "program_name",
            "semester", "semester_name", "semester_number",
            "subject", "subject_name", "subject_code",
            "instructor", "instructor_name",
            "is_active", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "program_name", "semester_name", "semester_number",
            "subject_name", "subject_code", "instructor_name",
            "created_at", "updated_at",
        ]

    def validate(self, attrs):
        """Surface the partial unique constraints as a field error rather
        than letting them surface as a 500 from the database."""
        def current(field):
            return attrs.get(field, getattr(self.instance, field, None))

        qs = CurriculumMapping.objects.filter(
            program=current("program"),
            semester=current("semester"),
            subject=current("subject"),
            instructor=current("instructor"),
        )
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                {"subject": "This subject is already mapped to that "
                            "program / semester / instructor."}
            )
        return attrs


class BatchSerializer(serializers.ModelSerializer):
    program_name = serializers.CharField(source="program.name", read_only=True)
    campus_name = serializers.CharField(source="campus.name", read_only=True)
    academic_year_code = serializers.CharField(source="academic_year.code", read_only=True)
    mentor_name = serializers.CharField(source="mentor.full_name", read_only=True, default="")
    start_semester_name = serializers.CharField(
        source="start_semester.name", read_only=True, default="",
    )

    class Meta:
        model = Batch
        fields = ["id", "name", "short_name",
                  "program", "program_name",
                  "campus", "campus_name",
                  "academic_year", "academic_year_code",
                  "start_semester", "start_semester_name",
                  "mentor", "mentor_name",
                  "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "program_name", "campus_name",
                            "academic_year_code", "start_semester_name",
                            "mentor_name", "created_at", "updated_at"]


class SubjectSerializer(serializers.ModelSerializer):
    program_name = serializers.CharField(
        source="program.name", read_only=True, default="",
    )
    semester_name = serializers.CharField(
        source="semester.name", read_only=True, default="",
    )

    class Meta:
        model = Subject
        fields = ["id", "name", "code",
                  "program", "program_name",
                  "semester", "semester_name",
                  "credits", "is_elective", "is_active",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "program_name", "semester_name",
                            "created_at", "updated_at"]


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
            "application_fee", "course_fee", "registration_fee",
            "other_fee", "total_fee",
            "notes", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "academic_year_code", "campus_name", "program_name",
            "course_name", "created_at", "updated_at",
        ]

    def validate(self, attrs):
        """The registration fee is carved out of `total_fee`, so it can
        never exceed it — otherwise the installment schedule, which must
        sum to the total, has nothing left to spread."""
        def current(field):
            return attrs.get(field, getattr(self.instance, field, None))

        registration = current("registration_fee")
        total = current("total_fee")
        if registration is not None and total is not None and registration > total:
            raise serializers.ValidationError({
                "registration_fee": f"Cannot exceed the total fee "
                                    f"({total}). The registration fee is "
                                    f"part of the total, not on top of it "
                                    f"— set it to 0 for courses that cost "
                                    f"less than the registration charge.",
            })
        return attrs


class LeadSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadSource
        fields = ["id", "name", "slug", "is_active", "sort_order"]
        read_only_fields = ["id", "slug"]
