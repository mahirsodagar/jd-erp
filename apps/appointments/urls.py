from django.urls import path

from .views import (
    AppointmentCompleteView, AppointmentDecideView, AppointmentListView,
)

urlpatterns = [
    path("", AppointmentListView.as_view(), name="appointment-list"),
    path("<int:pk>/decide/", AppointmentDecideView.as_view(),
         name="appointment-decide"),
    path("<int:pk>/complete/", AppointmentCompleteView.as_view(),
         name="appointment-complete"),
]
