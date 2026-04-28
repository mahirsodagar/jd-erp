from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "full_name", "is_active", "is_staff")
    search_fields = ("username", "email", "full_name")
    ordering = ("username",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal", {"fields": ("email", "full_name")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser",
                                    "groups", "user_permissions")}),
        ("Campus access", {"fields": ("campuses",)}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    filter_horizontal = ("groups", "user_permissions", "campuses")
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "password1", "password2"),
        }),
    )
