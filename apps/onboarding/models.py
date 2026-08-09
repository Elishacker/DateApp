"""Signup wizard state.

``onboarding`` owns only *progress through the wizard*. The data each step
collects is written to the owning service (profiles, accounts) through its
contract — this module stores no profile fields of its own.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class OnboardingStep(models.IntegerChoices):
    WELCOME = 1, "Welcome"
    IDENTITY = 2, "About you"
    PHOTOS = 3, "Photos"
    INTERESTS = 4, "Interests"
    PREFERENCES = 5, "What you're looking for"
    LOCATION = 6, "Location"
    DONE = 7, "Finished"


class OnboardingProgress(TimeStampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="onboarding", primary_key=True,
    )
    current_step = models.PositiveSmallIntegerField(
        choices=OnboardingStep.choices, default=OnboardingStep.WELCOME
    )
    completed_steps = models.JSONField(default=list, blank=True)
    is_complete = models.BooleanField(default=False, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    skipped_steps = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "onboarding_progress"
        verbose_name_plural = "Onboarding progress"

    def __str__(self):
        return f"Onboarding {self.current_step}/7 for {self.user_id}"

    @property
    def total_steps(self):
        return len(OnboardingStep.choices) - 1  # DONE is a terminal marker

    @property
    def percent_complete(self):
        return int(len(set(self.completed_steps)) / self.total_steps * 100)

    def mark_step_done(self, step):
        if step not in self.completed_steps:
            self.completed_steps = [*self.completed_steps, step]
        self.current_step = min(step + 1, OnboardingStep.DONE)
        if self.current_step == OnboardingStep.DONE:
            self.is_complete = True
            self.completed_at = timezone.now()
        self.save(update_fields=["completed_steps", "current_step",
                                 "is_complete", "completed_at", "updated_at"])
        return self
