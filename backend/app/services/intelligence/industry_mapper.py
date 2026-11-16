"""Stage: market applications per product — direct and indirect uses, industries, businesses that
need it, buyer categories, pain points, purchase reasons and substitutes.

A direct application quoted from a source is `needs_review`; indirect applications are inferences and
always stay `ai_hypothesis`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models import ProductApplication
from app.services.ai.providers import get_provider
from app.services.intelligence.common import (AIItem, Context, ask, finding_kwargs, render_sources, save_evidence,
                                              str_list, supersede)


class App(AIItem):
    product_id: str
    application: str = Field(min_length=2, max_length=300)
    application_type: Literal["direct", "indirect"] = "direct"
    industry: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    businesses_needing: list[str] = Field(default_factory=list)
    buyer_categories: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    purchase_reasons: list[str] = Field(default_factory=list)
    substitutes: list[str] = Field(default_factory=list)

    norm_lists = field_validator("businesses_needing", "buyer_categories", "pain_points", "purchase_reasons",
                             "substitutes", mode="before")(lambda cls, v: str_list(v))


class Out(BaseModel):
    applications: list[App] = Field(default_factory=list, max_length=80)


SHAPE = """{"applications": [{"product_id": "...", "application": "what it is used for", "application_type": "direct|indirect",
  "industry": "industry using it", "description": "1-2 sentences", "businesses_needing": ["type of business"],
  "buyer_categories": ["e.g. OEMs, contractors, distributors"], "pain_points": ["problem it solves"],
  "purchase_reasons": ["why they buy"], "substitutes": ["alternative products"],
  "evidence": [{"source_id": "...", "quote": "exact words"}], "confidence": 0.0}]}"""


def run(ctx: Context) -> dict:
    if not ctx.products:
        return {"applications": 0, "note": "Client has no products on record"}
    provider = get_provider("analysis")
    ids = [p.id for p in ctx.products]
    task = ("For each product, list its DIRECT applications (stated in sources) and plausible INDIRECT applications "
            "(reasoned), the industries that use it, the kinds of businesses that need it, buyer categories, "
            "pain points, purchase reasons and substitutes. 3-8 applications per product. Cite evidence; for "
            "indirect ones cite the source fact the inference rests on. Do not name specific companies. "
            f"Valid product ids: {', '.join(ids)}.")
    out: Out = ask(provider, Out, task, SHAPE, render_sources(ctx.sources, provider.max_context_chars))
    supersede(ctx, ProductApplication, "application", ids)
    n = 0
    for a in out.applications:
        if a.product_id not in ids:
            continue
        inferred = a.application_type == "indirect"
        row = ProductApplication(
            product_id=a.product_id, application=a.application.strip(), application_type=a.application_type,
            industry=a.industry, description=a.description, businesses_needing=a.businesses_needing,
            buyer_categories=a.buyer_categories, pain_points=a.pain_points, purchase_reasons=a.purchase_reasons,
            substitutes=a.substitutes, **finding_kwargs(ctx, a, inferred))
        ctx.db.add(row)
        ctx.db.flush()
        save_evidence(ctx, "application", row.id, a.evidence, inferred)
        n += 1
    return {"applications": n}
