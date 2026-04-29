from datetime import date as _date

from django.db import transaction
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admissions.models import Enrollment

from .models import Concession, FeeReceipt, Installment
from .permissions import (
    FeeAccessPolicy, can_view_all, has_perm, visible_enrollments_filter,
)
from .serializers import (
    CancelReceiptSerializer,
    ConcessionDecisionSerializer,
    ConcessionDetailSerializer,
    ConcessionRequestSerializer,
    FeeReceiptCreateSerializer,
    FeeReceiptDetailSerializer,
    FeeReceiptUpdateSerializer,
    InstallmentSerializer,
)
from .services.balance import enrollment_balance
from .services.pdf import render_receipt_pdf
from .services.receipt_no import generate_receipt_no


# --- Installments ------------------------------------------------------

class InstallmentListCreateView(APIView):
    permission_classes = [IsAuthenticated, FeeAccessPolicy]

    def get(self, request):
        qs = Installment.objects.select_related("enrollment", "enrollment__student")
        qs = visible_enrollments_filter(qs, request.user)
        if v := request.query_params.get("enrollment"):
            qs = qs.filter(enrollment_id=v)
        return Response(InstallmentSerializer(qs[:500], many=True).data)

    def post(self, request):
        if not has_perm(request.user, "fees.installment.manage"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = InstallmentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(created_by=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


class InstallmentDetailView(APIView):
    permission_classes = [IsAuthenticated, FeeAccessPolicy]

    def _obj(self, request, pk):
        try:
            inst = Installment.objects.select_related("enrollment").get(pk=pk)
        except Installment.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, inst)
        return inst

    def get(self, request, pk):
        return Response(InstallmentSerializer(self._obj(request, pk)).data)

    def patch(self, request, pk):
        if not has_perm(request.user, "fees.installment.manage"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        inst = self._obj(request, pk)
        s = InstallmentSerializer(inst, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        if not has_perm(request.user, "fees.installment.manage"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        inst = self._obj(request, pk)
        if inst.receipts.filter(status=FeeReceipt.Status.ACTIVE).exists():
            return Response(
                {"detail": "Installment has active receipts; cancel them first."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        inst.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- Receipts ----------------------------------------------------------

class FeeReceiptListCreateView(APIView):
    permission_classes = [IsAuthenticated, FeeAccessPolicy]

    def get(self, request):
        qs = FeeReceipt.objects.select_related(
            "enrollment", "enrollment__student", "enrollment__campus",
            "received_by", "cancelled_by",
        )
        qs = visible_enrollments_filter(qs, request.user)
        params = request.query_params
        if v := params.get("enrollment"):
            qs = qs.filter(enrollment_id=v)
        if v := params.get("status"):
            qs = qs.filter(status=v)
        if v := params.get("payment_mode"):
            qs = qs.filter(payment_mode=v)
        if v := params.get("from"):
            if d := parse_date(v):
                qs = qs.filter(received_date__gte=d)
        if v := params.get("to"):
            if d := parse_date(v):
                qs = qs.filter(received_date__lte=d)
        return Response(FeeReceiptDetailSerializer(qs[:500], many=True).data)

    @transaction.atomic
    def post(self, request):
        if not has_perm(request.user, "fees.receipt.create"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = FeeReceiptCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        enrollment = s.validated_data["enrollment"]

        # Campus scope on create
        if not (request.user.is_superuser
                or can_view_all(request.user)
                or request.user.campuses.filter(pk=enrollment.campus_id).exists()):
            return Response({"detail": "Enrollment outside your campus scope."},
                            status=http.HTTP_403_FORBIDDEN)

        receipt = s.save(
            received_by=request.user,
            receipt_no=generate_receipt_no(campus_code=enrollment.campus.code),
        )
        return Response(
            FeeReceiptDetailSerializer(receipt).data,
            status=http.HTTP_201_CREATED,
        )


class FeeReceiptDetailView(APIView):
    permission_classes = [IsAuthenticated, FeeAccessPolicy]

    def _obj(self, request, pk):
        try:
            r = FeeReceipt.objects.select_related(
                "enrollment", "enrollment__student", "enrollment__campus",
                "enrollment__batch", "enrollment__program",
                "enrollment__student__institute",
                "received_by", "cancelled_by",
            ).get(pk=pk)
        except FeeReceipt.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, r)
        return r

    def get(self, request, pk):
        return Response(FeeReceiptDetailSerializer(self._obj(request, pk)).data)

    def patch(self, request, pk):
        if not has_perm(request.user, "fees.receipt.edit"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        receipt = self._obj(request, pk)
        if receipt.status == FeeReceipt.Status.CANCELLED:
            return Response({"detail": "Cancelled receipts cannot be edited."},
                            status=http.HTTP_400_BAD_REQUEST)
        s = FeeReceiptUpdateSerializer(receipt, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(FeeReceiptDetailSerializer(receipt).data)


class FeeReceiptCancelView(APIView):
    permission_classes = [IsAuthenticated, FeeAccessPolicy]

    def post(self, request, pk):
        if not has_perm(request.user, "fees.receipt.cancel"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        try:
            receipt = FeeReceipt.objects.get(pk=pk)
        except FeeReceipt.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, receipt)
        if receipt.status == FeeReceipt.Status.CANCELLED:
            return Response({"detail": "Already cancelled."},
                            status=http.HTTP_400_BAD_REQUEST)
        s = CancelReceiptSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        receipt.status = FeeReceipt.Status.CANCELLED
        receipt.cancelled_by = request.user
        receipt.cancelled_on = timezone.now()
        receipt.cancellation_reason = s.validated_data["reason"]
        receipt.save(update_fields=[
            "status", "cancelled_by", "cancelled_on",
            "cancellation_reason", "updated_on",
        ])
        return Response(FeeReceiptDetailSerializer(receipt).data)


class FeeReceiptPdfView(APIView):
    permission_classes = [IsAuthenticated, FeeAccessPolicy]

    def get(self, request, pk):
        try:
            r = FeeReceipt.objects.select_related(
                "enrollment", "enrollment__student", "enrollment__campus",
                "enrollment__batch", "enrollment__program",
                "enrollment__student__institute", "installment",
                "received_by",
            ).get(pk=pk)
        except FeeReceipt.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, r)
        pdf = render_receipt_pdf(r)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{r.receipt_no}.pdf"'
        return resp


# --- Concessions -------------------------------------------------------

class ConcessionListCreateView(APIView):
    permission_classes = [IsAuthenticated, FeeAccessPolicy]

    def get(self, request):
        qs = Concession.objects.select_related(
            "enrollment", "enrollment__student", "requested_by", "approver",
        )
        qs = visible_enrollments_filter(qs, request.user)
        if v := request.query_params.get("status"):
            qs = qs.filter(status=v)
        if v := request.query_params.get("enrollment"):
            qs = qs.filter(enrollment_id=v)
        return Response(ConcessionDetailSerializer(qs[:500], many=True).data)

    def post(self, request):
        if not has_perm(request.user, "fees.concession.request"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = ConcessionRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        enrollment = s.validated_data["enrollment"]
        if not (request.user.is_superuser
                or can_view_all(request.user)
                or request.user.campuses.filter(pk=enrollment.campus_id).exists()):
            return Response({"detail": "Enrollment outside your campus scope."},
                            status=http.HTTP_403_FORBIDDEN)
        c = s.save(requested_by=request.user)
        return Response(ConcessionDetailSerializer(c).data,
                        status=http.HTTP_201_CREATED)


class ConcessionDetailView(APIView):
    permission_classes = [IsAuthenticated, FeeAccessPolicy]

    def _obj(self, request, pk):
        try:
            c = Concession.objects.select_related(
                "enrollment", "enrollment__student",
                "requested_by", "approver",
            ).get(pk=pk)
        except Concession.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, c)
        return c

    def get(self, request, pk):
        return Response(ConcessionDetailSerializer(self._obj(request, pk)).data)


class ConcessionDecisionView(APIView):
    permission_classes = [IsAuthenticated, FeeAccessPolicy]

    def post(self, request, pk):
        if not has_perm(request.user, "fees.concession.approve"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        try:
            c = Concession.objects.get(pk=pk)
        except Concession.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, c)
        if c.status != Concession.Status.PENDING:
            return Response({"detail": "Already decided."},
                            status=http.HTTP_400_BAD_REQUEST)
        s = ConcessionDecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        c.status = s.validated_data["status"]
        c.approver = request.user
        c.approver_remarks = s.validated_data.get("remarks", "")
        c.decided_on = timezone.now()
        c.save(update_fields=["status", "approver", "approver_remarks", "decided_on"])
        return Response(ConcessionDetailSerializer(c).data)


# --- Balance ------------------------------------------------------------

class EnrollmentBalanceView(APIView):
    permission_classes = [IsAuthenticated, FeeAccessPolicy]

    def get(self, request, pk):
        try:
            e = Enrollment.objects.select_related(
                "student", "campus", "program", "course", "academic_year",
            ).get(pk=pk)
        except Enrollment.DoesNotExist as exc:
            raise Http404 from exc
        if not (request.user.is_superuser
                or can_view_all(request.user)
                or request.user.campuses.filter(pk=e.campus_id).exists()):
            raise Http404
        return Response({
            "enrollment_id": e.id,
            "student_name": e.student.student_name,
            "student_application_id": e.student.application_form_id,
            **enrollment_balance(e),
        })


# --- Student panel ------------------------------------------------------

class _StudentMixin:
    def _student(self, request):
        s = getattr(request.user, "student", None)
        if s is None:
            raise Http404("No student record linked to this user.")
        return s


class FeesMeView(_StudentMixin, APIView):
    """Aggregate balance + recent receipts across all the student's enrollments."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = self._student(request)
        enrollments = list(student.enrollments.select_related(
            "campus", "program", "course", "academic_year", "batch",
        ))
        result = []
        for e in enrollments:
            result.append({
                "enrollment_id": e.id,
                "program": e.program.name,
                "batch": e.batch.name if e.batch else "",
                "academic_year": e.academic_year.code,
                "status": e.get_status_display(),
                **enrollment_balance(e),
            })
        return Response(result)


class FeesMeReceiptsView(_StudentMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = self._student(request)
        qs = FeeReceipt.objects.filter(
            enrollment__student=student,
        ).select_related("enrollment", "received_by")
        if v := request.query_params.get("status"):
            qs = qs.filter(status=v)
        return Response(FeeReceiptDetailSerializer(qs.order_by("-received_date"), many=True).data)


class FeesMeReceiptPdfView(_StudentMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        student = self._student(request)
        try:
            r = FeeReceipt.objects.select_related(
                "enrollment", "enrollment__student", "enrollment__campus",
                "enrollment__batch", "enrollment__program",
                "enrollment__student__institute", "installment", "received_by",
            ).get(pk=pk, enrollment__student=student)
        except FeeReceipt.DoesNotExist as e:
            raise Http404 from e
        pdf = render_receipt_pdf(r)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="{r.receipt_no}.pdf"'
        return resp
