from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

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

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "full_name",
            "is_active", "is_staff", "is_superuser",
            "date_joined", "last_login", "roles",
        ]
        read_only_fields = [
            "id", "is_superuser", "date_joined", "last_login", "roles",
        ]

    def get_roles(self, obj):
        return list(obj.roles.values_list("name", flat=True))


class UserCreateSerializer(serializers.ModelSerializer):
    temporary_password = serializers.CharField(write_only=True, min_length=8)
    role_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True,
    )

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "full_name", "is_active", "is_staff",
            "temporary_password", "role_ids",
        ]
        read_only_fields = ["id"]

    def create(self, validated_data):
        password = validated_data.pop("temporary_password")
        role_ids = validated_data.pop("role_ids", [])
        validate_password(password)
        user = User.objects.create_user(password=password, **validated_data)
        if role_ids:
            user.roles.set(role_ids)
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    role_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True,
    )

    class Meta:
        model = User
        fields = ["full_name", "email", "is_active", "is_staff", "role_ids"]

    def update(self, instance, validated_data):
        role_ids = validated_data.pop("role_ids", None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        if role_ids is not None:
            instance.roles.set(role_ids)
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
