"""Serializers for the authentication REST surface."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.common.validators import validate_adult

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    username = serializers.CharField(max_length=30)
    password = serializers.CharField(write_only=True, min_length=10)
    first_name = serializers.CharField(max_length=60)
    date_of_birth = serializers.DateField(validators=[validate_adult])
    phone = serializers.CharField(required=False, allow_blank=True)
    accepted_terms = serializers.BooleanField()
    marketing_opt_in = serializers.BooleanField(required=False, default=False)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_username(self, value):
        value = value.strip().lower()
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("That username is taken.")
        return value

    def validate_accepted_terms(self, value):
        if not value:
            raise serializers.ValidationError("You must accept the Terms of Service.")
        return value

    def validate(self, attrs):
        validate_password(attrs["password"], User(
            email=attrs["email"], username=attrs["username"], first_name=attrs["first_name"]
        ))
        return attrs


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)


class MFACodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=11)


class MFALoginSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    code = serializers.CharField(max_length=11)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=10)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True, min_length=10)


class EmailVerificationSerializer(serializers.Serializer):
    token = serializers.CharField()


class SocialLoginSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=["google", "facebook", "apple", "x"])
    access_token = serializers.CharField()


class LoginAttemptSerializer(serializers.Serializer):
    id = serializers.CharField()
    outcome = serializers.CharField()
    ip_address = serializers.CharField(allow_null=True)
    user_agent = serializers.CharField(allow_blank=True)
    risk_score = serializers.IntegerField()
    created_at = serializers.CharField()
    was_successful = serializers.BooleanField()
