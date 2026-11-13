from django.urls import path

from .views import (
    ExperienceLetterPdfView, MyRelievingChainView, MyRelievingView,
    RelievingDecideView, RelievingDetailView, RelievingFinalizeView,
    RelievingLetterPdfView, RelievingListCreateView,
    RelievingManagersForInstituteView, RelievingManagersView,
    RelievingReportView, RelievingWithdrawView, SendExperienceLetterView,
)

urlpatterns = [
    # Dashboard list (approver-of / view_all) + submit
    path("", RelievingListCreateView.as_view(), name="relieving-list-create"),
    # My Relieving page: own applications only
    path("me/", MyRelievingView.as_view(), name="relieving-me"),
    # Relieving Report page (hr.relieving.report), ?output=csv
    path("report/", RelievingReportView.as_view(), name="relieving-report"),
    # Relieving Managers master (L1–L4 per institute)
    path("managers/", RelievingManagersView.as_view(), name="relieving-managers"),
    path("managers/mine/", MyRelievingChainView.as_view(),
         name="relieving-managers-mine"),
    path("managers/<int:institute_id>/", RelievingManagersForInstituteView.as_view(),
         name="relieving-managers-institute"),
    path("<int:pk>/", RelievingDetailView.as_view(), name="relieving-detail"),
    path("<int:pk>/decide/<int:level>/", RelievingDecideView.as_view(),
         name="relieving-decide"),
    path("<int:pk>/finalize/", RelievingFinalizeView.as_view(),
         name="relieving-finalize"),
    path("<int:pk>/send-experience-letter/", SendExperienceLetterView.as_view(),
         name="relieving-send-experience-letter"),
    path("<int:pk>/withdraw/", RelievingWithdrawView.as_view(),
         name="relieving-withdraw"),
    path("<int:pk>/relieving-letter.pdf", RelievingLetterPdfView.as_view(),
         name="relieving-letter-pdf"),
    path("<int:pk>/experience-letter.pdf", ExperienceLetterPdfView.as_view(),
         name="experience-letter-pdf"),
]
