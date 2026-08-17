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
    """Staff: list document requests, scoped to the caller's campuses
    unless they hold `student_documents.view_all`."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        all_campuses = _has_perm(u, "student_documents.view_all")
        if not (all_campuses or _has_perm(u, "student_documents.view")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        qs = (DocumentRequest.objects
              .select_related("student", "decided_by"))
        if not all_campuses:
            qs = qs.filter(student__campus__in=u.campuses.all())
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
        try:
            obj = DocumentRequest.objects.select_related(
                "student").get(pk=pk)
        except DocumentRequest.DoesNotExist as e:
            raise Http404 from e

        s = DecideDocumentSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        u = request.user
        needed = (
            "student_documents.approve"
            if s.validated_data["decision"] == DocumentRequest.Status.APPROVED
            else "student_documents.reject"
        )
        if not _has_perm(u, needed):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        # Same campus scope as the list — otherwise a request you could
        # never see could still be decided by id.
        if not (_has_perm(u, "student_documents.view_all")
                or u.campuses.filter(pk=obj.student.campus_id).exists()):
            return Response(
                {"detail": "This request is outside your campus scope."},
                status=http.HTTP_403_FORBIDDEN,
            )

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
