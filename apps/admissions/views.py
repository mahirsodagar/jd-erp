from django.db import transaction
from django.http import Http404
from rest_framework import status as http
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Enrollment, Student, StudentDocument
from .permissions import (
    StudentAccessPolicy, can_view_all_campuses, filter_visible,
    has_perm, is_self_student,
)
from .serializers import (
    EnrollmentSerializer,
    StudentDetailSerializer,
    StudentDocumentSerializer,
    StudentHRUpdateSerializer,
    StudentListSerializer,
    StudentSelfUpdateSerializer,
)
from .services import can_enroll


# --- HR-facing student endpoints ---------------------------------------

class StudentListView(APIView):
    permission_classes = [IsAuthenticated, StudentAccessPolicy]

    def get(self, request):
        qs = Student.objects.select_related(
            "campus", "program", "academic_year", "institute",
        )
        qs = filter_visible(qs, request.user)
        params = request.query_params
        if v := params.get("campus"):
            qs = qs.filter(campus_id=v)
        if v := params.get("program"):
            qs = qs.filter(program_id=v)
        if v := params.get("academic_year"):
            qs = qs.filter(academic_year_id=v)
        if q := params.get("search"):
            from django.db.models import Q
            qs = qs.filter(
                Q(student_name__icontains=q)
                | Q(application_form_id__icontains=q)
                | Q(student_email__icontains=q)
                | Q(student_mobile__icontains=q)
            )
        return Response(StudentListSerializer(qs[:500], many=True).data)


class StudentDetailView(APIView):
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    permission_classes = [IsAuthenticated, StudentAccessPolicy]

    def _obj(self, request, pk):
        try:
            student = Student.objects.get(pk=pk)
        except Student.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, student)
        return student

    def get(self, request, pk):
        return Response(StudentDetailSerializer(
            self._obj(request, pk), context={"request": request}
        ).data)

    def patch(self, request, pk):
        student = self._obj(request, pk)
        if not has_perm(request.user, "admissions.student.edit"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = StudentHRUpdateSerializer(student, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save(updated_by=request.user)
        return Response(StudentDetailSerializer(student, context={"request": request}).data)


# --- Student self-service ("my" panel) ---------------------------------

class StudentMeView(APIView):
    """Endpoints used by the student panel — the student edits their
    own record without HR permission."""
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    permission_classes = [IsAuthenticated]

    def _self(self, request):
        student = getattr(request.user, "student", None)
        if student is None:
            raise Http404("No student record linked to this user.")
        return student

    def get(self, request):
        return Response(StudentDetailSerializer(
            self._self(request), context={"request": request}
        ).data)

    def patch(self, request):
        student = self._self(request)
        s = StudentSelfUpdateSerializer(student, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save(updated_by=request.user)
        return Response(StudentDetailSerializer(
            student, context={"request": request}
        ).data)


class StudentMeDocumentsView(APIView):
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    permission_classes = [IsAuthenticated]

    def _self(self, request):
        student = getattr(request.user, "student", None)
        if student is None:
            raise Http404("No student record linked to this user.")
        return student

    def get(self, request):
        student = self._self(request)
        return Response(StudentDocumentSerializer(student.documents.all(), many=True).data)

    def post(self, request):
        student = self._self(request)
        s = StudentDocumentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(uploaded_by=request.user, student=student)
        return Response(s.data, status=http.HTTP_201_CREATED)


# --- HR document management --------------------------------------------

class StudentDocumentsView(APIView):
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    permission_classes = [IsAuthenticated, StudentAccessPolicy]

    def _student(self, request, pk):
        try:
            s = Student.objects.get(pk=pk)
        except Student.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, s)
        return s

    def get(self, request, pk):
        student = self._student(request, pk)
        return Response(StudentDocumentSerializer(student.documents.all(), many=True).data)

    def post(self, request, pk):
        student = self._student(request, pk)
        if not has_perm(request.user, "admissions.document.manage"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = StudentDocumentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(uploaded_by=request.user, student=student)
        return Response(s.data, status=http.HTTP_201_CREATED)


class StudentDocumentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            doc = StudentDocument.objects.select_related("student").get(pk=pk)
        except StudentDocument.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        if not (
            u.is_superuser
            or has_perm(u, "admissions.document.manage")
            or is_self_student(u, doc.student)
        ):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        doc.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- Enrollments -------------------------------------------------------

class EnrollmentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not (u.is_superuser or has_perm(u, "admissions.student.view")):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        qs = Enrollment.objects.select_related(
            "student", "program", "course", "semester",
            "campus", "batch", "academic_year",
        )
        if not can_view_all_campuses(u):
            qs = qs.filter(campus__in=u.campuses.all())
        params = request.query_params
        if v := params.get("student"):
            qs = qs.filter(student_id=v)
        if v := params.get("batch"):
            qs = qs.filter(batch_id=v)
        if v := params.get("academic_year"):
            qs = qs.filter(academic_year_id=v)
        if v := params.get("status"):
            qs = qs.filter(status=v)
        return Response(EnrollmentSerializer(qs[:500], many=True).data)

    def post(self, request):
        if not has_perm(request.user, "admissions.enrollment.manage"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = EnrollmentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        student = s.validated_data["student"]
        ok, msg = can_enroll(student)
        if not ok:
            return Response({"detail": msg}, status=http.HTTP_400_BAD_REQUEST)
        s.save(entry_user=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


class EnrollmentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return Enrollment.objects.get(pk=pk)
        except Enrollment.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (u.is_superuser or has_perm(u, "admissions.student.view")):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        if not can_view_all_campuses(u) and not u.campuses.filter(pk=obj.campus_id).exists():
            raise Http404
        return Response(EnrollmentSerializer(obj).data)

    def patch(self, request, pk):
        if not has_perm(request.user, "admissions.enrollment.manage"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        obj = self._obj(pk)
        s = EnrollmentSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)
