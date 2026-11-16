"""Google PageSpeed Insights (free API key). Results are MEASURED values from Lighthouse (lab) and,
when Google has enough real-user data, CrUX field data. Skipped (not faked) when no key is set."""
from __future__ import annotations

import httpx

from app.core.config import get_settings

API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
AUDITS = {"largest-contentful-paint": "lcp_ms", "cumulative-layout-shift": "cls", "total-blocking-time": "tbt_ms",
          "first-contentful-paint": "fcp_ms", "speed-index": "speed_index_ms", "interactive": "tti_ms"}
FIELD = {"LARGEST_CONTENTFUL_PAINT_MS": "lcp_ms", "CUMULATIVE_LAYOUT_SHIFT_SCORE": "cls",
         "INTERACTION_TO_NEXT_PAINT": "inp_ms", "FIRST_CONTENTFUL_PAINT_MS": "fcp_ms"}
THRESHOLDS = {"lcp_ms": (2500, 4000), "cls": (0.1, 0.25), "tbt_ms": (200, 600), "inp_ms": (200, 500)}


def make_client() -> httpx.Client:
    return httpx.Client(timeout=90)


def configured() -> bool:
    return bool(get_settings().pagespeed_api_key)


def measure(url: str, strategy: str, client: httpx.Client | None = None) -> dict:
    own = client is None
    client = client or make_client()
    try:
        params = [("url", url), ("strategy", strategy), ("key", get_settings().pagespeed_api_key)] + \
                 [("category", c) for c in ("performance", "accessibility", "seo", "best-practices")]
        r = client.get(API, params=params)
        if r.status_code >= 400:
            msg = ((r.json() or {}).get("error") or {}).get("message", "") if "json" in r.headers.get("content-type", "") else ""
            return {"strategy": strategy, "error": f"PageSpeed API HTTP {r.status_code} {msg}"[:300]}
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"strategy": strategy, "error": f"PageSpeed request failed: {type(e).__name__}"}
    finally:
        if own:
            client.close()
    lh = data.get("lighthouseResult") or {}
    cats = {k: round((v or {}).get("score") * 100) for k, v in (lh.get("categories") or {}).items()
            if (v or {}).get("score") is not None}
    lab = {}
    for key, name in AUDITS.items():
        val = ((lh.get("audits") or {}).get(key) or {}).get("numericValue")
        if val is not None:
            lab[name] = round(val, 3) if name == "cls" else int(val)
    field = {}
    for key, name in FIELD.items():
        m = ((data.get("loadingExperience") or {}).get("metrics") or {}).get(key)
        if m and m.get("percentile") is not None:
            p = m["percentile"]
            field[name] = {"p75": p / 100 if name == "cls" else p, "category": m.get("category")}
    return {"strategy": strategy, "url": lh.get("finalUrl") or url, "fetched_at": lh.get("fetchTime"),
            "scores": cats, "lab": lab, "field": field or None,
            "source": "Google PageSpeed Insights (Lighthouse lab data; field data from CrUX when available)"}


def findings(result: dict) -> list[tuple[str, str, str, str]]:
    """(check, severity, message, value) for poor measured values."""
    out = []
    if result.get("error"):
        return out
    s, perf = result["strategy"], result.get("scores", {}).get("performance")
    if perf is not None and perf < 90:
        out.append((f"psi_performance_{s}", "high" if perf < 50 else "medium", f"PageSpeed performance score ({s}) is {perf}/100.", str(perf)))
    for name, (good, poor) in THRESHOLDS.items():
        v = result.get("lab", {}).get(name)
        if v is None:
            continue
        if v > good:
            label = name.replace("_ms", "").upper()
            unit = "" if name == "cls" else " ms"
            out.append((f"psi_{name}_{s}", "high" if v > poor else "medium", f"{label} ({s}, lab) is {v}{unit}; good is ≤ {good}{unit}.", str(v)))
    return out
