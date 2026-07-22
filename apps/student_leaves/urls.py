from django.urls import path

from .views import (
    StudentLeaveDecideView,
    StudentLeaveDeleteView,
    StudentLeaveListView,
    StudentLeaveReportView,
)

urlpatterns = [
    path("", StudentLeaveListView.as_view(), name="student-leave-list"),
    path("report/", StudentLeaveReportView.as_view(), name="student-leave-report"),
    path("<int:pk>/decide/", StudentLeaveDecideView.as_view(),
         name="student-leave-decide"),
    path("<int:pk>/", StudentLeaveDeleteView.as_view(),
         name="student-leave-delete"),
]
