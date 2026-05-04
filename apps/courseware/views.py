"""Staff-side courseware CRUD. Student-side reads live in apps/portal."""

from django.http import Http404
from rest_framework import status as http
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.models import Batch, Subject

from . import services
from .models import CoursewareAttachment, CoursewareTopic
from .permissions import has_perm
from .serializers import (
    CoursewareAttachmentSerializer, CoursewareTopicSerializer,
    PublishTopicSerializer,
)


def _can_manage(user) -> bool:
    return user.is_superuser or has_perm(user, "courseware.manage")


class CoursewareTopicListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        if not _can_manage(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        qs = (CoursewareTopic.objects
              .select_related("subject", "batch")
              .prefetch_related("attachments"))
        if v := request.query_params.get("subject"):
            qs = qs.filter(subject_id=v)
        if v := request.query_params.get("batch"):
            qs = qs.filter(batch_id=v)
        return Response(CoursewareTopicSerializer(
            qs, many=True, context={"request": request},
        ).data)

    def post(self, request):
        if not _can_manage(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = PublishTopicSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            subject = Subject.objects.get(pk=d["subject"])
            batch = Batch.objects.get(pk=d["batch"])
        except (Subject.DoesNotExist, Batch.DoesNotExist):
            return Response({"detail": "Subject or batch not found."},
                            status=http.HTTP_400_BAD_REQUEST)
        files = d.get("attachments", [])
        names = d.get("attachment_names", [])
        attachments = [
            {"name": names[i] if i < len(names) else f.name, "file": f}
            for i, f in enumerate(files)
        ]
        topic = services.publish_topic(
            subject=subject, batch=batch,
            name=d["name"], description=d.get("description", ""),
            attachments=attachments, created_by=request.user,
        )
        return Response(
            CoursewareTopicSerializer(topic, context={"request": request}).data,
            status=http.HTTP_201_CREATED,
        )


class CoursewareTopicDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, pk):
        if not _can_manage(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            topic = (CoursewareTopic.objects
                     .select_related("subject", "batch")
                     .prefetch_related("attachments")
                     .get(pk=pk))
        except CoursewareTopic.DoesNotExist as e:
            raise Http404 from e
        return Response(CoursewareTopicSerializer(
            topic, context={"request": request},
        ).data)

    def patch(self, request, pk):
        if not _can_manage(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            topic = CoursewareTopic.objects.get(pk=pk)
        except CoursewareTopic.DoesNotExist as e:
            raise Http404 from e
        for f in ("name", "description", "is_published"):
            if f in request.data:
                setattr(topic, f, request.data[f])
        topic.save()
        return Response(CoursewareTopicSerializer(
            topic, context={"request": request},
        ).data)

    def delete(self, request, pk):
        if not _can_manage(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            topic = CoursewareTopic.objects.get(pk=pk)
        except CoursewareTopic.DoesNotExist as e:
            raise Http404 from e
        topic.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


class CoursewareAttachmentAddView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        if not _can_manage(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            topic = CoursewareTopic.objects.get(pk=pk)
        except CoursewareTopic.DoesNotExist as e:
            raise Http404 from e
        file = request.FILES.get("file")
        if not file:
            return Response({"file": "Required."},
                            status=http.HTTP_400_BAD_REQUEST)
        att = CoursewareAttachment.objects.create(
            topic=topic, name=request.data.get("name", file.name),
            file=file, uploaded_by=request.user,
        )
        return Response(
            CoursewareAttachmentSerializer(att, context={"request": request}).data,
            status=http.HTTP_201_CREATED,
        )


class CoursewareAttachmentDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        if not _can_manage(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            att = CoursewareAttachment.objects.get(pk=pk)
        except CoursewareAttachment.DoesNotExist as e:
            raise Http404 from e
        att.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)
