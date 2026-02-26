"""Double top and double bottom pattern detector.

Detects two swing highs (double top) or two swing lows (double bottom) with:
- Price proximity < 0.75 × ATR between the two peaks/troughs
- Intermediate pivot of opposite type with strength ≥ 1
- Depth > 1.0 × ATR
- Spacing: 10–150 candles between the two peaks/troughs

Implementation is deferred — this skeleton satisfies the pipeline interface.
"""

import logging

import pandas as pd

from src.models import PatternResult
from src.detector.pivots import Pivot, PivotStore

logger = logging.getLogger(__name__)


class DoubleDetector:
    """Detects double top and double bottom chart patterns.

    Args:
        config: Pipeline configuration dictionary.

    Example:
        detector = DoubleDetector(config)
        results = detector.detect(df, pivot_store, current_pivot, 0, 600)
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
    ) -> list[PatternResult]:
        """Detect double top / double bottom anchored at current_pivot.

        current_pivot must be the second peak (H2) or second trough (L2).

        Args:
            df: Enriched OHLCV DataFrame.
            pivot_store: Pre-computed pivot store.
            current_pivot: Anchor pivot (last constitutive element).
            win_start: Inclusive start index of the context window.
            win_end: Inclusive end index (= current_pivot.index).

        Returns:
            List of PatternResult objects (empty until implemented).
        """
        # TODO: implement double top / double bottom detection
        return []
