from rest_framework import serializers

from .models import Permission, Role


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "key", "label", "module", "description"]
        read_only_fields = fields


class RoleSerializer(serializers.ModelSerializer):
    permission_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Permission.objects.all(),
        source="permissions", write_only=True, required=False,
    )
    permissions = PermissionSerializer(many=True, read_only=True)
    user_count = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "id", "name", "description", "is_system",
            "permissions", "permission_ids", "user_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "is_system", "created_at", "updated_at"]

    def validate_name(self, value):
        # System roles are looked up by name elsewhere; renaming one would
        # quietly detach it.
        if (self.instance is not None and self.instance.is_system
                and value != self.instance.name):
            raise serializers.ValidationError("System roles cannot be renamed.")
        return value

    def get_user_count(self, obj):
        return obj.users.count()
