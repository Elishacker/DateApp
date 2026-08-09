from django.urls import path

from . import views

app_name = "common"

urlpatterns = [
    path("", views.LandingView.as_view(), name="landing"),
    path("about/", views.AboutView.as_view(), name="about"),
    path("safety/", views.SafetyView.as_view(), name="safety"),
    path("terms/", views.TermsView.as_view(), name="terms"),
    path("privacy/", views.PrivacyView.as_view(), name="privacy"),
    path("health/", views.HealthView.as_view(), name="health"),
    path("offline/", views.OfflineView.as_view(), name="offline"),
    path("sw.js", views.ServiceWorkerView.as_view(), name="service_worker"),
]
