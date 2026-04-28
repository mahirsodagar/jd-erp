from django.urls import path

from .views import (
    CampusDetailView,
    CampusListCreateView,
    CampusProgramsView,
    LeadSourceDetailView,
    LeadSourceListCreateView,
    ProgramDetailView,
    ProgramListCreateView,
)

urlpatterns = [
    path("campuses/", CampusListCreateView.as_view(), name="campus-list-create"),
    path("campuses/<int:pk>/", CampusDetailView.as_view(), name="campus-detail"),
    path("campuses/<int:pk>/programs/", CampusProgramsView.as_view(), name="campus-programs"),

    path("programs/", ProgramListCreateView.as_view(), name="program-list-create"),
    path("programs/<int:pk>/", ProgramDetailView.as_view(), name="program-detail"),

    path("lead-sources/", LeadSourceListCreateView.as_view(), name="lead-source-list-create"),
    path("lead-sources/<int:pk>/", LeadSourceDetailView.as_view(), name="lead-source-detail"),
]
