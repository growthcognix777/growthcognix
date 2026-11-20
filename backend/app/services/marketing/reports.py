"""Client marketing report, composed only from stored records (no estimates)."""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import select

from app.models import AdvertisingCampaign, Client, ContentItem, MarketingBudget, MarketingStrategy, PublishingJob
from app.services.marketing import marketing_analytics
from app.services.marketing.budget_planner import LABELS, summarise


def _in(d: datetime | None, start: date, end: date) -> bool:
    if not d:
        return False
    d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime.combine(start, time.min, timezone.utc) <= d <= datetime.combine(end, time.max, timezone.utc)


def build(db, tenant_id: str, client: Client, start: date, end: date) -> tuple[str, dict]:
    items = db.scalars(select(ContentItem).where(ContentItem.tenant_id == tenant_id, ContentItem.client_id == client.id)).all()
    by_status: dict[str, int] = {}
    for i in items:
        by_status[i.status] = by_status.get(i.status, 0) + 1
    published = [i for i in items if i.status == "published" and _in(i.published_at, start, end)]
    scheduled = [i for i in items if i.status == "scheduled" and i.scheduled_at]
    jobs = db.scalars(select(PublishingJob).where(PublishingJob.client_id == client.id)).all()
    failed = [j for j in jobs if j.status == "failed" and _in(j.updated_at, start, end)]
    strat = db.scalar(select(MarketingStrategy).where(MarketingStrategy.client_id == client.id, MarketingStrategy.status == "approved")
                      .order_by(MarketingStrategy.approved_at.desc()).limit(1))
    budget = db.scalar(select(MarketingBudget).where(MarketingBudget.client_id == client.id, MarketingBudget.status == "approved")
                       .order_by(MarketingBudget.approved_at.desc()).limit(1))
    ads = db.scalars(select(AdvertisingCampaign).where(AdvertisingCampaign.client_id == client.id)).all()
    metrics = marketing_analytics.latest(db, tenant_id, client.id)
    L = [f"# Marketing report — {client.company_name}", f"Period: {start.isoformat()} to {end.isoformat()}", "",
         "Everything below comes from GrowthCognix records and connected platform APIs. Values that are not connected are shown as —.", ""]
    L += ["## Strategy", f"Approved strategy: {strat.title} (approved {strat.approved_at:%d %b %Y})" if strat else "No approved strategy yet.", ""]
    L += ["## Budget"]
    if budget:
        s = summarise(budget.lines, budget.quarterly_overrides)
        L += [f"Approved budget: {budget.name}, {s['monthly_total']:,.2f} {budget.currency} per month "
              f"(ad spend {s['by_cost_kind']['ad_spend']:,.2f}, agency fees {s['by_cost_kind']['agency_fee']:,.2f}, production {s['by_cost_kind']['production']:,.2f})."]
        L += [f"- {LABELS.get(k, k)}: {v:,.2f}" for k, v in s["by_category"].items()]
    else:
        L += ["No approved budget yet."]
    L += ["", "## Content", "Status | Items", "--- | ---"] + [f"{k.replace('_', ' ')} | {v}" for k, v in sorted(by_status.items())]
    L += ["", f"Published in this period: {len(published)}"] + [
        f"- {i.published_at:%d %b} {i.platform}: {i.title}" + (f" ({(i.data or {}).get('external_url')})" if (i.data or {}).get("external_url") else "")
        for i in sorted(published, key=lambda x: x.published_at)]
    L += [f"Scheduled: {len(scheduled)}", f"Publishing failures in this period: {len(failed)}", ""]
    L += ["## Platform metrics (reported by the platform)"]
    plat = [m for m in metrics if m["source"] == "platform"]
    L += ([f"- {m['platform']} · {m['title'] or m['external_id']}: {m['metric']} {m['value']:g} (retrieved {m['retrieved_at']:%d %b %Y})" for m in plat]
          or ["— No connected platform has reported metrics yet."])
    L += ["", "## Calculated by GrowthCognix"]
    calc = [m for m in metrics if m["source"] == "calculated"]
    L += [f"- {m['platform']} · {m['title'] or m['external_id']}: {m['metric']} {m['value']:g} = {m['formula']}" for m in calc] or ["—"]
    L += ["", "## Not available", *[f"- {v}" for v in marketing_analytics.UNAVAILABLE.values()], ""]
    L += ["## Ad plans (plans only; nothing is launched from GrowthCognix)"]
    L += [f"- {a.platform}: {a.name} — {a.status.replace('_', ' ')}; spend {'approved up to ' + f'{a.spend_cap:,.2f} ' + a.currency if a.spend_approved else 'not approved'}"
          for a in ads] or ["None."]
    data = {"content_by_status": by_status, "published": len(published), "scheduled": len(scheduled), "failed": len(failed),
            "metrics": len(metrics), "ad_plans": len(ads)}
    return "\n".join(L) + "\n", data
