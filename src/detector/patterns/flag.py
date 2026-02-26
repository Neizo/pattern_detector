"""Flag pattern detector.

A flag consists of:
- Pole: strong impulsive move > 2 × ATR in < 20 candles (OLS R² > 0.85)
- Flag body: counter-trend consolidation channel (2 parallel RANSAC lines)
  with amplitude < 50 % of pole height, lasting 5–50 candles

Requires trendline results from TrendlineDetector.
Implementation is deferred — this skeleton satisfies the pipeline interface.
"""

import logging

import pandas as pd

from src.models import PatternResult
from src.detector.pivots import Pivot, PivotStore

logger = logging.getLogger(__name__)


class FlagDetector:
    """Detects flag chart patterns (bull and bear flags).

    Args:
        config: Pipeline configuration dictionary.

    Example:
        detector = FlagDetector(config)
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
        """Detect flag patterns anchored at current_pivot.

        current_pivot must be the last pivot within the flag channel.

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
        # TODO: implement flag detection
        return []
