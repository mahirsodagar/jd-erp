from django.urls import path

from .views import (
    ExperienceLetterPdfView, MyRelievingView,
    RelievingDecideView, RelievingDetailView, RelievingFinalizeView,
    RelievingLetterPdfView, RelievingListCreateView, RelievingWithdrawView,
)

urlpatterns = [
    path("", RelievingListCreateView.as_view(), name="relieving-list-create"),
    path("me/", MyRelievingView.as_view(), name="relieving-me"),
    path("<int:pk>/", RelievingDetailView.as_view(), name="relieving-detail"),
    path("<int:pk>/decide/<int:level>/", RelievingDecideView.as_view(),
         name="relieving-decide"),
    path("<int:pk>/finalize/", RelievingFinalizeView.as_view(),
         name="relieving-finalize"),
    path("<int:pk>/withdraw/", RelievingWithdrawView.as_view(),
         name="relieving-withdraw"),
    path("<int:pk>/relieving-letter.pdf", RelievingLetterPdfView.as_view(),
         name="relieving-letter-pdf"),
    path("<int:pk>/experience-letter.pdf", ExperienceLetterPdfView.as_view(),
         name="experience-letter-pdf"),
]
