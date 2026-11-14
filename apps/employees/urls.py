from django.urls import path

from .views import (
    DepartmentDetailView,
    DepartmentListCreateView,
    DesignationDetailView,
    DesignationListCreateView,
    EmployeeActivateView,
    EmployeeDeactivateView,
    EmployeeDetailView,
    EmployeeDocumentDetailView,
    EmployeeDocumentListCreateView,
    EmployeeIdCardView,
    EmployeeListCreateView,
    EmployeeOptionsView,
    EmployeePortalAccountView,
    EmployeeQrView,
    HolidayDetailView,
    HolidayListCreateView,
)

urlpatterns = [
    path("departments/", DepartmentListCreateView.as_view(), name="department-list-create"),
    path("departments/<int:pk>/", DepartmentDetailView.as_view(), name="department-detail"),

    path("designations/", DesignationListCreateView.as_view(), name="designation-list-create"),
    path("designations/<int:pk>/", DesignationDetailView.as_view(), name="designation-detail"),

    path("holidays/", HolidayListCreateView.as_view(), name="holiday-list-create"),
    path("holidays/<int:pk>/", HolidayDetailView.as_view(), name="holiday-detail"),

    # Dropdown directory — any staff login, no HR permission needed.
    path("options/", EmployeeOptionsView.as_view(), name="employee-options"),
    path("", EmployeeListCreateView.as_view(), name="employee-list-create"),
    path("<int:pk>/", EmployeeDetailView.as_view(), name="employee-detail"),
    path("<int:pk>/activate/", EmployeeActivateView.as_view(), name="employee-activate"),
    path("<int:pk>/deactivate/", EmployeeDeactivateView.as_view(), name="employee-deactivate"),
    path("<int:pk>/documents/", EmployeeDocumentListCreateView.as_view(), name="employee-documents"),
    path("<int:pk>/documents/<int:doc_id>/", EmployeeDocumentDetailView.as_view(), name="employee-document-detail"),
    path("<int:pk>/id-card.pdf", EmployeeIdCardView.as_view(), name="employee-id-card"),
    path("<int:pk>/qr.png", EmployeeQrView.as_view(), name="employee-qr"),
    path("<int:pk>/portal-account/", EmployeePortalAccountView.as_view(), name="employee-portal"),
]
