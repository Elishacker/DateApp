from django.urls import path

from . import views

app_name = "subscriptions"

urlpatterns = [
    path("", views.PlansView.as_view(), name="plans"),
    path("mine/", views.MySubscriptionView.as_view(), name="mine"),
    path("checkout/<slug:plan_code>/", views.CheckoutView.as_view(), name="checkout"),
    path("coupon/", views.ApplyCouponView.as_view(), name="coupon"),
    path("cancel/", views.CancelSubscriptionView.as_view(), name="cancel"),
    path("boost/", views.UseBoostView.as_view(), name="boost"),
]
