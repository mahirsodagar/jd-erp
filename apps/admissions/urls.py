from django.urls import path

from apps.portal.views import ProvisionParentView

from .views import (
    EnrollmentDetailView,
    EnrollmentListCreateView,
    StudentDetailView,
    StudentDocumentDetailView,
    StudentDocumentsView,
    StudentListView,
    StudentMeDocumentsView,
    StudentMeView,
)

urlpatterns = [
    path("me/", StudentMeView.as_view(), name="student-me"),
    path("me/documents/", StudentMeDocumentsView.as_view(), name="student-me-docs"),

    path("students/", StudentListView.as_view(), name="student-list"),
    path("students/<int:pk>/", StudentDetailView.as_view(), name="student-detail"),
    path("students/<int:pk>/documents/", StudentDocumentsView.as_view(), name="student-docs"),
    path("students/<int:pk>/parent/", ProvisionParentView.as_view(), name="student-parent-provision"),
    path("documents/<int:pk>/", StudentDocumentDetailView.as_view(), name="student-doc-detail"),

    path("enrollments/", EnrollmentListCreateView.as_view(), name="enrollment-list-create"),
    path("enrollments/<int:pk>/", EnrollmentDetailView.as_view(), name="enrollment-detail"),
]
