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
_TOUCH_ATR = 0.5          # pivot within ± N×ATR counts as a "touch"
_REACTION_ATR = 0.5       # minimum expected bounce after a touch
_LOOK_AHEAD_BARS = 5      # bars ahead to measure a bounce (capped at current)

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
        bw = (0.5 * atr / price_std) if price_std > 0 else 0.1
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
        touch_tol = atr * _TOUCH_ATR
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
                        }
                    ],
                },
            )
            results.append(result)

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

        Weights from PATTERNS.md §2:
            0.30 × normalized_touches
            0.30 × temporal_spread
            0.20 × avg_reaction_magnitude  (normalised by 2 × ATR)
            0.20 × recency_factor           (fraction of touches in recent half)
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

        score = (
            0.30 * normalized_touches
            + 0.30 * temporal_score
            + 0.20 * reaction_score
            + 0.20 * recency
        )
        return float(np.clip(score, 0.0, 1.0))
