"""Common crawler: one interface over the native adapter and Firecrawl.

Behaviour
  * robots.txt is fetched first and obeyed for every URL (GrowthCognixBot, then *); its Crawl-delay
    raises our delay, never lowers it. Disallowed URLs are recorded as blocked, not fetched.
  * Limits: max_pages (hard ceiling CRAWL_MAX_PAGES_LIMIT), max_depth, timeout, include/exclude
    path patterns, same-host only, HTML-like content only.
  * Rate limiting: at most `concurrency` requests per `delay_seconds` window on the domain.
  * Resumable: the frontier is saved after each batch; a retried job skips URLs already stored.
  * Failed pages (timeouts, 5xx) are retried up to `retries` times within the crawl.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.core.config import get_settings
from app.models import CrawledPage, CrawlJob, Website
from app.services.web.opencrawl_adapter import FetchResult, NativeCrawler

SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".rar", ".gz", ".mp4", ".mp3",
            ".avi", ".mov", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".exe", ".dmg", ".css", ".js",
            ".ico", ".woff", ".woff2", ".ttf", ".xml", ".json")
PAGE_TYPES = [("contact", ("contact", "reach-us", "enquiry", "inquiry")), ("about", ("about", "company", "who-we-are", "profile")),
              ("product", ("product", "shop", "catalog", "catalogue", "item", "machine", "equipment")),
              ("service", ("service", "solution")), ("blog", ("blog", "news", "article", "insight", "post"))]
_sleep = time.sleep  # patched in tests


class CrawlConfig(BaseModel):
    max_pages: int = Field(default_factory=lambda: get_settings().crawl_default_max_pages, ge=1)
    max_depth: int = Field(default_factory=lambda: get_settings().crawl_default_max_depth, ge=0, le=10)
    delay_seconds: float = Field(default_factory=lambda: get_settings().crawl_default_delay_seconds, ge=0, le=60)
    concurrency: int = Field(default=2, ge=1, le=4)
    retries: int = Field(default=1, ge=0, le=3)
    include: list[str] = Field(default_factory=list, max_length=20)  # path globs, e.g. /products/*
    exclude: list[str] = Field(default_factory=list, max_length=20)
    use_sitemap: bool = True

    @field_validator("max_pages")
    @classmethod
    def _cap(cls, v: int) -> int:
        return min(v, get_settings().crawl_max_pages_limit)

    @field_validator("include", "exclude")
    @classmethod
    def _patterns(cls, v: list[str]) -> list[str]:
        return [p.strip()[:200] for p in v if p.strip()]


def get_crawler():
    s = get_settings()
    if s.crawler_provider == "firecrawl":
        from app.services.web.firecrawl_adapter import FirecrawlCrawler
        return FirecrawlCrawler()
    return NativeCrawler()


# ------------------------------------------------------------------ URL helpers
def _host(h: str | None) -> str:
    h = (h or "").lower()
    return h[4:] if h.startswith("www.") else h


def normalize(url: str) -> str | None:
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    netloc = u.hostname.lower() + (f":{u.port}" if u.port and u.port not in (80, 443) else "")
    path = re.sub(r"/{2,}", "/", u.path or "/")
    return urlunparse((u.scheme.lower(), netloc, path, "", u.query[:300], ""))


def same_site(url: str, root: str) -> bool:
    return _host(urlparse(url).hostname) == _host(urlparse(root).hostname)


def allowed_by_patterns(url: str, cfg: CrawlConfig) -> bool:
    path = urlparse(url).path or "/"
    if cfg.include and not any(fnmatch.fnmatch(path, p) for p in cfg.include):
        return path == "/"  # the start page is always allowed so links can be discovered
    return not any(fnmatch.fnmatch(path, p) for p in cfg.exclude)


def crawlable(url: str) -> bool:
    return not urlparse(url).path.lower().endswith(SKIP_EXT)


def domain_of(url: str) -> str:
    return _host(urlparse(url).hostname)


# ------------------------------------------------------------------ parsing
def _schema_types(soup: BeautifulSoup) -> list[str]:
    types: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            t = node.get("@type")
            for x in (t if isinstance(t, list) else [t]):
                if isinstance(x, str):
                    types.add(x[:60])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            walk(json.loads(tag.string or ""))
        except (json.JSONDecodeError, TypeError):
            types.add("invalid-json-ld")
    for el in soup.find_all(attrs={"itemtype": True}):
        types.add(str(el["itemtype"]).rstrip("/").rsplit("/", 1)[-1][:60])
    return sorted(types)


def page_type(url: str, title: str | None) -> str:
    path = urlparse(url).path.lower()
    if path in ("", "/", "/index.html", "/index.php", "/home"):
        return "home"
    hay = path + " " + (title or "").lower()
    for t, words in PAGE_TYPES:
        if any(w in hay for w in words):
            return t
    return "other"


def parse_html(url: str, html: str, root: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    meta = lambda **a: soup.find("meta", attrs=a)  # noqa: E731
    desc = meta(name=re.compile("^description$", re.I))
    robots = meta(name=re.compile("^robots$", re.I))
    canon = soup.find("link", rel=lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else [v])])
    html_tag = soup.find("html")
    imgs = soup.find_all("img")
    internal, external = [], 0
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        n = normalize(urljoin(url, href))
        if not n:
            continue
        if same_site(n, root):
            if n not in internal:
                internal.append(n)
        else:
            external += 1
    schema = _schema_types(soup)
    title = soup.title.get_text(" ", strip=True)[:500] if soup.title else None
    h1 = [" ".join(h.get_text(" ", strip=True).split())[:300] for h in soup.find_all("h1")][:10]
    h2 = [" ".join(h.get_text(" ", strip=True).split())[:300] for h in soup.find_all("h2")][:30]
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "template"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return {
        "title": title or None,
        "meta_description": (desc.get("content") or "").strip()[:1000] if desc else None,
        "h1": [x for x in h1 if x], "h2": [x for x in h2 if x],
        "canonical": normalize(urljoin(url, canon["href"])) if canon and canon.get("href") else None,
        "robots_meta": (robots.get("content") or "").strip().lower()[:200] if robots else None,
        "lang": (html_tag.get("lang") or "")[:20] or None if html_tag else None,
        "has_viewport": bool(meta(name=re.compile("^viewport$", re.I))),
        "structured_data": schema,
        "word_count": len(text.split()),
        "text": text[:20_000],
        "content_hash": hashlib.sha256(text.encode()).hexdigest() if text else None,
        "internal_links": internal[:500],
        "external_links_count": external,
        "images_total": len(imgs),
        "images_missing_alt": sum(1 for i in imgs if not i.has_attr("alt")),
        "page_type": page_type(url, title),
    }


# ------------------------------------------------------------------ robots + sitemap
def load_robots(crawler, root: str) -> tuple[RobotFileParser, dict]:
    rp = RobotFileParser()
    robots_url = urljoin(root, "/robots.txt")
    r = crawler.fetch(robots_url)
    info = {"url": robots_url, "found": False, "status": r.status, "sitemaps": [], "crawl_delay": None}
    if r.status and r.status < 400 and r.body:
        rp.parse(r.body.splitlines())
        info["found"] = True
        info["sitemaps"] = (rp.site_maps() or [])[:10]
        cd = rp.crawl_delay("GrowthCognixBot") or rp.crawl_delay("*")
        info["crawl_delay"] = float(cd) if cd else None
    elif r.status in (401, 403) or r.status is None or r.status >= 500:
        # Access-restricted or unreachable robots.txt: be conservative and do not crawl.
        rp.disallow_all = True
        info["note"] = f"robots.txt {'returned ' + str(r.status) if r.status else 'unreachable'}; treated as disallow all"
    else:
        rp.allow_all = True  # 404 or missing: allowed
    return rp, info


def sitemap_urls(crawler, sitemaps: list[str], root: str, limit: int) -> tuple[list[str], bool]:
    """Return (page urls, whether a sitemap was found). Follows one level of sitemap indexes."""
    candidates = sitemaps or [urljoin(root, "/sitemap.xml")]
    found, urls, seen = False, [], set()
    queue = list(candidates)[:10]
    while queue and len(urls) < limit and len(seen) < 15:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        r = crawler.fetch(sm)
        if not r.status or r.status >= 400 or "<" not in (r.body or ""):
            continue
        found = True
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.body, re.I)
        if "<sitemapindex" in r.body.lower():
            queue.extend(locs[:10])
            continue
        for loc in locs:
            n = normalize(loc)
            if n and same_site(n, root) and n not in urls:
                urls.append(n)
            if len(urls) >= limit:
                break
    return urls, found


# ------------------------------------------------------------------ crawl loop
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _store(db, job: CrawlJob, url: str, depth: int, r: FetchResult | None, root: str, *, blocked=False,
           retries=0) -> CrawledPage:
    page = db.scalar(select(CrawledPage).where(CrawledPage.crawl_job_id == job.id, CrawledPage.url == url))
    if page is None:
        page = CrawledPage(tenant_id=job.tenant_id, client_id=job.client_id, website_id=job.website_id,
                           crawl_job_id=job.id, url=url[:1000], depth=depth, discovered_at=_now())
        db.add(page)
    page.retries, page.blocked_by_robots = retries, blocked
    if blocked:
        page.error = "Disallowed by robots.txt (not fetched)"
        return page
    page.fetched_at = _now()
    page.final_url, page.status_code, page.content_type = r.final_url[:1000], r.status, r.content_type
    page.redirect_chain, page.response_ms, page.error = r.redirect_chain, r.ms, r.error
    if r.body and r.content_type and "html" in r.content_type:
        for k, v in parse_html(r.final_url, r.body, root).items():
            setattr(page, k, v)
    return page


def run_crawl(db, job: CrawlJob, crawler=None, on_progress=None) -> dict:
    site = db.get(Website, job.website_id)
    cfg = CrawlConfig.model_validate(job.config or {})
    root = normalize(site.url) or site.url
    own = crawler is None
    crawler = crawler or get_crawler()
    job.provider = crawler.name
    try:
        rp, info = load_robots(crawler, root)
        job.robots = info
        delay = max(cfg.delay_seconds, info.get("crawl_delay") or 0)
        done_urls = set(db.scalars(select(CrawledPage.url).where(CrawledPage.crawl_job_id == job.id)).all())
        frontier: list[list] = [list(x) for x in (job.frontier or [])]
        if not frontier and not done_urls:  # fresh crawl
            frontier = [[root, 0, 0]]
            if cfg.use_sitemap:
                sm, found = sitemap_urls(crawler, info.get("sitemaps", []), root, cfg.max_pages)
                info["sitemap_found"], info["sitemap_urls"] = found, len(sm)
                frontier += [[u, 1, 0] for u in sm if u != root and crawlable(u) and allowed_by_patterns(u, cfg)]
        queued = {f[0] for f in frontier} | done_urls
        db.commit()

        while frontier and len(done_urls) < cfg.max_pages:
            db.refresh(job)
            if job.status == "cancelled":
                break
            batch: list[list] = []
            while frontier and len(batch) < cfg.concurrency and len(done_urls) + len(batch) < cfg.max_pages:
                url, depth, tries = frontier.pop(0)
                if url in done_urls:
                    continue
                if not rp.can_fetch("GrowthCognixBot", url):
                    _store(db, job, url, depth, None, root, blocked=True)
                    done_urls.add(url)
                    job.pages_blocked += 1
                    continue
                batch.append([url, depth, tries])
            if not batch:
                continue
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                results = list(pool.map(lambda b: crawler.fetch(b[0]), batch))
            for (url, depth, tries), r in zip(batch, results):
                if r.retryable and tries < cfg.retries:
                    frontier.append([url, depth, tries + 1])  # retry later in this crawl
                    continue
                page = _store(db, job, url, depth, r, root, retries=tries)
                done_urls.add(url)
                if r.error or (r.status or 0) >= 400 or r.status is None:
                    job.pages_failed += 1
                else:
                    job.pages_crawled += 1
                if depth < cfg.max_depth and page.internal_links:
                    for link in page.internal_links:
                        if link not in queued and crawlable(link) and allowed_by_patterns(link, cfg):
                            queued.add(link)
                            frontier.append([link, depth + 1, 0])
            job.pages_discovered = len(queued)
            job.frontier = frontier[:5000]
            job.progress = min(95, int(len(done_urls) / max(1, min(cfg.max_pages, len(queued))) * 90))
            db.commit()
            if on_progress:
                on_progress(job)
            if frontier and delay:
                _sleep(delay)
        job.frontier = frontier[:5000] if job.status == "cancelled" else []
        site.last_crawled_at = _now()
        db.commit()
        return {"pages_crawled": job.pages_crawled, "pages_failed": job.pages_failed, "pages_blocked": job.pages_blocked,
                "pages_discovered": job.pages_discovered, "robots_found": info["found"], "delay_seconds": delay,
                "limit_reached": len(done_urls) >= cfg.max_pages and bool(frontier)}
    finally:
        if own:
            crawler.close()
