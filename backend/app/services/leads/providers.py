"""Discovery provider adapters.

Each adapter has its own configuration, daily usage limit, failure handling and source attribution. Keys
come only from the server environment. A provider returns *candidates*: appearing in a search result or a
directory is a discovery signal, never evidence that a company is a buyer.

Implemented: SearXNG (self-hosted, free), Brave Search API (metered; $5 monthly credit), Google Programmable
Search (~100 free queries/day), Directory pages (a trade-association / industrial-estate member list a user
supplies; fetched by the robots-aware crawler). Sources listed in NOT_AUTOMATED are deliberately not
scraped (terms of service, no public API, paid bulk data, or retired) and are used as manual signals.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select

from app.core.config import get_settings

# Listing, marketplace, social and data-aggregator sites: a result here is not a company website.
LISTING_DOMAINS = (
    "indiamart.com", "tradeindia.com", "justdial.com", "exportersindia.com", "alibaba.com", "made-in-china.com",
    "amazon.", "flipkart.com", "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "wikipedia.org", "quora.com", "reddit.com", "medium.com", "pinterest.", "glassdoor.", "naukri.com", "indeed.",
    "zaubacorp.com", "tofler.in", "crunchbase.com", "dnb.com", "google.", "bing.com", "yelp.", "yellowpages",
    "kompass.com", "europages.", "thomasnet.com", "blogspot.com", "wordpress.com", "wix.com", "sulekha.com",
    "magicbricks.com", "99acres.com", "tripadvisor.", "booking.com", "maps.app.goo.gl", "goo.gl", "bit.ly",
)


def is_listing_site(domain: str | None) -> bool:
    d = (domain or "").lower()
    return any(d == x or d.endswith("." + x) or (x.endswith(".") and (d.startswith(x) or ("." + x) in d)) for x in LISTING_DOMAINS)


@dataclass
class Hit:
    title: str
    url: str
    snippet: str = ""
    provider: str = ""
    source_url: str | None = None  # where we saw it (directory page) or the search endpoint label
    rank: int = 0
    extra: dict = field(default_factory=dict)


class ProviderFailure(RuntimeError):
    def __init__(self, msg: str, retryable: bool = True):
        super().__init__(msg)
        self.retryable = retryable


def http_client() -> httpx.Client:
    """Factory for provider API calls (patched in tests). Provider endpoints are admin-configured, not user input."""
    return httpx.Client(timeout=get_settings().discovery_provider_timeout,
                        headers={"User-Agent": "GrowthCognixBot/1.0 (+B2B buyer research)"})


def _get_json(url: str, params: dict, headers: dict | None = None) -> dict:
    try:
        with http_client() as c:
            r = c.get(url, params=params, headers=headers or {})
    except httpx.TimeoutException as e:
        raise ProviderFailure("Timed out") from e
    except httpx.HTTPError as e:
        raise ProviderFailure(f"{type(e).__name__}: {e}"[:300]) from e
    if r.status_code == 429:
        raise ProviderFailure("Rate limited by the provider (429)")
    if r.status_code in (401, 403):
        raise ProviderFailure(f"Provider refused the key ({r.status_code})", retryable=False)
    if r.status_code >= 500:
        raise ProviderFailure(f"Provider error {r.status_code}")
    if r.status_code != 200:
        raise ProviderFailure(f"Provider returned {r.status_code}: {r.text[:200]}", retryable=False)
    try:
        return r.json()
    except ValueError as e:
        raise ProviderFailure("Provider did not return JSON", retryable=False) from e


class SearXNG:
    key, label, kind = "searxng", "SearXNG (self-hosted)", "search"
    cost = "Free (self-hosted). Aggregates public search engines; respect their usage limits."

    def configured(self) -> bool:
        return bool(get_settings().searxng_url)

    def daily_limit(self) -> int:
        return get_settings().discovery_daily_limit_searxng

    def search(self, query: str, limit: int, region: str | None = None) -> list[Hit]:
        base = get_settings().searxng_url.rstrip("/")
        data = _get_json(base + "/search", {"q": query, "format": "json", "pageno": 1})
        return [Hit(title=(x.get("title") or "")[:300], url=x.get("url") or "", snippet=(x.get("content") or "")[:600],
                    provider=self.key, source_url=None, rank=i + 1)
                for i, x in enumerate(data.get("results") or []) if x.get("url")][:limit]


class Brave:
    key, label, kind = "brave", "Brave Search API", "search"
    cost = "Metered: $5 per 1,000 requests with a $5 monthly credit (about 1,000 queries); a card is required. No free plan since Feb 2026."

    def configured(self) -> bool:
        return bool(get_settings().brave_api_key)

    def daily_limit(self) -> int:
        return get_settings().discovery_daily_limit_brave

    def search(self, query: str, limit: int, region: str | None = None) -> list[Hit]:
        params = {"q": query, "count": min(limit, 20)}
        if region:
            params["country"] = region.lower()
        data = _get_json("https://api.search.brave.com/res/v1/web/search", params,
                         {"X-Subscription-Token": get_settings().brave_api_key, "Accept": "application/json"})
        rows = ((data.get("web") or {}).get("results")) or []
        return [Hit(title=(x.get("title") or "")[:300], url=x.get("url") or "", snippet=(x.get("description") or "")[:600],
                    provider=self.key, rank=i + 1) for i, x in enumerate(rows) if x.get("url")][:limit]


class GooglePSE:
    key, label, kind = "google_pse", "Google Programmable Search", "search"
    cost = "About 100 free queries/day; then paid per 1,000 queries."

    def configured(self) -> bool:
        s = get_settings()
        return bool(s.google_pse_key and s.google_pse_cx)

    def daily_limit(self) -> int:
        return get_settings().discovery_daily_limit_google_pse

    def search(self, query: str, limit: int, region: str | None = None) -> list[Hit]:
        s = get_settings()
        params = {"key": s.google_pse_key, "cx": s.google_pse_cx, "q": query, "num": min(limit, 10)}
        if region:
            params["gl"] = region.lower()
        data = _get_json("https://www.googleapis.com/customsearch/v1", params)
        return [Hit(title=(x.get("title") or "")[:300], url=x.get("link") or "", snippet=(x.get("snippet") or "")[:600],
                    provider=self.key, rank=i + 1) for i, x in enumerate(data.get("items") or []) if x.get("link")][:limit]


class Directory:
    """A public member/exhibitor/estate list a user supplies. Fetched with the robots-aware crawler; outbound links
    to company websites become candidates, attributed to the directory page."""
    key, label, kind = "directory", "Directory / association list (URL you provide)", "directory"
    cost = "Free. Only pages robots.txt allows; confirm the directory's terms permit this use."

    def configured(self) -> bool:
        return True

    def daily_limit(self) -> int:
        return get_settings().discovery_daily_limit_directory

    def fetch(self, url: str, limit: int) -> list[Hit]:
        from app.services.web.crawler_service import domain_of, get_crawler, load_robots
        crawler = get_crawler()
        try:
            root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            rp, info = load_robots(crawler, root)
            if info.get("found") and not rp.can_fetch("GrowthCognixBot", url):
                raise ProviderFailure("robots.txt disallows this directory page", retryable=False)
            r = crawler.fetch(url)
        finally:
            close = getattr(crawler, "close", None)
            if close:
                close()
        if r.error and not r.body:
            raise ProviderFailure(r.error, retryable=r.retryable)
        if not r.status or r.status >= 400:
            raise ProviderFailure(f"Directory page returned {r.status}", retryable=bool(r.status and r.status >= 500))
        own = domain_of(r.final_url)
        soup = BeautifulSoup(r.body, "html.parser")
        hits, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = urljoin(r.final_url, a["href"]).split("#")[0]
            if not href.startswith(("http://", "https://")):
                continue
            d = domain_of(href)
            if not d or d == own or d in seen:
                continue
            seen.add(d)
            name = " ".join(a.get_text(" ").split())[:300] or d
            parent = a.find_parent(["li", "tr", "div", "p"])
            snippet = " ".join(parent.get_text(" ").split())[:600] if parent else ""
            hits.append(Hit(title=name, url=href, snippet=snippet, provider=self.key, source_url=r.final_url, rank=len(hits) + 1))
            if len(hits) >= limit:
                break
        return hits


SEARCH_PROVIDERS = {p.key: p for p in (SearXNG(), Brave(), GooglePSE())}
ALL = {**SEARCH_PROVIDERS, "directory": Directory()}

NOT_AUTOMATED = [
    {"key": "bing", "label": "Bing Search API", "status": "retired", "note": "Microsoft retired the Bing Search APIs in August 2025."},
    {"key": "indiamart", "label": "IndiaMART / TradeIndia", "status": "manual_only",
     "note": "Terms restrict automated scraping. Use listings as manual supplier-market signals; listing sites are never treated as company websites."},
    {"key": "gem", "label": "GeM (Government e-Marketplace)", "status": "manual_only",
     "note": "No open API for bids. Add a public bid/tender URL to a prospect as intent evidence."},
    {"key": "mca", "label": "MCA company master data", "status": "manual_only",
     "note": "Portal lookups are manual and bulk data is paid. Record the CIN/registered name with the MCA page as evidence."},
    {"key": "data_gov_in", "label": "data.gov.in datasets", "status": "not_implemented",
     "note": "Free API key; dataset coverage varies by state. Planned as an import adapter."},
    {"key": "itc_trade_map", "label": "ITC Trade Map", "status": "manual_only",
     "note": "Free account, no public API. Enter figures as market insights with the Trade Map URL."},
    {"key": "authorised_provider", "label": "Authorised business-data providers", "status": "not_configured",
     "note": "Paid providers (e.g. licensed company databases) can be added as adapters once licensed."},
]


def used_today(db, tenant_id: str, provider: str) -> int:
    from app.models import DiscoveryTarget
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count()).select_from(DiscoveryTarget).where(
        DiscoveryTarget.tenant_id == tenant_id, DiscoveryTarget.provider == provider,
        DiscoveryTarget.executed_at.is_not(None), DiscoveryTarget.executed_at >= start)) or 0


def status(db, tenant_id: str) -> list[dict]:
    out = []
    for p in ALL.values():
        out.append({"key": p.key, "label": p.label, "kind": p.kind, "configured": p.configured(), "daily_limit": p.daily_limit(),
                    "used_today": used_today(db, tenant_id, p.key), "cost": p.cost, "status": "available" if p.configured() else "not_configured"})
    s = get_settings()
    out.append({"key": "site_verification", "label": f"Company website verification ({s.crawler_provider} crawler)", "kind": "verification",
                "configured": True, "daily_limit": None, "used_today": None, "status": "available",
                "cost": "Free with the native crawler; Firecrawl if CRAWLER_PROVIDER=firecrawl."})
    out.append({"key": "un_comtrade", "label": "UN Comtrade (trade statistics)", "kind": "market_data", "configured": True,
                "daily_limit": 500 if s.comtrade_api_key else None, "used_today": None, "status": "available",
                "cost": "Free public preview: no key, 500 rows per call, about 1 request/second."})
    return out + [{**x, "kind": "manual", "configured": False, "daily_limit": None, "used_today": None, "cost": None} for x in NOT_AUTOMATED]


def call_with_retry(fn, retries: int = 2, backoff: float = 1.0):
    """Retry retryable provider failures with backoff; non-retryable ones (bad key, 4xx) raise at once."""
    attempt = 0
    while True:
        try:
            return fn(), attempt
        except ProviderFailure as e:
            if not e.retryable or attempt >= retries:
                raise
            attempt += 1
            _sleep(backoff * attempt)


def _sleep(s: float) -> None:  # patched in tests
    time.sleep(s)
