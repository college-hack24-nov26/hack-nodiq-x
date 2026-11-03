# Adaptive graphite nodule detector.
# The original nodularity.py remains available as the legacy detector.
import datetime
import math
from pathlib import Path

import cv2
import numpy as np

import nodularity as legacy

# Processing settings
DEBUG = True
BACKGROUND_BLUR_SIZE = 201
MORPHOLOGY_KERNEL_SIZE = 15
MIN_CONTOUR_AREA = 30
MAX_CONTOUR_AREA_RATIO = 0.15
MIN_CIRCULARITY = 0.08
MIN_SOLIDITY = 0.45
MAX_ASPECT_RATIO = 8.0
MIN_LOCAL_CONTRAST = 35.0
ORIGINAL_DOMINANCE_RATIO = 1.25
MAX_ARTIFACT_AREA_RATIO = 0.65
ROBUST_SCORE_THRESHOLD = 2
LARGE_CONTOUR_AREA_RATIO = 0.001
LARGE_MIN_LOCAL_CONTRAST = 12.0
SMALL_MIN_LOCAL_CONTRAST = 25.0
SMALL_MIN_SCORE = 4
INNER_RING_SCALE = 0.15
OUTER_RING_SCALE = 0.35
LARGE_DARKNESS_CONTRAST = 12.0
MAX_SURROUNDING_EDGE_DENSITY = 0.18
MAX_FRAGMENTATION = 0.45
CONTOUR_MATCH_IOU = 0.20
SUSPICION_AREA_RATIO = 0.003
SUSPICION_SOLIDITY = 0.65
SUSPICION_CIRCULARITY = 0.15
SUSPICION_ASPECT_RATIO = 4.0
MIN_SPLIT_PEAK_DISTANCE = 12
MIN_SPLIT_PEAK_RELATIVE = 0.35
MIN_SPLIT_AREA_RATIO = 0.08
MIN_SPLIT_SEPARATION_RATIO = 0.25
MIN_SPLIT_SCORE_GAIN = 1.0

# Neighborhood / isolation context (image-local, cheap to compute)
NEIGHBOR_RADIUS_SCALE = 1.6
NEIGHBOR_MIN_RADIUS = 30.0
CLUSTER_NEIGHBOR_ABSOLUTE = 7
CLUSTER_NEIGHBOR_RELATIVE = 1.5
CLUSTER_FRAGMENTATION = 0.30
CLUSTER_DARK_MEDIAN = 150.0
CLUSTER_WEAK_DEPTH = 16.0
CLUSTER_MIN_SIGNALS = 4
ROBUST_MED_DEPTH = 12.0
ROBUST_DARK_MEDIAN = 158.0
ROBUST_UNIFORM_SPREAD = 120.0
ROBUST_ISOLATION = 0.40
ROBUST_MIN_EVIDENCE = 4
ROBUST_NEARBY_SMALL_FRACTION = 0.60

# Multi-scale evidence tiers + darkness-consistency requirements.
# SMALL bounds the tiny / sub-min-graphite cohort; everything below the
# protected LARGE boundary is MEDIUM.  Fractions are of full image area, so
# the tiers stay scale-independent across magnifications.
SMALL_AREA_RATIO = 0.0001
DARK_FRACTION_WEAK = 0.55
DARK_FRACTION_STRONG = 0.80
INTERIOR_SPREAD_UNIFORM = 40.0
INTERIOR_SPREAD_MODERATE = 70.0
TEXTURE_EDGE_CAP = 0.10
WEAK_MEDIAN_DEPTH = 22.0
# Minimum combined evidence required per (tier, source): both < original <
# robust.  Small candidates never ride on source alone.
SCORE_MIN_BOTH_SMALL = 6.5
SCORE_MIN_BOTH_MEDIUM = 4.5
SCORE_MIN_ORIGINAL_SMALL = 7.5
SCORE_MIN_ORIGINAL_MEDIUM = 5.5
SCORE_MIN_ROBUST_SMALL = 8.0
SCORE_MIN_ROBUST_MEDIUM = 6.0

# Duplicate / nested resolution
DUPLICATE_IOU = 0.30
DUPLICATE_BBOX_IOU = 0.35
NESTED_COVER = 0.80
NESTED_AREA_RATIO = 0.30
NESTED_MARGIN = 10

# Cheap refinement suspicion gate
VALLEY_LIFT = 18
VALLEY_MIN_AREA = 10
VALLEY_MIN_AREA_RATIO = 0.004
DARK_CORE_LIFT = 10
DARK_CORE_MIN_AREA_RATIO = 0.01
INTERIOR_STRUCTURE_MIN_AREA = 24

# Ring bands around a filled contour use exact dilation below this estimated
# per-candidate morphology cost and a fast distance-transform band above it.
RING_DILATE_COST_LIMIT = 25000000


def odd_kernel_size(value):
    value = max(3, int(value))
    return value if value % 2 else value + 1


def find_input_images(input_dir):
    generated_marker = "_nodularity("
    return sorted(
        str(path) for path in input_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        and generated_marker not in path.stem
    )


# ---------------------------------------------------------------------------
# Image-level cache: all per-image arrays are created once and reused by every
# contour. No repeated Canny / full-image masks anywhere in the pipeline.
# ---------------------------------------------------------------------------
def build_image_cache(gray, background, width, height):
    edges = cv2.Canny(gray, 50, 150)
    edge01 = np.uint8(edges > 0)
    return {
        "gray": gray,
        "background": background,
        "edges": edges,
        "edge01": edge01,
        "width": width,
        "height": height,
        "global_edge_density": float(cv2.mean(edge01)[0]),
        "texture": float(cv2.countNonZero(edges)) / edges.size * 100,
    }


def original_detection(gray, width, height):
    _, mask = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    return mask, legacy.select_contours(contours, width, height, legacy.min_grainsize)


def preliminary_filter(contours, width, height):
    max_area = width * height * MAX_ARTIFACT_AREA_RATIO
    return [
        contour for contour in contours
        if MIN_CONTOUR_AREA <= cv2.contourArea(contour) <= max_area
    ]


def robust_detection(gray, width, height):
    blur_size = odd_kernel_size(BACKGROUND_BLUR_SIZE)
    background = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
    normalized = cv2.normalize(
        cv2.subtract(background, gray), None, 0, 255, cv2.NORM_MINMAX
    )
    _, threshold = cv2.threshold(
        normalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    kernel_size = odd_kernel_size(MORPHOLOGY_KERNEL_SIZE)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
    )
    opened = cv2.morphologyEx(threshold, cv2.MORPH_OPEN, kernel)
    cleaned = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(
        cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    return cleaned, preliminary_filter(contours, width, height), normalized, threshold, background


# ---------------------------------------------------------------------------
# ROI-local statistics helpers. All operate inside small candidate ROIs only,
# never on full-image masks, and reuse the cached gray / edge arrays.
# ---------------------------------------------------------------------------
def masked_region_stats(gray_roi, mask):
    count = int(cv2.countNonZero(mask))
    if count == 0:
        return None
    values = gray_roi[mask > 0]
    return {
        "count": count,
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "q10": float(np.percentile(values, 10)),
        "q25": float(np.percentile(values, 25)),
        "q75": float(np.percentile(values, 75)),
        "q90": float(np.percentile(values, 90)),
    }


def masked_edge_density(edge01_roi, mask):
    count = int(cv2.countNonZero(mask))
    if count == 0:
        return 0.0
    return float(cv2.mean(edge01_roi, mask=mask)[0])


def build_ring_masks(roi_mask, inner_radius, outer_radius):
    """Return (inner_ring, outer_ring) band masks around a filled region.

    Small/medium ROIs use the exact morphological dilation (identical to the
    legacy detector); very large ROIs fall back to an equivalent
    distance-transform band so no per-candidate giant-kernel dilation occurs.
    """
    roi_height, roi_width = roi_mask.shape
    cost = roi_height * roi_width * (2 * outer_radius + 1) ** 2
    if cost <= RING_DILATE_COST_LIMIT:
        inner_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (inner_radius * 2 + 1, inner_radius * 2 + 1)
        )
        outer_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (outer_radius * 2 + 1, outer_radius * 2 + 1)
        )
        inner_ring = cv2.subtract(cv2.dilate(roi_mask, inner_kernel), roi_mask)
        outer_region = cv2.dilate(roi_mask, outer_kernel)
        outer_ring = cv2.subtract(outer_region, cv2.dilate(roi_mask, inner_kernel))
    else:
        background_mask = cv2.bitwise_not(roi_mask)
        distance = cv2.distanceTransform(background_mask, cv2.DIST_L2, 5)
        inner_ring = np.uint8(
            (distance >= 0.5) & (distance <= inner_radius + 0.5)
        ) * 255
        outer_ring = np.uint8(
            (distance > inner_radius + 0.5) & (distance <= outer_radius + 0.5)
        ) * 255
    return inner_ring, outer_ring


def contour_features(contour, ctx):
    gray = ctx["gray"]
    edge01 = ctx["edge01"]
    width = ctx["width"]
    height = ctx["height"]
    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)
    if perimeter == 0:
        return None
    hull_area = cv2.contourArea(cv2.convexHull(contour))
    if hull_area == 0:
        return None
    x, y, box_width, box_height = cv2.boundingRect(contour)
    largest_side = max(box_width, box_height)
    ring_radius = max(3, int(largest_side * OUTER_RING_SCALE))
    roi_x = max(0, x - ring_radius)
    roi_y = max(0, y - ring_radius)
    roi_right = min(width, x + box_width + ring_radius)
    roi_bottom = min(height, y + box_height + ring_radius)
    roi_gray = gray[roi_y:roi_bottom, roi_x:roi_right]
    roi_mask = np.zeros(roi_gray.shape, dtype=np.uint8)
    shifted_contour = contour.copy()
    shifted_contour[:, 0, 0] -= roi_x
    shifted_contour[:, 0, 1] -= roi_y
    cv2.drawContours(roi_mask, [shifted_contour], -1, 255, -1)
    inside = masked_region_stats(roi_gray, roi_mask)
    if inside is None or inside["count"] == 0:
        return None
    inner_radius = max(2, int(largest_side * INNER_RING_SCALE))
    outer_radius = max(inner_radius + 1, ring_radius)
    inner_ring_mask, outer_ring_mask = build_ring_masks(
        roi_mask, inner_radius, outer_radius
    )
    inner_stats = masked_region_stats(roi_gray, inner_ring_mask)
    outer_stats = masked_region_stats(roi_gray, outer_ring_mask)
    inner_mean = inner_stats["mean"] if inner_stats else 0.0
    outer_mean = outer_stats["mean"] if outer_stats else 0.0
    inner_median = inner_stats["median"] if inner_stats else 0.0
    outer_median = outer_stats["median"] if outer_stats else 0.0
    # Darkness-consistency metrics (ROI-local): how much of the contour is
    # genuinely darker than the local matrix transition, plus interior spread.
    interior_values = roi_gray[roi_mask > 0]
    if interior_values.size:
        interior_std = float(interior_values.std())
        interior_median_value = inside["median"]
        if outer_median > interior_median_value:
            dark_level = 0.5 * (interior_median_value + outer_median)
        elif inner_median > interior_median_value:
            dark_level = 0.5 * (interior_median_value + inner_median)
        else:
            dark_level = 0.5 * (interior_median_value + inside["q90"])
        dark_fraction = float((interior_values <= dark_level).mean())
        core_level = 0.5 * (interior_median_value + inside["q10"])
        dark_core_fraction = float((interior_values <= core_level).mean())
    else:
        interior_std = 0.0
        dark_fraction = 0.0
        dark_core_fraction = 0.0
    roi_edge = edge01[roi_y:roi_bottom, roi_x:roi_right]
    inside_edge_density = masked_edge_density(roi_edge, roi_mask)
    inner_edge_density = masked_edge_density(roi_edge, inner_ring_mask)
    outer_edge_density = masked_edge_density(roi_edge, outer_ring_mask)
    # Fragmentation: count of significant dark fragments in the ROI.
    dark_threshold = int(max(0, outer_mean - 0.5 * (outer_mean - inside["mean"])))
    dark_mask = cv2.inRange(roi_gray, 0, dark_threshold)
    components, _, component_stats, _ = cv2.connectedComponentsWithStats(dark_mask)
    significant_fragments = sum(
        component_stats[index, cv2.CC_STAT_AREA] >= 4
        for index in range(1, components)
    )
    fragmentation = min(1.0, max(0, significant_fragments - 1) / 5.0)
    return {
        "area": area,
        "circularity": 4 * math.pi * area / (perimeter * perimeter),
        "solidity": area / hull_area,
        "aspect_ratio": max(box_width, box_height) / max(1, min(box_width, box_height)),
        "extent": area / max(1, box_width * box_height),
        "inside_mean": inside["mean"],
        "local_contrast": inner_mean - inside["mean"],
        "outer_contrast": outer_mean - inside["mean"],
        "inside_edge_density": inside_edge_density,
        "inner_edge_density": inner_edge_density,
        "outer_edge_density": outer_edge_density,
        "fragmentation": fragmentation,
        "interior_median": inside["median"],
        "interior_q10": inside["q10"],
        "interior_q90": inside["q90"],
        "interior_spread": inside["q90"] - inside["q10"],
        "interior_std": interior_std,
        "dark_fraction": dark_fraction,
        "dark_core_fraction": dark_core_fraction,
        "inner_median": inner_median,
        "outer_median": outer_median,
        "x": x,
        "y": y,
        "width": box_width,
        "height": box_height,
    }


def candidate_centroid(contour):
    moments = cv2.moments(contour)
    if moments["m00"] == 0:
        x, y, width, height = cv2.boundingRect(contour)
        return x + width / 2, y + height / 2
    return moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]


def bounding_box_iou_from_boxes(first_bbox, second_bbox):
    first_x, first_y, first_width, first_height = first_bbox
    second_x, second_y, second_width, second_height = second_bbox
    left = max(first_x, second_x)
    top = max(first_y, second_y)
    right = min(first_x + first_width, second_x + second_width)
    bottom = min(first_y + first_height, second_y + second_height)
    intersection = max(0, right - left) * max(0, bottom - top)
    union = (first_width * first_height + second_width * second_height
             - intersection)
    return intersection / union if union else 0


def bounding_box_iou(first, second):
    return bounding_box_iou_from_boxes(
        cv2.boundingRect(first), cv2.boundingRect(second)
    )


def boxes_intersect(first_bbox, second_bbox):
    first_x, first_y, first_width, first_height = first_bbox
    second_x, second_y, second_width, second_height = second_bbox
    return (first_x < second_x + second_width
            and second_x < first_x + first_width
            and first_y < second_y + second_height
            and second_y < first_y + first_height)


def candidates_match(first_contour, second_contour, first_bbox, second_bbox):
    if not boxes_intersect(first_bbox, second_bbox):
        return False
    overlap = bounding_box_iou_from_boxes(first_bbox, second_bbox)
    first_center = candidate_centroid(first_contour)
    second_center = candidate_centroid(second_contour)
    center_distance = math.hypot(
        first_center[0] - second_center[0], first_center[1] - second_center[1]
    )
    scale = max(first_bbox[2], first_bbox[3], second_bbox[2], second_bbox[3])
    first_x, first_y, first_width, first_height = first_bbox
    second_x, second_y, second_width, second_height = second_bbox
    first_inside = (second_x <= first_center[0] <= second_x + second_width
                    and second_y <= first_center[1] <= second_y + second_height)
    second_inside = (first_x <= second_center[0] <= first_x + first_width
                     and first_y <= second_center[1] <= first_y + first_height)
    return overlap >= CONTOUR_MATCH_IOU or (overlap > 0 and (
        first_inside or second_inside or center_distance <= scale * 0.5
    ))


def is_image_wide_artifact(contour, width, height):
    area = cv2.contourArea(contour)
    x, y, contour_width, contour_height = cv2.boundingRect(contour)
    border_count = sum((x <= 0, y <= 0,
                        x + contour_width >= width,
                        y + contour_height >= height))
    return area > width * height * MAX_ARTIFACT_AREA_RATIO or border_count >= 2


def pair_contour_overlap(first, second):
    """Pixel-level overlap stats between two filled contours."""
    first_x, first_y, first_width, first_height = cv2.boundingRect(first)
    second_x, second_y, second_width, second_height = cv2.boundingRect(second)
    left = min(first_x, second_x)
    top = min(first_y, second_y)
    right = max(first_x + first_width, second_x + second_width)
    bottom = max(first_y + first_height, second_y + second_height)
    width = right - left + 1
    height = bottom - top + 1
    first_mask = np.zeros((height, width), dtype=np.uint8)
    second_mask = np.zeros((height, width), dtype=np.uint8)
    first_shifted = first.copy()
    first_shifted[:, 0, 0] -= left
    first_shifted[:, 0, 1] -= top
    second_shifted = second.copy()
    second_shifted[:, 0, 0] -= left
    second_shifted[:, 0, 1] -= top
    cv2.drawContours(first_mask, [first_shifted], -1, 255, -1)
    cv2.drawContours(second_mask, [second_shifted], -1, 255, -1)
    intersection = cv2.countNonZero(cv2.bitwise_and(first_mask, second_mask))
    if intersection == 0:
        return 0.0, 0.0, 0.0
    first_area = cv2.countNonZero(first_mask)
    second_area = cv2.countNonZero(second_mask)
    union = first_area + second_area - intersection
    iou = intersection / max(1, union)
    return iou, intersection / max(1, first_area), intersection / max(1, second_area)


# ---------------------------------------------------------------------------
# Merging with source-aware candidate resolution.
# ---------------------------------------------------------------------------
def merge_detection_candidates(original_contours, robust_contours, width, height):
    merged = []
    both_count = 0
    for contour in original_contours:
        if is_image_wide_artifact(contour, width, height):
            continue
        merged.append({
            "contour": contour,
            "source": "original",
            "options": [contour],
        })
    for robust_contour in robust_contours:
        if is_image_wide_artifact(robust_contour, width, height):
            continue
        robust_bbox = cv2.boundingRect(robust_contour)
        match = next(
            (item for item in merged
             if candidates_match(robust_contour, item["contour"],
                                 robust_bbox,
                                 cv2.boundingRect(item["contour"]))),
            None
        )
        if match is not None:
            if match["source"] == "original":
                both_count += 1
            match["source"] = "both"
            match["options"].append(robust_contour)
        else:
            merged.append({
                "contour": robust_contour,
                "source": "robust",
                "options": [robust_contour],
            })
    large_original = sum(
        item["source"] in {"original", "both"}
        and cv2.contourArea(item["contour"]) >= width * height * LARGE_CONTOUR_AREA_RATIO
        for item in merged
    )
    return merged, {
        "original": len(original_contours),
        "robust": len(robust_contours),
        "both": both_count,
        "large_original": large_original,
    }


def parent_protected_both(entries):
    """When a robust contour is nested inside a much larger original/both
    contour, keep the larger parent instead of the interior fragment."""
    if len(entries) < 2:
        return None, None
    by_area = sorted(entries, key=lambda pair: pair[1]["area"], reverse=True)
    big_contour, big_feature = by_area[0]
    small_contour, small_feature = by_area[-1]
    if big_feature["area"] < small_feature["area"] * 4:
        return None, None
    bx, by, bw, bh = (big_feature["x"], big_feature["y"],
                      big_feature["width"], big_feature["height"])
    sx, sy, sw, sh = (small_feature["x"], small_feature["y"],
                      small_feature["width"], small_feature["height"])
    inside_box = (sx >= bx - NESTED_MARGIN and sy >= by - NESTED_MARGIN
                  and sx + sw <= bx + bw + NESTED_MARGIN
                  and sy + sh <= by + bh + NESTED_MARGIN)
    if not inside_box:
        return None, None
    _, _, cover_small = pair_contour_overlap(big_contour, small_contour)
    if cover_small >= NESTED_COVER:
        return big_contour, big_feature
    return None, None


def attach_candidate_features(candidates, ctx):
    """Compute each physical contour's features once and choose the best
    boundary when original + robust contours describe the same object."""
    memo = {}
    for candidate in candidates:
        options = candidate.get("options") or [candidate["contour"]]
        evaluated = []
        for option in options:
            feature = memo.get(id(option))
            if feature is None:
                feature = contour_features(option, ctx)
                if feature is not None:
                    memo[id(option)] = feature
            if feature is not None:
                evaluated.append((option, feature))
        if not evaluated:
            candidate["dropped"] = True
            continue
        big_contour, big_feature = parent_protected_both(evaluated)
        if big_contour is not None:
            candidate["contour"] = big_contour
            candidate["feature"] = big_feature
            continue
        if len(evaluated) > 1:
            chosen_contour, chosen_feature = max(
                evaluated,
                key=lambda pair: (pair[1]["local_contrast"]
                                  + pair[1]["outer_contrast"]
                                  + pair[1]["solidity"] * 10),
            )
            candidate["contour"] = chosen_contour
            candidate["feature"] = chosen_feature
        else:
            candidate["contour"], candidate["feature"] = evaluated[0]


def contour_quality(feature, source):
    return sum((
        feature["local_contrast"] >= SMALL_MIN_LOCAL_CONTRAST,
        feature["outer_contrast"] >= SMALL_MIN_LOCAL_CONTRAST,
        feature["inside_mean"] < 150,
        feature["solidity"] >= MIN_SOLIDITY,
        feature["circularity"] >= MIN_CIRCULARITY,
        feature["fragmentation"] <= MAX_FRAGMENTATION,
        feature["outer_edge_density"] <= MAX_SURROUNDING_EDGE_DENSITY,
        source == "original",
        source == "both",
    ))


def candidate_source_priority(source):
    if source == "both":
        return 2
    if source == "original":
        return 1
    return 0


def candidate_is_large(feature, width, height):
    return feature["area"] >= width * height * LARGE_CONTOUR_AREA_RATIO


def candidate_strong_object(feature):
    return (feature["local_contrast"] >= SMALL_MIN_LOCAL_CONTRAST
            and feature["solidity"] >= MIN_SOLIDITY
            and feature["circularity"] >= MIN_CIRCULARITY)


def resolve_duplicate_candidates(candidates, width, height):
    """Remove duplicate / nested candidate detections of the same object.

    Preferred source priority: both > original > robust.  A robust contour is
    not blindly discarded when it represents a separate neighbouring object.
    """
    stats = {"duplicate_removed": 0, "nested_removed": 0}
    removed = [False] * len(candidates)
    for index, candidate in enumerate(candidates):
        if removed[index]:
            continue
        feature = candidate["feature"]
        if feature is None:
            continue
        index_bbox = (feature["x"], feature["y"],
                      feature["width"], feature["height"])
        for other in range(index + 1, len(candidates)):
            if removed[other]:
                continue
            other_feature = candidates[other]["feature"]
            if other_feature is None:
                continue
            other_bbox = (other_feature["x"], other_feature["y"],
                          other_feature["width"], other_feature["height"])
            if not boxes_intersect(index_bbox, other_bbox):
                continue
            big_index = index if feature["area"] >= other_feature["area"] else other
            small_index = other if big_index == index else index
            big = candidates[big_index]
            small = candidates[small_index]
            big_feature = big["feature"]
            small_feature = small["feature"]
            # Nested candidate check -------------------------------------------------
            big_bbox = (big_feature["x"], big_feature["y"],
                        big_feature["width"], big_feature["height"])
            small_bbox = (small_feature["x"], small_feature["y"],
                          small_feature["width"], small_feature["height"])
            nested_box = (small_bbox[0] >= big_bbox[0] - NESTED_MARGIN
                          and small_bbox[1] >= big_bbox[1] - NESTED_MARGIN
                          and small_bbox[0] + small_bbox[2] <= big_bbox[0] + big_bbox[2] + NESTED_MARGIN
                          and small_bbox[1] + small_bbox[3] <= big_bbox[1] + big_bbox[3] + NESTED_MARGIN)
            small_protected = (candidate_source_priority(small["source"]) >= 1
                               and candidate_is_large(small_feature, width, height))
            if nested_box and not small_protected:
                _, _, cover_small = pair_contour_overlap(
                    big["contour"], small["contour"]
                )
                if (cover_small >= NESTED_COVER
                        and small_feature["area"] <= big_feature["area"] * NESTED_AREA_RATIO):
                    # A tiny interior texture contour inside a parent boundary is
                    # a nested duplicate; a strongly evidenced object is kept so
                    # two separate nodules touching in a cluster are preserved.
                    if not candidate_strong_object(small_feature) or small["source"] == "robust":
                        removed[small_index] = True
                        stats["nested_removed"] += 1
                        continue
            # Duplicate (same object) check -----------------------------------------
            bbox_iou = bounding_box_iou_from_boxes(index_bbox, other_bbox)
            if bbox_iou < DUPLICATE_BBOX_IOU:
                continue
            contour_iou, _, _ = pair_contour_overlap(
                candidates[index]["contour"], candidates[other]["contour"]
            )
            if contour_iou < DUPLICATE_IOU:
                continue
            first_center = candidate_centroid(candidates[index]["contour"])
            second_center = candidate_centroid(candidates[other]["contour"])
            center_distance = math.hypot(
                first_center[0] - second_center[0],
                first_center[1] - second_center[1],
            )
            scale = max(index_bbox[2], index_bbox[3],
                        other_bbox[2], other_bbox[3])
            if center_distance > scale * 0.7 + 8:
                continue
            first_priority = candidate_source_priority(candidates[index]["source"])
            second_priority = candidate_source_priority(candidates[other]["source"])
            if first_priority != second_priority:
                loser = other if first_priority > second_priority else index
            else:
                first_quality = contour_quality(
                    candidates[index]["feature"], candidates[index]["source"]
                )
                second_quality = contour_quality(
                    candidates[other]["feature"], candidates[other]["source"]
                )
                if first_quality != second_quality:
                    loser = other if first_quality > second_quality else index
                else:
                    loser = other if candidates[index]["feature"]["area"] >= candidates[other]["feature"]["area"] else index
            removed[loser] = True
            stats["duplicate_removed"] += 1
    return [candidate for keep, candidate in zip(
        [not flag for flag in removed], candidates) if keep], stats


# ---------------------------------------------------------------------------
# Fast neighbourhood / isolation metrics (bounding-box level, no full-image ops).
# ---------------------------------------------------------------------------
def compute_candidate_contexts(candidates, width, height):
    count = len(candidates)
    if count == 0:
        return
    centers_x = np.empty(count, dtype=np.float64)
    centers_y = np.empty(count, dtype=np.float64)
    radii = np.empty(count, dtype=np.float64)
    areas = np.empty(count, dtype=np.float64)
    for index, candidate in enumerate(candidates):
        feature = candidate["feature"]
        if feature is None:
            centers_x[index] = 0
            centers_y[index] = 0
            radii[index] = 0
            areas[index] = 0
            continue
        centers_x[index] = feature["x"] + feature["width"] / 2.0
        centers_y[index] = feature["y"] + feature["height"] / 2.0
        radii[index] = max(NEIGHBOR_MIN_RADIUS,
                           max(feature["width"], feature["height"]) * NEIGHBOR_RADIUS_SCALE)
        areas[index] = feature["area"]
    density = count / max(1, width * height)
    for index, candidate in enumerate(candidates):
        feature = candidate["feature"]
        if feature is None:
            candidate["context"] = {
                "nearby_count": 0,
                "nearby_area_ratio": 0.0,
                "nearby_small_fraction": 0.0,
                "relative_neighbors": 0.0,
                "isolation_score": 0.0,
            }
            continue
        radius = radii[index]
        distance_sq = ((centers_x - centers_x[index]) ** 2
                       + (centers_y - centers_y[index]) ** 2)
        radius_sq = radius * radius
        nearby = (distance_sq <= radius_sq) & (distance_sq > 0)
        nearby_count = int(nearby.sum())
        nearby_areas = areas[nearby]
        nearby_area_ratio = float(nearby_areas.sum()) / max(1.0, feature["area"])
        if nearby_count:
            nearby_small_fraction = float(
                (nearby_areas < feature["area"] * 0.5).mean()
            )
        else:
            nearby_small_fraction = 0.0
        expected = density * math.pi * radius * radius
        relative_neighbors = nearby_count / max(1.0, expected)
        neighbour_penalty = max(0.0, 1.0 - nearby_area_ratio / 12.0)
        relative_penalty = max(0.0, 1.0 - relative_neighbors / 2.2)
        isolation_score = 0.5 * neighbour_penalty + 0.5 * relative_penalty
        candidate["context"] = {
            "nearby_count": nearby_count,
            "nearby_area_ratio": nearby_area_ratio,
            "nearby_small_fraction": nearby_small_fraction,
            "relative_neighbors": relative_neighbors,
            "isolation_score": isolation_score,
        }


def robust_only_evidence(feature, context):
    """Stricter object-level evidence required from robust-only candidates."""
    evidence = 0
    if feature["interior_median"] <= ROBUST_DARK_MEDIAN:
        evidence += 1
    median_depth = feature["outer_median"] - feature["interior_median"]
    if (median_depth >= ROBUST_MED_DEPTH
            or feature["local_contrast"] >= LARGE_MIN_LOCAL_CONTRAST):
        evidence += 1
    if feature["interior_spread"] <= ROBUST_UNIFORM_SPREAD:
        evidence += 1
    if context["isolation_score"] >= ROBUST_ISOLATION:
        evidence += 1
    if feature["fragmentation"] <= CLUSTER_FRAGMENTATION:
        evidence += 1
    if context["nearby_small_fraction"] <= ROBUST_NEARBY_SMALL_FRACTION:
        evidence += 1
    return evidence


def texture_cluster_signals(feature, context, global_edge_density):
    """Combined texture-cluster evidence; never reject from one signal."""
    crowded = (context["nearby_count"] >= CLUSTER_NEIGHBOR_ABSOLUTE
               and context["relative_neighbors"] >= CLUSTER_NEIGHBOR_RELATIVE)
    edge_dense = max(feature["inner_edge_density"],
                     feature["outer_edge_density"]) > max(
        MAX_SURROUNDING_EDGE_DENSITY, global_edge_density * 1.5
    )
    fragmented = feature["fragmentation"] > CLUSTER_FRAGMENTATION
    weak_depth = (feature["outer_median"] - feature["interior_median"]
                  < CLUSTER_WEAK_DEPTH)
    dark_surround = feature["outer_median"] <= CLUSTER_DARK_MEDIAN
    return {
        "signals": sum((crowded, edge_dense, fragmented, weak_depth, dark_surround)),
        "crowded": crowded,
        "edge_dense": edge_dense,
        "fragmented": fragmented,
        "weak_depth": weak_depth,
        "dark_surround": dark_surround,
    }


def candidate_size_tier(feature, width, height):
    if feature["area"] < width * height * SMALL_AREA_RATIO:
        return "small"
    return "medium"


def score_minimum(tier, source):
    """Minimum combined evidence by (tier, source).  Source is a prior that
    adjusts the required evidence: both < original < robust.  Small
    candidates can never survive on their source alone."""
    if source == "both":
        return SCORE_MIN_BOTH_SMALL if tier == "small" else SCORE_MIN_BOTH_MEDIUM
    if source == "original":
        return (SCORE_MIN_ORIGINAL_SMALL if tier == "small"
                else SCORE_MIN_ORIGINAL_MEDIUM)
    return (SCORE_MIN_ROBUST_SMALL if tier == "small"
            else SCORE_MIN_ROBUST_MEDIUM)


def multi_scale_evidence(feature, context, global_edge_density):
    """Interpretable combined confidence from multi-scale evidence.

    Contributions (total ~10):
      darkness depth     interior vs inner/outer ring medians        (0..3)
      consistency        dark_fraction + interior spread             (0..3)
      local contrast     near-ring mean depth                        (0..1)
      interior clean     low interior edge density (solid object)    (0..1)
      shape support      solidity + circularity, soft only           (0..1)
      fragmentation      low internal fragmentation support          (0..1)
      context            isolation / crowding adjustment             (-.5..5)
    """
    depth = feature["outer_median"] - feature["interior_median"]
    if depth >= 40.0:
        dark = 3.0
    elif depth >= WEAK_MEDIAN_DEPTH:
        dark = 2.0
    elif depth >= 12.0:
        dark = 1.0
    else:
        dark = 0.0
    dark_fraction = feature["dark_fraction"]
    if dark_fraction >= DARK_FRACTION_STRONG:
        consistency = 2.0
    elif dark_fraction >= 0.60:
        consistency = 1.0
    elif dark_fraction >= 0.45:
        consistency = 0.5
    else:
        consistency = 0.0
    spread = feature["interior_spread"]
    if spread <= INTERIOR_SPREAD_UNIFORM:
        uniformity = 1.0
    elif spread <= INTERIOR_SPREAD_MODERATE:
        uniformity = 0.5
    else:
        uniformity = 0.0
    contrast = (1.0 if feature["local_contrast"] >= SMALL_MIN_LOCAL_CONTRAST
                else 0.0)
    interior_clean = (1.0 if feature["inside_edge_density"] <= TEXTURE_EDGE_CAP
                      else 0.0)
    shape = 0.0
    if feature["solidity"] >= MIN_SOLIDITY:
        shape += 0.5
    if feature["circularity"] >= 0.10:
        shape += 0.5
    fragmentation_ok = (1.0 if feature["fragmentation"] <= CLUSTER_FRAGMENTATION
                        else 0.0)
    context_term = 0.0
    if context is not None:
        if context.get("isolation_score", 0.0) >= 0.35:
            context_term += 0.5
        if context.get("nearby_count", 0) >= 12:
            context_term -= 0.5
    score = (dark + consistency + uniformity + contrast + interior_clean
             + shape + fragmentation_ok + context_term)
    surround_edge = max(feature["inner_edge_density"],
                        feature["outer_edge_density"])
    return {
        "score": score,
        "depth": depth,
        "dark_fraction": dark_fraction,
        "interior_spread": spread,
        "dark": dark,
        "consistency": consistency,
        "uniformity": uniformity,
        "contrast": contrast,
        "interior_clean": interior_clean,
        "fragmentation_ok": fragmentation_ok,
        "context_term": context_term,
        "surround_edge": surround_edge,
        "inside_edge": feature["inside_edge_density"],
    }


def validate_candidates(candidates, ctx):
    width = ctx["width"]
    height = ctx["height"]
    global_edge_density = ctx["global_edge_density"]
    image_area = width * height
    # Minimum graphite size: the legacy/original detector rejects contours
    # whose enclosing-circle diameter is below this length at selection time;
    # robust-only candidates and watershed children used to bypass that rule.
    min_graphite_diameter = width * legacy.min_grainsize
    selected = []
    stats = {
        "tiny": 0,
        "weak_contrast": 0,
        "high_texture": 0,
        "high_fragmentation": 0,
        "scratch_like": 0,
        "image_artifact": 0,
        "texture_cluster_rejected": 0,
        "robust_only_rejected": 0,
        "accepted_strong": 0,
        "accepted_protected": 0,
        "accepted_robust_only": 0,
        "protected_large": 0,
        "rejected_small_low_confidence": 0,
        "rejected_texture_dominated": 0,
        "rejected_low_dark_consistency": 0,
        "rejected_below_min_size_evidence": 0,
        "accepted_large_protected": 0,
        "accepted_medium": 0,
        "accepted_small": 0,
        "accepted_small_original": 0,
        "accepted_small_robust": 0,
        "accepted_small_both": 0,
        "accepted_original": 0,
        "accepted_robust": 0,
        "accepted_both": 0,
    }
    empty_context = {
        "nearby_count": 0,
        "nearby_area_ratio": 0.0,
        "nearby_small_fraction": 0.0,
        "relative_neighbors": 0.0,
        "isolation_score": 0.0,
    }
    for candidate in candidates:
        feature = candidate.get("feature")
        if feature is None:
            continue
        source = candidate["source"]
        contour = candidate["contour"]
        if feature["x"] <= 0 or feature["y"] <= 0:
            stats["image_artifact"] += 1
            continue
        if (feature["x"] + feature["width"] >= width
                or feature["y"] + feature["height"] >= height):
            stats["image_artifact"] += 1
            continue
        if feature["area"] < MIN_CONTOUR_AREA:
            stats["tiny"] += 1
            continue
        if feature["area"] > image_area * MAX_ARTIFACT_AREA_RATIO:
            stats["image_artifact"] += 1
            continue
        (_, _), enclosing_radius = cv2.minEnclosingCircle(contour)
        if 2 * enclosing_radius < min_graphite_diameter:
            stats["rejected_below_min_size_evidence"] += 1
            continue
        scratch_signals = sum((
            feature["aspect_ratio"] > MAX_ASPECT_RATIO,
            feature["circularity"] < MIN_CIRCULARITY,
            feature["solidity"] < MIN_SOLIDITY,
            feature["extent"] < 0.25,
        ))
        strong_scratch = scratch_signals >= 3
        weak_contrast = (feature["local_contrast"] < SMALL_MIN_LOCAL_CONTRAST
                         and feature["outer_contrast"] < SMALL_MIN_LOCAL_CONTRAST)
        high_texture = max(feature["inner_edge_density"],
                           feature["outer_edge_density"]) > max(
                               MAX_SURROUNDING_EDGE_DENSITY,
                               global_edge_density * 1.5
                           )
        high_fragmentation = feature["fragmentation"] > MAX_FRAGMENTATION
        is_large = candidate_is_large(feature, width, height)
        protected = (source in {"original", "both"} and is_large
                     and not strong_scratch)
        if protected:
            # Large original/both contours stay protected: they are only
            # removed when both darkness AND surrounding texture fail.
            if weak_contrast and high_texture:
                stats["weak_contrast"] += 1
                continue
            stats["accepted_protected"] += 1
            stats["protected_large"] += 1
            stats["accepted_large_protected"] += 1
            if source == "original":
                stats["accepted_original"] += 1
            else:
                stats["accepted_both"] += 1
            selected.append(contour)
            continue
        tier = candidate_size_tier(feature, width, height)
        context = candidate.get("context")
        if context is None:
            context = empty_context
        strong_object = candidate_strong_object(feature)
        if not is_large:
            cluster = texture_cluster_signals(feature, context,
                                              global_edge_density)
            if (cluster["signals"] >= CLUSTER_MIN_SIGNALS
                    and cluster["weak_depth"]
                    and not strong_object):
                stats["texture_cluster_rejected"] += 1
                continue
            if source == "robust":
                if robust_only_evidence(feature, context) < ROBUST_MIN_EVIDENCE:
                    stats["robust_only_rejected"] += 1
                    continue
        if weak_contrast:
            stats["weak_contrast"] += 1
            continue
        positive_score = sum((
            feature["local_contrast"] >= SMALL_MIN_LOCAL_CONTRAST,
            feature["outer_contrast"] >= SMALL_MIN_LOCAL_CONTRAST,
            feature["inside_mean"] < 150,
            feature["circularity"] >= MIN_CIRCULARITY,
            feature["solidity"] >= MIN_SOLIDITY,
            feature["aspect_ratio"] <= MAX_ASPECT_RATIO,
        ))
        required_score = SMALL_MIN_SCORE + (1 if source == "robust" else 0)
        evidence = multi_scale_evidence(feature, context,
                                        global_edge_density)
        minimum = score_minimum(tier, source)
        # Acceptance requires BOTH the legacy evidence signals and the new
        # multi-scale confidence minimum: the score layer only makes the
        # final decision stricter, never looser than the validated baseline.
        if (positive_score >= required_score
                and not high_texture
                and not high_fragmentation
                and evidence["score"] >= minimum):
            stats["accepted_strong"] += 1
            if tier == "small":
                stats["accepted_small"] += 1
                if source == "original":
                    stats["accepted_small_original"] += 1
                elif source == "robust":
                    stats["accepted_small_robust"] += 1
                else:
                    stats["accepted_small_both"] += 1
            else:
                stats["accepted_medium"] += 1
            if source == "original":
                stats["accepted_original"] += 1
            elif source == "robust":
                stats["accepted_robust"] += 1
                stats["accepted_robust_only"] += 1
            else:
                stats["accepted_both"] += 1
            selected.append(contour)
        elif high_texture:
            stats["high_texture"] += 1
        elif high_fragmentation:
            stats["high_fragmentation"] += 1
        elif evidence["score"] < minimum:
            # The combined score fell short: attribute to the dominant
            # weakness so counters stay mutually exclusive.
            if (evidence["depth"] < 12.0
                    or evidence["dark_fraction"] < DARK_FRACTION_WEAK
                    or evidence["interior_spread"] > INTERIOR_SPREAD_MODERATE):
                stats["rejected_low_dark_consistency"] += 1
            elif (evidence["surround_edge"] > max(
                      MAX_SURROUNDING_EDGE_DENSITY,
                      global_edge_density * 1.5)
                    or evidence["inside_edge"] > TEXTURE_EDGE_CAP):
                stats["rejected_texture_dominated"] += 1
            elif tier == "small":
                stats["rejected_small_low_confidence"] += 1
            else:
                stats["scratch_like"] += 1
        elif strong_scratch:
            stats["scratch_like"] += 1
        else:
            stats["scratch_like"] += 1
    return selected, stats


# ---------------------------------------------------------------------------
# Suspicion gating + selective watershed refinement.
# ---------------------------------------------------------------------------
def is_suspicious_contour(feature, width, height):
    signals = sum((
        feature["area"] >= width * height * SUSPICION_AREA_RATIO,
        feature["solidity"] < SUSPICION_SOLIDITY,
        feature["circularity"] < SUSPICION_CIRCULARITY,
        feature["aspect_ratio"] > SUSPICION_ASPECT_RATIO,
        feature["fragmentation"] > MAX_FRAGMENTATION,
        feature["inside_edge_density"] > feature["outer_edge_density"] * 1.5,
    ))
    return signals >= 2, signals


def split_separation(children):
    centroids = [candidate_centroid(child) for child in children]
    if len(centroids) < 2:
        return 0.0
    distances = [math.hypot(first[0] - second[0], first[1] - second[1])
                 for index, first in enumerate(centroids)
                 for second in centroids[index + 1:]]
    scales = [max(cv2.boundingRect(child)[2:]) for child in children]
    return min(distances) / max(1.0, max(scales))


def interior_is_single_blob(roi_gray, roi_mask, contour_area):
    """Cheap structural screen: no internal light valleys and a single dark
    core means the contour is one solid object, not a merge of several."""
    interior = roi_gray[roi_mask > 0]
    if interior.size == 0:
        return True
    median = float(np.median(interior))
    valley_level = int(min(255, median + VALLEY_LIFT))
    valley_mask = cv2.bitwise_and(
        cv2.inRange(roi_gray, valley_level, 255), roi_mask
    )
    components, _, component_stats, _ = cv2.connectedComponentsWithStats(valley_mask)
    valley_components = 0
    for component in range(1, components):
        component_area = component_stats[component, cv2.CC_STAT_AREA]
        if component_area >= max(VALLEY_MIN_AREA,
                                 contour_area * VALLEY_MIN_AREA_RATIO):
            valley_components += 1
    core_level = int(max(0, median - DARK_CORE_LIFT))
    core_mask = cv2.bitwise_and(
        cv2.inRange(roi_gray, 0, core_level), roi_mask
    )
    components, _, component_stats, _ = cv2.connectedComponentsWithStats(core_mask)
    core_components = 0
    for component in range(1, components):
        component_area = component_stats[component, cv2.CC_STAT_AREA]
        if component_area >= max(INTERIOR_STRUCTURE_MIN_AREA,
                                 contour_area * DARK_CORE_MIN_AREA_RATIO):
            core_components += 1
    return valley_components == 0 and core_components <= 1


def prepare_split_region(contour, ctx):
    """ROI + distance-transform peak analysis shared by the cheap suspicion
    gate and the watershed stage (no repeated distance transforms)."""
    gray = ctx["gray"]
    width = ctx["width"]
    height = ctx["height"]
    x, y, box_width, box_height = cv2.boundingRect(contour)
    padding = max(4, int(max(box_width, box_height) * 0.15))
    roi_x = max(0, x - padding)
    roi_y = max(0, y - padding)
    roi_right = min(width, x + box_width + padding)
    roi_bottom = min(height, y + box_height + padding)
    roi_gray = gray[roi_y:roi_bottom, roi_x:roi_right]
    roi_mask = np.zeros((roi_bottom - roi_y, roi_right - roi_x), dtype=np.uint8)
    shifted = contour.copy()
    shifted[:, 0, 0] -= roi_x
    shifted[:, 0, 1] -= roi_y
    cv2.drawContours(roi_mask, [shifted], -1, 255, -1)
    contour_area = cv2.contourArea(contour)
    if interior_is_single_blob(roi_gray, roi_mask, contour_area):
        return None
    distance = cv2.distanceTransform(roi_mask, cv2.DIST_L2, 5)
    maximum = float(distance.max())
    if maximum <= 0:
        return None
    peak_mask = np.uint8(distance >= maximum * MIN_SPLIT_PEAK_RELATIVE) * 255
    peak_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    peak_mask = cv2.dilate(peak_mask, peak_kernel)
    peak_count, _, _, peak_centroids = cv2.connectedComponentsWithStats(peak_mask)
    peaks = []
    for index in range(1, peak_count):
        point = peak_centroids[index]
        if all(math.hypot(point[0] - other[0], point[1] - other[1]) >= MIN_SPLIT_PEAK_DISTANCE
               for other in peaks):
            peaks.append(point)
    if len(peaks) < 2:
        return None
    return {
        "roi_x": roi_x,
        "roi_y": roi_y,
        "roi_mask": roi_mask,
        "roi_gray": roi_gray,
        "peaks": peaks,
    }


def split_prepared_contour(prepared, contour):
    gray = prepared["roi_gray"]
    roi_mask = prepared["roi_mask"]
    peaks = prepared["peaks"]
    roi_x = prepared["roi_x"]
    roi_y = prepared["roi_y"]
    markers = np.zeros(roi_mask.shape, dtype=np.int32)
    markers[roi_mask == 0] = 1
    for index, point in enumerate(peaks, 2):
        cv2.circle(markers, (int(point[0]), int(point[1])), 2, index, -1)
    roi_color = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    cv2.watershed(roi_color, markers)
    children = []
    parent_area = cv2.contourArea(contour)
    for index in range(2, len(peaks) + 2):
        component_mask = np.uint8(markers == index) * 255
        component_mask = cv2.bitwise_and(component_mask, roi_mask)
        child_contours, _ = cv2.findContours(
            component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
        )
        if not child_contours:
            continue
        child = max(child_contours, key=cv2.contourArea)
        child[:, 0, 0] += roi_x
        child[:, 0, 1] += roi_y
        if cv2.contourArea(child) >= parent_area * MIN_SPLIT_AREA_RATIO:
            children.append(child)
    if len(children) < 2:
        return []
    if sum(cv2.contourArea(child) for child in children) < parent_area * 0.65:
        return []
    return children


def refine_suspicious_candidates(candidates, ctx):
    """Selective ROI watershed refinement with a cheap pre-gate so watershed is
    only attempted when multiple cheap signals suggest several objects."""
    width = ctx["width"]
    height = ctx["height"]
    refined = []
    stats = {
        "refinement_candidates": 0,
        "refinement_skipped_cheap_gate": 0,
        "refinement_attempted": 0,
        "refinement_accepted": 0,
        "refinement_parent_retained": 0,
        "rejected_children": 0,
        "components": 0,
    }
    for candidate in candidates:
        feature = candidate.get("feature")
        if feature is None:
            feature = contour_features(candidate["contour"], ctx)
            candidate["feature"] = feature
        if feature is None:
            refined.append(candidate)
            continue
        suspicious, _ = is_suspicious_contour(feature, width, height)
        if not suspicious:
            refined.append(candidate)
            continue
        stats["refinement_candidates"] += 1
        prepared = prepare_split_region(candidate["contour"], ctx)
        if prepared is None:
            stats["refinement_skipped_cheap_gate"] += 1
            stats["refinement_parent_retained"] += 1
            refined.append(candidate)
            continue
        stats["refinement_attempted"] += 1
        children = split_prepared_contour(prepared, candidate["contour"])
        if len(children) < 2:
            stats["rejected_children"] += 1
            stats["refinement_parent_retained"] += 1
            refined.append(candidate)
            continue
        child_features = [contour_features(child, ctx) for child in children]
        if any(feature is None
               or feature["area"] < cv2.contourArea(candidate["contour"]) * MIN_SPLIT_AREA_RATIO
               for feature in child_features):
            stats["rejected_children"] += 1
            stats["refinement_parent_retained"] += 1
            refined.append(candidate)
            continue
        if sum(feature["local_contrast"] >= LARGE_MIN_LOCAL_CONTRAST
               and feature["outer_contrast"] >= LARGE_MIN_LOCAL_CONTRAST
               for feature in child_features) < 2:
            stats["rejected_children"] += 1
            stats["refinement_parent_retained"] += 1
            refined.append(candidate)
            continue
        separation = split_separation(children)
        if separation < MIN_SPLIT_SEPARATION_RATIO:
            stats["rejected_children"] += 1
            stats["refinement_parent_retained"] += 1
            refined.append(candidate)
            continue
        parent_score = contour_quality(feature, candidate["source"])
        child_score = sum(contour_quality(child_feature, candidate["source"])
                          for child_feature in child_features)
        if child_score < parent_score + MIN_SPLIT_SCORE_GAIN:
            stats["rejected_children"] += 1
            stats["refinement_parent_retained"] += 1
            refined.append(candidate)
            continue
        child_candidates = [{
            "contour": child,
            "source": candidate["source"],
            "parent": candidate["contour"],
            "feature": child_feature,
        } for child, child_feature in zip(children, child_features)]
        stats["refinement_accepted"] += 1
        stats["components"] += len(child_candidates)
        refined.extend(child_candidates)
    return refined, stats


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------
def choose_detection(gray, background, original_contours, robust_contours,
                     width, height):
    ctx = build_image_cache(gray, background, width, height)
    merged, merge_stats = merge_detection_candidates(
        original_contours, robust_contours, width, height
    )
    attach_candidate_features(merged, ctx)
    merged = [candidate for candidate in merged
              if not candidate.get("dropped")]
    refined, refinement_stats = refine_suspicious_candidates(merged, ctx)
    refined, duplicate_stats = resolve_duplicate_candidates(refined, width, height)
    compute_candidate_contexts(refined, width, height)
    final, validation_stats = validate_candidates(refined, ctx)
    stats = {}
    stats.update(merge_stats)
    stats.update(refinement_stats)
    stats.update(duplicate_stats)
    stats.update(validation_stats)
    stats["merged"] = len(merged)
    stats["final"] = len(final)
    # Aliases requested by the debug counter spec mirror primary counters so
    # every reported number corresponds to an actual decision path.
    stats["rejected_duplicate"] = (stats["duplicate_removed"]
                                    + stats["nested_removed"])
    stats["rejected_cluster_texture"] = stats["texture_cluster_rejected"]
    stats["rejected_small_texture_cluster"] = stats["texture_cluster_rejected"]
    stats["rejected_small_robust_low_evidence"] = stats["robust_only_rejected"]
    stats["accepted_large_protected"] = stats["protected_large"]
    return final, "hybrid", ctx["texture"], stats


def save_debug(debug_dir, stem, original_mask, robust_mask, final_contours,
               final_image):
    final_mask = original_mask * 0
    cv2.drawContours(final_mask, final_contours, -1, 255, -1)
    cv2.imwrite(str(debug_dir / (stem + "_original_mask.png")), original_mask)
    cv2.imwrite(str(debug_dir / (stem + "_robust_mask.png")), robust_mask)
    cv2.imwrite(str(debug_dir / (stem + "_final_mask.png")), final_mask)
    cv2.imwrite(str(debug_dir / (stem + "_final_annotated.png")), final_image)


def process_image(filename, annotated_dir, labels_dir, debug_dir):
    annotated_dir.mkdir(exist_ok=True)
    labels_dir.mkdir(exist_ok=True)
    if DEBUG:
        debug_dir.mkdir(exist_ok=True)
    color = cv2.imread(filename)
    if color is None:
        raise ValueError("Unable to read image: {}".format(filename))
    source_height, source_width = color.shape[:2]
    height = int(legacy.pic_width * source_height / source_width)
    color = cv2.resize(color, (legacy.pic_width, height))
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    original_mask, original_contours = original_detection(
        gray, legacy.pic_width, height
    )
    robust_mask, robust_contours, _, _, background = robust_detection(
        gray, legacy.pic_width, height
    )
    contours, method, texture, stats = choose_detection(
        gray, background, original_contours, robust_contours,
        legacy.pic_width, height
    )
    if DEBUG:
        print("{}: original={}, robust={}, both={}, merged={}, "
              "dup_removed={}, nested_removed={}, "
              "refinement_candidates={}, refinement_skipped_cheap={}, "
              "refinement_attempted={}, refinement_accepted={}, "
              "refinement_parent_retained={}, "
              "texture_cluster_rejected={}, robust_only_rejected={}, "
              "tiny={}, weak_contrast={}, high_texture={}, "
              "fragmentation={}, scratch_like={}, image_artifact={}, "
              "protected_large={}, strong={}, robust_only_accepted={}, "
              "final={}".format(
            Path(filename).name,
            stats["original"], stats["robust"], stats["both"], stats["merged"],
            stats["duplicate_removed"], stats["nested_removed"],
            stats["refinement_candidates"], stats["refinement_skipped_cheap_gate"],
            stats["refinement_attempted"], stats["refinement_accepted"],
            stats["refinement_parent_retained"],
            stats["texture_cluster_rejected"], stats["robust_only_rejected"],
            stats["tiny"], stats["weak_contrast"], stats["high_texture"],
            stats["high_fragmentation"], stats["scratch_like"],
            stats["image_artifact"], stats["protected_large"],
            stats["accepted_strong"], stats["accepted_robust_only"],
            stats["final"],
        ), flush=True)
        print("    evidence: large_protected={}, medium={}, small={} "
              "(orig={}/rob={}/both={}), "
              "reject small_low_conf={}, texture_dominated={}, "
              "low_dark_consistency={}, below_min_size={}, "
              "cluster_texture={}, dup={}".format(
            stats["accepted_large_protected"], stats["accepted_medium"],
            stats["accepted_small"], stats["accepted_small_original"],
            stats["accepted_small_robust"], stats["accepted_small_both"],
            stats["rejected_small_low_confidence"],
            stats["rejected_texture_dominated"],
            stats["rejected_low_dark_consistency"],
            stats["rejected_below_min_size_evidence"],
            stats["rejected_cluster_texture"], stats["rejected_duplicate"],
        ), flush=True)

    iso_image = color.copy()
    jis_image = color.copy()
    annotated_image = color.copy()
    labels = []
    graphite_area_total = 0
    graphite_area_round = 0
    jis_counts = [0, 0, 0, 0, 0]
    for index, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        graphite_area_total += area
        x, y, box_width, box_height = cv2.boundingRect(contour)
        labels.append("0 {:.6f} {:.6f} {:.6f} {:.6f}".format(
            (x + box_width / 2) / legacy.pic_width,
            (y + box_height / 2) / height,
            box_width / legacy.pic_width,
            box_height / height,
        ))
        cv2.drawContours(annotated_image, contours, index, (0, 0, 255), 2)
        hull = cv2.convexHull(contour)
        _, _, radius = legacy.get_graphite_length(hull)
        marumi = area / ((radius ** 2) * math.pi)
        if marumi >= legacy.marumi_ratio:
            graphite_area_round += area
            cv2.drawContours(iso_image, contours, index, (0, 0, 255), 2)
        if marumi <= 0.2:
            jis_counts[0] += 1
            cv2.drawContours(jis_image, contours, index, (255, 255, 0), 2)
        elif marumi <= 0.4:
            jis_counts[1] += 1
            cv2.drawContours(jis_image, contours, index, (0, 255, 0), 2)
        elif marumi <= 0.7:
            jis_counts[2] += 1
            cv2.drawContours(jis_image, contours, index, (128, 0, 128), 2)
        elif marumi <= 0.8:
            jis_counts[3] += 1
            cv2.drawContours(jis_image, contours, index, (255, 0, 0), 2)
        else:
            jis_counts[4] += 1
            cv2.drawContours(jis_image, contours, index, (0, 0, 255), 2)

    stem = Path(filename).stem
    extension = Path(filename).suffix
    cv2.imwrite(str(annotated_dir / (stem + extension)), annotated_image)
    cv2.imwrite(str(annotated_dir / (stem + "_nodularity(ISO)" + extension)), iso_image)
    cv2.imwrite(str(annotated_dir / (stem + "_nodularity(JIS)" + extension)), jis_image)
    with open(labels_dir / (stem + ".txt"), "w", encoding="utf-8") as label_file:
        label_file.write("\n".join(labels))
    if DEBUG:
        save_debug(debug_dir, stem, original_mask, robust_mask, contours, annotated_image)

    if graphite_area_total:
        iso = graphite_area_round / graphite_area_total * 100
    else:
        iso = 0
    if contours:
        jis = (0.3 * jis_counts[1] + 0.7 * jis_counts[2]
               + 0.9 * jis_counts[3] + jis_counts[4]) / len(contours) * 100
    else:
        jis = 0
    return iso, jis, method, texture, len(contours)


def main():
    base_dir = Path(__file__).resolve().parent
    input_dir = base_dir / "input_images"
    annotated_dir = base_dir / "annotated_images_adaptive"
    labels_dir = base_dir / "labels_adaptive"
    debug_dir = base_dir / "debug_images_adaptive"
    annotated_dir.mkdir(exist_ok=True)
    labels_dir.mkdir(exist_ok=True)
    if DEBUG:
        debug_dir.mkdir(exist_ok=True)
    filenames = find_input_images(input_dir)
    if not filenames:
        raise SystemExit("input_images contains no source jpg, jpeg, or png images.")

    results = []
    total_images = len(filenames)
    for index, filename in enumerate(filenames, 1):
        print("Processing {}/{}: {}".format(
            index, total_images, Path(filename).name
        ), flush=True)
        results.append((filename,) + process_image(
            filename, annotated_dir, labels_dir, debug_dir
        ))

    output_file = base_dir / ("nodularity_adaptive_{:%Y%m%d%H%M}.csv".format(
        datetime.datetime.now()
    ))
    with open(output_file, "w", encoding="utf-8") as csv_file:
        print("最小黒鉛サイズ, {:.3f}".format(legacy.min_grainsize), file=csv_file)
        print("丸み係数のしきい値, {:.3f}".format(legacy.marumi_ratio), file=csv_file)
        print("画像処理と出力画像の幅, {}".format(legacy.pic_width), file=csv_file)
        print("ファイル名, 球状化率_ISO法(%), 球状化率_JIS法(%), method, texture_score, detections", file=csv_file)
        for filename, iso, jis, method, texture, count in results:
            print("{}, {:.2f}, {:.2f}, {}, {:.3f}, {}".format(
                filename, iso, jis, method, texture, count
            ), file=csv_file)


if __name__ == "__main__":
    main()
