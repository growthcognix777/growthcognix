"""Approval workflow shared by strategies, budgets, content items and ad plans.

  draft / ai_generated / rejected --submit--> internal_review
  internal_review --approve (manager+)--> approved, or client_review when client review is required
  internal_review --send_to_client--> client_review
  client_review --client_approve (manager+, records the client contact's name)--> approved
  internal_review / client_review --reject--> rejected ; --request_changes--> draft
  approved --schedule--> scheduled ; scheduled --unschedule--> approved   (content only, via publishing)
  scheduled / approved --> published | failed                            (publishing service only)

Editing an approved or scheduled item sends it back to internal_review (new version, revision saved, pending
publishing jobs cancelled). Nothing reaches `published` except through the publishing service, which only
accepts approved or scheduled items whose approved version is the current one.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select

from app.models import AdvertisingCampaign, ApprovalRequest, ContentCalendar, ContentItem, MarketingBudget, MarketingStrategy, PublishingJob
from app.services.marketing.common import now, record_revision

MODELS = {"strategy": MarketingStrategy, "budget": MarketingBudget, "content": ContentItem, "ad_plan": AdvertisingCampaign}
FIELDS = {
    "strategy": ["title", "sections", "status"],
    "budget": ["name", "scenario", "currency", "lines", "quarterly_overrides", "monthly_total", "status"],
    "content": ["title", "body", "data", "kind", "platform", "claims_to_check", "asset_ids", "scheduled_at", "status"],
    "ad_plan": ["name", "objective", "audience", "geography", "creative_brief", "headlines", "ad_copy", "landing_page",
                "daily_budget", "total_budget", "bidding", "conversion_tracking", "ab_tests", "targets", "status"],
}
RANK = {"staff": 0, "manager": 1, "admin": 2, "owner": 3}
ACTIONS = {
    "submit": ({"draft", "ai_generated", "rejected", "failed"}, "staff"),
    "approve": ({"internal_review"}, "manager"),
    "send_to_client": ({"internal_review"}, "manager"),
    "client_approve": ({"client_review"}, "manager"),
    "reject": ({"internal_review", "client_review"}, "manager"),
    "request_changes": ({"internal_review", "client_review"}, "manager"),
}


def _pending(db, entity_type: str, obj) -> ApprovalRequest | None:
    return db.scalar(select(ApprovalRequest).where(ApprovalRequest.entity_type == entity_type, ApprovalRequest.entity_id == obj.id,
                                                   ApprovalRequest.status == "pending").order_by(ApprovalRequest.created_at.desc()).limit(1))


def needs_client_review(db, client_id: str) -> bool:
    cal = db.scalar(select(ContentCalendar).where(ContentCalendar.client_id == client_id))
    return bool(cal and cal.require_client_review)


def act(db, user, entity_type: str, obj, action: str, note: str | None = None, reviewer_name: str | None = None) -> None:
    if action not in ACTIONS:
        raise HTTPException(422, f"Unknown action {action}")
    allowed, role = ACTIONS[action]
    if RANK[user.role] < RANK[role]:
        raise HTTPException(403, f"Requires {role} role or higher")
    if obj.status not in allowed:
        raise HTTPException(409, f"Cannot {action.replace('_', ' ')} an item that is {obj.status.replace('_', ' ')}")
    if entity_type == "strategy" and getattr(obj, "job_status", "completed") != "completed":
        raise HTTPException(409, "The strategy has not finished generating")
    if entity_type == "content" and action in ("approve", "client_approve") and obj.claims_to_check and not (note or "").strip():
        raise HTTPException(422, "This draft has claims to fact-check. Add a note saying they were checked (or edit them out) before approving.")
    pend = _pending(db, entity_type, obj)
    t = now()
    if action == "submit":
        if pend:
            pend.status = "cancelled"
        db.add(ApprovalRequest(tenant_id=obj.tenant_id, client_id=obj.client_id, entity_type=entity_type, entity_id=obj.id,
                               stage="internal_review", requested_by=user.id, note=note, entity_version=obj.version))
        obj.status = "internal_review"
        return
    if pend is None:  # e.g. items created before an approval row existed
        pend = ApprovalRequest(tenant_id=obj.tenant_id, client_id=obj.client_id, entity_type=entity_type, entity_id=obj.id,
                               stage=obj.status, requested_by=obj.created_by, entity_version=obj.version)
        db.add(pend)
    pend.reviewer_id, pend.note, pend.decided_at = user.id, note, t
    obj.reviewed_by, obj.reviewed_at = user.id, t
    if action in ("approve", "client_approve"):
        if action == "client_approve":
            if not (reviewer_name or "").strip():
                raise HTTPException(422, "Record who at the client approved it")
            pend.reviewer_name = reviewer_name.strip()[:200]
        pend.status = "approved"
        if action == "approve" and needs_client_review(db, obj.client_id):
            obj.status = "client_review"
            db.add(ApprovalRequest(tenant_id=obj.tenant_id, client_id=obj.client_id, entity_type=entity_type, entity_id=obj.id,
                                   stage="client_review", requested_by=user.id, entity_version=obj.version))
        else:
            obj.status, obj.approved_by, obj.approved_at = "approved", user.id, t
    elif action == "send_to_client":
        pend.status = "approved"
        obj.status = "client_review"
        db.add(ApprovalRequest(tenant_id=obj.tenant_id, client_id=obj.client_id, entity_type=entity_type, entity_id=obj.id,
                               stage="client_review", requested_by=user.id, entity_version=obj.version))
    elif action == "reject":
        pend.status, obj.status = "rejected", "rejected"
    else:
        pend.status, obj.status = "changes_requested", "draft"


def edited(db, user, entity_type: str, obj, note: str | None = None) -> None:
    """Call after changing an entity's content. Saves a revision; an approved/scheduled item goes back to review."""
    obj.version = (obj.version or 1) + 1
    record_revision(db, obj.tenant_id, entity_type, obj, FIELDS[entity_type], user.id, note or "Edited")
    if obj.status in ("approved", "scheduled", "client_review", "internal_review"):
        was = obj.status
        obj.status, obj.approved_by, obj.approved_at = "internal_review", None, None
        for a in db.scalars(select(ApprovalRequest).where(ApprovalRequest.entity_type == entity_type, ApprovalRequest.entity_id == obj.id,
                                                          ApprovalRequest.status == "pending")).all():
            a.status = "cancelled"
        db.add(ApprovalRequest(tenant_id=obj.tenant_id, client_id=obj.client_id, entity_type=entity_type, entity_id=obj.id,
                               stage="internal_review", requested_by=user.id, entity_version=obj.version,
                               note=f"Edited while {was.replace('_', ' ')}; needs approval again"))
        if entity_type == "content":
            for j in db.scalars(select(PublishingJob).where(PublishingJob.content_item_id == obj.id, PublishingJob.status == "queued")).all():
                j.status, j.error = "cancelled", "Content changed after approval"
            obj.publishing_status = "not_scheduled"
        if entity_type == "ad_plan":
            obj.spend_approved, obj.spend_approved_by, obj.spend_approved_at = False, None, None
