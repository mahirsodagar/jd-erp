from datetime import date as _date
from decimal import Decimal

from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.employees.models import Employee
from apps.master.models import Batch
from apps.roles.models import Role

from django.db import transaction
from django.db.models import Q, Sum

from apps.common.csv_export import csv_response, fmt_date, wants_csv
from apps.common.pagination import PaginatedAPIViewMixin, StandardPagination

from . import freeze
from .models import (
    AdminDailyReport, AuditAnswer, AuditForm, AuditFormField, AuditSubmission,
    BatchMentorReport, ComplianceFlag, CourseEndReport, DailyReportAccess,
    FacultyDailyReport, FacultySelfAppraisal, StudentFeedback, ZeroHourReport,
)
from .permissions import has_perm
from .serializers import (
    AdminDailyReportSerializer, AuditFormRoleSerializer, AuditFormSerializer,
    AuditSubmissionSerializer,
    BatchMentorReportSerializer,
    ComplianceFlagSerializer, CourseEndReportSerializer,
    CourseEndReviewSerializer, DailyReportAccessDecisionSerializer,
    DailyReportAccessGrantSerializer, DailyReportAccessSerializer,
    FacultyDailyReportSerializer,
    FacultySelfAppraisalSerializer, ResolveFlagSerializer,
    SelfAppraisalReviewSerializer, StudentFeedbackSerializer,
    SubmitAuditFormSerializer, ZeroHourReportSerializer,
)
from .services import (
    batch_progression, consolidated_monthly,
    faculty_daily_computed, feedback_summary_for_instructor,
    live_faculty_tracking, timetable_adherence,
)


def _emp_of(user) -> Employee | None:
    return getattr(user, "employee", None)


def _student_of(user):
    return getattr(user, "student", None)


# === 1. Faculty Daily Report ========================================

# Two-permission model:
#   dashboard.daily_report.submit → fill / see / edit / delete own report
#   audit.faculty_daily.view_all  → auditors' read-only sight of everyone's
# Nobody edits another faculty's report (no submit-on-behalf).

def _fd_can_view(user, *, is_own: bool) -> bool:
    if (has_perm(user, "audit.faculty_daily.view_all")
            or has_perm(user, "audit.faculty_daily.edit_any")
            or has_perm(user, "audit.faculty_daily.delete_any")):
        return True
    return is_own and has_perm(user, "dashboard.daily_report.submit")


def _fd_can_manage(user, *, is_own: bool) -> bool:
    """Create / upsert — own rows only. There is no submit-on-behalf."""
    return bool(
        user.is_superuser
        or (is_own and has_perm(user, "dashboard.daily_report.submit"))
    )


def _fd_can_edit(user, *, is_own: bool) -> bool:
    """Own row with `submit`, or anyone's with `edit_any`."""
    return (_fd_can_manage(user, is_own=is_own)
            or has_perm(user, "audit.faculty_daily.edit_any"))


def _fd_can_delete(user, *, is_own: bool) -> bool:
    """Own row with `submit`, or anyone's with `delete_any`."""
    return (_fd_can_manage(user, is_own=is_own)
            or has_perm(user, "audit.faculty_daily.delete_any"))


def _fd_is_own(user, faculty_id) -> bool:
    emp = _emp_of(user)
    return bool(emp and faculty_id == emp.id)


_FD_DEFAULT_FIELDS = (
    "academic_description", "academic_hours",
    "non_academic_description", "non_academic_hours",
    "others_description", "others_hours",
)


class FacultyDailyReportListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = FacultyDailyReport.objects.select_related("faculty")
        # `*_any` holders need to reach the rows they may edit / delete,
        # otherwise the permission is unusable without `view_all` too.
        if not (has_perm(u, "audit.faculty_daily.view_all")
                or has_perm(u, "audit.faculty_daily.edit_any")
                or has_perm(u, "audit.faculty_daily.delete_any")):
            # Restricted to own rows — requires the dashboard submit perm.
            emp = _emp_of(u)
            if emp is None or not has_perm(u, "dashboard.daily_report.submit"):
                return Response([])
            qs = qs.filter(faculty=emp)
        params = request.query_params
        if v := params.get("faculty"):
            qs = qs.filter(faculty_id=v)
        if v := params.get("from"):
            if d := parse_date(v):
                qs = qs.filter(date__gte=d)
        if v := params.get("to"):
            if d := parse_date(v):
                qs = qs.filter(date__lte=d)
        return Response(FacultyDailyReportSerializer(qs[:500], many=True).data)

    def post(self, request):
        """Upsert one (faculty, date) row — the grid's per-day Save."""
        u = request.user
        s = FacultyDailyReportSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        target = data["faculty"]
        is_own = _fd_is_own(u, target.id)
        if not _fd_can_manage(u, is_own=is_own):
            return Response(
                {"detail": "You can only submit your own daily report."},
                status=http.HTTP_403_FORBIDDEN)
        if blocked := freeze.write_blocked_reason(u, freeze.REPORT_FACULTY, data["date"]):
            return Response({"detail": blocked, "code": "frozen"},
                            status=http.HTTP_423_LOCKED)
        defaults = {f: data.get(f, "" if "description" in f else 0)
                    for f in _FD_DEFAULT_FIELDS}
        defaults["submitted_by"] = u
        obj, created = FacultyDailyReport.objects.update_or_create(
            faculty=target, date=data["date"], defaults=defaults,
        )
        return Response(
            FacultyDailyReportSerializer(obj).data,
            status=http.HTTP_201_CREATED if created else http.HTTP_200_OK)


class FacultyDailyReportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return FacultyDailyReport.objects.get(pk=pk)
        except FacultyDailyReport.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        obj = self._obj(pk)
        if not _fd_can_view(request.user,
                            is_own=_fd_is_own(request.user, obj.faculty_id)):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response(FacultyDailyReportSerializer(obj).data)

    def patch(self, request, pk):
        obj = self._obj(pk)
        if not _fd_can_edit(request.user,
                            is_own=_fd_is_own(request.user, obj.faculty_id)):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if blocked := freeze.write_blocked_reason(
                request.user, freeze.REPORT_FACULTY, obj.date):
            return Response({"detail": blocked, "code": "frozen"},
                            status=http.HTTP_423_LOCKED)
        s = FacultyDailyReportSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        obj = self._obj(pk)
        if not _fd_can_delete(request.user,
                              is_own=_fd_is_own(request.user, obj.faculty_id)):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if blocked := freeze.write_blocked_reason(
                request.user, freeze.REPORT_FACULTY, obj.date):
            return Response({"detail": blocked, "code": "frozen"},
                            status=http.HTTP_423_LOCKED)
        obj.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


class FacultyDailyComputedView(APIView):
    """Per-day class hours (attendance-marked slots only), missed hours
    and leave hours for one faculty."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        fid = request.query_params.get("faculty")
        if not fid:
            return Response({"detail": "faculty is required."},
                            status=http.HTTP_400_BAD_REQUEST)
        try:
            emp = Employee.objects.get(pk=fid)
        except (Employee.DoesNotExist, ValueError) as e:
            raise Http404 from e
        if not _fd_can_view(request.user,
                            is_own=_fd_is_own(request.user, emp.id)):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        start = parse_date(request.query_params.get("from") or "")
        end = parse_date(request.query_params.get("to") or "")
        if not (start and end):
            return Response({"detail": "from and to are required."},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(
            faculty_daily_computed(faculty=emp, start=start, end=end))


# === Audit filter lookups ===========================================
# Lightweight campus / academic-year / employee pickers for the audit
# cascades, gated on any audit view permission so auditors don't also
# need master.* / employees.* view perms. Campuses/employees are scoped
# to the auditor's assigned campuses (superusers see all).

def _can_use_audit_filters(user) -> bool:
    return bool(
        has_perm(user, "audit.faculty_daily.view_all")
        or has_perm(user, "audit.admin_daily.view_all")
        or has_perm(user, "audit.faculty_daily.edit_any")
        or has_perm(user, "audit.admin_daily.edit_any")
    )


def _assigned_campus_ids(user):
    return list(user.campuses.values_list("id", flat=True))


class AuditFilterOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not _can_use_audit_filters(u):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        from apps.master.models import AcademicYear, Campus
        campuses = Campus.objects.all().order_by("name")
        mine = _assigned_campus_ids(u)
        if not u.is_superuser and mine:
            campuses = campuses.filter(id__in=mine)
        return Response({
            "campuses": [
                {"id": c.id, "name": c.name, "code": c.code} for c in campuses
            ],
            "academic_years": [
                {"id": y.id, "code": y.code, "full_name": y.full_name,
                 "start_date": y.start_date, "end_date": y.end_date,
                 "is_current": y.is_current}
                for y in AcademicYear.objects.all()
            ],
        })


class AuditFilterEmployeesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not _can_use_audit_filters(u):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        campus = request.query_params.get("campus")
        if not campus:
            return Response([])
        mine = _assigned_campus_ids(u)
        try:
            if not u.is_superuser and mine and int(campus) not in mine:
                return Response([])
        except (TypeError, ValueError):
            return Response([])
        qs = Employee.objects.filter(
            campus_id=campus, is_deleted=False,
        ).order_by("emp_code")
        return Response([
            {"id": e.id, "emp_code": e.emp_code, "full_name": e.full_name}
            for e in qs
        ])


class AuditFilterAdminDailyAuthorsView(APIView):
    """Accounts that have filed an admin daily report.

    Admin daily reports are keyed by *user*, not employee, so their author
    may be an admin/superuser with no Employee record — such a person never
    appears in the campus staff picker. This lets an auditor look a report
    up by its author account directly. Gated on admin-daily view-all.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not (u.is_superuser or has_perm(u, "audit.admin_daily.view_all")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        from django.contrib.auth import get_user_model
        author_ids = (AdminDailyReport.objects
                      .values_list("user_id", flat=True).distinct())
        users = (get_user_model().objects
                 .filter(id__in=list(author_ids))
                 .select_related("employee")
                 .order_by("full_name", "username"))
        out = []
        for usr in users:
            emp = getattr(usr, "employee", None)
            out.append({
                "user": usr.id,
                "username": usr.username,
                "full_name": usr.full_name,
                "emp_code": emp.emp_code if emp else None,
                "employee_id": emp.id if emp else None,
            })
        return Response(out)


# === 2. Admin Daily Report ==========================================

# Mirrors the faculty model:
#   dashboard.admin_daily.submit → fill / see / edit / delete own report
#   audit.admin_daily.view_all   → auditors' read-only sight of everyone's
# Nobody edits another user's report.

def _ad_can_view(user, *, is_own: bool) -> bool:
    if (has_perm(user, "audit.admin_daily.view_all")
            or has_perm(user, "audit.admin_daily.edit_any")
            or has_perm(user, "audit.admin_daily.delete_any")):
        return True
    return is_own and has_perm(user, "dashboard.admin_daily.submit")


def _ad_can_manage(user, *, is_own: bool) -> bool:
    """Create / upsert — own rows only. There is no submit-on-behalf."""
    return bool(
        user.is_superuser
        or (is_own and has_perm(user, "dashboard.admin_daily.submit"))
    )


def _ad_can_edit(user, *, is_own: bool) -> bool:
    return (_ad_can_manage(user, is_own=is_own)
            or has_perm(user, "audit.admin_daily.edit_any"))


def _ad_can_delete(user, *, is_own: bool) -> bool:
    return (_ad_can_manage(user, is_own=is_own)
            or has_perm(user, "audit.admin_daily.delete_any"))


class AdminDailyReportListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = AdminDailyReport.objects.select_related("user")
        if not (has_perm(u, "audit.admin_daily.view_all")
                or has_perm(u, "audit.admin_daily.edit_any")
                or has_perm(u, "audit.admin_daily.delete_any")):
            if not has_perm(u, "dashboard.admin_daily.submit"):
                return Response([])
            qs = qs.filter(user=u)
        params = request.query_params
        if v := params.get("user"):
            qs = qs.filter(user_id=v)
        if v := params.get("employee"):
            # Resolve an employee to their linked user account.
            qs = qs.filter(user__employee=v)
        if v := params.get("from"):
            if d := parse_date(v):
                qs = qs.filter(rep_date__gte=d)
        if v := params.get("to"):
            if d := parse_date(v):
                qs = qs.filter(rep_date__lte=d)
        return Response(AdminDailyReportSerializer(qs[:500], many=True).data)

    def post(self, request):
        """Upsert one (user, rep_date) row for the current user."""
        u = request.user
        if not _ad_can_manage(u, is_own=True):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = AdminDailyReportSerializer(data={**request.data, "user": u.id})
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if blocked := freeze.write_blocked_reason(u, freeze.REPORT_ADMIN, d["rep_date"]):
            return Response({"detail": blocked, "code": "frozen"},
                            status=http.HTTP_423_LOCKED)
        obj, created = AdminDailyReport.objects.update_or_create(
            user=u, rep_date=d["rep_date"],
            defaults={"slot1": d.get("slot1", ""), "slot2": d.get("slot2", "")},
        )
        return Response(
            AdminDailyReportSerializer(obj).data,
            status=http.HTTP_201_CREATED if created else http.HTTP_200_OK)


class AdminDailyReportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return AdminDailyReport.objects.get(pk=pk)
        except AdminDailyReport.DoesNotExist as e:
            raise Http404 from e

    def patch(self, request, pk):
        obj = self._obj(pk)
        if not _ad_can_edit(request.user, is_own=obj.user_id == request.user.id):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if blocked := freeze.write_blocked_reason(
                request.user, freeze.REPORT_ADMIN, obj.rep_date):
            return Response({"detail": blocked, "code": "frozen"},
                            status=http.HTTP_423_LOCKED)
        s = AdminDailyReportSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        obj = self._obj(pk)
        if not _ad_can_delete(request.user, is_own=obj.user_id == request.user.id):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        if blocked := freeze.write_blocked_reason(
                request.user, freeze.REPORT_ADMIN, obj.rep_date):
            return Response({"detail": blocked, "code": "frozen"},
                            status=http.HTTP_423_LOCKED)
        obj.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# === 2c. Month-wise freeze: access requests =========================
#
#   employee  → POST  freeze/requests/              (PENDING)
#   manager   → POST  freeze/requests/<pk>/decide/  (MANAGER_APPROVED / REJECTED)
#   admin     → POST  freeze/requests/<pk>/grant/   (GRANTED until a date)
#   admin     → POST  freeze/requests/<pk>/revoke/
#
# The manager is the applicant's `reporting_manager_1`, snapshotted by
# email and matched like leave approvals — no permission key needed to
# decide. Granting / revoking needs `audit.daily_report.unlock`.

UNLOCK_KEY = "audit.daily_report.unlock"


def _can_unlock(user) -> bool:
    return bool(user.is_superuser or has_perm(user, UNLOCK_KEY))


def _unlock_admins():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return (User.objects.filter(is_active=True)
            .filter(Q(is_superuser=True) | Q(roles__permissions__key=UNLOCK_KEY))
            .distinct())


def _notify_access(req: DailyReportAccess, *, event: str, actor) -> None:
    """In-app bell for each hop of the request. Best-effort."""
    from apps.notifications.inapp import notify, user_by_email
    from apps.notifications.models import InAppNotification

    who = req.employee.full_name if req.employee_id else (
        req.user.full_name or req.user.username)
    label = f"{req.get_report_type_display()} · {req.month_label}"
    link_mine = "/daily-report" if req.report_type == freeze.REPORT_FACULTY else "/admin-daily"
    if event == "requested":
        notify([user_by_email(req.manager_email)],
               kind=InAppNotification.Kind.OTHER,
               title=f"Daily report access request from {who}",
               body=f"{label}. Reason: {req.reason}",
               link="/daily-report-access", exclude_user=actor)
    elif event == "manager_approved":
        notify(list(_unlock_admins()), kind=InAppNotification.Kind.OTHER,
               title=f"Grant daily report access: {who}",
               body=f"{label} — approved by the reporting manager.",
               link="/daily-report-access", exclude_user=actor)
        notify([req.user], kind=InAppNotification.Kind.OTHER,
               title="Your access request was approved by your manager",
               body=f"{label}. An admin will now grant the access window.",
               link=link_mine, exclude_user=actor)
    elif event == "rejected":
        notify([req.user], kind=InAppNotification.Kind.OTHER,
               title="Your daily report access request was rejected",
               body=f"{label}. {req.manager_remarks}".strip(),
               link=link_mine, exclude_user=actor)
    elif event == "granted":
        notify([req.user], kind=InAppNotification.Kind.OTHER,
               title="Daily report month unlocked",
               body=(f"{label} is editable until "
                     f"{req.access_until.strftime('%d-%m-%Y')}."),
               link=link_mine, exclude_user=actor)
    elif event == "revoked":
        notify([req.user], kind=InAppNotification.Kind.OTHER,
               title="Daily report access revoked",
               body=f"{label} is frozen again.", link=link_mine,
               exclude_user=actor)


def _parse_report_type(raw) -> str | None:
    v = (raw or "").strip().upper()
    return v if v in (freeze.REPORT_FACULTY, freeze.REPORT_ADMIN) else None


def _parse_month(raw) -> tuple[int, int] | None:
    """'YYYY-MM' → (year, month)."""
    try:
        y, m = (raw or "").split("-")[:2]
        y, m = int(y), int(m)
    except (TypeError, ValueError):
        return None
    return (y, m) if 1 <= m <= 12 and 2000 <= y <= 2100 else None


class DailyReportFreezeStatusView(APIView):
    """Is this month frozen for me, and do I hold access?
    `?type=FACULTY|ADMIN&month=YYYY-MM`."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rt = _parse_report_type(request.query_params.get("type"))
        ym = _parse_month(request.query_params.get("month"))
        if rt is None or ym is None:
            return Response({"detail": "type (FACULTY|ADMIN) and month (YYYY-MM) required."},
                            status=http.HTTP_400_BAD_REQUEST)
        st = freeze.status_for(request.user, rt, *ym)
        st["access"] = (DailyReportAccessSerializer(st["access"]).data
                        if st["access"] else None)
        st["latest_request"] = (DailyReportAccessSerializer(st["latest_request"]).data
                                if st["latest_request"] else None)
        return Response(st)


class DailyReportAccessListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """`?scope=mine` (default) | `team` (I am the snapshotted manager)
        | `all` (unlock key). Filters: status, type."""
        from apps.leaves.permissions import manager_email_q

        u = request.user
        scope = (request.query_params.get("scope") or "mine").lower()
        qs = DailyReportAccess.objects.select_related(
            "user", "employee", "manager_decided_by", "granted_by")
        if scope == "all":
            if not _can_unlock(u):
                return Response({"detail": "Permission denied."},
                                status=http.HTTP_403_FORBIDDEN)
        elif scope == "team":
            qs = qs.filter(manager_email_q(u))
        else:
            qs = qs.filter(user=u)
        if v := request.query_params.get("status"):
            qs = qs.filter(status=v)
        if rt := _parse_report_type(request.query_params.get("type")):
            qs = qs.filter(report_type=rt)
        return Response(DailyReportAccessSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        s = DailyReportAccessSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        rt, year, month = d["report_type"], d["year"], d["month"]

        # Only someone who can fill that report may ask to unlock it.
        submit_key = ("dashboard.daily_report.submit" if rt == freeze.REPORT_FACULTY
                      else "dashboard.admin_daily.submit")
        if not (u.is_superuser or has_perm(u, submit_key)):
            return Response({"detail": "You cannot fill this report, so there is "
                                       "nothing to unlock."},
                            status=http.HTTP_403_FORBIDDEN)
        if not freeze.month_is_frozen(year, month):
            return Response({"detail": f"{_date(year, month, 1).strftime('%B %Y')} "
                                       "is not frozen; you can edit it directly."},
                            status=http.HTTP_400_BAD_REQUEST)
        if freeze.open_access(u, rt, year, month) is not None:
            return Response({"detail": "You already hold access to this month."},
                            status=http.HTTP_400_BAD_REQUEST)
        if DailyReportAccess.objects.filter(
                user=u, report_type=rt, year=year, month=month,
                status__in=(DailyReportAccess.Status.PENDING,
                            DailyReportAccess.Status.MANAGER_APPROVED)).exists():
            return Response({"detail": "A request for this month is already in progress."},
                            status=http.HTTP_400_BAD_REQUEST)

        emp = _emp_of(u)
        rm = getattr(emp, "reporting_manager_1", None) if emp else None
        manager_email = (rm.email_primary if rm else "") or ""
        if not manager_email:
            return Response(
                {"detail": "No reporting manager is set on your employee record, "
                           "so the request cannot be routed. Ask HR to set one."},
                status=http.HTTP_400_BAD_REQUEST)

        req = DailyReportAccess.objects.create(
            report_type=rt, user=u, employee=emp, year=year, month=month,
            reason=d["reason"], manager_email=manager_email,
        )
        _notify_access(req, event="requested", actor=u)
        return Response(DailyReportAccessSerializer(req).data,
                        status=http.HTTP_201_CREATED)


def _access_obj(pk) -> DailyReportAccess:
    try:
        return DailyReportAccess.objects.select_related(
            "user", "employee", "manager_decided_by", "granted_by").get(pk=pk)
    except DailyReportAccess.DoesNotExist as e:
        raise Http404 from e


class DailyReportAccessDecideView(APIView):
    """Step 1 — the reporting manager approves or rejects."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        from apps.leaves.permissions import is_manager_for

        u = request.user
        req = _access_obj(pk)
        if req.status != DailyReportAccess.Status.PENDING:
            return Response({"detail": "This request is not awaiting the manager."},
                            status=http.HTTP_400_BAD_REQUEST)
        if not (is_manager_for(u, req) or u.is_superuser):
            return Response({"detail": "Only the applicant's reporting manager can decide."},
                            status=http.HTTP_403_FORBIDDEN)
        s = DailyReportAccessDecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        approve = s.validated_data["approve"]
        req.status = (DailyReportAccess.Status.MANAGER_APPROVED if approve
                      else DailyReportAccess.Status.REJECTED)
        req.manager_decided_by = u
        req.manager_decided_at = timezone.now()
        req.manager_remarks = s.validated_data.get("remarks", "")
        req.save(update_fields=["status", "manager_decided_by", "manager_decided_at",
                                "manager_remarks", "updated_at"])
        _notify_access(req, event="manager_approved" if approve else "rejected", actor=u)
        return Response(DailyReportAccessSerializer(req).data)


class DailyReportAccessGrantView(APIView):
    """Step 2 — an admin grants the unlock window. Manager approval first."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not _can_unlock(u):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        req = _access_obj(pk)
        if req.status != DailyReportAccess.Status.MANAGER_APPROVED:
            return Response(
                {"detail": "Access can only be granted after the reporting "
                           "manager has approved the request."},
                status=http.HTTP_400_BAD_REQUEST)
        s = DailyReportAccessGrantSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        until = s.validated_data["access_until"]
        if until < freeze.today():
            return Response({"access_until": ["Must be today or later."]},
                            status=http.HTTP_400_BAD_REQUEST)
        req.status = DailyReportAccess.Status.GRANTED
        req.granted_by = u
        req.granted_at = timezone.now()
        req.access_until = until
        req.grant_remarks = s.validated_data.get("remarks", "")
        req.save(update_fields=["status", "granted_by", "granted_at", "access_until",
                                "grant_remarks", "updated_at"])
        _notify_access(req, event="granted", actor=u)
        return Response(DailyReportAccessSerializer(req).data)


class DailyReportAccessRevokeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not _can_unlock(u):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        req = _access_obj(pk)
        if req.status != DailyReportAccess.Status.GRANTED:
            return Response({"detail": "Only a granted access can be revoked."},
                            status=http.HTTP_400_BAD_REQUEST)
        req.status = DailyReportAccess.Status.REVOKED
        req.revoked_by = u
        req.revoked_at = timezone.now()
        req.save(update_fields=["status", "revoked_by", "revoked_at", "updated_at"])
        _notify_access(req, event="revoked", actor=u)
        return Response(DailyReportAccessSerializer(req).data)


# === 3. Course End Report ===========================================

class CourseEndReportListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = CourseEndReport.objects.select_related(
            "instructor", "subject", "batch", "batch__program",
        )
        if not (has_perm(u, "audit.course_end.view_all")
                or has_perm(u, "audit.course_end.edit_any")
                or has_perm(u, "audit.course_end.delete_any")):
            emp = _emp_of(u)
            qs = qs.filter(instructor=emp) if emp else qs.none()
        params = request.query_params
        if v := params.get("campus"):
            qs = qs.filter(batch__campus_id=v)
        if v := params.get("program"):
            qs = qs.filter(batch__program_id=v)
        if v := params.get("batch"):
            qs = qs.filter(batch_id=v)
        if v := params.get("subject"):
            qs = qs.filter(subject_id=v)
        if v := params.get("hod_status"):
            qs = qs.filter(hod_status=v)
        if wants_csv(request):
            # "Module End Reports.csv" — every matching row, same
            # visibility rule as the list (own rows without a view_all key).
            def rows():
                for r in (qs.select_related("hod_reviewed_by")
                          .order_by("-completed_on", "batch__name")
                          .iterator(chunk_size=500)):
                    rb = r.hod_reviewed_by
                    yield [
                        fmt_date(r.completed_on), r.batch.program.name,
                        r.batch.name, f"{r.subject.name} ({r.subject.code})",
                        r.instructor.full_name, r.instructor.emp_code,
                        r.avg_attendance_pct if r.avg_attendance_pct is not None else "",
                        r.avg_marks_pct if r.avg_marks_pct is not None else "",
                        r.summary, r.learning_outcomes, r.challenges, r.suggestions,
                        r.get_hod_status_display(), r.hod_remarks,
                        fmt_date(r.hod_reviewed_at),
                        (rb.full_name or rb.username) if rb else "",
                        fmt_date(r.created_at),
                    ]
            return csv_response("Module End Reports.csv", [
                "Completed on", "Program", "Batch", "Subject", "Instructor",
                "Emp Code", "Avg attendance %", "Avg marks %", "Summary",
                "Learning outcomes", "Challenges", "Suggestions", "HOD status",
                "HOD remarks", "Reviewed on", "Reviewed by", "Submitted on",
            ], rows())
        return Response(CourseEndReportSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        if not has_perm(u, "audit.course_end.submit"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        # A plain faculty login files for themselves only (client,
        # 2026-11-25): the instructor is their own employee record,
        # whatever the body says. HOD / admin (anyone who can see every
        # report) may file on a colleague's behalf.
        own = getattr(u, "employee", None)
        if own is not None and not (
            has_perm(u, "audit.course_end.view_all")
            or has_perm(u, "audit.course_end.edit_any")
        ):
            data["instructor"] = own.pk
        s = CourseEndReportSerializer(data=data)
        s.is_valid(raise_exception=True)
        s.save(submitted_by=u)
        return Response(s.data, status=http.HTTP_201_CREATED)


class CourseEndReportReviewView(APIView):
    """HOD approves the course-end report, or returns it for rework.

    Signing a report off and sending it back to its author are separate
    permissions — `review` used to cover both.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        try:
            obj = CourseEndReport.objects.get(pk=pk)
        except CourseEndReport.DoesNotExist as e:
            raise Http404 from e
        s = CourseEndReviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        needed = (
            "audit.course_end.approve"
            if s.validated_data["hod_status"] == "APPROVED"
            else "audit.course_end.return"
        )
        if not has_perm(u, needed):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        obj.hod_status = s.validated_data["hod_status"]
        obj.hod_remarks = s.validated_data.get("hod_remarks", "")
        obj.hod_reviewed_at = timezone.now()
        obj.hod_reviewed_by = u
        obj.save(update_fields=[
            "hod_status", "hod_remarks", "hod_reviewed_at",
            "hod_reviewed_by", "updated_at",
        ])
        return Response(CourseEndReportSerializer(obj).data)


class CourseEndReportDetailView(APIView):
    """Read / edit / delete one course-end report.

    Neither editing nor deleting existed before — not even for
    superusers — so a typo in a filed report was permanent.

    The author may fix their own report while it is still PENDING; once
    an HOD has approved or returned it, changing it needs `edit_any`, so
    a signed-off report cannot be rewritten under the reviewer.
    """

    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return CourseEndReport.objects.select_related(
                "instructor", "subject", "batch", "batch__program",
            ).get(pk=pk)
        except CourseEndReport.DoesNotExist as e:
            raise Http404 from e

    def _is_own(self, user, obj) -> bool:
        emp = _emp_of(user)
        return bool(emp and obj.instructor_id == emp.id)

    def get(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (has_perm(u, "audit.course_end.view_all")
                or has_perm(u, "audit.course_end.edit_any")
                or has_perm(u, "audit.course_end.delete_any")
                or self._is_own(u, obj)):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response(CourseEndReportSerializer(obj).data)

    def patch(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        own_and_pending = (
            self._is_own(u, obj)
            and obj.hod_status == "PENDING"
            and has_perm(u, "audit.course_end.submit")
        )
        if not (own_and_pending or has_perm(u, "audit.course_end.edit_any")):
            return Response(
                {"detail": "You can only edit your own report while it is "
                           "still pending review."},
                status=http.HTTP_403_FORBIDDEN,
            )
        s = CourseEndReportSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        own_and_pending = (
            self._is_own(u, obj)
            and obj.hod_status == "PENDING"
            and has_perm(u, "audit.course_end.submit")
        )
        if not (own_and_pending or has_perm(u, "audit.course_end.delete_any")):
            return Response(
                {"detail": "You can only delete your own report while it is "
                           "still pending review."},
                status=http.HTTP_403_FORBIDDEN,
            )
        obj.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# === 4. Batch Mentor Report =========================================

class BatchMentorReportListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = BatchMentorReport.objects.select_related("batch", "mentor")
        if not (has_perm(u, "audit.batch_mentor.view_all")
                or has_perm(u, "audit.batch_mentor.edit_any")
                or has_perm(u, "audit.batch_mentor.delete_any")):
            emp = _emp_of(u)
            qs = qs.filter(mentor=emp) if emp else qs.none()
        params = request.query_params
        if v := params.get("batch"):
            qs = qs.filter(batch_id=v)
        if v := params.get("year"):
            qs = qs.filter(year=v)
        return Response(BatchMentorReportSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        s = BatchMentorReportSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        # Mentors can submit for their own batches; auditors override.
        emp = _emp_of(u)
        is_mentor = (s.validated_data["batch"].mentor_id == (emp.id if emp else None))
        if not (u.is_superuser or is_mentor
                or has_perm(u, "audit.batch_mentor.submit_for_others")):
            return Response({"detail": "Only the batch mentor can submit."},
                            status=http.HTTP_403_FORBIDDEN)
        s.save(submitted_by=u)
        return Response(s.data, status=http.HTTP_201_CREATED)


class BatchMentorReportDetailView(APIView):
    """Read / edit / delete one batch-mentor report.

    Mirrors the course-end detail view. There is no review flow on this
    report, so the mentor may fix their own at any time; `edit_any` /
    `delete_any` cover everyone else's.
    """

    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return BatchMentorReport.objects.select_related(
                "batch", "mentor").get(pk=pk)
        except BatchMentorReport.DoesNotExist as e:
            raise Http404 from e

    def _is_own(self, user, obj) -> bool:
        emp = _emp_of(user)
        return bool(emp and obj.mentor_id == emp.id)

    def get(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (has_perm(u, "audit.batch_mentor.view_all")
                or has_perm(u, "audit.batch_mentor.edit_any")
                or has_perm(u, "audit.batch_mentor.delete_any")
                or self._is_own(u, obj)):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response(BatchMentorReportSerializer(obj).data)

    def patch(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (self._is_own(u, obj)
                or has_perm(u, "audit.batch_mentor.edit_any")):
            return Response(
                {"detail": "Only the batch mentor can edit this report."},
                status=http.HTTP_403_FORBIDDEN,
            )
        s = BatchMentorReportSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (self._is_own(u, obj)
                or has_perm(u, "audit.batch_mentor.delete_any")):
            return Response(
                {"detail": "Only the batch mentor can delete this report."},
                status=http.HTTP_403_FORBIDDEN,
            )
        obj.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# === 4b. Zero-Hour Report ===========================================
#
# Two-permission model, mirroring the other batch reports:
#   academics.zero_hour.submit     → fill / see / edit OWN reports
#                                    (shows under Academics)
#   academics.zero_hour.delete     → delete OWN report
#   academics.zero_hour.edit_any   → edit anyone's (was superuser-only)
#   academics.zero_hour.delete_any → delete anyone's (was superuser-only)
#   audit.zero_hour.view_all       → auditors' read-only sight of
#                                    everyone's (shows under Audit,
#                                    date-wise + paginated)

class ZeroHourPagination(StandardPagination):
    """Audit report defaults to the 10 most recent, page_size overridable."""
    page_size = 10


def _zh_can_view_all(user) -> bool:
    return bool(user.is_superuser or has_perm(user, "audit.zero_hour.view_all"))


def _zh_can_submit(user) -> bool:
    return bool(user.is_superuser
                or has_perm(user, "academics.zero_hour.submit"))


def _zh_can_edit(user, obj) -> bool:
    """Own report with `submit`, or anyone's with `edit_any`."""
    if has_perm(user, "academics.zero_hour.edit_any"):
        return True
    return (obj.submitted_by_id == user.id
            and has_perm(user, "academics.zero_hour.submit"))


def _zh_can_delete(user, obj) -> bool:
    """Own report with `delete`, or anyone's with `delete_any`."""
    if has_perm(user, "academics.zero_hour.delete_any"):
        return True
    return (obj.submitted_by_id == user.id
            and has_perm(user, "academics.zero_hour.delete"))


class ZeroHourReportListCreateView(PaginatedAPIViewMixin, APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = ZeroHourPagination

    def get(self, request):
        u = request.user
        qs = ZeroHourReport.objects.select_related("batch", "batch__program",
                                                    "mentor", "submitted_by")
        if not (_zh_can_view_all(u)
                or has_perm(u, "academics.zero_hour.edit_any")
                or has_perm(u, "academics.zero_hour.delete_any")):
            # Fillers see only their own submissions.
            if not _zh_can_submit(u):
                return Response({"results": [], "count": 0,
                                 "next": None, "previous": None})
            qs = qs.filter(submitted_by=u)
        params = request.query_params
        if v := params.get("campus"):
            qs = qs.filter(batch__campus_id=v)
        if v := params.get("program"):
            qs = qs.filter(batch__program_id=v)
        if v := params.get("batch"):
            qs = qs.filter(batch_id=v)
        if v := params.get("mentor"):
            qs = qs.filter(mentor_id=v)
        if v := params.get("from"):
            if d := parse_date(v):
                qs = qs.filter(report_date__gte=d)
        if v := params.get("to"):
            if d := parse_date(v):
                qs = qs.filter(report_date__lte=d)
        if wants_csv(request):
            # "0-Hour Reports.csv" — every matching row, not one page.
            # Same visibility rule as the list.
            def rows():
                for r in (qs.select_related("batch__campus", "batch__program")
                          .order_by("-report_date", "batch__name")
                          .iterator(chunk_size=500)):
                    yield [
                        fmt_date(r.report_date), r.batch.campus.name,
                        r.batch.program.name, r.batch.name,
                        r.mentor.full_name if r.mentor_id else "",
                        r.batch_strength, r.zero_hour_attendance,
                        r.avg_attendance_first_half if r.avg_attendance_first_half is not None else "",
                        r.avg_attendance_month_end if r.avg_attendance_month_end is not None else "",
                        r.agenda, r.outcome, r.activities, r.remarks,
                        r.hod_discussion, r.action_taken,
                        (r.submitted_by.full_name or r.submitted_by.username)
                        if r.submitted_by_id else "",
                        fmt_date(r.created_at),
                    ]
            return csv_response("0-Hour Reports.csv", [
                "Date", "Campus", "Program", "Class / Batch", "Mentor",
                "Batch strength", "0-Hour attendance", "Avg attendance 1st half %",
                "Avg attendance month end %", "Agenda", "Outcome", "Activities",
                "Remarks", "HOD discussion", "Action taken", "Submitted by",
                "Submitted on",
            ], rows())
        return self.paginate(qs, ZeroHourReportSerializer)

    def post(self, request):
        u = request.user
        if not _zh_can_submit(u):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = ZeroHourReportSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(submitted_by=u)
        return Response(s.data, status=http.HTTP_201_CREATED)


class ZeroHourReportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return ZeroHourReport.objects.select_related(
                "batch", "mentor", "submitted_by").get(pk=pk)
        except ZeroHourReport.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (_zh_can_view_all(u)
                or _zh_can_edit(u, obj)
                or _zh_can_delete(u, obj)):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response(ZeroHourReportSerializer(obj).data)

    def patch(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not _zh_can_edit(u, obj):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = ZeroHourReportSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not _zh_can_delete(u, obj):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        obj.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# === 5. Student Feedback ============================================

class StudentFeedbackListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = StudentFeedback.objects.select_related(
            "student", "subject", "instructor", "batch",
        )
        # Visibility: students see their own; auditors see all
        if not (has_perm(u, "audit.feedback.view_all")
                or has_perm(u, "audit.feedback.edit_any")
                or has_perm(u, "audit.feedback.delete_any")):
            student = _student_of(u)
            qs = qs.filter(student=student) if student else qs.none()
        params = request.query_params
        # Campus = the batch's campus (feedback is always tied to a batch).
        if v := params.get("campus"):
            qs = qs.filter(batch__campus_id=v)
        if v := params.get("instructor"):
            qs = qs.filter(instructor_id=v)
        if v := params.get("subject"):
            qs = qs.filter(subject_id=v)
        if v := params.get("batch"):
            qs = qs.filter(batch_id=v)
        if wants_csv(request):
            # "Student Feedback.csv" — every matching row, not the
            # on-screen cap. Same visibility rule as the list.
            def rows():
                for f in qs.order_by("-created_at").iterator(chunk_size=500):
                    yield [
                        fmt_date(f.created_at), f.get_type_display(),
                        f.student.student_name, f.student.application_form_id,
                        f.instructor.full_name, f.instructor.emp_code,
                        f"{f.subject.name} ({f.subject.code})", f.batch.name,
                        f.rating_overall, f.rating_clarity, f.rating_engagement,
                        f.rating_responsiveness, f.what_worked, f.suggestions,
                    ]
            return csv_response("Student Feedback.csv", [
                "Date", "Type", "Student", "Form No", "Instructor", "Emp Code",
                "Subject", "Batch", "Overall", "Clarity", "Engagement",
                "Responsiveness", "What worked", "Suggestions",
            ], rows())
        return Response(StudentFeedbackSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        student = _student_of(u)
        if student is None:
            return Response({"detail": "Only students can submit feedback."},
                            status=http.HTTP_403_FORBIDDEN)
        # Force student to self.
        data = dict(request.data)
        data["student"] = student.id
        s = StudentFeedbackSerializer(data=data)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data, status=http.HTTP_201_CREATED)


class StudentFeedbackDetailView(APIView):
    """Read / edit / delete one feedback row.

    Editing did not exist before, so a student who filed feedback
    against the wrong instructor could never correct it. A student may
    fix or withdraw their OWN feedback; `edit_any` / `delete_any` cover
    everyone else's.
    """

    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return StudentFeedback.objects.select_related(
                "student", "subject", "instructor", "batch").get(pk=pk)
        except StudentFeedback.DoesNotExist as e:
            raise Http404 from e

    def _is_own(self, user, obj) -> bool:
        student = _student_of(user)
        return bool(student and obj.student_id == student.id)

    def get(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (has_perm(u, "audit.feedback.view_all")
                or has_perm(u, "audit.feedback.edit_any")
                or has_perm(u, "audit.feedback.delete_any")
                or self._is_own(u, obj)):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response(StudentFeedbackSerializer(obj).data)

    def patch(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (self._is_own(u, obj)
                or has_perm(u, "audit.feedback.edit_any")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        # A student can never reassign feedback to another student.
        data = dict(request.data)
        data.pop("student", None)
        s = StudentFeedbackSerializer(obj, data=data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (self._is_own(u, obj)
                or has_perm(u, "audit.feedback.delete_any")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        obj.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# === 6. Faculty Self-Appraisal ======================================

class FacultySelfAppraisalListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        qs = FacultySelfAppraisal.objects.select_related("faculty")
        if not (has_perm(u, "audit.self_appraisal.view_all")
                or has_perm(u, "audit.self_appraisal.edit_any")
                or has_perm(u, "audit.self_appraisal.delete_any")):
            emp = _emp_of(u)
            if emp is None or not has_perm(u, "audit.self_appraisal.view_own"):
                return Response([])
            qs = qs.filter(faculty=emp)
        params = request.query_params
        if v := params.get("faculty"):
            qs = qs.filter(faculty_id=v)
        if v := params.get("year"):
            qs = qs.filter(year=v)
        if wants_csv(request):
            # "Faculty Feedback.csv" — every matching row. Same visibility
            # rule as the list (own rows only without a view_all key).
            def rows():
                for a in (qs.select_related("auditor_reviewed_by")
                          .order_by("-year", "-quarter", "faculty__first_name")
                          .iterator(chunk_size=500)):
                    rb = a.auditor_reviewed_by
                    yield [
                        a.faculty.emp_code, a.faculty.full_name,
                        a.year, a.get_quarter_display(),
                        a.achievements, a.challenges, a.plans,
                        a.green_flags, a.red_flags,
                        a.auditor_remarks, fmt_date(a.auditor_reviewed_at),
                        (rb.full_name or rb.username) if rb else "",
                        fmt_date(a.created_at),
                    ]
            return csv_response("Faculty Feedback.csv", [
                "Emp Code", "Faculty", "Year", "Quarter", "Achievements",
                "Challenges", "Plans", "Stars", "Red flags",
                "Auditor remarks", "Reviewed on", "Reviewed by", "Submitted on",
            ], rows())
        return Response(FacultySelfAppraisalSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        s = FacultySelfAppraisalSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        emp = _emp_of(u)
        target = s.validated_data["faculty"]
        is_own = bool(emp and emp.id == target.id)
        if not (u.is_superuser
                or (is_own and has_perm(u, "audit.self_appraisal.submit"))):
            return Response({"detail": "You can only submit your own appraisal."},
                            status=http.HTTP_403_FORBIDDEN)
        s.save(submitted_by=u)
        return Response(s.data, status=http.HTTP_201_CREATED)


class SelfAppraisalReviewView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not (u.is_superuser or has_perm(u, "audit.self_appraisal.review")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            obj = FacultySelfAppraisal.objects.get(pk=pk)
        except FacultySelfAppraisal.DoesNotExist as e:
            raise Http404 from e
        s = SelfAppraisalReviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        obj.auditor_remarks = s.validated_data["auditor_remarks"]
        obj.auditor_reviewed_at = timezone.now()
        obj.auditor_reviewed_by = u
        obj.save(update_fields=[
            "auditor_remarks", "auditor_reviewed_at",
            "auditor_reviewed_by", "updated_at",
        ])
        return Response(FacultySelfAppraisalSerializer(obj).data)


class FacultySelfAppraisalDetailView(APIView):
    """Read / edit / delete one self-appraisal.

    The author may revise their own until an auditor has reviewed it —
    after that, changing it needs `edit_any`, so a reviewed appraisal
    cannot be rewritten under the reviewer. Same rule as course-end.
    """

    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return FacultySelfAppraisal.objects.select_related(
                "faculty").get(pk=pk)
        except FacultySelfAppraisal.DoesNotExist as e:
            raise Http404 from e

    def _is_own(self, user, obj) -> bool:
        emp = _emp_of(user)
        return bool(emp and obj.faculty_id == emp.id)

    def get(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        own = self._is_own(u, obj)
        if not (has_perm(u, "audit.self_appraisal.view_all")
                or has_perm(u, "audit.self_appraisal.edit_any")
                or has_perm(u, "audit.self_appraisal.delete_any")
                or (own and has_perm(u, "audit.self_appraisal.view_own"))):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response(FacultySelfAppraisalSerializer(obj).data)

    def patch(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        own_and_unreviewed = (
            self._is_own(u, obj)
            and obj.auditor_reviewed_at is None
            and has_perm(u, "audit.self_appraisal.submit")
        )
        if not (own_and_unreviewed
                or has_perm(u, "audit.self_appraisal.edit_any")):
            return Response(
                {"detail": "You can only revise your own appraisal before "
                           "it has been reviewed."},
                status=http.HTTP_403_FORBIDDEN,
            )
        s = FacultySelfAppraisalSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        own_and_unreviewed = (
            self._is_own(u, obj)
            and obj.auditor_reviewed_at is None
            and has_perm(u, "audit.self_appraisal.submit")
        )
        if not (own_and_unreviewed
                or has_perm(u, "audit.self_appraisal.delete_any")):
            return Response(
                {"detail": "You can only delete your own appraisal before "
                           "it has been reviewed."},
                status=http.HTTP_403_FORBIDDEN,
            )
        obj.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# === 7. Compliance Flag =============================================

class ComplianceFlagListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not (u.is_superuser or has_perm(u, "audit.compliance.view")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        qs = ComplianceFlag.objects.select_related(
            "target_faculty", "target_batch", "target_student",
            "raised_by", "resolved_by",
        )
        params = request.query_params
        if v := params.get("kind"):
            qs = qs.filter(kind=v)
        if params.get("open") == "1":
            qs = qs.filter(resolved_at__isnull=True)
        elif params.get("resolved") == "1":
            qs = qs.filter(resolved_at__isnull=False)
        if v := params.get("category"):
            qs = qs.filter(category=v)
        if v := params.get("severity"):
            qs = qs.filter(severity=v)
        if v := params.get("faculty"):
            qs = qs.filter(target_faculty_id=v)
        return Response(ComplianceFlagSerializer(qs[:500], many=True).data)

    def post(self, request):
        u = request.user
        if not (u.is_superuser or has_perm(u, "audit.compliance.flag")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        s = ComplianceFlagSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(raised_by=u)
        return Response(s.data, status=http.HTTP_201_CREATED)


class ComplianceFlagResolveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        u = request.user
        if not (u.is_superuser or has_perm(u, "audit.compliance.resolve")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            obj = ComplianceFlag.objects.get(pk=pk)
        except ComplianceFlag.DoesNotExist as e:
            raise Http404 from e
        if obj.kind == ComplianceFlag.Kind.STAR:
            return Response({"detail": "Stars are a permanent record and "
                                       "cannot be resolved."},
                            status=http.HTTP_400_BAD_REQUEST)
        if obj.resolved_at:
            return Response({"detail": "Already resolved."},
                            status=http.HTTP_400_BAD_REQUEST)
        s = ResolveFlagSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        obj.resolved_at = timezone.now()
        obj.resolved_by = u
        obj.resolution_remarks = s.validated_data["resolution_remarks"]
        obj.save(update_fields=[
            "resolved_at", "resolved_by", "resolution_remarks", "updated_at",
        ])
        return Response(ComplianceFlagSerializer(obj).data)


class ComplianceFlagDetailView(APIView):
    """Read / edit / delete one flag or star.

    Nothing here could be changed before, by anyone — a flag raised
    against the wrong colleague stayed on their record permanently, and
    a star is by design never resolved.

    The person who raised it may correct or withdraw it while it is
    still open; `edit_any` / `delete_any` cover everything else. `kind`
    is immutable, so a flag can never be quietly rewritten into a star
    (or vice versa) — the categories are validated per polarity.
    """

    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return ComplianceFlag.objects.select_related(
                "target_faculty", "target_batch", "target_student",
                "raised_by", "resolved_by").get(pk=pk)
        except ComplianceFlag.DoesNotExist as e:
            raise Http404 from e

    def _is_own(self, user, obj) -> bool:
        return obj.raised_by_id == user.id

    def _own_and_open(self, user, obj) -> bool:
        # Stars are never resolved, so for them this is simply "mine".
        return self._is_own(user, obj) and obj.resolved_at is None

    def get(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (has_perm(u, "audit.compliance.view")
                or has_perm(u, "audit.compliance.edit_any")
                or has_perm(u, "audit.compliance.delete_any")
                or self._is_own(u, obj)):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response(ComplianceFlagSerializer(obj).data)

    def patch(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (self._own_and_open(u, obj)
                or has_perm(u, "audit.compliance.edit_any")):
            return Response(
                {"detail": "You can only edit a flag you raised, while it "
                           "is still open."},
                status=http.HTTP_403_FORBIDDEN,
            )
        data = dict(request.data)
        data.pop("kind", None)
        s = ComplianceFlagSerializer(obj, data=data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        obj = self._obj(pk)
        u = request.user
        if not (self._own_and_open(u, obj)
                or has_perm(u, "audit.compliance.delete_any")):
            return Response(
                {"detail": "You can only withdraw a flag you raised, while "
                           "it is still open."},
                status=http.HTTP_403_FORBIDDEN,
            )
        obj.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# === Dashboard reports ==============================================

def _can_view_dashboards(user) -> bool:
    """Roll-up dashboards: consolidated monthly + batch progression."""
    return has_perm(user, "audit.report.consolidated")


def _can_view_live_faculty(user) -> bool:
    """Live tracking + timetable adherence — who is teaching, when."""
    return has_perm(user, "audit.report.live_faculty")


def _can_view_instructor_feedback(user) -> bool:
    """A named instructor's student-feedback scores."""
    return has_perm(user, "audit.report.instructor_feedback")


class LiveFacultyTrackingView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view_live_faculty(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        d = parse_date(request.query_params.get("date") or "") or None
        return Response(live_faculty_tracking(on_date=d))


class TimetableAdherenceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view_live_faculty(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        params = request.query_params
        start = parse_date(params.get("start") or "")
        end = parse_date(params.get("end") or "")
        if not start or not end:
            return Response({"detail": "start and end (YYYY-MM-DD) required."},
                            status=http.HTTP_400_BAD_REQUEST)
        return Response(timetable_adherence(start=start, end=end))


class BatchProgressionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _can_view_dashboards(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            batch = Batch.objects.select_related("campus", "program").get(pk=pk)
        except Batch.DoesNotExist as e:
            raise Http404 from e
        return Response(batch_progression(batch=batch))


class FeedbackSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _can_view_instructor_feedback(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            instr = Employee.objects.get(pk=pk)
        except Employee.DoesNotExist as e:
            raise Http404 from e
        year = request.query_params.get("year")
        return Response(feedback_summary_for_instructor(
            instructor=instr, year=int(year) if year else None,
        ))


class ConsolidatedMonthlyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view_dashboards(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            year = int(request.query_params.get("year") or 0)
            month = int(request.query_params.get("month") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "year and month required (integers)."},
                            status=http.HTTP_400_BAD_REQUEST)
        if not year or not month:
            now = timezone.now()
            year = year or now.year
            month = month or now.month
        try:
            return Response(consolidated_monthly(year=year, month=month))
        except ValueError as e:
            return Response({"detail": str(e)},
                            status=http.HTTP_400_BAD_REQUEST)


# === Dynamic Audit Form Builder =====================================

def _can_form(user, action) -> bool:
    """action is one of: view, add, edit, delete."""
    return user.is_superuser or has_perm(user, f"audit.form.{action}")


def _can_view_all_submissions(user) -> bool:
    return user.is_superuser or has_perm(user, "audit.submission.view_all")


def _can_access_form(user, form) -> bool:
    """A regular user may see / fill a published form only if they hold one
    of its assigned roles. Form managers always have access."""
    if _can_form(user, "view"):
        return True
    if form.status != AuditForm.Status.PUBLISHED:
        return False
    return form.roles.filter(users=user).exists()


class AuditFormListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = AuditForm.objects.prefetch_related("fields", "roles")
        # Managers see every form; everyone else only published forms that
        # target one of their roles.
        if not _can_form(request.user, "view"):
            qs = qs.filter(
                status=AuditForm.Status.PUBLISHED,
                roles__users=request.user,
            ).distinct()
        if v := request.query_params.get("status"):
            qs = qs.filter(status=v)
        return Response(AuditFormSerializer(qs, many=True).data)

    def post(self, request):
        if not _can_form(request.user, "add"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        # Creating straight into PUBLISHED would otherwise sidestep the
        # publish permission.
        if (request.data.get("status") not in (None, "", AuditForm.Status.DRAFT)
                and not _can_form(request.user, "publish")):
            return Response(
                {"detail": "Creating a form in that status requires "
                           "audit.form.publish."},
                status=http.HTTP_403_FORBIDDEN,
            )
        s = AuditFormSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(created_by=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


class AuditFormDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _obj(self, pk):
        try:
            return (AuditForm.objects
                    .prefetch_related("fields", "roles").get(pk=pk))
        except AuditForm.DoesNotExist as e:
            raise Http404 from e

    def get(self, request, pk):
        form = self._obj(pk)
        if not _can_access_form(request.user, form):
            return Response({"detail": "Not found."},
                            status=http.HTTP_404_NOT_FOUND)
        return Response(AuditFormSerializer(form).data)

    def patch(self, request, pk):
        if not _can_form(request.user, "edit"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        form = self._obj(pk)
        # Publishing pushes the form to a whole role's worth of staff and
        # closing stops collection — a different act from renaming a
        # question, so it carries its own key. Gate on the status
        # actually changing, since the builder PATCHes the whole form.
        new_status = request.data.get("status")
        if (new_status and new_status != form.status
                and not _can_form(request.user, "publish")):
            return Response(
                {"detail": "Changing a form's status requires "
                           "audit.form.publish."},
                status=http.HTTP_403_FORBIDDEN,
            )
        s = AuditFormSerializer(form, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)

    def delete(self, request, pk):
        if not _can_form(request.user, "delete"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        form = self._obj(pk)
        # `AuditSubmission.form` cascades, so deleting a form that has
        # been filled would silently destroy every collected response.
        # Same rule as a consumed leave allocation or an installment
        # with receipts: close it instead.
        if form.submissions.exists():
            return Response(
                {"detail": "This form has responses and cannot be deleted. "
                           "Close it instead to stop collection."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        form.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


class AuditFormSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            form = (AuditForm.objects
                    .prefetch_related("fields", "roles").get(pk=pk))
        except AuditForm.DoesNotExist as e:
            raise Http404 from e
        if form.status != AuditForm.Status.PUBLISHED:
            return Response({"detail": "This form is not open for submission."},
                            status=http.HTTP_400_BAD_REQUEST)
        if not _can_access_form(request.user, form):
            return Response(
                {"detail": "Your role is not allowed to fill this form."},
                status=http.HTTP_403_FORBIDDEN)
        s = SubmitAuditFormSerializer(data=request.data, context={"form": form})
        s.is_valid(raise_exception=True)
        cleaned = s.validated_data["cleaned"]  # {field_id: value}
        with transaction.atomic():
            submission = AuditSubmission.objects.create(
                form=form, submitted_by=request.user,
            )
            AuditAnswer.objects.bulk_create([
                AuditAnswer(submission=submission, field_id=fid, value=val)
                for fid, val in cleaned.items()
            ])
        return Response(AuditSubmissionSerializer(submission).data,
                        status=http.HTTP_201_CREATED)


class AuditSubmissionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (AuditSubmission.objects
              .select_related("form", "submitted_by")
              .prefetch_related("answers__field"))
        params = request.query_params
        # `?mine=1` asks for the caller's own submissions regardless of
        # `view_all` — without it a holder of that key could never see
        # just their own filed forms.
        if params.get("mine") == "1":
            qs = qs.filter(submitted_by=request.user)
        elif not _can_view_all_submissions(request.user):
            qs = qs.filter(submitted_by=request.user)
        if v := params.get("form"):
            qs = qs.filter(form_id=v)
        if v := params.get("role"):
            qs = qs.filter(form__roles__id=v).distinct()
        if v := params.get("search"):
            qs = qs.filter(form__title__icontains=v)
        if v := params.get("from"):
            if d := parse_date(v):
                qs = qs.filter(created_at__date__gte=d)
        if v := params.get("to"):
            if d := parse_date(v):
                qs = qs.filter(created_at__date__lte=d)
        return Response(AuditSubmissionSerializer(qs[:1000], many=True).data)


class AuditFormDuplicateView(APIView):
    """POST /api/audit-reports/forms/<pk>/duplicate/

    Copies a form so it can be adjusted and shared again without being
    rebuilt: title + " (Copy)", description, every field in order (type,
    options, required, help text, config) and the target roles. The copy
    starts as a DRAFT owned by the caller; responses are never copied
    and the original is untouched. Same key as creating a form.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _can_form(request.user, "add"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            src = (AuditForm.objects
                   .prefetch_related("fields", "roles").get(pk=pk))
        except AuditForm.DoesNotExist as e:
            raise Http404 from e

        base = src.title.strip()
        title = f"{base} (Copy)"
        n = 2
        while AuditForm.objects.filter(title=title).exists():
            title = f"{base} (Copy {n})"
            n += 1

        with transaction.atomic():
            copy = AuditForm.objects.create(
                title=title[:200], description=src.description,
                status=AuditForm.Status.DRAFT, created_by=request.user,
            )
            copy.roles.set(src.roles.all())
            AuditFormField.objects.bulk_create([
                AuditFormField(
                    form=copy, label=f.label, field_type=f.field_type,
                    options=list(f.options or []), required=f.required,
                    help_text=f.help_text, config=dict(f.config or {}),
                    sort_order=f.sort_order,
                )
                for f in src.fields.all()
            ])
        copy = AuditForm.objects.prefetch_related("fields", "roles").get(pk=copy.pk)
        return Response(AuditFormSerializer(copy).data,
                        status=http.HTTP_201_CREATED)


class AuditFormResponsesCsvView(APIView):
    """GET /api/audit-reports/forms/<pk>/responses.csv?from=&to=

    Every response to one form as a CSV: one row per submission, one
    column per question in the form's own order, so a form built today
    is downloadable with no further work. Multi-choice answers join
    with "; ". Same gate as the Filled Forms page
    (`audit.submission.view_all`); the whole set is written, not the
    on-screen page.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from apps.common.csv_export import csv_response

        if not _can_view_all_submissions(request.user):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        try:
            form = AuditForm.objects.prefetch_related("fields").get(pk=pk)
        except AuditForm.DoesNotExist as e:
            raise Http404 from e

        fields = list(form.fields.all())  # ordered by sort_order, id
        qs = (AuditSubmission.objects.filter(form=form)
              .select_related("submitted_by", "submitted_by__employee")
              .prefetch_related("answers")
              .order_by("created_at", "id"))
        params = request.query_params
        if v := params.get("from"):
            if d := parse_date(v):
                qs = qs.filter(created_at__date__gte=d)
        if v := params.get("to"):
            if d := parse_date(v):
                qs = qs.filter(created_at__date__lte=d)

        def cell(value):
            if value is None:
                return ""
            if isinstance(value, (list, tuple)):
                return "; ".join(str(x) for x in value if x not in (None, ""))
            return str(value)

        def rows():
            for n, s in enumerate(qs, start=1):
                by = s.submitted_by
                emp = getattr(by, "employee", None) if by else None
                answers = {a.field_id: a.value for a in s.answers.all()}
                yield [
                    n,
                    (by.full_name or by.username) if by else "",
                    emp.emp_code if emp else "",
                    timezone.localtime(s.created_at).strftime("%d-%m-%Y %H:%M"),
                    *[cell(answers.get(f.id)) for f in fields],
                ]

        header = ["Sr No", "Submitted by", "Emp code", "Submitted on",
                  *[f.label for f in fields]]
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in form.title).strip()
        return csv_response(f"{safe or 'Form'} - Responses.csv", header, rows())


class AuditFormRoleListView(APIView):
    """Lightweight role list (id + name) for the form builder's role
    picker. Available to anyone who can manage audit forms, so they don't
    need the separate roles.role permission."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not (_can_form(u, "view") or _can_form(u, "add")
                or _can_form(u, "edit")):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response(
            AuditFormRoleSerializer(Role.objects.all(), many=True).data)


class AuditSubmissionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            obj = (AuditSubmission.objects
                   .select_related("form", "submitted_by")
                   .prefetch_related("answers__field")
                   .get(pk=pk))
        except AuditSubmission.DoesNotExist as e:
            raise Http404 from e
        if not (_can_view_all_submissions(request.user)
                or obj.submitted_by_id == request.user.id):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        return Response(AuditSubmissionSerializer(obj).data)


# === Fee Receipts Export (Tally receipt vouchers) ===================
# Audit > Fee Receipts Export. One key, `audit.fee_export`; the rows and
# the CSV are built in `fee_export.py` so the download is the same file
# whoever pulls it. Non-superusers with assigned campuses see only those.

class FeeReceiptExportView(APIView):
    """GET — the preview, paginated with `page` / `page_size` (default
    50, max 500). Voucher numbers run on across pages so the page shows
    the same numbers the CSV will carry. `output=csv` ignores paging and
    streams every matching receipt."""
    permission_classes = [IsAuthenticated]

    PAGE_SIZE = 50
    MAX_PAGE_SIZE = 500

    def get(self, request):
        from . import fee_export

        u = request.user
        if not has_perm(u, "audit.fee_export"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)

        mine = None if u.is_superuser else (_assigned_campus_ids(u) or None)
        params = request.query_params
        for key in ("start_date", "end_date"):
            if (v := params.get(key)) and parse_date(v) is None:
                return Response({"detail": f"{key} must be YYYY-MM-DD."},
                                status=http.HTTP_400_BAD_REQUEST)

        qs = fee_export.apply_filters(
            fee_export.base_queryset(), params, campus_ids=mine,
        )
        if (params.get("output") or "").lower() == "csv":
            return fee_export.csv_response(qs)

        try:
            page_size = min(max(int(params.get("page_size") or self.PAGE_SIZE), 1),
                            self.MAX_PAGE_SIZE)
            page = max(int(params.get("page") or 1), 1)
        except ValueError:
            return Response({"detail": "page and page_size must be integers."},
                            status=http.HTTP_400_BAD_REQUEST)

        count = qs.count()
        total_pages = max(1, -(-count // page_size))
        page = min(page, total_pages)
        offset = (page - 1) * page_size
        rows = fee_export.voucher_rows(
            qs[offset: offset + page_size], start=offset + 1,
        )
        return Response({
            "count": count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_amount": str(
                Decimal(qs.aggregate(t=Sum("amount"))["t"] or 0).quantize(Decimal("0.01"))
            ),
            "rows": rows,
        })


class FeeReceiptExportOptionsView(APIView):
    """Campus / program / institute lists for the export filters. Audit
    users rarely hold the master.* keys, so the page cannot use the
    master endpoints."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        u = request.user
        if not has_perm(u, "audit.fee_export"):
            return Response({"detail": "Permission denied."},
                            status=http.HTTP_403_FORBIDDEN)
        from apps.master.models import Campus, Institute, Program

        campuses = Campus.objects.filter(is_active=True).order_by("name")
        mine = _assigned_campus_ids(u)
        if not u.is_superuser and mine:
            campuses = campuses.filter(id__in=mine)
        return Response({
            "campuses": [
                {"id": c.id, "name": c.name, "code": c.code} for c in campuses
            ],
            # `campus_ids`: campuses the program is offered at — its own
            # campus list plus any campus a batch of it runs at — so the
            # page can narrow programs once a campus is picked.
            "programs": [
                {"id": p.id, "name": p.name, "code": p.code,
                 "institute": p.institute_id,
                 "campus_ids": sorted(
                     set(p.campuses.values_list("id", flat=True))
                     | set(p.batches.values_list("campus_id", flat=True))
                 )}
                for p in Program.objects.filter(is_active=True)
                .prefetch_related("campuses", "batches")
                .order_by("institute__code", "name")
            ],
            "institutes": [
                {"id": i.id, "name": i.name, "code": i.code}
                for i in Institute.objects.filter(is_active=True).order_by("code")
            ],
        })
