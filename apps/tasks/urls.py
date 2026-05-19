from django.urls import path

from .views import TaskCompleteView, TaskDetailView, TaskListCreateView

urlpatterns = [
    path("", TaskListCreateView.as_view(), name="task-list-create"),
    path("<int:pk>/", TaskDetailView.as_view(), name="task-detail"),
    path("<int:pk>/complete/", TaskCompleteView.as_view(),
         name="task-complete"),
]
