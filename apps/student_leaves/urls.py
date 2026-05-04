from django.urls import path

from .views import StudentLeaveDecideView, StudentLeaveListView

urlpatterns = [
    path("", StudentLeaveListView.as_view(), name="student-leave-list"),
    path("<int:pk>/decide/", StudentLeaveDecideView.as_view(),
         name="student-leave-decide"),
]
