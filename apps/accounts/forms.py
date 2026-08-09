"""Forms for the server-rendered account pages."""
from django import forms

from .models import User, UserSettings


class BootstrapFormMixin:
    """Applies the shared input styling without a template filter."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-input")


class AccountDetailsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "phone", "marketing_opt_in"]
        widgets = {"phone": forms.TextInput(attrs={"placeholder": "+255712345678"})}

    def clean_username(self):
        value = self.cleaned_data["username"].strip().lower()
        if User.objects.filter(username__iexact=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("That username is taken.")
        return value

    def clean_phone(self):
        value = self.cleaned_data.get("phone") or None
        if value and User.objects.filter(phone=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("That phone number is already in use.")
        return value


class AccountSettingsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = UserSettings
        exclude = ["user", "created_at", "updated_at"]
