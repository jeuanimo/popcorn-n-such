# Make the Celery app available as soon as Django starts so that shared_task
# decorators and @app.autodiscover_tasks() both work correctly.
from .celery import app as celery_app

__all__ = ("celery_app",)
