from django.urls import path

from .views import (
    AdminDailyReportDetailView,
    AdminDailyReportListCreateView,
    BatchMentorReportListCreateView,
    BatchProgressionView,
    ComplianceFlagListCreateView,
    ComplianceFlagResolveView,
    ConsolidatedMonthlyView,
    CourseEndReportListCreateView,
    CourseEndReportReviewView,
    FacultyDailyReportDetailView,
    FacultyDailyReportListCreateView,
    FacultySelfAppraisalListCreateView,
    FeedbackSummaryView,
    LiveFacultyTrackingView,
    SelfAppraisalReviewView,
    StudentFeedbackListCreateView,
    TimetableAdherenceView,
)

urlpatterns = [
    # Logs
    path("faculty-daily/", FacultyDailyReportListCreateView.as_view(),
         name="faculty-daily-list-create"),
    path("faculty-daily/<int:pk>/", FacultyDailyReportDetailView.as_view(),
         name="faculty-daily-detail"),

    path("admin-daily/", AdminDailyReportListCreateView.as_view(),
         name="admin-daily-list-create"),
    path("admin-daily/<int:pk>/", AdminDailyReportDetailView.as_view(),
         name="admin-daily-detail"),

    # Course-end + Batch-mentor
    path("course-end/", CourseEndReportListCreateView.as_view(),
         name="course-end-list-create"),
    path("course-end/<int:pk>/review/", CourseEndReportReviewView.as_view(),
         name="course-end-review"),

    path("batch-mentor/", BatchMentorReportListCreateView.as_view(),
         name="batch-mentor-list-create"),

    # Feedback + Self-appraisal
    path("feedback/", StudentFeedbackListCreateView.as_view(),
         name="student-feedback-list-create"),
    path("self-appraisal/", FacultySelfAppraisalListCreateView.as_view(),
         name="self-appraisal-list-create"),
    path("self-appraisal/<int:pk>/review/", SelfAppraisalReviewView.as_view(),
         name="self-appraisal-review"),

    # Compliance
    path("compliance/", ComplianceFlagListCreateView.as_view(),
         name="compliance-list-create"),
    path("compliance/<int:pk>/resolve/", ComplianceFlagResolveView.as_view(),
         name="compliance-resolve"),

    # Dashboards
    path("dashboards/live-faculty/", LiveFacultyTrackingView.as_view(),
         name="dash-live-faculty"),
    path("dashboards/timetable-adherence/", TimetableAdherenceView.as_view(),
         name="dash-timetable-adherence"),
    path("dashboards/batch/<int:pk>/progression/", BatchProgressionView.as_view(),
         name="dash-batch-progression"),
    path("dashboards/instructor/<int:pk>/feedback-summary/",
         FeedbackSummaryView.as_view(), name="dash-feedback-summary"),
    path("dashboards/consolidated-monthly/", ConsolidatedMonthlyView.as_view(),
         name="dash-consolidated-monthly"),
]
