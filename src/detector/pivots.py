"""Batch pivot (swing high / swing low) detection and indexed storage.

PivotDetector is called once per pipeline run on the full DataFrame.
The resulting PivotStore is passed to all downstream detectors for O(log n)
range queries via bisect.
"""

import bisect
import logging

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from src.models import Pivot

logger = logging.getLogger(__name__)

# Multi-scale detection parameters: (left_bars, right_bars)
_SCALES: dict[str, tuple[int, int]] = {
    "minor":  (3, 3),
    "medium": (5, 5),
    "major":  (10, 10),
}


class PivotStore:
    """Indexed container for fast range queries on pre-computed pivots.

    Highs and lows are kept in separate lists sorted by DataFrame index.
    Range queries use bisect for O(log n) start/end lookup.

    Attributes:
        highs: Swing high pivots, sorted by index.
        lows: Swing low pivots, sorted by index.
    """

    def __init__(self, highs: list[Pivot], lows: list[Pivot]) -> None:
        """Initialise the store with pre-sorted pivot lists.

        Args:
            highs: List of swing high Pivot objects sorted by index.
            lows: List of swing low Pivot objects sorted by index.
        """
        self.highs = highs
        self.lows = lows
        # Pre-build index lists for bisect
        self._high_indices = [p.index for p in highs]
        self._low_indices = [p.index for p in lows]

    def in_range(
        self, start: int, end: int, pivot_type: str = "both"
    ) -> list[Pivot]:
        """Return pivots whose DataFrame index falls in [start, end].

        Args:
            start: Inclusive lower bound (DataFrame integer index).
            end: Inclusive upper bound (DataFrame integer index).
            pivot_type: "swing_high", "swing_low", or "both".

        Returns:
            Pivots within the range, sorted by index.
        """
        results: list[Pivot] = []
        if pivot_type in ("swing_high", "both"):
            results += self._slice(self.highs, self._high_indices, start, end)
        if pivot_type in ("swing_low", "both"):
            results += self._slice(self.lows, self._low_indices, start, end)
        results.sort(key=lambda p: p.index)
        return results

    def last_n(
        self, before_index: int, n: int, pivot_type: str = "both"
    ) -> list[Pivot]:
        """Return the n most recent pivots strictly before before_index.

        Args:
            before_index: Exclusive upper bound.
            n: Maximum number of pivots to return.
            pivot_type: "swing_high", "swing_low", or "both".

        Returns:
            Up to n pivots, sorted by index ascending.
        """
        candidates = self.in_range(0, before_index - 1, pivot_type)
        return candidates[-n:] if len(candidates) >= n else candidates

    def all(self, pivot_type: str = "both") -> list[Pivot]:
        """Return all pivots sorted by index.

        Args:
            pivot_type: "swing_high", "swing_low", or "both".

        Returns:
            All matching pivots sorted by index.
        """
        if pivot_type == "swing_high":
            return list(self.highs)
        if pivot_type == "swing_low":
            return list(self.lows)
        merged = self.highs + self.lows
        merged.sort(key=lambda p: p.index)
        return merged

    # ── Private ────────────────────────────────────────────────────────────────

    @staticmethod
    def _slice(
        pivots: list[Pivot], indices: list[int], start: int, end: int
    ) -> list[Pivot]:
        """Bisect-based slice of a sorted pivot list.

        Args:
            pivots: Sorted list of Pivot objects.
            indices: Pre-built list of integer indices (same order as pivots).
            start: Inclusive start index.
            end: Inclusive end index.

        Returns:
            Subset of pivots with index in [start, end].
        """
        lo = bisect.bisect_left(indices, start)
        hi = bisect.bisect_right(indices, end)
        return pivots[lo:hi]


class PivotDetector:
    """Multi-scale batch detector for swing highs and swing lows.

    Operates on the full DataFrame in a single pass using vectorised
    scipy.signal.find_peaks calls on the Enricher-computed smoothed columns.

    Pivot strength = number of scales (minor/medium/major) at which the
    candle is detected as a peak.

    Example:
        detector = PivotDetector()
        pivot_store = detector.compute_all(df)
    """

    def compute_all(self, df: pd.DataFrame) -> PivotStore:
        """Detect all swing highs and lows on the full DataFrame.

        Uses df['smoothed_high'] and df['smoothed_low'] (Enricher output).
        Each scale applies find_peaks with distance = left_bars + right_bars.
        Pivots detected at multiple scales receive a higher strength score.

        Args:
            df: Enriched OHLCV DataFrame (must have 'smoothed_high',
                'smoothed_low', and 'atr' columns).

        Returns:
            A PivotStore containing all detected highs and lows.
        """
        smooth_high = df["smoothed_high"].to_numpy()
        smooth_low = df["smoothed_low"].to_numpy()
        atr = df["atr"].to_numpy()
        timestamps = df.index.to_pydatetime()

        high_votes: dict[int, int] = {}
        low_votes: dict[int, int] = {}
        high_prominence: dict[int, float] = {}
        low_prominence: dict[int, float] = {}

        for scale, (left, right) in _SCALES.items():
            distance = left + right
            min_prominence = float(np.nanmedian(atr) * 0.5) if len(atr) else 0.0

            # Swing highs
            peaks_h, props_h = find_peaks(
                smooth_high,
                distance=distance,
                prominence=min_prominence,
            )
            for idx, prom in zip(peaks_h, props_h["prominences"]):
                high_votes[int(idx)] = high_votes.get(int(idx), 0) + 1
                high_prominence[int(idx)] = max(
                    high_prominence.get(int(idx), 0.0), float(prom)
                )

            # Swing lows (invert signal)
            peaks_l, props_l = find_peaks(
                -smooth_low,
                distance=distance,
                prominence=min_prominence,
            )
            for idx, prom in zip(peaks_l, props_l["prominences"]):
                low_votes[int(idx)] = low_votes.get(int(idx), 0) + 1
                low_prominence[int(idx)] = max(
                    low_prominence.get(int(idx), 0.0), float(prom)
                )

        highs = [
            Pivot(
                index=idx,
                timestamp=timestamps[idx],
                price=float(df["high"].iloc[idx]),
                pivot_type="swing_high",
                strength=votes,
                prominence=high_prominence[idx],
            )
            for idx, votes in sorted(high_votes.items())
        ]

        lows = [
            Pivot(
                index=idx,
                timestamp=timestamps[idx],
                price=float(df["low"].iloc[idx]),
                pivot_type="swing_low",
                strength=votes,
                prominence=low_prominence[idx],
            )
            for idx, votes in sorted(low_votes.items())
        ]

        logger.info(
            "%d swing highs, %d swing lows detected", len(highs), len(lows)
        )
        return PivotStore(highs, lows)
