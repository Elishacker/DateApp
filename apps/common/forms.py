"""Shared form utilities.

Lives in the kernel rather than in ``accounts`` so every module can style its
forms consistently without importing another service.
"""
from django import forms


class BootstrapFormMixin:
    """Applies the shared input classes so templates need no widget markup."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                widget.attrs.setdefault("class", "form-check")
            elif isinstance(widget, forms.RadioSelect):
                widget.attrs.setdefault("class", "form-radio")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", "form-input form-textarea")
            elif isinstance(widget, forms.FileInput):
                widget.attrs.setdefault("class", "form-file")
            elif not isinstance(widget, forms.HiddenInput):
                widget.attrs.setdefault("class", "form-input")
