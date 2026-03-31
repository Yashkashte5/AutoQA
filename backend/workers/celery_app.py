from celery import Celery
from backend.core.config import settings

celery = Celery(
    "autoqa",
    broker=settings.rabbitmq_url,
    backend=settings.redis_url,
    include=["backend.workers.tasks"],
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)
