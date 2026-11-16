"""Stage: product intelligence — one set of facts per product, each tied to evidence.

Hard rule: specifications, materials, pricing, MOQ, manufacturing capacity and certifications are
kept ONLY when the model quotes them verbatim from a source. Anything else is dropped, so the field
stays unknown rather than invented.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models import BusinessInsight
from app.services.ai.providers import get_provider
from app.services.intelligence.common import (AIItem, Context, ask, finding_kwargs, quote_matches, render_sources,
                                              save_evidence, supersede)

Field_ = Literal["category", "specifications", "materials", "applications", "industry_usage", "advantages",
                 "differentiation", "pricing", "moq", "capacity", "certifications", "target_buyer_types"]
STRICT = {"specifications", "materials", "pricing", "moq", "capacity", "certifications"}
INFERRED = {"target_buyer_types", "differentiation"}
LABELS = {"category": "Category", "specifications": "Technical specification", "materials": "Material",
          "applications": "Application", "industry_usage": "Industry usage", "advantages": "Advantage",
          "differentiation": "Competitive differentiation", "pricing": "Pricing", "moq": "Minimum order quantity",
          "capacity": "Manufacturing capacity", "certifications": "Certification",
          "target_buyer_types": "Target buyer type"}


class Fact(AIItem):
    field: Field_
    value: str = Field(min_length=1, max_length=1000)


class ProductFacts(BaseModel):
    product_id: str
    facts: list[Fact] = Field(default_factory=list, max_length=60)


class Out(BaseModel):
    products: list[ProductFacts] = Field(default_factory=list)

    @field_validator("products", mode="before")
    @classmethod
    def drop_bad(cls, v):
        return v or []


SHAPE = """{"products": [{"product_id": "<id from the product record>", "facts": [
  {"field": "category|specifications|materials|applications|industry_usage|advantages|differentiation|pricing|moq|capacity|certifications|target_buyer_types",
   "value": "one concise fact", "evidence": [{"source_id": "...", "quote": "exact words"}], "confidence": 0.0}]}]}"""


def run(ctx: Context) -> dict:
    if not ctx.products:
        return {"facts": 0, "note": "Client has no products on record"}
    provider = get_provider("analysis")
    ids = [p.id for p in ctx.products]
    task = ("For EACH product listed in the product records, extract product intelligence. "
            "One fact per item (one spec, one certification, one advantage). "
            "specifications, materials, pricing, moq, capacity and certifications: ONLY if stated in a source, "
            "with an exact quote. advantages/industry_usage/applications: from sources. "
            "differentiation and target_buyer_types may be reasoned inferences but must still cite the source they rest on. "
            f"Valid product ids: {', '.join(ids)}.")
    out: Out = ask(provider, Out, task, SHAPE, render_sources(ctx.sources, provider.max_context_chars))
    supersede(ctx, BusinessInsight, "insight", ids, category="product_fact")
    kept = dropped = 0
    for pf in out.products:
        if pf.product_id not in ids:
            continue
        for f in pf.facts:
            if f.field in STRICT and not any(quote_matches(ctx, e) for e in f.evidence):
                dropped += 1  # unverifiable spec/price/MOQ/capacity/certification: never stored
                continue
            inferred = f.field in INFERRED
            row = BusinessInsight(product_id=pf.product_id, category="product_fact", field=f.field,
                                  title=LABELS[f.field], detail=f.value.strip(), **finding_kwargs(ctx, f, inferred))
            ctx.db.add(row)
            ctx.db.flush()
            save_evidence(ctx, "insight", row.id, f.evidence, inferred)
            kept += 1
    return {"facts": kept, "dropped_unverifiable": dropped}
