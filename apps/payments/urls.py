from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("", views.CheckoutView.as_view(), name="checkout"),
    path("start/", views.StartPaymentView.as_view(), name="start"),
    path("pending/<str:reference>/", views.PendingPaymentView.as_view(), name="pending"),
    path("status/<str:reference>/", views.PaymentStatusView.as_view(), name="status"),
    path("history/", views.PaymentHistoryView.as_view(), name="history"),
    path("success/", views.PaymentSuccessView.as_view(), name="success"),
    path("cancel/", views.PaymentCancelView.as_view(), name="cancel"),
    path("webhook/<str:provider>/", views.WebhookView.as_view(), name="webhook"),
]
