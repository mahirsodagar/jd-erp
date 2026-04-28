import csv
from datetime import date as _date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.utils import timezone
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPerm
from apps.employees.models import Employee

from .models import (
    CompOffApplication, EmailDispatchLog, Holiday,
    LeaveAllocation, LeaveApplication, LeaveType, Session,
)
from .permissions import LeaveAccessPolicy, get_employee_for, has_perm
from .serializers import (
    BulkAllocationSerializer,
    CancelOrWithdrawSerializer,
    CompOffApplicationSerializer,
    CompOffApplyInputSerializer,
    DecisionSerializer,
    EmailDispatchLogSerializer,
    HolidaySerializer,
    LeaveAllocationSerializer,
    LeaveApplicationSerializer,
    LeaveApplyInputSerializer,
    LeaveTypeSerializer,
    SessionSerializer,
)
from .services import notifications
from .services.balance import all_balances, compute_balance
from .services.day_count import count_days


# --- LeaveType ---------------------------------------------------------

class LeaveTypeListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), HasPerm()]
    required_perm = "leaves.type.manage"

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
    required_perm = "leaves.type.manage"

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


# --- Session -----------------------------------------------------------

class SessionListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), HasPerm()]
    required_perm = "leaves.session.manage"

    def get(self, request):
        qs = Session.objects.all()
        if request.query_params.get("is_current") == "1":
            qs = qs.filter(is_current=True)
        return Response(SessionSerializer(qs, many=True).data)

    def post(self, request):
        s = SessionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        # Run model.clean() to enforce single-current invariant
        instance = Session(**s.validated_data)
        instance.clean()
        instance.save()
        return Response(SessionSerializer(instance).data, status=http.HTTP_201_CREATED)


class SessionDetailView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "leaves.session.manage"

    def patch(self, request, pk):
        obj = Session.objects.get(pk=pk)
        s = SessionSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        for k, v in s.validated_data.items():
            setattr(obj, k, v)
        obj.clean()
        obj.save()
        return Response(SessionSerializer(obj).data)


# --- Allocations -------------------------------------------------------

def _scope_allocations(qs, user):
    if user.is_superuser or has_perm(user, "leaves.application.view_all"):
        return qs
    return qs.filter(employee__campus__in=user.campuses.all())


class AllocationListCreateView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def get(self, request):
        qs = LeaveAllocation.objects.select_related(
            "employee", "session", "leave_type", "created_by"
        )
        qs = _scope_allocations(qs, request.user)
        params = request.query_params
        if v := params.get("employee"):
            qs = qs.filter(employee_id=v)
        if v := params.get("session"):
            qs = qs.filter(session_id=v)
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
                    employee=emp, session=d["session"], leave_type=d["leave_type"],
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
                    employee=emp, session=d["session"], leave_type=d["leave_type"],
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
        return qs.filter(Q(manager_email__iexact=user.email) | Q(approved_by__user_account=user))
    # default: self
    me = get_employee_for(user)
    if me is None:
        return qs.none()
    return qs.filter(employee=me)


def _check_overlap(employee, from_date: _date, to_date: _date,
                   exclude_id: int | None = None) -> bool:
    qs = LeaveApplication.objects.filter(
        employee=employee,
        status__in=[
            LeaveApplication.Status.PENDING,
            LeaveApplication.Status.APPROVED,
        ],
    ).filter(
        from_date__lte=to_date,
        to_date__gte=from_date,
    )
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


def _check_balance(employee, leave_type, from_date, count: Decimal) -> tuple[bool, str]:
    if leave_type.category != LeaveType.Category.LEAVE:
        return True, ""
    # Comp-off: derived pool
    if leave_type.code == "COMP_OFF":
        bal = compute_balance(employee, leave_type, None)["balance"]
        if bal < count:
            return False, f"Comp-off balance is {bal}; requested {count}."
        return True, ""
    # Standard: active allocations covering from_date
    from django.db.models import Sum
    granted = (
        LeaveAllocation.objects.filter(
            employee=employee, leave_type=leave_type,
            start_date__lte=from_date, end_date__gte=from_date,
        ).aggregate(s=Sum("count"))["s"] or Decimal("0")
    )
    used = (
        LeaveApplication.objects.filter(
            employee=employee, leave_type=leave_type,
            status__in=[LeaveApplication.Status.PENDING,
                        LeaveApplication.Status.APPROVED],
        ).aggregate(s=Sum("count"))["s"] or Decimal("0")
    )
    bal = granted - used
    if bal < count:
        return False, f"Balance is {bal}; requested {count}."
    return True, ""


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
        target = d.get("employee") or get_employee_for(request.user)
        if target is None:
            return Response(
                {"detail": "No employee profile linked to this user."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if d.get("employee") and d["employee"] != get_employee_for(request.user):
            if not has_perm(request.user, "leaves.application.approve_any"):
                return Response(
                    {"detail": "HR override needed to apply on behalf of others."},
                    status=http.HTTP_403_FORBIDDEN,
                )

        # Backdate guard
        if d["from_date"] < timezone.now().date() and not d.get("backdate"):
            return Response(
                {"from_date": "Backdated leaves require HR with leaves.application.backdate_apply."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if d.get("backdate") and not has_perm(request.user, "leaves.application.backdate_apply"):
            return Response(
                {"detail": "Permission denied to back-date."},
                status=http.HTTP_403_FORBIDDEN,
            )

        # Overlap
        if _check_overlap(target, d["from_date"], d["to_date"]):
            return Response(
                {"detail": "Overlaps with another active leave application."},
                status=http.HTTP_409_CONFLICT,
            )

        # Day count
        days = count_days(
            employee=target, leave_type=d["leave_type"],
            from_date=d["from_date"], to_date=d["to_date"],
            from_session=d["from_session"],
        )
        if days <= 0 and d["leave_type"].category == LeaveType.Category.LEAVE:
            return Response(
                {"detail": "Computed leave days = 0. All dates are weekends/holidays."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        # Balance check (LEAVE category only)
        if not d.get("force"):
            ok, msg = _check_balance(target, d["leave_type"], d["from_date"], days)
            if not ok:
                return Response({"detail": msg}, status=http.HTTP_400_BAD_REQUEST)
        elif not has_perm(request.user, "leaves.application.override_balance"):
            return Response({"detail": "Permission denied to override balance."},
                            status=http.HTTP_403_FORBIDDEN)

        # Manager email default
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
        # Visibility: applicant, manager, or HR-with-view-all.
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


class LeaveWithdrawView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def patch(self, request, pk):
        try:
            app = LeaveApplication.objects.get(pk=pk)
        except LeaveApplication.DoesNotExist as e:
            raise Http404 from e
        me = get_employee_for(request.user)
        if not me or app.employee_id != me.id:
            return Response({"detail": "Not your application."},
                            status=http.HTTP_403_FORBIDDEN)
        if app.status != LeaveApplication.Status.PENDING:
            return Response({"detail": "Only pending applications can be withdrawn."},
                            status=http.HTTP_400_BAD_REQUEST)
        s = CancelOrWithdrawSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        app.status = LeaveApplication.Status.WITHDRAWN
        app.approver_remarks = s.validated_data["reason"]
        app.decided_on = timezone.now()
        app.save(update_fields=["status", "approver_remarks", "decided_on"])
        return Response(LeaveApplicationSerializer(app).data)


class LeaveCancelView(APIView):
    permission_classes = [IsAuthenticated, LeaveAccessPolicy]

    def patch(self, request, pk):
        try:
            app = LeaveApplication.objects.get(pk=pk)
        except LeaveApplication.DoesNotExist as e:
            raise Http404 from e
        me = get_employee_for(request.user)
        if not me or app.employee_id != me.id:
            return Response({"detail": "Not your application."},
                            status=http.HTTP_403_FORBIDDEN)
        if app.status != LeaveApplication.Status.APPROVED:
            return Response({"detail": "Only approved applications can be cancelled."},
                            status=http.HTTP_400_BAD_REQUEST)
        if app.from_date <= timezone.now().date():
            return Response({"detail": "Cannot cancel after the leave start date."},
                            status=http.HTTP_400_BAD_REQUEST)
        s = CancelOrWithdrawSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        app.status = LeaveApplication.Status.CANCELLED
        app.approver_remarks = s.validated_data["reason"]
        app.decided_on = timezone.now()
        app.save(update_fields=["status", "approver_remarks", "decided_on"])
        notifications.notify_leave_cancelled(app)
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

        sess_id = request.query_params.get("session_id")
        if sess_id:
            try:
                session = Session.objects.get(pk=sess_id)
            except Session.DoesNotExist as e:
                raise Http404 from e
        else:
            session = Session.objects.filter(is_current=True).first()

        return Response(all_balances(emp, session))


# --- Comp-off ----------------------------------------------------------

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
        return Response(compute_balance(me, comp_off_type, None))


# --- Holidays ----------------------------------------------------------

class HolidayListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), HasPerm()]
    required_perm = "leaves.holiday.manage"

    def get(self, request):
        qs = Holiday.objects.select_related("campus")
        if v := request.query_params.get("year"):
            qs = qs.filter(date__year=v)
        if v := request.query_params.get("month"):
            qs = qs.filter(date__month=v)
        if v := request.query_params.get("campus"):
            qs = qs.filter(Q(campus_id=v) | Q(campus__isnull=True))
        return Response(HolidaySerializer(qs, many=True).data)

    def post(self, request):
        s = HolidaySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=http.HTTP_201_CREATED)


class HolidayDetailView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "leaves.holiday.manage"

    def patch(self, request, pk):
        try:
            obj = Holiday.objects.get(pk=pk)
        except Holiday.DoesNotExist as e:
            raise Http404 from e
        s = HolidaySerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        try:
            obj = Holiday.objects.get(pk=pk)
        except Holiday.DoesNotExist as e:
            raise Http404 from e
        obj.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# --- Reports -----------------------------------------------------------

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
        from django.utils.dateparse import parse_date
        start = parse_date(params.get("start_date") or "")
        end = parse_date(params.get("end_date") or "")
        if not start or not end:
            return Response({"detail": "start_date and end_date are required."},
                            status=http.HTTP_400_BAD_REQUEST)

        qs = LeaveApplication.objects.select_related(
            "employee", "employee__campus", "employee__department", "leave_type",
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

        # JSON or CSV? `output=csv` instead of `format=csv` because
        # DRF reserves `?format=` for content-negotiation.
        if (params.get("output") or "").lower() == "csv":
            return self._csv(qs)

        rows = [{
            "id": a.id,
            "emp_code": a.employee.emp_code,
            "employee": a.employee.full_name,
            "campus": a.employee.campus.name,
            "department": a.employee.department.name,
            "leave_type": a.leave_type.code,
            "from_date": a.from_date,
            "to_date": a.to_date,
            "count": str(a.count),
            "status": a.get_status_display(),
            "applied_on": a.applied_on,
            "decided_on": a.decided_on,
        } for a in qs[:5000]]
        return Response({"count": len(rows), "rows": rows})

    def _csv(self, qs):
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="leave_report.csv"'
        w = csv.writer(resp)
        w.writerow(["emp_code", "employee", "campus", "department", "leave_type",
                    "from_date", "to_date", "count", "status",
                    "applied_on", "decided_on"])
        for a in qs.iterator():
            w.writerow([
                a.employee.emp_code, a.employee.full_name,
                a.employee.campus.name, a.employee.department.name,
                a.leave_type.code,
                a.from_date, a.to_date, a.count, a.get_status_display(),
                a.applied_on.isoformat(), a.decided_on.isoformat() if a.decided_on else "",
            ])
        return resp


# --- Email log (HR / superuser only) ------------------------------------

class EmailLogListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not (u.is_superuser or has_perm(u, "leaves.application.view_all")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        qs = EmailDispatchLog.objects.all()[:500]
        return Response(EmailDispatchLogSerializer(qs, many=True).data)
