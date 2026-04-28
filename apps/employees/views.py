import secrets

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status as http
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPerm

from .models import Department, Designation, Employee
from .pagination import EmployeePagination
from .permissions import (
    EmployeeAccessPolicy,
    can_view_all_campuses,
    filter_visible,
    has_perm,
    is_self,
)
from .serializers import (
    DepartmentSerializer,
    DesignationSerializer,
    EmployeeCreateSerializer,
    EmployeeDetailSerializer,
    EmployeeListSerializer,
    EmployeeSelfUpdateSerializer,
    EmployeeUpdateSerializer,
    PortalAccountSerializer,
    StatusToggleSerializer,
)
from .services import (
    generate_emp_code, make_thumbnail, regenerate_qr, render_id_card,
)

User = get_user_model()


# --- Department / Designation (master CRUD) ----------------------------
#
# Listing is open to any authenticated user (so the Add Employee form can
# populate dropdowns); CUD requires `employees.master.manage`.

class _MasterListCreate(APIView):
    model = None
    serializer = None
    required_perm = "employees.master.manage"

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), HasPerm()]

    def get(self, request):
        qs = self.model.objects.all()
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(self.serializer(qs, many=True).data)

    def post(self, request):
        s = self.serializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=http.HTTP_201_CREATED)


class DepartmentListCreateView(_MasterListCreate):
    model = Department
    serializer = DepartmentSerializer


class DesignationListCreateView(_MasterListCreate):
    model = Designation
    serializer = DesignationSerializer


class _MasterDetail(APIView):
    model = None
    serializer = None
    required_perm = "employees.master.manage"

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), HasPerm()]

    def _obj(self, pk):
        try:
            return self.model.objects.get(pk=pk)
        except self.model.DoesNotExist as e:
            raise Http404 from e

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
        return Response(status=http.HTTP_204_NO_CONTENT)


class DepartmentDetailView(_MasterDetail):
    model = Department
    serializer = DepartmentSerializer


class DesignationDetailView(_MasterDetail):
    model = Designation
    serializer = DesignationSerializer


# --- Employees ---------------------------------------------------------

def _apply_filters(qs, params):
    if v := params.get("campus"):
        qs = qs.filter(campus_id=v)
    if v := params.get("department"):
        qs = qs.filter(department_id=v)
    if v := params.get("designation"):
        qs = qs.filter(designation_id=v)
    if v := params.get("institute"):
        qs = qs.filter(institute_id=v)
    if v := params.get("employment_type"):
        qs = qs.filter(employment_type=v)
    if v := params.get("status"):
        qs = qs.filter(status=v)
    if v := params.get("gender"):
        qs = qs.filter(gender=v)
    if v := params.get("nationality"):
        qs = qs.filter(nationality=v)
    if v := params.get("created_after"):
        if d := parse_date(v):
            qs = qs.filter(created_on__date__gte=d)
    if v := params.get("created_before"):
        if d := parse_date(v):
            qs = qs.filter(created_on__date__lte=d)
    if q := params.get("search"):
        from django.db.models import Q
        qs = qs.filter(
            Q(emp_code__icontains=q)
            | Q(first_name__icontains=q)
            | Q(family_name__icontains=q)
            | Q(email_primary__icontains=q)
            | Q(mobile_primary__icontains=q)
        )
    return qs


def _apply_ordering(qs, params):
    allowed = {"emp_code", "first_name", "date_of_joining", "created_on"}
    raw = params.get("ordering", "-created_on")
    fields = []
    for token in raw.split(","):
        bare = token.lstrip("-")
        if bare in allowed:
            fields.append(token)
    return qs.order_by(*fields) if fields else qs


class EmployeeListCreateView(APIView):
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    pagination_class = EmployeePagination

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), EmployeeAccessPolicy()]
        return [IsAuthenticated()]   # create perm checked manually below

    def get(self, request):
        params = request.query_params

        if params.get("include_deleted") == "1":
            if not (request.user.is_superuser
                    or has_perm(request.user, "employees.employee.manage_deleted")):
                return Response({"detail": "Permission denied."},
                                status=http.HTTP_403_FORBIDDEN)
            qs = Employee.all_objects.all()
        else:
            qs = Employee.objects.all()

        qs = filter_visible(qs, request.user)
        qs = _apply_filters(qs, params)
        qs = _apply_ordering(qs, params)
        qs = qs.select_related(
            "designation", "department", "campus", "institute",
        )

        paginator = EmployeePagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        ser = EmployeeListSerializer(page, many=True, context={"request": request})
        return paginator.get_paginated_response(ser.data)

    def post(self, request):
        if not has_perm(request.user, "employees.employee.create"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        s = EmployeeCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        campus = s.validated_data["campus"]
        if not (request.user.is_superuser
                or has_perm(request.user, "employees.employee.add_in_any_campus")
                or request.user.campuses.filter(pk=campus.pk).exists()):
            return Response({"detail": "Campus not in your scope."},
                            status=http.HTTP_403_FORBIDDEN)

        with transaction.atomic():
            data = dict(s.validated_data)
            photo = data.pop("photo", None)
            if not data.get("emp_code"):
                data["emp_code"] = generate_emp_code(campus_code=campus.code)

            emp = Employee(**data, created_by=request.user, updated_by=request.user)
            emp.save()
            if photo:
                emp.photo.save("photo.jpg", make_thumbnail(photo), save=True)
            regenerate_qr(emp)

        return Response(
            EmployeeDetailSerializer(emp, context={"request": request}).data,
            status=http.HTTP_201_CREATED,
        )


class EmployeeDetailView(APIView):
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    permission_classes = [IsAuthenticated, EmployeeAccessPolicy]

    def _obj(self, request, pk, *, with_deleted: bool = False):
        manager = Employee.all_objects if with_deleted else Employee.objects
        try:
            emp = manager.get(pk=pk)
        except Employee.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, emp)
        return emp

    def get(self, request, pk):
        emp = self._obj(request, pk)
        return Response(EmployeeDetailSerializer(emp, context={"request": request}).data)

    def patch(self, request, pk):
        emp = self._obj(request, pk)
        u = request.user

        full_edit = u.is_superuser or has_perm(u, "employees.employee.edit")
        self_edit = is_self(u, emp)

        if full_edit:
            cls = EmployeeUpdateSerializer
        elif self_edit:
            cls = EmployeeSelfUpdateSerializer
        else:
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        s = cls(emp, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        photo = s.validated_data.pop("photo", None)
        for k, v in s.validated_data.items():
            setattr(emp, k, v)
        emp.updated_by = u
        emp.save()
        if photo is not None:
            emp.photo.save("photo.jpg", make_thumbnail(photo), save=True)
        return Response(EmployeeDetailSerializer(emp, context={"request": request}).data)

    def delete(self, request, pk):
        emp = self._obj(request, pk)
        if not (request.user.is_superuser
                or has_perm(request.user, "employees.employee.delete")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        emp.soft_delete(user=request.user)
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- Status toggle -----------------------------------------------------

class _StatusBase(APIView):
    permission_classes = [IsAuthenticated, EmployeeAccessPolicy, HasPerm]
    required_perm = "employees.employee.change_status"
    target_status: int = 0
    require_reason: bool = False

    def post(self, request, pk):
        try:
            emp = Employee.objects.get(pk=pk)
        except Employee.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, emp)

        s = StatusToggleSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if self.require_reason and not s.validated_data.get("reason"):
            return Response({"reason": "Reason is required (≥ 5 chars)."},
                            status=http.HTTP_400_BAD_REQUEST)

        emp.status = self.target_status
        emp.updated_by = request.user
        emp.save(update_fields=["status", "updated_by", "updated_on"])
        return Response(EmployeeDetailSerializer(emp, context={"request": request}).data)


class EmployeeActivateView(_StatusBase):
    target_status = Employee.Status.ACTIVE


class EmployeeDeactivateView(_StatusBase):
    target_status = Employee.Status.INACTIVE
    require_reason = True


# --- Files: ID card + QR -----------------------------------------------

class EmployeeIdCardView(APIView):
    permission_classes = [IsAuthenticated, EmployeeAccessPolicy]

    def get(self, request, pk):
        try:
            emp = Employee.objects.get(pk=pk)
        except Employee.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, emp)
        png = render_id_card(emp)
        resp = HttpResponse(png, content_type="image/png")
        resp["Content-Disposition"] = f'inline; filename="id-card-{emp.emp_code}.png"'
        return resp


class EmployeeQrView(APIView):
    permission_classes = [IsAuthenticated, EmployeeAccessPolicy]

    def get(self, request, pk):
        try:
            emp = Employee.objects.get(pk=pk)
        except Employee.DoesNotExist as e:
            raise Http404 from e
        self.check_object_permissions(request, emp)
        if not emp.qr_code:
            regenerate_qr(emp)
        return HttpResponse(emp.qr_code.read(), content_type="image/png")


# --- Portal account ----------------------------------------------------

class EmployeePortalAccountView(APIView):
    """HR creates a `User` for the employee and links it via OneToOne.

    Returns the temporary password ONCE in the response — there is no
    email delivery on PA free. Caller must copy it now or reset later.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not (u.is_superuser
                or (has_perm(u, "accounts.user.manage")
                    and has_perm(u, "employees.employee.edit"))):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        try:
            emp = Employee.objects.get(pk=pk)
        except Employee.DoesNotExist as e:
            raise Http404 from e

        if emp.user_account_id:
            return Response({"detail": "Portal account already exists."},
                            status=http.HTTP_409_CONFLICT)

        s = PortalAccountSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        username = s.validated_data["username"]
        if User.objects.filter(username__iexact=username).exists():
            return Response({"username": "Username already in use."},
                            status=http.HTTP_400_BAD_REQUEST)

        temp_pw = secrets.token_urlsafe(12)
        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=emp.email_primary,
                full_name=emp.full_name,
                password=temp_pw,
            )
            if role_ids := s.validated_data.get("role_ids"):
                user.roles.set(role_ids)
            user.campuses.add(emp.campus)
            emp.user_account = user
            emp.save(update_fields=["user_account"])

        return Response(
            {
                "user_id": user.id,
                "username": user.username,
                "temporary_password": temp_pw,
                "note": ("Save this password now — it is shown once. "
                         "Email delivery is not configured on this host."),
            },
            status=http.HTTP_201_CREATED,
        )
