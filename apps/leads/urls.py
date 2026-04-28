from django.urls import path

from .views import (
    LeadCommunicationListCreateView,
    LeadDetailView,
    LeadFollowupDetailView,
    LeadFollowupListCreateView,
    LeadHistoryView,
    LeadIntakeView,
    LeadListCreateView,
    LeadReassignView,
    LeadStatusView,
)

urlpatterns = [
    path("intake/", LeadIntakeView.as_view(), name="lead-intake"),

    path("", LeadListCreateView.as_view(), name="lead-list-create"),
    path("<int:pk>/", LeadDetailView.as_view(), name="lead-detail"),
    path("<int:pk>/status/", LeadStatusView.as_view(), name="lead-status"),
    path("<int:pk>/reassign/", LeadReassignView.as_view(), name="lead-reassign"),
    path("<int:pk>/history/", LeadHistoryView.as_view(), name="lead-history"),

    path("<int:pk>/followups/",
         LeadFollowupListCreateView.as_view(), name="lead-followup-list-create"),
    path("followups/<int:pk>/",
         LeadFollowupDetailView.as_view(), name="lead-followup-detail"),

    path("<int:pk>/communications/",
         LeadCommunicationListCreateView.as_view(), name="lead-communication-list-create"),
]
