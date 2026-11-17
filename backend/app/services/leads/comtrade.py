"""UN Comtrade trade statistics (historical, annual).

Public preview API: no key, at most 500 rows per call, one period per call, about 1 request/second (429 when
faster). With COMTRADE_API_KEY the free subscription endpoint is used instead. Figures are *historical trade
flows reported by countries*; they are stored as kind="historical_trade" and never presented as current demand
or obtainable revenue.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.core.config import get_settings
from app.models import TradeMarketInsight
from app.services.leads import geo
from app.services.leads.providers import ProviderFailure, _get_json

PREVIEW = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
SUBSCRIBED = "https://comtradeapi.un.org/data/v1/get/C/A/HS"


def fetch(hs_code: str, reporter: str, period: str, flow: str = "M", partner: str | None = None) -> list[dict]:
    if not re.fullmatch(r"\d{2,6}", hs_code or ""):
        raise ValueError("HS code must be 2 to 6 digits")
    if not re.fullmatch(r"\d{4}", period or ""):
        raise ValueError("Period must be a year, e.g. 2023")
    if flow not in ("M", "X"):
        raise ValueError("Flow must be M (imports) or X (exports)")
    rc = geo.comtrade_code(reporter)
    if rc is None:
        raise ValueError(f"Unknown reporter country: {reporter}")
    pc = 0 if not partner else geo.comtrade_code(partner)
    if pc is None:
        raise ValueError(f"Unknown partner country: {partner}")
    key = get_settings().comtrade_api_key
    params = {"reporterCode": rc, "period": period, "cmdCode": hs_code, "flowCode": flow, "partnerCode": pc}
    data = _get_json(SUBSCRIBED if key else PREVIEW, params, {"Ocp-Apim-Subscription-Key": key} if key else None)
    if data.get("error"):
        raise ProviderFailure(f"UN Comtrade: {data['error']}"[:300], retryable=False)
    return list(data.get("data") or [])[:500]


def save(db, tenant_id: str, client_id: str, user_id: str | None, product_id: str | None, hs_code: str, reporter: str,
         period: str, flow: str = "M", partner: str | None = None) -> list[TradeMarketInsight]:
    rows = fetch(hs_code, reporter, period, flow, partner)
    now = datetime.now(timezone.utc)
    src = f"{PREVIEW}?reporterCode={geo.comtrade_code(reporter)}&period={period}&cmdCode={hs_code}&flowCode={flow}&partnerCode={0 if not partner else geo.comtrade_code(partner)}"
    out = []
    for r in rows:
        value = r.get("primaryValue")
        qty = r.get("qty") or None
        unit = r.get("qtyUnitAbbr")
        ins = TradeMarketInsight(tenant_id=tenant_id, client_id=client_id, product_id=product_id, kind="historical_trade",
                                 hs_code=str(r.get("cmdCode") or hs_code), reporter=geo.country_name(reporter) or reporter,
                                 partner=(geo.country_name(partner) or partner) if partner else "World",
                                 flow="import" if (r.get("flowCode") or flow) == "M" else "export", period=str(r.get("period") or period),
                                 value_usd=float(value) if value is not None else None, quantity=float(qty) if qty else None,
                                 quantity_unit=unit if qty else None,
                                 title=f"HS {hs_code} {'imports' if flow == 'M' else 'exports'} reported by {geo.country_name(reporter) or reporter}, {period}",
                                 detail=("Historical annual trade flow reported to UN Comtrade (USD). Not current demand or revenue a client can win."
                                         + (" Values estimated by UN Comtrade." if r.get("isReported") is False else "")),
                                 source="un_comtrade", source_url=src[:500], retrieved_at=now, created_by=user_id)
        db.add(ins)
        out.append(ins)
    db.flush()
    return out
