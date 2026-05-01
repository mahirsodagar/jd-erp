from django.urls import path

from .views import (
    BulkWeeklyPublishView,
    ConflictCheckView,
    MyTimetableView,
    ScheduleSlotDetailView,
    ScheduleSlotListCreateView,
)

urlpatterns = [
    path("schedule/", ScheduleSlotListCreateView.as_view(), name="schedule-list-create"),
    path("schedule/<int:pk>/", ScheduleSlotDetailView.as_view(), name="schedule-detail"),
    path("schedule/bulk-weekly/", BulkWeeklyPublishView.as_view(), name="schedule-bulk-weekly"),
    path("schedule/conflict-check/", ConflictCheckView.as_view(), name="schedule-conflict-check"),

    path("timetable/me/", MyTimetableView.as_view(), name="timetable-me"),
]
