from django.urls import path

from .views import (
    DepartmentDetailView,
    DepartmentListCreateView,
    DesignationDetailView,
    DesignationListCreateView,
    EmployeeActivateView,
    EmployeeDeactivateView,
    EmployeeDetailView,
    EmployeeIdCardView,
    EmployeeListCreateView,
    EmployeePortalAccountView,
    EmployeeQrView,
)

urlpatterns = [
    path("departments/", DepartmentListCreateView.as_view(), name="department-list-create"),
    path("departments/<int:pk>/", DepartmentDetailView.as_view(), name="department-detail"),

    path("designations/", DesignationListCreateView.as_view(), name="designation-list-create"),
    path("designations/<int:pk>/", DesignationDetailView.as_view(), name="designation-detail"),

    path("", EmployeeListCreateView.as_view(), name="employee-list-create"),
    path("<int:pk>/", EmployeeDetailView.as_view(), name="employee-detail"),
    path("<int:pk>/activate/", EmployeeActivateView.as_view(), name="employee-activate"),
    path("<int:pk>/deactivate/", EmployeeDeactivateView.as_view(), name="employee-deactivate"),
    path("<int:pk>/id-card.png", EmployeeIdCardView.as_view(), name="employee-id-card"),
    path("<int:pk>/qr.png", EmployeeQrView.as_view(), name="employee-qr"),
    path("<int:pk>/portal-account/", EmployeePortalAccountView.as_view(), name="employee-portal"),
]
