from django.urls import path

from .views import (
    AdminResetPasswordView,
    ChangePasswordView,
    ForgotPasswordView,
    LoginView,
    LogoutView,
    MeView,
    RefreshView,
    ResetPasswordView,
    UserDetailView,
    UserListCreateView,
)

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", RefreshView.as_view(), name="refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("auth/change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("auth/forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("auth/reset-password/", ResetPasswordView.as_view(), name="reset-password"),

    path("users/", UserListCreateView.as_view(), name="user-list-create"),
    path("users/<int:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("users/<int:pk>/reset-password/",
         AdminResetPasswordView.as_view(), name="user-reset-password"),
]
