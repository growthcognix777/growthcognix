"""Technical audit from crawled pages. Every finding is a crawler observation (measured=False) with the
page URL it was seen on; PageSpeed findings come from pagespeed_service and are measured=True.
No ranking, traffic or keyword-volume claims are made here."""
from __future__ import annotations

from collections import Counter, defaultdict
from urllib.parse import urlparse

from sqlalchemy import select

from app.models import CrawledPage, CrawlJob, SEOFinding, Website, WebsiteAudit

PENALTY = {"high": 15, "medium": 8, "low": 3, "info": 0}
SITE_PENALTY = {"high": 10, "medium": 5, "low": 2, "info": 0}


def _ok(p: CrawledPage) -> bool:
    return bool(p.status_code and p.status_code < 400 and not p.error and not p.blocked_by_robots)


def _html(p: CrawledPage) -> bool:
    return _ok(p) and bool(p.content_type and "html" in p.content_type)


class Collector:
    def __init__(self, audit: WebsiteAudit):
        self.audit, self.rows, self.page_pen = audit, [], defaultdict(int)
        self.site_pen = 0

    def add(self, check, category, severity, message, url=None, value=None, source="crawler", measured=False):
        self.rows.append(SEOFinding(tenant_id=self.audit.tenant_id, client_id=self.audit.client_id, audit_id=self.audit.id,
                                    page_url=(url or None) and url[:1000], check=check, category=category,
                                    severity=severity, message=message[:2000],
                                    observed_value=None if value is None else str(value)[:2000],
                                    source=source, measured=measured))
        if url and source == "crawler":
            self.page_pen[url] += PENALTY[severity]
        else:
            self.site_pen += SITE_PENALTY[severity]


def run(db, job: CrawlJob, audit: WebsiteAudit) -> dict:
    site = db.get(Website, job.website_id)
    pages = db.scalars(select(CrawledPage).where(CrawledPage.crawl_job_id == job.id)).all()
    html = [p for p in pages if _html(p)]
    by_url = {p.url: p for p in pages}
    by_final = {p.final_url: p for p in pages if p.final_url}
    c = Collector(audit)
    robots = job.robots or {}

    # ---- security / availability
    root = pages[0] if pages else None
    home = next((p for p in pages if p.depth == 0), root)
    if urlparse(site.url).scheme != "https" or (home and home.final_url and not home.final_url.startswith("https://")):
        c.add("https", "security", "high", "The site is not served over HTTPS.", home.url if home else site.url)
    if home and not _ok(home):
        c.add("homepage_unavailable", "availability", "high", "The home page did not load.", home.url,
              home.error or f"HTTP {home.status_code}")
    http_pages = [p for p in html if p.final_url and p.final_url.startswith("http://")]
    if http_pages and urlparse(site.url).scheme == "https":
        for p in http_pages[:20]:
            c.add("http_page", "security", "medium", "Page is served over plain HTTP.", p.url)
    slow = [p for p in html if (p.response_ms or 0) > 3000]
    for p in slow[:20]:
        c.add("slow_response", "performance", "low", "The server took over 3 seconds to respond to the crawler "
              "(crawler observation, not a Core Web Vitals measurement).", p.url, f"{p.response_ms} ms")

    # ---- indexing
    if not robots.get("found"):
        c.add("robots_missing", "indexing", "low", "No robots.txt file was found.", value=robots.get("status"))
    if robots.get("sitemap_found") is False or (not robots.get("sitemaps") and not robots.get("sitemap_found")):
        c.add("sitemap_missing", "indexing", "medium", "No XML sitemap was found (robots.txt or /sitemap.xml).")
    for p in html:
        if p.robots_meta and "noindex" in p.robots_meta:
            c.add("noindex", "indexing", "medium" if p.page_type in ("home", "product", "service") else "info",
                  "Page asks search engines not to index it.", p.url, p.robots_meta)
        if not p.canonical:
            c.add("canonical_missing", "indexing", "low", "No canonical link.", p.url)
        elif p.canonical.rstrip("/") != (p.final_url or p.url).rstrip("/"):
            c.add("canonical_other", "indexing", "info", "Canonical points to a different URL.", p.url, p.canonical)
    for p in pages:
        if p.blocked_by_robots:
            c.add("blocked_by_robots", "indexing", "info", "Disallowed by robots.txt, so it was not crawled.", p.url)

    # ---- metadata
    titles, descs = Counter(), Counter()
    for p in html:
        if not p.title:
            c.add("title_missing", "metadata", "high", "Page has no title.", p.url)
        else:
            titles[p.title.strip().lower()] += 1
            if len(p.title) > 60:
                c.add("title_long", "metadata", "low", "Title is longer than 60 characters and may be cut off.", p.url, len(p.title))
            elif len(p.title) < 10:
                c.add("title_short", "metadata", "low", "Title is shorter than 10 characters.", p.url, p.title)
        if not p.meta_description:
            c.add("meta_description_missing", "metadata", "medium", "No meta description.", p.url)
        else:
            descs[p.meta_description.strip().lower()] += 1
            if len(p.meta_description) > 160:
                c.add("meta_description_long", "metadata", "low", "Meta description is over 160 characters.", p.url, len(p.meta_description))
            elif len(p.meta_description) < 50:
                c.add("meta_description_short", "metadata", "low", "Meta description is under 50 characters.", p.url, len(p.meta_description))
    for p in html:
        if p.title and titles[p.title.strip().lower()] > 1:
            c.add("title_duplicate", "metadata", "medium", "Title is shared with other pages.", p.url, p.title)
        if p.meta_description and descs[p.meta_description.strip().lower()] > 1:
            c.add("meta_description_duplicate", "metadata", "low", "Meta description is shared with other pages.", p.url)

    # ---- content
    hashes = Counter(p.content_hash for p in html if p.content_hash)
    for p in html:
        if not p.h1:
            c.add("h1_missing", "content", "medium", "No H1 heading.", p.url)
        elif len(p.h1) > 1:
            c.add("h1_multiple", "content", "low", "More than one H1 heading.", p.url, " | ".join(p.h1[:5]))
        if not p.h2 and (p.word_count or 0) > 300:
            c.add("h2_missing", "content", "info", "Long page with no H2 subheadings.", p.url)
        if (p.word_count or 0) < 200 and p.page_type not in ("contact",):
            c.add("thin_content", "content", "low", "Less than 200 words of text.", p.url, p.word_count)
        if p.content_hash and hashes[p.content_hash] > 1:
            c.add("duplicate_content", "content", "medium", "Page text is identical to another page.", p.url)

    # ---- links
    inbound = Counter()
    for p in html:
        for link in p.internal_links or []:
            inbound[link] += 1
            t = by_url.get(link) or by_final.get(link)
            if t and t.status_code and t.status_code >= 400:
                c.add("broken_link", "links", "high", f"Links to a page that returns HTTP {t.status_code}.", p.url, link)
            elif t and t.redirect_chain:
                c.add("link_to_redirect", "links", "low", "Links to a URL that redirects.", p.url, link)
    for p in pages:
        if p.status_code and p.status_code >= 400:
            c.add("page_error", "availability", "high" if p.status_code < 500 else "medium",
                  f"Page returns HTTP {p.status_code}.", p.url, p.status_code)
        if len(p.redirect_chain or []) > 1:
            chain = " → ".join([h["url"] for h in p.redirect_chain] + [p.final_url or ""])
            c.add("redirect_chain", "links", "medium", f"Redirect chain of {len(p.redirect_chain)} hops.", p.url, chain)
    for p in html:
        if p.depth > 0 and inbound[p.url] == 0 and inbound[p.final_url or ""] == 0:
            c.add("orphan_page", "links", "low", "No crawled page links here (found only via the sitemap).", p.url)

    # ---- media / mobile / accessibility / structured data
    for p in html:
        if p.images_missing_alt:
            c.add("img_alt_missing", "media", "medium" if p.images_missing_alt > 3 else "low",
                  f"{p.images_missing_alt} of {p.images_total} images have no alt attribute.", p.url, p.images_missing_alt)
        if p.has_viewport is False:
            c.add("viewport_missing", "mobile", "high", "No mobile viewport meta tag (page may not be mobile-friendly).", p.url)
        if not p.lang:
            c.add("lang_missing", "accessibility", "low", "The html element has no lang attribute.", p.url)
        if "invalid-json-ld" in (p.structured_data or []):
            c.add("schema_invalid", "structured_data", "medium", "A JSON-LD block could not be parsed.", p.url)
        if p.page_type == "product" and not {"Product", "Offer", "Service"} & set(p.structured_data or []):
            c.add("product_schema_missing", "structured_data", "low", "Product page has no Product schema markup.", p.url)
    all_types = {t for p in html for t in (p.structured_data or [])}
    if html and not all_types - {"invalid-json-ld"}:
        c.add("schema_missing", "structured_data", "low", "No schema.org structured data found on any crawled page.")
    elif html and not {"Organization", "LocalBusiness", "Corporation"} & all_types:
        c.add("org_schema_missing", "structured_data", "low", "No Organization or LocalBusiness schema found.")

    # ---- scores (crawler-observed health, not search performance)
    page_scores = {p.url: max(0, 100 - c.page_pen[p.url]) for p in html}
    health = None
    if page_scores:
        health = max(0, min(100, round(sum(page_scores.values()) / len(page_scores) - c.site_pen)))
    db.add_all(c.rows)
    sev = Counter(r.severity for r in c.rows)
    cat = Counter(r.category for r in c.rows)
    audit.health_score, audit.page_scores = health, page_scores
    audit.summary = {"pages_audited": len(html), "pages_total": len(pages), "findings": len(c.rows),
                     "by_severity": dict(sev), "by_category": dict(cat),
                     "https": not any(r.check == "https" for r in c.rows), "robots_found": bool(robots.get("found")),
                     "sitemap_found": bool(robots.get("sitemap_found")),
                     "broken_links": sum(1 for r in c.rows if r.check == "broken_link"),
                     "redirect_chains": sum(1 for r in c.rows if r.check == "redirect_chain"),
                     "duplicate_titles": sum(1 for r in c.rows if r.check == "title_duplicate"),
                     "missing_meta": sum(1 for r in c.rows if r.check == "meta_description_missing"),
                     "score_basis": "Crawler-observed technical health (0-100). Not a ranking or traffic metric."}
    db.flush()
    return {"findings": len(c.rows), "health_score": health}
