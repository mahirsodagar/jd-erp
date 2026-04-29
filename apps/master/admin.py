from django.contrib import admin

from .models import (
    AcademicYear, Batch, Campus, City, Course, Degree, FeeTemplate,
    Institute, LeadSource, Program, Semester, State,
)


@admin.register(FeeTemplate)
class FeeTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "academic_year", "campus", "program",
                    "course", "total_fee", "is_active")
    list_filter = ("is_active", "academic_year", "campus", "program")
    search_fields = ("name",)
    autocomplete_fields = ("academic_year", "campus", "program", "course")


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("code", "full_name", "start_date", "end_date", "is_current")
    list_filter = ("is_current",)
    search_fields = ("code", "full_name")


@admin.register(Degree)
class DegreeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "program", "duration_months", "is_active")
    list_filter = ("is_active", "program")
    search_fields = ("name", "code")
    autocomplete_fields = ("program",)


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ("name", "number", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("name", "program", "campus", "academic_year", "mentor", "is_active")
    list_filter = ("is_active", "program", "campus", "academic_year")
    search_fields = ("name", "short_name")
    autocomplete_fields = ("program", "campus", "academic_year", "mentor")


@admin.register(Institute)
class InstituteAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active")
    search_fields = ("name", "code")


@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_union_territory")
    list_filter = ("is_union_territory",)
    search_fields = ("name", "code")


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "state", "is_active")
    list_filter = ("state", "is_active")
    search_fields = ("name",)
    autocomplete_fields = ("state",)


@admin.register(Campus)
class CampusAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "city", "state", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "city")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "degree_type", "duration_months", "is_active")
    list_filter = ("is_active", "degree_type")
    search_fields = ("name", "code")
    filter_horizontal = ("campuses",)


@admin.register(LeadSource)
class LeadSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
