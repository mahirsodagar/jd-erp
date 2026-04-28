from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPerm

from .models import Campus, LeadSource, Program
from .serializers import CampusSerializer, LeadSourceSerializer, ProgramSerializer


class _MasterDetailMixin:
    model = None
    serializer = None
    perm = None

    def _obj(self, pk):
        return self.model.objects.get(pk=pk)

    def get(self, request, pk):
        return Response(self.serializer(self._obj(pk)).data)

    def patch(self, request, pk):
        obj = self._obj(pk)
        s = self.serializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(self.serializer(obj).data)

    def delete(self, request, pk):
        obj = self._obj(pk)
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Campus -------------------------------------------------------------

class CampusListCreateView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "master.campus.manage"

    def get(self, request):
        qs = Campus.objects.all()
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(CampusSerializer(qs, many=True).data)

    def post(self, request):
        s = CampusSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=status.HTTP_201_CREATED)


class CampusDetailView(_MasterDetailMixin, APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "master.campus.manage"
    model = Campus
    serializer = CampusSerializer


class CampusProgramsView(APIView):
    """List the programs offered at a specific campus.
    Used by the Add Lead form to filter the program dropdown."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        campus = Campus.objects.get(pk=pk)
        qs = campus.programs.filter(is_active=True)
        return Response(ProgramSerializer(qs, many=True).data)


# --- Program ------------------------------------------------------------

class ProgramListCreateView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "master.program.manage"

    def get(self, request):
        qs = Program.objects.all()
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        if cid := request.query_params.get("campus"):
            qs = qs.filter(campuses__id=cid)
        return Response(ProgramSerializer(qs, many=True).data)

    def post(self, request):
        s = ProgramSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=status.HTTP_201_CREATED)


class ProgramDetailView(_MasterDetailMixin, APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "master.program.manage"
    model = Program
    serializer = ProgramSerializer


# --- Lead Source --------------------------------------------------------

class LeadSourceListCreateView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "master.source.manage"

    def get(self, request):
        qs = LeadSource.objects.all()
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(LeadSourceSerializer(qs, many=True).data)

    def post(self, request):
        s = LeadSourceSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=status.HTTP_201_CREATED)


class LeadSourceDetailView(_MasterDetailMixin, APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "master.source.manage"
    model = LeadSource
    serializer = LeadSourceSerializer
