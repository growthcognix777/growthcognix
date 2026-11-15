"""RQ worker entrypoint. Phase 1 has no executable job types; Phase 2 registers real tasks here.

Run: rq worker --url $REDIS_URL growthcognix
"""
from redis import Redis
from rq import Queue

from app.core.config import get_settings


def queue() -> Queue:
    return Queue("growthcognix", connection=Redis.from_url(get_settings().redis_url))
