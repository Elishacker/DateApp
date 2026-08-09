"""Forms for the server-rendered authentication flow."""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from apps.common.forms import BootstrapFormMixin
from apps.common.validators import validate_adult

User = get_user_model()


class RegisterForm(BootstrapFormMixin, forms.Form):
    first_name = forms.CharField(max_length=60, label="First name")
    email = forms.EmailField(label="Email address")
    username = forms.CharField(max_length=30, label="Username")
    date_of_birth = forms.DateField(
        label="Date of birth",
        widget=forms.DateInput(attrs={"type": "date"}),
        validators=[validate_adult],
        help_text="You must be 18 or older.",
    )
    password = forms.CharField(widget=forms.PasswordInput, label="Password")
    password_confirm = forms.CharField(widget=forms.PasswordInput, label="Confirm password")
    accepted_terms = forms.BooleanField(label="I agree to the Terms and Privacy Policy")
    marketing_opt_in = forms.BooleanField(
        required=False, label="Send me tips and offers"
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data["username"].strip().lower()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("That username is taken.")
        return username

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        confirm = cleaned.get("password_confirm")
        if password and confirm and password != confirm:
            self.add_error("password_confirm", "The two passwords do not match.")
        if password:
            temp = User(
                email=cleaned.get("email", ""),
                username=cleaned.get("username", ""),
                first_name=cleaned.get("first_name", ""),
            )
            try:
                validate_password(password, temp)
            except forms.ValidationError as exc:
                self.add_error("password", exc)
        return cleaned


class LoginForm(BootstrapFormMixin, forms.Form):
    identifier = forms.CharField(label="Email, username or phone")
    password = forms.CharField(widget=forms.PasswordInput, label="Password")
    remember_me = forms.BooleanField(required=False, initial=True, label="Keep me signed in")


class MFAChallengeForm(BootstrapFormMixin, forms.Form):
    code = forms.CharField(
        max_length=11, label="Authentication code",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code",
                                      "placeholder": "123456"}),
        help_text="Enter the 6-digit code from your app, or a recovery code.",
    )


class MFAEnrolForm(BootstrapFormMixin, forms.Form):
    code = forms.CharField(max_length=6, label="Verification code")


class PasswordResetRequestForm(BootstrapFormMixin, forms.Form):
    email = forms.EmailField(label="Email address")


class PasswordResetForm(BootstrapFormMixin, forms.Form):
    password = forms.CharField(widget=forms.PasswordInput, label="New password")
    password_confirm = forms.CharField(widget=forms.PasswordInput, label="Confirm new password")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("password_confirm"):
            self.add_error("password_confirm", "The two passwords do not match.")
        return cleaned


class PasswordChangeForm(BootstrapFormMixin, forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput, label="Current password")
    password = forms.CharField(widget=forms.PasswordInput, label="New password")
    password_confirm = forms.CharField(widget=forms.PasswordInput, label="Confirm new password")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("password") != cleaned.get("password_confirm"):
            self.add_error("password_confirm", "The two passwords do not match.")
        return cleaned
