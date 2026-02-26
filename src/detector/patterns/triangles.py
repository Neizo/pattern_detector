"""Ascending and descending triangle pattern detector.

Ascending triangle: horizontal resistance (RANSAC on swing highs) +
ascending support trendline (RANSAC on swing lows).
Descending triangle: descending resistance trendline + horizontal support.

Validation:
- Apex in the future (converging lines)
- Compression ratio (start gap / end gap) > 1.5
- Confirmed by volatility compression

Requires trendline results from TrendlineDetector.
Implementation is deferred — this skeleton satisfies the pipeline interface.
"""

import logging

import pandas as pd

from src.models import PatternResult
from src.detector.pivots import Pivot, PivotStore

logger = logging.getLogger(__name__)


class TriangleDetector:
    """Detects ascending and descending triangle chart patterns.

    Args:
        config: Pipeline configuration dictionary.

    Example:
        detector = TriangleDetector(config)
        results = detector.detect(df, pivot_store, current_pivot, 0, 600, trendlines)
    """

    def __init__(self, config: dict) -> None:
        """Initialise with pipeline configuration.

        Args:
            config: Pipeline configuration dict.
        """
        self._config = config

    def detect(
        self,
        df: pd.DataFrame,
        pivot_store: PivotStore,
        current_pivot: Pivot,
        win_start: int,
        win_end: int,
        trendlines: list[PatternResult],
    ) -> list[PatternResult]:
        """Detect ascending / descending triangles anchored at current_pivot.

        current_pivot must be the last pivot touching a triangle boundary.

        Args:
            df: Enriched OHLCV DataFrame.
            pivot_store: Pre-computed pivot store.
            current_pivot: Anchor pivot (last constitutive element).
            win_start: Inclusive start index of the context window.
            win_end: Inclusive end index (= current_pivot.index).
            trendlines: Trendline results from TrendlineDetector for this window.

        Returns:
            List of PatternResult objects (empty until implemented).
        """
        # TODO: implement ascending / descending triangle detection
        return []
