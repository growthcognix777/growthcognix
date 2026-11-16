"""Native, self-hosted crawler adapter (the spec's "OpenCrawl" adapter).

Plain httpx, no third-party service, no cost. Every request (and every redirect hop) passes the SSRF
guard; only HTML/XML/text responses are read, and bodies are capped. It never sends credentials or
cookies, never solves captchas and never retries a 401/403/429 to get around access controls.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings
from app.services.intelligence.website_analyser import UnsafeURL, check_url

UA = "GrowthCognixBot/1.0 (+authorised website audit; respects robots.txt)"
READABLE = ("text/html", "application/xhtml", "application/xml", "text/xml", "text/plain")


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int | None = None
    content_type: str | None = None
    body: str = ""
    redirect_chain: list[dict] = field(default_factory=list)  # [{"url", "status"}] hops before final_url
    ms: int | None = None
    error: str | None = None
    retryable: bool = False


def make_client() -> httpx.Client:
    """Factory (patched in tests with a MockTransport)."""
    return httpx.Client(timeout=get_settings().crawl_timeout_seconds, headers={"User-Agent": UA},
                        follow_redirects=False)


class NativeCrawler:
    name = "native"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or make_client()

    def close(self) -> None:
        self.client.close()

    def fetch(self, url: str, max_redirects: int = 5) -> FetchResult:
        s = get_settings()
        res = FetchResult(url=url, final_url=url)
        start = time.monotonic()
        current = url
        try:
            for _ in range(max_redirects + 1):
                check_url(current)  # every hop: scheme, port, credentials, public DNS only
                with self.client.stream("GET", current) as r:
                    if r.is_redirect and "location" in r.headers:
                        res.redirect_chain.append({"url": current, "status": r.status_code})
                        current = urljoin(current, r.headers["location"]).split("#")[0]
                        continue
                    res.final_url, res.status = current, r.status_code
                    res.content_type = (r.headers.get("content-type") or "").split(";")[0].strip().lower()[:120]
                    if r.status_code >= 500:
                        res.retryable = True
                    if r.status_code < 400 and any(res.content_type.startswith(t) for t in READABLE):
                        body = b""
                        for chunk in r.iter_bytes():
                            body += chunk
                            if len(body) > s.crawl_max_bytes:
                                res.error = f"Response larger than {s.crawl_max_bytes} bytes; truncated"
                                break
                        res.body = body.decode(r.encoding or "utf-8", errors="replace")
                    break
            else:
                res.error = f"More than {max_redirects} redirects"
        except UnsafeURL as e:
            res.error = f"Blocked by SSRF protection: {e}"
        except httpx.TimeoutException:
            res.error, res.retryable = "Timed out", True
        except httpx.HTTPError as e:
            res.error, res.retryable = f"{type(e).__name__}: {e}"[:300], True
        res.ms = int((time.monotonic() - start) * 1000)
        return res
