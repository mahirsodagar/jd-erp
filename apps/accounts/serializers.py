from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.roles.models import Permission

User = get_user_model()


class TenantTokenObtainSerializer(serializers.Serializer):
    """Login serializer — accepts username or email in `identifier`.

    The `authenticate(request, ...)` call routes through django-axes so
    failed attempts increment the lockout counter.
    """

    identifier = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        request = self.context.get("request")
        user = authenticate(
            request=request,
            username=attrs["identifier"],
            password=attrs["password"],
        )
        if user is None:
            raise serializers.ValidationError({"detail": "Invalid credentials."})
        if not user.is_active:
            raise serializers.ValidationError({"detail": "Account disabled."})

        refresh = RefreshToken.for_user(user)
        attrs["user"] = user
        attrs["tokens"] = {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }
        return attrs


class UserSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    modules = serializers.SerializerMethodField()
    campuses = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    is_student = serializers.SerializerMethodField()
    is_parent = serializers.SerializerMethodField()
    is_employee = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "full_name",
            "is_active", "is_staff", "is_superuser",
            "is_student", "is_parent", "is_employee",
            "campuses",
            "date_joined", "last_login",
            "roles", "permissions", "modules",
        ]
        read_only_fields = [
            "id", "is_superuser", "date_joined", "last_login",
            "roles", "permissions", "modules",
            "campuses", "is_student", "is_parent", "is_employee",
        ]

    def get_roles(self, obj):
        return list(obj.roles.values_list("name", flat=True))

    def get_permissions(self, obj):
        # Superusers bypass per-permission gating (mirrors Django's
        # User.has_perm behavior). Send them the full catalogue so the
        # frontend can treat any check as satisfied.
        qs = Permission.objects.all() if obj.is_superuser else (
            Permission.objects.filter(roles__users=obj).distinct()
        )
        return list(qs.values_list("key", flat=True))

    def get_modules(self, obj):
        qs = Permission.objects.all() if obj.is_superuser else (
            Permission.objects.filter(roles__users=obj).distinct()
        )
        return sorted(set(qs.values_list("module", flat=True)))

    def get_is_student(self, obj):
        # Reverse OneToOne from admissions.Student.user_account
        return getattr(obj, "student", None) is not None

    def get_is_parent(self, obj):
        # Reverse FK from admissions.Student.parent_user_account
        from apps.admissions.models import Student
        return Student.objects.filter(parent_user_account=obj).exists()

    def get_is_employee(self, obj):
        # Reverse OneToOne from employees.Employee.user_account
        return getattr(obj, "employee", None) is not None


class UserCreateSerializer(serializers.ModelSerializer):
    temporary_password = serializers.CharField(write_only=True, min_length=8)
    role_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True,
    )
    campus_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True,
    )

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "full_name", "is_active", "is_staff",
            "temporary_password", "role_ids", "campus_ids",
        ]
        read_only_fields = ["id"]

    def create(self, validated_data):
        password = validated_data.pop("temporary_password")
        role_ids = validated_data.pop("role_ids", [])
        campus_ids = validated_data.pop("campus_ids", [])
        validate_password(password)
        user = User.objects.create_user(password=password, **validated_data)
        if role_ids:
            user.roles.set(role_ids)
        if campus_ids:
            user.campuses.set(campus_ids)
        return user


class MeUpdateSerializer(serializers.ModelSerializer):
    """Self-service profile edit — limited to the fields a user is
    allowed to change about themselves. Username, roles, campuses, and
    privilege flags stay admin-only."""

    class Meta:
        model = User
        fields = ["full_name", "email"]

    def validate_email(self, value):
        qs = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Another account already uses this email.",
            )
        return value


class UserUpdateSerializer(serializers.ModelSerializer):
    role_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True,
    )
    campus_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True,
    )

    class Meta:
        model = User
        fields = ["full_name", "email", "is_active", "is_staff",
                  "role_ids", "campus_ids"]

    def update(self, instance, validated_data):
        role_ids = validated_data.pop("role_ids", None)
        campus_ids = validated_data.pop("campus_ids", None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        if role_ids is not None:
            instance.roles.set(role_ids)
        if campus_ids is not None:
            instance.campuses.set(campus_ids)
        return instance


class AdminResetPasswordSerializer(serializers.Serializer):
    """Admin sets a new password for a user. The password is treated as
    'temporary' only by convention — there is no forced change-on-first-
    login flow per spec."""

    new_password = serializers.CharField(min_length=8)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class ChangePasswordSerializer(serializers.Serializer):
    """User changes their own password — must supply the current one."""

    current_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": "Incorrect."})
        validate_password(attrs["new_password"], user=user)
        return attrs


class ForgotPasswordSerializer(serializers.Serializer):
    """Anonymous: user supplies their email to start a reset."""

    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    """Anonymous: complete a reset with the (uid, token) emailed earlier.

    Validates the signed token via Django's `default_token_generator`,
    then sets the new password.
    """

    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8)

    def validate(self, attrs):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_str
        from django.utils.http import urlsafe_base64_decode

        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=int(user_id))
        except (ValueError, TypeError, OverflowError, User.DoesNotExist) as e:
            raise serializers.ValidationError(
                {"uid": "Invalid reset link."},
            ) from e

        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError(
                {"token": "Reset link is invalid or has expired."},
            )

        validate_password(attrs["new_password"], user=user)
        attrs["user"] = user
        return attrs
