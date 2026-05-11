from django.urls import path

from .views import UploadTestView

urlpatterns = [
    path("upload-test/", UploadTestView.as_view(), name="upload-test"),
]
