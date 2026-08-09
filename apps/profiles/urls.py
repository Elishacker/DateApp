from django.urls import path

from . import views

app_name = "profiles"

urlpatterns = [
    path("", views.MyProfileView.as_view(), name="me"),
    path("edit/", views.EditProfileView.as_view(), name="edit"),
    path("photos/", views.PhotoGalleryView.as_view(), name="photos"),
    path("photos/<uuid:pk>/delete/", views.PhotoDeleteView.as_view(), name="photo_delete"),
    path("photos/<uuid:pk>/primary/", views.PhotoPrimaryView.as_view(), name="photo_primary"),
    path("preferences/", views.PreferencesView.as_view(), name="preferences"),
    path("viewers/", views.ProfileViewersView.as_view(), name="viewers"),
    path("location/", views.LocationUpdateView.as_view(), name="location"),
    path("u/<uuid:user_id>/", views.PublicProfileView.as_view(), name="public"),
]
