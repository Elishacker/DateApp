"""Onboarding REST routes, mounted at /api/v1/onboarding/."""
from django.urls import path

from . import api_views

app_name = "onboarding"

urlpatterns = [
    path("", api_views.OnboardingStateView.as_view(), name="state"),
    path("skip/", api_views.OnboardingSkipView.as_view(), name="skip"),
    path("step/<str:key>/", api_views.OnboardingStepView.as_view(), name="step"),
]
