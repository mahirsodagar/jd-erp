from django.urls import path

from .views import PermissionListView, RoleDetailView, RoleListCreateView

urlpatterns = [
    path("permissions/", PermissionListView.as_view(), name="permission-list"),
    path("roles/", RoleListCreateView.as_view(), name="role-list-create"),
    path("roles/<int:pk>/", RoleDetailView.as_view(), name="role-detail"),
]
