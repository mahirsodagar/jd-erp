from django.urls import path

from .views import (
    AudiencePreviewView, CampaignActionView, CampaignDetailView,
    CampaignListCreateView, CampaignRecipientsView, SuppressionDetailView,
    SuppressionListCreateView, TemplateDetailView, TemplateListCreateView,
    TestSendView,
)

urlpatterns = [
    path("audience/preview/", AudiencePreviewView.as_view(), name="comms-audience-preview"),
    path("campaigns/", CampaignListCreateView.as_view(), name="comms-campaign-list"),
    path("campaigns/test-send/", TestSendView.as_view(), name="comms-test-send"),
    path("campaigns/<int:pk>/", CampaignDetailView.as_view(), name="comms-campaign-detail"),
    path("campaigns/<int:pk>/recipients/", CampaignRecipientsView.as_view(),
         name="comms-campaign-recipients"),
    path("campaigns/<int:pk>/<slug:action>/", CampaignActionView.as_view(),
         name="comms-campaign-action"),
    path("templates/", TemplateListCreateView.as_view(), name="comms-template-list"),
    path("templates/<int:pk>/", TemplateDetailView.as_view(), name="comms-template-detail"),
    path("suppression/", SuppressionListCreateView.as_view(), name="comms-suppression-list"),
    path("suppression/<int:pk>/", SuppressionDetailView.as_view(), name="comms-suppression-detail"),
]
