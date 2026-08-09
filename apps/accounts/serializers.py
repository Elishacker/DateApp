"""DRF serializers for the accounts service."""
from rest_framework import serializers

from .models import Device, User, UserSettings


class UserRefSerializer(serializers.Serializer):
    """Matches :class:`apps.common.interface.UserRef` — the public shape of a person."""

    id = serializers.CharField()
    username = serializers.CharField()
    display_name = serializers.CharField()
    avatar_url = serializers.CharField(allow_blank=True)
    age = serializers.IntegerField(allow_null=True)
    is_verified = serializers.BooleanField()
    is_online = serializers.BooleanField()


class UserSerializer(serializers.ModelSerializer):
    age = serializers.IntegerField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    is_verified = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "email", "phone", "username", "first_name", "last_name",
            "full_name", "date_of_birth", "age", "avatar_url", "role", "status",
            "is_email_verified", "is_phone_verified", "is_photo_verified",
            "is_identity_verified", "verification_level", "is_verified",
            "is_mfa_enabled", "has_completed_onboarding", "onboarding_step",
            "is_online", "last_active_at", "date_joined", "marketing_opt_in",
        ]
        read_only_fields = [
            "id", "email", "role", "status", "is_email_verified", "is_phone_verified",
            "is_photo_verified", "is_identity_verified", "verification_level",
            "is_mfa_enabled", "has_completed_onboarding", "onboarding_step",
            "is_online", "last_active_at", "date_joined", "avatar_url",
        ]


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "phone", "marketing_opt_in"]

    def validate_username(self, value):
        value = value.strip().lower()
        qs = User.objects.filter(username__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("That username is taken.")
        return value

    def validate_phone(self, value):
        if not value:
            return None
        qs = User.objects.filter(phone=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("That phone number is already in use.")
        return value


class DeviceSerializer(serializers.ModelSerializer):
    is_revoked = serializers.BooleanField(read_only=True)

    class Meta:
        model = Device
        fields = [
            "id", "name", "platform", "ip_address", "location", "is_trusted",
            "is_revoked", "last_seen_at", "created_at",
        ]
        read_only_fields = fields


class UserSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSettings
        exclude = ["user", "created_at", "updated_at"]


class DeactivateSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Incorrect password.")
        return value
