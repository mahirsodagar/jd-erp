from django.urls import path

from .views import (
    ConcessionDecisionView,
    ConcessionDetailView,
    ConcessionListCreateView,
    EnrollmentBalanceView,
    FeeReceiptCancelView,
    FeeReceiptDetailView,
    FeeReceiptListCreateView,
    FeeReceiptPdfView,
    FeesMeReceiptPdfView,
    FeesMeReceiptsView,
    FeesMeView,
    InstallmentDetailView,
    InstallmentListCreateView,
)

urlpatterns = [
    # Student panel
    path("me/", FeesMeView.as_view(), name="fees-me"),
    path("me/receipts/", FeesMeReceiptsView.as_view(), name="fees-me-receipts"),
    path("me/receipts/<int:pk>/pdf/", FeesMeReceiptPdfView.as_view(), name="fees-me-receipt-pdf"),

    # Installments
    path("installments/", InstallmentListCreateView.as_view(), name="installment-list-create"),
    path("installments/<int:pk>/", InstallmentDetailView.as_view(), name="installment-detail"),

    # Receipts
    path("receipts/", FeeReceiptListCreateView.as_view(), name="receipt-list-create"),
    path("receipts/<int:pk>/", FeeReceiptDetailView.as_view(), name="receipt-detail"),
    path("receipts/<int:pk>/cancel/", FeeReceiptCancelView.as_view(), name="receipt-cancel"),
    path("receipts/<int:pk>/pdf/", FeeReceiptPdfView.as_view(), name="receipt-pdf"),

    # Concessions
    path("concessions/", ConcessionListCreateView.as_view(), name="concession-list-create"),
    path("concessions/<int:pk>/", ConcessionDetailView.as_view(), name="concession-detail"),
    path("concessions/<int:pk>/decision/", ConcessionDecisionView.as_view(), name="concession-decision"),

    # Balance per enrollment
    path("enrollments/<int:pk>/balance/", EnrollmentBalanceView.as_view(), name="enrollment-balance"),
]
