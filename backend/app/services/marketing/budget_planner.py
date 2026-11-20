"""Marketing budget planner. Deterministic: no AI, no invented benchmarks.

The team gives a monthly total; a planning template splits it across categories and cost kinds (proposed ad
spend vs agency fees vs production costs). Every line stays editable. Scenarios scale the total (conservative
0.7x, growth 1.4x) or keep the team's own lines (custom). The template percentages are a starting point the
team adjusts, not a recommendation derived from data.
"""
from __future__ import annotations

from app.models.marketing import BUDGET_CATEGORIES, COST_KINDS

# category -> (share of monthly total, cost kind)
TEMPLATE: dict[str, tuple[float, str]] = {
    "seo": (0.15, "agency_fee"),
    "social_media": (0.15, "agency_fee"),
    "content_production": (0.12, "production"),
    "paid_search": (0.20, "ad_spend"),
    "social_ads": (0.15, "ad_spend"),
    "video_production": (0.08, "production"),
    "email_marketing": (0.05, "agency_fee"),
    "agency_services": (0.10, "agency_fee"),
}
SCENARIOS = {"base": 1.0, "conservative": 0.7, "growth": 1.4}
LABELS = {"seo": "SEO", "social_media": "Social media management", "content_production": "Content production",
          "paid_search": "Paid search (Google Ads)", "social_ads": "Social ads (Meta / LinkedIn)", "video_production": "Video production",
          "email_marketing": "Email marketing", "agency_services": "Agency services & reporting"}


def template_lines(monthly_total: float, categories: list[str] | None = None) -> list[dict]:
    cats = [c for c in (categories or BUDGET_CATEGORIES) if c in TEMPLATE]
    if not cats:
        raise ValueError("Choose at least one budget category")
    share = sum(TEMPLATE[c][0] for c in cats)
    lines, left = [], round(monthly_total, 2)
    for i, c in enumerate(cats):
        amt = round(monthly_total * TEMPLATE[c][0] / share, 2) if i < len(cats) - 1 else round(left, 2)
        left -= amt
        lines.append({"category": c, "cost_kind": TEMPLATE[c][1], "amount": amt, "note": "Template share; adjust"})
    return lines


def clean_lines(lines: list[dict]) -> list[dict]:
    out = []
    for ln in lines:
        c, k = ln.get("category"), ln.get("cost_kind")
        if c not in BUDGET_CATEGORIES:
            raise ValueError(f"Unknown category: {c}")
        if k not in COST_KINDS:
            raise ValueError(f"cost_kind must be one of {', '.join(COST_KINDS)}")
        try:
            amt = round(float(ln.get("amount") or 0), 2)
        except (TypeError, ValueError):
            raise ValueError(f"Amount for {c} must be a number")
        if amt < 0:
            raise ValueError("Amounts cannot be negative")
        out.append({"category": c, "cost_kind": k, "amount": amt, "note": (ln.get("note") or "")[:300] or None})
    if len(out) > 40:
        raise ValueError("Too many lines")
    return out


def scenario_lines(lines: list[dict], scenario: str) -> list[dict]:
    m = SCENARIOS.get(scenario)
    if m is None:
        return lines
    return [{**ln, "amount": round(ln["amount"] * m, 2)} for ln in lines]


def summarise(lines: list[dict], quarterly_overrides: dict | None = None) -> dict:
    monthly = round(sum(ln["amount"] for ln in lines), 2)
    by_kind = {k: round(sum(ln["amount"] for ln in lines if ln["cost_kind"] == k), 2) for k in COST_KINDS}
    by_cat: dict[str, float] = {}
    for ln in lines:
        by_cat[ln["category"]] = round(by_cat.get(ln["category"], 0) + ln["amount"], 2)
    q = {c: round(float((quarterly_overrides or {}).get(c, v * 3)), 2) for c, v in by_cat.items()}
    return {"monthly_total": monthly, "quarterly_total": round(sum(q.values()), 2), "by_cost_kind": by_kind,
            "by_category": by_cat, "quarterly_by_category": q,
            "share": {c: (round(100 * v / monthly, 1) if monthly else 0) for c, v in by_cat.items()}}
