"""Phase 5 API: strategy, budget, campaigns, social/SEO content, brand assets, ads planner, calendar, approvals,
social accounts (OAuth), publishing, analytics and reports.

Tenant comes from the verified token; rows load through scoped()/get_owned(). Roles: staff drafts and submits;
manager+ approves, publishes, connects accounts and deletes; admin+ approves ad spend.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.core.config import get_settings
from app.core.db import get_db
from app.deps import ROLE_RANK, Ctx, get_ctx
from app.models import (AdvertisingCampaign, ApprovalRequest, BuyerPersona, Client, ContentAsset, ContentCalendar, ContentItem,
                        ContentRevision, Document, MarketingBudget, MarketingCampaign, MarketingReport, MarketingStrategy, Product,
                        PublishingJob, SocialAccount, User)
from app.models.marketing import APPROVAL_STATUSES, BUDGET_CATEGORIES, CONTENT_KINDS
from app.services.activity import log
from app.services.ai.providers import ProviderNotConfigured, get_provider, provider_status
from app.services.intelligence.common import StageError
from app.services.marketing import (ad_campaign_planner, approval_service, brand_asset_manager, budget_planner, marketing_analytics,
                                    publishing_service, reports)
from app.services.marketing.common import detect_claims, guarantee_issues, now
from app.services.marketing.content_generator import SEO_KINDS, SOCIAL_KINDS, generate as generate_content
from app.services.marketing.marketing_strategy import SECTIONS, run_strategy
from app.services.marketing.publishing_service import PublishError
from app.services.tenancy import get_owned, scoped
from app.services.web.crawler_service import normalize

router = APIRouter(tags=["marketing strategy & campaigns"])
P = "/api/v1"


def _need(ctx: Ctx, role: str) -> None:
    if ROLE_RANK[ctx.user.role] < ROLE_RANK[role]:
        raise HTTPException(403, f"Requires {role} role or higher")


def _client(ctx: Ctx, cid: str) -> Client:
    return get_owned(ctx, Client, cid, "Client")


def _require_ai(purpose: str = "analysis"):
    try:
        return get_provider(purpose)
    except ProviderNotConfigured as e:
        raise HTTPException(409, str(e))


def _out(o, keys: list[str]) -> dict:
    return {k: getattr(o, k) for k in keys}


REVIEW = ["status", "origin", "provider", "model", "version", "reviewed_by", "reviewed_at", "approved_by", "approved_at", "created_by",
          "created_at", "updated_at"]
STRAT = ["id", "client_id", "title", "inputs", "sections", "disclaimer", "job_status", "error"] + REVIEW
BUDGET = ["id", "client_id", "name", "strategy_id", "scenario", "currency", "monthly_total", "lines", "quarterly_overrides", "notes"] + REVIEW
CONTENT = ["id", "client_id", "campaign_id", "product_id", "persona_id", "studio", "kind", "platform", "title", "body", "data",
           "claims_to_check", "asset_ids", "scheduled_at", "published_at", "publishing_status", "assigned_to"] + REVIEW
AD = ["id", "client_id", "campaign_id", "platform", "name", "objective", "audience", "geography", "creative_brief", "headlines", "ad_copy",
      "landing_page", "currency", "daily_budget", "total_budget", "bidding", "conversion_tracking", "ab_tests", "targets", "claims_to_check",
      "spend_approved", "spend_cap", "spend_approved_by", "spend_approved_at"] + REVIEW
ASSET = ["id", "client_id", "kind", "name", "document_id", "value", "product_id", "tags", "notes", "approved", "approved_by", "approved_at",
         "created_at"]
ACCOUNT = ["id", "client_id", "platform", "account_name", "external_id", "status", "token_expires_at", "scopes", "permissions", "last_error",
           "connected_by", "connected_at", "created_at"]
JOB = ["id", "client_id", "content_item_id", "social_account_id", "platform", "status", "scheduled_at", "attempts", "error", "external_post_id",
       "external_url", "content_version", "requested_by", "published_at", "created_at", "updated_at"]
CAMPAIGN = ["id", "client_id", "name", "objective", "strategy_id", "budget_id", "start_date", "end_date", "status", "created_at"]


def budget_out(b: MarketingBudget) -> dict:
    return {**_out(b, BUDGET), "summary": budget_planner.summarise(b.lines, b.quarterly_overrides)}


def _bg(background: BackgroundTasks, fn, *args, ctx: Ctx | None = None, on_fail=None) -> None:
    if get_settings().analysis_inline:
        background.add_task(fn, *args)
        return
    try:
        from app.worker import queue
        queue().enqueue(fn, *args, job_timeout=1800)
    except Exception as e:  # noqa: BLE001
        if on_fail:
            on_fail(f"Job queue unavailable ({type(e).__name__}). Start Redis and the worker, then retry.")
            ctx.db.commit()


def _check_product(ctx: Ctx, client_id: str, pid: str | None) -> str | None:
    if not pid:
        return None
    p = get_owned(ctx, Product, pid, "Product")
    if p.client_id != client_id:
        raise HTTPException(400, "Product belongs to another client")
    return p.id


def _url(u: str | None, required: bool = False) -> str | None:
    if not u or not u.strip():
        if required:
            raise HTTPException(422, "A URL is required")
        return None
    n = normalize(u.strip() if "://" in u else "https://" + u.strip())
    if not n:
        raise HTTPException(422, "Enter a valid http(s) URL")
    return n[:500]


# ------------------------------------------------------------------ status & overview
@router.get(f"{P}/marketing/status")
def status(ctx: Ctx = Depends(get_ctx)):
    return {"ai": provider_status(), "publishing": publishing_service.status(), "ad_platforms": ad_campaign_planner.ADAPTERS,
            "approval_statuses": APPROVAL_STATUSES, "content_kinds": CONTENT_KINDS, "social_kinds": sorted(SOCIAL_KINDS),
            "seo_kinds": sorted(SEO_KINDS), "budget_categories": BUDGET_CATEGORIES, "budget_labels": budget_planner.LABELS,
            "strategy_sections": SECTIONS, "analytics_unavailable": marketing_analytics.UNAVAILABLE,
            "email_marketing": "Planned adapter (Listmonk + a free SMTP tier); not built in this phase."}


@router.get(f"{P}/clients/{{client_id}}/marketing/overview")
def overview(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)

    def by(model, col="status"):
        return dict(ctx.db.execute(select(getattr(model, col), func.count()).where(model.tenant_id == ctx.tenant_id, model.client_id == client_id)
                                   .group_by(getattr(model, col))).all())
    upcoming = ctx.db.scalars(scoped(ctx, ContentItem).where(ContentItem.client_id == client_id, ContentItem.scheduled_at >= now(),
                                                             ContentItem.status.in_(("approved", "scheduled")))
                              .order_by(ContentItem.scheduled_at).limit(5)).all()
    pending = ctx.db.scalar(select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.tenant_id == ctx.tenant_id,
                            ApprovalRequest.client_id == client_id, ApprovalRequest.status == "pending")) or 0
    budget = ctx.db.scalar(scoped(ctx, MarketingBudget).where(MarketingBudget.client_id == client_id, MarketingBudget.status == "approved")
                           .order_by(MarketingBudget.approved_at.desc()).limit(1))
    return {"strategies": by(MarketingStrategy), "content": by(ContentItem), "ad_plans": by(AdvertisingCampaign), "accounts": by(SocialAccount),
            "pending_approvals": pending, "upcoming": [_out(i, CONTENT) for i in upcoming],
            "approved_budget": budget_out(budget) if budget else None}


# ------------------------------------------------------------------ revisions & approvals
@router.get(f"{P}/marketing/{{entity_type}}/{{entity_id}}/history")
def history(entity_type: Literal["strategy", "budget", "content", "ad_plan"], entity_id: str, ctx: Ctx = Depends(get_ctx)):
    get_owned(ctx, approval_service.MODELS[entity_type], entity_id, "Item")
    revs = ctx.db.scalars(select(ContentRevision).where(ContentRevision.tenant_id == ctx.tenant_id, ContentRevision.entity_type == entity_type,
                                                        ContentRevision.entity_id == entity_id).order_by(ContentRevision.created_at.desc())).all()
    apps = ctx.db.scalars(select(ApprovalRequest).where(ApprovalRequest.tenant_id == ctx.tenant_id, ApprovalRequest.entity_type == entity_type,
                                                        ApprovalRequest.entity_id == entity_id).order_by(ApprovalRequest.created_at.desc())).all()
    return {"revisions": [_out(r, ["id", "version", "snapshot", "note", "user_id", "created_at"]) for r in revs],
            "approvals": [_out(a, ["id", "stage", "status", "requested_by", "reviewer_id", "reviewer_name", "note", "decided_at",
                                   "entity_version", "created_at"]) for a in apps]}


class ReviewIn(BaseModel):
    action: Literal["submit", "approve", "send_to_client", "client_approve", "reject", "request_changes"]
    note: str | None = Field(default=None, max_length=2000)
    reviewer_name: str | None = Field(default=None, max_length=200)


def _review(ctx: Ctx, entity_type: str, obj, body: ReviewIn) -> None:
    approval_service.act(ctx.db, ctx.user, entity_type, obj, body.action, body.note, body.reviewer_name)
    log(ctx, f"marketing.{body.action}", entity_type, obj.id, f"{entity_type.replace('_', ' ').title()} {body.action.replace('_', ' ')}: "
        f"{getattr(obj, 'title', None) or getattr(obj, 'name', '')}", client_id=obj.client_id)
    ctx.db.commit()


@router.get(f"{P}/clients/{{client_id}}/marketing/approvals")
def approvals(client_id: str, ctx: Ctx = Depends(get_ctx), status: str | None = "pending"):
    _client(ctx, client_id)
    q = select(ApprovalRequest).where(ApprovalRequest.tenant_id == ctx.tenant_id, ApprovalRequest.client_id == client_id)
    if status:
        q = q.where(ApprovalRequest.status == status)
    rows = ctx.db.scalars(q.order_by(ApprovalRequest.created_at.desc()).limit(300)).all()
    out = []
    for a in rows:
        obj = ctx.db.get(approval_service.MODELS[a.entity_type], a.entity_id)
        if obj is None or obj.tenant_id != ctx.tenant_id:
            continue
        out.append({**_out(a, ["id", "entity_type", "entity_id", "stage", "status", "requested_by", "reviewer_id", "reviewer_name", "note",
                               "decided_at", "entity_version", "created_at"]),
                    "title": getattr(obj, "title", None) or getattr(obj, "name", None), "entity_status": obj.status,
                    "platform": getattr(obj, "platform", None), "kind": getattr(obj, "kind", None),
                    "claims_to_check": getattr(obj, "claims_to_check", []), "current_version": obj.version})
    return out


# ------------------------------------------------------------------ strategies
class StrategyIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    objectives: str | None = Field(default=None, max_length=2000)
    monthly_budget: float | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    sales_capacity: str | None = Field(default=None, max_length=500)
    channels_in_use: list[str] = Field(default_factory=list, max_length=20)
    product_ids: list[str] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)


class StrategyPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    sections: dict[str, dict] | None = None
    note: str | None = Field(default=None, max_length=500)


@router.get(f"{P}/clients/{{client_id}}/marketing/strategies")
def list_strategies(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    rows = ctx.db.scalars(scoped(ctx, MarketingStrategy).where(MarketingStrategy.client_id == client_id).order_by(MarketingStrategy.created_at.desc())).all()
    return [_out(s, STRAT) for s in rows]


@router.post(f"{P}/clients/{{client_id}}/marketing/strategies", status_code=201)
def create_strategy(client_id: str, body: StrategyIn, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    _require_ai()
    for pid in body.product_ids:
        _check_product(ctx, client_id, pid)
    s = MarketingStrategy(tenant_id=ctx.tenant_id, client_id=client_id, title=body.title.strip(), status="draft", origin="ai",
                          job_status="queued", inputs=body.model_dump(exclude={"title"}), created_by=ctx.user.id)
    ctx.db.add(s)
    log(ctx, "marketing.strategy_requested", "strategy", s.id, f"Strategy requested: {s.title}", client_id=client_id)
    ctx.db.commit()

    def fail(msg):
        s.job_status, s.error, s.status = "failed", msg, "failed"
    _bg(background, run_strategy, s.id, ctx=ctx, on_fail=fail)
    return _out(s, STRAT)


@router.get(f"{P}/marketing/strategies/{{sid}}")
def get_strategy(sid: str, ctx: Ctx = Depends(get_ctx)):
    return _out(get_owned(ctx, MarketingStrategy, sid, "Strategy"), STRAT)


@router.patch(f"{P}/marketing/strategies/{{sid}}")
def edit_strategy(sid: str, body: StrategyPatch, ctx: Ctx = Depends(get_ctx)):
    s = get_owned(ctx, MarketingStrategy, sid, "Strategy")
    if s.job_status != "completed":
        raise HTTPException(409, "The strategy has not finished generating")
    if body.title:
        s.title = body.title.strip()
    if body.sections is not None:
        bad = set(body.sections) - set(SECTIONS)
        if bad:
            raise HTTPException(422, f"Unknown sections: {', '.join(sorted(bad))}")
        merged = dict(s.sections or {})
        for k, v in body.sections.items():
            sec = dict(merged.get(k) or {})
            for f in ("summary", "assumptions", "recommendations"):
                if f in v:
                    sec[f] = v[f] if f == "summary" else [str(x)[:500] for x in (v[f] or [])][:20]
            if guarantee_issues(sec.get("summary", ""), *sec.get("recommendations", [])):
                raise HTTPException(422, "Remove outcome guarantees (e.g. 'guaranteed leads'); the plan cannot promise results")
            sec.pop("missing", None)
            merged[k] = sec
        s.sections = merged
    approval_service.edited(ctx.db, ctx.user, "strategy", s, body.note)
    ctx.db.commit()
    return _out(s, STRAT)


@router.post(f"{P}/marketing/strategies/{{sid}}/review")
def review_strategy(sid: str, body: ReviewIn, ctx: Ctx = Depends(get_ctx)):
    s = get_owned(ctx, MarketingStrategy, sid, "Strategy")
    _review(ctx, "strategy", s, body)
    return _out(s, STRAT)


@router.post(f"{P}/marketing/strategies/{{sid}}/retry")
def retry_strategy(sid: str, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    s = get_owned(ctx, MarketingStrategy, sid, "Strategy")
    if s.job_status != "failed":
        raise HTTPException(409, "Only a failed strategy can be retried")
    _require_ai()
    s.job_status, s.error, s.status = "queued", None, "draft"
    ctx.db.commit()
    _bg(background, run_strategy, s.id)
    return _out(s, STRAT)


@router.delete(f"{P}/marketing/strategies/{{sid}}", status_code=204)
def delete_strategy(sid: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    s = get_owned(ctx, MarketingStrategy, sid, "Strategy")
    log(ctx, "marketing.strategy_deleted", "strategy", s.id, f"Strategy deleted: {s.title}", client_id=s.client_id)
    ctx.db.delete(s)
    ctx.db.commit()


# ------------------------------------------------------------------ budgets
class Line(BaseModel):
    category: str
    cost_kind: str
    amount: float = Field(ge=0)
    note: str | None = Field(default=None, max_length=300)


class BudgetIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    monthly_total: float | None = Field(default=None, ge=0, le=1e11)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    categories: list[str] | None = None
    lines: list[Line] | None = None
    scenario: Literal["base", "conservative", "growth", "custom"] = "base"
    strategy_id: str | None = None
    notes: str | None = Field(default=None, max_length=2000)


class BudgetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    lines: list[Line] | None = None
    quarterly_overrides: dict[str, float] | None = None
    notes: str | None = Field(default=None, max_length=2000)


@router.get(f"{P}/marketing/budget-template")
def budget_template(monthly_total: float = Query(ge=0, le=1e11), categories: str | None = None, ctx: Ctx = Depends(get_ctx)):
    try:
        lines = budget_planner.template_lines(monthly_total, [c for c in (categories or "").split(",") if c] or None)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"lines": lines, "summary": budget_planner.summarise(lines), "labels": budget_planner.LABELS,
            "scenarios": budget_planner.SCENARIOS, "basis": "Planning template shares; adjust them. Not derived from performance data."}


@router.get(f"{P}/clients/{{client_id}}/marketing/budgets")
def list_budgets(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    return [budget_out(b) for b in ctx.db.scalars(scoped(ctx, MarketingBudget).where(MarketingBudget.client_id == client_id)
                                                  .order_by(MarketingBudget.created_at.desc())).all()]


@router.post(f"{P}/clients/{{client_id}}/marketing/budgets", status_code=201)
def create_budget(client_id: str, body: BudgetIn, ctx: Ctx = Depends(get_ctx)):
    client = _client(ctx, client_id)
    try:
        if body.lines is not None:
            lines = budget_planner.clean_lines([ln.model_dump() for ln in body.lines])
        else:
            total = body.monthly_total if body.monthly_total is not None else float(client.marketing_budget or 0)
            if not total:
                raise ValueError("Enter a monthly budget (the client record has none)")
            lines = budget_planner.scenario_lines(budget_planner.template_lines(total, body.categories), body.scenario)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if body.strategy_id:
        st = get_owned(ctx, MarketingStrategy, body.strategy_id, "Strategy")
        if st.client_id != client_id:
            raise HTTPException(400, "Strategy belongs to another client")
    b = MarketingBudget(tenant_id=ctx.tenant_id, client_id=client_id, name=body.name.strip(), strategy_id=body.strategy_id,
                        scenario=body.scenario if body.lines is None else "custom", currency=body.currency.upper(), lines=lines,
                        monthly_total=budget_planner.summarise(lines)["monthly_total"], notes=body.notes, status="draft", created_by=ctx.user.id)
    ctx.db.add(b)
    ctx.db.flush()
    log(ctx, "marketing.budget_created", "budget", b.id, f"Budget created: {b.name}", client_id=client_id)
    ctx.db.commit()
    return budget_out(b)


@router.patch(f"{P}/marketing/budgets/{{bid}}")
def edit_budget(bid: str, body: BudgetPatch, ctx: Ctx = Depends(get_ctx)):
    b = get_owned(ctx, MarketingBudget, bid, "Budget")
    if body.name:
        b.name = body.name.strip()
    if body.currency:
        b.currency = body.currency.upper()
    if body.notes is not None:
        b.notes = body.notes
    if body.lines is not None:
        try:
            b.lines = budget_planner.clean_lines([ln.model_dump() for ln in body.lines])
        except ValueError as e:
            raise HTTPException(422, str(e))
        b.scenario = "custom"
    if body.quarterly_overrides is not None:
        cats = {ln["category"] for ln in b.lines}
        bad = set(body.quarterly_overrides) - cats
        if bad or any(v < 0 for v in body.quarterly_overrides.values()):
            raise HTTPException(422, "Quarterly overrides must be non-negative and for categories in the budget")
        b.quarterly_overrides = body.quarterly_overrides
    b.monthly_total = budget_planner.summarise(b.lines)["monthly_total"]
    approval_service.edited(ctx.db, ctx.user, "budget", b)
    ctx.db.commit()
    return budget_out(b)


@router.post(f"{P}/marketing/budgets/{{bid}}/scenario", status_code=201)
def budget_scenario(bid: str, scenario: Literal["base", "conservative", "growth"], ctx: Ctx = Depends(get_ctx)):
    b = get_owned(ctx, MarketingBudget, bid, "Budget")
    base = [{**ln, "amount": round(ln["amount"] / budget_planner.SCENARIOS.get(b.scenario, 1.0), 2)} for ln in b.lines] \
        if b.scenario in budget_planner.SCENARIOS else b.lines
    lines = budget_planner.scenario_lines(base, scenario)
    n = MarketingBudget(tenant_id=ctx.tenant_id, client_id=b.client_id, name=f"{b.name} ({scenario})", strategy_id=b.strategy_id, scenario=scenario,
                        currency=b.currency, lines=lines, monthly_total=budget_planner.summarise(lines)["monthly_total"], notes=b.notes,
                        status="draft", created_by=ctx.user.id)
    ctx.db.add(n)
    ctx.db.commit()
    return budget_out(n)


@router.post(f"{P}/marketing/budgets/{{bid}}/review")
def review_budget(bid: str, body: ReviewIn, ctx: Ctx = Depends(get_ctx)):
    b = get_owned(ctx, MarketingBudget, bid, "Budget")
    _review(ctx, "budget", b, body)
    return budget_out(b)


@router.delete(f"{P}/marketing/budgets/{{bid}}", status_code=204)
def delete_budget(bid: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    ctx.db.delete(get_owned(ctx, MarketingBudget, bid, "Budget"))
    ctx.db.commit()


# ------------------------------------------------------------------ campaigns
class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    objective: str | None = Field(default=None, max_length=300)
    strategy_id: str | None = None
    budget_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: Literal["planned", "active", "paused", "completed", "archived"] = "planned"


@router.get(f"{P}/clients/{{client_id}}/marketing/campaigns")
def list_campaigns(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    return [_out(c, CAMPAIGN) for c in ctx.db.scalars(scoped(ctx, MarketingCampaign).where(MarketingCampaign.client_id == client_id)
                                                      .order_by(MarketingCampaign.created_at.desc())).all()]


@router.post(f"{P}/clients/{{client_id}}/marketing/campaigns", status_code=201)
def create_campaign(client_id: str, body: CampaignIn, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(422, "End date is before the start date")
    for model, oid in ((MarketingStrategy, body.strategy_id), (MarketingBudget, body.budget_id)):
        if oid and get_owned(ctx, model, oid, "Linked record").client_id != client_id:
            raise HTTPException(400, "Linked record belongs to another client")
    c = MarketingCampaign(tenant_id=ctx.tenant_id, client_id=client_id, created_by=ctx.user.id, **body.model_dump())
    ctx.db.add(c)
    ctx.db.commit()
    return _out(c, CAMPAIGN)


@router.patch(f"{P}/marketing/campaigns/{{cid}}")
def edit_campaign(cid: str, body: CampaignIn, ctx: Ctx = Depends(get_ctx)):
    c = get_owned(ctx, MarketingCampaign, cid, "Campaign")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    ctx.db.commit()
    return _out(c, CAMPAIGN)


@router.delete(f"{P}/marketing/campaigns/{{cid}}", status_code=204)
def delete_campaign(cid: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    ctx.db.delete(get_owned(ctx, MarketingCampaign, cid, "Campaign"))
    ctx.db.commit()


# ------------------------------------------------------------------ content
class GenerateIn(BaseModel):
    studio: Literal["social", "seo"]
    kind: str
    platform: str | None = None
    product_id: str | None = None
    persona_id: str | None = None
    topic: str | None = Field(default=None, max_length=500)
    tone: str | None = Field(default=None, max_length=100)
    count: int = Field(default=1, ge=1, le=5)
    campaign_id: str | None = None


class ContentIn(BaseModel):
    studio: Literal["social", "seo"] = "social"
    kind: str
    platform: str | None = None
    title: str = Field(min_length=2, max_length=300)
    body: str | None = Field(default=None, max_length=60000)
    data: dict = Field(default_factory=dict)
    product_id: str | None = None
    persona_id: str | None = None
    campaign_id: str | None = None
    scheduled_at: datetime | None = None
    assigned_to: str | None = None


class ContentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=300)
    body: str | None = Field(default=None, max_length=60000)
    data: dict | None = None
    kind: str | None = None
    platform: str | None = None
    claims_to_check: list[str] | None = None
    asset_ids: list[str] | None = None
    scheduled_at: datetime | None = None
    clear_schedule: bool = False
    assigned_to: str | None = None
    campaign_id: str | None = None
    note: str | None = Field(default=None, max_length=500)


def _check_links(ctx: Ctx, client_id: str, persona_id=None, campaign_id=None, assigned_to=None):
    if persona_id and get_owned(ctx, BuyerPersona, persona_id, "Buyer profile").client_id != client_id:
        raise HTTPException(400, "Buyer profile belongs to another client")
    if campaign_id and get_owned(ctx, MarketingCampaign, campaign_id, "Campaign").client_id != client_id:
        raise HTTPException(400, "Campaign belongs to another client")
    if assigned_to:
        u = ctx.db.get(User, assigned_to)
        if not u or u.tenant_id != ctx.tenant_id:
            raise HTTPException(400, "Team member not found")


def _clean_data(d: dict) -> dict:
    allowed = {"hashtags", "cta", "slides", "scenes", "creative_brief", "keywords", "outline", "meta_title", "meta_description", "faqs",
               "internal_links", "image_url", "link", "notes"}
    bad = set(d) - allowed
    if bad:
        raise HTTPException(422, f"Unknown content fields: {', '.join(sorted(bad))}")
    if d.get("image_url") and not str(d["image_url"]).startswith("https://"):
        raise HTTPException(422, "image_url must be a public https URL")
    if d.get("link"):
        d["link"] = _url(d["link"])
    return d


@router.post(f"{P}/clients/{{client_id}}/marketing/content/generate", status_code=201)
def generate(client_id: str, body: GenerateIn, ctx: Ctx = Depends(get_ctx)):
    client = _client(ctx, client_id)
    _require_ai("fast" if body.studio == "social" else "analysis")
    _check_links(ctx, client_id, body.persona_id, body.campaign_id)
    try:
        items = generate_content(ctx.db, ctx.tenant_id, client, ctx.user.id, studio=body.studio, kind=body.kind,
                                 platform=body.platform if body.studio == "social" else "website", product_id=body.product_id,
                                 persona_id=body.persona_id, topic=body.topic, count=body.count, tone=body.tone, campaign_id=body.campaign_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except StageError as e:
        raise HTTPException(502, f"The AI provider failed: {e}"[:500])
    log(ctx, "marketing.content_generated", "client", client_id, f"{len(items)} {body.kind.replace('_', ' ')} draft(s) generated",
        client_id=client_id)
    ctx.db.commit()
    return [_out(i, CONTENT) for i in items]


@router.post(f"{P}/clients/{{client_id}}/marketing/content", status_code=201)
def add_content(client_id: str, body: ContentIn, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    kinds = SOCIAL_KINDS if body.studio == "social" else SEO_KINDS
    if body.kind not in kinds:
        raise HTTPException(422, f"kind must be one of {', '.join(sorted(kinds))}")
    if body.studio == "social" and body.platform not in ("instagram", "facebook", "linkedin", "youtube", "youtube_shorts"):
        raise HTTPException(422, "Choose a platform")
    _check_product(ctx, client_id, body.product_id)
    _check_links(ctx, client_id, body.persona_id, body.campaign_id, body.assigned_to)
    if guarantee_issues(body.title, body.body or ""):
        raise HTTPException(422, "Remove outcome guarantees; content cannot promise results")
    it = ContentItem(tenant_id=ctx.tenant_id, client_id=client_id, studio=body.studio, kind=body.kind,
                     platform=body.platform if body.studio == "social" else "website", title=body.title.strip(), body=body.body,
                     data=_clean_data(dict(body.data)), product_id=body.product_id, persona_id=body.persona_id, campaign_id=body.campaign_id,
                     scheduled_at=body.scheduled_at, assigned_to=body.assigned_to, status="draft", origin="user", created_by=ctx.user.id,
                     claims_to_check=detect_claims(f"{body.title}. {body.body or ''}"))
    ctx.db.add(it)
    ctx.db.commit()
    return _out(it, CONTENT)


@router.get(f"{P}/clients/{{client_id}}/marketing/content")
def list_content(client_id: str, ctx: Ctx = Depends(get_ctx), studio: str | None = None, status: str | None = None, platform: str | None = None,
                 campaign_id: str | None = None, limit: int = Query(200, ge=1, le=500)):
    _client(ctx, client_id)
    q = scoped(ctx, ContentItem).where(ContentItem.client_id == client_id)
    for col, v in ((ContentItem.studio, studio), (ContentItem.status, status), (ContentItem.platform, platform), (ContentItem.campaign_id, campaign_id)):
        if v:
            q = q.where(col == v)
    return [_out(i, CONTENT) for i in ctx.db.scalars(q.order_by(ContentItem.created_at.desc()).limit(limit)).all()]


@router.get(f"{P}/marketing/content/{{iid}}")
def get_content(iid: str, ctx: Ctx = Depends(get_ctx)):
    return _out(get_owned(ctx, ContentItem, iid, "Content"), CONTENT)


@router.patch(f"{P}/marketing/content/{{iid}}")
def edit_content(iid: str, body: ContentPatch, ctx: Ctx = Depends(get_ctx)):
    it = get_owned(ctx, ContentItem, iid, "Content")
    if it.status == "published":
        raise HTTPException(409, "Published content cannot be edited; duplicate it instead")
    changes = body.model_dump(exclude_unset=True)
    note = changes.pop("note", None)
    content_fields = {"title", "body", "data", "kind", "platform", "claims_to_check", "asset_ids"}
    _check_links(ctx, it.client_id, None, changes.get("campaign_id"), changes.get("assigned_to"))
    if "asset_ids" in changes:
        assets = ctx.db.scalars(scoped(ctx, ContentAsset).where(ContentAsset.id.in_(changes["asset_ids"] or []))).all()
        if len(assets) != len(set(changes["asset_ids"] or [])) or any(a.client_id != it.client_id for a in assets):
            raise HTTPException(400, "Some assets were not found for this client")
        if any(not a.approved for a in assets):
            raise HTTPException(409, "Only approved brand assets can be attached")
    if "data" in changes:
        changes["data"] = _clean_data(dict(changes["data"] or {}))
    if guarantee_issues(changes.get("title") or "", changes.get("body") or ""):
        raise HTTPException(422, "Remove outcome guarantees; content cannot promise results")
    touched = bool(content_fields & set(changes))
    for k in ("title", "body", "data", "kind", "platform", "claims_to_check", "asset_ids", "assigned_to", "campaign_id"):
        if k in changes:
            setattr(it, k, changes[k])
    if body.clear_schedule:
        it.scheduled_at = None
    elif "scheduled_at" in changes:
        it.scheduled_at = changes["scheduled_at"]
        for j in ctx.db.scalars(select(PublishingJob).where(PublishingJob.content_item_id == it.id, PublishingJob.status == "queued")).all():
            j.scheduled_at = it.scheduled_at  # moving a scheduled post on the calendar keeps its approval
    if touched:
        if "body" in changes or "title" in changes:
            it.claims_to_check = list(dict.fromkeys((changes.get("claims_to_check") if "claims_to_check" in changes else []) +
                                                    detect_claims(f"{it.title}. {it.body or ''}")))
        approval_service.edited(ctx.db, ctx.user, "content", it, note)
    ctx.db.commit()
    return _out(it, CONTENT)


@router.post(f"{P}/marketing/content/{{iid}}/review")
def review_content(iid: str, body: ReviewIn, ctx: Ctx = Depends(get_ctx)):
    it = get_owned(ctx, ContentItem, iid, "Content")
    _review(ctx, "content", it, body)
    return _out(it, CONTENT)


@router.delete(f"{P}/marketing/content/{{iid}}", status_code=204)
def delete_content(iid: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    it = get_owned(ctx, ContentItem, iid, "Content")
    log(ctx, "marketing.content_deleted", "content", it.id, f"Content deleted: {it.title}", client_id=it.client_id)
    ctx.db.delete(it)
    ctx.db.commit()


# ------------------------------------------------------------------ calendar
class CalendarSettings(BaseModel):
    timezone: str = Field(default="Asia/Kolkata", max_length=60)
    require_client_review: bool = False
    default_reviewer_id: str | None = None


def _calendar(ctx: Ctx, client_id: str) -> ContentCalendar:
    cal = ctx.db.scalar(scoped(ctx, ContentCalendar).where(ContentCalendar.client_id == client_id))
    if cal is None:
        cal = ContentCalendar(tenant_id=ctx.tenant_id, client_id=client_id)
        ctx.db.add(cal)
        ctx.db.flush()
    return cal


@router.get(f"{P}/clients/{{client_id}}/marketing/calendar")
def calendar(client_id: str, start: datetime, end: datetime, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    if end <= start or (end - start).days > 400:
        raise HTTPException(422, "Choose a range of up to 400 days")
    q = scoped(ctx, ContentItem).where(ContentItem.client_id == client_id, or_(
        ContentItem.scheduled_at.between(start, end), ContentItem.published_at.between(start, end)))
    cal = _calendar(ctx, client_id)
    ctx.db.commit()
    return {"settings": _out(cal, ["timezone", "require_client_review", "default_reviewer_id"]),
            "items": [_out(i, CONTENT) for i in ctx.db.scalars(q.order_by(ContentItem.scheduled_at)).all()]}


@router.put(f"{P}/clients/{{client_id}}/marketing/calendar/settings")
def calendar_settings(client_id: str, body: CalendarSettings, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    _client(ctx, client_id)
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(body.timezone)
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "Unknown time zone")
    _check_links(ctx, client_id, assigned_to=body.default_reviewer_id)
    cal = _calendar(ctx, client_id)
    cal.timezone, cal.require_client_review, cal.default_reviewer_id = body.timezone, body.require_client_review, body.default_reviewer_id
    ctx.db.commit()
    return _out(cal, ["timezone", "require_client_review", "default_reviewer_id"])


# ------------------------------------------------------------------ brand assets
class AssetIn(BaseModel):
    kind: str
    name: str = Field(min_length=2, max_length=200)
    document_id: str | None = None
    value: str | None = Field(default=None, max_length=300)
    product_id: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)


@router.get(f"{P}/clients/{{client_id}}/marketing/assets")
def list_assets(client_id: str, ctx: Ctx = Depends(get_ctx), kind: str | None = None):
    _client(ctx, client_id)
    q = scoped(ctx, ContentAsset).where(ContentAsset.client_id == client_id)
    if kind:
        q = q.where(ContentAsset.kind == kind)
    return [_out(a, ASSET) for a in ctx.db.scalars(q.order_by(ContentAsset.created_at.desc())).all()]


@router.post(f"{P}/clients/{{client_id}}/marketing/assets", status_code=201)
def add_asset(client_id: str, body: AssetIn, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    if body.document_id:
        d = get_owned(ctx, Document, body.document_id, "Document")
        if d.client_id != client_id:
            raise HTTPException(400, "Document belongs to another client")
    try:
        value = brand_asset_manager.validate(body.kind, body.value, bool(body.document_id))
    except ValueError as e:
        raise HTTPException(422, str(e))
    a = ContentAsset(tenant_id=ctx.tenant_id, client_id=client_id, kind=body.kind, name=body.name.strip(), document_id=body.document_id,
                     value=value, product_id=_check_product(ctx, client_id, body.product_id), tags=[t.strip()[:40] for t in body.tags if t.strip()],
                     notes=body.notes, approved=False, created_by=ctx.user.id)
    ctx.db.add(a)
    ctx.db.commit()
    return _out(a, ASSET)


@router.post(f"{P}/marketing/assets/{{aid}}/approve")
def approve_asset(aid: str, approved: bool = True, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    a = get_owned(ctx, ContentAsset, aid, "Asset")
    a.approved, a.approved_by, a.approved_at = approved, ctx.user.id if approved else None, now() if approved else None
    log(ctx, "marketing.asset_" + ("approved" if approved else "unapproved"), "asset", a.id, f"Brand asset {a.name} {'approved' if approved else 'withdrawn'}",
        client_id=a.client_id)
    ctx.db.commit()
    return _out(a, ASSET)


@router.delete(f"{P}/marketing/assets/{{aid}}", status_code=204)
def delete_asset(aid: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    ctx.db.delete(get_owned(ctx, ContentAsset, aid, "Asset"))
    ctx.db.commit()


# ------------------------------------------------------------------ ad plans
class AdGenerate(BaseModel):
    platform: Literal["meta", "google", "linkedin"]
    product_id: str | None = None
    persona_id: str | None = None
    objective: str | None = Field(default=None, max_length=100)
    geography: list[str] = Field(default_factory=list, max_length=30)
    landing_page: str | None = Field(default=None, max_length=500)
    daily_budget: float | None = Field(default=None, ge=0)
    total_budget: float | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    campaign_id: str | None = None


class AdIn(AdGenerate):
    name: str = Field(min_length=2, max_length=200)
    audience: dict = Field(default_factory=dict)
    creative_brief: str | None = Field(default=None, max_length=3000)
    headlines: list[str] = Field(default_factory=list, max_length=20)
    ad_copy: list[str] = Field(default_factory=list, max_length=10)
    bidding: str | None = Field(default=None, max_length=1000)
    conversion_tracking: str | None = Field(default=None, max_length=1500)
    ab_tests: list[str] = Field(default_factory=list, max_length=10)
    targets: dict = Field(default_factory=dict)


class AdPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    objective: str | None = None
    audience: dict | None = None
    geography: list[str] | None = None
    creative_brief: str | None = None
    headlines: list[str] | None = None
    ad_copy: list[str] | None = None
    landing_page: str | None = None
    daily_budget: float | None = Field(default=None, ge=0)
    total_budget: float | None = Field(default=None, ge=0)
    bidding: str | None = None
    conversion_tracking: str | None = None
    ab_tests: list[str] | None = None
    targets: dict | None = None


class SpendIn(BaseModel):
    approved: bool
    spend_cap: float | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=1000)


@router.get(f"{P}/clients/{{client_id}}/marketing/ad-plans")
def list_ads(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    return [_out(a, AD) for a in ctx.db.scalars(scoped(ctx, AdvertisingCampaign).where(AdvertisingCampaign.client_id == client_id)
                                                .order_by(AdvertisingCampaign.created_at.desc())).all()]


@router.post(f"{P}/clients/{{client_id}}/marketing/ad-plans/generate", status_code=201)
def generate_ad(client_id: str, body: AdGenerate, ctx: Ctx = Depends(get_ctx)):
    client = _client(ctx, client_id)
    _require_ai()
    _check_links(ctx, client_id, body.persona_id, body.campaign_id)
    try:
        ad = ad_campaign_planner.generate(ctx.db, ctx.tenant_id, client, ctx.user.id, platform=body.platform, product_id=body.product_id,
                                          persona_id=body.persona_id, objective=body.objective, geography=body.geography,
                                          landing_page=_url(body.landing_page), daily_budget=body.daily_budget, total_budget=body.total_budget,
                                          currency=body.currency.upper(), campaign_id=body.campaign_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except StageError as e:
        raise HTTPException(502, f"The AI provider failed: {e}"[:500])
    log(ctx, "marketing.ad_plan_generated", "ad_plan", ad.id, f"Ad plan drafted: {ad.name}", client_id=client_id)
    ctx.db.commit()
    return _out(ad, AD)


@router.post(f"{P}/clients/{{client_id}}/marketing/ad-plans", status_code=201)
def add_ad(client_id: str, body: AdIn, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    _check_product(ctx, client_id, body.product_id)
    _check_links(ctx, client_id, body.persona_id, body.campaign_id)
    data = body.model_dump(exclude={"product_id", "persona_id"})
    data["landing_page"], data["currency"] = _url(body.landing_page), body.currency.upper()
    ad = AdvertisingCampaign(tenant_id=ctx.tenant_id, client_id=client_id, status="draft", origin="user", created_by=ctx.user.id,
                             claims_to_check=detect_claims(" ".join(body.headlines + body.ad_copy)), **data)
    ctx.db.add(ad)
    ctx.db.commit()
    return _out(ad, AD)


@router.patch(f"{P}/marketing/ad-plans/{{aid}}")
def edit_ad(aid: str, body: AdPatch, ctx: Ctx = Depends(get_ctx)):
    ad = get_owned(ctx, AdvertisingCampaign, aid, "Ad plan")
    ch = body.model_dump(exclude_unset=True)
    if "landing_page" in ch:
        ch["landing_page"] = _url(ch["landing_page"])
    for k, v in ch.items():
        setattr(ad, k, v)
    if guarantee_issues(*(ad.headlines or []), *(ad.ad_copy or [])):
        raise HTTPException(422, "Remove outcome guarantees from the ad copy")
    approval_service.edited(ctx.db, ctx.user, "ad_plan", ad)
    ctx.db.commit()
    return _out(ad, AD)


@router.post(f"{P}/marketing/ad-plans/{{aid}}/review")
def review_ad(aid: str, body: ReviewIn, ctx: Ctx = Depends(get_ctx)):
    ad = get_owned(ctx, AdvertisingCampaign, aid, "Ad plan")
    _review(ctx, "ad_plan", ad, body)
    return _out(ad, AD)


@router.post(f"{P}/marketing/ad-plans/{{aid}}/spend-approval")
def spend_approval(aid: str, body: SpendIn, ctx: Ctx = Depends(get_ctx)):
    """Records the spend decision only. Nothing is spent: no ad-account adapter exists in this phase."""
    _need(ctx, "admin")
    ad = get_owned(ctx, AdvertisingCampaign, aid, "Ad plan")
    if body.approved:
        if ad.status != "approved":
            raise HTTPException(409, "Approve the ad plan before approving spend")
        if not body.spend_cap:
            raise HTTPException(422, "Set a spend cap")
        if ad.total_budget is not None and body.spend_cap > ad.total_budget:
            raise HTTPException(422, "The spend cap cannot exceed the plan's total budget")
    ad.spend_approved, ad.spend_cap = body.approved, body.spend_cap if body.approved else None
    ad.spend_approved_by, ad.spend_approved_at = (ctx.user.id, now()) if body.approved else (None, None)
    ctx.db.add(ApprovalRequest(tenant_id=ctx.tenant_id, client_id=ad.client_id, entity_type="ad_plan", entity_id=ad.id, stage="spend",
                               status="approved" if body.approved else "rejected", requested_by=ctx.user.id, reviewer_id=ctx.user.id,
                               note=body.note, decided_at=now(), entity_version=ad.version))
    log(ctx, "marketing.spend_" + ("approved" if body.approved else "withdrawn"), "ad_plan", ad.id,
        f"Ad spend {'approved up to ' + f'{body.spend_cap:,.2f} ' + ad.currency if body.approved else 'withdrawn'} for {ad.name}", client_id=ad.client_id)
    ctx.db.commit()
    return {**_out(ad, AD), "note": ad_campaign_planner.ADAPTERS[ad.platform]}


@router.delete(f"{P}/marketing/ad-plans/{{aid}}", status_code=204)
def delete_ad(aid: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    ctx.db.delete(get_owned(ctx, AdvertisingCampaign, aid, "Ad plan"))
    ctx.db.commit()


# ------------------------------------------------------------------ social accounts & OAuth
class ConnectIn(BaseModel):
    platform: Literal["facebook", "instagram", "linkedin"]


@router.get(f"{P}/clients/{{client_id}}/marketing/accounts")
def list_accounts(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    rows = ctx.db.scalars(scoped(ctx, SocialAccount).where(SocialAccount.client_id == client_id, SocialAccount.oauth_state.is_(None))
                          .order_by(SocialAccount.platform)).all()
    return {"accounts": [_out(a, ACCOUNT) for a in rows], "platforms": publishing_service.status()}


@router.post(f"{P}/clients/{{client_id}}/marketing/accounts/connect")
def connect(client_id: str, body: ConnectIn, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    _client(ctx, client_id)
    if not publishing_service.configured(body.platform):
        missing = next(p["missing"] for p in publishing_service.status() if p["platform"] == body.platform)
        raise HTTPException(409, f"{body.platform.title()} is not configured on the server. Set {', '.join(missing)}.")
    state = publishing_service.new_state()
    pend = SocialAccount(tenant_id=ctx.tenant_id, client_id=client_id, platform=body.platform, account_name="(connecting)",
                         status="not_connected", oauth_state=state, connected_by=ctx.user.id)
    ctx.db.add(pend)
    ctx.db.commit()
    return {"authorize_url": publishing_service.authorize_url(body.platform, state)}


@router.get(f"{P}/marketing/oauth/{{provider}}/callback", include_in_schema=True)
def oauth_callback(provider: Literal["meta", "linkedin"], state: str, code: str | None = None, error: str | None = None,
                   db=Depends(get_db)):
    """The provider redirects the browser here. The one-time `state` ties it to the pending connection."""
    pend = db.scalar(select(SocialAccount).where(SocialAccount.oauth_state == state, SocialAccount.status == "not_connected"))
    app_url = get_settings().public_app_url.rstrip("/")
    if pend is None or (now() - pend.created_at.replace(tzinfo=pend.created_at.tzinfo or timezone.utc)).total_seconds() > 900:
        return RedirectResponse(f"{app_url}/clients/?marketing_oauth=expired", status_code=303)
    back = f"{app_url}/clients/view/?id={pend.client_id}&tab=marketing"
    if error or not code:
        db.delete(pend)
        db.commit()
        return RedirectResponse(f"{back}&connected=cancelled", status_code=303)
    try:
        if provider == "meta" and pend.platform in ("facebook", "instagram"):
            made = publishing_service.meta_callback(db, pend, code)
        elif provider == "linkedin" and pend.platform == "linkedin":
            made = publishing_service.linkedin_callback(db, pend, code)
        else:
            raise PublishError("Provider does not match the pending connection")
    except (PublishError, KeyError) as e:
        db.rollback()
        pend = db.scalar(select(SocialAccount).where(SocialAccount.oauth_state == state))
        if pend:
            db.delete(pend)
        db.commit()
        return RedirectResponse(f"{back}&connected=failed&reason={str(e)[:120]}", status_code=303)
    for a in made:
        a.oauth_state = None
    db.commit()
    return RedirectResponse(f"{back}&connected={len(made)}", status_code=303)


@router.post(f"{P}/marketing/accounts/{{acct_id}}/disconnect")
def disconnect(acct_id: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    a = get_owned(ctx, SocialAccount, acct_id, "Account")
    a.token_encrypted, a.status, a.permissions = None, "revoked", {**(a.permissions or {}), "can_publish": False}
    for j in ctx.db.scalars(select(PublishingJob).where(PublishingJob.social_account_id == a.id, PublishingJob.status == "queued")).all():
        j.status, j.error = "cancelled", "Account disconnected"
    log(ctx, "marketing.account_disconnected", "social_account", a.id, f"{a.platform} account {a.account_name} disconnected", client_id=a.client_id)
    ctx.db.commit()
    return _out(a, ACCOUNT)


# ------------------------------------------------------------------ publishing
class PublishIn(BaseModel):
    account_id: str
    scheduled_at: datetime | None = None


class ManualIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    published_at: datetime | None = None


@router.post(f"{P}/marketing/content/{{iid}}/publish")
def publish(iid: str, body: PublishIn, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    it = get_owned(ctx, ContentItem, iid, "Content")
    acct = get_owned(ctx, SocialAccount, body.account_id, "Account")
    if acct.client_id != it.client_id:
        raise HTTPException(400, "The account belongs to another client")
    try:
        publishing_service.check_ready(it, acct)
    except PublishError as e:
        raise HTTPException(409, str(e))
    if ctx.db.scalar(select(PublishingJob).where(PublishingJob.content_item_id == it.id, PublishingJob.status.in_(("queued", "publishing")))):
        raise HTTPException(409, "This item already has a pending publishing job")
    when = body.scheduled_at
    if when is not None:
        when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    job = PublishingJob(tenant_id=ctx.tenant_id, client_id=it.client_id, content_item_id=it.id, social_account_id=acct.id, platform=acct.platform,
                        status="queued", scheduled_at=when, content_version=it.version, requested_by=ctx.user.id)
    ctx.db.add(job)
    future = when is not None and when > now()
    if future:
        it.status, it.publishing_status, it.scheduled_at = "scheduled", "scheduled", when
    log(ctx, "marketing.publish_" + ("scheduled" if future else "requested"), "content", it.id,
        f"'{it.title}' {'scheduled for ' + when.isoformat() if future else 'sent'} to {acct.platform} ({acct.account_name})", client_id=it.client_id)
    ctx.db.commit()
    if not future:
        _bg(background, publishing_service.run_publishing_job, job.id)
    return _out(job, JOB)


@router.post(f"{P}/marketing/content/{{iid}}/mark-published")
def mark_published(iid: str, body: ManualIn, ctx: Ctx = Depends(get_ctx)):
    """For posts the team published itself (e.g. YouTube): records where it went live. Needs an approved item."""
    _need(ctx, "manager")
    it = get_owned(ctx, ContentItem, iid, "Content")
    if it.status not in ("approved", "scheduled") or not it.approved_at:
        raise HTTPException(409, "Only approved content can be marked published")
    url = _url(body.url, True)
    t = body.published_at or now()
    ctx.db.add(PublishingJob(tenant_id=ctx.tenant_id, client_id=it.client_id, content_item_id=it.id, platform=it.platform or "website",
                             status="published", content_version=it.version, requested_by=ctx.user.id, published_at=t, external_url=url))
    it.status, it.publishing_status, it.published_at = "published", "manual", t
    it.data = {**(it.data or {}), "external_url": url}
    log(ctx, "marketing.marked_published", "content", it.id, f"'{it.title}' recorded as published manually", client_id=it.client_id, url=url)
    ctx.db.commit()
    return _out(it, CONTENT)


@router.get(f"{P}/clients/{{client_id}}/marketing/publishing-jobs")
def publishing_jobs(client_id: str, ctx: Ctx = Depends(get_ctx), status: str | None = None):
    _client(ctx, client_id)
    q = scoped(ctx, PublishingJob).where(PublishingJob.client_id == client_id)
    if status:
        q = q.where(PublishingJob.status == status)
    titles = {i.id: i.title for i in ctx.db.scalars(scoped(ctx, ContentItem).where(ContentItem.client_id == client_id)).all()}
    return [{**_out(j, JOB), "title": titles.get(j.content_item_id)} for j in ctx.db.scalars(q.order_by(PublishingJob.created_at.desc()).limit(300)).all()]


@router.post(f"{P}/marketing/publishing-jobs/{{jid}}/cancel")
def cancel_job(jid: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    j = get_owned(ctx, PublishingJob, jid, "Publishing job")
    if j.status != "queued":
        raise HTTPException(409, f"The job is {j.status}")
    j.status, j.error = "cancelled", "Cancelled by a team member"
    it = ctx.db.get(ContentItem, j.content_item_id)
    if it and it.status == "scheduled":
        it.status, it.publishing_status = "approved", "not_scheduled"
    ctx.db.commit()
    return _out(j, JOB)


@router.post(f"{P}/marketing/publishing-jobs/{{jid}}/retry")
def retry_job(jid: str, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    j = get_owned(ctx, PublishingJob, jid, "Publishing job")
    if j.status != "failed":
        raise HTTPException(409, "Only failed jobs can be retried")
    it = ctx.db.get(ContentItem, j.content_item_id)
    if not it or not it.approved_at or it.version != j.content_version:
        raise HTTPException(409, "The content changed after approval; approve it again, then publish")
    it.status = "approved"
    n = PublishingJob(tenant_id=j.tenant_id, client_id=j.client_id, content_item_id=j.content_item_id, social_account_id=j.social_account_id,
                      platform=j.platform, status="queued", content_version=it.version, requested_by=ctx.user.id)
    ctx.db.add(n)
    ctx.db.commit()
    _bg(background, publishing_service.run_publishing_job, n.id)
    return _out(n, JOB)


# ------------------------------------------------------------------ analytics & reports
@router.post(f"{P}/clients/{{client_id}}/marketing/analytics/refresh")
def refresh_analytics(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    res = marketing_analytics.refresh(ctx.db, ctx.tenant_id, client_id)
    ctx.db.commit()
    return res


@router.get(f"{P}/clients/{{client_id}}/marketing/analytics")
def analytics(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    rows = marketing_analytics.latest(ctx.db, ctx.tenant_id, client_id)
    return {"platform": [r for r in rows if r["source"] == "platform"], "calculated": [r for r in rows if r["source"] == "calculated"],
            "not_available": marketing_analytics.UNAVAILABLE}


class ReportIn(BaseModel):
    start: date
    end: date
    title: str | None = Field(default=None, max_length=200)


@router.post(f"{P}/clients/{{client_id}}/marketing/reports", status_code=201)
def create_report(client_id: str, body: ReportIn, ctx: Ctx = Depends(get_ctx)):
    client = _client(ctx, client_id)
    if body.end < body.start:
        raise HTTPException(422, "End date is before the start date")
    md, data = reports.build(ctx.db, ctx.tenant_id, client, body.start, body.end)
    r = MarketingReport(tenant_id=ctx.tenant_id, client_id=client_id, title=body.title or f"Marketing report {body.start:%d %b} – {body.end:%d %b %Y}",
                        period_start=body.start, period_end=body.end, markdown=md, data=data, created_by=ctx.user.id)
    ctx.db.add(r)
    ctx.db.commit()
    return _out(r, ["id", "client_id", "title", "period_start", "period_end", "markdown", "data", "created_at"])


@router.get(f"{P}/clients/{{client_id}}/marketing/reports")
def list_reports(client_id: str, ctx: Ctx = Depends(get_ctx)):
    _client(ctx, client_id)
    return [_out(r, ["id", "client_id", "title", "period_start", "period_end", "data", "created_at"])
            for r in ctx.db.scalars(scoped(ctx, MarketingReport).where(MarketingReport.client_id == client_id).order_by(MarketingReport.created_at.desc())).all()]


@router.get(f"{P}/marketing/reports/{{rid}}/report.md", response_class=PlainTextResponse)
def report_md(rid: str, ctx: Ctx = Depends(get_ctx)):
    return get_owned(ctx, MarketingReport, rid, "Report").markdown


@router.delete(f"{P}/marketing/reports/{{rid}}", status_code=204)
def delete_report(rid: str, ctx: Ctx = Depends(get_ctx)):
    _need(ctx, "manager")
    ctx.db.delete(get_owned(ctx, MarketingReport, rid, "Report"))
    ctx.db.commit()
