from django.urls import path

from .views import (
    CoursewareAttachmentAddView, CoursewareAttachmentDeleteView,
    CoursewareTopicDetailView, CoursewareTopicListCreateView,
)

urlpatterns = [
    path("topics/", CoursewareTopicListCreateView.as_view(),
         name="courseware-topic-list-create"),
    path("topics/<int:pk>/", CoursewareTopicDetailView.as_view(),
         name="courseware-topic-detail"),
    path("topics/<int:pk>/attachments/", CoursewareAttachmentAddView.as_view(),
         name="courseware-attachment-add"),
    path("attachments/<int:pk>/", CoursewareAttachmentDeleteView.as_view(),
         name="courseware-attachment-delete"),
]
