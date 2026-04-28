from django.urls import path

from .views import (
    CampusDetailView,
    CampusListCreateView,
    CampusProgramsView,
    CityDetailView,
    CityListCreateView,
    InstituteDetailView,
    InstituteListCreateView,
    LeadSourceDetailView,
    LeadSourceListCreateView,
    ProgramDetailView,
    ProgramListCreateView,
    StateDetailView,
    StateListView,
    StateManageView,
)

urlpatterns = [
    path("institutes/", InstituteListCreateView.as_view(), name="institute-list-create"),
    path("institutes/<int:pk>/", InstituteDetailView.as_view(), name="institute-detail"),

    path("states/", StateListView.as_view(), name="state-list"),
    path("states/create/", StateManageView.as_view(), name="state-create"),
    path("states/<int:pk>/", StateDetailView.as_view(), name="state-detail"),

    path("cities/", CityListCreateView.as_view(), name="city-list-create"),
    path("cities/<int:pk>/", CityDetailView.as_view(), name="city-detail"),

    path("campuses/", CampusListCreateView.as_view(), name="campus-list-create"),
    path("campuses/<int:pk>/", CampusDetailView.as_view(), name="campus-detail"),
    path("campuses/<int:pk>/programs/", CampusProgramsView.as_view(), name="campus-programs"),

    path("programs/", ProgramListCreateView.as_view(), name="program-list-create"),
    path("programs/<int:pk>/", ProgramDetailView.as_view(), name="program-detail"),

    path("lead-sources/", LeadSourceListCreateView.as_view(), name="lead-source-list-create"),
    path("lead-sources/<int:pk>/", LeadSourceDetailView.as_view(), name="lead-source-detail"),
]
