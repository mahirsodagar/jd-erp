from django.urls import path

from .views import (
    AssignmentDetailView,
    AssignmentListCreateView,
    AssignmentSubmissionsView,
    AttendanceFreezeView,
    AttendanceRosterView,
    AttendanceUnfreezeView,
    BatchAttendanceReportView,
    BulkWeeklyPublishView,
    ConflictCheckView,
    MarksDetailView,
    MarksListCreateView,
    MarksPublishView,
    MarksUnpublishView,
    MyAssignmentsView,
    MyAttendanceView,
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
]
