"""Abstract base models shared by every Zynora service module.

Three rules hold platform-wide:
  * public identifiers are UUIDs, never sequential primary keys;
  * business records are soft deleted so audit trails stay intact;
  * a module's tables are owned by that module — cross-module references are
    plain UUID columns (:class:`ServiceReference`), never ForeignKeys.

The single exception is ``AUTH_USER_MODEL``: identity is the one shared kernel,
so modules may hold a FK to the user. Everything else crosses via UUID + the
service registry, which is what allows a module's tables to be moved to their
own database without touching a migration.
"""
import uuid

from django.db import models
from django.utils import timezone

from .managers import SoftDeleteManager


class UUIDModel(models.Model):
    """Primary key that is safe to expose in URLs and API payloads."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """Keeps rows physically present but hidden from the default manager."""

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False, hard=False):
        if hard:
            return super().delete(using=using, keep_parents=keep_parents)
        self.is_deleted = True
        self.deleted_at = timezone.now()
        fields = ["is_deleted", "deleted_at"]
        if hasattr(self, "updated_at"):
            fields.append("updated_at")
        self.save(update_fields=fields)
        return 1, {self._meta.label: 1}

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])


class BaseModel(UUIDModel, TimeStampedModel, SoftDeleteModel):
    """The default parent for domain models: UUID + timestamps + soft delete."""

    class Meta:
        abstract = True
        ordering = ["-created_at"]


def ServiceReference(service, verbose_name=None, null=False, blank=False, db_index=True, **kwargs):
    """A pointer to a record owned by *another* module.

    Deliberately a bare ``UUIDField`` and not a ``ForeignKey``: there is no
    database-level join, no cascade and no import of the other module's models.
    Resolve it through the registry::

        conversation.match_id  ->  services.matches.get_match(match_id)

    The owning service name is recorded in ``help_text`` so the dependency is
    visible in the schema, in migrations and in the admin.
    """
    help_text = kwargs.pop("help_text", "")
    return models.UUIDField(
        verbose_name=verbose_name or f"{service} reference",
        null=null,
        blank=blank,
        db_index=db_index,
        help_text=help_text or f"UUID of a record owned by the '{service}' service.",
        **kwargs,
    )
