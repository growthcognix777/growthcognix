"""Social content studio: Instagram, Facebook, LinkedIn, YouTube and YouTube Shorts drafts.
Thin wrapper over content_generator so each studio keeps its own entry point."""
from app.services.marketing.content_generator import LIMITS, SOCIAL_KINDS, SOCIAL_PLATFORMS, generate  # noqa: F401


def generate_social(db, tenant_id, client, user_id, **kw):
    return generate(db, tenant_id, client, user_id, studio="social", **kw)
