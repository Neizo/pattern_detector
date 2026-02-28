"""Comparator — matches human annotations against algorithmic detections.

For each annotation type (levels, pivots, trendlines), computes:
  - Matched (true positives): algo detection corresponds to a human annotation
  - False positives: algo detection with no human match
  - False negatives: human annotation with no algo match
  - Precision & recall
"""

from __future__ import annotations


def compare(
    human_annotations: dict,
    algo_detections: dict,
    atr_median: float,
) -> dict:
    """Compare human annotations against algo detections.

    Args:
        human_annotations: Dict with keys levels, pivots, trendlines, patterns.
        algo_detections: Dict from DataProvider.get_detections().
        atr_median: Median ATR for distance normalization.

    Returns:
        Structured comparison report with summary + detail per type.
    """
    report = {
        "atr_median": round(atr_median, 6),
        "summary": {},
    }

    # ── Levels ───────────────────────────────────────────────────────────
    report["levels"] = _compare_levels(
        human_annotations.get("levels", []),
        algo_detections.get("levels", []),
        atr_median,
    )
    report["summary"]["levels"] = _summary(report["levels"])

    # ── Pivots ───────────────────────────────────────────────────────────
    report["pivots"] = _compare_pivots(
        human_annotations.get("pivots", []),
        algo_detections.get("pivots", []),
    )
    report["summary"]["pivots"] = _summary(report["pivots"])

    # ── Trendlines ───────────────────────────────────────────────────────
    report["trendlines"] = _compare_trendlines(
        human_annotations.get("trendlines", []),
        algo_detections.get("trendlines", []),
        atr_median,
    )
    report["summary"]["trendlines"] = _summary(report["trendlines"])

    return report


# ── Level matching ───────────────────────────────────────────────────────────


def _compare_levels(
    human_levels: list[dict],
    algo_levels: list[dict],
    atr: float,
) -> dict:
    """Match algo levels to human zones.

    Match criteria:
      - Algo price falls inside human zone [price_low, price_high]
      - OR distance to nearest zone edge < 0.3 × ATR
    Greedy: closest pair matched first, each side matched at most once.
    """
    tolerance = atr * 0.3

    # Build candidate pairs sorted by distance to zone center
    candidates = []
    for ai, algo in enumerate(algo_levels):
        ap = algo["price"]
        for hi, human in enumerate(human_levels):
            zone_center = (human["price_high"] + human["price_low"]) / 2
            inside = human["price_low"] <= ap <= human["price_high"]
            dist_edge = _dist_to_zone(ap, human["price_low"], human["price_high"])
            dist_center = abs(ap - zone_center)
            if inside or dist_edge <= tolerance:
                candidates.append((dist_center, ai, hi))

    candidates.sort(key=lambda x: x[0])

    matched_algo: set[int] = set()
    matched_human: set[int] = set()
    matched_pairs: list[dict] = []

    for dist_center, ai, hi in candidates:
        if ai in matched_algo or hi in matched_human:
            continue
        matched_algo.add(ai)
        matched_human.add(hi)
        matched_pairs.append({
            "human": human_levels[hi],
            "algo": algo_levels[ai],
            "algo_inside_zone": (
                human_levels[hi]["price_low"]
                <= algo_levels[ai]["price"]
                <= human_levels[hi]["price_high"]
            ),
            "distance_to_zone_center_atr": round(dist_center / atr, 4) if atr > 0 else 0,
        })

    false_positives = []
    for ai, algo in enumerate(algo_levels):
        if ai in matched_algo:
            continue
        nearest = _nearest_human_zone(algo["price"], human_levels, atr)
        false_positives.append({"algo": algo, "nearest_human_zone": nearest})

    false_negatives = []
    for hi, human in enumerate(human_levels):
        if hi in matched_human:
            continue
        nearest = _nearest_algo_level(human, algo_levels, atr)
        false_negatives.append({"human": human, "nearest_algo": nearest})

    return {
        "matched": matched_pairs,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


def _dist_to_zone(price: float, low: float, high: float) -> float:
    """Distance from price to nearest edge of a zone. 0 if inside."""
    if low <= price <= high:
        return 0.0
    return min(abs(price - low), abs(price - high))


def _nearest_human_zone(
    algo_price: float, human_levels: list[dict], atr: float
) -> dict | None:
    if not human_levels:
        return None
    best = None
    best_dist = float("inf")
    for h in human_levels:
        d = _dist_to_zone(algo_price, h["price_low"], h["price_high"])
        if d < best_dist:
            best_dist = d
            best = {
                "price_high": h["price_high"],
                "price_low": h["price_low"],
                "distance_to_nearest_edge_atr": round(best_dist / atr, 4) if atr > 0 else 0,
            }
    return best


def _nearest_algo_level(
    human: dict, algo_levels: list[dict], atr: float
) -> dict | None:
    if not algo_levels:
        return None
    zone_center = (human["price_high"] + human["price_low"]) / 2
    best = None
    best_dist = float("inf")
    for a in algo_levels:
        d = abs(a["price"] - zone_center)
        if d < best_dist:
            best_dist = d
            edge_dist = _dist_to_zone(a["price"], human["price_low"], human["price_high"])
            best = {
                "price": a["price"],
                "distance_to_zone_edge_atr": round(edge_dist / atr, 4) if atr > 0 else 0,
            }
    return best


# ── Pivot matching ───────────────────────────────────────────────────────────


def _compare_pivots(
    human_pivots: list[dict],
    algo_pivots: list[dict],
) -> dict:
    """Match pivots: same type AND index ±2 candles. Greedy closest-first."""
    tolerance = 2

    candidates = []
    for ai, algo in enumerate(algo_pivots):
        for hi, human in enumerate(human_pivots):
            if algo["type"] != human["type"]:
                continue
            dist = abs(algo["index"] - human["index"])
            if dist <= tolerance:
                candidates.append((dist, ai, hi))

    candidates.sort(key=lambda x: x[0])

    matched_algo: set[int] = set()
    matched_human: set[int] = set()
    matched_pairs: list[dict] = []

    for dist, ai, hi in candidates:
        if ai in matched_algo or hi in matched_human:
            continue
        matched_algo.add(ai)
        matched_human.add(hi)
        matched_pairs.append({
            "human": human_pivots[hi],
            "algo": algo_pivots[ai],
            "index_distance": dist,
        })

    false_positives = [
        {"algo": algo_pivots[ai]}
        for ai in range(len(algo_pivots))
        if ai not in matched_algo
    ]

    false_negatives = [
        {"human": human_pivots[hi]}
        for hi in range(len(human_pivots))
        if hi not in matched_human
    ]

    return {
        "matched": matched_pairs,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


# ── Trendline matching ──────────────────────────────────────────────────────


def _compare_trendlines(
    human_trendlines: list[dict],
    algo_trendlines: list[dict],
    atr: float,
) -> dict:
    """Match trendlines: same type, similar slope ±15%, ≥2 shared anchor points ±3 candles.

    Currently algo_trendlines is always [] (stub detector).
    """
    if not algo_trendlines or not human_trendlines:
        return {
            "matched": [],
            "false_positives": [{"algo": a} for a in algo_trendlines],
            "false_negatives": [{"human": h} for h in human_trendlines],
        }

    # When TrendlineDetector is implemented, matching logic goes here
    slope_tolerance = 0.15
    anchor_tolerance = 3
    min_shared_anchors = 2

    candidates = []
    for ai, algo in enumerate(algo_trendlines):
        for hi, human in enumerate(human_trendlines):
            if algo.get("type") != human.get("type"):
                continue

            # Compare slopes
            algo_pts = algo.get("points", [])
            human_pts = human.get("points", [])
            if len(algo_pts) < 2 or len(human_pts) < 2:
                continue

            algo_slope = (algo_pts[-1]["price"] - algo_pts[0]["price"]) / max(1, algo_pts[-1]["index"] - algo_pts[0]["index"])
            human_slope = (human_pts[-1]["price"] - human_pts[0]["price"]) / max(1, human_pts[-1]["index"] - human_pts[0]["index"])

            if abs(human_slope) > 1e-10:
                slope_diff = abs(algo_slope - human_slope) / abs(human_slope)
            else:
                slope_diff = abs(algo_slope - human_slope)

            if slope_diff > slope_tolerance:
                continue

            # Count shared anchor points
            shared = 0
            for ap in algo_pts:
                for hp in human_pts:
                    if abs(ap["index"] - hp["index"]) <= anchor_tolerance:
                        shared += 1
                        break

            if shared >= min_shared_anchors:
                candidates.append((slope_diff, ai, hi))

    candidates.sort(key=lambda x: x[0])

    matched_algo: set[int] = set()
    matched_human: set[int] = set()
    matched_pairs: list[dict] = []

    for slope_diff, ai, hi in candidates:
        if ai in matched_algo or hi in matched_human:
            continue
        matched_algo.add(ai)
        matched_human.add(hi)
        matched_pairs.append({
            "human": human_trendlines[hi],
            "algo": algo_trendlines[ai],
            "slope_diff_pct": round(slope_diff * 100, 2),
        })

    false_positives = [
        {"algo": algo_trendlines[ai]}
        for ai in range(len(algo_trendlines))
        if ai not in matched_algo
    ]
    false_negatives = [
        {"human": human_trendlines[hi]}
        for hi in range(len(human_trendlines))
        if hi not in matched_human
    ]

    return {
        "matched": matched_pairs,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────


def _summary(type_report: dict) -> dict:
    """Compute precision/recall from matched/FP/FN counts."""
    n_matched = len(type_report["matched"])
    n_fp = len(type_report["false_positives"])
    n_fn = len(type_report["false_negatives"])

    precision = n_matched / (n_matched + n_fp) if (n_matched + n_fp) > 0 else 0.0
    recall = n_matched / (n_matched + n_fn) if (n_matched + n_fn) > 0 else 0.0

    return {
        "matched": n_matched,
        "false_positives": n_fp,
        "false_negatives": n_fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
    }
