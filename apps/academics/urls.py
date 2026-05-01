from django.urls import path

from .views import (
    AlumniDetailView,
    AlumniListView,
    AlumniMeView,
    AssignmentDetailView,
    AssignmentListCreateView,
    AssignmentSubmissionsView,
    AttendanceFreezeView,
    AttendanceRosterView,
    AttendanceUnfreezeView,
    BatchAttendanceReportView,
    BulkWeeklyPublishView,
    CertificateDetailView,
    CertificateEligibilityCheckView,
    CertificateIssueView,
    CertificateListCreateView,
    CertificatePdfView,
    CertificateRejectView,
    ConflictCheckView,
    EnrollmentGraduateView,
    MarksDetailView,
    MarksListCreateView,
    MarksPublishView,
    MarksUnpublishView,
    MyAssignmentsView,
    MyAttendanceView,
    MyCertificatesView,
    MyTimetableView,
    MyTranscriptView,
    ScheduleSlotDetailView,
    ScheduleSlotListCreateView,
    StudentAttendanceReportView,
    StudentSubmitView,
    StudentTranscriptView,
    SubmissionGradeView,
)

urlpatterns = [
    # G.1 — Schedule
    path("schedule/", ScheduleSlotListCreateView.as_view(), name="schedule-list-create"),
    path("schedule/<int:pk>/", ScheduleSlotDetailView.as_view(), name="schedule-detail"),
    path("schedule/bulk-weekly/", BulkWeeklyPublishView.as_view(), name="schedule-bulk-weekly"),
    path("schedule/conflict-check/", ConflictCheckView.as_view(), name="schedule-conflict-check"),
    path("timetable/me/", MyTimetableView.as_view(), name="timetable-me"),

    # G.2 — Attendance
    path("schedule/<int:pk>/attendance/", AttendanceRosterView.as_view(),
         name="attendance-roster"),
    path("schedule/<int:pk>/attendance/freeze/", AttendanceFreezeView.as_view(),
         name="attendance-freeze"),
    path("schedule/<int:pk>/attendance/unfreeze/", AttendanceUnfreezeView.as_view(),
         name="attendance-unfreeze"),
    path("attendance/batch/<int:pk>/report/", BatchAttendanceReportView.as_view(),
         name="attendance-batch-report"),
    path("attendance/student/<int:pk>/report/", StudentAttendanceReportView.as_view(),
         name="attendance-student-report"),
    path("attendance/me/", MyAttendanceView.as_view(), name="attendance-me"),

    # G.3 — Assignments + Marks + Transcript
    path("assignments/", AssignmentListCreateView.as_view(), name="assignment-list-create"),
    path("assignments/me/", MyAssignmentsView.as_view(), name="assignment-me"),
    path("assignments/<int:pk>/", AssignmentDetailView.as_view(), name="assignment-detail"),
    path("assignments/<int:pk>/submissions/", AssignmentSubmissionsView.as_view(),
         name="assignment-submissions"),
    path("assignments/<int:pk>/submit/", StudentSubmitView.as_view(),
         name="assignment-submit"),
    path("submissions/<int:pk>/grade/", SubmissionGradeView.as_view(),
         name="submission-grade"),

    path("marks/", MarksListCreateView.as_view(), name="marks-list-create"),
    path("marks/<int:pk>/", MarksDetailView.as_view(), name="marks-detail"),
    path("marks/<int:pk>/publish/", MarksPublishView.as_view(), name="marks-publish"),
    path("marks/<int:pk>/unpublish/", MarksUnpublishView.as_view(), name="marks-unpublish"),

    path("transcript/student/<int:pk>/", StudentTranscriptView.as_view(),
         name="transcript-student"),
    path("transcript/me/", MyTranscriptView.as_view(), name="transcript-me"),

    # G.5 — Certificates + Alumni
    path("certificates/", CertificateListCreateView.as_view(),
         name="certificate-list-create"),
    path("certificates/me/", MyCertificatesView.as_view(), name="certificate-me"),
    path("certificates/<int:pk>/", CertificateDetailView.as_view(),
         name="certificate-detail"),
    path("certificates/<int:pk>/eligibility-check/",
         CertificateEligibilityCheckView.as_view(),
         name="certificate-eligibility-check"),
    path("certificates/<int:pk>/issue/", CertificateIssueView.as_view(),
         name="certificate-issue"),
    path("certificates/<int:pk>/reject/", CertificateRejectView.as_view(),
         name="certificate-reject"),
    path("certificates/<int:pk>/pdf/", CertificatePdfView.as_view(),
         name="certificate-pdf"),

    path("enrollments/<int:pk>/graduate/", EnrollmentGraduateView.as_view(),
         name="enrollment-graduate"),

    path("alumni/", AlumniListView.as_view(), name="alumni-list"),
    path("alumni/me/", AlumniMeView.as_view(), name="alumni-me"),
    path("alumni/<int:pk>/", AlumniDetailView.as_view(), name="alumni-detail"),
]


# === G.4 — Online Tests =============================================
from .views import (
    AttemptStartView, AttemptSubmitView, AttemptViewWithQuestions,
    MyTestsView, ResponseReviewView, TestAttemptsListView, TestCloseView,
    TestDetailView, TestListCreateView, TestMapView, TestPublishView,
    TestQuestionDetailView, TestQuestionListCreateView, TestReportView,
)

urlpatterns += [
    path("tests/", TestListCreateView.as_view(), name="test-list-create"),
    path("tests/me/", MyTestsView.as_view(), name="test-me"),
    path("tests/<int:pk>/", TestDetailView.as_view(), name="test-detail"),
    path("tests/<int:pk>/publish/", TestPublishView.as_view(),
         name="test-publish"),
    path("tests/<int:pk>/close/", TestCloseView.as_view(), name="test-close"),
    path("tests/<int:pk>/questions/", TestQuestionListCreateView.as_view(),
         name="test-question-list-create"),
    path("tests/<int:pk>/map/", TestMapView.as_view(), name="test-map"),
    path("tests/<int:pk>/attempts/", TestAttemptsListView.as_view(),
         name="test-attempts"),
    path("tests/<int:pk>/report/", TestReportView.as_view(),
         name="test-report"),

    path("questions/<int:pk>/", TestQuestionDetailView.as_view(),
         name="test-question-detail"),

    path("attempts/<int:pk>/", AttemptViewWithQuestions.as_view(),
         name="attempt-detail"),
    path("attempts/<int:pk>/start/", AttemptStartView.as_view(),
         name="attempt-start"),
    path("attempts/<int:pk>/submit/", AttemptSubmitView.as_view(),
         name="attempt-submit"),

    path("responses/<int:pk>/review/", ResponseReviewView.as_view(),
         name="response-review"),
]
