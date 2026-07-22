import csv

from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPerm
from apps.employees.models import Employee

from .models import (
    CompOffApplication, LeaveAllocation, LeaveApplication, LeaveType,
)
from .permissions import LeaveAccessPolicy, get_employee_for, has_perm
from .serializers import (
    BulkAllocationSerializer,
    CompOffApplicationSerializer,
    CompOffApplyInputSerializer,
    DecisionSerializer,
    LeaveAllocationSerializer,
    LeaveApplicationSerializer,
    LeaveApplyInputSerializer,
    LeaveTypeSerializer,
)
from .services import notifications
from .services.balance import all_balances, cl_dashboard, compute_balance
from .services.day_count import count_days


# --- LeaveType ---------------------------------------------------------

class LeaveTypeListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), HasPerm()]
    perm_base = "leaves.type"

    def get(self, request):
        qs = LeaveType.objects.all()
        if request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return Response(LeaveTypeSerializer(qs, many=True).data)

    def post(self, request):
        s = LeaveTypeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=http.HTTP_201_CREATED)


class LeaveTypeDetailView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    perm_base = "leaves.type"

    def patch(self, request, pk):
        obj = LeaveType.objects.get(pk=pk)
        s = LeaveTypeSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        obj = LeaveType.objects.get(pk=pk)
        obj.is_active = False
        obj.save(update_fields=["is_active"])
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- Allocations (HR bulk grant — legacy assign_leaves.php) -------------

def _scope_allocations(qs, user):
    if user.is_superuser or has_perm(user, "leaves.application.view_all"):
        return qs
    return qs.filter(employee__campus__in=user.campuses.all())


class AllocationListCreateView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def get(self, request):
        qs = LeaveAllocation.objects.select_related(
            "employee", "leave_type", "created_by"
        )
        qs = _scope_allocations(qs, request.user)
        params = request.query_params
        if v := params.get("employee"):
            qs = qs.filter(employee_id=v)
        if v := params.get("leave_type"):
            qs = qs.filter(leave_type_id=v)
        if v := params.get("campus"):
            qs = qs.filter(employee__campus_id=v)
        if v := params.get("department"):
            qs = qs.filter(employee__department_id=v)
        return Response(LeaveAllocationSerializer(qs[:1000], many=True).data)

    def post(self, request):
        if not has_perm(request.user, "leaves.allocation.add"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        s = LeaveAllocationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(created_by=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


class AllocationDetailView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def delete(self, request, pk):
        if not has_perm(request.user, "leaves.allocation.delete"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)
        try:
            alloc = LeaveAllocation.objects.get(pk=pk)
        except LeaveAllocation.DoesNotExist as e:
            raise Http404 from e
        consumed = LeaveApplication.objects.filter(
            employee=alloc.employee, leave_type=alloc.leave_type,
            from_date__gte=alloc.start_date, from_date__lte=alloc.end_date,
            status=LeaveApplication.Status.APPROVED,
        ).exists()
        if consumed:
            return Response(
                {"detail": "Allocation already consumed by approved leaves."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        alloc.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


class BulkAllocationView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def post(self, request):
        if not has_perm(request.user, "leaves.allocation.add"):
            return Response({"detail": "Permission denied."}, status=http.HTTP_403_FORBIDDEN)

        s = BulkAllocationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        created, skipped = [], []
        with transaction.atomic():
            for emp_id in d["employee_ids"]:
                try:
                    emp = Employee.objects.get(pk=emp_id)
                except Employee.DoesNotExist:
                    skipped.append({"employee": emp_id, "reason": "not found"})
                    continue
                exists = LeaveAllocation.objects.filter(
                    employee=emp, leave_type=d["leave_type"],
                    start_date=d["start_date"], end_date=d["end_date"],
                ).exists()
                if exists:
                    if d["skip_existing"]:
                        skipped.append({"employee": emp_id, "reason": "already allocated"})
                        continue
                    return Response(
                        {"detail": f"Duplicate allocation for employee {emp_id}."},
                        status=http.HTTP_400_BAD_REQUEST,
                    )
                alloc = LeaveAllocation.objects.create(
                    employee=emp, leave_type=d["leave_type"],
                    count=d["count"], start_date=d["start_date"], end_date=d["end_date"],
                    created_by=request.user,
                )
                created.append(alloc.id)
        return Response({"created": created, "skipped": skipped},
                        status=http.HTTP_201_CREATED)


# --- Leave applications ------------------------------------------------

def _scope_applications(qs, user, scope: str):
    if scope == "all":
        if not (user.is_superuser or has_perm(user, "leaves.application.view_all")):
            return qs.none()
        return qs
    if scope == "team":
        # Legacy: manager sees leaves whose manager_mail snapshot == their email.
        return qs.filter(manager_email__iexact=user.email)
    me = get_employee_for(user)
    if me is None:
        return qs.none()
    return qs.filter(employee=me)


class LeaveApplicationListCreateView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def get(self, request):
        scope = request.query_params.get("scope", "self")
        qs = LeaveApplication.objects.select_related(
            "employee", "leave_type", "approved_by"
        )
        qs = _scope_applications(qs, request.user, scope)
        params = request.query_params
        if v := params.get("status"):
            qs = qs.filter(status=v)
        if v := params.get("leave_type"):
            qs = qs.filter(leave_type_id=v)
        if v := params.get("employee"):
            qs = qs.filter(employee_id=v)
        return Response(LeaveApplicationSerializer(qs[:500], many=True).data)

    def post(self, request):
        s = LeaveApplyInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        # Resolve target employee — self by default; HR can override.
        me = get_employee_for(request.user)
        target = d.get("employee") or me
        if target is None:
            return Response(
                {"detail": "No employee profile linked to this user."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if d.get("employee") and d["employee"] != me:
            if not has_perm(request.user, "leaves.application.approve_any"):
                return Response(
                    {"detail": "HR override needed to apply on behalf of others."},
                    status=http.HTTP_403_FORBIDDEN,
                )

        # Legacy day count — plain calendar days (no weekend/holiday netting).
        days = count_days(
            employee=target, leave_type=d["leave_type"],
            from_date=d["from_date"], to_date=d["to_date"],
            from_session=d["from_session"],
        )

        # Manager email snapshot (default: reporting manager 1).
        manager_email = d.get("manager_email") or ""
        if not manager_email:
            rm = target.reporting_manager_1
            manager_email = rm.email_primary if rm else ""
        if not manager_email:
            return Response(
                {"manager_email": "No manager email available."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        app = LeaveApplication.objects.create(
            employee=target,
            leave_type=d["leave_type"],
            from_date=d["from_date"], to_date=d["to_date"],
            from_session=d["from_session"], count=days,
            reason=d["reason"],
            manager_email=manager_email,
            cc_emails=d.get("cc_emails", "") or "",
        )
        notifications.notify_leave_applied(app)
        return Response(LeaveApplicationSerializer(app).data,
                        status=http.HTTP_201_CREATED)


class LeaveApplicationDetailView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def get(self, request, pk):
        try:
            app = LeaveApplication.objects.select_related(
                "employee", "leave_type", "approved_by"
            ).get(pk=pk)
        except LeaveApplication.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        me = get_employee_for(u)
        allowed = (
            u.is_superuser
            or has_perm(u, "leaves.application.view_all")
            or (me and app.employee_id == me.id)
            or app.manager_email.lower() == (u.email or "").lower()
        )
        if not allowed:
            raise Http404
        return Response(LeaveApplicationSerializer(app).data)

    def delete(self, request, pk):
        # Legacy leave_report.php delete — privileged HR only.
        if not (request.user.is_superuser
                or has_perm(request.user, "leaves.report.delete")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            app = LeaveApplication.objects.get(pk=pk)
        except LeaveApplication.DoesNotExist as e:
            raise Http404 from e
        app.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


class LeaveDecisionView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def patch(self, request, pk):
        try:
            app = LeaveApplication.objects.select_related("employee").get(pk=pk)
        except LeaveApplication.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        is_manager = app.manager_email.lower() == (u.email or "").lower()
        can_decide = (
            u.is_superuser
            or has_perm(u, "leaves.application.approve_any")
            or is_manager
        )
        if not can_decide:
            return Response({"detail": "Not the manager for this leave."},
                            status=http.HTTP_403_FORBIDDEN)

        if app.status != LeaveApplication.Status.PENDING:
            return Response({"detail": "Application is not pending."},
                            status=http.HTTP_400_BAD_REQUEST)

        s = DecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        app.status = s.validated_data["status"]
        app.approver_remarks = s.validated_data.get("remarks", "")
        app.approved_by = get_employee_for(u)
        app.decided_on = timezone.now()
        app.save(update_fields=["status", "approver_remarks", "approved_by", "decided_on"])

        notifications.notify_leave_decision(app)
        return Response(LeaveApplicationSerializer(app).data)


class LeaveBalancesView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def get(self, request):
        emp_id = request.query_params.get("employee_id")
        if emp_id:
            if not (request.user.is_superuser
                    or has_perm(request.user, "leaves.application.view_all")):
                return Response({"detail": "HR perm required to query other employees."},
                                status=http.HTTP_403_FORBIDDEN)
            try:
                emp = Employee.objects.get(pk=emp_id)
            except Employee.DoesNotExist as e:
                raise Http404 from e
        else:
            emp = get_employee_for(request.user)
            if emp is None:
                return Response({"detail": "No employee profile linked to this user."},
                                status=http.HTTP_400_BAD_REQUEST)
        return Response(all_balances(emp))


class LeaveDashboardView(APIView):
    """Legacy leave_apply.php dashboard counters (fixed leave-year + CL accrual)."""
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def get(self, request):
        emp = get_employee_for(request.user)
        if emp is None:
            return Response({"detail": "No employee profile linked to this user."},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(cl_dashboard(emp))


# --- Comp-off (legacy compoff_apply.php) -------------------------------

class CompOffListCreateView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def get(self, request):
        scope = request.query_params.get("scope", "self")
        qs = CompOffApplication.objects.select_related("employee", "approver")
        if scope == "all":
            if not (request.user.is_superuser
                    or has_perm(request.user, "leaves.compoff.view_all")):
                return Response([], status=http.HTTP_200_OK)
        elif scope == "team":
            qs = qs.filter(employee__reporting_manager_1__user_account=request.user)
        else:
            me = get_employee_for(request.user)
            qs = qs.filter(employee=me) if me else qs.none()
        return Response(CompOffApplicationSerializer(qs[:500], many=True).data)

    def post(self, request):
        from decimal import Decimal
        s = CompOffApplyInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        target = d.get("employee") or get_employee_for(request.user)
        if target is None:
            return Response({"detail": "No employee profile linked."},
                            status=http.HTTP_400_BAD_REQUEST)
        count = Decimal("1.0") if (d["worked_session_1"] + d["worked_session_2"] == 2) else Decimal("0.5")
        co = CompOffApplication.objects.create(
            employee=target,
            worked_date=d["worked_date"],
            worked_session_1=d["worked_session_1"],
            worked_session_2=d["worked_session_2"],
            count=count,
            reason=d["reason"],
        )
        notifications.notify_compoff_applied(co)
        return Response(CompOffApplicationSerializer(co).data,
                        status=http.HTTP_201_CREATED)


class CompOffDecisionView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def patch(self, request, pk):
        try:
            co = CompOffApplication.objects.select_related("employee").get(pk=pk)
        except CompOffApplication.DoesNotExist as e:
            raise Http404 from e
        u = request.user
        emp = co.employee
        is_manager = emp.reporting_manager_1 and emp.reporting_manager_1.user_account_id == u.id
        if not (u.is_superuser or has_perm(u, "leaves.compoff.approve_any") or is_manager):
            return Response({"detail": "Not the manager for this comp-off."},
                            status=http.HTTP_403_FORBIDDEN)
        if co.status != CompOffApplication.Status.PENDING:
            return Response({"detail": "Already decided."},
                            status=http.HTTP_400_BAD_REQUEST)
        s = DecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        co.status = s.validated_data["status"]
        co.approver = get_employee_for(u)
        co.approver_remarks = s.validated_data.get("remarks", "")
        co.decided_on = timezone.now()
        co.save(update_fields=["status", "approver", "approver_remarks", "decided_on"])
        notifications.notify_compoff_decision(co)
        return Response(CompOffApplicationSerializer(co).data)


class CompOffBalanceView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def get(self, request):
        me = get_employee_for(request.user)
        if me is None:
            return Response({"detail": "No employee profile linked."},
                            status=http.HTTP_400_BAD_REQUEST)
        try:
            comp_off_type = LeaveType.objects.get(code="COMP_OFF")
        except LeaveType.DoesNotExist:
            return Response({"earned": "0.0", "used": "0.0", "balance": "0.0"})
        return Response(compute_balance(me, comp_off_type))


# --- Reports (legacy leave_report.php) ---------------------------------

def _scope_report(qs, user):
    if user.is_superuser or has_perm(user, "leaves.report.view_all"):
        return qs
    if has_perm(user, "leaves.report.view"):
        return qs.filter(employee__campus__in=user.campuses.all())
    return qs.none()


class LeaveReportSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not (u.is_superuser
                or has_perm(u, "leaves.report.view")
                or has_perm(u, "leaves.report.view_all")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        params = request.query_params
        start = parse_date(params.get("start_date") or "")
        end = parse_date(params.get("end_date") or "")
        if not start or not end:
            return Response({"detail": "start_date and end_date are required."},
                            status=http.HTTP_400_BAD_REQUEST)

        qs = LeaveApplication.objects.select_related(
            "employee", "employee__campus", "employee__department",
            "leave_type", "approved_by",
        ).filter(from_date__gte=start, to_date__lte=end)
        qs = _scope_report(qs, u)
        if v := params.get("campus"):
            qs = qs.filter(employee__campus_id=v)
        if v := params.get("department"):
            qs = qs.filter(employee__department_id=v)
        if v := params.get("leave_type"):
            qs = qs.filter(leave_type_id=v)
        if v := params.get("status"):
            qs = qs.filter(status=v)

        if (params.get("output") or "").lower() == "csv":
            return self._csv(qs)

        rows = [{
            "id": a.id,
            "emp_code": a.employee.emp_code,
            "employee": a.employee.full_name,
            "campus": a.employee.campus.name,
            "department": a.employee.department.name,
            "leave_type": a.leave_type.name,
            "applied_for": a.leave_type.get_category_display(),
            "from_date": a.from_date,
            "to_date": a.to_date,
            "count": str(a.count),
            "reason": a.reason,
            "status": a.get_status_display(),
            "approver": a.approved_by.full_name if a.approved_by else "",
            "approver_remarks": a.approver_remarks,
            "applied_on": a.applied_on,
            "decided_on": a.decided_on,
        } for a in qs[:5000]]
        return Response({"count": len(rows), "rows": rows})

    def _csv(self, qs):
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="leave_report.csv"'
        w = csv.writer(resp)
        w.writerow(["emp_code", "employee", "campus", "department", "leave_type",
                    "applied_for", "from_date", "to_date", "count", "reason",
                    "status", "approver", "approver_remarks",
                    "applied_on", "decided_on"])
        for a in qs.iterator():
            w.writerow([
                a.employee.emp_code, a.employee.full_name,
                a.employee.campus.name, a.employee.department.name,
                a.leave_type.name, a.leave_type.get_category_display(),
                a.from_date, a.to_date, a.count, a.reason,
                a.get_status_display(),
                a.approved_by.full_name if a.approved_by else "",
                a.approver_remarks,
                a.applied_on.isoformat(),
                a.decided_on.isoformat() if a.decided_on else "",
            ])
        return resp
