from django.contrib import admin

from .models import Department, Designation, Employee


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Designation)
class DesignationAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        "emp_code", "first_name", "family_name",
        "campus", "department", "designation",
        "status", "is_deleted", "date_of_joining",
    )
    list_filter = ("status", "is_deleted", "campus", "department",
                   "employment_type", "gender", "nationality")
    search_fields = ("emp_code", "first_name", "family_name",
                     "email_primary", "mobile_primary")
    autocomplete_fields = (
        "designation", "department", "campus", "institute",
        "current_city", "current_state", "permanent_city", "permanent_state",
        "reporting_manager_1", "reporting_manager_2",
        "reporting_manager_3", "reporting_manager_4",
        "user_account",
    )
    readonly_fields = ("qr_code", "created_by", "created_on",
                       "updated_by", "updated_on", "deleted_at")

    def get_queryset(self, request):
        return Employee.all_objects.all()
