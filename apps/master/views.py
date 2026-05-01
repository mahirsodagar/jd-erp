from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPerm

from .models import (
    AcademicYear, Batch, Campus, City, Classroom, Course, CourseSubject,
    Degree, FeeTemplate, Institute, LeadSource, Program, Semester,
    State, Subject, TimeSlot,
)
from .serializers import (
    AcademicYearSerializer,
    BatchSerializer,
    CampusSerializer,
    CitySerializer,
    ClassroomSerializer,
    CourseSerializer,
    CourseSubjectSerializer,
    DegreeSerializer,
    FeeTemplateSerializer,
    InstituteSerializer,
    LeadSourceSerializer,
    ProgramSerializer,
    SemesterSerializer,
    StateSerializer,
    SubjectSerializer,
    TimeSlotSerializer,
)


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

# --- Institute ----------------------------------------------------------

class InstituteListCreateView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "master.institute.manage"

    def get(self, request):
        qs = Institute.objects.all()
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(InstituteSerializer(qs, many=True).data)

    def post(self, request):
        s = InstituteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=status.HTTP_201_CREATED)


class InstituteDetailView(_MasterDetailMixin, APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "master.institute.manage"
    model = Institute
    serializer = InstituteSerializer


# --- State --------------------------------------------------------------

class StateListView(APIView):
    """Read-only for everyone authenticated; CRUD requires perm."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(StateSerializer(State.objects.all(), many=True).data)


class StateManageView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "master.state.manage"

    def post(self, request):
        s = StateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=status.HTTP_201_CREATED)


class StateDetailView(_MasterDetailMixin, APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "master.state.manage"
    model = State
    serializer = StateSerializer


# --- City ---------------------------------------------------------------

class CityListCreateView(APIView):
    """List filterable by state; create requires perm."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        from rest_framework.permissions import IsAuthenticated as _IA
        return [_IA(), HasPerm()]

    required_perm = "master.city.manage"

    def get(self, request):
        qs = City.objects.select_related("state")
        if v := request.query_params.get("state"):
            qs = qs.filter(state_id=v)
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(CitySerializer(qs, many=True).data)

    def post(self, request):
        s = CitySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=status.HTTP_201_CREATED)


class CityDetailView(_MasterDetailMixin, APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "master.city.manage"
    model = City
    serializer = CitySerializer


# --- Academic / cohort masters -----------------------------------------
#
# All read-open to any authenticated user (so dropdowns work),
# CUD requires the relevant manage perm.

class _ListCreateBase(APIView):
    model = None
    serializer = None
    required_perm = ""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), HasPerm()]

    def get(self, request):
        qs = self.model.objects.all()
        if request.query_params.get("active") == "1" and hasattr(self.model, "is_active"):
            qs = qs.filter(is_active=True)
        return Response(self.serializer(qs, many=True).data)

    def post(self, request):
        s = self.serializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=status.HTTP_201_CREATED)


class _DetailBase(APIView):
    model = None
    serializer = None
    required_perm = ""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), HasPerm()]

    def _obj(self, pk):
        return self.model.objects.get(pk=pk)

    def get(self, request, pk):
        return Response(self.serializer(self._obj(pk)).data)

    def patch(self, request, pk):
        obj = self._obj(pk)
        s = self.serializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        obj = self._obj(pk)
        if hasattr(obj, "is_active"):
            obj.is_active = False
            obj.save(update_fields=["is_active"])
        else:
            obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AcademicYearListCreateView(_ListCreateBase):
    model = AcademicYear
    serializer = AcademicYearSerializer
    required_perm = "master.academicyear.manage"


class AcademicYearDetailView(_DetailBase):
    model = AcademicYear
    serializer = AcademicYearSerializer
    required_perm = "master.academicyear.manage"


class DegreeListCreateView(_ListCreateBase):
    model = Degree
    serializer = DegreeSerializer
    required_perm = "master.degree.manage"


class DegreeDetailView(_DetailBase):
    model = Degree
    serializer = DegreeSerializer
    required_perm = "master.degree.manage"


class CourseListCreateView(_ListCreateBase):
    model = Course
    serializer = CourseSerializer
    required_perm = "master.course.manage"

    def get(self, request):
        qs = Course.objects.select_related("program")
        if v := request.query_params.get("program"):
            qs = qs.filter(program_id=v)
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(CourseSerializer(qs, many=True).data)


class CourseDetailView(_DetailBase):
    model = Course
    serializer = CourseSerializer
    required_perm = "master.course.manage"


class SemesterListCreateView(_ListCreateBase):
    model = Semester
    serializer = SemesterSerializer
    required_perm = "master.semester.manage"


class SemesterDetailView(_DetailBase):
    model = Semester
    serializer = SemesterSerializer
    required_perm = "master.semester.manage"


class BatchListCreateView(_ListCreateBase):
    model = Batch
    serializer = BatchSerializer
    required_perm = "master.batch.manage"

    def get(self, request):
        qs = Batch.objects.select_related("program", "campus", "academic_year", "mentor")
        if v := request.query_params.get("program"):
            qs = qs.filter(program_id=v)
        if v := request.query_params.get("campus"):
            qs = qs.filter(campus_id=v)
        if v := request.query_params.get("academic_year"):
            qs = qs.filter(academic_year_id=v)
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(BatchSerializer(qs, many=True).data)


class BatchDetailView(_DetailBase):
    model = Batch
    serializer = BatchSerializer
    required_perm = "master.batch.manage"


class SubjectListCreateView(_ListCreateBase):
    model = Subject
    serializer = SubjectSerializer
    required_perm = "master.subject.manage"


class SubjectDetailView(_DetailBase):
    model = Subject
    serializer = SubjectSerializer
    required_perm = "master.subject.manage"


class CourseSubjectListCreateView(_ListCreateBase):
    model = CourseSubject
    serializer = CourseSubjectSerializer
    required_perm = "master.subject.manage"

    def get(self, request):
        qs = CourseSubject.objects.select_related("course", "subject")
        if v := request.query_params.get("course"):
            qs = qs.filter(course_id=v)
        if v := request.query_params.get("subject"):
            qs = qs.filter(subject_id=v)
        return Response(CourseSubjectSerializer(qs, many=True).data)


class CourseSubjectDetailView(_DetailBase):
    model = CourseSubject
    serializer = CourseSubjectSerializer
    required_perm = "master.subject.manage"


class ClassroomListCreateView(_ListCreateBase):
    model = Classroom
    serializer = ClassroomSerializer
    required_perm = "master.classroom.manage"

    def get(self, request):
        qs = Classroom.objects.select_related("campus")
        if v := request.query_params.get("campus"):
            qs = qs.filter(campus_id=v)
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(ClassroomSerializer(qs, many=True).data)


class ClassroomDetailView(_DetailBase):
    model = Classroom
    serializer = ClassroomSerializer
    required_perm = "master.classroom.manage"


class TimeSlotListCreateView(_ListCreateBase):
    model = TimeSlot
    serializer = TimeSlotSerializer
    required_perm = "master.timeslot.manage"

    def get(self, request):
        qs = TimeSlot.objects.select_related("academic_year")
        if v := request.query_params.get("academic_year"):
            qs = qs.filter(academic_year_id=v)
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(TimeSlotSerializer(qs, many=True).data)


class TimeSlotDetailView(_DetailBase):
    model = TimeSlot
    serializer = TimeSlotSerializer
    required_perm = "master.timeslot.manage"


class FeeTemplateListCreateView(_ListCreateBase):
    model = FeeTemplate
    serializer = FeeTemplateSerializer
    required_perm = "master.feetemplate.manage"

    def get(self, request):
        qs = FeeTemplate.objects.select_related(
            "academic_year", "campus", "program", "course",
        )
        if v := request.query_params.get("academic_year"):
            qs = qs.filter(academic_year_id=v)
        if v := request.query_params.get("campus"):
            qs = qs.filter(campus_id=v)
        if v := request.query_params.get("program"):
            qs = qs.filter(program_id=v)
        if v := request.query_params.get("course"):
            qs = qs.filter(course_id=v)
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(FeeTemplateSerializer(qs, many=True).data)


class FeeTemplateDetailView(_DetailBase):
    model = FeeTemplate
    serializer = FeeTemplateSerializer
    required_perm = "master.feetemplate.manage"


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
