"""Server-rendered profile editor and public profile page."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import FormView, TemplateView, View

from apps.common.exceptions import ZynoraError
from apps.common.registry import services
from apps.common.utils import haversine_km

from .forms import (
    PhotoUploadForm,
    PreferenceForm,
    ProfileBasicsForm,
    ProfileInterestsForm,
    ProfileLifestyleForm,
    ProfileLocationForm,
    ProfileWorkForm,
)
from .models import ProfilePhoto
from .services import PhotoService, PreferenceService, ProfileService


class MyProfileView(LoginRequiredMixin, TemplateView):
    template_name = "profiles/my_profile.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = ProfileService.get_or_create(self.request.user)
        context["profile"] = profile
        context["photos"] = ProfilePhoto.objects.filter(user=self.request.user).order_by("position")
        context["completion"] = profile.completion_score
        context["missing"] = self._missing_items(profile)
        return context

    @staticmethod
    def _missing_items(profile):
        checks = [
            ("Add a photo", profile.photo_count >= 1),
            ("Add three photos", profile.photo_count >= 3),
            ("Write a bio", len(profile.bio) >= 60),
            ("Add a headline", bool(profile.headline)),
            ("Set your location", profile.has_location),
            ("Pick three interests", profile.interests.count() >= 3),
            ("Add your work or school", bool(profile.job_title or profile.school)),
            ("Say what you're looking for", bool(profile.relationship_goal)),
        ]
        return [label for label, done in checks if not done]


class EditProfileView(LoginRequiredMixin, TemplateView):
    """Single page hosting the four profile sections as separate forms."""

    template_name = "profiles/edit.html"

    FORMS = {
        "basics": ProfileBasicsForm,
        "work": ProfileWorkForm,
        "lifestyle": ProfileLifestyleForm,
        "location": ProfileLocationForm,
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = ProfileService.get_or_create(self.request.user)
        context["profile"] = profile
        for name, form_class in self.FORMS.items():
            context.setdefault(f"{name}_form", form_class(instance=profile))
        context.setdefault(
            "interests_form",
            ProfileInterestsForm(initial={"interests": profile.interests.all()}),
        )
        return context

    def post(self, request, *args, **kwargs):
        profile = ProfileService.get_or_create(request.user)
        section = request.POST.get("section", "basics")

        if section == "interests":
            form = ProfileInterestsForm(request.POST)
            if form.is_valid():
                ProfileService.update(
                    request.user, interests=[str(i.id) for i in form.cleaned_data["interests"]]
                )
                messages.success(request, "Interests updated.")
                return redirect("profiles:edit")
            return self.render_to_response(self.get_context_data(interests_form=form))

        form_class = self.FORMS.get(section)
        if not form_class:
            raise Http404
        form = form_class(request.POST, instance=profile)
        if form.is_valid():
            ProfileService.update(request.user, **form.cleaned_data)
            messages.success(request, "Profile updated.")
            return redirect("profiles:edit")
        return self.render_to_response(self.get_context_data(**{f"{section}_form": form}))


class PhotoGalleryView(LoginRequiredMixin, FormView):
    template_name = "profiles/photos.html"
    form_class = PhotoUploadForm
    success_url = reverse_lazy("profiles:photos")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["photos"] = ProfilePhoto.objects.filter(user=self.request.user).order_by("position")
        context["max_photos"] = 9
        return context

    def form_valid(self, form):
        try:
            PhotoService.upload(
                self.request.user,
                form.cleaned_data["image"],
                form.cleaned_data.get("caption", ""),
                form.cleaned_data.get("make_primary", False),
            )
            messages.success(self.request, "Photo uploaded. It will appear once reviewed.")
        except ZynoraError as exc:
            messages.error(self.request, exc.message)
        return super().form_valid(form)


class PhotoDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        try:
            PhotoService.delete(request.user, pk)
            messages.success(request, "Photo removed.")
        except ZynoraError as exc:
            messages.error(request, exc.message)
        return redirect("profiles:photos")


class PhotoPrimaryView(LoginRequiredMixin, View):
    def post(self, request, pk):
        try:
            PhotoService.set_primary(request.user, pk)
            messages.success(request, "Main photo updated.")
        except ZynoraError as exc:
            messages.error(request, exc.message)
        return redirect("profiles:photos")


class PreferencesView(LoginRequiredMixin, FormView):
    template_name = "profiles/preferences.html"
    form_class = PreferenceForm
    success_url = reverse_lazy("profiles:preferences")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = PreferenceService.get_or_create(self.request.user)
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["has_advanced_filters"] = services.subscriptions.has_entitlement(
            self.request.user.id, "advanced_filters"
        )
        return context

    def form_valid(self, form):
        PreferenceService.update(self.request.user, **form.cleaned_data)
        messages.success(self.request, "Your preferences were saved.")
        return super().form_valid(form)


class PublicProfileView(LoginRequiredMixin, TemplateView):
    template_name = "profiles/public.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_id = str(self.kwargs["user_id"])
        viewer_id = str(self.request.user.id)

        if services.reports.is_blocked_between(viewer_id, user_id):
            raise Http404

        card = services.profiles.get_public_card(user_id, viewer_id=viewer_id)
        if not card:
            raise Http404

        here = services.profiles.get_location(viewer_id)
        there = services.profiles.get_location(user_id)
        distance = None
        if here and there:
            distance = haversine_km(
                here["latitude"], here["longitude"], there["latitude"], there["longitude"]
            )

        services.profiles.record_view(viewer_id, user_id, source="profile")

        context.update({
            "person": services.accounts.get_user_ref(user_id),
            "card": card,
            "distance_km": distance,
            "compatibility": services.matching.score_pair(viewer_id, user_id),
            "is_match": services.matches.are_matched(viewer_id, user_id),
            "has_liked": services.likes.has_liked(viewer_id, user_id),
            "received": services.likes.count_admirers_by_kind(user_id),
        })
        return context


class ProfileViewersView(LoginRequiredMixin, TemplateView):
    template_name = "profiles/viewers.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        unlocked = services.subscriptions.has_entitlement(
            self.request.user.id, "see_profile_viewers"
        )
        context["unlocked"] = unlocked
        context["count"] = services.profiles.count_views(self.request.user.id)
        if unlocked:
            ids = services.profiles.get_viewer_ids(self.request.user.id)
            refs = services.accounts.get_user_refs(ids)
            context["viewers"] = [refs[i] for i in ids if i in refs]
        return context


class LocationUpdateView(LoginRequiredMixin, View):
    """Browser geolocation posts here."""

    def post(self, request):
        try:
            profile = ProfileService.update_location(
                request.user,
                latitude=request.POST.get("latitude"),
                longitude=request.POST.get("longitude"),
                city=request.POST.get("city", ""),
                country=request.POST.get("country", ""),
            )
        except (TypeError, ValueError):
            return JsonResponse({"success": False, "error": "Invalid coordinates."}, status=400)
        return JsonResponse({"success": True, "city": profile.city, "country": profile.country})
