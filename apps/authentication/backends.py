"""Authentication backend accepting email, username or phone as the identifier."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

UserModel = get_user_model()


class EmailOrPhoneBackend(ModelBackend):
    """Members sign in with whatever identifier they remember.

    A dummy ``set_password`` runs when no user matches so the response time does
    not reveal whether an account exists (user-enumeration defence).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = (username or kwargs.get("email") or kwargs.get("identifier") or "").strip()
        if not identifier or not password:
            return None

        user = UserModel.objects.filter(
            Q(email__iexact=identifier)
            | Q(username__iexact=identifier)
            | Q(phone=identifier)
        ).first()

        if user is None:
            UserModel().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def user_can_authenticate(self, user):
        """Banned and locked accounts must not obtain a session."""
        return bool(user.is_active and not user.is_banned and not user.is_locked)
