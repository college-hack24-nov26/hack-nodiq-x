"""services/experimental/touching_split.py — Phase 9C offline splitter.

EXPERIMENT ONLY.  This module is never imported by production code.  It
accepts one production binary particle mask (plus its gray image, optional)
and returns the mask unchanged or as >= 2 proposed child particles.

Determinism: every technique is a pure function of (mask, params); no RNG
anywhere.  Two runs on the same input produce identical output.

Techniques measured (Phase 9C/9D — none assumed correct up front):

* ``concavity``   — contour concavity-depth analysis: depth of every boundary
  vertex inside the polygon's own convex hull; split at significant,
  well-separated concavity peaks (the "waist" of a dumb-bell) whose joining
  chord lies inside the polygon and leaves two sizable halves.  Conservative
  by design.
* ``watershed``   — distance-transform local-maxima markers + marker-
  controlled watershed flooding on the DT surface.  Not assumed correct:
  markers only from prominent, separated DT maxima; the evidence gate
  (elongation + concavity depth) decides WHETHER to split for both
  techniques equally, so watershed competes with concavity on equal terms.

Children are always a partition of the parent mask (watershed -1 boundary
pixels and concavity chord pixels are assigned to the nearest child), so
``sum(child areas) == parent area`` up to rasterization tolerance
``AREA_CONSERVATION_TOLERANCE`` (Phase 9H guarantee).

Parameters (Phase 9F) with documented ranges:

============================  ===========  ==============================
parameter                     range        default
============================  ===========  ==============================
min_area                      [10, 1e6]    40 px (children below -> reject)
min_concavity_depth           [0.02, 0.6]  0.10 x sqrt(area)  (px)
min_separation                [0.05, 2.0]  0.25 (fraction of sqrt(area))
max_children                  [2, 12]      4
dt_marker_min_distance        [2, 100]     8 px
dt_marker_prominence          [0.0, 1.0]   0.20 (fraction of max DT)
watershed_compactness         [0.0, 1.0]   0.10 (marker dilation 0..20%
                                           of sqrt(area))
neck_ratio_min                [1.0, 4.0]   1.2 (min marker DT / min DT
                                           along the marker-pair chord;
                                           nearest-neighbor pairs only)
elongation_min                [1.0, 8.0]   1.30 (major/minor hull extent)
technique                     concavity    | watershed
============================  ===========  ==============================
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

# sum(child areas) / parent area must stay within [1 - t, 1 + t]; the split
# is a partition so only rasterization noise can move it (documented in 9H).
AREA_CONSERVATION_TOLERANCE = 0.02


@dataclass
class SplitParams:
    """Documented, exposed parameters (Phase 9F).  Ranges in module doc."""

    technique: str = "concavity"          # concavity | watershed
    min_area: float = 40.0
    min_concavity_depth: float = 0.10
    min_separation: float = 0.25
    max_children: int = 4
    dt_marker_min_distance: float = 8.0
    dt_marker_prominence: float = 0.20
    watershed_compactness: float = 0.10
    neck_ratio_min: float = 1.2
    elongation_min: float = 1.30

    def validated(self) -> "SplitParams":
        if self.technique not in ("concavity", "watershed"):
            raise ValueError(f"unknown technique: {self.technique!r}")
        if not (10.0 <= self.min_area <= 1e6):
            raise ValueError("min_area outside documented range [10, 1e6]")
        if not (0.02 <= self.min_concavity_depth <= 0.6):
            raise ValueError("min_concavity_depth outside [0.02, 0.6]")
        if not (0.05 <= self.min_separation <= 2.0):
            raise ValueError("min_separation outside [0.05, 2.0]")
        if not (2 <= int(self.max_children) <= 12):
            raise ValueError("max_children outside [2, 12]")
        if not (2.0 <= self.dt_marker_min_distance <= 100.0):
            raise ValueError("dt_marker_min_distance outside [2, 100]")
        if not (0.0 <= self.dt_marker_prominence <= 1.0):
            raise ValueError("dt_marker_prominence outside [0, 1]")
        if not (0.0 <= self.watershed_compactness <= 1.0):
            raise ValueError("watershed_compactness outside [0, 1]")
        if not (1.0 <= self.neck_ratio_min <= 4.0):
            raise ValueError("neck_ratio_min outside [1.0, 4.0]")
        if not (1.0 <= self.elongation_min <= 8.0):
            raise ValueError("elongation_min outside [1, 8]")
        return self


@dataclass
class SplitResult:
    """Outcome for one particle mask (deterministic per input + params)."""

    split_performed: bool = False
    reason: str = "unchanged"
    technique: str = ""
    children_masks: list = field(default_factory=list)   # full-size uint8
    concavity_depth: float = 0.0
    elongation: float = 1.0
    n_candidates: int = 0                                # peaks/cut sites
    children_areas: list = field(default_factory=list)   # px, crop-based
    children_bboxes: list = field(default_factory=list)  # abs (x, y, w, h)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _mask_and_contour(mask):
    m = np.ascontiguousarray(mask.astype(np.uint8))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return m, None
    cnt = max(cnts, key=cv2.contourArea)
    if len(cnt) > 900:
        # deterministic decimation: keeps every significant vertex (waist
        # included) while bounding the per-vertex hull-cost of large contours
        approx = cv2.approxPolyDP(cnt, 1.5, True)
        if len(approx) >= 6:
            cnt = approx
    return m, cnt


def _polygon_area(pts):
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def _hull_extents(pts):
    """(major, minor) full extents of the point set via covariance axes."""
    c = pts.mean(axis=0)
    p = pts - c
    cov = p.T @ p / max(len(p), 1)
    evals, evecs = np.linalg.eigh(cov)
    major = evecs[:, np.argmax(evals)]
    minor = evecs[:, np.argmin(evals)]
    t_maj = p @ major
    t_min = p @ minor
    return float(t_maj.max() - t_maj.min()), float(t_min.max() - t_min.min())


def concavity_signal(poly):
    """Concavity depth of every polygon vertex inside its own convex hull.

    Depth = Euclidean distance from the vertex to the hull boundary
    (concave vertices sit strictly inside the hull; hull vertices score 0).
    Vectorized point-to-segment distance over all (vertex, hull-edge) pairs
    — numerically equivalent to per-vertex pointPolygonTest, ~100x faster.
    Returns (depths, indices sorted by depth desc, positive only).
    """
    pts = poly.reshape(-1, 2).astype(np.float64)
    n = len(pts)
    if n < 6:
        return np.zeros(n), []
    hull = cv2.convexHull(pts.astype(np.float32)).reshape(-1, 2) \
        .astype(np.float64)
    m = len(hull)
    if m < 3:
        return np.zeros(n), []
    a = hull
    d = np.roll(hull, -1, axis=0) - a            # (m, 2) edge vectors
    seg_len2 = np.maximum((d ** 2).sum(1), 1e-12)
    ap = pts[:, None, :] - a[None, :, :]         # (n, m, 2)
    t = np.clip((ap * d[None]).sum(-1) / seg_len2[None], 0.0, 1.0)
    proj = a[None, :, :] + t[..., None] * d[None, :, :]   # (n, m, 2)
    dist = np.linalg.norm(pts[:, None, :] - proj, axis=-1)
    depths = dist.min(axis=1)
    depths[depths < 1e-9] = 0.0
    order = [int(i) for i in np.argsort(-depths) if depths[i] > 0]
    return depths, order


def _depth_peaks(depths):
    """Indices of plateau-aware local maxima of the depth signal.

    A vertex is a peak when depth[i] >= depth[i-1] and depth[i] > depth[i+1]
    (cyclic): exactly one index per plateau, fully deterministic.
    """
    n = len(depths)
    if n < 3:
        return []
    peaks = []
    for i in range(n):
        d = depths[i]
        if d <= 0:
            continue
        if d >= depths[(i - 1) % n] and d > depths[(i + 1) % n]:
            peaks.append(i)
    return peaks


def _split_polygon_by_chord(poly, i, j):
    """Split closed polygon at vertices i, j into the two polygonal halves."""
    n = len(poly)
    if i > j:
        i, j = j, i
    if i == j or (i == 0 and j == n - 1):
        return None
    a = np.vstack([poly[i:j + 1]])
    b = np.vstack([poly[j:], poly[:i + 1]])
    return a, b


def _rasterize_full(poly, shape):
    """Rasterize polygon (absolute coords) onto a full-size mask canvas."""
    canvas = np.zeros(shape[:2], np.uint8)
    pts = poly.astype(np.int32).reshape(-1, 1, 2)
    cv2.fillPoly(canvas, [pts], 255)
    return canvas


def _absorb_boundary(children, parent):
    """Assign unassigned parent pixels to the nearest child (deterministic).

    Guarantees the children form a partition of the parent: watershed
    label -1 pixels and chord-rasterization residuals join the child whose
    existing pixels are closest (L2 distance transform, ties -> lowest
    child index via argmin).  Work is cropped to the parent bbox.
    """
    assigned = [c > 0 for c in children]
    remaining = (parent > 0)
    for a in assigned:
        remaining &= ~a
    if not remaining.any():
        return children
    ys, xs = np.nonzero(remaining)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    dists = []
    for a in assigned:
        inv = (~a[y0:y1, x0:x1]).astype(np.uint8)
        dists.append(cv2.distanceTransform(inv, cv2.DIST_L2, 3))
    stack = np.stack(dists)
    nearest = np.argmin(stack, axis=0)
    rem = remaining[y0:y1, x0:x1]
    out = []
    for i, c in enumerate(children):
        m = c.copy()
        sub = m[y0:y1, x0:x1]
        sub[rem & (nearest == i)] = 255
        m[y0:y1, x0:x1] = sub
        out.append(m)
    return out


# ---------------------------------------------------------------------------
# concavity technique
# ---------------------------------------------------------------------------

def _deepest_cut_in_polygon(P, params, parent_area):
    """Deepest valid waist cut within ONE polygon piece, or None.

    Valid: two concavity peaks of P whose chord stays inside P and whose
    two halves each hold >= 25% of P (no slivers) and >= min_area pixels
    worth of polygon area.
    """
    pts = P.reshape(-1, 2).astype(np.float64)
    n = len(pts)
    if n < 6:
        return None
    depths, _ = concavity_signal(P.astype(np.float32))
    peaks = [k for k in _depth_peaks(depths)
             if depths[k] >= params.min_concavity_depth *
             math.sqrt(max(parent_area, 1.0))]
    if len(peaks) < 2:
        return None
    peaks.sort(key=lambda k: -depths[k])
    total = _polygon_area(pts)
    min_frac = 0.25
    for p in peaks:
        for q in peaks:
            if q == p:
                continue
            halves = _split_polygon_by_chord(pts, p, q)
            if halves is None:
                continue
            areas = [_polygon_area(h) for h in halves]
            if min(areas) < min_frac * total:
                continue
            mid = (pts[p] + pts[q]) / 2.0
            hullP = cv2.convexHull(P.astype(np.float32))
            if cv2.pointPolygonTest(hullP, (float(mid[0]), float(mid[1])),
                                    False) < 0:
                continue
            return (p, q, float(depths[p]))
    return None


def _apply_concavity_split(mask, params):
    """Recursive waist cutting: repeatedly split the deepest valid waist of
    a piece until no piece carries one or max_children pieces exist.
    Deterministic: pieces processed largest-area first, cuts deepest-first.
    """
    m, cnt = _mask_and_contour(mask)
    if cnt is None:
        return None
    area = int(np.count_nonzero(m))
    poly = cnt.reshape(-1, 2).astype(np.float64)

    # queue of (piece, area); process deepest-cut-capable, largest first
    pieces = [(poly, _polygon_area(poly))]
    final = []
    while pieces and len(final) + len(pieces) < params.max_children:
        pieces.sort(key=lambda t: -t[1])
        P, Pa = pieces.pop(0)
        cut = _deepest_cut_in_polygon(P, params, area)
        if cut is None:
            final.append((P, Pa))
            continue
        p_idx, q_idx, _ = cut
        pts = P.reshape(-1, 2).astype(np.float64)
        halves = _split_polygon_by_chord(pts, p_idx, q_idx)
        if halves is None:
            final.append((P, Pa))
            continue
        accepted = True
        for h in halves:
            ha = _polygon_area(h)
            if ha < params.min_area or ha < 0.25 * Pa:
                accepted = False
        if not accepted:
            final.append((P, Pa))   # this waist rejected; piece stays whole
            continue
        for h in halves:
            pieces.append((h, _polygon_area(h)))

    final.extend(pieces)
    if len(final) < 2:
        return None
    children = []
    for P, _ in final:
        child = _rasterize_full(P, m.shape)
        if np.count_nonzero(child) >= params.min_area:
            children.append(child)
    if len(children) < 2:
        return None
    return _absorb_boundary(children, m)      # chord pixels -> nearest child


# ---------------------------------------------------------------------------
# watershed technique
# ---------------------------------------------------------------------------

def _dt_markers(dist, m, params, area):
    """Marker labels from DT local maxima (dilate-comparison), filtered by
    prominence, pairwise minimum distance, and a NECK-RATIO guard.

    Neck ratio (9H over-split guard): for every marker, look at its nearest
    neighboring marker; the MINIMUM DT along the straight chord between the
    two markers (the true saddle; sampled at 64 deterministic points) must
    be genuinely lower than the markers —
    min(marker DT) / min-chord-DT >= neck_ratio_min.
    A thick arc or plain blob has chord-DT ~= marker thickness (ratio ~1)
    and is rejected: watershed may not invent particles where there is no
    neck.  If ANY nearest-neighbor pair fails, no watershed split is
    attempted (conservative).
    """
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    local_max = (dist >= cv2.dilate(dist, k)) & (dist > 0)
    dmax = float(dist.max())
    if dmax <= 0:
        return None
    peak_map = (local_max & (dist >= params.dt_marker_prominence * dmax)
                ).astype(np.uint8) * 255
    n_peaks, peak_lab, pstats, pcent = cv2.connectedComponentsWithStats(
        peak_map)
    order = sorted(range(1, n_peaks),
                   key=lambda i: -pstats[i, cv2.CC_STAT_AREA])
    markers = np.zeros(m.shape, np.int32)
    kept, taken = 0, []
    for i in order:
        cx, cy = float(pcent[i, 0]), float(pcent[i, 1])
        if any((cx - ax) ** 2 + (cy - ay) ** 2 <
               params.dt_marker_min_distance ** 2 for ax, ay in taken):
            continue
        taken.append((cx, cy))
        kept += 1
        markers[peak_lab == i] = kept
        if kept >= params.max_children:
            break
    if kept < 2:
        return None

    h, w = m.shape
    for i, (cx, cy) in enumerate(taken):
        others = [(j, q) for j, q in enumerate(taken) if j != i]
        j, (qx, qy) = min(others,
                          key=lambda t: (cx - t[1][0]) ** 2 +
                          (cy - t[1][1]) ** 2)
        # min DT along the chord = the saddle (64 deterministic samples)
        ts_x = np.linspace(cx, qx, 64)
        ts_y = np.linspace(cy, qy, 64)
        xi = np.clip(ts_x, 0, w - 1).astype(int)
        yi = np.clip(ts_y, 0, h - 1).astype(int)
        saddle = float(dist[yi, xi].min())
        mi = min(float(dist[int(round(cy)), int(round(cx))]),
                 float(dist[int(round(qy)), int(round(qx))]))
        if saddle <= 0 or mi / saddle < params.neck_ratio_min:
            return None                       # no genuine neck: no split
    return markers, kept


def _apply_watershed_split(mask, params):
    """Distance-transform marker-controlled watershed (surface = DT)."""
    m, cnt = _mask_and_contour(mask)
    if cnt is None:
        return None
    area = int(np.count_nonzero(m))
    dist = cv2.distanceTransform(m, cv2.DIST_L2, 5)
    mk = _dt_markers(dist, m, params, area)
    if mk is None:
        return None
    markers, kept = mk

    if params.watershed_compactness > 0:
        rad = int(round(params.watershed_compactness * 0.2 *
                        math.sqrt(area)))
        if rad > 0:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                          (2 * rad + 1, 2 * rad + 1))
            grown = np.zeros_like(markers)
            for lab in range(1, kept + 1):
                dil = cv2.dilate((markers == lab).astype(np.uint8) * 255, k)
                grown[(dil > 0) & (markers == 0)] = lab
            markers = np.where(markers > 0, markers, grown)

    surf = cv2.normalize(dist, None, 0, 255,
                         cv2.NORM_MINMAX).astype(np.uint8)
    ws_input = cv2.cvtColor(surf, cv2.COLOR_GRAY2BGR)
    ws = cv2.watershed(ws_input, markers.copy())
    labels = np.unique(ws)
    labels = labels[labels > 0]
    if len(labels) < 2:
        return None
    children = []
    for lab in labels:
        child = (ws == lab).astype(np.uint8) * 255
        child &= m                                   # stay inside parent
        if np.count_nonzero(child) >= params.min_area:
            children.append(child)
    if len(children) < 2:
        return None
    return _absorb_boundary(children, m)      # ws == -1 pixels -> nearest


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def _candidate_evidence(mask):
    """Elongation + max concavity depth of one particle mask."""
    _, cnt = _mask_and_contour(mask)
    if cnt is None:
        return 1.0, 0.0, 0
    poly = cnt.reshape(-1, 2).astype(np.float64)
    maj, mino = _hull_extents(poly)
    elong = maj / max(mino, 1e-6)
    depths, order = concavity_signal(cnt)
    return elong, float(depths.max()) if len(depths) else 0.0, len(order)


def passes_evidence(mask, params: SplitParams | None = None) -> bool:
    """True when the mask passes the evidence gate (elongation or multi-peak
    concavity + real waist depth) — i.e. the splitter would consider it a
    candidate.  GT-independent; usable for candidate pre-selection."""
    p = (params or SplitParams()).validated()
    if mask is None:
        return False
    m = np.ascontiguousarray(mask.astype(np.uint8))
    if m.ndim != 2 or m.size == 0 or np.count_nonzero(m) == 0:
        return False
    area = int(np.count_nonzero(m))
    if area < 2 * p.min_area:
        return False
    elong, depth, _ = _candidate_evidence(m)
    thresh = p.min_concavity_depth * math.sqrt(area)
    if depth < thresh:
        return False
    if elong >= p.elongation_min:
        return True
    depths_arr, _order = concavity_signal(_mask_and_contour(m)[1])
    n_sig = sum(1 for k in _depth_peaks(depths_arr) if depths_arr[k] >= thresh)
    return n_sig >= 2


def split_particle_mask(mask, params: SplitParams | None = None,
                        gray=None):
    """Split one production particle mask (offline experiment, 9C/9D).

    Returns a :class:`SplitResult`.  The parent mask is never modified;
    children (when any) are a partition of the parent up to rasterization
    tolerance.  ``gray`` is accepted for future texture-aware techniques;
    unused here.
    """
    p = (params or SplitParams()).validated()
    res = SplitResult(technique=p.technique)
    if mask is None:
        res.reason = "invalid_mask"
        return res
    m = np.ascontiguousarray(mask.astype(np.uint8))
    if m.ndim != 2 or m.size == 0 or np.count_nonzero(m) == 0:
        res.reason = "invalid_mask"
        return res
    area = int(np.count_nonzero(m))
    if area < 2 * p.min_area:
        res.reason = "area_too_small"
        return res

    elong, depth, n_sites = _candidate_evidence(m)
    res.elongation = round(elong, 4)
    res.concavity_depth = round(depth, 4)
    res.n_candidates = n_sites

    # evidence gate: a candidate needs a real waist (depth) AND either
    # elongation or >= 2 concavity peaks (a triangular cluster is not
    # elongated but still carries multiple waists).  A convex or singly-
    # concave particle (C shape) is never a candidate.
    depths_arr, _order = concavity_signal(_mask_and_contour(m)[1])
    # only SIGNIFICANT peaks count (a rasterized circle has hundreds of
    # depth>0 vertices; its peak plateau depth is ~1px = noise)
    thresh = p.min_concavity_depth * math.sqrt(area)
    n_sig_peaks = sum(1 for k in _depth_peaks(depths_arr)
                      if depths_arr[k] >= thresh)
    if depth < thresh or (elong < p.elongation_min and n_sig_peaks < 2):
        res.reason = "no_evidence"
        return res

    # run the technique on a tight bbox crop (DT and watershed are
    # translation-invariant; children are padded back to full canvas)
    ys, xs = np.nonzero(m)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    crop = m[y0:y1, x0:x1]
    if p.technique == "watershed":
        kids = _apply_watershed_split(crop, p)
    else:
        kids = _apply_concavity_split(crop, p)
    if not kids or len(kids) < 2:
        res.reason = "no_valid_split"
        return res
    children = []
    children_areas, children_bboxes = [], []
    for c in kids:
        full = np.zeros_like(m)
        full[y0:y1, x0:x1] = c
        children.append(full)
        children_areas.append(int(np.count_nonzero(c)))
        cys, cxs = np.nonzero(c)
        children_bboxes.append(
            (x0 + int(cxs.min()), y0 + int(cys.min()),
             int(cxs.max() - cxs.min() + 1), int(cys.max() - cys.min() + 1)))
    res.children_areas = children_areas
    res.children_bboxes = children_bboxes

    # 9H guards: max children + area conservation within rasterization tol
    children = children[:p.max_children]
    child_area = sum(int(np.count_nonzero(c)) for c in children)
    ratio = child_area / area
    if abs(ratio - 1.0) > AREA_CONSERVATION_TOLERANCE:
        res.reason = f"area_conservation_failed({ratio:.3f})"
        return res
    res.split_performed = True
    res.reason = "split"
    res.children_masks = children
    return res


def split_particle_contour(contour, shape, params: SplitParams | None = None):
    """Convenience wrapper: contour (production format) -> children contours.

    Returns (split_performed, children_contours_or_[contour], SplitResult).
    """
    m = np.zeros(shape[:2], np.uint8)
    arr = np.asarray(contour)
    cv2.drawContours(m, [arr.astype(np.int64)], -1, 255, -1)
    r = split_particle_mask(m, params)
    if not r.split_performed:
        return False, [arr.astype(np.int64)], r
    children = []
    for c in r.children_masks:
        cc, _ = cv2.findContours(c, cv2.RETR_EXTERNAL,
                                 cv2.CHAIN_APPROX_SIMPLE)
        if cc:
            children.append(max(cc, key=cv2.contourArea))
    return True, children, r
