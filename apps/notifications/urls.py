from django.urls import path

from .views import MarkAllReadView, MarkReadView, MyNotificationsView

urlpatterns = [
    path("", MyNotificationsView.as_view(), name="notifications-mine"),
    path("read-all/", MarkAllReadView.as_view(), name="notifications-read-all"),
    path("<int:pk>/read/", MarkReadView.as_view(), name="notifications-read"),
]
