"""AI marketing strategy generator.

Inputs are the client's real records (see common.marketing_sources) plus what the team types in (budget,
objectives, sales capacity, channels in use). Output has a fixed set of sections, each split into:
  facts           statements that cite a source with a verbatim quote (quotes are checked; a fact whose quote
                  is not found in that source is moved to assumptions, marked unverified)
  assumptions     what the plan takes for granted and the team must confirm
  recommendations the AI's suggestions
Guarantee language ("guaranteed leads", "assured ROI"...) is removed and reported. Nothing here promises
revenue, leads or performance.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, Field, field_validator

from app.core.db import SessionLocal
from app.models import ActivityLog, Client, MarketingStrategy
from app.services.ai.providers import ProviderNotConfigured, get_provider
from app.services.intelligence.common import StageError, ask
from app.services.marketing.common import Fact, GUARANTEE, guarantee_issues, marketing_sources, quote_ok, source_text, str_list

log = logging.getLogger(__name__)

SECTIONS = ["executive_summary", "positioning", "brand_messaging", "target_audience", "channel_strategy", "seo",
            "social_media", "paid_ads", "content", "lead_generation", "calendar", "budget_allocation", "kpis", "reporting"]
DISCLAIMER = ("AI-generated draft for the agency team to review. Facts cite the client's own records; assumptions must be "
              "confirmed; recommendations are suggestions. No revenue, lead or performance outcome is promised.")


class Section(BaseModel):
    key: str
    summary: str = Field(default="", max_length=3000)
    facts: list[Fact] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    @field_validator("assumptions", "recommendations", mode="before")
    @classmethod
    def _l(cls, v):
        return str_list(v, 15, 500)


class Out(BaseModel):
    sections: list[Section] = Field(default_factory=list, max_length=20)


SHAPE = """{"sections": [{"key": "one of: %s",
  "summary": "2-5 sentences",
  "facts": [{"text": "a fact from the sources", "source_id": "client|product:<id>|doc:<id>|web:<n>|persona:<id>|markets|competitors|audit|brand|channels", "quote": "verbatim 5-30 words from that source"}],
  "assumptions": ["what this plan assumes and the team must confirm"],
  "recommendations": ["specific, actionable suggestion"]}]}""" % ", ".join(SECTIONS)

TASK = ("Write a B2B digital marketing strategy for this client, as a draft for an agency team. Produce every section key "
        "once. Ground it in the sources: the client's products and applications, approved buyer profiles, target markets, "
        "competitors, website audit, brand assets and channels. Put a statement under facts ONLY when a source states it, "
        "with an exact quote. Everything else is an assumption or a recommendation. Never promise or guarantee revenue, leads, "
        "rankings, ROAS or any outcome; KPIs are targets to agree, not predictions. Never invent certifications, awards, "
        "client names, prices or statistics. The budget section allocates only the budget given below; if none is given, "
        "say the budget is needed. The calendar section is a cadence (e.g. weekly themes), not dates.")


def clean(out: Out, srcs) -> tuple[dict, list[str]]:
    sections, removed = {}, []
    for s in out.sections:
        if s.key not in SECTIONS or s.key in sections:
            continue
        facts, assumptions = [], list(s.assumptions)
        for f in s.facts:
            if quote_ok(srcs, f.source_id, f.quote):
                facts.append({"text": f.text, "source": f.source_id, "quote": f.quote})
            else:
                assumptions.append(f"Unverified (no matching quote in the sources): {f.text}")
        recs = []
        for r in s.recommendations:
            bad = guarantee_issues(r)
            if bad:
                removed += bad
                r = GUARANTEE.sub("[removed: no outcome is promised]", r)
            recs.append(r)
        summary = s.summary
        if guarantee_issues(summary):
            removed += guarantee_issues(summary)
            summary = GUARANTEE.sub("[removed]", summary)
        sections[s.key] = {"summary": summary, "facts": facts, "assumptions": assumptions[:20], "recommendations": recs}
    for k in SECTIONS:
        sections.setdefault(k, {"summary": "", "facts": [], "assumptions": [], "recommendations": [], "missing": True})
    return sections, removed


def inputs_text(inputs: dict) -> str:
    rows = [f"{k.replace('_', ' ')}: {v}" for k, v in inputs.items() if v not in (None, "", [], {})]
    return "\nTeam inputs for this strategy (stated by the agency, treat as facts from source_id=client):\n" + "\n".join(rows) if rows else ""


def run_strategy(strategy_id: str) -> None:
    db = SessionLocal()
    try:
        s = db.get(MarketingStrategy, strategy_id)
        if s is None or s.job_status not in ("queued", "running"):
            return
        s.job_status = "running"
        db.commit()
        try:
            provider = get_provider("analysis")
        except ProviderNotConfigured as e:
            s.job_status, s.error, s.status = "failed", str(e), "failed"
            db.commit()
            return
        client = db.get(Client, s.client_id)
        srcs = marketing_sources(db, s.tenant_id, client, (s.inputs or {}).get("product_ids") or None)
        try:
            out: Out = ask(provider, Out, TASK + inputs_text({k: v for k, v in (s.inputs or {}).items() if k != "product_ids"}),
                           SHAPE, source_text(srcs, provider.max_context_chars))
        except StageError as e:
            s.job_status, s.error, s.status = "failed", str(e)[:2000], "failed"
            db.add(ActivityLog(tenant_id=s.tenant_id, user_id=s.created_by, action="marketing.strategy_failed", entity_type="strategy",
                               entity_id=s.id, summary=f"Strategy generation failed: {str(e)[:150]}", meta={"client_id": s.client_id}))
            db.commit()
            return
        sections, removed = clean(out, srcs)
        s.sections, s.provider, s.model, s.status, s.job_status = sections, provider.name, provider.model, "ai_generated", "completed"
        s.disclaimer = DISCLAIMER + (f" Removed outcome promises: {', '.join(sorted(set(removed)))}." if removed else "")
        s.inputs = {**(s.inputs or {}), "sources_used": [x.ref for x in srcs]}
        db.add(ActivityLog(tenant_id=s.tenant_id, user_id=s.created_by, action="marketing.strategy_generated", entity_type="strategy",
                           entity_id=s.id, summary=f"Marketing strategy drafted: {s.title}", meta={"client_id": s.client_id}))
        db.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("strategy %s failed", strategy_id)
        db.rollback()
        s = db.get(MarketingStrategy, strategy_id)
        if s:
            s.job_status, s.error, s.status = "failed", f"{type(e).__name__}: {e}"[:2000], "failed"
            db.commit()
    finally:
        db.close()
