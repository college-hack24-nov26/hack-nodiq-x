#!/usr/bin/env python3
"""
services/morphology.py — graphite form classification (Advancement).

Classifies the detected particle population into ISO 945 graphite forms:

    I   flake/lamellar (grey iron)          — very irregular, low solidity
    II  interdendritic flake                — fine, spidery (clustered areas)
    III vermicular/compacted (CGI)          — elongated, moderate roundness
    IV temper/cumple carbonate nodules      — irregular aggregates
    V  defective nodules                    — crab-like, partially rounded
    VI spheroidal nodules (ductile iron)    — round, high solidity

Each particle is typed from engine-derived shape measures (aspect ratio,
solidity, roundness) already computed per contour — no new thresholds on raw
pixels. The population shares drive a dominant-form statement and matrix
hints. This is classification of the MEASURED geometry, not a phase map.
"""

# (form, label, predicate on (aspect_ratio, solidity, roundness), note)
_RULES = [
    ("VI", "spheroidal",
     lambda ar, sol, rnd: ar <= 1.6 and sol >= 0.90 and rnd >= 0.775,
     "graphite nodules — ductile iron signature"),
    ("V", "defective nodule",
     lambda ar, sol, rnd: ar <= 2.4 and sol >= 0.80 and rnd >= 0.625,
     "imperfectly rounded graphite — nodularity loss"),
    ("III", "vermicular/compacted",
     lambda ar, sol, rnd: ar <= 6.0 and sol >= 0.62 and rnd < 0.625,
     "compacted graphite — CGI signature when dominant"),
    ("I", "flake/lamellar",
     lambda ar, sol, rnd: sol < 0.62 or rnd < 0.30,
     "lamellar graphite — grey iron signature when dominant"),
]


def classify_graphite_forms(rows):
    """Type each detected particle (ISO 945 forms I-VI) and summarize.

    rows: engine nodule rows with aspect_ratio/solidity/roundness/area_px.
    Returns dict with per-form shares, dominant form and matrix hints.
    """
    particles = []
    counts = {"I": 0, "II": 0, "III": 0, "IV": 0, "V": 0, "VI": 0}
    areas = {"I": 0.0, "II": 0.0, "III": 0.0, "IV": 0.0, "V": 0.0, "VI": 0.0}

    for r in rows or []:
        ar = r.get("aspect_ratio")
        sol = r.get("solidity")
        rnd = r.get("roundness")
        if not all(isinstance(v, (int, float)) for v in (ar, sol, rnd)):
            form = "unclassified"
            note = "shape measures incomplete for this particle"
        else:
            form, note = "IV", "irregular aggregate (temper/other graphite)"
            for f, _label, pred, why in _RULES:
                if pred(ar, sol, rnd):
                    form, note = f, why
                    break
        counts[form] = counts.get(form, 0) + 1
        if isinstance(r.get("area_px"), (int, float)):
            areas[form] = areas.get(form, 0.0) + r["area_px"]
        particles.append({
            "nodule_id": r.get("nodule_id"),
            "iso945_form": form,
            "note": note,
        })

    total = len(rows or [])
    total_area = sum(areas.values())

    def share(d):
        # Shares are percentages of the POPULATION. Count shares divide by the
        # particle count; AREA shares must divide by the total graphite area so
        # that they genuinely sum to ~100% ("px2-per-particle" numbers are
        # exposed separately as form_area_px2).
        if d is counts:
            return {k: (round(v / total * 100.0, 1) if total else 0.0)
                    for k, v in d.items() if k in counts}
        return {k: (round(v / total_area * 100.0, 1)
                    if total_area else 0.0)
                for k, v in d.items() if k in counts}

    count_share = share(counts)
    area_share = share(areas)

    # dominant form by area (area reflects graphite amount better than count)
    dominant = max(area_share, key=area_share.get) if total else None

    hints = _matrix_hints(dominant, count_share, area_share)

    return {
        "available": total > 0,
        "standard": "ISO 945-based graphite forms I-VI",
        "particles": particles,
        "form_count_share_pct": count_share,
        "form_area_share_pct": area_share,
        # raw summed graphite area per form (px^2 at engine working scale) —
        # kept as correctly-named data alongside the percentage shares
        "form_area_px2": {k: round(v, 1) for k, v in areas.items()
                          if k in counts},
        "dominant_form": dominant,
        "dominant_interpretation": _FORM_INTERPRETATION.get(dominant),
        "matrix_hints": hints,
        "note": ("ISO 945-based classification of measured particle "
                 "geometry; verify matrix with etched metallography"),
    }


_FORM_INTERPRETATION = {
    "I": "lamellar (flake) graphite — grey cast iron morphology",
    "II": "interdendritic flake graphite",
    "III": "vermicular/compacted graphite — compacted graphite iron (CGI)",
    "IV": "temper/irregular graphite aggregates",
    "V": "defective nodules — degraded spheroidal graphite",
    "VI": "spheroidal nodules — fully nodular ductile iron",
}


def _matrix_hints(dominant, count_share, area_share):
    hints = []
    if dominant == "VI" and area_share.get("VI", 0) >= 80:
        hints.append("consistent with a fully nodular (ductile) iron — "
                     "ferritic or pearlitic matrix per heat treatment")
    if dominant == "V" or (area_share.get("V", 0) >= 20):
        hints.append("significant defective nodularity — check treatment "
                     "fading, late inoculation or high sulfur")
    if dominant == "III":
        hints.append("vermicular graphite dominant — compacted graphite iron "
                     "(CGI) or degraded ductile base")
    if dominant == "I":
        hints.append("flake graphite dominant — grey iron, not ductile: "
                     "engine accuracy is calibrated for spheroidal graphite")
    if not hints:
        hints.append("mixed morphology — class fractions above give the "
                     "breakdown")
    return hints
