from rest_framework import serializers

from .models import Campus, LeadSource, Program


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


class LeadSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadSource
        fields = ["id", "name", "slug", "is_active", "sort_order"]
        read_only_fields = ["id", "slug"]
