"""Stage: target markets — India overall, states, districts & cities, international countries and export
markets, each with a rationale and the evidence it rests on. Always hypotheses (`is_inferred`)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models import TargetMarket
from app.services.ai.providers import get_provider
from app.services.intelligence.common import (AIItem, Context, ask, finding_kwargs, render_sources, save_evidence,
                                              supersede)

Scope = Literal["india", "state", "district_city", "country", "export_market"]


class Market(AIItem):
    scope: Scope
    name: str = Field(min_length=2, max_length=200)
    parent: str | None = Field(default=None, max_length=200)
    product_id: str | None = None
    rationale: str = Field(min_length=5, max_length=2000)
    priority: Literal["high", "medium", "low"] | None = None

    @field_validator("scope", mode="before")
    @classmethod
    def norm_scope(cls, v):
        v = str(v).lower().strip().replace(" ", "_").replace("-", "_")
        return {"district": "district_city", "city": "district_city", "export": "export_market",
                "international": "country", "national": "india"}.get(v, v)

    @field_validator("priority", mode="before")
    @classmethod
    def norm_priority(cls, v):
        return str(v).lower() if v else None


class Out(BaseModel):
    markets: list[Market] = Field(default_factory=list, max_length=60)


SHAPE = """{"markets": [{"scope": "india|state|district_city|country|export_market", "name": "e.g. Karnataka / Pune / UAE",
  "parent": "state for a city, region for a country, else null", "product_id": "... or null", "rationale": "why this market, tied to the sources",
  "priority": "high|medium|low", "evidence": [{"source_id": "...", "quote": "source fact this rests on"}], "confidence": 0.0}]}"""


def run(ctx: Context) -> dict:
    provider = get_provider("analysis")
    ids = {p.id for p in ctx.products}
    task = ("Recommend target markets for this client: one 'india' entry for the national market if relevant, "
            "3-6 Indian states, 3-8 districts or cities (with parent state), 3-6 international countries and "
            "1-4 export market regions. Give a rationale tied to the products, their applications and any markets "
            "the client already named. These are hypotheses; do not state market sizes or figures that are not "
            "in the sources. " + (f"Valid product ids: {', '.join(ids)}." if ids else ""))
    out: Out = ask(provider, Out, task, SHAPE, render_sources(ctx.sources, provider.max_context_chars))
    supersede(ctx, TargetMarket, "market", list(ids) if ctx.job.params.get("product_ids") else None)
    n = 0
    for m in out.markets:
        pid = m.product_id if m.product_id in ids else None
        row = TargetMarket(scope=m.scope, name=m.name.strip(), parent=m.parent, product_id=pid, rationale=m.rationale,
                           priority=m.priority, **finding_kwargs(ctx, m, inferred=True))
        ctx.db.add(row)
        ctx.db.flush()
        save_evidence(ctx, "market", row.id, m.evidence, inferred=True)
        n += 1
    return {"markets": n}
