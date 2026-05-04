from django.contrib import admin

from .models import CoursewareAttachment, CoursewareMapping, CoursewareTopic


class CoursewareAttachmentInline(admin.TabularInline):
    model = CoursewareAttachment
    extra = 0


@admin.register(CoursewareTopic)
class CoursewareTopicAdmin(admin.ModelAdmin):
    list_display = ("id", "subject", "batch", "name",
                    "is_published", "created_at")
    list_filter = ("is_published",)
    search_fields = ("name", "subject__code", "batch__name")
    autocomplete_fields = ("subject", "batch", "created_by")
    inlines = [CoursewareAttachmentInline]


@admin.register(CoursewareMapping)
class CoursewareMappingAdmin(admin.ModelAdmin):
    list_display = ("id", "topic", "student", "created_at")
    search_fields = ("topic__name", "student__student_name",
                     "student__application_form_id")
    autocomplete_fields = ("topic", "student")
