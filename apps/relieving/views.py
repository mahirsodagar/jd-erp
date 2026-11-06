from django.db.models import Q
from django.http import Http404, HttpResponse
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.employees.models import Employee
from apps.master.models import Institute

from .letters import render_experience_letter, render_relieving_letter
from .models import RelievingApplication, RelievingApproval
from .permissions import has_perm
from .serializers import (
    DecideSerializer, FinalizeSerializer, RelievingApplicationSerializer,
    RelievingManagerSerializer, SaveRelievingManagersSerializer,
    SubmitRelievingSerializer, WithdrawSerializer,
)
from . import notifications, services


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


def _full(pk) -> RelievingApplication:
    return (RelievingApplication.objects
            .select_related("employee", "employee__institute")
            .prefetch_related("approvals__approver")
            .get(pk=pk))


# --- Relieving Managers master --------------------------------------

class RelievingManagersView(APIView):
    """GET: every active institute's L1–L4 (missing rows are created
    with no approver). Readable by any signed-in user so the apply form
    can show who will approve; editing needs `hr.relieving.managers`."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = []
        for inst in Institute.objects.filter(is_active=True).order_by("code"):
            rows += services.managers_for(inst)
        return Response(RelievingManagerSerializer(rows, many=True).data)


class RelievingManagersForInstituteView(APIView):
    permission_classes = [IsAuthenticated]

    def _institute(self, pk):
        try:
            return Institute.objects.get(pk=pk)
        except Institute.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, institute_id):
        rows = services.managers_for(self._institute(institute_id))
        return Response(RelievingManagerSerializer(rows, many=True).data)

    def put(self, request, institute_id):
        u = request.user
        if not (u.is_superuser or has_perm(u, "hr.relieving.managers")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        inst = self._institute(institute_id)
        s = SaveRelievingManagersSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        levels = []
        for item in s.validated_data["levels"]:
            approver = None
            if item["approver"] is not None:
                approver = Employee.objects.filter(pk=item["approver"]).first()
                if approver is None:
                    return Response(
                        {"levels": f"L{item['level']}: employee not found."},
                        status=http.HTTP_400_BAD_REQUEST,
                    )
            levels.append({
                "level": item["level"], "approver": approver,
                "label": item.get("label", ""),
            })
        try:
            rows = services.save_managers(
                institute=inst, levels=levels, updated_by=u,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=http.HTTP_400_BAD_REQUEST)
        return Response(RelievingManagerSerializer(rows, many=True).data)


class MyRelievingChainView(APIView):
    """The chain the signed-in employee's application would be routed
    through right now — shown on the apply form."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emp = _emp_of(request.user)
        if emp is None:
            return Response([])
        rows = services.managers_for(emp.institute)
        return Response(RelievingManagerSerializer(rows, many=True).data)


# --- List + submit -------------------------------------------------

class RelievingListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = RelievingApplication.objects.select_related(
            "employee", "employee__institute",
        ).prefetch_related("approvals__approver")
        if not (u.is_superuser or has_perm(u, "hr.relieving.view_all")):
            emp = _emp_of(u)
            if emp is None:
                return Response([])
            # Self + applications I'm an approver on
            qs = qs.filter(Q(employee=emp) | Q(approvals__approver=emp)).distinct()
        params = request.query_params
        if v := params.get("status"):
            qs = qs.filter(status=v)
        if v := params.get("employee"):
            qs = qs.filter(employee_id=v)
        if v := params.get("application_type"):
            qs = qs.filter(application_type=v)
        return Response(RelievingApplicationSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        s = SubmitRelievingSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            employee = Employee.objects.select_related("institute").get(
                pk=d["employee"])
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
                {"employee": "Only ACTIVE employees can apply."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if (d["application_type"] == RelievingApplication.Type.PART_TIME
                and employee.employment_type == Employee.EmploymentType.PART_TIME):
            return Response(
                {"application_type": "Employee is already part-time."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        try:
            app = services.submit(
                employee=employee, reason=d["reason"],
                application_type=d["application_type"],
                last_working_date_requested=d["last_working_date_requested"],
                submitted_by=u,
            )
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)
        notifications.notify_submitted(app)
        return Response(RelievingApplicationSerializer(_full(app.pk)).data,
                        status=http.HTTP_201_CREATED)


class RelievingDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            app = _full(pk)
        except RelievingApplication.DoesNotExist as e:
            raise Http404 from e
        if not _can_view_application(request.user, app):
            raise Http404
        return Response(RelievingApplicationSerializer(app).data)


# --- Decide --------------------------------------------------------

class RelievingDecideView(APIView):
    """The snapshotted approver of a level decides that level. Nobody
    else can — not HR, not a superuser (user rule 2026-11-06: strict
    four-manager approval; HR acts only when HR is one of the four).
    The service layer enforces sequence."""
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

        emp = _emp_of(u)
        if not (emp and approval.approver_id == emp.id):
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
        app.refresh_from_db()
        if app.status == RelievingApplication.Status.REJECTED:
            notifications.notify_rejected(app)
        elif app.status == RelievingApplication.Status.COMPLETED:
            notifications.notify_completed(app)
        return Response(RelievingApplicationSerializer(_full(pk)).data)


# --- Finalize (legacy APPROVED rows only) ---------------------------

class RelievingFinalizeView(APIView):
    """Completion is automatic on the final approval; this stays for
    applications left APPROVED from before that change."""
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
        notifications.notify_completed(app)
        return Response(RelievingApplicationSerializer(_full(pk)).data)


# --- Send experience letter (HR) -----------------------------------

class SendExperienceLetterView(APIView):
    """Mail the experience letter to the employee. Repeatable — a second
    call re-sends it."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not (u.is_superuser or has_perm(u, "hr.relieving.finalize")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            app = RelievingApplication.objects.select_related(
                "employee", "employee__institute",
                "employee__designation", "employee__department",
            ).get(pk=pk)
        except RelievingApplication.DoesNotExist as e:
            raise Http404 from e
        if not app.is_relieving:
            return Response(
                {"detail": "Only relieving applications have letters."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if app.status != RelievingApplication.Status.COMPLETED:
            return Response(
                {"detail": "Experience letter can only be sent once the "
                           "application is COMPLETED."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        emp = app.employee
        if not (emp.email_alternate or emp.email_primary):
            return Response(
                {"detail": "Employee has no email address on record."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        log = notifications.send_experience_letter(app)
        if log is None or log.status != log.Status.SENT:
            return Response(
                {"detail": "Could not send the experience letter"
                           + (f": {log.error}" if log and log.error else ".")},
                status=http.HTTP_502_BAD_GATEWAY,
            )
        app.experience_letter_sent_at = log.sent_at
        app.save(update_fields=["experience_letter_sent_at", "updated_at"])
        return Response(RelievingApplicationSerializer(_full(pk)).data)


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
        return Response(RelievingApplicationSerializer(_full(pk)).data)


# --- /me/ ----------------------------------------------------------

class MyRelievingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emp = _emp_of(request.user)
        if emp is None:
            return Response([])
        qs = (RelievingApplication.objects
              .filter(employee=emp)
              .select_related("employee", "employee__institute")
              .prefetch_related("approvals__approver")
              .order_by("-submitted_at"))
        return Response(RelievingApplicationSerializer(qs, many=True).data)


# --- Letter PDFs ---------------------------------------------------

def _letter_app(request, pk) -> RelievingApplication | Response:
    try:
        app = RelievingApplication.objects.select_related(
            "employee", "employee__institute",
            "employee__designation", "employee__department",
        ).get(pk=pk)
    except RelievingApplication.DoesNotExist as e:
        raise Http404 from e
    if not _can_view_application(request.user, app):
        raise Http404
    if not app.is_relieving:
        return Response(
            {"detail": "Only relieving applications have letters."},
            status=http.HTTP_400_BAD_REQUEST,
        )
    if app.status != RelievingApplication.Status.COMPLETED:
        return Response(
            {"detail": "Letter unavailable until application is COMPLETED."},
            status=http.HTTP_400_BAD_REQUEST,
        )
    return app


class RelievingLetterPdfView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        app = _letter_app(request, pk)
        if isinstance(app, Response):
            return app
        pdf = render_relieving_letter(app)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = (
            f'inline; filename="{app.relieving_letter_no}.pdf"'
        )
        return resp


class ExperienceLetterPdfView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        app = _letter_app(request, pk)
        if isinstance(app, Response):
            return app
        pdf = render_experience_letter(app)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = (
            f'inline; filename="{app.experience_letter_no}.pdf"'
        )
        return resp
