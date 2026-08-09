"""Password validators plugged into AUTH_PASSWORD_VALIDATORS."""
from django.core.exceptions import ValidationError


class BreachedPasswordValidator:
    """Rejects passwords that appear in known breach corpora.

    Fails open: if the breach API is unreachable, registration still works.
    A password checker that takes the site down is worse than no checker.
    """

    def __init__(self, min_occurrences=1):
        self.min_occurrences = min_occurrences

    def validate(self, password, user=None):
        from .services import PasswordBreachService

        breached, count = PasswordBreachService.is_breached(password)
        if breached and count >= self.min_occurrences:
            raise ValidationError(
                "This password has appeared in a public data breach "
                f"({count:,} times). Please choose a different one.",
                code="password_breached",
            )

    def get_help_text(self):
        return "Your password must not appear in any known data breach."
