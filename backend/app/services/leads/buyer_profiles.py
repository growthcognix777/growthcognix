"""AI buyer-profile generator (Phase 4). Extends the Phase 2 persona stage: same sources, evidence checks and
review statuses, plus buyer type, direct/indirect industry, application categories, company types, problems
solved, substitutes, geography and a rationale. Profiles are always hypotheses (`is_inferred`) until a
person approves them as a working basis for discovery; they never name real people or companies."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.models import AnalysisJob, BuyerPersona, Client, Product, ProductApplication
from app.models.leads import BUYER_TYPES
from app.services.ai.providers import get_provider
from app.services.intelligence.common import (AIItem, Context, StageError, ask, build_sources, finding_kwargs, now,
                                              render_sources, save_evidence, str_list, supersede)


class Profile(AIItem):
    product_id: str | None = None
    name: str = Field(min_length=2, max_length=200)
    buyer_type: Literal["end_user", "distributor", "importer", "dealer", "oem", "institutional", "project"] = "end_user"
    industry: str | None = Field(default=None, max_length=200)
    industry_relation: Literal["direct", "indirect"] = "direct"
    application_categories: list[str] = Field(default_factory=list)
    company_types: list[str] = Field(default_factory=list)
    company_size: str | None = Field(default=None, max_length=100)
    departments: list[str] = Field(default_factory=list)
    job_titles: list[str] = Field(default_factory=list)
    problems_solved: list[str] = Field(default_factory=list)
    purchase_reasons: list[str] = Field(default_factory=list)
    substitutes: list[str] = Field(default_factory=list)
    geography: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=10, max_length=1500)

    @field_validator("buyer_type", mode="before")
    @classmethod
    def bt(cls, v):
        v = str(v or "end_user").strip().lower().replace(" ", "_").replace("-", "_")
        return {"end_users": "end_user", "dealer_reseller": "dealer", "reseller": "dealer", "oem_buyer": "oem",
                "project_buyer": "project", "epc": "project"}.get(v, v if v in BUYER_TYPES else "end_user")

    norm = field_validator("application_categories", "company_types", "departments", "job_titles", "problems_solved",
                           "purchase_reasons", "substitutes", "geography", mode="before")(lambda cls, v: str_list(v))


class Out(BaseModel):
    profiles: list[Profile] = Field(default_factory=list, max_length=30)


SHAPE = """{"profiles": [{"product_id": "... or null", "name": "e.g. 'Food processing plants needing process water treatment'",
 "buyer_type": "end_user|distributor|importer|dealer|oem|institutional|project", "industry": "...", "industry_relation": "direct|indirect",
 "application_categories": ["what they use the product for"], "company_types": ["e.g. dairy plant, hotel, hospital"],
 "company_size": "...", "departments": ["..."], "job_titles": ["roles, never names"], "problems_solved": ["operational problems"],
 "purchase_reasons": ["why they need it"], "substitutes": ["what they use instead today"], "geography": ["countries/states where this profile applies, if the sources support it"],
 "rationale": "why this buyer needs the product, from the sources", "evidence": [{"source_id": "...", "quote": "verbatim"}], "confidence": 0.0}]}"""

TASK = ("Build B2B buyer profiles for the client's products. Think by application and operational need, not by keyword: "
        "include direct buyer industries and indirect ones (businesses that have the problem the product solves even if they "
        "never search for the product), plus channel buyers (distributors, importers, dealers), OEMs, institutional and "
        "project buyers where plausible. Give each profile a rationale tied to the sources and cite evidence. These are "
        "hypotheses: never name real people or companies, never state budgets, demand or purchase intent as fact.")


def generate(db, tenant_id: str, client: Client, user_id: str | None, product_ids: list[str] | None = None,
             buyer_types: list[str] | None = None, geography: list[str] | None = None) -> dict:
    q = select(Product).where(Product.tenant_id == tenant_id, Product.client_id == client.id)
    if product_ids:
        q = q.where(Product.id.in_(product_ids))
    products = db.scalars(q).all()
    if not products:
        raise ValueError("Add at least one product or service before generating buyer profiles")
    provider = get_provider("analysis")
    job = AnalysisJob(tenant_id=tenant_id, client_id=client.id, status="running", progress=10, created_by=user_id,
                      stages=[{"key": "buyer_profiles", "status": "running"}], provider=provider.name, model=provider.model,
                      params={"product_ids": product_ids or [], "kind": "buyer_profiles"}, started_at=now())
    db.add(job)
    db.flush()
    ctx = Context(db=db, job=job, client=client, products=list(products))
    ctx.sources = build_sources(ctx)
    apps = db.scalars(select(ProductApplication).where(ProductApplication.tenant_id == tenant_id,
                      ProductApplication.client_id == client.id, ProductApplication.verification_status != "rejected")).all()
    extra = ""
    if apps:
        extra = "\nKnown applications (Phase 2 findings, may be hypotheses): " + "; ".join(
            f"{a.application} ({a.industry or 'industry n/a'})" for a in apps[:40])
    if buyer_types:
        extra += "\nFocus on these buyer types: " + ", ".join(buyer_types)
    if geography:
        extra += "\nThe agency is researching these geographies: " + ", ".join(geography)
    ids = {p.id for p in products}
    try:
        out: Out = ask(provider, Out, TASK + extra + f"\nValid product ids: {', '.join(ids)}.", SHAPE,
                       render_sources(ctx.sources, provider.max_context_chars))
    except StageError as e:
        job.status, job.error, job.completed_at = "failed", str(e)[:2000], now()
        job.stages = [{"key": "buyer_profiles", "status": "failed", "error": str(e)[:300]}]
        db.commit()
        raise
    supersede(ctx, BuyerPersona, "persona", list(ids) if product_ids else None)
    made = []
    for p in out.profiles:
        row = BuyerPersona(product_id=p.product_id if p.product_id in ids else None, name=p.name.strip(), buyer_category=p.buyer_type,
                           buyer_type=p.buyer_type, industry=p.industry, industry_relation=p.industry_relation,
                           application_categories=p.application_categories, company_types=p.company_types,
                           company_size=p.company_size, departments=p.departments, job_titles=p.job_titles,
                           pain_points=p.problems_solved, problems_solved=p.problems_solved, purchase_reasons=p.purchase_reasons,
                           substitutes=p.substitutes, geography=p.geography, rationale=p.rationale, description=p.rationale,
                           **finding_kwargs(ctx, p, inferred=True))
        db.add(row)
        db.flush()
        save_evidence(ctx, "persona", row.id, p.evidence, inferred=True)
        made.append(row.id)
    job.status, job.progress, job.completed_at = "completed", 100, now()
    job.stages = [{"key": "buyer_profiles", "status": "completed", "count": len(made)}]
    job.summary = {"buyer_profiles": len(made)}
    db.commit()
    return {"created": len(made), "ids": made, "analysis_id": job.id, "provider": provider.name, "model": provider.model}
