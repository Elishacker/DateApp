"""Payments REST routes, mounted at /api/v1/payments/."""
from django.urls import path

from . import api_views

app_name = "payments"

urlpatterns = [
    path("providers/", api_views.ProviderListAPIView.as_view(), name="providers"),
    path("create/", api_views.CreatePaymentAPIView.as_view(), name="create"),
    path("history/", api_views.PaymentHistoryAPIView.as_view(), name="history"),
    path("refund/", api_views.RefundAPIView.as_view(), name="refund"),
    path("status/<str:reference>/", api_views.PaymentStatusAPIView.as_view(), name="status"),
]
