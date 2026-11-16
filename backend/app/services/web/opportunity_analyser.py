"""Opportunities for the client, from comparing its crawled site with competitor snapshots and the
Phase 2 intelligence. Rule-based: every opportunity cites the pages it rests on. Nothing about
competitor revenue, customers, traffic, market share or ad spend is ever stated.

Opportunities are recommendations (is_inferred=True). They start as needs_review; approval marks them
approved to act on, never "verified"."""
from __future__ import annotations

import hashlib
from collections import defaultdict

from sqlalchemy import select

from app.models import (Client, Competitor, CompetitorSnapshot, CrawledPage, CrawlJob, EvidenceSource, Opportunity,
                        ProductApplication, TargetMarket, Website, WebsiteAudit)
from app.services.web.competitor_analyser import CERTS, PRICE
from app.services.web.seo_analyser import topics_from_pages

KINDS = ("missing_product_info", "industry_page", "geographic_page", "content_gap", "differentiation",
         "conversion", "underserved_segment", "new_application")


def latest_client_audit(db, tenant_id: str, client_id: str) -> tuple[WebsiteAudit | None, list[CrawledPage]]:
    audit = db.scalar(select(WebsiteAudit).where(WebsiteAudit.tenant_id == tenant_id, WebsiteAudit.client_id == client_id)
                      .order_by(WebsiteAudit.created_at.desc()).limit(1))
    if not audit:
        return None, []
    pages = db.scalars(select(CrawledPage).where(CrawledPage.crawl_job_id == audit.crawl_job_id)).all()
    return audit, [p for p in pages if p.status_code and p.status_code < 400 and p.content_type and "html" in p.content_type]


def latest_snapshots(db, tenant_id: str, client_id: str) -> list[tuple[Competitor, CompetitorSnapshot]]:
    out = []
    for c in db.scalars(select(Competitor).where(Competitor.tenant_id == tenant_id, Competitor.client_id == client_id,
                                                 Competitor.status == "active")).all():
        s = db.scalar(select(CompetitorSnapshot).where(CompetitorSnapshot.tenant_id == tenant_id,
                      CompetitorSnapshot.competitor_id == c.id).order_by(CompetitorSnapshot.captured_at.desc()).limit(1))
        if s:
            out.append((c, s))
    return out


def run(db, tenant_id: str, client: Client) -> dict:
    audit, pages = latest_client_audit(db, tenant_id, client.id)
    comps = latest_snapshots(db, tenant_id, client.id)
    if not audit and not comps:
        return {"created": 0, "note": "Run a website audit or a competitor analysis first."}
    corpus = " ".join(" ".join([p.title or "", " ".join(p.h1 or []), " ".join(p.h2 or []), p.text or ""]) for p in pages).lower()
    client_topics = {t["topic"] for t in topics_from_pages(pages, 80)}
    client_url = (audit and db.get(Website, audit.website_id).url) or client.website
    ops: list[dict] = []

    def op(kind, title, description, rationale, priority, next_action, refs):
        refs = [r for r in refs if r.get("url") or r.get("note")][:12]
        ops.append({"kind": kind, "title": title[:300], "description": description, "rationale": rationale,
                    "priority": priority, "next_action": next_action, "source_refs": refs,
                    "confidence": round(min(0.9, 0.35 + 0.1 * len(refs)), 2)})

    # 1. Content gaps: topics several competitors cover that the client's site does not
    if comps and pages:
        seen = defaultdict(list)
        for c, s in comps:
            for t in s.topics or []:
                seen[t].append((c, s))
        need = 2 if len(comps) >= 2 else 1
        gaps = [(t, v) for t, v in seen.items() if len(v) >= need and t not in client_topics and t not in corpus]
        gaps.sort(key=lambda x: (-len(x[1]), " " not in x[0]))
        for t, v in gaps[:8]:
            op("content_gap", f"Cover “{t}” on the website",
               f"{len(v)} competitor site(s) feature “{t}” in titles or headings; the client's crawled pages do not.",
               "Topics competitors build pages around are what buyers in this space look for; the client has no page answering them.",
               "medium" if len(v) >= 2 else "low", f"Plan a page or article on “{t}” using the client's own product facts.",
               [{"type": "competitor_page", "url": (s.homepage or {}).get("url") or c.website, "note": c.name} for c, s in v[:5]])

    # 2. Missing product info: competitors publish prices / certifications, the client does not
    client_prices = bool(PRICE.search(corpus))
    pricing_comps = [(c, s) for c, s in comps if s.prices]
    if pricing_comps and not client_prices and pages:
        op("missing_product_info", "Publish indicative prices or price ranges",
           f"{len(pricing_comps)} competitor(s) show prices publicly; no price was found on the client's crawled pages.",
           "Visible pricing (or 'from' ranges and MOQ) reduces friction for B2B buyers comparing suppliers.", "medium",
           "Agree with the client which prices, ranges or MOQ can be published; never publish unapproved figures.",
           [{"type": "competitor_page", "url": s.prices[0]["url"], "note": f"{c.name}: {s.prices[0]['text'][:80]}"} for c, s in pricing_comps[:5]])
    client_certs = {" ".join(m.group(1).split()) for m in CERTS.finditer(" ".join(p.text or "" for p in pages))}
    comp_certs = defaultdict(list)
    for c, s in comps:
        for ce in s.certifications or []:
            comp_certs[ce["name"]].append((c, ce["url"]))
    if comp_certs and not client_certs and pages:
        op("missing_product_info", "Show certifications and quality standards",
           "Competitors display certifications (" + ", ".join(sorted(comp_certs)[:6]) + "); none were found on the client's site.",
           "Certifications are a buyer shortlist filter in B2B and export markets.", "high",
           "Ask the client for certificates they actually hold, then add a Quality page and badges on product pages.",
           [{"type": "competitor_page", "url": u, "note": f"{c.name}: {n}"} for n, v in comp_certs.items() for c, u in v][:6])
    # 3. Differentiation: certifications the client shows that no competitor shows
    unique = sorted(client_certs - set(comp_certs))
    if unique and comps:
        op("differentiation", "Lead with " + ", ".join(unique[:3]),
           "The client's site mentions " + ", ".join(unique) + "; none of the analysed competitors do.",
           "A credential competitors lack is a concrete differentiator for ads, landing pages and sales decks.", "medium",
           "Feature it on the home page, product pages and in campaign copy.",
           [{"type": "client_page", "url": next((p.final_url or p.url for p in pages if u in (p.text or "")), client_url), "note": u} for u in unique[:3]])

    # 4-5. Industry and geographic landing pages from Phase 2 intelligence
    apps = db.scalars(select(ProductApplication).where(ProductApplication.tenant_id == tenant_id,
                      ProductApplication.client_id == client.id, ProductApplication.verification_status != "rejected")).all()
    comp_text = " ".join(" ".join([(s.homepage or {}).get("title") or "", " ".join(s.topics or [])] +
                                  [v.get("title") or "" for v in (s.pages or {}).values()]) for _, s in comps).lower()
    if pages:
        for ind in sorted({a.industry for a in apps if a.industry})[:8]:
            if ind.lower() not in corpus:
                op("industry_page", f"Industry page: {ind}",
                   f"The client's products have applications in {ind}, but the website never mentions it.",
                   "Industry pages match how buyers search (by their sector), and give ads a relevant landing page.", "medium",
                   f"Create a {ind} page: the problem, the products that solve it, applications, proof.",
                   [{"type": "intelligence", "note": f"Product application: {a.application} ({a.industry})"} for a in apps if a.industry == ind][:3]
                   + [{"type": "client_site", "url": client_url, "note": f"'{ind}' not found on {len(pages)} crawled pages"}])
        markets = db.scalars(select(TargetMarket).where(TargetMarket.tenant_id == tenant_id, TargetMarket.client_id == client.id,
                             TargetMarket.verification_status != "rejected")).all()
        for m in [m for m in markets if m.scope in ("state", "district_city", "country", "export_market")][:8]:
            if m.name.lower() not in corpus:
                op("geographic_page", f"Location page: {m.name}",
                   f"{m.name} is a target market hypothesis for the client but has no page or mention on the site.",
                   "Location pages support local and export search and give geo-targeted campaigns a landing page.",
                   m.priority or "low", f"Create a page for buyers in {m.name} (delivery, references, contact).",
                   [{"type": "intelligence", "note": f"Target market ({m.scope}): {m.name}" + (" — approved" if m.approved else " — AI hypothesis")},
                    {"type": "client_site", "url": client_url, "note": f"'{m.name}' not found on crawled pages"}])
    # 6. Underserved segments: client applications no competitor mentions
    if comps:
        for a in apps[:20]:
            if a.industry and a.industry.lower() not in comp_text:
                op("underserved_segment", f"Underserved segment: {a.industry}",
                   f"None of the {len(comps)} analysed competitors mention {a.industry}, where the client's {a.application} applies.",
                   "A segment competitors ignore can be cheaper to win in search and ads.", "medium",
                   f"Validate demand in {a.industry} with the client, then target it with a landing page and campaign.",
                   [{"type": "intelligence", "note": f"Application: {a.application}"}] +
                   [{"type": "competitor_site", "url": c.website, "note": f"{c.name}: no mention"} for c, _ in comps[:4]])
    # 7. Conversion
    if pages:
        has_contact = any(p.page_type == "contact" for p in pages)
        has_cta = any(w in corpus for w in ("request a quote", "get a quote", "enquire", "enquiry", "inquiry", "request quote", "contact us"))
        if not has_contact or not has_cta:
            op("conversion", "Add clear enquiry paths",
               ("No contact page was found. " if not has_contact else "") + ("No 'request a quote' or enquiry call to action was found." if not has_cta else ""),
               "Without an obvious enquiry path, traffic from campaigns cannot convert into leads.", "high",
               "Add a quote/enquiry form, WhatsApp/phone buttons and a contact page linked from every product page.",
               [{"type": "client_site", "url": client_url, "note": f"{len(pages)} pages crawled"}])

    # store, de-duplicated by fingerprint against earlier runs
    existing = {o.fingerprint for o in db.scalars(select(Opportunity).where(Opportunity.tenant_id == tenant_id,
                                                                            Opportunity.client_id == client.id)).all()}
    created = 0
    for o in ops:
        fp = hashlib.sha256(f"{o['kind']}|{o['title'].lower()}".encode()).hexdigest()
        if fp in existing:
            continue
        existing.add(fp)
        row = Opportunity(tenant_id=tenant_id, client_id=client.id, origin="rule", is_inferred=True,
                          verification_status="needs_review", fingerprint=fp,
                          crawl_job_id=audit.crawl_job_id if audit else None, **o)
        db.add(row)
        db.flush()
        for r in o["source_refs"]:
            db.add(EvidenceSource(tenant_id=tenant_id, client_id=client.id, finding_type="opportunity", finding_id=row.id,
                                  source_type="website" if r.get("url") else "client_record", source_url=(r.get("url") or None) and r["url"][:500],
                                  excerpt=r.get("note"), quote_matched=False))
        created += 1
    db.flush()
    return {"created": created, "evaluated": len(ops), "competitors_used": len(comps), "client_pages": len(pages)}
