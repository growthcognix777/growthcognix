"""Stage: fetch readable text from the client's website (home page + a few about/product pages).

SSRF protection: only http/https on ports 80/443, every hostname (including each redirect hop) must
resolve to public IP addresses only, response size capped, HTML/text content types only.
Known limitation: DNS can change between the check and the connection (rebinding); a production
deployment should also block private ranges at the network/egress level.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.models import WebsiteSnapshot
from app.services.intelligence.common import Context

UA = "GrowthCognixBot/1.0 (+client website analysis; contact the agency that runs this instance)"
KEYWORDS = ("about", "company", "product", "service", "solution", "industr", "application", "who-we-are",
            "profile", "capabilit", "manufactur", "export", "certif", "quality")


class UnsafeURL(ValueError):
    pass


def check_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise UnsafeURL("Only http(s) URLs are allowed")
    if u.username or u.password:
        raise UnsafeURL("URLs with credentials are not allowed")
    if u.port not in (None, 80, 443):
        raise UnsafeURL("Only ports 80 and 443 are allowed")
    if get_settings().website_allow_private:
        return url
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise UnsafeURL(f"Could not resolve {u.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise UnsafeURL(f"{u.hostname} resolves to a non-public address")
    return url


def fetch(url: str, client: httpx.Client) -> tuple[str, int, str]:
    """Return (final_url, status_code, html). Follows up to 3 redirects, checking each hop."""
    max_bytes = get_settings().website_max_bytes
    for _ in range(4):
        check_url(url)
        with client.stream("GET", url) as r:
            if r.is_redirect and "location" in r.headers:
                url = urljoin(url, r.headers["location"])
                continue
            ctype = r.headers.get("content-type", "")
            if "html" not in ctype and "text/plain" not in ctype:
                return url, r.status_code, ""
            body = b""
            for chunk in r.iter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    break
            return url, r.status_code, body.decode(r.encoding or "utf-8", errors="replace")
    raise UnsafeURL("Too many redirects")


def readable(html: str) -> tuple[str | None, str, list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(strip=True)[:300] if soup.title else None
    links = [a.get("href", "") for a in soup.find_all("a")]
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    meta = soup.find("meta", attrs={"name": "description"})
    parts = [meta["content"].strip()] if meta and meta.get("content") else []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "th"]):
        t = " ".join(el.get_text(" ", strip=True).split())
        if len(t) > 2 and t not in parts[-3:]:
            parts.append(t)
    return title, "\n".join(parts)[:60_000], links


def candidate_links(base: str, links: list[str], limit: int) -> list[str]:
    host = urlparse(base).hostname
    out: list[str] = []
    for href in links:
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base, href).split("#")[0]
        u = urlparse(full)
        if u.hostname != host or full in out or full.rstrip("/") == base.rstrip("/"):
            continue
        if any(k in u.path.lower() for k in KEYWORDS) and not u.path.lower().endswith((".pdf", ".jpg", ".png", ".zip")):
            out.append(full)
        if len(out) >= limit:
            break
    return out


def run(ctx: Context) -> dict:
    site = ctx.client.website
    if not site:
        return {"pages": 0, "note": "Client has no website on record"}
    max_pages = get_settings().website_max_pages
    fetched, errors = 0, []
    with httpx.Client(timeout=20, headers={"User-Agent": UA}, follow_redirects=False) as http:
        queue, done = [site], set()
        while queue and len(done) < max_pages:
            url = queue.pop(0)
            if url in done:
                continue
            done.add(url)
            snap = WebsiteSnapshot(tenant_id=ctx.tenant_id, client_id=ctx.client.id, analysis_job_id=ctx.job.id, url=url[:500])
            try:
                final, code, html = fetch(url, http)
                snap.status_code = code
                if code >= 400 or not html:
                    snap.error = f"HTTP {code}" if code >= 400 else "Not an HTML page"
                else:
                    snap.title, snap.text, links = readable(html)
                    fetched += 1
                    if len(done) == 1:
                        queue.extend(candidate_links(final, links, max_pages - 1))
            except (UnsafeURL, httpx.HTTPError) as e:
                snap.error = str(e)[:500]
                errors.append(snap.error)
            ctx.db.add(snap)
    ctx.db.flush()
    if fetched == 0 and errors:
        raise RuntimeError(f"Website could not be fetched: {errors[0]}")
    return {"pages": fetched, "errors": len(errors)}
