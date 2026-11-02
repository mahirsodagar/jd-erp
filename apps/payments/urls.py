from django.urls import path

from .views import (
    PaymentRequestListView,
    PaymentRequestReceiptPdfView,
    PaymentRequestReconcileView,
    SmartGatewayStatusView,
)

urlpatterns = [
    path("smartgateway/status/", SmartGatewayStatusView.as_view(),
         name="smartgateway-status"),
    path("requests/", PaymentRequestListView.as_view(),
         name="payment-request-list"),
    path("requests/<int:pk>/reconcile/", PaymentRequestReconcileView.as_view(),
         name="payment-request-reconcile"),
    path("requests/<int:pk>/receipt/pdf/", PaymentRequestReceiptPdfView.as_view(),
         name="payment-request-receipt-pdf"),
]
