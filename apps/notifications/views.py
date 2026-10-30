"""Bell endpoints. Every user sees only their own rows."""

from rest_framework import serializers, status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import InAppNotification

PAGE = 30


class InAppNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = InAppNotification
        fields = ["id", "kind", "title", "body", "link", "is_read", "created_at"]


class MyNotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = InAppNotification.objects.filter(recipient=request.user)
        return Response({
            "unread_count": qs.filter(is_read=False).count(),
            "results": InAppNotificationSerializer(qs[:PAGE], many=True).data,
        })


class MarkReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        updated = InAppNotification.objects.filter(
            pk=pk, recipient=request.user,
        ).update(is_read=True)
        if not updated:
            return Response(status=http.HTTP_404_NOT_FOUND)
        return Response(status=http.HTTP_204_NO_CONTENT)


class MarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        InAppNotification.objects.filter(
            recipient=request.user, is_read=False,
        ).update(is_read=True)
        return Response(status=http.HTTP_204_NO_CONTENT)
