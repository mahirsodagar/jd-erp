from django.urls import path

from .views import (
    AllocationDetailView,
    AllocationListCreateView,
    BulkAllocationView,
    CompOffBalanceView,
    CompOffDecisionView,
    CompOffListCreateView,
    LeaveApplicationDetailView,
    LeaveApplicationListCreateView,
    LeaveBalancesView,
    LeaveDashboardView,
    LeaveDecisionView,
    LeaveReportSummaryView,
    LeaveTypeDetailView,
    LeaveTypeListCreateView,
)

urlpatterns = [
    path("types/", LeaveTypeListCreateView.as_view(), name="leave-type-list-create"),
    path("types/<int:pk>/", LeaveTypeDetailView.as_view(), name="leave-type-detail"),

    path("allocations/", AllocationListCreateView.as_view(), name="allocation-list-create"),
    path("allocations/bulk/", BulkAllocationView.as_view(), name="allocation-bulk"),
    path("allocations/<int:pk>/", AllocationDetailView.as_view(), name="allocation-detail"),

    path("applications/", LeaveApplicationListCreateView.as_view(), name="application-list-create"),
    path("applications/balances/", LeaveBalancesView.as_view(), name="application-balances"),
    path("applications/dashboard/", LeaveDashboardView.as_view(), name="application-dashboard"),
    path("applications/<int:pk>/", LeaveApplicationDetailView.as_view(), name="application-detail"),
    path("applications/<int:pk>/decision/", LeaveDecisionView.as_view(), name="application-decision"),

    path("comp-off/", CompOffListCreateView.as_view(), name="compoff-list-create"),
    path("comp-off/balance/", CompOffBalanceView.as_view(), name="compoff-balance"),
    path("comp-off/<int:pk>/decision/", CompOffDecisionView.as_view(), name="compoff-decision"),

    path("reports/summary/", LeaveReportSummaryView.as_view(), name="report-summary"),
]
