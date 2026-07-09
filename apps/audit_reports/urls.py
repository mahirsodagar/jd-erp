from django.urls import path

from .views import (
    AdminDailyReportDetailView,
    AdminDailyReportListCreateView,
    AuditFormDetailView,
    AuditFormListCreateView,
    AuditFormRoleListView,
    AuditFormSubmitView,
    AuditSubmissionDetailView,
    AuditSubmissionListView,
    BatchMentorReportListCreateView,
    BatchProgressionView,
    ComplianceFlagListCreateView,
    ComplianceFlagResolveView,
    ConsolidatedMonthlyView,
    CourseEndReportListCreateView,
    CourseEndReportReviewView,
    AuditFilterAdminDailyAuthorsView,
    AuditFilterEmployeesView,
    AuditFilterOptionsView,
    FacultyDailyComputedView,
    FacultyDailyReportDetailView,
    FacultyDailyReportListCreateView,
    FacultySelfAppraisalListCreateView,
    FeedbackSummaryView,
    LiveFacultyTrackingView,
    SelfAppraisalReviewView,
    StudentFeedbackListCreateView,
    TimetableAdherenceView,
    ZeroHourReportDetailView,
    ZeroHourReportListCreateView,
)

urlpatterns = [
    # Dynamic audit form builder
    path("forms/", AuditFormListCreateView.as_view(),
         name="audit-form-list-create"),
    path("forms/<int:pk>/", AuditFormDetailView.as_view(),
         name="audit-form-detail"),
    path("forms/<int:pk>/submit/", AuditFormSubmitView.as_view(),
         name="audit-form-submit"),
    path("form-roles/", AuditFormRoleListView.as_view(),
         name="audit-form-role-list"),
    path("submissions/", AuditSubmissionListView.as_view(),
         name="audit-submission-list"),
    path("submissions/<int:pk>/", AuditSubmissionDetailView.as_view(),
         name="audit-submission-detail"),

    # Logs
    path("faculty-daily/", FacultyDailyReportListCreateView.as_view(),
         name="faculty-daily-list-create"),
    path("faculty-daily/<int:pk>/", FacultyDailyReportDetailView.as_view(),
         name="faculty-daily-detail"),
    path("faculty-daily-computed/", FacultyDailyComputedView.as_view(),
         name="faculty-daily-computed"),

    # Audit cascade filter lookups (audit-gated; no master.* perms needed)
    path("filters/options/", AuditFilterOptionsView.as_view(),
         name="audit-filter-options"),
    path("filters/employees/", AuditFilterEmployeesView.as_view(),
         name="audit-filter-employees"),
    path("filters/admin-daily-authors/",
         AuditFilterAdminDailyAuthorsView.as_view(),
         name="audit-filter-admin-daily-authors"),

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

    # Zero-Hour report (Academics fill + Audit review)
    path("zero-hour/", ZeroHourReportListCreateView.as_view(),
         name="zero-hour-list-create"),
    path("zero-hour/<int:pk>/", ZeroHourReportDetailView.as_view(),
         name="zero-hour-detail"),

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
