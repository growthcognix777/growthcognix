"""Company profile and business opportunities (AI stages), plus the structured BI report compiled
from stored findings (no AI: the report only ever shows what is in the database, with statuses)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.models import (BusinessInsight, BusinessProfile, BuyerPersona, Client, Document, EvidenceSource,
                        Product, ProductApplication, TargetMarket)
from app.services.ai.providers import get_provider
from app.services.intelligence.common import (AIItem, Context, Evidence, ask, finding_kwargs, quote_matches,
                                              render_sources, save_evidence, supersede)

FACT_KEYS = ("legal_name", "founded", "headquarters", "locations", "employees", "ownership", "business_model",
             "key_markets", "certifications", "awards", "key_customers_named", "export_presence")


class FactValue(BaseModel):
    value: str = Field(min_length=1, max_length=500)
    evidence: list[Evidence] = Field(default_factory=list, max_length=4)


class ProfileOut(AIItem):
    summary: str = Field(min_length=10, max_length=4000)
    value_proposition: str | None = Field(default=None, max_length=2000)
    facts: dict[str, FactValue] = Field(default_factory=dict)


PROFILE_SHAPE = """{"summary": "3-6 sentence company overview built only from the sources",
 "value_proposition": "what the company offers its buyers, or null",
 "facts": {"<one of: %s>": {"value": "...", "evidence": [{"source_id": "...", "quote": "exact words"}]}},
 "evidence": [{"source_id": "...", "quote": "exact words supporting the summary"}], "confidence": 0.0}""" % ", ".join(FACT_KEYS)


def run_profile(ctx: Context) -> dict:
    provider = get_provider("analysis")
    task = ("Write the company profile. Include a fact ONLY when a source states it, with an exact quote. "
            "Leave out every fact the sources do not state.")
    out: ProfileOut = ask(provider, ProfileOut, task, PROFILE_SHAPE, render_sources(ctx.sources, provider.max_context_chars))
    supersede(ctx, BusinessProfile, "profile")
    facts, dropped, fact_evidence = {}, 0, []
    for k, fv in out.facts.items():
        if k in FACT_KEYS and any(quote_matches(ctx, e) for e in fv.evidence):
            facts[k] = fv.value.strip()
            fact_evidence.extend(fv.evidence)
        else:
            dropped += 1
    row = BusinessProfile(summary=out.summary.strip(), value_proposition=out.value_proposition, facts=facts,
                          **finding_kwargs(ctx, out, inferred=False))
    ctx.db.add(row)
    ctx.db.flush()
    save_evidence(ctx, "profile", row.id, out.evidence + fact_evidence, inferred=False)
    return {"facts": len(facts), "dropped_unverifiable": dropped}


class Opportunity(AIItem):
    category: Literal["opportunity", "risk", "gap"] = "opportunity"
    product_id: str | None = None
    title: str = Field(min_length=3, max_length=300)
    detail: str = Field(min_length=5, max_length=2000)


class OppOut(BaseModel):
    insights: list[Opportunity] = Field(default_factory=list, max_length=25)


OPP_SHAPE = """{"insights": [{"category": "opportunity|risk|gap", "product_id": "... or null", "title": "short headline",
  "detail": "2-3 sentences, practical for a marketing agency", "evidence": [{"source_id": "...", "quote": "source fact"}], "confidence": 0.0}]}"""


def run_opportunities(ctx: Context) -> dict:
    provider = get_provider("fast")
    ids = {p.id for p in ctx.products}
    task = ("Identify 4-10 business opportunities for this client's growth (new applications, segments, markets, "
            "positioning), plus notable risks and information gaps an analyst should fill (e.g. missing pricing, "
            "certifications, capacity). Hypotheses only; no invented figures.")
    out: OppOut = ask(provider, OppOut, task, OPP_SHAPE, render_sources(ctx.sources, provider.max_context_chars))
    for cat in ("opportunity", "risk", "gap"):
        supersede(ctx, BusinessInsight, "insight", category=cat)
    for o in out.insights:
        pid = o.product_id if o.product_id in ids else None
        row = BusinessInsight(category=o.category, product_id=pid, title=o.title.strip(), detail=o.detail,
                              **finding_kwargs(ctx, o, inferred=True))
        ctx.db.add(row)
        ctx.db.flush()
        save_evidence(ctx, "insight", row.id, o.evidence, inferred=True)
    return {"insights": len(out.insights)}


# ---------------------------------------------------------------- report (no AI)
def _status_counts(rows) -> dict:
    out = {"verified": 0, "ai_hypothesis": 0, "needs_review": 0, "rejected": 0}
    for r in rows:
        out[r.verification_status] = out.get(r.verification_status, 0) + 1
    return out


def compile_report(db, tenant_id: str, client: Client, include_rejected: bool = False) -> dict:
    def q(model):
        stmt = select(model).where(model.tenant_id == tenant_id, model.client_id == client.id)
        if not include_rejected:
            stmt = stmt.where(model.verification_status != "rejected")
        return db.scalars(stmt.order_by(model.created_at)).all()

    profile = db.scalar(select(BusinessProfile).where(
        BusinessProfile.tenant_id == tenant_id, BusinessProfile.client_id == client.id,
        BusinessProfile.verification_status != "rejected").order_by(BusinessProfile.created_at.desc()).limit(1))
    products = db.scalars(select(Product).where(Product.tenant_id == tenant_id, Product.client_id == client.id)).all()
    insights, apps, personas, markets = q(BusinessInsight), q(ProductApplication), q(BuyerPersona), q(TargetMarket)
    all_rows = insights + apps + personas + markets + ([profile] if profile else [])
    docs = db.scalars(select(Document).where(Document.tenant_id == tenant_id, Document.client_id == client.id)).all()

    def f(r, **extra):
        return {"id": r.id, "status": r.verification_status, "approved": r.approved, "inferred": r.is_inferred,
                "confidence": r.confidence, **extra}

    return {
        "client": {"id": client.id, "company_name": client.company_name, "website": client.website,
                   "industry": client.industry},
        "profile": f(profile, summary=profile.summary, value_proposition=profile.value_proposition,
                     facts=profile.facts) if profile else None,
        "products": [{
            "id": p.id, "name": p.name,
            "facts": [f(i, field=i.field, title=i.title, detail=i.detail) for i in insights
                      if i.product_id == p.id and i.category == "product_fact"],
            "applications": [f(a, application=a.application, type=a.application_type, industry=a.industry)
                             for a in apps if a.product_id == p.id],
        } for p in products],
        "personas": [f(p, name=p.name, industry=p.industry, job_titles=p.job_titles) for p in personas],
        "markets": [f(m, scope=m.scope, name=m.name, parent=m.parent, rationale=m.rationale, priority=m.priority)
                    for m in markets],
        "opportunities": [f(i, category=i.category, title=i.title, detail=i.detail) for i in insights
                          if i.category in ("opportunity", "risk", "gap")],
        "sources": {"documents": len(docs),
                    "documents_extracted": sum(1 for d in docs if d.extraction_status == "completed"),
                    "evidence_items": len(db.scalars(select(EvidenceSource.id).where(
                        EvidenceSource.tenant_id == tenant_id, EvidenceSource.client_id == client.id)).all())},
        "status_counts": _status_counts(all_rows),
    }


def report_markdown(rep: dict) -> str:
    badge = {"verified": "Verified", "ai_hypothesis": "AI hypothesis", "needs_review": "Needs review",
             "rejected": "Rejected"}

    def b(x):
        s = badge[x["status"]]
        return f"{s} (approved)" if x.get("approved") and x["status"] == "ai_hypothesis" else s

    c = rep["client"]
    L = [f"# Business Intelligence Report — {c['company_name']}", "",
         "Statuses: Verified = confirmed by a reviewer; Needs review = quoted from a source, awaiting review; "
         "AI hypothesis = inferred by AI, not verified.", ""]
    p = rep["profile"]
    L += ["## Company overview", ""]
    if p:
        L += [f"_{b(p)}_", "", p["summary"] or "—", ""]
        if p.get("value_proposition"):
            L += [f"**Value proposition:** {p['value_proposition']}", ""]
        for k, v in (p.get("facts") or {}).items():
            L.append(f"- **{k.replace('_', ' ').title()}:** {v}")
        L.append("")
    else:
        L += ["— Not analysed yet.", ""]
    L += ["## Products", ""]
    for pr in rep["products"]:
        L += [f"### {pr['name']}", ""]
        for fct in pr["facts"]:
            L.append(f"- {fct['title']}: {fct['detail']} — _{b(fct)}_")
        if not pr["facts"]:
            L.append("- — No product facts yet.")
        if pr["applications"]:
            L += ["", "Applications:"]
            for a in pr["applications"]:
                L.append(f"- {a['application']} ({a['type']}{', ' + a['industry'] if a['industry'] else ''}) — _{b(a)}_")
        L.append("")
    L += ["## Buyer personas", ""] + ([f"- {x['name']} — _{b(x)}_" for x in rep["personas"]] or ["- —"]) + [""]
    L += ["## Target markets", ""] + ([f"- [{x['scope']}] {x['name']}{' (' + x['parent'] + ')' if x['parent'] else ''}: "
                                      f"{x['rationale']} — _{b(x)}_" for x in rep["markets"]] or ["- —"]) + [""]
    L += ["## Opportunities, risks and gaps", ""] + ([f"- **{x['category'].title()}: {x['title']}** — {x['detail']} — _{b(x)}_"
                                                    for x in rep["opportunities"]] or ["- —"])
    return "\n".join(L) + "\n"
