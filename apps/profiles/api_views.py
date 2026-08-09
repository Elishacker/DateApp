"""REST endpoints owned by the profiles service."""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.mixins import ServiceResponseMixin
from apps.common.registry import services
from apps.common.utils import haversine_km

from .models import Interest, ProfilePhoto
from .serializers import (
    InterestSerializer,
    LocationSerializer,
    MatchPreferenceSerializer,
    PhotoReorderSerializer,
    PhotoUploadSerializer,
    ProfilePhotoSerializer,
    ProfileSerializer,
)
from .services import PhotoService, PreferenceService, ProfileService


class MyProfileView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = ProfileService.get_or_create(request.user)
        return self.ok(ProfileSerializer(profile).data)

    def patch(self, request):
        serializer = ProfileSerializer(
            ProfileService.get_or_create(request.user), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        fields = dict(serializer.validated_data)
        interests = fields.pop("interest_ids", None)
        if interests is not None:
            fields["interests"] = interests

        profile = ProfileService.update(request.user, **fields)
        return self.ok(ProfileSerializer(profile).data, message="Profile updated.")


class PublicProfileView(ServiceResponseMixin, APIView):
    """Another member's profile, assembled from several services."""

    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        if services.reports.is_blocked_between(str(request.user.id), str(user_id)):
            return self.ok(message="Profile unavailable.", status=status.HTTP_404_NOT_FOUND)

        card = services.profiles.get_public_card(user_id, viewer_id=request.user.id)
        if not card:
            return self.ok(message="Profile not found.", status=status.HTTP_404_NOT_FOUND)

        user_ref = services.accounts.get_user_ref(user_id)
        viewer_location = services.profiles.get_location(request.user.id)
        target_location = services.profiles.get_location(user_id)

        distance = None
        if viewer_location and target_location:
            distance = haversine_km(
                viewer_location["latitude"], viewer_location["longitude"],
                target_location["latitude"], target_location["longitude"],
            )

        services.profiles.record_view(request.user.id, user_id, source="profile")

        return self.ok({
            "user": user_ref,
            "profile": card,
            "distance_km": distance,
            "compatibility": services.matching.score_pair(request.user.id, user_id),
            "is_match": services.matches.are_matched(request.user.id, user_id),
            "has_liked": services.likes.has_liked(request.user.id, user_id),
        })


class PhotoViewSet(ServiceResponseMixin, viewsets.ModelViewSet):
    serializer_class = ProfilePhotoSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        return ProfilePhoto.objects.filter(user=self.request.user).order_by("position")

    def create(self, request, *args, **kwargs):
        serializer = PhotoUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        photo = PhotoService.upload(
            request.user,
            serializer.validated_data["image"],
            serializer.validated_data.get("caption", ""),
            serializer.validated_data.get("make_primary", False),
        )
        return self.ok(ProfilePhotoSerializer(photo).data,
                       message="Photo uploaded and queued for review.",
                       status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        PhotoService.delete(request.user, kwargs["pk"])
        return self.ok(message="Photo removed.")

    @action(detail=True, methods=["post"])
    def primary(self, request, pk=None):
        photo = PhotoService.set_primary(request.user, pk)
        return self.ok(ProfilePhotoSerializer(photo).data, message="Primary photo updated.")

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        serializer = PhotoReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        PhotoService.reorder(request.user, serializer.validated_data["order"])
        return self.ok(message="Gallery reordered.")


class PreferenceView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        preference = PreferenceService.get_or_create(request.user)
        return self.ok(MatchPreferenceSerializer(preference).data)

    def patch(self, request):
        preference = PreferenceService.get_or_create(request.user)
        serializer = MatchPreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        # Hard filters are a premium entitlement.
        gated = {"verified_only", "show_me_globally"}
        requested = gated & set(serializer.validated_data)
        if requested and not services.subscriptions.has_entitlement(
            request.user.id, "advanced_filters"
        ):
            return self.ok(
                {"locked_fields": sorted(requested)},
                message="Advanced filters are a premium feature.",
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        preference = PreferenceService.update(request.user, **serializer.validated_data)
        return self.ok(MatchPreferenceSerializer(preference).data, message="Preferences saved.")


class LocationView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = ProfileService.update_location(request.user, **serializer.validated_data)
        return self.ok({
            "city": profile.city, "country": profile.country,
            "latitude": float(profile.latitude), "longitude": float(profile.longitude),
        }, message="Location updated.")


class InterestListView(ServiceResponseMixin, APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        qs = Interest.objects.filter(is_active=True)
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        return self.ok(InterestSerializer(qs, many=True).data)


class ProfileViewersView(ServiceResponseMixin, APIView):
    """'Who viewed me' — gated behind a premium entitlement."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not services.subscriptions.has_entitlement(request.user.id, "see_profile_viewers"):
            count = services.profiles.count_views(request.user.id)
            return Response({
                "success": True,
                "data": {"count": count, "viewers": [], "locked": True},
                "message": f"{count} people viewed you. Upgrade to see who.",
            }, status=status.HTTP_200_OK)

        viewer_ids = services.profiles.get_viewer_ids(request.user.id)
        refs = services.accounts.get_user_refs(viewer_ids)
        return self.ok({
            "count": len(viewer_ids),
            "viewers": [refs[v] for v in viewer_ids if v in refs],
            "locked": False,
        })
