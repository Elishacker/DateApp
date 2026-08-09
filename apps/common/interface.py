"""Base class for every module's public interface.

A module's ``interface.py`` is its API contract. Everything else inside the
module — models, managers, forms, consumers — is private and must not be
imported from outside.

Contract rules (enforced by ``manage.py check_boundaries``):
  1. Interface methods accept and return primitives, UUIDs and plain dicts.
     Never an ORM instance, queryset or Django object.
  2. Interface methods must be safe to serialise over the wire.
  3. Interfaces never import another module's models.
"""
from dataclasses import dataclass


class ModuleInterface:
    """Marker base class. Subclasses expose only wire-safe methods."""

    #: Module name as registered in :class:`~apps.common.registry.ServiceRegistry`.
    name = ""
    #: Modules this one is allowed to call synchronously. Kept explicit so the
    #: dependency graph stays acyclic and reviewable.
    depends_on = ()

    def describe(self):
        return {
            "name": self.name,
            "depends_on": list(self.depends_on),
            "methods": sorted(
                m for m in dir(self)
                if not m.startswith("_") and callable(getattr(self, m))
                and m not in {"describe"}
            ),
        }


@dataclass(frozen=True)
class UserRef:
    """The minimal cross-module representation of a person.

    Modules exchange this instead of a ``User`` instance so no module needs the
    accounts tables to render a name and a face.
    """

    id: str
    username: str
    display_name: str
    avatar_url: str = ""
    age: int | None = None
    is_verified: bool = False
    is_online: bool = False

    def to_dict(self):
        return {
            "id": str(self.id),
            "username": self.username,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "age": self.age,
            "is_verified": self.is_verified,
            "is_online": self.is_online,
        }
