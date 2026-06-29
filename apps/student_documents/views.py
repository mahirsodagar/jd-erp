"""Staff-side document-request views. Student-side apply/list lives in
apps/portal."""

from django.http import Http404
from rest_framework import status as http
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import DocumentRequest
from .serializers import DecideDocumentSerializer, DocumentRequestSerializer


def _has_perm(user, key: str) -> bool:
    return user.is_authenticated and (
        user.is_superuser
        or user.roles.filter(permissions__key=key).exists()
    )


class DocumentRequestListView(APIView):
    """Staff: list document requests across the system."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_perm(request.user, "student_documents.view_all"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        qs = (DocumentRequest.objects
              .select_related("student", "decided_by"))
        if v := request.query_params.get("status"):
            qs = qs.filter(status=v)
        if v := request.query_params.get("doc_type"):
            qs = qs.filter(doc_type=v)
        if v := request.query_params.get("student"):
            qs = qs.filter(student_id=v)
        return Response(
            DocumentRequestSerializer(qs, many=True,
                                      context={"request": request}).data
        )


class DocumentRequestDecideView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        if not _has_perm(request.user, "student_documents.decide"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            obj = DocumentRequest.objects.select_related("student").get(pk=pk)
        except DocumentRequest.DoesNotExist as e:
            raise Http404 from e
        s = DecideDocumentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.decide_document(
                request_obj=obj,
                decision=s.validated_data["decision"],
                remarks=s.validated_data.get("remarks", ""),
                attachment=s.validated_data.get("attachment"),
                decided_by=request.user,
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(
            DocumentRequestSerializer(obj, context={"request": request}).data
        )
