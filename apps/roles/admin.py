from django.contrib import admin

from .models import Permission, Role


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("key", "label", "module")
    list_filter = ("module",)
    search_fields = ("key", "label")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "is_system")
    list_filter = ("is_system",)
    search_fields = ("name",)
    filter_horizontal = ("permissions", "users")
