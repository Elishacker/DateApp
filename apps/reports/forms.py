"""Forms for reporting and support."""
from django import forms

from apps.common.forms import BootstrapFormMixin

from .models import ReportReason, SupportTicket


class ReportForm(BootstrapFormMixin, forms.Form):
    reason = forms.ChoiceField(
        choices=ReportReason.choices, label="What's happening?",
        widget=forms.RadioSelect,
    )
    description = forms.CharField(
        max_length=2000, required=False, label="Tell us more (optional)",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    evidence = forms.ImageField(required=False, label="Screenshot (optional)")
    also_block = forms.BooleanField(
        required=False, initial=True, label="Also block this person",
    )


class SupportTicketForm(BootstrapFormMixin, forms.Form):
    category = forms.ChoiceField(choices=SupportTicket.Category.choices, label="Topic")
    subject = forms.CharField(max_length=140, label="Subject")
    message = forms.CharField(
        max_length=4000, label="How can we help?",
        widget=forms.Textarea(attrs={"rows": 6}),
    )
