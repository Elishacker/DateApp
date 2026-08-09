"""Forms for the server-rendered profile editor."""
from django import forms

from apps.common.forms import BootstrapFormMixin

from .models import Interest, MatchPreference, Profile


class ProfileBasicsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["headline", "bio", "gender", "pronouns", "height_cm", "relationship_goal"]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 5, "placeholder":
                                         "What should someone know about you?"}),
            "headline": forms.TextInput(attrs={"placeholder": "A line that sounds like you"}),
        }


class ProfileWorkForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["job_title", "company", "education_level", "school"]


class ProfileLifestyleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["smoking", "drinking", "exercise", "children", "religion"]


class ProfileInterestsForm(BootstrapFormMixin, forms.Form):
    interests = forms.ModelMultipleChoiceField(
        queryset=Interest.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Pick up to 15",
    )

    def clean_interests(self):
        chosen = self.cleaned_data["interests"]
        if len(chosen) > 15:
            raise forms.ValidationError("Choose up to 15 interests.")
        return chosen


class ProfileLocationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["city", "region", "country", "latitude", "longitude"]
        widgets = {
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),
        }


class PhotoUploadForm(BootstrapFormMixin, forms.Form):
    image = forms.ImageField(label="Choose a photo")
    caption = forms.CharField(max_length=140, required=False)
    make_primary = forms.BooleanField(required=False, label="Use as my main photo")


class PreferenceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = MatchPreference
        exclude = ["user", "created_at", "updated_at"]
        widgets = {
            "min_age": forms.NumberInput(attrs={"min": 18, "max": 99}),
            "max_age": forms.NumberInput(attrs={"min": 18, "max": 99}),
            "max_distance_km": forms.NumberInput(attrs={"min": 1, "max": 500}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("min_age") and cleaned.get("max_age"):
            if cleaned["min_age"] > cleaned["max_age"]:
                self.add_error("min_age", "Minimum age cannot exceed maximum age.")
        return cleaned
