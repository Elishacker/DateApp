from django.urls import path

from . import views

app_name = "onboarding"

urlpatterns = [
    path("", views.WizardView.as_view(), name="wizard"),
    path("skip/", views.SkipStepView.as_view(), name="skip"),
    path("back/", views.BackStepView.as_view(), name="back"),
]
