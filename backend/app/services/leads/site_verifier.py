"""Visit a prospect's own website (robots-aware, SSRF-guarded) and record what it publicly says.

Everything returned is an observation with its page URL and excerpt: matched application/industry terms,
buying signals (tenders, RFQs, explicit supplier requests, expansion), capacity signals, places named and
published role contacts. Nothing is inferred here; the score uses these observations and the people who
verify the prospect decide what they mean.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.services.web.competitor_analyser import PLACE_RE, ROLE_EMAIL
from app.services.web.crawler_service import domain_of, get_crawler, load_robots, normalize, parse_html

STOP = {"and", "the", "for", "with", "from", "into", "units", "unit", "company", "companies", "industry", "industries",
        "plant", "plants", "sector", "services", "service", "other", "small", "large", "medium", "based", "type", "types"}

INTENT_STRONG = re.compile(r"\b(tenders?|e-?tender|request for (?:quotation|proposal)s?|RFQ|RFP|expression of interest|EOI|"
                           r"inviting (?:bids|quotations|tenders)|procurement notice|notice inviting tender|NIT\b|"
                           r"looking for (?:suppliers|vendors|manufacturers|distributors)|vendor enquiry|supplier enquiry)", re.I)
INTENT_TIMING = re.compile(r"\b(new (?:plant|facility|factory|unit) (?:in|at|coming)|capacity expansion|expanding (?:our )?(?:capacity|operations|plant)|"
                           r"upcoming project|under construction|greenfield project|brownfield expansion)", re.I)
CAPACITY = [
    ("certified", re.compile(r"\b(ISO\s?\d{4,5}(?::\d{4})?|IATF\s?16949|GMP|HACCP|FSSC\s?22000|NABH|NABL)\b")),
    ("workforce", re.compile(r"\b\d[\d,]{1,7}\+?\s+(?:employees|workers|staff|people|professionals)\b", re.I)),
    ("facilities", re.compile(r"\b(?:\d+|two|three|four|five|six|multiple)\s+(?:manufacturing\s+)?(?:plants|factories|units|facilities|branches|hospitals|hotels|campuses)\b", re.I)),
    ("production_capacity", re.compile(r"\b(?:production|installed|processing)\s+capacity\b", re.I)),
    ("exports", re.compile(r"\bexports?\s+to\s+(?:\d+\s+countries|[A-Z][a-z]+)", re.I)),
]
PHONE = re.compile(r"\+?\d[\d\s\-()]{8,}\d")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _ctx(text: str, start: int, end: int, width: int = 80) -> str:
    return " ".join(text[max(0, start - width): end + width].split())[:300]


def terms_from(personas: list, applications: list) -> list[dict]:
    """Phrases to look for on a prospect's site, built from buyer personas and product applications (never the
    product name). kind=fit: industries, applications, company types; kind=need: problems the product solves."""
    raw: list[tuple[str, str]] = []
    for p in personas:
        raw += [(x, "fit") for x in [p.industry or ""] + list(p.application_categories or []) + list(p.company_types or [])]
        raw += [(x, "need") for x in list(p.problems_solved or []) + list(p.pain_points or [])]
    for a in applications:
        raw += [(x, "fit") for x in [a.application or "", a.industry or ""] + list(a.businesses_needing or [])]
        raw += [(x, "need") for x in list(a.pain_points or [])]
    seen, res = set(), []
    for t, kind in raw:
        t = " ".join(str(t).split()).strip().lower()
        if 3 <= len(t) <= 80 and t not in seen:
            seen.add(t)
            res.append({"term": t, "kind": kind})
    return res[:80]


def match_term(term: str, low: str) -> re.Match | None:
    m = re.search(r"\b" + re.escape(term) + r"\b", low)
    if m:
        return m
    words = [w for w in re.findall(r"[a-z]{4,}", term) if w not in STOP]
    if len(words) >= 2 and all(re.search(r"\b" + re.escape(w[:-1] if w.endswith("s") else w) + r"s?\b", low) for w in words):
        return re.search(r"\b" + re.escape(words[0][:-1] if words[0].endswith("s") else words[0]), low)
    return None


def inspect(url: str, terms: list[dict], max_pages: int = 3, crawler=None) -> dict:
    """Return observations for a company site. Never raises for site problems; reports them in `status`."""
    now = datetime.now(timezone.utc)
    own_crawler = crawler is None
    crawler = crawler or get_crawler()
    out = {"status": None, "checked_at": now, "final_url": None, "pages": [], "title": None, "description": None,
           "site_name": None, "matched_terms": [], "intent": [], "capacity": [], "locations": [], "contacts": []}
    try:
        n = normalize(url if "://" in url else "https://" + url)
        if not n:
            out["status"] = "invalid_url"
            return out
        root = n.split("/", 3)
        root = f"{root[0]}//{root[2]}"
        rp, info = load_robots(crawler, root)
        queue, seen = [n], set()
        dom = domain_of(n)
        while queue and len(out["pages"]) < max_pages:
            u = queue.pop(0)
            if u in seen:
                continue
            seen.add(u)
            if info.get("found") and not rp.can_fetch("GrowthCognixBot", u) or getattr(rp, "disallow_all", False):
                if not out["pages"]:
                    out["status"] = "blocked_by_robots"
                    return out
                continue
            r = crawler.fetch(u)
            if not r.status or r.status >= 400 or "html" not in (r.content_type or ""):
                if not out["pages"]:
                    out["status"] = r.error or (f"http_{r.status}" if r.status else "unreachable")
                    return out
                continue
            p = parse_html(r.final_url, r.body, root)
            if not out["pages"]:
                out["final_url"], out["title"], out["description"] = r.final_url, p["title"], p["meta_description"]
                dom = domain_of(r.final_url)
                links = [x for x in p["internal_links"] if any(k in x.lower() for k in ("contact", "about", "company", "profile", "tender", "career"))]
                queue += sorted(links, key=lambda x: 0 if "contact" in x.lower() else 1 if "about" in x.lower() else 2)
            out["pages"].append({"url": r.final_url, "title": p["title"], "type": p["page_type"]})
            text, low, page = p["text"], p["text"].lower(), r.final_url
            for t in terms:
                if any(m["term"] == t["term"] for m in out["matched_terms"]):
                    continue
                m = match_term(t["term"], low)
                if m:
                    out["matched_terms"].append({"term": t["term"], "kind": t["kind"], "url": page,
                                                 "excerpt": _ctx(text, m.start(), m.end())})
            for rx, strength in ((INTENT_STRONG, "strong"), (INTENT_TIMING, "timing")):
                for m in rx.finditer(text):
                    ex = _ctx(text, m.start(), m.end())
                    if not any(i["excerpt"] == ex for i in out["intent"]):
                        out["intent"].append({"signal": m.group(1)[:80], "strength": strength, "url": page, "excerpt": ex})
                    if len(out["intent"]) >= 6:
                        break
            for kind, rx in CAPACITY:
                m = rx.search(text)
                if m and not any(c["kind"] == kind for c in out["capacity"]):
                    out["capacity"].append({"kind": kind, "value": " ".join(m.group(0).split())[:100], "url": page,
                                            "excerpt": _ctx(text, m.start(), m.end())})
            for m in PLACE_RE.finditer(text):
                if not any(x["name"] == m.group(1) for x in out["locations"]):
                    out["locations"].append({"name": m.group(1), "url": page})
            for e in {e.lower().rstrip(".") for e in EMAIL.findall(text)}:
                if dom and e.endswith("@" + dom) and e.split("@")[0] in ROLE_EMAIL and not any(c["value"] == e for c in out["contacts"]):
                    out["contacts"].append({"kind": "role_email", "value": e, "url": page})
            if p["page_type"] == "contact" or len(out["pages"]) == 1:
                for ph in list(dict.fromkeys(" ".join(x.split()) for x in PHONE.findall(text)))[:2]:
                    if not any(c["value"] == ph for c in out["contacts"]):
                        out["contacts"].append({"kind": "phone", "value": ph, "url": page})
        out["status"] = "ok"
        out["locations"] = out["locations"][:15]
        out["contacts"] = out["contacts"][:6]
        return out
    except Exception as e:  # noqa: BLE001 - a broken site must not stop the campaign
        out["status"] = f"error: {type(e).__name__}: {e}"[:200]
        return out
    finally:
        if own_crawler and getattr(crawler, "close", None):
            crawler.close()
