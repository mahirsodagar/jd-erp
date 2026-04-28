from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPerm
from apps.audit.events import record_role_change

from .models import Permission, Role
from .serializers import PermissionSerializer, RoleSerializer


class PermissionListView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "roles.role.manage"

    def get(self, request):
        return Response(PermissionSerializer(Permission.objects.all(), many=True).data)


class RoleListCreateView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "roles.role.manage"

    def get(self, request):
        return Response(RoleSerializer(Role.objects.all(), many=True).data)

    def post(self, request):
        serializer = RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = serializer.save()
        record_role_change(request, action="create", role=role)
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "roles.role.manage"

    def get(self, request, pk):
        return Response(RoleSerializer(Role.objects.get(pk=pk)).data)

    def patch(self, request, pk):
        role = Role.objects.get(pk=pk)
        serializer = RoleSerializer(role, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        role = serializer.save()
        record_role_change(request, action="update", role=role)
        return Response(RoleSerializer(role).data)

    def delete(self, request, pk):
        role = Role.objects.get(pk=pk)
        if role.is_system:
            return Response(
                {"detail": "System roles cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_role_change(request, action="delete", role=role)
        role.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
