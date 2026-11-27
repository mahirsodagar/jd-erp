import logging

from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.shortcuts import get_object_or_404
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.admissions.services import sync_portal_password
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

from .permissions import HasPerm, has_perm
from .tokens import revoke_all_refresh_tokens
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
        sync_portal_password(request.user, new_pw)
        record_password_change(request, user=request.user)
        # Every other device is signed out; this one continues on a
        # fresh token pair returned here (the SPA swaps them in).
        revoke_all_refresh_tokens(request.user)
        refresh = RefreshToken.for_user(request.user)
        return Response(
            {"tokens": {"access": str(refresh.access_token), "refresh": str(refresh)}},
            status=status.HTTP_200_OK,
        )


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

        return Response(
            UserSerializer(qs, many=True, context={"request": request}).data
        )

    def post(self, request):
        # Creating a user with roles / is_staff / campuses needs the same
        # per-field keys as granting them on PATCH (UserDetailView), or
        # `accounts.user.add` alone would mint an account with any role.
        sent = set(request.data.keys())
        needed = {
            perm for field, perm in UserDetailView._FIELD_PERMS.items()
            if field in sent and request.data.get(field) not in (None, "", [], False)
        }
        missing = sorted(p for p in needed if not has_perm(request.user, p))
        if missing:
            return Response(
                {"detail": f"Missing permission(s): {', '.join(missing)}."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            UserSerializer(user, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class UserDetailView(APIView):
    """Read / edit / deactivate one user.

    PATCH is gated per field rather than by one blanket key. Assigning
    roles (or `is_staff`), assigning campuses and the ordinary profile
    edit are separate permissions: a single `accounts.user.edit` would
    let its holder grant themselves any role in the system, and campus
    assignment is what nearly every `*_all_campuses` scope resolves
    against.
    """

    permission_classes = [IsAuthenticated, HasPerm]
    perm_base = "accounts.user"

    #: field -> permission needed to change it.
    _FIELD_PERMS = {
        "role_ids": "accounts.user.assign_roles",
        "is_staff": "accounts.user.assign_roles",
        "campus_ids": "accounts.user.assign_campuses",
    }
    _PLAIN_FIELDS = frozenset({"full_name", "email", "is_active"})

    #: PATCH does its own per-field checks, so it must not be rejected
    #: up-front by the blanket `accounts.user.edit` requirement.
    def get_permissions(self):
        if self.request.method == "PATCH":
            return [IsAuthenticated()]
        return [IsAuthenticated(), HasPerm()]

    def get(self, request, pk):
        return Response(UserSerializer(
            get_object_or_404(User, pk=pk), context={"request": request},
        ).data)

    @staticmethod
    def _guard_superuser(request, target):
        """Only a superuser may alter a superuser's account — otherwise
        `accounts.user.edit` could change their email / deactivate them
        and take the account over via forgot-password."""
        if target.is_superuser and not request.user.is_superuser:
            return Response(
                {"detail": "Only a superuser can modify a superuser account."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def patch(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if (denied := self._guard_superuser(request, user)) is not None:
            return denied
        sent = set(request.data.keys())

        needed = {
            perm for field, perm in self._FIELD_PERMS.items() if field in sent
        }
        if sent & self._PLAIN_FIELDS:
            needed.add("accounts.user.edit")
        missing = sorted(p for p in needed if not has_perm(request.user, p))
        if missing:
            return Response(
                {"detail": f"Missing permission(s): {', '.join(missing)}."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        if "is_active" in sent and not user.is_active:
            revoke_all_refresh_tokens(user)
        return Response(UserSerializer(user, context={"request": request}).data)

    def delete(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if (denied := self._guard_superuser(request, user)) is not None:
            return denied
        user.is_active = False
        user.save(update_fields=["is_active"])
        # Deactivation must end the account's live sessions too, not only
        # block the next login.
        revoke_all_refresh_tokens(user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminResetPasswordView(APIView):
    """Admin issues a temporary password for any user.

    Best-effort emails the new password to the target user so they
    don't depend on the admin reading it out (template row
    `account.password_reset_by_admin.email` via the notifications layer).
    """

    permission_classes = [IsAuthenticated, HasPerm]
    # Its own key: handing out a temporary password for any account —
    # including a superuser's — is not an ordinary profile edit.
    required_perm = "accounts.user.reset_password"

    def post(self, request, pk):
        target = get_object_or_404(User, pk=pk)
        if (denied := UserDetailView._guard_superuser(request, target)) is not None:
            return denied
        serializer = AdminResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_pw = serializer.validated_data["new_password"]
        target.set_password(new_pw)
        target.save(update_fields=["password"])
        # Student accounts: keep the staff-visible copy on the student row.
        sync_portal_password(target, new_pw)
        record_password_reset(request, actor=request.user, target=target)
        # An admin reset is a compromise response as often as a favour:
        # end the account's existing sessions.
        revoke_all_refresh_tokens(target)

        delivery = {
            "delivered": False,
            "delivery_error": "",
            "recipient": (target.email or "").strip(),
        }
        # This mail ("JD ERP password") is
        # for STAFF only. Student / parent portal accounts get their login
        # via "Send portal credentials" on the student record instead.
        is_portal_account = (hasattr(target, "student")
                             or hasattr(target, "parent_of_student"))
        if is_portal_account:
            delivery["delivery_error"] = (
                "Password reset, but no email sent: this is a student/parent "
                "portal account. Use 'Send portal credentials' on the "
                "student record to email the login."
            )
        elif delivery["recipient"]:
            from apps.notifications.services import queue_notification
            from apps.notifications.models import NotificationDispatchLog
            base = getattr(
                dj_settings, "FRONTEND_BASE_URL", "http://localhost:5173",
            ).rstrip("/")
            from apps.notifications.context import user_vars

            log = queue_notification(
                template_key="account.password_reset_by_admin.email",
                recipient=delivery["recipient"],
                context={
                    **user_vars(target),
                    "Password": new_pw,
                    "Login_Url": base,
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

            # System e-mail `account.forgot_password.email` (wording
            # editable under Communication → System Emails).
            try:
                from apps.notifications.context import user_vars
                from apps.notifications.services import send_system_email

                send_system_email(
                    "account.forgot_password.email", recipient=email,
                    context={**user_vars(user), "Reset_Link": reset_url},
                    related=user,
                )
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
        sync_portal_password(user, new_pw)
        record_password_reset_completed(request, target=user)
        revoke_all_refresh_tokens(user)

        # Best-effort: tell the user their password just changed.
        if user.email:
            try:
                from apps.notifications.context import user_vars
                from apps.notifications.services import send_system_email

                send_system_email(
                    "account.password_changed.email", recipient=user.email,
                    context=user_vars(user), related=user,
                )
            except Exception:
                logger.exception("Failed to send password-changed notice to %s", user.email)

        return Response(status=status.HTTP_204_NO_CONTENT)
