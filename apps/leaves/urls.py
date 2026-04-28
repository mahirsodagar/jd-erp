from django.urls import path

from .views import (
    AllocationDetailView,
    AllocationListCreateView,
    BulkAllocationView,
    CompOffBalanceView,
    CompOffDecisionView,
    CompOffListCreateView,
    EmailLogListView,
    HolidayDetailView,
    HolidayListCreateView,
    LeaveApplicationDetailView,
    LeaveApplicationListCreateView,
    LeaveBalancesView,
    LeaveCancelView,
    LeaveDecisionView,
    LeaveReportSummaryView,
    LeaveTypeDetailView,
    LeaveTypeListCreateView,
    LeaveWithdrawView,
    SessionDetailView,
    SessionListCreateView,
)

urlpatterns = [
    path("types/", LeaveTypeListCreateView.as_view(), name="leave-type-list-create"),
    path("types/<int:pk>/", LeaveTypeDetailView.as_view(), name="leave-type-detail"),

    path("sessions/", SessionListCreateView.as_view(), name="session-list-create"),
    path("sessions/<int:pk>/", SessionDetailView.as_view(), name="session-detail"),

    path("allocations/", AllocationListCreateView.as_view(), name="allocation-list-create"),
    path("allocations/bulk/", BulkAllocationView.as_view(), name="allocation-bulk"),
    path("allocations/<int:pk>/", AllocationDetailView.as_view(), name="allocation-detail"),

    path("applications/", LeaveApplicationListCreateView.as_view(), name="application-list-create"),
    path("applications/balances/", LeaveBalancesView.as_view(), name="application-balances"),
    path("applications/<int:pk>/", LeaveApplicationDetailView.as_view(), name="application-detail"),
    path("applications/<int:pk>/decision/", LeaveDecisionView.as_view(), name="application-decision"),
    path("applications/<int:pk>/withdraw/", LeaveWithdrawView.as_view(), name="application-withdraw"),
    path("applications/<int:pk>/cancel/", LeaveCancelView.as_view(), name="application-cancel"),

    path("comp-off/", CompOffListCreateView.as_view(), name="compoff-list-create"),
    path("comp-off/balance/", CompOffBalanceView.as_view(), name="compoff-balance"),
    path("comp-off/<int:pk>/decision/", CompOffDecisionView.as_view(), name="compoff-decision"),

    path("holidays/", HolidayListCreateView.as_view(), name="holiday-list-create"),
    path("holidays/<int:pk>/", HolidayDetailView.as_view(), name="holiday-detail"),

    path("reports/summary/", LeaveReportSummaryView.as_view(), name="report-summary"),

    path("email-log/", EmailLogListView.as_view(), name="email-log-list"),
]
