from django.urls import path

from apps.portal.views import ProvisionParentView

from .views import (
    BatchGraduateView,
    BatchPromoteView,
    EnrollmentDetailView,
    EnrollmentListCreateView,
    EnrollmentUndertakingView,
    StudentDetailView,
    StudentDocumentDetailView,
    StudentDocumentsView,
    StudentListView,
    StudentMeDocumentsView,
    StudentMeView,
    StudentRemarksView,
    StudentSendHandbookView,
    StudentSendPortalCredentialsView,
)

urlpatterns = [
    path("me/", StudentMeView.as_view(), name="student-me"),
    path("me/documents/", StudentMeDocumentsView.as_view(), name="student-me-docs"),

    path("students/", StudentListView.as_view(), name="student-list"),
    path("students/<int:pk>/", StudentDetailView.as_view(), name="student-detail"),
    path("students/<int:pk>/documents/", StudentDocumentsView.as_view(), name="student-docs"),
    path("students/<int:pk>/remarks/", StudentRemarksView.as_view(), name="student-remarks"),
    path("students/<int:pk>/parent/", ProvisionParentView.as_view(), name="student-parent-provision"),
    path("students/<int:pk>/send-portal-credentials/",
         StudentSendPortalCredentialsView.as_view(),
         name="student-send-portal-credentials"),
    path("students/<int:pk>/send-handbook/",
         StudentSendHandbookView.as_view(),
         name="student-send-handbook"),
    path("documents/<int:pk>/", StudentDocumentDetailView.as_view(), name="student-doc-detail"),

    path("enrollments/", EnrollmentListCreateView.as_view(), name="enrollment-list-create"),
    path("enrollments/<int:pk>/", EnrollmentDetailView.as_view(), name="enrollment-detail"),
    path(
        "enrollments/<int:pk>/undertaking/",
        EnrollmentUndertakingView.as_view(),
        name="enrollment-undertaking",
    ),

    path("batch-promote/", BatchPromoteView.as_view(),
         name="batch-promote"),
    path("batch-graduate/", BatchGraduateView.as_view(),
         name="batch-graduate"),
]
