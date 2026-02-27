"""Main pipeline orchestrator.

Ties together all stages:
  1.   Loader   → DataFrame
  1.5  Enricher → enriched DataFrame
  2.0  PivotDetector → PivotStore (batch, once)
  2.1  Iteration over pivots → PatternResult list
  3.   Renderer → PNG images

Each (pair, timeframe) run is independent.
"""

import logging
import time
from pathlib import Path

import pandas as pd

from src.config import DEFAULT_CONFIG
from src.loader import CSVLoader
from src.enricher import Enricher
from src.models import PatternResult, Pivot
from src.detector.pivots import PivotDetector
from src.detector.levels import LevelDetector
from src.detector.trendlines import TrendlineDetector
from src.detector.patterns import (
    DoubleDetector,
    HeadShouldersDetector,
    TriangleDetector,
    FlagDetector,
    ConsolidationDetector,
)
from src.renderer import ChartRenderer

logger = logging.getLogger(__name__)


class PatternDetectorManager:
    """Orchestrates all pattern sub-detectors.

    Args:
        config: Pipeline configuration dictionary.
    """

    def __init__(self, config: dict) -> None:
        """Initialise all sub-detectors.

        Args:
            config: Pipeline configuration dict.
        """
        self._double = DoubleDetector(config)
        self._hs = HeadShouldersDetector(config)
        self._triangle = TriangleDetector(config)
        self._flag = FlagDetector(config)
        self._consolidation = ConsolidationDetector(config)

    def detect_all(
        self,
        df: pd.DataFrame,
        pivot_store,
        current_pivot: Pivot,
        win_start: int,
        win_end: int,
        levels: list[PatternResult],
        trendlines: list[PatternResult],
    ) -> list[PatternResult]:
        """Run all pattern detectors for the current pivot.

        Args:
            df: Enriched OHLCV DataFrame.
            pivot_store: Pre-computed PivotStore.
            current_pivot: Anchor pivot (last element of any detected pattern).
            win_start: Inclusive context window start.
            win_end: Inclusive context window end.
            levels: S/R PatternResults from LevelDetector.
            trendlines: Trendline PatternResults from TrendlineDetector.

        Returns:
            Combined list of all detected PatternResult objects.
        """
        results: list[PatternResult] = []
        results += self._double.detect(df, pivot_store, current_pivot, win_start, win_end)
        results += self._hs.detect(df, pivot_store, current_pivot, win_start, win_end)
        results += self._triangle.detect(
            df, pivot_store, current_pivot, win_start, win_end, trendlines
        )
        results += self._flag.detect(
            df, pivot_store, current_pivot, win_start, win_end, trendlines
        )
        results += self._consolidation.detect(
            df, pivot_store, current_pivot, win_start, win_end, levels
        )
        return results


class Pipeline:
    """Full detection pipeline for one (pair, timeframe) run.

    Args:
        config: Optional configuration dict; defaults to DEFAULT_CONFIG.

    Example:
        pipeline = Pipeline()
        images = pipeline.run("EURUSD", "H4")
    """

    def __init__(self, config: dict | None = None) -> None:
        """Initialise all pipeline components.

        Args:
            config: Override for DEFAULT_CONFIG. Missing keys fall back to
                DEFAULT_CONFIG values.
        """
        self._config: dict = {**DEFAULT_CONFIG, **(config or {})}

        self._loader = CSVLoader()
        self._enricher = Enricher()
        self._pivot_detector = PivotDetector()
        self._level_detector = LevelDetector(self._config)
        self._trendline_detector = TrendlineDetector(self._config)
        self._pattern_manager = PatternDetectorManager(self._config)
        self._renderer = ChartRenderer(self._config)

    def run(self, pair: str, timeframe: str) -> list[Path]:
        """Execute the full pipeline for a single pair/timeframe.

        Args:
            pair: Forex pair identifier (e.g. "EURUSD").
            timeframe: Chart timeframe (e.g. "H4").

        Returns:
            List of Paths to the generated PNG images.
        """
        t0 = time.monotonic()

        # ── Stage 1: Load ──────────────────────────────────────────────────────
        df = self._loader.load(pair, timeframe)
        logger.info("%s/%s loaded: %d rows", pair, timeframe, len(df))

        # ── Stage 1.5: Enrich ─────────────────────────────────────────────────
        df = self._enricher.enrich(df, timeframe)

        # ── Stage 2.0: Pivot pre-computation (batch, once) ────────────────────
        pivot_store = self._pivot_detector.compute_all(df)
        all_pivots = pivot_store.all()
        logger.info(
            "%d swing highs, %d swing lows detected",
            len(pivot_store.highs),
            len(pivot_store.lows),
        )

        # ── Stage 2.1: Iterate over pivots ────────────────────────────────────
        window_size: int = self._config["context_window_size"]
        all_results: list[PatternResult] = []

        for current_pivot in all_pivots:
            win_end = current_pivot.detection_index
            win_start = max(0, win_end - window_size + 1)

            levels = self._level_detector.detect(
                df, pivot_store, current_pivot, win_start, win_end,
                pair=pair, timeframe=timeframe,
            )
            trendlines = self._trendline_detector.detect(
                df, pivot_store, current_pivot, win_start, win_end
            )
            patterns = self._pattern_manager.detect_all(
                df, pivot_store, current_pivot, win_start, win_end,
                levels, trendlines,
            )
            all_results.extend(levels + trendlines + patterns)

        logger.info(
            "%d patterns detected across %d pivots",
            len(all_results),
            len(all_pivots),
        )

        # ── Stage 3: Render ───────────────────────────────────────────────────
        min_confidence: float = self._config["render_min_confidence"]
        renderable = [r for r in all_results if r.confidence >= min_confidence]
        images = [self._renderer.render(df, r) for r in renderable]

        elapsed = time.monotonic() - t0
        logger.info(
            "Completed %s/%s in %.1fs — %d patterns, %d images",
            pair,
            timeframe,
            elapsed,
            len(all_results),
            len(images),
        )
        return images
