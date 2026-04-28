from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.audit.events import (
    record_login_failure,
    record_login_success,
    record_logout,
    record_password_change,
    record_password_reset,
)

from .permissions import HasPerm
from .serializers import (
    AdminResetPasswordSerializer,
    ChangePasswordSerializer,
    TenantTokenObtainSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

User = get_user_model()


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TenantTokenObtainSerializer(
            data=request.data, context={"request": request}
        )
        if not serializer.is_valid():
            record_login_failure(
                request, identifier=request.data.get("identifier", "")
            )
            return Response(serializer.errors, status=status.HTTP_401_UNAUTHORIZED)

        user = serializer.validated_data["user"]
        record_login_success(request, user=user)
        return Response(
            {
                "tokens": serializer.validated_data["tokens"],
                "user": UserSerializer(user).data,
            }
        )


# Use simplejwt's built-in refresh — rotation + blacklist already configured
RefreshView = TokenRefreshView


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw = request.data.get("refresh")
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except (TokenError, AttributeError):
                pass
        record_logout(request, user=request.user)
        return Response(status=status.HTTP_205_RESET_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        record_password_change(request, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserListCreateView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "accounts.user.manage"

    def get(self, request):
        return Response(
            UserSerializer(User.objects.all().order_by("-id"), many=True).data
        )

    def post(self, request):
        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            UserSerializer(user).data, status=status.HTTP_201_CREATED
        )


class UserDetailView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "accounts.user.manage"

    def get(self, request, pk):
        return Response(UserSerializer(User.objects.get(pk=pk)).data)

    def patch(self, request, pk):
        user = User.objects.get(pk=pk)
        serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(user).data)

    def delete(self, request, pk):
        user = User.objects.get(pk=pk)
        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminResetPasswordView(APIView):
    """Admin issues a temporary password for any user."""

    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "accounts.user.manage"

    def post(self, request, pk):
        target = User.objects.get(pk=pk)
        serializer = AdminResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target.set_password(serializer.validated_data["new_password"])
        target.save(update_fields=["password"])
        record_password_reset(request, actor=request.user, target=target)
        return Response(status=status.HTTP_204_NO_CONTENT)
