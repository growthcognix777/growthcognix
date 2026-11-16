"""Page-level SEO scores, topic coverage and rule-based content recommendations.

Topics are counted from titles and headings of crawled pages (what the site talks about). They are
not keywords with search volume: no ranking or traffic data is used or implied.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from sqlalchemy import select

from app.models import CrawledPage, CrawlJob, KeywordTopic, ProductApplication, TargetMarket, WebsiteAudit

STOP = set("""a an and are as at be by for from has have how in is it its of on or our the their this to was we what
when where which who why will with you your us more about all new home page contact read get can not no
any one two also other than into out over per such these those very via best top welcome products product
services service solutions solution company ltd pvt limited inc llc co""".split())


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9\-]{2,}", (text or "").lower()) if w not in STOP]


def topics_from_pages(pages: list[CrawledPage], limit: int = 40) -> list[dict]:
    pages_with: dict[str, set] = defaultdict(set)
    occ, in_titles = Counter(), Counter()
    for p in pages:
        heads = [p.title or ""] + list(p.h1 or []) + list(p.h2 or [])
        seen_here = set()
        for i, h in enumerate(heads):
            t = tokens(h)
            grams = t + [f"{a} {b}" for a, b in zip(t, t[1:])]
            for g in grams:
                occ[g] += 1
                seen_here.add(g)
                if i == 0:
                    in_titles[g] += 1
        for g in seen_here:
            pages_with[g].add(p.final_url or p.url)
    ranked = sorted(pages_with, key=lambda g: (len(pages_with[g]), " " in g, occ[g]), reverse=True)
    out, used = [], set()
    for g in ranked:
        if len(pages_with[g]) < 1 or g in used:
            continue
        # prefer a bigram over its parts when it covers the same pages
        out.append({"topic": g, "pages": len(pages_with[g]), "occurrences": occ[g], "in_titles": in_titles[g],
                    "example_urls": sorted(pages_with[g])[:5]})
        used.add(g)
        if len(out) >= limit:
            break
    return out


def _mentioned(term: str, corpus: str) -> bool:
    term = term.lower().strip()
    return bool(term) and term in corpus


def run(db, job: CrawlJob, audit: WebsiteAudit) -> dict:
    pages = [p for p in db.scalars(select(CrawledPage).where(CrawledPage.crawl_job_id == job.id)).all()
             if p.status_code and p.status_code < 400 and p.content_type and "html" in p.content_type]
    topics = topics_from_pages(pages)
    for t in topics:
        db.add(KeywordTopic(tenant_id=job.tenant_id, client_id=job.client_id, audit_id=audit.id, **t))

    corpus = " ".join(" ".join([p.title or "", p.meta_description or "", " ".join(p.h1 or []), " ".join(p.h2 or []),
                                (p.text or "")[:5000]]) for p in pages).lower()
    recs: list[dict] = []

    def rec(kind, title, detail, urls=None, priority="medium"):
        recs.append({"kind": kind, "title": title, "detail": detail, "urls": (urls or [])[:10], "priority": priority,
                     "basis": "rule-based from crawled pages"})

    product_pages = [p for p in pages if p.page_type == "product"]
    if not product_pages:
        rec("product_pages", "Add dedicated product pages",
            "No crawled page looks like a product or catalogue page. One page per product, with specifications, "
            "applications and an enquiry button, helps buyers and search engines.", priority="high")
    else:
        weak = [p for p in product_pages if not p.meta_description or (p.word_count or 0) < 300 or not p.h1]
        if weak:
            rec("product_pages", "Strengthen product pages",
                f"{len(weak)} of {len(product_pages)} product pages lack a meta description, an H1 or 300+ words "
                "(specifications, applications, MOQ, certifications).", [p.url for p in weak], "high")
        no_schema = [p for p in product_pages if "Product" not in (p.structured_data or [])]
        if no_schema:
            rec("product_schema", "Add Product schema markup", "Product schema lets search engines show product details.",
                [p.url for p in no_schema], "medium")

    # Industry and geographic landing pages, from Phase 2 intelligence that is not rejected
    apps = db.scalars(select(ProductApplication).where(ProductApplication.tenant_id == job.tenant_id,
                      ProductApplication.client_id == job.client_id, ProductApplication.verification_status != "rejected")).all()
    industries = sorted({a.industry for a in apps if a.industry})
    missing_ind = [i for i in industries if not _mentioned(i, corpus)]
    if missing_ind:
        rec("industry_pages", "Create industry landing pages",
            "These industries come from the client's product applications but are not mentioned on the crawled site: "
            + ", ".join(missing_ind[:10]) + ".", priority="medium")
    markets = db.scalars(select(TargetMarket).where(TargetMarket.tenant_id == job.tenant_id,
                         TargetMarket.client_id == job.client_id, TargetMarket.verification_status != "rejected")).all()
    places = sorted({m.name for m in markets if m.scope in ("state", "district_city", "country", "export_market")})
    missing_geo = [m for m in places if not _mentioned(m, corpus)]
    if missing_geo:
        rec("geo_pages", "Create location landing pages",
            "Target markets (AI hypotheses or approved) not mentioned on the site: " + ", ".join(missing_geo[:10]) + ".")

    # Local SEO
    contact = [p for p in pages if p.page_type == "contact"]
    types = {t for p in pages for t in (p.structured_data or [])}
    phone = re.search(r"(\+?\d[\d\s\-()]{8,}\d)", corpus)
    if not contact:
        rec("local_seo", "Add a contact page", "No contact page was found. Include address, phone, map and hours.", priority="high")
    if "LocalBusiness" not in types and "Organization" not in types:
        rec("local_seo", "Add LocalBusiness / Organization schema",
            "Structured name, address and phone help local search and Google Business Profile consistency.")
    if not phone:
        rec("local_seo", "Show a phone number on the site", "No phone number was found in the crawled text.")

    # Content calendar: suggestions only, built from the gaps above (no AI needed)
    ideas = [f"{i}: how our products are used" for i in missing_ind[:4]] + \
            [f"Serving buyers in {m}" for m in missing_geo[:3]]
    covered = {t["topic"] for t in topics[:15]}
    if not ideas and covered:
        ideas = [f"Guide: {t}" for t in list(covered)[:4]]
    calendar = [{"week": i + 1, "topic": idea, "status": "suggestion"} for i, idea in enumerate(ideas[:8])]
    audit.recommendations = recs
    audit.summary = {**(audit.summary or {}), "topics": len(topics), "recommendations": len(recs),
                     "content_calendar": calendar}
    db.flush()
    return {"topics": len(topics), "recommendations": len(recs)}
