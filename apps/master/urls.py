from django.urls import path

from .views import (
    AcademicYearDetailView,
    AcademicYearListCreateView,
    BatchDetailView,
    BatchListCreateView,
    CampusDetailView,
    CampusListCreateView,
    CampusProgramsView,
    CityDetailView,
    CityListCreateView,
    CourseDetailView,
    CourseListCreateView,
    DegreeDetailView,
    DegreeListCreateView,
    FeeTemplateDetailView,
    FeeTemplateListCreateView,
    InstituteDetailView,
    InstituteListCreateView,
    LeadSourceDetailView,
    LeadSourceListCreateView,
    ProgramDetailView,
    ProgramListCreateView,
    SemesterDetailView,
    SemesterListCreateView,
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

    path("academic-years/", AcademicYearListCreateView.as_view(), name="academic-year-list-create"),
    path("academic-years/<int:pk>/", AcademicYearDetailView.as_view(), name="academic-year-detail"),

    path("degrees/", DegreeListCreateView.as_view(), name="degree-list-create"),
    path("degrees/<int:pk>/", DegreeDetailView.as_view(), name="degree-detail"),

    path("courses/", CourseListCreateView.as_view(), name="course-list-create"),
    path("courses/<int:pk>/", CourseDetailView.as_view(), name="course-detail"),

    path("semesters/", SemesterListCreateView.as_view(), name="semester-list-create"),
    path("semesters/<int:pk>/", SemesterDetailView.as_view(), name="semester-detail"),

    path("batches/", BatchListCreateView.as_view(), name="batch-list-create"),
    path("batches/<int:pk>/", BatchDetailView.as_view(), name="batch-detail"),

    path("fee-templates/", FeeTemplateListCreateView.as_view(), name="fee-template-list-create"),
    path("fee-templates/<int:pk>/", FeeTemplateDetailView.as_view(), name="fee-template-detail"),
]
