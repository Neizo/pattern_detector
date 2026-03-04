"""Support and resistance level detector (KDE-based).

Uses Kernel Density Estimation on pivot prices within a sliding lookback
window to identify price clusters that act as support or resistance.

Algorithm per incoming pivot (current_pivot):
  1. Collect pivots in [current_index - level_lookback_bars, current_index]
  2. Run gaussian_kde with ATR-scaled bandwidth (0.5 × ATR / std)
  3. Sample density on a fine price grid; locate density peaks
  4. For each candidate level price:
       a. Touches     = pivots within ± TOUCH_ATR × ATR
       b. Anchor rule : current_pivot must be among the touches
       c. Validate    : >= level_min_touches, temporal spread, price reaction
       d. Score       : weighted composite (0–1) per PATTERNS.md §2
       e. Classify    : SUPPORT if current close > level, else RESISTANCE
  5. Return one PatternResult per validated level

Each level is emitted exactly once — at the moment current_pivot becomes
its latest touch.  This enforces the pipeline's "no-lookahead" contract and
avoids duplicate reporting.

Annotation keys populated (consumed by ChartRenderer):
    hlines : list[dict]  — {"price", "color", "width", "label"}
    zones  : list[dict]  — {"ymin", "ymax", "color", "alpha"}
"""

import logging

import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from scipy.stats import gaussian_kde

from src.models import PatternResult, PatternType
from src.detector.pivots import Pivot, PivotStore

logger = logging.getLogger(__name__)

# ── Annotation colours ──────────────────────────────────────────────────────
_COLOR_SUPPORT = "#26a69a"     # teal
_COLOR_RESISTANCE = "#ef5350"  # red

# ── ATR multiples (all price thresholds are ATR-relative) ──────────────────
_TOUCH_ATR_DEFAULT = 0.5  # pivot within ± N×ATR counts as a "touch"
_TOUCH_ATR_BY_TF: dict[str, float] = {
    "M15": 0.25,
    "M30": 0.25,
    "H1":  0.35,
    "H4":  0.50,
    "D1":  0.50,
    "W1":  0.50,
}
_ZONE_MAX_PRICE_RANGE_FRAC = 0.03  # cap: zone half-width ≤ 3% of visible range
_REACTION_ATR = 0.5       # minimum expected bounce after a touch
_LOOK_AHEAD_BARS = 5      # bars ahead to measure a bounce (capped at current)

# Post-validation merge: levels closer than this are fused (keeps best score)
_MERGE_DISTANCE_ATR_BY_TF: dict[str, float] = {
    "M15": 0.60,
    "M30": 0.60,
    "H1":  0.80,
    "H4":  1.00,
    "D1":  1.20,
    "W1":  1.20,
}
_MERGE_DISTANCE_ATR_DEFAULT = 1.0

# Maximum zone width in ATR — clamp zones that would be wider
_MAX_ZONE_WIDTH_ATR_BY_TF: dict[str, float] = {
    "M15": 0.50,
    "M30": 0.60,
    "H1":  0.80,
    "H4":  1.00,
    "D1":  1.00,
    "W1":  1.00,
}
_MAX_ZONE_WIDTH_ATR_DEFAULT = 1.0

# Minimum temporal clusters — touches must span ≥ 2 distinct time groups
_MIN_CLUSTER_GAP: dict[str, int] = {
    "M15": 40,   # ~10 h
    "M30": 30,   # ~15 h
    "H1":  20,   # ~20 h
    "H4":  10,   # ~40 h
    "D1":  8,    # ~8 days
    "W1":  4,    # ~4 weeks
}
_MIN_CLUSTER_GAP_DEFAULT = 20

# Broken level penalty: if price closed beyond the level between touches
_BREACH_ATR = 1.0               # close must exceed level by N×ATR to count
_BREACH_PENALTY_PER_EVENT = 0.35  # each breach reduces score by 35%

# Minimum number of pivots required for a meaningful KDE
_MIN_KDE_PIVOTS = 4


class LevelDetector:
    """Detects support and resistance levels via KDE on pivot prices.

    For each pivot passed to ``detect()``, the detector queries the pre-built
    PivotStore over a configurable lookback window, fits a Gaussian KDE, and
    validates each density peak as a candidate S/R level.

    Only levels for which *current_pivot* is the most recent touch are
    returned, ensuring each level is reported exactly once per new touch.

    Args:
        config: Pipeline configuration dictionary.

    Example:
        detector = LevelDetector(config)
        results = detector.detect(df, pivot_store, current_pivot, 0, 600,
                                  pair="EURUSD", timeframe="H4")
    """

    def __init__(self, config: dict) -> None:
        self._config = config

    def detect(
        self,
        df: pd.DataFrame,
        pivot_store: PivotStore,
        current_pivot: Pivot,
        win_start: int,
        win_end: int,
        pair: str = "",
        timeframe: str = "",
        visual_mode: bool = False,
    ) -> list[PatternResult]:
        """Detect S/R levels anchored at current_pivot.

        The KDE lookback is driven by config['level_lookback_bars'] (default
        600) and is *independent* of the rendering window (win_start/win_end).

        Args:
            df: Enriched OHLCV DataFrame (requires 'atr' column).
            pivot_store: Pre-computed pivot store for O(log n) range queries.
            current_pivot: Anchor — must be the last touch of any returned level.
            win_start: Inclusive start of the rendering context window.
            win_end: Inclusive end of the rendering context window
                (equals current_pivot.index).
            pair: Forex pair forwarded to PatternResult.
            timeframe: Timeframe forwarded to PatternResult.
            visual_mode: If True, skip anchor rule (current_pivot need not
                be a touch) to show all significant levels at once. For
                visual validation only — production pipeline leaves False.

        Returns:
            List of SUPPORT or RESISTANCE PatternResult objects.
            Empty if no level passes validation.
        """
        atr = float(df["atr"].iloc[current_pivot.index])
        if atr <= 0:
            return []

        # Resolve timeframe-adaptive touch tolerance
        touch_atr_mult = _TOUCH_ATR_BY_TF.get(timeframe, _TOUCH_ATR_DEFAULT)

        # ── 1. Collect pivots in lookback window ────────────────────────────
        # Clamp lookback to win_start so we never use pivots outside the
        # rendering window — avoids zones anchored on invisible touches.
        lookback: int = self._config.get("level_lookback_bars", 600)
        lb_start = max(win_start, current_pivot.index - lookback)
        context_pivots = pivot_store.in_range(lb_start, win_end)

        if len(context_pivots) < _MIN_KDE_PIVOTS:
            return []

        pivot_prices = np.array([p.price for p in context_pivots], dtype=float)

        # ── 2. KDE on pivot prices ──────────────────────────────────────────
        # ATR-scaled bandwidth: resolves individual price clusters better than
        # Silverman which over-smooths when pivot count is low.
        price_std = float(pivot_prices.std()) if len(pivot_prices) > 1 else 1.0
        bw = (touch_atr_mult * atr / price_std) if price_std > 0 else 0.1
        try:
            kde = gaussian_kde(pivot_prices, bw_method=bw)
        except np.linalg.LinAlgError:
            return []

        price_min, price_max = float(pivot_prices.min()), float(pivot_prices.max())
        if price_max <= price_min:
            return []

        grid = np.linspace(price_min, price_max, 1000)
        density = kde(grid)

        # ── 3. Density peaks → candidate level prices ───────────────────────
        prominence_floor = max(float(density.max()) * 0.10, 1e-12)
        candidate_idxs, _ = find_peaks(
            density,
            prominence=prominence_floor,
            distance=20,  # min 2 % of grid spacing between peaks
        )
        if len(candidate_idxs) == 0:
            return []

        candidate_prices = grid[candidate_idxs]

        # ── 4. Validate each candidate level ────────────────────────────────
        touch_tol = atr * touch_atr_mult
        # Safety cap: zone half-width ≤ 3% of visible price range
        price_range = float(
            df["high"].iloc[win_start:win_end + 1].max()
            - df["low"].iloc[win_start:win_end + 1].min()
        )
        if price_range > 0:
            touch_tol = min(touch_tol, price_range * _ZONE_MAX_PRICE_RANGE_FRAC)
        min_touches: int = self._config.get("level_min_touches", 2)
        current_price = float(df["close"].iloc[current_pivot.index])

        results: list[PatternResult] = []

        for level_price in candidate_prices:
            touches = [
                p for p in context_pivots
                if abs(p.price - level_price) <= touch_tol
            ]
            if len(touches) < min_touches:
                continue

            # Anchor rule: current_pivot must be one of the touches
            if not visual_mode and not any(t.index == current_pivot.index for t in touches):
                continue

            # Temporal spread (0 → all in one cluster; 1 → well spread)
            temporal_score = self._temporal_spread_score(touches)
            if temporal_score < 0.05 and len(touches) < 3:
                continue

            # Require touches to span ≥ 2 distinct temporal clusters
            min_gap = _MIN_CLUSTER_GAP.get(timeframe, _MIN_CLUSTER_GAP_DEFAULT)
            if self._count_temporal_clusters(touches, min_gap) < 2:
                continue

            # Price reaction at each touch (no-lookahead: capped at current)
            reactions = [
                self._measure_reaction(df, t, current_pivot.index)
                for t in touches
            ]
            avg_reaction = float(np.mean(reactions))
            # Relaxed threshold: require half the ideal average reaction
            if avg_reaction < atr * _REACTION_ATR * 0.5:
                continue

            score = self._score(
                touches=touches,
                temporal_score=temporal_score,
                avg_reaction=avg_reaction,
                atr=atr,
                current_index=current_pivot.index,
                lb_start=lb_start,
            )

            # Broken level penalty: penalise levels that were breached
            # Skip in visual_mode — each pivot acts as current_pivot which
            # changes the support/resistance direction unreliably.
            if not visual_mode:
                breach_count = self._count_breaches(
                    df, touches, level_price, atr, current_price
                )
                if breach_count > 0:
                    penalty = max(0.0, 1.0 - breach_count * _BREACH_PENALTY_PER_EVENT)
                    score *= penalty

            if score < self._config.get("render_min_confidence", 0.5):
                continue

            # Classify
            if current_price > level_price:
                pattern_type = PatternType.SUPPORT
                color = _COLOR_SUPPORT
                label = "S"
            else:
                pattern_type = PatternType.RESISTANCE
                color = _COLOR_RESISTANCE
                label = "R"

            result = PatternResult(
                pattern_type=pattern_type,
                pair=pair,
                timeframe=timeframe,
                timestamp_detected=current_pivot.timestamp,
                start_index=touches[0].index,
                end_index=current_pivot.index,
                confidence=score,
                key_points=[
                    {
                        "label": f"{label}_touch",
                        "index": t.index,
                        "price": t.price,
                        "strength": t.strength,
                    }
                    for t in touches
                ],
                atr_at_detection=atr,
                window_start_index=win_start,
                window_end_index=win_end,
                annotations={
                    "hlines": [
                        {
                            "price": float(level_price),
                            "color": color,
                            "width": 1.5,
                            "label": label,
                        }
                    ],
                    "zones": [
                        {
                            "ymin": float(level_price - touch_tol),
                            "ymax": float(level_price + touch_tol),
                            "color": color,
                            "alpha": 0.10,
                            "x_start_idx": max(touches[0].index, win_start),
                            "_touch_tol": float(touch_tol),
                        }
                    ],
                },
            )
            results.append(result)

        # ── 5. Deduplicate levels with identical touch sets ────────────
        results = self._deduplicate_by_touches(results)

        # ── 6. Merge nearby levels to eliminate KDE fragmentation ─────────
        results = self._merge_nearby_levels(results, atr, timeframe, current_price)

        if results:
            logger.debug(
                "%d level(s) anchored at pivot index %d (atr=%.5f)",
                len(results),
                current_pivot.index,
                atr,
            )
        return results

    # ── Private helpers ─────────────────────────────────────────────────────

    def _temporal_spread_score(self, touches: list[Pivot]) -> float:
        """0–1 score: how spread out in time are the touches.

        std(touch_indices) >= 50 bars → 1.0; 0 bars → 0.0.
        """
        if len(touches) <= 1:
            return 0.0
        spread = float(np.std([t.index for t in touches]))
        return min(1.0, spread / 50.0)

    def _measure_reaction(
        self, df: pd.DataFrame, touch: Pivot, cap_index: int
    ) -> float:
        """Price bounce after a touch, capped at cap_index (no lookahead).

        swing_high (resistance) → how far price fell after the touch.
        swing_low  (support)    → how far price rose after the touch.

        Args:
            df: Full OHLCV DataFrame.
            touch: Pivot marking the touch point.
            cap_index: Latest allowable look-ahead index (inclusive).

        Returns:
            Bounce magnitude in price units (≥ 0).
        """
        idx = touch.index
        look_end = min(idx + _LOOK_AHEAD_BARS + 1, cap_index + 1, len(df))
        if look_end <= idx + 1:
            return 0.0
        future = df.iloc[idx + 1: look_end]
        if future.empty:
            return 0.0
        if touch.pivot_type == "swing_high":
            return max(0.0, float(touch.price - future["low"].min()))
        return max(0.0, float(future["high"].max() - touch.price))

    def _score(
        self,
        touches: list[Pivot],
        temporal_score: float,
        avg_reaction: float,
        atr: float,
        current_index: int,
        lb_start: int,
    ) -> float:
        """Weighted confidence score (0–1).

        Weights:
            0.20 × normalized_touches
            0.30 × temporal_spread
            0.15 × avg_reaction_magnitude  (normalised by 2 × ATR)
            0.15 × recency_factor
            0.20 × pivot_strength   (avg strength: 1→0, 3→1)
        """
        # Touches component: 1 touch above min → small score; 10+ → 1.0
        normalized_touches = min(1.0, (len(touches) - 1) / 9.0)

        # Reaction component
        reaction_score = (
            min(1.0, avg_reaction / (2.0 * atr)) if atr > 0 else 0.0
        )

        # Recency: average normalised position of each touch in the lookback window
        # (lb_start → 0, current_index → 1)
        window = max(1, current_index - lb_start)
        recency_scores = [
            min(1.0, max(0.0, (t.index - lb_start) / window))
            for t in touches
        ]
        recency = float(np.mean(recency_scores))

        # Pivot quality: average strength of touch pivots (1=minor → 0, 3=major → 1)
        avg_strength = float(np.mean([t.strength for t in touches]))
        strength_score = min(1.0, (avg_strength - 1.0) / 2.0)

        score = (
            0.20 * normalized_touches
            + 0.30 * temporal_score
            + 0.15 * reaction_score
            + 0.15 * recency
            + 0.20 * strength_score
        )
        return float(np.clip(score, 0.0, 1.0))

    def _count_temporal_clusters(
        self, touches: list[Pivot], min_gap_bars: int
    ) -> int:
        """Count distinct temporal clusters among *touches*.

        A new cluster starts whenever the gap between consecutive touches
        (sorted by index) exceeds *min_gap_bars*.

        Returns:
            Number of clusters (≥ 1 when touches is non-empty).
        """
        if len(touches) <= 1:
            return len(touches)
        indices = sorted(t.index for t in touches)
        clusters = 1
        for i in range(1, len(indices)):
            if indices[i] - indices[i - 1] > min_gap_bars:
                clusters += 1
        return clusters

    def _count_breaches(
        self,
        df: pd.DataFrame,
        touches: list[Pivot],
        level_price: float,
        atr: float,
        current_price: float,
    ) -> int:
        """Count how many times price closed beyond the level between touches.

        Only checks the **relevant direction**: if current price is above the
        level (support), a breach is a close *below* the level.  If current
        price is below (resistance), a breach is a close *above*.

        Uses close prices (not high/low) so that mere wicks through the level
        are not penalised.

        Returns:
            Number of breach events (0 = level was never broken).
        """
        if len(touches) < 2:
            return 0

        sorted_touches = sorted(touches, key=lambda t: t.index)
        breach_thr = _BREACH_ATR * atr
        breaches = 0
        is_support = current_price > level_price

        for i in range(len(sorted_touches) - 1):
            idx_start = sorted_touches[i].index + 1
            idx_end = sorted_touches[i + 1].index
            if idx_end <= idx_start:
                continue
            closes = df["close"].iloc[idx_start:idx_end].values
            if is_support:
                # Support breach: price closed well below the level
                if np.any(closes < level_price - breach_thr):
                    breaches += 1
            else:
                # Resistance breach: price closed well above the level
                if np.any(closes > level_price + breach_thr):
                    breaches += 1

        return breaches

    def _deduplicate_by_touches(
        self, results: list[PatternResult]
    ) -> list[PatternResult]:
        """Remove levels that share the exact same set of touch indices.

        When two KDE peaks resolve to the same cluster of pivots, keep only
        the one with the highest confidence.
        """
        if len(results) <= 1:
            return results

        seen: dict[frozenset[int], PatternResult] = {}
        for r in results:
            touch_set = frozenset(kp["index"] for kp in r.key_points)
            if touch_set in seen:
                if r.confidence > seen[touch_set].confidence:
                    seen[touch_set] = r
            else:
                seen[touch_set] = r
        return list(seen.values())

    def _merge_nearby_levels(
        self,
        results: list[PatternResult],
        atr: float,
        timeframe: str = "",
        current_price: float = 0.0,
    ) -> list[PatternResult]:
        """Merge levels whose prices are within a TF-adaptive ATR distance.

        Uses **directional merge**: when two levels are close, the one kept
        depends on current price position:
        - Price above both → keep the higher (nearest support).
        - Price below both → keep the lower (nearest resistance).
        - Price between    → fall back to highest confidence.

        After merging, zone bounds are recomputed from actual touch prices
        rather than taking the union of prior zones (which inflated widths).

        Args:
            results: Validated PatternResult list (may be empty).
            atr: Current ATR for distance thresholds.
            timeframe: Timeframe key for adaptive merge distance.
            current_price: Current close price for directional selection.

        Returns:
            Deduplicated list of PatternResult, sorted by price.
        """
        if len(results) <= 1:
            return results

        merge_mult = _MERGE_DISTANCE_ATR_BY_TF.get(
            timeframe, _MERGE_DISTANCE_ATR_DEFAULT
        )
        merge_dist = merge_mult * atr

        max_zone_width = _MAX_ZONE_WIDTH_ATR_BY_TF.get(
            timeframe, _MAX_ZONE_WIDTH_ATR_DEFAULT
        ) * atr

        # Sort by the hline price
        def _level_price(r: PatternResult) -> float:
            return r.annotations["hlines"][0]["price"]

        results.sort(key=_level_price)

        merged: list[PatternResult] = [results[0]]
        for candidate in results[1:]:
            prev = merged[-1]
            p_prev = _level_price(prev)
            p_cand = _level_price(candidate)
            if abs(p_cand - p_prev) < merge_dist:
                # Directional merge: keep the level nearest to price action
                both_below = current_price > max(p_prev, p_cand)
                both_above = current_price < min(p_prev, p_cand)

                if both_below:
                    # Both are supports — keep the higher (nearest to price)
                    if p_cand > p_prev:
                        winner, loser = candidate, prev
                    else:
                        winner, loser = prev, candidate
                elif both_above:
                    # Both are resistances — keep the lower (nearest to price)
                    if p_cand < p_prev:
                        winner, loser = candidate, prev
                    else:
                        winner, loser = prev, candidate
                else:
                    # Price between the two — fall back to confidence
                    if candidate.confidence > prev.confidence:
                        winner, loser = candidate, prev
                    else:
                        winner, loser = prev, candidate

                # Combine key_points (deduplicate by index)
                seen_idx = {kp["index"] for kp in winner.key_points}
                for kp in loser.key_points:
                    if kp["index"] not in seen_idx:
                        winner.key_points.append(kp)
                        seen_idx.add(kp["index"])
                winner.key_points.sort(key=lambda kp: kp["index"])

                # Recompute hline price as confidence-weighted average
                w_price = _level_price(winner)
                l_price = _level_price(loser)
                total_conf = winner.confidence + loser.confidence
                if total_conf > 0:
                    new_price = (
                        w_price * winner.confidence + l_price * loser.confidence
                    ) / total_conf
                else:
                    new_price = w_price
                winner.annotations["hlines"][0]["price"] = float(new_price)

                # Recompute zone from actual touch dispersion
                touch_prices = [kp["price"] for kp in winner.key_points]
                zone_center = float(np.mean(touch_prices))
                # Use touch_tol from the winner as half-width basis
                w_zone = winner.annotations["zones"][0]
                l_zone = loser.annotations["zones"][0]
                touch_tol = w_zone.get("_touch_tol", atr * 0.3)
                zone_half = max(touch_tol, float(np.std(touch_prices)))
                # Clamp to max zone width
                zone_half = min(zone_half, max_zone_width / 2.0)

                w_zone["ymin"] = float(zone_center - zone_half)
                w_zone["ymax"] = float(zone_center + zone_half)
                w_zone["x_start_idx"] = min(
                    w_zone.get("x_start_idx", 0),
                    l_zone.get("x_start_idx", 0),
                )

                # Update start_index to earliest touch
                winner.start_index = min(
                    winner.start_index, loser.start_index
                )

                merged[-1] = winner
            else:
                merged.append(candidate)

        # Final pass: clamp any remaining zones that exceed max width
        for r in merged:
            zone = r.annotations["zones"][0]
            width = zone["ymax"] - zone["ymin"]
            if width > max_zone_width:
                center = (zone["ymax"] + zone["ymin"]) / 2.0
                zone["ymin"] = float(center - max_zone_width / 2.0)
                zone["ymax"] = float(center + max_zone_width / 2.0)

        return merged
