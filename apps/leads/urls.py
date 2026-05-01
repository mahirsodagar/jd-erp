from django.urls import path

from .reports import (
    ConversionFunnelView,
    CounsellorLeaderboardView,
    CoursewiseRevenueView,
    DuplicateFrequencyView,
    LostLeadAnalysisView,
    SummaryView,
    TimePerStageView,
)
from .views import (
    LeadCommunicationListCreateView,
    LeadDetailView,
    LeadFollowupDetailView,
    LeadFollowupListCreateView,
    LeadHistoryView,
    LeadIntakeView,
    LeadListCreateView,
    LeadPromoteView,
    LeadReassignView,
    LeadStatusView,
    PoolDetailView,
    PoolListCreateView,
    PoolMembershipDetailView,
    PoolMembershipListCreateView,
)

urlpatterns = [
    path("intake/", LeadIntakeView.as_view(), name="lead-intake"),

    # F.3 — counsellor pools
    path("pools/", PoolListCreateView.as_view(), name="pool-list-create"),
    path("pools/<int:pk>/", PoolDetailView.as_view(), name="pool-detail"),
    path("pool-members/", PoolMembershipListCreateView.as_view(), name="pool-member-list-create"),
    path("pool-members/<int:pk>/", PoolMembershipDetailView.as_view(), name="pool-member-detail"),

    # F.6 — reports
    path("reports/funnel/", ConversionFunnelView.as_view(), name="report-funnel"),
    path("reports/leaderboard/", CounsellorLeaderboardView.as_view(), name="report-leaderboard"),
    path("reports/time-per-stage/", TimePerStageView.as_view(), name="report-time-per-stage"),
    path("reports/lost-analysis/", LostLeadAnalysisView.as_view(), name="report-lost"),
    path("reports/coursewise-revenue/", CoursewiseRevenueView.as_view(), name="report-coursewise"),
    path("reports/duplicates/", DuplicateFrequencyView.as_view(), name="report-duplicates"),
    path("reports/summary/", SummaryView.as_view(), name="report-summary"),

    path("", LeadListCreateView.as_view(), name="lead-list-create"),
    path("<int:pk>/", LeadDetailView.as_view(), name="lead-detail"),
    path("<int:pk>/status/", LeadStatusView.as_view(), name="lead-status"),
    path("<int:pk>/reassign/", LeadReassignView.as_view(), name="lead-reassign"),
    path("<int:pk>/promote/", LeadPromoteView.as_view(), name="lead-promote"),
    path("<int:pk>/history/", LeadHistoryView.as_view(), name="lead-history"),

    path("<int:pk>/followups/",
         LeadFollowupListCreateView.as_view(), name="lead-followup-list-create"),
    path("followups/<int:pk>/",
         LeadFollowupDetailView.as_view(), name="lead-followup-detail"),

    path("<int:pk>/communications/",
         LeadCommunicationListCreateView.as_view(), name="lead-communication-list-create"),
]
