"""Firecrawl adapter: works with a self-hosted Firecrawl (free, AGPL) or Firecrawl cloud (paid beyond
its small free allowance). Configure FIRECRAWL_API_URL (+ FIRECRAWL_API_KEY for cloud) and set
CRAWLER_PROVIDER=firecrawl. robots.txt is still checked by GrowthCognix before any URL is sent, and
the target URL still passes the SSRF guard (Firecrawl itself fetches the page).
"""
from __future__ import annotations

import time

import httpx

from app.core.config import get_settings
from app.services.intelligence.website_analyser import UnsafeURL, check_url
from app.services.web.opencrawl_adapter import FetchResult


class FirecrawlNotConfigured(RuntimeError):
    pass


def make_client() -> httpx.Client:
    s = get_settings()
    headers = {"Authorization": f"Bearer {s.firecrawl_api_key}"} if s.firecrawl_api_key else {}
    return httpx.Client(timeout=max(30, s.crawl_timeout_seconds * 3), headers=headers)


class FirecrawlCrawler:
    name = "firecrawl"

    def __init__(self, client: httpx.Client | None = None):
        s = get_settings()
        if not s.firecrawl_api_url:
            raise FirecrawlNotConfigured("CRAWLER_PROVIDER=firecrawl but FIRECRAWL_API_URL is not set")
        self.base = s.firecrawl_api_url.rstrip("/")
        self.client = client or make_client()

    def close(self) -> None:
        self.client.close()

    def fetch(self, url: str, max_redirects: int = 5) -> FetchResult:
        res = FetchResult(url=url, final_url=url)
        start = time.monotonic()
        try:
            check_url(url)
            r = self.client.post(f"{self.base}/v1/scrape", json={"url": url, "formats": ["rawHtml"], "onlyMainContent": False})
            if r.status_code == 402:
                res.error = "Firecrawl credits exhausted (cloud plan limit)"
            elif r.status_code == 429:
                res.error, res.retryable = "Firecrawl rate limit", True
            elif r.status_code >= 400:
                res.error, res.retryable = f"Firecrawl error HTTP {r.status_code}", r.status_code >= 500
            else:
                data = (r.json() or {}).get("data") or {}
                meta = data.get("metadata") or {}
                res.status = meta.get("statusCode") or 200
                res.final_url = meta.get("url") or meta.get("sourceURL") or url
                res.content_type = "text/html"
                res.body = (data.get("rawHtml") or data.get("html") or "")[: get_settings().crawl_max_bytes]
                if res.final_url != url:
                    res.redirect_chain = [{"url": url, "status": None}]
        except UnsafeURL as e:
            res.error = f"Blocked by SSRF protection: {e}"
        except (httpx.HTTPError, ValueError) as e:
            res.error, res.retryable = f"Firecrawl request failed: {type(e).__name__}", True
        res.ms = int((time.monotonic() - start) * 1000)
        return res
