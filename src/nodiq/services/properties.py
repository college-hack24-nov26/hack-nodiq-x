#!/usr/bin/env python3
"""
services/properties.py — Multi-Material Mechanical Property & Material Grade Prediction Engine.
(Pillar 2: Industrial ROI Feature — Microstructure -> Mechanical Properties)

Bridges metallographic computer vision metrics directly to commercial deliverables:
Tensile Strength (Rm), Yield Strength (Rp0.2), Elongation (A%), Brinell Hardness (HBW),
Compressive Strength, Fracture Toughness, and Standard Grade Compliance Envelopes for:

  1. Ductile / Spheroidal Graphite Cast Iron (ISO 1083 / ASTM A536 / EN 1563)
  2. Gray Cast Iron / Flake Graphite (ASTM A48 / ISO 185 / EN 1561)
  3. White Cast Iron / Wear-Resistant Carbides (ASTM A532 / ISO 21988)
  4. Steel Grain Size Metallography (ASTM E112 / ISO 643 / Hall-Petch Formulation)

Includes an automated Acceptance Verdict Meter with safety margin calculations for foundry QA.
"""

import math

_UNCERTAINTY = 0.12  # +/- 12% industrial uncertainty band for microstructure-based estimation


def _band(v, nd=0, uncertainty=_UNCERTAINTY):
    """Return low, estimate, high band for property values."""
    v_clean = float(v)
    return {
        "low": round(v_clean * (1.0 - uncertainty), nd),
        "estimate": round(v_clean, nd),
        "high": round(v_clean * (1.0 + uncertainty), nd)
    }


# ============================================================================
# 1. DUCTILE CAST IRON (ISO 1083 / ASTM A536 / EN 1563)
# ============================================================================

# Anchors: nodularity_pct -> (Rm MPa, Rp0.2 MPa, A %) per matrix baseline
_FERRITIC_ANCHORS = {
    0: (320.0, 230.0, 10.0),
    90: (425.0, 310.0, 15.0),
    100: (450.0, 320.0, 16.0)
}
_PEARLITIC_ANCHORS = {
    0: (350.0, 280.0, 2.0),
    60: (560.0, 370.0, 4.0),
    100: (700.0, 430.0, 2.0)
}

_DUCTILE_GRADES = [
    # (grade, min Rm, min Rp0.2, min A, typical matrix, application_note)
    ("EN-GJS-350-22", 350, 220, 22.0, "ferritic", "Cryogenic impact service, sub-zero refrigeration"),
    ("EN-GJS-400-18", 400, 240, 18.0, "ferritic", "Safety-critical wind turbine rotor hubs & main frames"),
    ("EN-GJS-400-15", 400, 250, 15.0, "ferritic", "Automotive steering knuckles and wheel hubs"),
    ("EN-GJS-450-10", 450, 310, 10.0, "ferritic", "Pressure pipe fittings, transmission housings"),
    ("EN-GJS-500-7",  500, 320, 7.0,  "ferritic/pearlitic", "Crankshafts, differential cases, suspension arms"),
    ("EN-GJS-600-3",  600, 370, 3.0,  "pearlitic", "Heavy-duty truck gears, diesel rocker arms"),
    ("EN-GJS-700-2",  700, 420, 2.0,  "pearlitic", "High-stress camshafts, railway brake discs"),
    ("EN-GJS-800-2",  800, 480, 2.0,  "pearlitic (alloyed)", "High-performance gears, track rollers"),
    # ASTM A536 Equivalents
    ("ASTM 60-40-18", 414, 276, 18.0, "ferritic", "High-ductility piping and structural hubs"),
    ("ASTM 65-45-12", 448, 310, 12.0, "ferritic", "General automotive castings, valve bodies"),
    ("ASTM 80-55-06", 552, 379, 6.0,  "ferritic/pearlitic", "Engine crankshafts, drive sprockets"),
    ("ASTM 100-70-03", 689, 483, 3.0, "pearlitic", "Heavy industrial gears, high-strength shafts"),
    ("ASTM 120-90-02", 827, 621, 2.0, "quenched/tempered", "High-wear track shoes and pinions")
]


def _interp(anchors, n):
    points = sorted(anchors)
    if n <= points[0]:
        lo, hi = points[0], points[1]
    elif n >= points[-1]:
        lo, hi = points[-2], points[-1]
    else:
        for a, b in zip(points, points[1:]):
            if a <= n <= b:
                lo, hi = a, b
                break
    t = (n - lo) / (hi - lo) if hi != lo else 0.0
    return tuple(anchors[lo][i] + t * (anchors[hi][i] - anchors[lo][i]) for i in range(3))


def estimate_ductile_iron_properties(nodularity_pct, graphite_area_pct=None, pearlite_pct=None,
                                     nodule_density_mm2=None, matrix="unknown", target_grade=None):
    """Estimate mechanical properties & grade compliance for Ductile / Nodular Cast Iron."""
    if not isinstance(nodularity_pct, (int, float)) or not (0 <= nodularity_pct <= 100):
        return {"available": False, "reason": "nodularity out of range or not measured"}

    n = float(nodularity_pct)

    # Determine matrix influence if specified
    if pearlite_pct is not None and isinstance(pearlite_pct, (int, float)):
        p_ratio = max(0.0, min(100.0, float(pearlite_pct))) / 100.0
        rm_f, rp_f, el_f = _interp(_FERRITIC_ANCHORS, n)
        rm_p, rp_p, el_p = _interp(_PEARLITIC_ANCHORS, n)
        rm = rm_f * (1.0 - p_ratio) + rm_p * p_ratio
        rp = rp_f * (1.0 - p_ratio) + rp_p * p_ratio
        el = el_f * (1.0 - p_ratio) + el_p * p_ratio
        matrix_name = f"{round(p_ratio * 100)}% pearlite / {round((1 - p_ratio) * 100)}% ferrite"
    elif matrix == "ferritic":
        rm, rp, el = _interp(_FERRITIC_ANCHORS, n)
        matrix_name = "ferritic"
    elif matrix == "pearlitic":
        rm, rp, el = _interp(_PEARLITIC_ANCHORS, n)
        matrix_name = "pearlitic"
    else:
        rm_f, rp_f, el_f = _interp(_FERRITIC_ANCHORS, n)
        rm_p, rp_p, el_p = _interp(_PEARLITIC_ANCHORS, n)
        rm = (rm_f + rm_p) / 2.0
        rp = (rp_f + rp_p) / 2.0
        el = (el_f + el_p) / 2.0
        matrix_name = "mixed baseline (unknown matrix)"

    # Graphite area fraction correction (typical standard is 10-12% area)
    if graphite_area_pct and isinstance(graphite_area_pct, (int, float)):
        area = float(graphite_area_pct)
        if area > 14.0:
            penalty = 1.0 - 0.015 * (area - 14.0)
            rm *= max(0.85, penalty)
            rp *= max(0.88, penalty)

    # Nodule count boundary pinning correction
    if nodule_density_mm2 and isinstance(nodule_density_mm2, (int, float)) and nodule_density_mm2 > 50:
        pinning_bonus = min(25.0, 0.12 * math.sqrt(float(nodule_density_mm2)))
        rp += pinning_bonus

    # Brinell hardness estimation
    if matrix == "ferritic":
        hbw = 130.0 + 0.35 * n
    elif matrix == "pearlitic":
        hbw = 210.0 + 0.65 * n
    else:
        hbw = 150.0 + 0.70 * n

    # Acceptance Verdict & Target Grade Matching
    compatible_grades = [g for g in _DUCTILE_GRADES if g[1] <= rm * (1.0 + _UNCERTAINTY)]
    nearest = min(compatible_grades or _DUCTILE_GRADES, key=lambda g: abs(g[1] - rm))

    active_grade_spec = None
    if target_grade:
        for g in _DUCTILE_GRADES:
            if g[0].lower() == target_grade.lower():
                active_grade_spec = g
                break
    if not active_grade_spec:
        active_grade_spec = nearest

    # Verdict evaluation
    req_rm, req_rp, req_a = active_grade_spec[1], active_grade_spec[2], active_grade_spec[3]
    rm_margin = ((rm - req_rm) / req_rm) * 100.0
    rp_margin = ((rp - req_rp) / req_rp) * 100.0
    a_margin = ((el - req_a) / req_a) * 100.0

    if rm >= req_rm and rp >= req_rp and el >= req_a:
        verdict_status = "COMPLIANT"
        verdict_text = (
            f"Complies with {active_grade_spec[0]} requirements for {active_grade_spec[5]} "
            f"(Tensile Margin: {rm_margin:+.1f}%, Yield Margin: {rp_margin:+.1f}%, Elongation Margin: {a_margin:+.1f}%)."
        )
        acceptance_score = min(100, int(85 + min(rm_margin, rp_margin, a_margin) * 0.5))
    elif rm >= req_rm * 0.95 and rp >= req_rp * 0.95 and el >= req_a * 0.90:
        verdict_status = "MARGINAL"
        verdict_text = (
            f"Marginal compliance with {active_grade_spec[0]}. Tensile/Yield within 5% of minimum; "
            "verify furnace inoculation and heat treatment before lot release."
        )
        acceptance_score = 65
    else:
        verdict_status = "NON_COMPLIANT"
        verdict_text = (
            f"NON-COMPLIANT with {active_grade_spec[0]}. Predicted properties below minimum spec. "
            "Foundry scrap prevention alert triggered."
        )
        acceptance_score = 35

    return {
        "available": True,
        "material_family": "Ductile / Spheroidal Graphite Cast Iron",
        "standard_basis": "ISO 1083 / EN 1563 / ASTM A536 grade envelopes",
        "matrix_assumed": matrix_name,
        "estimated_tensile_strength_mpa": _band(rm),
        "estimated_yield_strength_mpa": _band(rp),
        "estimated_elongation_pct": _band(el, 1),
        "estimated_hardness_hbw": _band(hbw, 0, 0.08),
        "active_grade": {
            "grade": active_grade_spec[0],
            "min_rm_mpa": active_grade_spec[1],
            "min_rp02_mpa": active_grade_spec[2],
            "min_elongation_pct": active_grade_spec[3],
            "typical_matrix": active_grade_spec[4],
            "application": active_grade_spec[5],
        },
        "nearest_iso_grades": [
            {"grade": nearest[0], "min_rm_mpa": nearest[1],
             "min_rp02_mpa": nearest[2], "min_elongation_pct": nearest[3],
             "matrix": nearest[4]}
        ],
        "acceptance_verdict": {
            "status": verdict_status,
            "score": acceptance_score,
            "target_grade": active_grade_spec[0],
            "statement": verdict_text,
            "tensile_margin_pct": round(rm_margin, 1),
            "yield_margin_pct": round(rp_margin, 1),
            "elongation_margin_pct": round(a_margin, 1),
        },
        "assumptions": [
            "Ductile iron per ISO 1083 / ASTM A536 with sound metallurgical inoculation",
            f"Matrix phase balance: {matrix_name}",
            "Microstructure measured on standard cross-section; chemical composition & casting cooling rate apply"
        ]
    }


def estimate_properties(nodularity_pct, matrix="unknown"):
    """Backward-compatible wrapper for existing callers and test suites."""
    return estimate_ductile_iron_properties(nodularity_pct, matrix=matrix)


# ============================================================================
# 2. GRAY CAST IRON (ASTM A48 / ISO 185 / EN 1561)
# ============================================================================

_GRAY_GRADES = [
    # (grade, min Rm, typical HBW, application_note)
    ("ASTM Class 20", 138, 160, "Low-stress housings, ornamental castings, furnace dampers"),
    ("ASTM Class 25", 172, 175, "Machine tool bases, municipal casting, pump casings"),
    ("ASTM Class 30", 207, 200, "Automotive brake rotors, brake drums, clutch pressure plates"),
    ("ASTM Class 35", 241, 220, "Diesel engine cylinder blocks, cylinder heads, transmission cases"),
    ("ASTM Class 40", 276, 240, "Heavy-duty diesel cylinder liners, high-pressure hydraulic bodies"),
    ("ASTM Class 50", 345, 260, "Severe-duty gears, compressor cylinders, diesel pistons"),
    # ISO 185 equivalents
    ("EN-GJL-150", 150, 165, "General engineering castings with high thermal conductivity"),
    ("EN-GJL-200", 200, 195, "Automotive brake discs with high thermal shock resistance"),
    ("EN-GJL-250", 250, 215, "Engine blocks requiring sound damping and dimensional stability"),
    ("EN-GJL-300", 300, 235, "High-strength machine tool beds and slideways")
]

_FLAKE_TYPE_PENALTY = {
    "A": 1.00,  # Uniform random distribution (optimal strength & damping)
    "B": 0.88,  # Rosette grouping (moderate eutectic undercooling)
    "C": 0.55,  # Kish graphite (coarse hypereutectic, severe notch effect)
    "D": 0.72,  # Interdendritic fine (low strength, localized wear)
    "E": 0.68   # Interdendritic preferred orientation (weak plane)
}


def estimate_gray_iron_properties(flake_type="A", flake_size=4, flake_area_pct=10.0,
                                  pearlite_pct=80.0, target_grade=None):
    """Estimate mechanical properties for Gray Cast Iron from flake morphology & matrix."""
    f_type = str(flake_type).upper()[:1] if flake_type else "A"
    k_type = _FLAKE_TYPE_PENALTY.get(f_type, 0.90)

    # Size effect: ASTM Size 1 (longest flakes >= 100 um) to Size 8 (shortest flakes <= 15 um)
    # Shorter flakes (higher size number) yield higher strength
    size_num = max(1, min(8, int(flake_size))) if flake_size is not None else 4
    size_factor = 0.70 + (size_num / 8.0) * 0.45  # 0.75 for size 1 up to 1.15 for size 8

    p_pct = float(pearlite_pct) if pearlite_pct is not None else 80.0
    p_pct = max(0.0, min(100.0, p_pct))

    area_pct = float(flake_area_pct) if flake_area_pct is not None else 10.0
    area_factor = max(0.80, 1.0 - 0.015 * (area_pct - 9.0)) if area_pct > 9.0 else 1.0

    # Griffith-based tensile strength
    base_matrix_strength = 110.0 + 1.8 * p_pct  # Pearlitic matrix provides higher strength
    rm = base_matrix_strength * k_type * size_factor * area_factor

    # Compressive strength: typically 3.4x to 3.8x tensile strength in gray iron
    compressive = rm * 3.65

    # Brinell hardness: 100 + 1.1*Pearlite + 0.22*Rm
    hbw = 105.0 + 1.15 * p_pct + 0.20 * rm

    # Damping capacity: inversely related to tensile strength, directly related to flake area and Type A
    damping_score = round(min(10.0, max(2.0, (area_pct / 2.0) * k_type * (8.5 - size_num * 0.5))), 1)

    # Grade matching
    compatible = [g for g in _GRAY_GRADES if g[1] <= rm * (1.0 + _UNCERTAINTY)]
    nearest = min(compatible or _GRAY_GRADES, key=lambda g: abs(g[1] - rm))

    active_grade_spec = None
    if target_grade:
        for g in _GRAY_GRADES:
            if g[0].lower() == target_grade.lower():
                active_grade_spec = g
                break
    if not active_grade_spec:
        active_grade_spec = nearest

    req_rm = active_grade_spec[1]
    rm_margin = ((rm - req_rm) / req_rm) * 100.0

    if rm >= req_rm:
        verdict_status = "COMPLIANT"
        verdict_text = (
            f"Complies with {active_grade_spec[0]} requirements for {active_grade_spec[3]} "
            f"(Tensile Margin: {rm_margin:+.1f}%, Damping Index: {damping_score}/10)."
        )
        score = min(100, int(85 + rm_margin * 0.5))
    elif rm >= req_rm * 0.95:
        verdict_status = "MARGINAL"
        verdict_text = (
            f"Marginal compliance with {active_grade_spec[0]} ({rm_margin:+.1f}% margin). "
            "Graphite flake size or matrix pearlite ratio requires foundry process verification."
        )
        score = 65
    else:
        verdict_status = "NON_COMPLIANT"
        verdict_text = (
            f"NON-COMPLIANT with {active_grade_spec[0]}. Tensile strength below specification limit. "
            "Excessive coarse kish or undercooled graphite detected."
        )
        score = 35

    return {
        "available": True,
        "material_family": "Gray Cast Iron (Flake Graphite)",
        "standard_basis": "ASTM A48 / ISO 185 / ASTM A247",
        "flake_morphology": {
            "type": f_type,
            "size_number": size_num,
            "type_penalty_factor": k_type,
            "flake_area_pct": area_pct,
        },
        "matrix_pearlite_pct": round(p_pct, 1),
        "estimated_tensile_strength_mpa": _band(rm),
        "estimated_compressive_strength_mpa": _band(compressive),
        "estimated_hardness_hbw": _band(hbw, 0, 0.08),
        "damping_capacity_index": damping_score,
        "active_grade": {
            "grade": active_grade_spec[0],
            "min_rm_mpa": active_grade_spec[1],
            "typical_hbw": active_grade_spec[2],
            "application": active_grade_spec[3],
        },
        "acceptance_verdict": {
            "status": verdict_status,
            "score": score,
            "target_grade": active_grade_spec[0],
            "statement": verdict_text,
            "tensile_margin_pct": round(rm_margin, 1),
        },
        "assumptions": [
            f"Lamellar graphite Type {f_type}, ASTM size {size_num}",
            f"Pearlitic/ferritic matrix balance: {round(p_pct)}% pearlite",
            "Compressive strength and thermal damping properties estimated via ISO 185 empirical factors"
        ]
    }


# ============================================================================
# 3. WHITE CAST IRON (ASTM A532 / ISO 21988)
# ============================================================================

_WHITE_GRADES = [
    # (grade, min HRC, min HBW, application_note)
    ("ASTM A532 Class I Type A (Ni-Hard 1)", 55, 550, "Ball mill liners, slurry pump wear plates"),
    ("ASTM A532 Class I Type D (Ni-Hard 4)", 58, 600, "Severe impact grinding balls, cement mill rolls"),
    ("ASTM A532 Class II Type B (15% Cr-Mo)", 59, 600, "High-wear dredge pump impellers, mining chute liners"),
    ("ASTM A532 Class III Type A (25% Cr)", 59, 600, "Corrosive slurry pumps, flue gas scrubber impellers"),
    ("ISO 21988 JN/HBW555", 55, 555, "Crusher wear segments"),
    ("ISO 21988 JN/HBW650", 63, 650, "Extremely abrasive rock crushing jaw plates")
]


def estimate_white_iron_properties(carbide_volume_fraction_pct=25.0, mean_spacing_um=15.0,
                                   matrix="martensitic", target_grade=None):
    """Estimate hardness, abrasion resistance, and toughness for White Cast Iron."""
    cvf = float(carbide_volume_fraction_pct) if carbide_volume_fraction_pct is not None else 25.0
    cvf = max(5.0, min(60.0, cvf))

    # Base matrix hardness
    base_hrc = 52.0 if matrix == "martensitic" else 42.0  # austenitic or pearlitic

    # Hardness scales directly with carbide volume fraction
    hrc = min(68.0, base_hrc + 0.38 * cvf)
    hbw = max(350.0, 10.0 * hrc - 30.0)

    # Abrasion Wear Resistance Index (WRI)
    spacing = max(2.0, float(mean_spacing_um) if mean_spacing_um is not None else 15.0)
    wri = round((hrc * cvf) / (spacing + 2.0), 1)

    # Fracture toughness K_IC (MPa*sqrt(m)) - decreases as brittle carbide fraction increases
    k_ic = round(max(13.0, 28.0 - 0.35 * cvf), 1)

    compatible = [g for g in _WHITE_GRADES if g[1] <= hrc * (1.0 + 0.05)]
    nearest = min(compatible or _WHITE_GRADES, key=lambda g: abs(g[1] - hrc))
    active_grade_spec = nearest
    if target_grade:
        for g in _WHITE_GRADES:
            if g[0].lower() == target_grade.lower():
                active_grade_spec = g
                break

    req_hrc = active_grade_spec[1]
    margin = ((hrc - req_hrc) / req_hrc) * 100.0

    if hrc >= req_hrc:
        status = "COMPLIANT"
        verdict = (
            f"Complies with {active_grade_spec[0]} requirements for {active_grade_spec[3]} "
            f"(Hardness: {round(hrc)} HRC / {round(hbw)} HBW, Margin: {margin:+.1f}%, Wear Index: {wri})."
        )
        score = min(100, int(85 + margin * 0.8))
    else:
        status = "NON_COMPLIANT"
        verdict = (
            f"NON-COMPLIANT with {active_grade_spec[0]}. Hardness ({round(hrc)} HRC) below minimum {req_hrc} HRC. "
            "Insufficient eutectic carbide volume fraction."
        )
        score = 40

    return {
        "available": True,
        "material_family": "White Cast Iron (Wear-Resistant Carbides)",
        "standard_basis": "ASTM A532 / ISO 21988",
        "carbide_volume_fraction_pct": round(cvf, 1),
        "estimated_rockwell_hardness_hrc": _band(hrc, 1, 0.05),
        "estimated_hardness_hbw": _band(hbw, 0, 0.06),
        "abrasion_wear_resistance_index": wri,
        "estimated_fracture_toughness_kic_mpa_m05": k_ic,
        "active_grade": {
            "grade": active_grade_spec[0],
            "min_hrc": active_grade_spec[1],
            "min_hbw": active_grade_spec[2],
            "application": active_grade_spec[3],
        },
        "acceptance_verdict": {
            "status": status,
            "score": score,
            "target_grade": active_grade_spec[0],
            "statement": verdict,
            "hardness_margin_pct": round(margin, 1),
        },
        "assumptions": [
            f"Carbide volume fraction: {round(cvf, 1)}% M3C/M7C3 eutectic carbides",
            f"Matrix structure: {matrix}",
            "Dry-sand rubber wheel abrasion wear index modeled per ASTM G65 baseline"
        ]
    }


# ============================================================================
# 4. STEEL GRAIN SIZE (ASTM E112 / ISO 643 / Hall-Petch Formulation)
# ============================================================================

_STEEL_GRADES = [
    # (grade, min Rp0.2, Rm range, min A, application_note)
    ("EN 10025 S235", 235, (360, 510), 26.0, "General structural steel, low-stress building columns"),
    ("EN 10025 S275", 275, (410, 560), 22.0, "Structural bridge sections, rail wagons"),
    ("EN 10025 S355", 355, (470, 630), 20.0, "Offshore wind tower flanges, heavy crane booms"),
    ("EN 10025 S460", 460, (540, 720), 17.0, "High-strength seismic architectural frames"),
    ("API 5L X52",    360, (460, 620), 21.0, "Natural gas & crude oil transmission pipelines"),
    ("API 5L X65",    450, (535, 760), 18.0, "High-pressure offshore subsea pipelines"),
    ("ASTM A36",     250, (400, 550), 23.0, "Bolted and welded structural steel building members"),
]


def estimate_steel_properties(astm_grain_size_g=8.0, mean_intercept_um=20.0,
                              steel_category="structural", target_grade=None):
    """Estimate mechanical properties for Steel via the Hall-Petch relationship."""
    g = float(astm_grain_size_g) if astm_grain_size_g is not None else 8.0
    g = max(1.0, min(14.0, g))

    # Mean spatial grain diameter d (mm)
    l_um = float(mean_intercept_um) if mean_intercept_um is not None else (32.0 / math.sqrt(2.0 ** (g - 1)))
    d_mm = max(0.001, (1.128 * l_um) / 1000.0)

    # Hall-Petch formulation: sigma_y = sigma_0 + k_y * d^(-1/2)
    # For structural C-Mn steels (S275/S355/API 5L), base friction + solid-solution sigma_0 ~ 200 MPa, k_y ~ 19.5 MPa*mm^(1/2)
    sigma_0 = 205.0
    k_y = 19.5
    rp = sigma_0 + (k_y / math.sqrt(d_mm))

    # Tensile strength Rm
    rm = 280.0 + 0.65 * rp

    # Elongation at fracture: fine grain steels maintain high ductility
    el = max(16.0, 32.0 - 0.025 * rp)

    # Brinell hardness: HBW ~ 0.31 * Rm
    hbw = 0.31 * rm

    # Ductile-to-Brittle Transition Temperature (DBTT) shift:
    # Fine grains lower the DBTT significantly (Petch-Cottrell: ~11.5 deg C per ASTM grain size number)
    dbtt_c = round(10.0 - 11.5 * (g - 5.0), 1)

    compatible = [st for st in _STEEL_GRADES if st[1] <= rp * (1.0 + _UNCERTAINTY)]
    nearest = min(compatible or _STEEL_GRADES, key=lambda st: abs(st[1] - rp))
    active_grade_spec = nearest
    if target_grade:
        for st in _STEEL_GRADES:
            if st[0].lower() == target_grade.lower():
                active_grade_spec = st
                break

    req_rp = active_grade_spec[1]
    rp_margin = ((rp - req_rp) / req_rp) * 100.0

    if rp >= req_rp:
        status = "COMPLIANT"
        verdict = (
            f"Complies with {active_grade_spec[0]} requirements for {active_grade_spec[4]} "
            f"(Yield Margin: {rp_margin:+.1f}%, Grain Size G={round(g, 1)}, DBTT: {dbtt_c}°C)."
        )
        score = min(100, int(85 + rp_margin * 0.6))
    else:
        status = "NON_COMPLIANT"
        verdict = (
            f"NON-COMPLIANT with {active_grade_spec[0]}. Grain size too coarse (G={round(g, 1)}). "
            f"Yield strength ({round(rp)} MPa) fails minimum {req_rp} MPa."
        )
        score = 40

    return {
        "available": True,
        "material_family": "Steel Grain Size (ASTM E112 / ISO 643)",
        "standard_basis": "Hall-Petch Grain Boundary Strengthening (ASTM E112)",
        "measured_grain_parameters": {
            "astm_grain_size_g": round(g, 2),
            "mean_intercept_length_um": round(l_um, 2),
            "mean_grain_diameter_mm": round(d_mm, 4),
        },
        "estimated_yield_strength_mpa": _band(rp),
        "estimated_tensile_strength_mpa": _band(rm),
        "estimated_elongation_pct": _band(el, 1),
        "estimated_hardness_hbw": _band(hbw, 0, 0.08),
        "estimated_dbtt_celsius": dbtt_c,
        "active_grade": {
            "grade": active_grade_spec[0],
            "min_rp02_mpa": active_grade_spec[1],
            "typical_rm_range_mpa": active_grade_spec[2],
            "min_elongation_pct": active_grade_spec[3],
            "application": active_grade_spec[4],
        },
        "acceptance_verdict": {
            "status": status,
            "score": score,
            "target_grade": active_grade_spec[0],
            "statement": verdict,
            "yield_margin_pct": round(rp_margin, 1),
        },
        "assumptions": [
            "Hall-Petch relationship: sigma_y = sigma_0 + k_y * d^(-1/2)",
            f"Measured ASTM Grain Size Number: G = {round(g, 2)}",
            "Ductile-to-brittle transition temperature shift modeled for standard C-Mn structural ferrite"
        ]
    }


# ============================================================================
# 5. UNIVERSAL DISPATCHER
# ============================================================================

def estimate_mechanical_properties(analysis_type, measured_data, target_grade=None):
    """Universal dispatcher for all 4 metallographic analysis types."""
    data = measured_data or {}
    atype = str(analysis_type or "").lower()

    if "gray" in atype or "flake" in atype:
        return estimate_gray_iron_properties(
            flake_type=data.get("dominant_type") or data.get("flake_type", "A"),
            flake_size=data.get("astm_size") or data.get("flake_size", 4),
            flake_area_pct=data.get("area_fraction_pct") or data.get("flake_area_pct", 10.0),
            pearlite_pct=data.get("pearlite_pct", 80.0),
            target_grade=target_grade
        )

    if "white" in atype or "carbide" in atype:
        return estimate_white_iron_properties(
            carbide_volume_fraction_pct=data.get("carbide_fraction_pct") or data.get("area_fraction_pct", 25.0),
            mean_spacing_um=data.get("mean_spacing_um", 15.0),
            matrix=data.get("matrix", "martensitic"),
            target_grade=target_grade
        )

    if "steel" in atype or "grain" in atype:
        return estimate_steel_properties(
            astm_grain_size_g=data.get("astm_grain_size") or data.get("grain_size_g", 8.0),
            mean_intercept_um=data.get("mean_intercept_um", 20.0),
            target_grade=target_grade
        )

    # Default to Ductile / Spheroidal Graphite Cast Iron
    return estimate_ductile_iron_properties(
        nodularity_pct=data.get("iso_nodularity_pct") or data.get("nodularity_pct", 85.0),
        graphite_area_pct=data.get("graphite_area_pct"),
        pearlite_pct=data.get("pearlite_pct"),
        nodule_density_mm2=data.get("nodule_density_mm2"),
        matrix=data.get("matrix", "unknown"),
        target_grade=target_grade
    )
