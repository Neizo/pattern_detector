"""Tests for PivotDetector and PivotStore."""

import numpy as np
import pandas as pd
import pytest

from src.enricher import Enricher
from src.detector.pivots import PivotDetector, PivotStore, Pivot


def _make_df_with_peaks(n: int = 100) -> pd.DataFrame:
    """Build a synthetic enriched DataFrame with clear swing highs/lows."""
    rng = np.random.default_rng(0)
    # Sine wave to create clear pivots
    t = np.linspace(0, 4 * np.pi, n)
    base = np.sin(t) * 0.01 + 1.1
    noise = rng.normal(0, 0.0005, n)
    close = base + noise
    high = close + rng.uniform(0.001, 0.002, n)
    low = close - rng.uniform(0.001, 0.002, n)
    open_ = close - rng.normal(0, 0.0005, n)

    idx = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "volume": np.ones(n) * 500},
        index=idx,
    )
    enricher = Enricher()
    return enricher.enrich(df, "H4")


def test_compute_all_returns_pivot_store() -> None:
    """PivotDetector.compute_all returns a PivotStore instance."""
    df = _make_df_with_peaks()
    detector = PivotDetector()
    store = detector.compute_all(df)

    assert isinstance(store, PivotStore)


def test_pivot_store_detects_highs_and_lows() -> None:
    """PivotStore contains at least some highs and lows on a sine-wave dataset."""
    df = _make_df_with_peaks()
    store = PivotDetector().compute_all(df)

    assert len(store.highs) > 0
    assert len(store.lows) > 0


def test_pivot_store_in_range() -> None:
    """in_range returns only pivots within the given index bounds."""
    df = _make_df_with_peaks()
    store = PivotDetector().compute_all(df)

    pivots = store.in_range(0, 50)
    for p in pivots:
        assert 0 <= p.index <= 50


def test_pivot_store_all_sorted() -> None:
    """all() returns pivots sorted by index."""
    df = _make_df_with_peaks()
    store = PivotDetector().compute_all(df)

    all_pivots = store.all()
    indices = [p.index for p in all_pivots]
    assert indices == sorted(indices)


def test_pivot_store_last_n() -> None:
    """last_n returns at most n pivots strictly before the given index."""
    df = _make_df_with_peaks()
    store = PivotDetector().compute_all(df)

    pivots = store.last_n(before_index=80, n=3)
    assert len(pivots) <= 3
    for p in pivots:
        assert p.index < 80


def test_pivot_strength_in_range() -> None:
    """Pivot strength is between 1 and 3 (one per detection scale)."""
    df = _make_df_with_peaks()
    store = PivotDetector().compute_all(df)

    for p in store.all():
        assert 1 <= p.strength <= 3
