from django.contrib import admin

from .models import AuthLog


@admin.register(AuthLog)
class AuthLogAdmin(admin.ModelAdmin):
    list_display = ("event", "actor", "target", "ip_address", "created_at")
    list_filter = ("event",)
    search_fields = ("identifier", "actor__username", "target__username", "ip_address")
    readonly_fields = [f.name for f in AuthLog._meta.fields]
