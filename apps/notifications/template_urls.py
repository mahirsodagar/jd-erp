"""Communication → System Emails (`/api/comms/system-emails/`)."""

from django.urls import path

from .template_views import (
    EmailLayoutPreviewView, EmailLayoutRevertView, EmailLayoutView,
    SystemEmailAttachmentsView, SystemEmailDetailView, SystemEmailListView,
    SystemEmailPreviewView, SystemEmailRevertView, SystemEmailTestSendView,
    SystemEmailVersionView,
)

urlpatterns = [
    path("", SystemEmailListView.as_view(), name="system-emails-list"),
    path("layout/", EmailLayoutView.as_view(), name="system-emails-layout"),
    path("layout/preview/", EmailLayoutPreviewView.as_view(), name="system-emails-layout-preview"),
    path("layout/revert/<int:version_id>/", EmailLayoutRevertView.as_view(),
         name="system-emails-layout-revert"),
    path("<str:key>/", SystemEmailDetailView.as_view(), name="system-emails-detail"),
    path("<str:key>/preview/", SystemEmailPreviewView.as_view(), name="system-emails-preview"),
    path("<str:key>/test-send/", SystemEmailTestSendView.as_view(), name="system-emails-test-send"),
    path("<str:key>/attachments/", SystemEmailAttachmentsView.as_view(),
         name="system-emails-attachments"),
    path("<str:key>/attachments/<int:attachment_id>/", SystemEmailAttachmentsView.as_view(),
         name="system-emails-attachment"),
    path("<str:key>/versions/<int:version_id>/", SystemEmailVersionView.as_view(),
         name="system-emails-version"),
    path("<str:key>/revert/<int:version_id>/", SystemEmailRevertView.as_view(),
         name="system-emails-revert"),
]
