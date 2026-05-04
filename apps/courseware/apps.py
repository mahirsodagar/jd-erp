from django.apps import AppConfig


class CoursewareConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.courseware"
    label = "courseware"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import CoursewareTopic, CoursewareAttachment, CoursewareMapping
        auditlog.register(CoursewareTopic)
        auditlog.register(CoursewareAttachment)
        auditlog.register(CoursewareMapping)
