from django.utils.dateparse import parse_date
from django.utils.timezone import now
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPerm

from .intake_auth import HasIntakeApiKey
from .models import Lead, LeadCommunication, LeadFollowup
from .permissions import LeadVisibility, can_see_all_leads, filter_visible
from .serializers import (
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
from .services import change_status, create_lead


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
    permission_classes = [IsAuthenticated, LeadVisibility]

    def get(self, request, pk):
        lead = Lead.objects.get(pk=pk)
        self.check_object_permissions(request, lead)
        return Response(StatusHistorySerializer(lead.status_history.all(), many=True).data)


# --- Followups ----------------------------------------------------------

class LeadFollowupListCreateView(APIView):
    permission_classes = [IsAuthenticated, LeadVisibility, HasPerm]
    required_perm = "leads.followup.manage"

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
    required_perm = "leads.followup.manage"

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

        from apps.accounts.permissions import HasPerm
        from apps.admissions.permissions import has_perm as has_adm_perm
        if not (request.user.is_superuser
                or has_adm_perm(request.user, "admissions.student.create")):
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


class LeadIntakeView(APIView):
    """Public endpoint for automated lead sources (website forms, ad
    platforms, etc.). Auth via static API key, NOT JWT."""

    authentication_classes = []
    permission_classes = [HasIntakeApiKey]

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
