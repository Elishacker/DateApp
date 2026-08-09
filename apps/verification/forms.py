"""Forms for the verification flow."""
from django import forms

from apps.common.forms import BootstrapFormMixin
from apps.common.validators import validate_image_file, validate_phone


class SelfieForm(BootstrapFormMixin, forms.Form):
    photo = forms.ImageField(label="Upload your photo", validators=[validate_image_file])
    confirm = forms.BooleanField(
        label="This is a photo of me, taken just now", initial=False
    )


class PhoneStartForm(BootstrapFormMixin, forms.Form):
    phone = forms.CharField(
        max_length=20, label="Mobile number", validators=[validate_phone],
        widget=forms.TextInput(attrs={"placeholder": "+255712345678"}),
    )


class PhoneCodeForm(BootstrapFormMixin, forms.Form):
    code = forms.CharField(
        max_length=6, min_length=6, label="Verification code",
        widget=forms.TextInput(attrs={"inputmode": "numeric",
                                      "autocomplete": "one-time-code"}),
    )
