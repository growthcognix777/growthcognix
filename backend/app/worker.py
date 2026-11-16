"""RQ worker entrypoint. Phase 2 runs Client Intelligence analyses (app.services.intelligence.pipeline.run_analysis).

Run: rq worker --url $REDIS_URL growthcognix
"""
from redis import Redis
from rq import Queue

from app.core.config import get_settings


def queue() -> Queue:
    return Queue("growthcognix", connection=Redis.from_url(get_settings().redis_url))
