"""One form per wizard step."""
from django import forms

from apps.common.forms import BootstrapFormMixin
from apps.common.constants import Gender, RelationshipGoal


class IdentityStepForm(BootstrapFormMixin, forms.Form):
    gender = forms.ChoiceField(choices=Gender.choices, label="I identify as")
    headline = forms.CharField(
        max_length=120, required=False, label="Headline",
        widget=forms.TextInput(attrs={"placeholder": "One line that sounds like you"}),
    )
    bio = forms.CharField(
        max_length=2000, required=False, label="About me",
        widget=forms.Textarea(attrs={"rows": 4,
                                     "placeholder": "What should someone know about you?"}),
    )
    relationship_goal = forms.ChoiceField(
        choices=RelationshipGoal.choices, label="I'm looking for", required=False
    )
    job_title = forms.CharField(max_length=120, required=False, label="Work")
    school = forms.CharField(max_length=150, required=False, label="Education")


class InterestsStepForm(BootstrapFormMixin, forms.Form):
    interests = forms.MultipleChoiceField(
        choices=(), widget=forms.CheckboxSelectMultiple, label="Choose at least three"
    )

    def __init__(self, *args, interest_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["interests"].choices = interest_choices

    def clean_interests(self):
        chosen = self.cleaned_data["interests"]
        if len(chosen) < 3:
            raise forms.ValidationError("Pick at least three interests.")
        if len(chosen) > 15:
            raise forms.ValidationError("Pick at most 15 interests.")
        return chosen


class PreferencesStepForm(BootstrapFormMixin, forms.Form):
    interested_in = forms.MultipleChoiceField(
        choices=Gender.choices, widget=forms.CheckboxSelectMultiple,
        required=False, label="Show me",
    )
    min_age = forms.IntegerField(min_value=18, max_value=99, initial=18, label="From age")
    max_age = forms.IntegerField(min_value=18, max_value=99, initial=45, label="To age")
    max_distance_km = forms.IntegerField(
        min_value=1, max_value=500, initial=100, label="Maximum distance (km)"
    )
    preferred_relationship_goals = forms.MultipleChoiceField(
        choices=RelationshipGoal.choices, widget=forms.CheckboxSelectMultiple,
        required=False, label="They should be looking for",
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("min_age") and cleaned.get("max_age"):
            if cleaned["min_age"] > cleaned["max_age"]:
                self.add_error("min_age", "Minimum age cannot exceed maximum age.")
        return cleaned


class LocationStepForm(BootstrapFormMixin, forms.Form):
    city = forms.CharField(max_length=120, required=False, label="City")
    country = forms.CharField(max_length=80, required=False, label="Country")
    latitude = forms.FloatField(required=False, widget=forms.HiddenInput)
    longitude = forms.FloatField(required=False, widget=forms.HiddenInput)
