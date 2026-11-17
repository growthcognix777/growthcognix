"""Configurable 100-point lead score with a separate evidence-confidence score.

Default weights: fit 30, need 25, intent & timing 20, capacity 15, contact quality 10. Each component
earns a share of its weight from observations on the company's own site and from human verifications.
Search or directory appearance alone earns nothing. Intent stays at 0 unless there is real evidence:
a tender / RFQ / procurement notice / explicit supplier request on the site, an observable expansion
signal, or intent evidence a person added with a source URL. Every point has a written reason.
"""
from __future__ import annotations

from datetime import datetime, timezone

DEFAULT_WEIGHTS = {"fit": 30, "need": 25, "intent": 20, "capacity": 15, "contact": 10}
CLASSES = [(80, "very_high"), (65, "high"), (40, "medium"), (0, "low")]
VERSION = "v1"


def classify(total: int) -> str:
    return next(c for t, c in CLASSES if total >= t)


def normalise_weights(w: dict | None) -> dict:
    w = {k: int((w or {}).get(k, DEFAULT_WEIGHTS[k])) for k in DEFAULT_WEIGHTS}
    if any(v < 0 for v in w.values()) or sum(w.values()) != 100:
        raise ValueError("Weights must be non-negative and add up to 100")
    return w


def _aware(d):
    if d and d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d


def compute(prospect, contacts: list, user_evidence: list, weights: dict | None = None) -> dict:
    """prospect: ProspectCompany; contacts: BusinessContact rows; user_evidence: EvidenceSource rows a person added
    (field in intent|need|capacity|fit). Returns {total, score_class, confidence, components, weights, explanation}."""
    w = normalise_weights(weights)
    v = prospect.verified_fields or {}
    sig = prospect.signals or {}
    terms = [t for t in (sig.get("matched_terms") or []) if t.get("kind", "fit") == "fit"]
    need_terms = [t for t in (sig.get("matched_terms") or []) if t.get("kind") == "need"]
    intent = sig.get("intent") or []
    capacity = sig.get("capacity") or []
    uev = {f: [e for e in user_evidence if e.field == f] for f in ("intent", "need", "capacity", "fit")}
    comps, why = {}, []

    def part(key: str, frac: float, reasons: list[str]):
        frac = max(0.0, min(1.0, frac))
        pts = round(w[key] * frac)
        comps[key] = {"points": pts, "max": w[key], "reasons": reasons or ["No supporting evidence yet"]}

    # Product & industry fit
    r, f = [], 0.0
    if "product_relevance" in v:
        f = 1.0
        r.append("Product relevance verified by a person")
    elif "industry" in v:
        f = 0.7
        r.append("Industry verified by a person")
    if f < 1.0 and terms:
        add = min(0.5, 0.17 * len(terms))
        f = max(f, add) if f == 0 else min(1.0, f + add / 2)
        r.append(f"Its site mentions {len(terms)} relevant application/industry term(s): " + ", ".join(t["term"] for t in terms[:4]))
    if uev["fit"]:
        f = max(f, 0.5)
        r.append(f"{len(uev['fit'])} fit evidence item(s) added by the team")
    if not r:
        r.append("No fit evidence beyond appearing in a search or directory")
    part("fit", f, r)

    # Relevant business need
    r, f = [], 0.0
    if "product_relevance" in v:
        f += 0.5
        r.append("A person confirmed the product meets a need this company has")
    if need_terms:
        f += min(0.5, 0.2 * len(need_terms))
        r.append(f"Its site describes {len(need_terms)} problem(s) the product addresses: " + ", ".join(t["term"] for t in need_terms[:3]))
    if uev["need"]:
        f += 0.3
        r.append(f"{len(uev['need'])} need evidence item(s) added by the team")
    part("need", f, r)

    # Buying intent & timing: real evidence only
    strong = [i for i in intent if i.get("strength") == "strong"]
    timing = [i for i in intent if i.get("strength") == "timing"]
    r, f = [], 0.0
    if strong:
        f += 0.5 * min(2, len(strong))
        r.append("Buying signal on its site: " + "; ".join(i["signal"] for i in strong[:2]))
    if timing:
        f += 0.25
        r.append("Timing signal on its site: " + timing[0]["signal"])
    if uev["intent"]:
        f += 0.5 * min(2, len(uev["intent"]))
        r.append(f"{len(uev['intent'])} intent evidence item(s) with a source URL (e.g. tender, enquiry)")
    if not r:
        r.append("No observable buying signal (tender, RFQ, procurement notice or explicit request), so intent scores 0")
    part("intent", f, r)

    # Purchase capacity
    r, f = [], 0.0
    if capacity:
        f += min(0.7, 0.25 * len(capacity))
        r.append("Capacity signals on its site: " + ", ".join(c["value"] for c in capacity[:3]))
    if "company" in v:
        f += 0.3
        r.append("Company verified by a person")
    if uev["capacity"]:
        f += 0.3
        r.append(f"{len(uev['capacity'])} capacity evidence item(s) added by the team")
    part("capacity", f, r)

    # Contact quality
    active = [c for c in contacts if not getattr(c, "suppressed", False)]
    r, f = [], 0.0
    if any(c.kind == "person" and c.verified for c in active):
        f = 1.0
        r.append("Verified business decision-maker with a public source")
    else:
        if any(c.kind == "role_email" for c in active):
            f += 0.4
            r.append("Role email published on its site")
        if any(c.kind == "phone" for c in active):
            f += 0.3
            r.append("Business phone published on its site")
        if "contact" in v:
            f += 0.3
            r.append("Contact details verified by a person")
    part("contact", f, r)

    total = sum(c["points"] for c in comps.values())
    for k in ("fit", "need", "intent", "capacity", "contact"):
        why.append(f"{k.title()} {comps[k]['points']}/{comps[k]['max']}: {comps[k]['reasons'][0]}")

    # Evidence confidence: how much of the above rests on fresh, independent, human-checked evidence.
    conf = 0.0
    if prospect.site_status == "ok":
        conf += 0.2
    conf += 0.12 * len([k for k in ("company", "website", "industry", "product_relevance", "contact") if k in v])
    if len(prospect.providers or []) >= 2:
        conf += 0.1
    if terms or need_terms:
        conf += 0.05
    if user_evidence:
        conf += 0.05
    last = _aware(prospect.last_verified_at or prospect.site_checked_at)
    if last and (datetime.now(timezone.utc) - last).days > 180:
        conf *= 0.6
        why.append("Confidence reduced: last verified more than 180 days ago")
    if prospect.verification_status == "rejected":
        conf = 0.0
    conf = round(min(1.0, conf), 2)
    return {"total": total, "score_class": classify(total), "confidence": conf, "components": comps, "weights": w,
            "explanation": why, "version": VERSION}
