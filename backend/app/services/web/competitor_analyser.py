"""Turn a competitor crawl into a CompetitorSnapshot of publicly published facts, each with its URL.
Prices, promotions and certifications are copied as text exactly as published; nothing is estimated.
Competitor revenue, customers, traffic, market share and ad spend are never produced."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Competitor, CompetitorSnapshot, CrawledPage, CrawlJob
from app.services.ai.providers import ProviderError, ProviderNotConfigured, get_provider
from app.services.web.seo_analyser import topics_from_pages

PRICE = re.compile(r"(?:₹|rs\.?|inr|usd|us\$|\$|€|eur|£|gbp|aed)\s?\d[\d,]*(?:\.\d{1,2})?(?:\s?(?:/|per)\s?[a-z]{2,10})?", re.I)
PROMO = re.compile(r"\b(?:\d{1,2}\s?% off|flat \d+%|discount|sale ends|limited[- ]time offer|special offer|free shipping|buy one get one|festive offer)\b", re.I)
CERTS = re.compile(r"\b(ISO\s?\d{4,5}(?::\d{4})?|CE (?:mark(?:ed|ing)?|certified)|BIS|ISI mark|FDA(?: approved| registered)?|GMP|HACCP|NSF|UL listed|RoHS|FSSAI|ASME|API\s?\d{1,4}[A-Z]?|IATF\s?16949|ZED certified)\b")
ROLE_EMAIL = ("info", "sales", "contact", "enquiry", "enquiries", "inquiry", "support", "export", "exports",
              "marketing", "hello", "office", "admin", "business", "care", "service")
PLACES = ["Andhra Pradesh", "Assam", "Bihar", "Chhattisgarh", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
          "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Odisha", "Punjab", "Rajasthan",
          "Tamil Nadu", "Telangana", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Mumbai", "Pune", "Bengaluru",
          "Bangalore", "Chennai", "Hyderabad", "Kolkata", "Ahmedabad", "Surat", "Coimbatore", "Mysuru", "Hubballi",
          "Noida", "Gurugram", "Jaipur", "Ludhiana", "Rajkot", "Vadodara", "Nagpur", "Indore", "Kochi",
          "UAE", "Dubai", "Saudi Arabia", "Qatar", "Oman", "Kenya", "Nigeria", "South Africa", "Bangladesh", "Nepal",
          "Sri Lanka", "Singapore", "Malaysia", "Indonesia", "Vietnam", "Thailand", "Germany", "United Kingdom",
          "France", "Italy", "Netherlands", "USA", "United States", "Canada", "Australia", "Brazil", "Mexico"]
PLACE_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in PLACES) + r")\b")


def _ctx(text: str, m: re.Match, width: int = 50) -> str:
    return " ".join(text[max(0, m.start() - width): m.end() + width].split())[:200]


def extract(pages: list[CrawledPage], domain: str | None) -> dict:
    ok = [p for p in pages if p.status_code and p.status_code < 400 and p.content_type and "html" in p.content_type]
    home = next((p for p in ok if p.depth == 0), ok[0] if ok else None)
    out = {"pages": {}, "products": [], "prices": [], "certifications": [], "locations": [], "promotions": [],
           "contact": {"emails": [], "phones": [], "url": None},
           "homepage": {"url": home.final_url or home.url, "title": home.title, "h1": (home.h1 or [None])[0],
                        "description": home.meta_description} if home else {}}
    certs, places = {}, {}
    for p in ok:
        url = p.final_url or p.url
        text = p.text or ""
        prices = list(dict.fromkeys(_ctx(text, m) for m in PRICE.finditer(text)))[:10]
        promos = list(dict.fromkeys(_ctx(text, m) for m in PROMO.finditer(text)))[:5]
        out["pages"][url] = {"title": p.title, "description": p.meta_description, "h1": (p.h1 or [None])[0],
                             "hash": p.content_hash, "type": p.page_type, "status": p.status_code,
                             "prices": prices, "promotions": promos}
        if p.page_type == "product":
            out["products"].append({"name": ((p.h1 or [None])[0] or p.title or url)[:200], "url": url})
        out["prices"] += [{"text": t, "url": url} for t in prices]
        out["promotions"] += [{"text": t, "url": url} for t in promos]
        for m in CERTS.finditer(text):
            certs.setdefault(" ".join(m.group(1).split()), url)
        if p.page_type in ("contact", "about", "home"):
            for m in PLACE_RE.finditer(text):
                places.setdefault(m.group(1), url)
        if p.page_type == "contact" or not out["contact"]["url"]:
            emails = {e.lower() for e in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)}
            emails = [e for e in emails if domain and e.endswith("@" + domain) and e.split("@")[0] in ROLE_EMAIL]
            phones = list(dict.fromkeys(" ".join(x.split()) for x in re.findall(r"\+?\d[\d\s\-()]{8,}\d", text)))[:3]
            if emails or phones:
                out["contact"] = {"emails": sorted(emails)[:3], "phones": phones, "url": url}
    for p in pages:  # record 404/410 so removals can be detected
        if p.status_code in (404, 410):
            out["pages"][p.url] = {"status": p.status_code}
    out["certifications"] = [{"name": k, "url": v} for k, v in sorted(certs.items())]
    out["locations"] = [{"name": k, "url": v} for k, v in sorted(places.items())]
    out["prices"], out["promotions"] = out["prices"][:30], out["promotions"][:15]
    out["topics"] = [t["topic"] for t in topics_from_pages(ok, 30)]
    out["seo"] = {"pages": len(ok), "product_pages": len(out["products"]),
                  "with_meta_description": sum(1 for p in ok if p.meta_description),
                  "with_h1": sum(1 for p in ok if p.h1),
                  "avg_words": round(sum(p.word_count or 0 for p in ok) / len(ok)) if ok else None,
                  "schema_types": sorted({t for p in ok for t in (p.structured_data or [])})[:20],
                  "https": bool(home and (home.final_url or "").startswith("https://"))}
    return out


def positioning(text: str) -> tuple[str | None, str | None]:
    """Optional AI interpretation of how the competitor positions itself (labelled as AI)."""
    try:
        provider = get_provider("fast")
    except ProviderNotConfigured:
        return None, None
    try:
        raw = provider.generate_json(
            "Summarise how a company positions itself, using only the text given. Return JSON only.",
            'TEXT:\n' + text[:6000] + '\n\nJSON SHAPE: {"positioning": "2 sentences on who they target and what they emphasise"}')
        val = str(raw.get("positioning") or "").strip()[:1000]
        return (val or None), provider.model
    except ProviderError:
        return None, None


def run(db, job: CrawlJob, crawl_summary: dict) -> CompetitorSnapshot:
    comp = db.get(Competitor, job.competitor_id)
    pages = db.scalars(select(CrawledPage).where(CrawledPage.crawl_job_id == job.id)).all()
    data = extract(pages, comp.domain)
    promotions = data.pop("promotions")
    snap = CompetitorSnapshot(tenant_id=job.tenant_id, client_id=job.client_id, competitor_id=comp.id, crawl_job_id=job.id,
                              captured_at=datetime.now(timezone.utc), pages=data["pages"], homepage=data["homepage"],
                              products=data["products"], prices=data["prices"], certifications=data["certifications"],
                              locations=data["locations"], contact=data["contact"], topics=data["topics"],
                              seo={**data["seo"], "promotions": promotions, "limit_reached": crawl_summary.get("limit_reached", False)})
    db.add(snap)
    home_text = " ".join(filter(None, [data["homepage"].get("title"), data["homepage"].get("h1"), data["homepage"].get("description")]))
    about = next((p.text for p in pages if p.page_type in ("about", "home") and p.text), "")
    pos, _model = positioning(home_text + "\n" + (about or ""))
    if pos:
        comp.positioning = pos
    comp.last_analysed_at = snap.captured_at
    db.flush()
    return snap
