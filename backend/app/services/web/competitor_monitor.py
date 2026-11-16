"""Change detection between consecutive competitor snapshots. Each change records the old value, the
new value, the source URL and the observation date. A page counts as removed only when it now returns
404/410, or the new crawl was complete (not cut off by the page limit) and the page is gone."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Competitor, CompetitorChange, CompetitorSnapshot, CrawlJob, Website


def _names(items: list[dict], key: str = "name") -> dict:
    return {i[key]: i.get("url") for i in items or [] if i.get(key)}


def diff(prev: CompetitorSnapshot, cur: CompetitorSnapshot) -> list[dict]:
    out: list[dict] = []

    def add(t, url, old, new):
        out.append({"change_type": t, "url": url, "old_value": None if old is None else str(old)[:2000],
                    "new_value": None if new is None else str(new)[:2000]})

    pp, cp = prev.pages or {}, cur.pages or {}
    live = lambda d: {u: v for u, v in d.items() if (v.get("status") or 200) < 400}  # noqa: E731
    lp, lc = live(pp), live(cp)
    complete = not (cur.seo or {}).get("limit_reached")
    prev_complete = not (prev.seo or {}).get("limit_reached")
    for u in lc.keys() - lp.keys():
        if pp.get(u, {}).get("status") in (404, 410) or (u not in pp and prev_complete):
            add("page_added", u, None, lc[u].get("title") or u)
    for u in lp.keys() - lc.keys():
        if cp.get(u, {}).get("status") in (404, 410) or complete:
            add("page_removed", u, lp[u].get("title") or u, None)
    for u in lp.keys() & lc.keys():
        a, b = lp[u], lc[u]
        if (a.get("title") or "") != (b.get("title") or ""):
            add("title_changed", u, a.get("title"), b.get("title"))
        if (a.get("description") or "") != (b.get("description") or ""):
            add("description_changed", u, a.get("description"), b.get("description"))
        if set(a.get("prices") or []) != set(b.get("prices") or []):
            add("price_changed", u, "; ".join(a.get("prices") or []) or None, "; ".join(b.get("prices") or []) or None)
        new_promos = set(b.get("promotions") or []) - set(a.get("promotions") or [])
        for pr in new_promos:
            add("promotion_added", u, None, pr)
    ph, ch = prev.homepage or {}, cur.homepage or {}
    if (ph.get("h1") or "") != (ch.get("h1") or "") and (ph or ch):
        add("homepage_messaging", ch.get("url") or ph.get("url"), ph.get("h1"), ch.get("h1"))
    for kind, a, b in (("product", _names(prev.products), _names(cur.products)),
                       ("certification", _names(prev.certifications), _names(cur.certifications)),
                       ("location", _names(prev.locations), _names(cur.locations))):
        for n in b.keys() - a.keys():
            add(f"{kind}_added", b[n], None, n)
        for n in a.keys() - b.keys():
            if complete:
                add(f"{kind}_removed", a[n], n, None)
    pc, cc = prev.contact or {}, cur.contact or {}
    if (sorted(pc.get("emails") or []), sorted(pc.get("phones") or [])) != (sorted(cc.get("emails") or []), sorted(cc.get("phones") or [])) \
            and (cc.get("emails") or cc.get("phones")):
        add("contact_changed", cc.get("url") or pc.get("url"),
            ", ".join((pc.get("emails") or []) + (pc.get("phones") or [])) or None,
            ", ".join((cc.get("emails") or []) + (cc.get("phones") or [])) or None)
    return out


def run(db, snap: CompetitorSnapshot) -> int:
    prev = db.scalar(select(CompetitorSnapshot).where(
        CompetitorSnapshot.tenant_id == snap.tenant_id, CompetitorSnapshot.competitor_id == snap.competitor_id,
        CompetitorSnapshot.id != snap.id, CompetitorSnapshot.captured_at <= snap.captured_at)
        .order_by(CompetitorSnapshot.captured_at.desc()).limit(1))
    if prev is None:
        return 0
    changes = diff(prev, snap)
    for c in changes:
        db.add(CompetitorChange(tenant_id=snap.tenant_id, client_id=snap.client_id, competitor_id=snap.competitor_id,
                                snapshot_id=snap.id, previous_snapshot_id=prev.id, observed_at=snap.captured_at, **c))
    db.flush()
    return len(changes)


def due_jobs(db, now: datetime | None = None) -> list[CrawlJob]:
    """Create scheduled crawl jobs for competitors and client sites whose interval has passed.
    Call from cron or an RQ scheduler: `python -m app.services.web.scheduler`."""
    now = now or datetime.now(timezone.utc)
    jobs = []
    busy = {j.website_id for j in db.scalars(select(CrawlJob).where(CrawlJob.status.in_(("queued", "running")))).all()}
    for site in db.scalars(select(Website)).all():
        comp = db.get(Competitor, site.competitor_id) if site.competitor_id else None
        interval = comp.monitor_interval_days if comp else site.crawl_interval_days
        if not interval or site.id in busy or (comp and comp.status != "active"):
            continue
        last = site.last_crawled_at
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last and now - last < timedelta(days=interval):
            continue
        job = CrawlJob(tenant_id=site.tenant_id, client_id=site.client_id, website_id=site.id,
                       competitor_id=site.competitor_id, kind="competitor" if comp else "audit", trigger="scheduled",
                       config=site.crawl_config or {})
        db.add(job)
        jobs.append(job)
    db.commit()
    return jobs
