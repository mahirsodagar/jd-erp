from django.urls import path

from .views import (
    AttendanceFreezeView,
    AttendanceRosterView,
    AttendanceUnfreezeView,
    BatchAttendanceReportView,
    BulkWeeklyPublishView,
    ConflictCheckView,
    MyAttendanceView,
    MyTimetableView,
    ScheduleSlotDetailView,
    ScheduleSlotListCreateView,
    StudentAttendanceReportView,
)

urlpatterns = [
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
]
