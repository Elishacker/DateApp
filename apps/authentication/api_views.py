"""REST endpoints for authentication (mobile clients and SPAs)."""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.mixins import ServiceResponseMixin

from .serializers import (
    EmailVerificationSerializer,
    LoginAttemptSerializer,
    LoginSerializer,
    MFACodeSerializer,
    MFALoginSerializer,
    PasswordChangeSerializer,
    PasswordResetRequestSerializer,
    PasswordResetSerializer,
    RegisterSerializer,
    SocialLoginSerializer,
)
from .services import LoginService, MFAService, PasswordService, RegistrationService, SocialAuthService

User = get_user_model()


class AuthThrottle(AnonRateThrottle):
    rate = "20/min"


class RegisterAPIView(ServiceResponseMixin, APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user, _ = RegistrationService.register(
            email=data["email"], username=data["username"], password=data["password"],
            first_name=data["first_name"], date_of_birth=data["date_of_birth"],
            phone=data.get("phone") or None, accepted_terms=data["accepted_terms"],
            marketing_opt_in=data.get("marketing_opt_in", False), request=request,
        )
        tokens = LoginService.issue_jwt(user)
        return self.ok(
            {"user_id": str(user.id), "tokens": tokens, "onboarding_required": True},
            message="Account created. Check your email to verify it.",
            status=status.HTTP_201_CREATED,
        )


class LoginAPIView(ServiceResponseMixin, APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user, requires_mfa = LoginService.authenticate(
            serializer.validated_data["identifier"],
            serializer.validated_data["password"],
            request,
        )
        if requires_mfa:
            # No tokens are issued until the second factor is satisfied.
            return self.ok(
                {"mfa_required": True, "user_id": str(user.id)},
                message="Enter your authentication code.",
            )

        LoginService.complete_login(user, request)
        return self.ok({
            "mfa_required": False,
            "tokens": LoginService.issue_jwt(user),
            "onboarding_required": not user.has_completed_onboarding,
        }, message="Signed in.")


class MFALoginAPIView(ServiceResponseMixin, APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle]

    def post(self, request):
        serializer = MFALoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.filter(id=serializer.validated_data["user_id"]).first()
        if not user:
            return self.ok({"verified": False}, message="Invalid request.",
                           status=status.HTTP_400_BAD_REQUEST)

        MFAService.verify(user, serializer.validated_data["code"])
        LoginService.complete_login(user, request, mfa_used=True)
        return self.ok({"tokens": LoginService.issue_jwt(user)}, message="Signed in.")


class LogoutAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
            except Exception:  # noqa: BLE001 - already expired/blacklisted is fine
                pass
        LoginService.logout(request.user, request)
        return self.ok(message="Signed out.")


class VerifyEmailAPIView(ServiceResponseMixin, APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = RegistrationService.verify_email(serializer.validated_data["token"])
        return self.ok({"user_id": str(user.id)}, message="Email verified.")


class ResendVerificationAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        RegistrationService.resend_verification(request.user, request)
        return self.ok(message="Verification email sent.")


class PasswordResetRequestAPIView(ServiceResponseMixin, APIView):
    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        PasswordService.request_reset(serializer.validated_data["email"], request)
        # Deliberately identical response whether or not the account exists.
        return self.ok(message="If that address has an account, a reset link is on its way.")


class PasswordResetAPIView(ServiceResponseMixin, APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        PasswordService.reset(
            serializer.validated_data["token"], serializer.validated_data["password"]
        )
        return self.ok(message="Password updated.")


class PasswordChangeAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        PasswordService.change(
            request.user,
            serializer.validated_data["current_password"],
            serializer.validated_data["password"],
        )
        return self.ok(message="Password changed.")


class MFASetupAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return self.ok(MFAService.begin_enrolment(request.user),
                       message="Scan the QR code, then confirm with a code.")


class MFAConfirmAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MFACodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        codes = MFAService.confirm_enrolment(request.user, serializer.validated_data["code"])
        return self.ok({"recovery_codes": codes},
                       message="Two-factor authentication enabled. Store these codes safely.")


class MFADisableAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        MFAService.disable(request.user, request.data.get("password", ""))
        return self.ok(message="Two-factor authentication disabled.")


class SocialLoginAPIView(ServiceResponseMixin, APIView):
    """Exchanges a provider access token for a Zynora session.

    The provider call itself lives in ``providers.py`` so each vendor can be
    swapped without touching this view.
    """

    permission_classes = [AllowAny]
    throttle_classes = [AuthThrottle]

    def post(self, request):
        serializer = SocialLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from .providers import fetch_social_profile

        profile = fetch_social_profile(
            serializer.validated_data["provider"], serializer.validated_data["access_token"]
        )
        user, created = SocialAuthService.connect_or_create(
            provider=profile["provider"], uid=profile["uid"], email=profile["email"],
            first_name=profile.get("first_name", ""), extra=profile,
        )
        LoginService.complete_login(user, request)
        return self.ok({
            "tokens": LoginService.issue_jwt(user),
            "created": created,
            "onboarding_required": not user.has_completed_onboarding,
        }, message="Signed in.")


class SessionListAPIView(ServiceResponseMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.common.registry import services

        return self.ok({
            "sessions": services.authentication.list_active_sessions(request.user.id),
            "attempts": LoginAttemptSerializer(
                services.authentication.recent_login_attempts(request.user.id), many=True
            ).data,
            "mfa": services.authentication.mfa_status(request.user.id),
        })

    def delete(self, request):
        from apps.common.registry import services

        revoked = services.authentication.revoke_all_sessions(
            request.user.id, except_session_key=request.session.session_key
        )
        return self.ok({"revoked": revoked}, message="Other sessions signed out.")
