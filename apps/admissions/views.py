from django.db import transaction
from django.http import Http404, HttpResponse
from rest_framework import status as http
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.csv_export import csv_response, fmt_date, wants_csv

from .models import Enrollment, Student, StudentDocument, StudentRemark
from .permissions import (
    StudentAccessPolicy, can_view_all_campuses, filter_visible,
    has_perm, is_self_student,
)
from .serializers import (
    BatchTransferSerializer,
    EnrollmentSerializer,
    StudentDetailSerializer,
    StudentDocumentSerializer,
    StudentHRUpdateSerializer,
    StudentListSerializer,
    StudentRemarkSerializer,
    StudentSelfUpdateSerializer,
    StudentStatusChangeInputSerializer,
    StudentStatusChangeSerializer,
)
from .services import (
    LIVE_STATUSES, StatusChangeError, can_enroll, drop_out_student,
    graduate_batch, promote_batch, reactivate_student,
    provision_student_portal_credentials,
    sync_student_placement_from_enrollment, transfer_enrollment,
)
from .services_handbook import send_handbook_email
from .services_portal_email import send_portal_credentials_email
from .services_undertaking import render_undertaking_pdf, send_undertaking


# --- HR-facing student endpoints ---------------------------------------

def _dropout_annotation():
    from django.db.models import Exists, OuterRef
    rows = Enrollment.objects.filter(student=OuterRef("pk"))
    return (
        Exists(rows.filter(status=Enrollment.Status.DROPPED))
        & ~Exists(rows.filter(status__in=LIVE_STATUSES))
    )


_DROPOUT_ANNOTATION = _dropout_annotation()


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
        # Legacy Student Search filtered by batch. Batch lives on the
        # enrollment; any enrollment in it counts (a batch keeps its
        # students across semesters).
        if v := params.get("batch"):
            from django.db.models import Exists, OuterRef
            qs = qs.filter(Exists(Enrollment.objects.filter(
                student=OuterRef("pk"), batch_id=v,
            )))
        qs = qs.annotate(is_dropout=_DROPOUT_ANNOTATION)
        # Legacy Student Data report filtered Active / Dropout.
        if (v := params.get("status")) == "dropout":
            qs = qs.filter(is_dropout=True)
        elif v == "active":
            qs = qs.filter(is_dropout=False)
        if q := params.get("search"):
            from django.db.models import Q
            qs = qs.filter(
                Q(student_name__icontains=q)
                | Q(application_form_id__icontains=q)
                | Q(registration_number__icontains=q)
                | Q(student_email__icontains=q)
                | Q(student_mobile__icontains=q)
            )
        if wants_csv(request):
            return self._csv(qs, request.user)
        return Response(StudentListSerializer(qs[:500], many=True).data)

    # Legacy JD_ERP "Student Data.csv". Columns marked sensitive are
    # dropped unless the user may see them — the same rule as
    # StudentDetailSerializer.SENSITIVE_FIELDS.
    _CSV_COLUMNS = (
        ("Student ID", False, lambda s: s.application_form_id),
        ("Registration No", False, lambda s: s.registration_number),
        ("Name", False, lambda s: s.student_name),
        ("Status", False, lambda s: "Dropout" if s.is_dropout else "Active"),
        ("Email", False, lambda s: s.student_email),
        ("Institute Mail", False, lambda s: s.institute_email),
        ("Phone No", False, lambda s: s.student_mobile),
        ("DOB", True, lambda s: fmt_date(s.dob)),
        ("Nationality", True, lambda s: s.get_nationality_display()),
        ("Blood Group", True, lambda s: s.get_blood_group_display()),
        ("Gender", True, lambda s: s.get_gender_display()),
        ("Category", True, lambda s: s.get_category_display()),
        ("Institute", False, lambda s: s.institute.name),
        ("Program", False, lambda s: s.program.name),
        ("Course", False, lambda s: s.course.name if s.course else ""),
        ("Campus", False, lambda s: s.campus.name),
        ("Academic Year", False, lambda s: s.academic_year.code),
        ("Current Address", True, lambda s: s.current_address),
        ("Current State", True,
         lambda s: s.current_state.name if s.current_state else ""),
        ("Current City", True,
         lambda s: s.current_city.name if s.current_city else ""),
        ("Current Pincode", True, lambda s: s.current_pincode),
        ("Permanent Address", True, lambda s: s.permanent_address),
        ("Permanent State", True,
         lambda s: s.permanent_state.name if s.permanent_state else ""),
        ("Permanent City", True,
         lambda s: s.permanent_city.name if s.permanent_city else ""),
        ("Permanent Pincode", True, lambda s: s.permanent_pincode),
        ("Father Name", True, lambda s: s.father_name),
        ("Father No.", True, lambda s: s.father_mobile),
        ("Father Email", True, lambda s: s.father_email),
        ("Mother Name", True, lambda s: s.mother_name),
        ("Mother No.", True, lambda s: s.mother_mobile),
        ("Mother Email", True, lambda s: s.mother_email),
        ("Created On", False, lambda s: fmt_date(s.created_on)),
        ("Created By", False,
         lambda s: s.created_by.username if s.created_by else ""),
    )

    def _csv(self, qs, user):
        sensitive = has_perm(user, "admissions.student.view_sensitive")
        cols = [c for c in self._CSV_COLUMNS if sensitive or not c[1]]
        qs = qs.select_related(
            "course", "created_by", "current_state", "current_city",
            "permanent_state", "permanent_city",
        )
        return csv_response(
            "Student Data.csv",
            ["SL NO", *(c[0] for c in cols)],
            ([i, *(c[2](s) for c in cols)]
             for i, s in enumerate(qs.iterator(), start=1)),
        )


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

    # Fields that move a student between academic units. Editing a
    # phone number and transferring a student to another institute used
    # to be the same permission; these are carved out.
    TRANSFER_FIELDS = frozenset({
        "institute", "campus", "program", "course", "academic_year",
    })

    #: Fields compared as FK ids rather than as model instances.
    _GATED_FK = TRANSFER_FIELDS

    @classmethod
    def _changed_fields(cls, student, data) -> set:
        """Keys in `data` whose value differs from what's stored."""
        changed = set()
        for key in data:
            if key in cls._GATED_FK:
                current = getattr(student, f"{key}_id", None)
                incoming = data.get(key)
                incoming = None if incoming in ("", None) else int(incoming)
            elif key == "registration_number":
                current = student.registration_number or ""
                incoming = (data.get(key) or "").strip()
            else:
                continue
            if current != incoming:
                changed.add(key)
        return changed

    def patch(self, request, pk):
        student = self._obj(request, pk)
        if not has_perm(request.user, "admissions.student.edit"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)

        # The edit form PATCHes the whole record, so gate on fields that
        # actually change rather than on their mere presence — otherwise
        # correcting a phone number would trip the transfer check.
        changed = self._changed_fields(student, request.data)
        if (changed & self.TRANSFER_FIELDS) and not has_perm(
            request.user, "admissions.student.transfer",
        ):
            return Response(
                {"detail": "You cannot transfer a student to another "
                           "institute, campus, program or course."},
                status=http.HTTP_403_FORBIDDEN,
            )
        if "registration_number" in changed and not has_perm(
            request.user, "admissions.student.set_registration_no",
        ):
            return Response(
                {"detail": "You cannot set the registration number."},
                status=http.HTTP_403_FORBIDDEN,
            )

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
        if not has_perm(request.user, "admissions.document.view"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
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
        if not has_perm(request.user, "admissions.student.view_remarks"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        qs = student.remarks.select_related("created_by").all()
        return Response(StudentRemarkSerializer(qs, many=True).data)

    def post(self, request, pk):
        student = self._student(request, pk)
        if not has_perm(request.user, "admissions.student.add_remark"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = StudentRemarkSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(student=student, created_by=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


class _StudentStatusChangeBase(APIView):
    """Drop Out / Re-activate (legacy Student Search → Actions → Drop
    Out, includes/save.php:1208). Remarks are mandatory."""

    permission_classes = [IsAuthenticated, StudentAccessPolicy]
    required_perm = ""
    service = None

    def post(self, request, pk):
        try:
            student = Student.objects.get(pk=pk)
        except Student.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, student)
        if not has_perm(request.user, self.required_perm):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = StudentStatusChangeInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            change = type(self).service(
                student=student, remarks=s.validated_data["remarks"],
                by=request.user,
            )
        except StatusChangeError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(StudentStatusChangeSerializer(change).data,
                        status=http.HTTP_201_CREATED)


class StudentDropoutView(_StudentStatusChangeBase):
    required_perm = "admissions.student.dropout"
    service = staticmethod(drop_out_student)


class StudentReactivateView(_StudentStatusChangeBase):
    required_perm = "admissions.student.reactivate"
    service = staticmethod(reactivate_student)


class StudentStatusHistoryView(APIView):
    permission_classes = [IsAuthenticated, StudentAccessPolicy]

    def get(self, request, pk):
        try:
            student = Student.objects.get(pk=pk)
        except Student.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, student)
        qs = student.status_changes.select_related("created_by")
        return Response(StudentStatusChangeSerializer(qs, many=True).data)


# --- Enrollments -------------------------------------------------------

class EnrollmentListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not has_perm(u, "admissions.enrollment.view"):
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
        with transaction.atomic():
            s.save(entry_user=request.user)
            # Enrolling into a different program than the one applied for
            # is allowed and common; the student profile has to follow it.
            sync_student_placement_from_enrollment(student, actor=request.user)
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
        if not has_perm(u, "admissions.enrollment.view"):
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
        with transaction.atomic():
            s.save()
            sync_student_placement_from_enrollment(obj.student, actor=request.user)
        return Response(s.data)


class _UndertakingMixin:
    """Shared lookup for the two undertaking endpoints.

    Downloading and emailing are the same document under the same
    permission — a counsellor who may send it to the student may
    certainly print it — so both go through this.
    """

    permission_classes = [IsAuthenticated]

    def _enrollment(self, request, pk) -> Enrollment:
        try:
            enrollment = Enrollment.objects.select_related(
                "student", "campus", "program", "course",
                "student__institute",
            ).get(pk=pk)
        except Enrollment.DoesNotExist as e:
            raise Http404 from e

        u = request.user
        if not has_perm(u, "admissions.enrollment.send_undertaking"):
            raise PermissionDenied("Permission denied.")
        if not can_view_all_campuses(u) and not u.campuses.filter(
            pk=enrollment.campus_id,
        ).exists():
            raise Http404
        return enrollment


class EnrollmentUndertakingPdfView(_UndertakingMixin, APIView):
    """GET /api/admissions/enrollments/{pk}/undertaking/pdf/

    The undertaking as a file, for printing or handing over in person.
    `remarks` rides in as a query parameter so what the counsellor typed
    on screen prints in the REMARKS row, exactly as it would in the
    emailed copy.
    """

    def get(self, request, pk):
        enrollment = self._enrollment(request, pk)
        pdf = render_undertaking_pdf(
            enrollment,
            remarks=(request.query_params.get("remarks") or "").strip(),
            submitted_by=(
                getattr(request.user, "full_name", "")
                or getattr(request.user, "username", "")
                or ""
            ),
        )
        resp = HttpResponse(pdf, content_type="application/pdf")
        name = enrollment.student.application_form_id or enrollment.id
        resp["Content-Disposition"] = f'inline; filename="undertaking-{name}.pdf"'
        return resp


class EnrollmentUndertakingView(_UndertakingMixin, APIView):
    """POST /api/admissions/enrollments/{pk}/undertaking/

    Renders the fee undertaking PDF from the enrollment + installments
    + approved concession, emails it to the student with the requesting
    user CC'd. The PDF is not persisted.

    Body (all optional):
        remarks: str
        extra_cc: [str]         # additional CC addresses
    """

    def post(self, request, pk):
        enrollment = self._enrollment(request, pk)
        u = request.user

        remarks = (request.data.get("remarks") or "").strip()
        extra_cc = request.data.get("extra_cc") or []
        if isinstance(extra_cc, str):
            extra_cc = [s.strip() for s in extra_cc.split(",") if s.strip()]

        try:
            result = send_undertaking(
                enrollment,
                requested_by=u,
                remarks=remarks,
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
        if not has_perm(request.user, "admissions.student.send_credentials"):
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
        if not has_perm(request.user, "admissions.student.send_handbook"):
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
        if not has_perm(u, "admissions.student.promote"):
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


class BatchTransferView(APIView):
    """GET  /api/admissions/batch-transfer/?student=<id>
        Transfer history, newest first (optionally one student's).
    POST /api/admissions/batch-transfer/

    Body:
        enrollment: int              # the live enrolment being moved
        target_batch: int
        target_semester: int
        target_academic_year: int
        remarks: str
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not has_perm(u, "admissions.student.transfer"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        from .models import BatchTransfer

        qs = BatchTransfer.objects.select_related(
            "student", "created_by",
            "from_batch", "from_program", "from_campus", "from_semester",
            "from_academic_year",
            "to_batch", "to_program", "to_campus", "to_semester",
            "to_academic_year",
        )
        student = request.query_params.get("student")
        if student:
            qs = qs.filter(student_id=student)
        if not can_view_all_campuses(u):
            from django.db.models import Q
            campuses = list(u.campuses.values_list("pk", flat=True))
            qs = qs.filter(Q(from_campus_id__in=campuses)
                           | Q(to_campus_id__in=campuses))
        return Response(BatchTransferSerializer(qs[:200], many=True).data)

    def post(self, request):
        u = request.user
        if not has_perm(u, "admissions.student.transfer"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        from apps.master.models import AcademicYear, Batch, Semester

        try:
            enrollment = Enrollment.objects.select_related(
                "student", "batch", "program", "campus", "semester",
                "academic_year", "course",
            ).get(pk=request.data.get("enrollment"))
            target_batch = Batch.objects.select_related(
                "program", "campus",
            ).get(pk=request.data.get("target_batch"))
            target_semester = Semester.objects.get(
                pk=request.data.get("target_semester"),
            )
            target_year = AcademicYear.objects.get(
                pk=request.data.get("target_academic_year"),
            )
        except (Enrollment.DoesNotExist, Batch.DoesNotExist,
                Semester.DoesNotExist, AcademicYear.DoesNotExist,
                ValueError, TypeError):
            return Response(
                {"detail": "Enrolment / target batch / semester / academic "
                           "year not found."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        # Campus scope — both ends must be campuses the user can see.
        if not can_view_all_campuses(u):
            campuses = set(u.campuses.values_list("pk", flat=True))
            if enrollment.campus_id not in campuses \
                    or target_batch.campus_id not in campuses:
                return Response(
                    {"detail": "Current or target campus is out of scope."},
                    status=http.HTTP_403_FORBIDDEN,
                )

        try:
            transfer = transfer_enrollment(
                enrollment=enrollment,
                target_batch=target_batch,
                target_semester=target_semester,
                target_academic_year=target_year,
                remarks=request.data.get("remarks") or "",
                actor=u,
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(BatchTransferSerializer(transfer).data,
                        status=http.HTTP_201_CREATED)


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
        # Graduating mints alumni records — neither an enrolment edit
        # nor a certificate issue, so it has its own key. The
        # per-enrolment endpoint (`EnrollmentGraduateView`) uses the
        # same one.
        u = request.user
        if not has_perm(u, "academics.certificate.graduate"):
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
