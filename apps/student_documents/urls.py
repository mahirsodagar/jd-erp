from django.urls import path

from .views import DocumentRequestDecideView, DocumentRequestListView

urlpatterns = [
    path("", DocumentRequestListView.as_view(), name="document-request-list"),
    path("<int:pk>/decide/", DocumentRequestDecideView.as_view(),
         name="document-request-decide"),
]
