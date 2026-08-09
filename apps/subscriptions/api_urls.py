"""Subscriptions REST routes, mounted at /api/v1/subscriptions/."""
from django.urls import path

from . import api_views

app_name = "subscriptions"

urlpatterns = [
    path("plans/", api_views.PlanListAPIView.as_view(), name="plans"),
    path("me/", api_views.MySubscriptionAPIView.as_view(), name="mine"),
    path("start/", api_views.StartSubscriptionAPIView.as_view(), name="start"),
    path("entitlements/", api_views.EntitlementAPIView.as_view(), name="entitlements"),
    path("coupon/quote/", api_views.CouponQuoteAPIView.as_view(), name="coupon_quote"),
    path("boost/", api_views.BoostAPIView.as_view(), name="boost"),
]
