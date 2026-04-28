from django.apps import AppConfig


class EmployeesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.employees"
    label = "employees"

    def ready(self):
        from auditlog.registry import auditlog
        from .models import Department, Designation, Employee
        auditlog.register(Department)
        auditlog.register(Designation)
        auditlog.register(Employee, exclude_fields=["qr_code"])
