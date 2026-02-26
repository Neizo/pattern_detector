"""Consolidation (range / sideways market) pattern detector.

Criteria:
- KDE-based S/R cluster validation (≥ 2 touches on both support and resistance)
- Augmented Dickey-Fuller stationarity test (p-value < 0.05)
- Range width < 3.0 × ATR
- > 80 % of closes within the range
- Minimum duration: 20 candles

Requires level (S/R) results from LevelDetector.
Implementation is deferred — this skeleton satisfies the pipeline interface.
"""

import logging

import pandas as pd

from src.models import PatternResult
from src.detector.pivots import Pivot, PivotStore

logger = logging.getLogger(__name__)


class ConsolidationDetector:
    """Detects sideways consolidation / range patterns.

    Args:
        config: Pipeline configuration dictionary.

    Example:
        detector = ConsolidationDetector(config)
        results = detector.detect(df, pivot_store, current_pivot, 0, 600, levels)
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
        levels: list[PatternResult],
    ) -> list[PatternResult]:
        """Detect consolidation zones anchored at current_pivot.

        current_pivot must be the last pivot inside the range.

        Args:
            df: Enriched OHLCV DataFrame.
            pivot_store: Pre-computed pivot store.
            current_pivot: Anchor pivot (last constitutive element).
            win_start: Inclusive start index of the context window.
            win_end: Inclusive end index (= current_pivot.index).
            levels: Support/resistance results from LevelDetector.

        Returns:
            List of PatternResult objects (empty until implemented).
        """
        # TODO: implement consolidation detection
        return []
