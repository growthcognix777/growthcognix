"""Stage: buyer personas. Personas are always inferences (`is_inferred`), so they can be approved as a
working hypothesis but never shown as verified. No real people or companies are named."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models import BuyerPersona
from app.services.ai.providers import get_provider
from app.services.intelligence.common import (AIItem, Context, ask, finding_kwargs, render_sources, save_evidence,
                                              str_list, supersede)


class Persona(AIItem):
    product_id: str | None = None
    name: str = Field(min_length=2, max_length=200)
    buyer_category: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    company_size: str | None = Field(default=None, max_length=100)
    job_titles: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    purchase_reasons: list[str] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=2000)

    norm_lists = field_validator("job_titles", "departments", "pain_points", "purchase_reasons",
                             mode="before")(lambda cls, v: str_list(v))


class Out(BaseModel):
    personas: list[Persona] = Field(default_factory=list, max_length=30)


SHAPE = """{"personas": [{"product_id": "... or null for all products", "name": "short persona label e.g. 'Plant maintenance head, food processing'",
  "buyer_category": "...", "industry": "...", "company_size": "e.g. mid-size manufacturer", "job_titles": ["..."],
  "departments": ["..."], "pain_points": ["..."], "purchase_reasons": ["..."], "description": "2 sentences",
  "evidence": [{"source_id": "...", "quote": "source fact this rests on"}], "confidence": 0.0}]}"""


def run(ctx: Context) -> dict:
    provider = get_provider("fast")
    ids = {p.id for p in ctx.products}
    task = ("Propose 3-8 B2B buyer personas for this client's products: who buys, their job titles and departments, "
            "pain points and purchase reasons. These are hypotheses. Never name real people or companies, never state "
            "budgets or purchase intent as fact. " + (f"Valid product ids: {', '.join(ids)}." if ids else ""))
    out: Out = ask(provider, Out, task, SHAPE, render_sources(ctx.sources, provider.max_context_chars))
    supersede(ctx, BuyerPersona, "persona", list(ids) if ctx.job.params.get("product_ids") else None)
    n = 0
    for p in out.personas:
        pid = p.product_id if p.product_id in ids else None
        row = BuyerPersona(product_id=pid, name=p.name.strip(), buyer_category=p.buyer_category, industry=p.industry,
                           company_size=p.company_size, job_titles=p.job_titles, departments=p.departments,
                           pain_points=p.pain_points, purchase_reasons=p.purchase_reasons, description=p.description,
                           **finding_kwargs(ctx, p, inferred=True))
        ctx.db.add(row)
        ctx.db.flush()
        save_evidence(ctx, "persona", row.id, p.evidence, inferred=True)
        n += 1
    return {"personas": n}
