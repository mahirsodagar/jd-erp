from auditlog.models import LogEntry
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AuthLog
from .permissions import IsSuperuser
from .serializers import AuthLogSerializer, DataAuditSerializer


class AuthLogListView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request):
        qs = AuthLog.objects.all()
        event = request.query_params.get("event")
        if event:
            qs = qs.filter(event=event)
        actor = request.query_params.get("actor")
        if actor:
            qs = qs.filter(actor_id=actor)
        return Response(AuthLogSerializer(qs[:500], many=True).data)


class DataAuditListView(APIView):
    permission_classes = [IsAuthenticated, IsSuperuser]

    def get(self, request):
        qs = LogEntry.objects.select_related("content_type", "actor").order_by("-timestamp")
        model = request.query_params.get("model")  # e.g. accounts.user
        if model:
            try:
                app_label, model_name = model.split(".", 1)
                qs = qs.filter(
                    content_type__app_label=app_label,
                    content_type__model=model_name,
                )
            except ValueError:
                pass
        return Response(DataAuditSerializer(qs[:500], many=True).data)
