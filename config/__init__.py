"""Project configuration package.

Importing the Celery app here guarantees ``@shared_task`` decorators bind to the
configured application whenever Django starts.
"""
from .celery import app as celery_app

__all__ = ("celery_app",)
