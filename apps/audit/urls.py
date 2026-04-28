from django.urls import path

from .views import AuthLogListView, DataAuditListView

urlpatterns = [
    path("auth-logs/", AuthLogListView.as_view(), name="auth-log-list"),
    path("data-logs/", DataAuditListView.as_view(), name="data-audit-list"),
]
