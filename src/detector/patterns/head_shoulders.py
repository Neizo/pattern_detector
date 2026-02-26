"""Head & Shoulders and Inverse Head & Shoulders pattern detector.

Detects alternating sequences of 5 pivots: EG→L1→T→L2→ED (H&S) or
EG→H1→T→H2→ED (inverse H&S), where T is the head and EG/ED are shoulders.

Criteria (all thresholds in ATR multiples):
- Head prominence > 0.5 × ATR above shoulders
- Shoulder height asymmetry < 1.0 × ATR
- Pattern spans 20–300 candles
- Neckline quality scored by slope and touch precision

Implementation is deferred — this skeleton satisfies the pipeline interface.
"""

import logging

import pandas as pd

from src.models import PatternResult
from src.detector.pivots import Pivot, PivotStore

logger = logging.getLogger(__name__)


class HeadShouldersDetector:
    """Detects Head & Shoulders and Inverse Head & Shoulders patterns.

    Args:
        config: Pipeline configuration dictionary.

    Example:
        detector = HeadShouldersDetector(config)
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
        """Detect H&S / inverse H&S anchored at current_pivot.

        current_pivot must be ED (the second, final shoulder pivot).

        Args:
            df: Enriched OHLCV DataFrame.
            pivot_store: Pre-computed pivot store.
            current_pivot: Anchor pivot (last constitutive element).
            win_start: Inclusive start index of the context window.
            win_end: Inclusive end index (= current_pivot.index).

        Returns:
            List of PatternResult objects (empty until implemented).
        """
        # TODO: implement H&S / inverse H&S detection
        return []
