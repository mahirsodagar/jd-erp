from django.db import transaction
from django.http import Http404
from rest_framework import status as http
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Enrollment, Student, StudentDocument, StudentRemark
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
    StudentRemarkSerializer,
    StudentSelfUpdateSerializer,
)
from .services import (
    can_enroll, graduate_batch, promote_batch,
    provision_student_portal_credentials,
)
from .services_handbook import send_handbook_email
from .services_portal_email import send_portal_credentials_email
from .services_undertaking import send_undertaking


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
                | Q(registration_number__icontains=q)
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
        if not has_perm(request.user, "admissions.document.add"):
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
            or has_perm(u, "admissions.document.delete")
            or is_self_student(u, doc.student)
        ):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        doc.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- Student remarks ---------------------------------------------------

class StudentRemarksView(APIView):
    """List + append free-form admin remarks on a student.

    Read access is gated by the standard student visibility policy; write
    access requires `admissions.student.edit`. Remarks are append-only —
    no PATCH/DELETE — so historical context isn't quietly rewritten.
    """

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
        qs = student.remarks.select_related("created_by").all()
        return Response(StudentRemarkSerializer(qs, many=True).data)

    def post(self, request, pk):
        student = self._student(request, pk)
        if not has_perm(request.user, "admissions.student.edit"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = StudentRemarkSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(student=student, created_by=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


# --- Enrollments -------------------------------------------------------

class EnrollmentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not (u.is_superuser or has_perm(u, "admissions.student.view")):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        qs = Enrollment.objects.select_related(
            "student", "program", "semester",
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
        if not has_perm(request.user, "admissions.enrollment.add"):
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
        if not has_perm(request.user, "admissions.enrollment.edit"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        obj = self._obj(pk)
        s = EnrollmentSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)


class EnrollmentUndertakingView(APIView):
    """POST /api/admissions/enrollments/{pk}/undertaking/

    Renders the fee undertaking PDF from the enrollment + installments
    + approved concession, emails it to the student with the requesting
    user CC'd. The PDF is not persisted.

    Body (all optional):
        remarks: str
        application_form: str   # defaults to student.application_form_id
        extra_cc: [str]         # additional CC addresses
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            enrollment = Enrollment.objects.select_related(
                "student", "campus", "program", "course",
                "student__institute",
            ).get(pk=pk)
        except Enrollment.DoesNotExist as e:
            raise Http404 from e

        u = request.user
        if not (u.is_superuser or has_perm(u, "admissions.student.view")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if not can_view_all_campuses(u) and not u.campuses.filter(
            pk=enrollment.campus_id,
        ).exists():
            raise Http404

        remarks = (request.data.get("remarks") or "").strip()
        application_form = (request.data.get("application_form") or "").strip()
        extra_cc = request.data.get("extra_cc") or []
        if isinstance(extra_cc, str):
            extra_cc = [s.strip() for s in extra_cc.split(",") if s.strip()]

        try:
            result = send_undertaking(
                enrollment,
                requested_by=u,
                remarks=remarks,
                application_form=application_form,
                extra_cc=extra_cc,
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        except RuntimeError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_502_BAD_GATEWAY)
        return Response(result)


# --- Portal credentials + handbook -------------------------------------

class StudentSendPortalCredentialsView(APIView):
    """Single-button "send portal credentials" action.

    On each call we:
      1. Provision the portal user if missing (set `Student.user_account`).
      2. Generate a personalised institute email from the Institute's
         `email_domain` master.
      3. Rotate the user's password so the email reflects current state.
      4. Email the (institute_email, password) pair to the student's
         personal email.

    Returns the username, email, and the just-issued temporary password
    so the calling counsellor can show it on screen too (matching the
    PHP "show once" pattern).

    Gated on the student having at least one Enrollment — per the
    revised admission flow.
    """

    permission_classes = [IsAuthenticated, StudentAccessPolicy]

    def post(self, request, pk):
        try:
            student = Student.objects.select_related(
                "institute", "campus",
            ).get(pk=pk)
        except Student.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, student)
        if not has_perm(request.user, "admissions.student.edit"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        if not Enrollment.objects.filter(student=student).exists():
            return Response(
                {"detail": "Enroll the student into a batch first."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        try:
            creds = provision_student_portal_credentials(student=student)
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)

        # Best-effort delivery: don't block the staff response on SMTP.
        email_ok, email_err = send_portal_credentials_email(
            student=student, creds=creds,
        )

        return Response({
            **creds,
            "delivered": email_ok,
            "delivery_error": "" if email_ok else email_err,
            "recipient": student.student_email or "",
        })


class StudentSendHandbookView(APIView):
    """Emails the institute's student handbook to the student's personal
    inbox. Plain-text body for now — attach the actual PDF later by
    storing it on the Institute master."""

    permission_classes = [IsAuthenticated, StudentAccessPolicy]

    def post(self, request, pk):
        try:
            student = Student.objects.select_related(
                "institute",
            ).get(pk=pk)
        except Student.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, student)
        if not has_perm(request.user, "admissions.student.edit"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        if not Enrollment.objects.filter(student=student).exists():
            return Response(
                {"detail": "Enroll the student into a batch first."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        email_ok, email_err = send_handbook_email(student=student)
        return Response({
            "delivered": email_ok,
            "delivery_error": "" if email_ok else email_err,
            "recipient": student.student_email or "",
        })


# --- Batch promotion + bulk graduation ---------------------------------

class BatchPromoteView(APIView):
    """POST /api/admissions/batch-promote/

    Body:
        source_batch: int
        source_semester: int
        target_batch: int
        target_semester: int
        target_academic_year: int
        student_ids: list[int] | null   # null = whole batch
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        u = request.user
        if not (u.is_superuser
                or has_perm(u, "admissions.enrollment.edit")
                or has_perm(u, "admissions.student.promote")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        from apps.master.models import AcademicYear, Batch, Semester

        try:
            source_batch = Batch.objects.get(pk=request.data.get("source_batch"))
            source_semester = Semester.objects.get(
                pk=request.data.get("source_semester"),
            )
            target_batch = Batch.objects.get(pk=request.data.get("target_batch"))
            target_semester = Semester.objects.get(
                pk=request.data.get("target_semester"),
            )
            target_year = AcademicYear.objects.get(
                pk=request.data.get("target_academic_year"),
            )
        except (Batch.DoesNotExist, Semester.DoesNotExist,
                AcademicYear.DoesNotExist):
            return Response(
                {"detail": "Source / target batch / semester / academic year "
                           "not found."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        # Campus scope — block users from promoting students out of
        # campuses they can't see.
        if not can_view_all_campuses(u):
            campuses = set(u.campuses.values_list("pk", flat=True))
            if source_batch.campus_id not in campuses \
                    or target_batch.campus_id not in campuses:
                return Response(
                    {"detail": "Source or target campus is out of scope."},
                    status=http.HTTP_403_FORBIDDEN,
                )

        raw_ids = request.data.get("student_ids")
        student_ids = None
        if raw_ids is not None:
            try:
                student_ids = [int(v) for v in raw_ids]
            except (TypeError, ValueError):
                return Response({"student_ids": "Must be a list of integers."},
                                status=http.HTTP_400_BAD_REQUEST)

        try:
            result = promote_batch(
                source_batch=source_batch,
                source_semester=source_semester,
                target_batch=target_batch,
                target_semester=target_semester,
                target_academic_year=target_year,
                student_ids=student_ids,
                actor=u,
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(result)


class BatchGraduateView(APIView):
    """POST /api/admissions/batch-graduate/

    Mark every ACTIVE enrollment in a batch (optionally one semester)
    as ALUMNI, creating an AlumniRecord per student.

    Body:
        batch: int
        semester: int | null
        student_ids: list[int] | null
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        u = request.user
        if not (u.is_superuser
                or has_perm(u, "admissions.enrollment.edit")
                or has_perm(u, "academics.certificate.issue")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        from apps.master.models import Batch, Semester

        try:
            batch = Batch.objects.get(pk=request.data.get("batch"))
        except Batch.DoesNotExist:
            return Response({"batch": "Required and must exist."},
                            status=http.HTTP_400_BAD_REQUEST)

        semester = None
        if request.data.get("semester") is not None:
            try:
                semester = Semester.objects.get(pk=request.data["semester"])
            except Semester.DoesNotExist:
                return Response({"semester": "Not found."},
                                status=http.HTTP_400_BAD_REQUEST)

        if not can_view_all_campuses(u) \
                and not u.campuses.filter(pk=batch.campus_id).exists():
            return Response({"detail": "Batch campus is out of scope."},
                            status=http.HTTP_403_FORBIDDEN)

        raw_ids = request.data.get("student_ids")
        student_ids = None
        if raw_ids is not None:
            try:
                student_ids = [int(v) for v in raw_ids]
            except (TypeError, ValueError):
                return Response({"student_ids": "Must be a list of integers."},
                                status=http.HTTP_400_BAD_REQUEST)

        result = graduate_batch(
            batch=batch, semester=semester,
            student_ids=student_ids, actor=u,
        )
        return Response(result)
