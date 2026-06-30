import logging

from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
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
    record_password_reset_requested,
    record_password_reset_completed,
)
from apps.common.throttles import (
    ForgotPasswordThrottle,
    LoginRateThrottle,
    PasswordChangeThrottle,
)
from apps.notifications.email import send_email

from .password_mirror import mirror_plaintext_password
from .permissions import HasPerm
from .serializers import (
    AdminResetPasswordSerializer,
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    MeUpdateSerializer,
    ResetPasswordSerializer,
    TenantTokenObtainSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

logger = logging.getLogger(__name__)

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
        # If this is a student logging in, retire the plaintext mirror of
        # their portal password — the field is only meant to bridge the
        # gap between provisioning and the first successful login.
        from apps.admissions.services import clear_temp_password_for
        clear_temp_password_for(user)
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

    def patch(self, request):
        serializer = MeUpdateSerializer(
            request.user, data=request.data, partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PasswordChangeThrottle]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        new_pw = serializer.validated_data["new_password"]
        request.user.set_password(new_pw)
        request.user.save(update_fields=["password"])
        # Self-change: the student knows the new password. Don't mirror
        # the plaintext — clear any stale temp from the prior provision.
        from apps.admissions.services import clear_temp_password_for
        clear_temp_password_for(request.user)
        record_password_change(request, user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserListCreateView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    perm_base = "accounts.user"

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
    perm_base = "accounts.user"

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
    """Admin issues a temporary password for any user.

    Best-effort emails the new password to the target user so they
    don't depend on the admin reading it out. Goes through MSG91 when
    settings.MSG91_EMAIL_TEMPLATES has the matching key registered;
    otherwise falls back to plain SMTP via the notifications layer.
    """

    permission_classes = [IsAuthenticated, HasPerm]
    # Resetting a password edits an existing user, not a CRUD "add".
    required_perm = "accounts.user.edit"

    def post(self, request, pk):
        target = User.objects.get(pk=pk)
        serializer = AdminResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_pw = serializer.validated_data["new_password"]
        target.set_password(new_pw)
        target.save(update_fields=["password"])
        mirror_plaintext_password(target, new_pw)
        record_password_reset(request, actor=request.user, target=target)

        delivery = {
            "delivered": False,
            "delivery_error": "",
            "recipient": (target.email or "").strip(),
        }
        if delivery["recipient"]:
            from apps.notifications.services import queue_notification
            from apps.notifications.models import NotificationDispatchLog
            base = getattr(
                dj_settings, "FRONTEND_BASE_URL", "http://localhost:5173",
            ).rstrip("/")
            log = queue_notification(
                template_key="account.password_reset_by_admin.email",
                recipient=delivery["recipient"],
                context={
                    "name": target.full_name or target.username,
                    "username": target.username,
                    "password": new_pw,
                    "login_url": base,
                },
                related=target,
            )
            sent = NotificationDispatchLog.Status.SENT
            delivery["delivered"] = getattr(log, "status", "") == sent
            if not delivery["delivered"]:
                delivery["delivery_error"] = getattr(log, "error", "") or ""
        else:
            delivery["delivery_error"] = "User has no email on file."

        return Response(delivery, status=status.HTTP_200_OK)


# --- Self-service forgot-password ----------------------------------------

class ForgotPasswordView(APIView):
    """Anonymous: kick off a password reset.

    Always returns 200 — we don't want this endpoint to leak whether an
    email is registered (account enumeration). The audit log records
    actual-user-found vs not-found separately.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ForgotPasswordThrottle]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()

        # Case-insensitive lookup; if multiple users share an email (rare
        # but legal in the User model), grab the most-recently-active.
        user = (
            User.objects.filter(email__iexact=email, is_active=True)
            .order_by("-last_login", "-date_joined")
            .first()
        )

        if user is not None:
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            base = getattr(
                dj_settings, "FRONTEND_BASE_URL", "http://localhost:5173",
            ).rstrip("/")
            # SPA uses HashRouter → route lives after #.
            reset_url = f"{base}/#/reset-password/{uidb64}/{token}"

            subject = "Reset your JD ERP password"
            body = (
                f"Hi {user.full_name or user.username},\n\n"
                "We received a request to reset the password on your JD "
                "account. To choose a new password, open this link:\n\n"
                f"{reset_url}\n\n"
                "The link expires in a few days. If you didn't request "
                "this, you can safely ignore the email — your password "
                "won't change.\n\n"
                "— JD Admissions"
            )
            try:
                send_email(recipient=email, subject=subject, body=body)
            except Exception:
                # Don't surface the failure to the caller (still 200 to
                # avoid enumeration) — but log it so ops can spot
                # SMTP outages.
                logger.exception("Failed to send password-reset email to %s", email)

            record_password_reset_requested(request, target=user)
        else:
            # Still audit so brute-force probes show up in the log.
            record_password_reset_requested(request, target=None, email=email)

        return Response(
            {"detail": "If that email is registered, a reset link has been sent."},
            status=status.HTTP_200_OK,
        )


class ResetPasswordView(APIView):
    """Anonymous: complete a reset using the link emailed earlier."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ForgotPasswordThrottle]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        new_pw = serializer.validated_data["new_password"]
        user.set_password(new_pw)
        user.save(update_fields=["password"])
        # Self-reset via token: the user typed the new password just now,
        # so they have it. Clear any plaintext mirror lying around.
        from apps.admissions.services import clear_temp_password_for
        clear_temp_password_for(user)
        record_password_reset_completed(request, target=user)

        # Best-effort: tell the user their password just changed.
        if user.email:
            try:
                send_email(
                    recipient=user.email,
                    subject="Your JD ERP password was changed",
                    body=(
                        f"Hi {user.full_name or user.username},\n\n"
                        "Your password was just changed. If this was you, "
                        "no further action is needed. If you didn't change "
                        "your password, contact your administrator "
                        "immediately.\n\n— JD Admissions"
                    ),
                )
            except Exception:
                logger.exception("Failed to send password-changed notice to %s", user.email)

        return Response(status=status.HTTP_204_NO_CONTENT)
