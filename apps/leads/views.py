from django.core.exceptions import ImproperlyConfigured
from django.utils.dateparse import parse_date
from django.utils.timezone import now
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPerm
from apps.common.throttles import LeadIntakeThrottle

from .intake_auth import HasIntakeApiKey
from .models import (
    Counsellor,
    Lead, LeadCommunication, LeadFollowup,
)
from .permissions import LeadVisibility, can_see_all_leads, filter_visible
from .serializers import (
    CounsellorSerializer,
    LeadCommunicationSerializer,
    LeadCreateSerializer,
    LeadDetailSerializer,
    LeadFollowupSerializer,
    LeadIntakeSerializer,
    LeadUpdateSerializer,
    ReassignSerializer,
    StatusChangeSerializer,
    StatusHistorySerializer,
)
from .services import (
    change_status, create_lead, eligible_counsellors, has_recent_outcome,
)


# --- Lead list/create ---------------------------------------------------

class LeadListCreateView(APIView):
    permission_classes = [IsAuthenticated, LeadVisibility]

    def get(self, request):
        qs = filter_visible(Lead.objects.select_related(
            "campus", "program", "source", "assign_to", "created_by",
        ).prefetch_related("utm"), request.user)

        params = request.query_params
        if v := params.get("status"):
            qs = qs.filter(status=v)
        if v := params.get("source"):
            qs = qs.filter(source_id=v)
        if v := params.get("campus"):
            qs = qs.filter(campus_id=v)
        if v := params.get("program"):
            qs = qs.filter(program_id=v)
        if v := params.get("assign_to"):
            qs = qs.filter(assign_to_id=v)
        if params.get("is_repeated") == "1":
            qs = qs.filter(is_repeated=True)
        if v := params.get("created_after"):
            if d := parse_date(v):
                qs = qs.filter(created_at__date__gte=d)
        if v := params.get("created_before"):
            if d := parse_date(v):
                qs = qs.filter(created_at__date__lte=d)
        if q := params.get("q"):
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
        if params.get("overdue") == "1":
            today = now().date()
            qs = qs.filter(
                followups__next_followup_date__lt=today,
            ).distinct()

        return Response(LeadDetailSerializer(qs[:500], many=True).data)

    def post(self, request):
        if not (request.user.is_superuser
                or request.user.roles.filter(permissions__key="leads.lead.create").exists()):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)

        serializer = LeadCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lead = create_lead(data=serializer.validated_data, created_by=request.user)
        return Response(LeadDetailSerializer(lead).data, status=http.HTTP_201_CREATED)


class LeadDetailView(APIView):
    permission_classes = [IsAuthenticated, LeadVisibility]

    def _get(self, request, pk):
        lead = Lead.objects.get(pk=pk)
        self.check_object_permissions(request, lead)
        return lead

    def get(self, request, pk):
        return Response(LeadDetailSerializer(self._get(request, pk)).data)

    def patch(self, request, pk):
        lead = self._get(request, pk)
        if not (request.user.is_superuser
                or request.user.roles.filter(permissions__key="leads.lead.edit").exists()):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = LeadUpdateSerializer(lead, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(LeadDetailSerializer(lead).data)


class LeadStatusView(APIView):
    permission_classes = [IsAuthenticated, LeadVisibility, HasPerm]
    required_perm = "leads.lead.change_status"

    def post(self, request, pk):
        lead = Lead.objects.get(pk=pk)
        self.check_object_permissions(request, lead)

        # F.4 guard — outcome must be logged before stage moves.
        # Caller can either log a followup first, or pass the outcome
        # inline as `outcome_category` + `outcome_disposition`.
        outcome_cat = (request.data.get("outcome_category") or "").upper()
        outcome_disp = request.data.get("outcome_disposition") or ""
        if outcome_cat:
            from .outcomes import is_valid_disposition
            from .models import LeadFollowup
            if outcome_disp and not is_valid_disposition(outcome_cat, outcome_disp):
                return Response(
                    {"outcome_disposition":
                     f"'{outcome_disp}' invalid for {outcome_cat}."},
                    status=http.HTTP_400_BAD_REQUEST,
                )
            LeadFollowup.objects.create(
                lead=lead,
                followup_type=LeadFollowup.Type.OTHER,
                outcome_category=outcome_cat,
                outcome_disposition=outcome_disp,
                notes=request.data.get("note", ""),
                created_by=request.user,
            )
        elif not has_recent_outcome(lead):
            return Response(
                {"detail": "Cannot change status without a logged outcome. "
                           "Log a follow-up with outcome_category first, or "
                           "pass `outcome_category` (+ optional "
                           "`outcome_disposition`) inline."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        s = StatusChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        change_status(
            lead=lead,
            new_status=s.validated_data["new_status"],
            changed_by=request.user,
            note=s.validated_data.get("note", ""),
        )
        return Response(LeadDetailSerializer(lead).data)


class LeadReassignView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "leads.lead.reassign"

    def post(self, request, pk):
        lead = Lead.objects.get(pk=pk)
        s = ReassignSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        lead.assign_to = s.validated_data["assign_to"]
        lead.save(update_fields=["assign_to", "updated_at"])
        return Response(LeadDetailSerializer(lead).data)


class LeadHistoryView(APIView):
    permission_classes = [IsAuthenticated, LeadVisibility, HasPerm]
    required_perm = "leads.lead.view_history"

    def get(self, request, pk):
        lead = Lead.objects.get(pk=pk)
        self.check_object_permissions(request, lead)
        return Response(StatusHistorySerializer(lead.status_history.all(), many=True).data)


# --- Application form close / open (counsellor kill switch) --------------

class LeadApplicationCloseView(APIView):
    """Close the self-fill application form for this lead's student.
    After this, the public POST /api/public/application/<token>/ returns
    403. Counsellor-side edits via authenticated endpoints are
    unaffected."""
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "leads.application_form.lock"

    def post(self, request, pk):
        from django.utils import timezone
        lead = Lead.objects.get(pk=pk)
        lead.application_locked_for_student = True
        lead.application_locked_at = timezone.now()
        lead.application_locked_by = request.user
        lead.save(update_fields=[
            "application_locked_for_student",
            "application_locked_at", "application_locked_by", "updated_at",
        ])
        return Response(LeadDetailSerializer(lead).data)


class LeadApplicationOpenView(APIView):
    """Re-open the form so the student can edit again."""
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "leads.application_form.lock"

    def post(self, request, pk):
        lead = Lead.objects.get(pk=pk)
        lead.application_locked_for_student = False
        lead.application_locked_at = None
        lead.application_locked_by = None
        lead.save(update_fields=[
            "application_locked_for_student",
            "application_locked_at", "application_locked_by", "updated_at",
        ])
        return Response(LeadDetailSerializer(lead).data)


# --- Followups ----------------------------------------------------------

class LeadFollowupListCreateView(APIView):
    permission_classes = [IsAuthenticated, LeadVisibility, HasPerm]
    perm_base = "leads.followup"

    def _lead(self, request, pk):
        lead = Lead.objects.get(pk=pk)
        self.check_object_permissions(request, lead)
        return lead

    def get(self, request, pk):
        lead = self._lead(request, pk)
        return Response(LeadFollowupSerializer(lead.followups.all(), many=True).data)

    def post(self, request, pk):
        lead = self._lead(request, pk)
        data = {**request.data, "lead": lead.id}
        s = LeadFollowupSerializer(data=data)
        s.is_valid(raise_exception=True)
        s.save(created_by=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


class LeadFollowupDetailView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    perm_base = "leads.followup"

    def patch(self, request, pk):
        f = LeadFollowup.objects.select_related("lead").get(pk=pk)
        if not can_see_all_leads(request.user) and f.lead.assign_to_id != request.user.id:
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = LeadFollowupSerializer(f, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        f = LeadFollowup.objects.select_related("lead").get(pk=pk)
        if not can_see_all_leads(request.user) and f.lead.assign_to_id != request.user.id:
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        f.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- Communications -----------------------------------------------------

class LeadCommunicationListCreateView(APIView):
    permission_classes = [IsAuthenticated, LeadVisibility, HasPerm]
    required_perm = "leads.communication.log"

    def _lead(self, request, pk):
        lead = Lead.objects.get(pk=pk)
        self.check_object_permissions(request, lead)
        return lead

    def get(self, request, pk):
        lead = self._lead(request, pk)
        return Response(LeadCommunicationSerializer(lead.communications.all(), many=True).data)

    def post(self, request, pk):
        lead = self._lead(request, pk)
        data = {**request.data, "lead": lead.id}
        s = LeadCommunicationSerializer(data=data)
        s.is_valid(raise_exception=True)
        s.save(logged_by=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


# --- Counsellors (F.3) ------------------------------------------------

def _has_perm(request, key):
    u = request.user
    return u.is_superuser or u.roles.filter(permissions__key=key).exists()


def _denied():
    return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)


def _counsellor_qs():
    return Counsellor.objects.select_related(
        "employee", "employee__designation", "employee__department",
        "employee__campus", "employee__user_account",
    )


class CounsellorListCreateView(APIView):
    """The Counsellors page: list who is a counsellor, and promote an
    employee into one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_perm(request, "leads.pool.view"):
            return _denied()
        qs = _counsellor_qs()
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(CounsellorSerializer(qs, many=True).data)

    def post(self, request):
        if not _has_perm(request, "leads.pool.add"):
            return _denied()
        s = CounsellorSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=http.HTTP_201_CREATED)


class CounsellorDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        try:
            return _counsellor_qs().get(pk=pk)
        except Counsellor.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        if not _has_perm(request, "leads.pool.view"):
            return _denied()
        return Response(CounsellorSerializer(self._get(pk)).data)

    def patch(self, request, pk):
        if not _has_perm(request, "leads.pool.edit"):
            return _denied()
        c = self._get(pk)
        # `employee` is fixed once set — removing and re-adding is the
        # way to point a counsellor slot at somebody else.
        data = {k: v for k, v in request.data.items() if k != "employee"}
        s = CounsellorSerializer(c, data=data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        if not _has_perm(request, "leads.pool.delete"):
            return _denied()
        self._get(pk).delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


class CounsellorEligibleEmployeesView(APIView):
    """Employees that may be made counsellors — active, not deleted, with
    a portal account, and not already a counsellor.

    Lives here rather than reusing the employees list so the Counsellors
    page needs only `leads.pool.add`, not `employees.employee.view`.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _has_perm(request, "leads.pool.add"):
            return _denied()

        from apps.employees.models import Employee

        qs = (
            Employee.objects
            .filter(
                status=Employee.Status.ACTIVE,
                user_account__isnull=False,
                user_account__is_active=True,
                counsellor__isnull=True,
            )
            .select_related("designation", "department", "campus")
            .order_by("first_name", "family_name")
        )
        if q := request.query_params.get("search"):
            from django.db.models import Q
            qs = qs.filter(
                Q(first_name__icontains=q) | Q(family_name__icontains=q)
                | Q(emp_code__icontains=q) | Q(email_primary__icontains=q)
            )
        return Response([
            {
                "id": e.id,
                "emp_code": e.emp_code,
                "full_name": e.full_name,
                "designation": e.designation.name,
                "department": e.department.name,
                "campus": e.campus.name,
                "email": e.email_primary,
            }
            for e in qs
        ])


class CounsellorOptionsView(APIView):
    """Assignable counsellors for the lead forms' "Assign to" picker.

    Open to any authenticated user — a counsellor filling in the Add
    Lead form needs the list but has no business administering it. Only
    people who can actually hold a lead are returned, so the dropdown
    never offers somebody the backend would reject.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response([
            {
                "id": c.employee.user_account_id,
                "counsellor_id": c.id,
                "full_name": (c.employee.user_account.full_name
                              or c.employee.full_name),
                "username": c.employee.user_account.username,
                "emp_code": c.employee.emp_code,
            }
            for c in eligible_counsellors()
        ])


# --- Public intake ------------------------------------------------------

class LeadPromoteView(APIView):
    """Lead → Student promotion. HR action.

    Creates a Student record, a portal User, and links them. Returns the
    student id + a one-time temporary password (PA free can't email).
    """
    permission_classes = [IsAuthenticated, LeadVisibility]

    def post(self, request, pk):
        try:
            lead = Lead.objects.get(pk=pk)
        except Lead.DoesNotExist:
            return Response({"detail": "Lead not found."}, status=http.HTTP_404_NOT_FOUND)
        self.check_object_permissions(request, lead)

        # Promotion needs BOTH keys: the Leads-side permission to convert
        # a lead, and the Admissions-side permission to create the
        # student record it produces.
        from apps.admissions.permissions import has_perm as has_adm_perm
        if not (request.user.is_superuser
                or (has_adm_perm(request.user, "admissions.student.create")
                    and has_adm_perm(request.user, "leads.lead.promote"))):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)

        from apps.admissions.serializers import PromotionResultSerializer
        from apps.admissions.services import promote_lead_to_student
        try:
            student, creds = promote_lead_to_student(lead=lead, actor=request.user)
        except ValueError as e:
            return Response({"detail": str(e)}, status=http.HTTP_400_BAD_REQUEST)

        body = {
            "student_id": student.id,
            "application_form_id": student.application_form_id,
            "user_id": student.user_account_id,
            **creds,
        }
        return Response(PromotionResultSerializer(body).data,
                        status=http.HTTP_201_CREATED)


# --- Send Application / Fee / Welcome links ---------------------------

class _SendLinkBase(APIView):
    """Shared lead lookup + permission gate for the Send / fee actions.

    Each subclass declares its own `required_perm` — sending a fee link,
    sending an application link and recording an application fee are
    distinct capabilities, not one blanket "communications" grant.
    """

    permission_classes = [IsAuthenticated, LeadVisibility]
    required_perm = None

    def _resolve(self, request, pk):
        try:
            lead = Lead.objects.select_related("campus", "program").get(pk=pk)
        except Lead.DoesNotExist:
            return None, Response(
                {"detail": "Lead not found."}, status=http.HTTP_404_NOT_FOUND,
            )
        self.check_object_permissions(request, lead)
        if not self.required_perm:
            raise ImproperlyConfigured(
                f"{type(self).__name__} must declare a `required_perm`.",
            )
        if not (request.user.is_superuser
                or request.user.roles.filter(
                    permissions__key=self.required_perm,
                ).exists()):
            return None, Response(
                {"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN,
            )
        return lead, None


class LeadSendApplicationLinkView(_SendLinkBase):
    """Body: { "institute": "JDIFT" | "JDSD" }"""

    required_perm = "leads.send.application_link"

    def post(self, request, pk):
        from .send_links import send_application_link

        lead, err = self._resolve(request, pk)
        if err:
            return err

        institute = request.data.get("institute")
        if not institute:
            return Response(
                {"institute": "Required. e.g. 'JDIFT' or 'JDSD'."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        try:
            result = send_application_link(
                lead=lead, institute_key=institute, actor=request.user,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=http.HTTP_400_BAD_REQUEST)
        return Response(result, status=http.HTTP_201_CREATED)


class LeadSendFeeLinkView(_SendLinkBase):
    """Body: { "institute": "JDIFT" | "JDSD" }"""

    required_perm = "leads.send.fee_link"

    def post(self, request, pk):
        from .send_links import send_fee_link

        lead, err = self._resolve(request, pk)
        if err:
            return err

        institute = request.data.get("institute")
        if not institute:
            return Response(
                {"institute": "Required. e.g. 'JDIFT' or 'JDSD'."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        try:
            result = send_fee_link(
                lead=lead, institute_key=institute, actor=request.user,
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=http.HTTP_400_BAD_REQUEST)
        return Response(result, status=http.HTTP_201_CREATED)


class LeadSendWelcomeView(_SendLinkBase):
    """No body. Sends welcome email to lead.email."""

    required_perm = "leads.send.welcome"

    def post(self, request, pk):
        from .send_links import send_welcome_message

        lead, err = self._resolve(request, pk)
        if err:
            return err

        try:
            result = send_welcome_message(lead=lead, actor=request.user)
        except ValueError as e:
            return Response({"detail": str(e)}, status=http.HTTP_400_BAD_REQUEST)
        return Response(result, status=http.HTTP_201_CREATED)


class LeadMarkFeePaidView(_SendLinkBase):
    required_perm = "leads.application_fee.record"

    """Body: { amount?, mode?, ref?, paid_at?, notes? }

    Records the application fee as paid on the lead. This is the gate
    that unlocks `send_application_link`. All body fields are optional
    to keep the action low-friction — the only required state change is
    `application_fee_paid_at = now()`.
    """

    def post(self, request, pk):
        from django.utils.dateparse import parse_datetime

        lead, err = self._resolve(request, pk)
        if err:
            return err

        from django.utils import timezone

        paid_at_raw = request.data.get("paid_at")
        paid_at = parse_datetime(paid_at_raw) if paid_at_raw else None
        lead.application_fee_paid_at = paid_at or timezone.now()
        lead.application_fee_amount = (
            request.data.get("amount") or None
        )
        lead.application_fee_mode = (
            (request.data.get("mode") or "").strip().upper()
        )
        lead.application_fee_ref = (
            (request.data.get("ref") or "").strip()
        )
        lead.application_fee_notes = (
            (request.data.get("notes") or "").strip()
        )
        lead.application_fee_recorded_by = request.user
        lead.save(update_fields=[
            "application_fee_paid_at", "application_fee_amount",
            "application_fee_mode", "application_fee_ref",
            "application_fee_notes", "application_fee_recorded_by",
        ])
        return Response(
            {
                "application_fee_paid_at": lead.application_fee_paid_at,
                "application_fee_amount": str(lead.application_fee_amount or ""),
                "application_fee_mode": lead.application_fee_mode,
                "application_fee_ref": lead.application_fee_ref,
                "application_fee_notes": lead.application_fee_notes,
                "application_fee_recorded_by": request.user.id,
            },
            status=http.HTTP_200_OK,
        )


class LeadClearFeePaidView(_SendLinkBase):
    """Undo a mark-paid (mistake correction). All fields cleared."""

    required_perm = "leads.application_fee.clear"

    def post(self, request, pk):
        lead, err = self._resolve(request, pk)
        if err:
            return err

        lead.application_fee_paid_at = None
        lead.application_fee_amount = None
        lead.application_fee_mode = ""
        lead.application_fee_ref = ""
        lead.application_fee_notes = ""
        lead.application_fee_recorded_by = None
        lead.save(update_fields=[
            "application_fee_paid_at", "application_fee_amount",
            "application_fee_mode", "application_fee_ref",
            "application_fee_notes", "application_fee_recorded_by",
        ])
        return Response(status=http.HTTP_204_NO_CONTENT)


class LeadIntakeView(APIView):
    """Public endpoint for automated lead sources (website forms, ad
    platforms, etc.). Auth via static API key, NOT JWT.

    Rate-limited per (API key, IP) — 120/hour by default. Override via
    THROTTLE_LEAD_INTAKE env var."""

    authentication_classes = []
    permission_classes = [HasIntakeApiKey]
    throttle_classes = [LeadIntakeThrottle]

    def post(self, request):
        s = LeadIntakeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        lead_data, utm = s.split_payload()
        lead = create_lead(data=lead_data, created_by=None, utm=utm)
        return Response(
            {"id": lead.id, "is_repeated": lead.is_repeated,
             "duplicate_of": lead.duplicate_of_id},
            status=http.HTTP_201_CREATED,
        )
