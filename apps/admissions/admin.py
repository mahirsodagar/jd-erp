from django.contrib import admin

from .models import Enrollment, Student, StudentDocument


class StudentDocumentInline(admin.TabularInline):
    model = StudentDocument
    extra = 0
    readonly_fields = ("uploaded_by", "uploaded_on")


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        "application_form_id", "student_name", "gender",
        "campus", "program", "academic_year",
        "student_mobile", "student_email", "created_on",
    )
    list_filter = ("campus", "program", "academic_year",
                   "gender", "category", "nationality")
    search_fields = (
        "application_form_id", "student_name",
        "student_email", "student_mobile",
        "father_name", "mother_name",
    )
    autocomplete_fields = (
        "institute", "campus", "program", "course", "academic_year",
        "current_city", "current_state", "permanent_city", "permanent_state",
        "user_account", "lead_origin",
    )
    readonly_fields = (
        "application_form_id", "user_account", "lead_origin",
        "created_by", "created_on", "updated_by", "updated_on",
    )
    inlines = (StudentDocumentInline,)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "id", "student", "program", "batch", "semester",
        "academic_year", "status", "entry_date",
    )
    list_filter = ("status", "campus", "program", "academic_year", "batch")
    search_fields = (
        "student__student_name", "student__application_form_id",
        "batch__name",
    )
    autocomplete_fields = (
        "student", "program", "course", "semester",
        "campus", "batch", "academic_year", "entry_user",
    )
    readonly_fields = ("created_on", "updated_on")


@admin.register(StudentDocument)
class StudentDocumentAdmin(admin.ModelAdmin):
    list_display = ("student", "header", "school_college",
                    "percent_obtained", "uploaded_on")
    list_filter = ("header",)
    search_fields = ("student__student_name", "school_college", "certificate_no")
    autocomplete_fields = ("student", "uploaded_by")
