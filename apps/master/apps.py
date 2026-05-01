from django.apps import AppConfig


class MasterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.master"
    label = "master"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import (
            AcademicYear, Batch, Campus, City, Classroom, Course, CourseSubject,
            Degree, FeeTemplate, Institute, LeadSource, Program, Semester,
            State, Subject, TimeSlot,
        )
        auditlog.register(Subject)
        auditlog.register(CourseSubject)
        auditlog.register(Classroom)
        auditlog.register(TimeSlot)
        auditlog.register(FeeTemplate)
        auditlog.register(Campus)
        auditlog.register(Program)
        auditlog.register(LeadSource)
        auditlog.register(Institute)
        auditlog.register(State)
        auditlog.register(City)
        auditlog.register(AcademicYear)
        auditlog.register(Degree)
        auditlog.register(Course)
        auditlog.register(Semester)
        auditlog.register(Batch)
