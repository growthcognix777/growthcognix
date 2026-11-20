"""SEO content studio: keyword clusters, topic maps, outlines, articles, product/industry/location pages,
meta tags, FAQs and internal links. Keyword clusters carry no search volumes (none is measured here)."""
from app.services.marketing.content_generator import SEO_KINDS, generate  # noqa: F401


def generate_seo(db, tenant_id, client, user_id, **kw):
    return generate(db, tenant_id, client, user_id, studio="seo", platform="website", **kw)
