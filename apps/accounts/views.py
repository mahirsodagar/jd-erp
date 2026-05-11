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
from apps.common.throttles import LoginRateThrottle, PasswordChangeThrottle

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
    throttle_classes = [LoginRateThrottle]

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


# SimpleJWT's TokenRefreshView (rotation + blacklist already configured),
# subclassed only to attach the login throttle so refresh shares the same
# 10/min IP budget as login.
class RefreshView(TokenRefreshView):
    throttle_classes = [LoginRateThrottle]


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
    throttle_classes = [PasswordChangeThrottle]

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
        # `select_related` on the reverse OneToOne avoids the N+1 the
        # serializer would otherwise trigger when computing
        # is_student / is_employee.
        qs = User.objects.select_related("student", "employee").order_by("-id")

        params = request.query_params
        if params.get("exclude_students") == "1":
            qs = qs.filter(student__isnull=True)
        if params.get("exclude_employees") == "1":
            qs = qs.filter(employee__isnull=True)
        if (q := params.get("search")):
            from django.db.models import Q
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(email__icontains=q)
                | Q(full_name__icontains=q)
            )
        if params.get("active") == "1":
            qs = qs.filter(is_active=True)
        elif params.get("active") == "0":
            qs = qs.filter(is_active=False)

        return Response(UserSerializer(qs, many=True).data)

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
