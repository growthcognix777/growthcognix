"""Shared plumbing for the intelligence modules: sources, evidence checking, AI calls, persistence."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (AnalysisJob, Client, DocumentExtraction, Document, EvidenceSource, Product,
                        WebsiteSnapshot)
from app.services.ai.providers import LLMProvider, ProviderError

SYSTEM_RULES = """You are a careful B2B business analyst for a digital marketing agency.
Rules you must follow:
- Use ONLY the numbered SOURCES provided. Never invent specifications, prices, MOQ, capacities,
  certifications, awards, client names, numbers or contact details.
- When a value is not in the sources, leave it out. Missing data stays unknown.
- Every factual item must cite evidence: the source_id and a SHORT VERBATIM quote copied exactly
  from that source (5-30 words). Do not paraphrase quotes.
- Inferences (buyer types, industries that could use a product, markets, pain points) are allowed only
  where asked, must be plausible from the sources, and are treated as hypotheses.
- confidence is your own 0-1 estimate; it is not verification.
- Reply with a single JSON object exactly matching the requested shape. No prose outside JSON."""


class Evidence(BaseModel):
    source_id: str = Field(max_length=80)
    quote: str = Field(default="", max_length=600)


class AIItem(BaseModel):
    evidence: list[Evidence] = Field(default_factory=list, max_length=6)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp(cls, v):
        if v is None or v == "":
            return None
        v = float(v)
        return v / 100 if 1 < v <= 100 else v


def str_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    return [str(x).strip()[:200] for x in v if str(x).strip()][:15]


@dataclass
class Source:
    ref: str
    source_type: str  # client_record|product_record|document|website
    label: str
    text: str
    url: str | None = None
    document_id: str | None = None
    product_id: str | None = None


@dataclass
class Context:
    db: Session
    job: AnalysisJob
    client: Client
    products: list[Product]
    sources: list[Source] = field(default_factory=list)

    @property
    def tenant_id(self) -> str:
        return self.job.tenant_id

    def source(self, ref: str) -> Source | None:
        return next((s for s in self.sources if s.ref == ref), None)


def _fmt(pairs: list[tuple[str, object]]) -> str:
    out = []
    for k, v in pairs:
        if v in (None, "", [], {}):
            continue
        if isinstance(v, list):
            v = ", ".join(map(str, v))
        out.append(f"{k}: {v}")
    return "\n".join(out)


def build_sources(ctx: Context) -> list[Source]:
    c = ctx.client
    sources = [Source("client", "client_record", f"Client record: {c.company_name}", _fmt([
        ("Company name", c.company_name), ("Website", c.website), ("Industry", c.industry),
        ("Business type", c.business_type), ("Description", c.description), ("Address", c.address),
        ("Target markets given by client", c.target_markets), ("Business objectives", c.business_objectives)]))]
    for i, p in enumerate(ctx.products, 1):
        sources.append(Source(f"product:{p.id}", "product_record", f"Product record: {p.name}", _fmt([
            ("Product id", p.id), ("Type", p.kind), ("Name", p.name), ("Category", p.category),
            ("Description", p.description), ("Specifications", p.specifications),
            ("Applications", p.applications), ("Pricing", p.pricing), ("Minimum order quantity", p.min_order_quantity),
            ("Production capacity", p.production_capacity), ("Target industries", p.target_industries)]),
            product_id=p.id))
    docs = ctx.db.execute(
        select(Document, DocumentExtraction).join(DocumentExtraction, DocumentExtraction.document_id == Document.id)
        .where(Document.tenant_id == ctx.tenant_id, Document.client_id == c.id)).all()
    for d, ex in docs:
        if ex.text:
            sources.append(Source(f"doc:{d.id}", "document", f"Document: {d.original_name}", ex.text,
                                  document_id=d.id, product_id=d.product_id))
    snaps = ctx.db.scalars(select(WebsiteSnapshot).where(
        WebsiteSnapshot.tenant_id == ctx.tenant_id, WebsiteSnapshot.client_id == c.id,
        WebsiteSnapshot.text.is_not(None)).order_by(WebsiteSnapshot.created_at.desc())).all()
    seen = set()
    for s in snaps:
        if s.url in seen:
            continue
        seen.add(s.url)
        sources.append(Source(f"web:{len(seen)}", "website", f"Web page: {s.url}", s.text or "", url=s.url))
    return sources


def render_sources(sources: list[Source], budget: int) -> str:
    """Render sources for a prompt within a character budget, sharing it fairly."""
    if not sources:
        return "(no sources)"
    per = max(1500, budget // len(sources))
    blocks = []
    for s in sources:
        text = s.text if len(s.text) <= per else s.text[:per] + " …[truncated]"
        blocks.append(f"### SOURCE source_id={s.ref} ({s.label})\n{text}")
    return "\n\n".join(blocks)


_ws = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _ws.sub(" ", re.sub(r"[“”\"'‘’`]", "", s)).strip().lower()


def quote_matches(ctx: Context, ev: Evidence) -> bool:
    src = ctx.source(ev.source_id)
    q = _norm(ev.quote or "")
    return bool(src and len(q) >= 8 and q in _norm(src.text))


def status_for(ctx: Context, evidence: list[Evidence], inferred: bool) -> str:
    if inferred:
        return "ai_hypothesis"
    return "needs_review" if any(quote_matches(ctx, e) for e in evidence) else "ai_hypothesis"


def save_evidence(ctx: Context, finding_type: str, finding_id: str, evidence: list[Evidence], inferred: bool) -> None:
    kept = 0
    for ev in evidence:
        src = ctx.source(ev.source_id)
        if src is None:
            continue  # cites a source that does not exist: drop the citation, never trust it
        ctx.db.add(EvidenceSource(
            tenant_id=ctx.tenant_id, client_id=ctx.client.id, finding_type=finding_type, finding_id=finding_id,
            source_type=src.source_type, source_ref=src.ref, source_url=src.url, document_id=src.document_id,
            excerpt=(ev.quote or "")[:600] or None, quote_matched=quote_matches(ctx, ev)))
        kept += 1
    if inferred or kept == 0:
        ctx.db.add(EvidenceSource(
            tenant_id=ctx.tenant_id, client_id=ctx.client.id, finding_type=finding_type, finding_id=finding_id,
            source_type="ai_inference", excerpt="Inferred by AI from the sources above; not verified."))


def finding_kwargs(ctx: Context, item: AIItem, inferred: bool) -> dict:
    return dict(tenant_id=ctx.tenant_id, client_id=ctx.client.id, analysis_job_id=ctx.job.id, origin="ai",
                confidence=item.confidence, is_inferred=inferred,
                verification_status=status_for(ctx, item.evidence, inferred))


def supersede(ctx: Context, model, finding_type: str, product_ids: list[str] | None = None, **filters) -> None:
    """Remove earlier unreviewed AI findings of this kind so a re-run does not duplicate them.
    Anything a human reviewed or edited is kept."""
    cond = [model.tenant_id == ctx.tenant_id, model.client_id == ctx.client.id, model.origin == "ai",
            model.reviewed_at.is_(None), model.edited.is_(False)]
    if product_ids is not None and hasattr(model, "product_id"):
        cond.append(model.product_id.in_(product_ids))
    for k, v in filters.items():
        cond.append(getattr(model, k) == v)
    ids = list(ctx.db.scalars(select(model.id).where(*cond)))
    if ids:
        ctx.db.execute(delete(EvidenceSource).where(EvidenceSource.finding_type == finding_type,
                                                    EvidenceSource.finding_id.in_(ids)))
        ctx.db.execute(delete(model).where(model.id.in_(ids)))


class StageError(RuntimeError):
    pass


def ask(provider: LLMProvider, schema: type[BaseModel], task: str, shape: str, sources_text: str) -> BaseModel:
    """Call the model and validate against `schema`; one corrective retry on invalid output."""
    prompt = f"TASK:\n{task}\n\nJSON SHAPE:\n{shape}\n\nSOURCES:\n{sources_text}"
    last_err = ""
    for attempt in range(2):
        p = prompt if attempt == 0 else prompt + f"\n\nYour previous reply was invalid: {last_err}\nReturn valid JSON only."
        try:
            raw = provider.generate_json(SYSTEM_RULES, p)
        except ProviderError as e:
            raise StageError(str(e)) from e
        try:
            return schema.model_validate(raw)
        except ValidationError as e:
            last_err = json.dumps(e.errors(include_url=False, include_context=False)[:5], default=str)[:800]
    raise StageError(f"AI output failed schema validation: {last_err}")


def now() -> datetime:
    return datetime.now(timezone.utc)
