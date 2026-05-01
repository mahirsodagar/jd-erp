from django.http import Http404, HttpResponse
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.employees.models import Employee

from .letters import render_experience_letter, render_relieving_letter
from .models import RelievingApplication, RelievingApproval
from .permissions import has_perm
from .serializers import (
    DecideSerializer, FinalizeSerializer, RelievingApplicationSerializer,
    SubmitRelievingSerializer, WithdrawSerializer,
)
from . import services


def _emp_of(user) -> Employee | None:
    return getattr(user, "employee", None)


def _can_view_application(user, app: RelievingApplication) -> bool:
    if user.is_superuser or has_perm(user, "hr.relieving.view_all"):
        return True
    emp = _emp_of(user)
    if emp is None:
        return False
    # Self
    if app.employee_id == emp.id:
        return True
    # Approver in chain
    if app.approvals.filter(approver=emp).exists():
        return True
    return False


# --- List + submit -------------------------------------------------

class RelievingListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = RelievingApplication.objects.select_related(
            "employee",
        ).prefetch_related("approvals__approver")
        if not (u.is_superuser or has_perm(u, "hr.relieving.view_all")):
            emp = _emp_of(u)
            if emp is None:
                return Response([])
            # Self + applications I'm an approver on
            from django.db.models import Q
            qs = qs.filter(Q(employee=emp) | Q(approvals__approver=emp)).distinct()
        params = request.query_params
        if v := params.get("status"):
            qs = qs.filter(status=v)
        if v := params.get("employee"):
            qs = qs.filter(employee_id=v)
        return Response(RelievingApplicationSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        s = SubmitRelievingSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            employee = Employee.objects.get(pk=d["employee"])
        except Employee.DoesNotExist:
            return Response({"employee": "Not found."},
                            status=http.HTTP_400_BAD_REQUEST)
        emp = _emp_of(u)
        is_self = (emp and emp.id == employee.id)
        if not (is_self
                or u.is_superuser
                or has_perm(u, "hr.relieving.submit_for_others")):
            return Response(
                {"detail": "You can only submit for yourself."},
                status=http.HTTP_403_FORBIDDEN,
            )
        if employee.status != Employee.Status.ACTIVE:
            return Response(
                {"employee": "Only ACTIVE employees can apply for relieving."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        try:
            app = services.submit(
                employee=employee, reason=d["reason"],
                last_working_date_requested=d["last_working_date_requested"],
                submitted_by=u,
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        # Refresh with prefetch
        app = (RelievingApplication.objects
               .select_related("employee")
               .prefetch_related("approvals__approver")
               .get(pk=app.pk))
        return Response(RelievingApplicationSerializer(app).data,
                        status=http.HTTP_201_CREATED)


class RelievingDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            app = (RelievingApplication.objects
                   .select_related("employee")
                   .prefetch_related("approvals__approver")
                   .get(pk=pk))
        except RelievingApplication.DoesNotExist as e:
            raise Http404 from e
        if not _can_view_application(request.user, app):
            raise Http404
        return Response(RelievingApplicationSerializer(app).data)


# --- Decide --------------------------------------------------------

class RelievingDecideView(APIView):
    """Approver of any level decides their own row. The service layer
    enforces sequence (earlier non-skipped levels must be APPROVED)."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk, level):
        u = request.user
        try:
            app = RelievingApplication.objects.select_related(
                "employee",
            ).get(pk=pk)
        except RelievingApplication.DoesNotExist as e:
            raise Http404 from e
        try:
            approval = app.approvals.get(level=level)
        except RelievingApproval.DoesNotExist:
            return Response({"detail": "No approval row at that level."},
                            status=http.HTTP_400_BAD_REQUEST)

        # Authorization: caller must be the approver, OR have override.
        emp = _emp_of(u)
        is_assigned = (emp and approval.approver_id == emp.id)
        is_override = u.is_superuser or has_perm(u, "hr.relieving.override")
        if not (is_assigned or is_override):
            return Response({"detail": "Not the approver for this level."},
                            status=http.HTTP_403_FORBIDDEN)

        s = DecideSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.decide(
                approval=approval,
                decision=s.validated_data["decision"],
                remarks=s.validated_data.get("remarks", ""),
                decided_by=u,
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        # Reload + serialize
        app = (RelievingApplication.objects
               .select_related("employee")
               .prefetch_related("approvals__approver")
               .get(pk=pk))
        return Response(RelievingApplicationSerializer(app).data)


# --- Finalize (HR generates letters) -------------------------------

class RelievingFinalizeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not (u.is_superuser or has_perm(u, "hr.relieving.finalize")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            app = RelievingApplication.objects.select_related(
                "employee", "employee__institute",
            ).get(pk=pk)
        except RelievingApplication.DoesNotExist as e:
            raise Http404 from e
        s = FinalizeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.finalize(
                application=app,
                last_working_date_approved=s.validated_data["last_working_date_approved"],
                set_inactive=s.validated_data.get("set_inactive", True),
                finalized_by=u,
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        app = (RelievingApplication.objects
               .select_related("employee")
               .prefetch_related("approvals__approver")
               .get(pk=pk))
        return Response(RelievingApplicationSerializer(app).data)


# --- Withdraw ------------------------------------------------------

class RelievingWithdrawView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        try:
            app = RelievingApplication.objects.select_related(
                "employee",
            ).get(pk=pk)
        except RelievingApplication.DoesNotExist as e:
            raise Http404 from e
        emp = _emp_of(u)
        is_self = (emp and app.employee_id == emp.id)
        if not (is_self or u.is_superuser):
            return Response({"detail": "Only the applicant can withdraw."},
                            status=http.HTTP_403_FORBIDDEN)
        s = WithdrawSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.withdraw(
                application=app,
                remarks=s.validated_data.get("remarks", ""),
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(RelievingApplicationSerializer(
            RelievingApplication.objects
            .select_related("employee")
            .prefetch_related("approvals__approver")
            .get(pk=pk)
        ).data)


# --- /me/ ----------------------------------------------------------

class MyRelievingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emp = _emp_of(request.user)
        if emp is None:
            return Response([])
        qs = (RelievingApplication.objects
              .filter(employee=emp)
              .select_related("employee")
              .prefetch_related("approvals__approver")
              .order_by("-submitted_at"))
        return Response(RelievingApplicationSerializer(qs, many=True).data)


# --- Letter PDFs ---------------------------------------------------

class RelievingLetterPdfView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            app = RelievingApplication.objects.select_related(
                "employee", "employee__institute",
                "employee__designation", "employee__department",
            ).get(pk=pk)
        except RelievingApplication.DoesNotExist as e:
            raise Http404 from e
        if not _can_view_application(request.user, app):
            raise Http404
        if app.status != RelievingApplication.Status.COMPLETED:
            return Response(
                {"detail": "Letter unavailable until application is COMPLETED."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        pdf = render_relieving_letter(app)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = (
            f'inline; filename="{app.relieving_letter_no}.pdf"'
        )
        return resp


class ExperienceLetterPdfView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            app = RelievingApplication.objects.select_related(
                "employee", "employee__institute",
                "employee__designation", "employee__department",
            ).get(pk=pk)
        except RelievingApplication.DoesNotExist as e:
            raise Http404 from e
        if not _can_view_application(request.user, app):
            raise Http404
        if app.status != RelievingApplication.Status.COMPLETED:
            return Response(
                {"detail": "Letter unavailable until application is COMPLETED."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        pdf = render_experience_letter(app)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = (
            f'inline; filename="{app.experience_letter_no}.pdf"'
        )
        return resp
