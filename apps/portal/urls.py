from django.urls import path

from .views import (
    AssignmentListView, AssignmentSubjectsView, AssignmentSubmitView,
    AttendanceCalendarView, AttendanceReportView,
    ChangePasswordView, CoursewareListView, CoursewareSubjectsView,
    DashboardView, FeedbackLinkView, LeaveListCreateView, MeView,
    QualificationListCreateView, TestDetailView, TestListView,
    TestResultView, TestSubjectsView, TestSubmitView, TimetableView,
)

urlpatterns = [
    # Profile / auth
    path("me/", MeView.as_view(), name="portal-me"),
    path("change-password/", ChangePasswordView.as_view(),
         name="portal-change-password"),

    # Dashboard
    path("dashboard/", DashboardView.as_view(), name="portal-dashboard"),

    # Attendance
    path("attendance/calendar/", AttendanceCalendarView.as_view(),
         name="portal-attendance-calendar"),
    path("attendance/report/", AttendanceReportView.as_view(),
         name="portal-attendance-report"),

    # Timetable
    path("timetable/", TimetableView.as_view(), name="portal-timetable"),

    # Assignments
    path("assignments/subjects/", AssignmentSubjectsView.as_view(),
         name="portal-assignment-subjects"),
    path("assignments/", AssignmentListView.as_view(),
         name="portal-assignment-list"),
    path("assignments/<int:pk>/submit/", AssignmentSubmitView.as_view(),
         name="portal-assignment-submit"),

    # Courseware
    path("courseware/subjects/", CoursewareSubjectsView.as_view(),
         name="portal-courseware-subjects"),
    path("courseware/", CoursewareListView.as_view(),
         name="portal-courseware-list"),

    # Tests
    path("tests/subjects/", TestSubjectsView.as_view(),
         name="portal-test-subjects"),
    path("tests/", TestListView.as_view(), name="portal-test-list"),
    path("tests/<int:pk>/", TestDetailView.as_view(), name="portal-test-detail"),
    path("tests/<int:pk>/submit/", TestSubmitView.as_view(),
         name="portal-test-submit"),
    path("tests/<int:pk>/result/", TestResultView.as_view(),
         name="portal-test-result"),

    # Leaves
    path("leaves/", LeaveListCreateView.as_view(), name="portal-leaves"),

    # Feedback link
    path("feedback-link/", FeedbackLinkView.as_view(),
         name="portal-feedback-link"),

    # Qualifications (educational documents)
    path("qualifications/", QualificationListCreateView.as_view(),
         name="portal-qualifications"),
]
