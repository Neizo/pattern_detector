"""Tests for LevelDetector (KDE-based support/resistance)."""

import numpy as np
import pandas as pd
import pytest

from src.config import DEFAULT_CONFIG
from src.enricher import Enricher
from src.detector.pivots import PivotDetector
from src.detector.levels import LevelDetector
from src.models import PatternType


def _make_oscillating_df(n: int = 150) -> pd.DataFrame:
    """Sine-wave OHLCV that oscillates clearly between two price levels.

    The sine wave creates well-defined swing highs (~1.10) and swing lows
    (~1.08), giving the KDE a clear bimodal structure to detect.
    """
    rng = np.random.default_rng(42)
    t = np.linspace(0, 6 * np.pi, n)
    base = np.sin(t) * 0.010 + 1.090
    noise = rng.normal(0, 0.0003, n)
    close = base + noise
    high = close + rng.uniform(0.0005, 0.0015, n)
    low = close - rng.uniform(0.0005, 0.0015, n)
    open_ = close - rng.normal(0, 0.0005, n)
    idx = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "volume": np.ones(n) * 500},
        index=idx,
    )
    return Enricher().enrich(df, "H4")


def _last_pivot(df: pd.DataFrame):
    """Return (pivot_store, last_pivot) from the full DataFrame."""
    store = PivotDetector().compute_all(df)
    all_pivots = store.all()
    if not all_pivots:
        return store, None
    return store, all_pivots[-1]


# ── Basic contract tests ────────────────────────────────────────────────────

def test_detect_returns_list():
    """detect() always returns a list."""
    df = _make_oscillating_df()
    store, pivot = _last_pivot(df)
    if pivot is None:
        pytest.skip("No pivots in synthetic data")

    results = LevelDetector(DEFAULT_CONFIG).detect(
        df, store, pivot, 0, pivot.index
    )
    assert isinstance(results, list)


def test_detect_empty_on_insufficient_pivots():
    """Returns [] when the lookback window has fewer than _MIN_KDE_PIVOTS."""
    df = _make_oscillating_df()
    store, pivot = _last_pivot(df)
    if pivot is None:
        pytest.skip("No pivots")

    # Force a tiny lookback so at most 1-2 pivots are in range
    config = {**DEFAULT_CONFIG, "level_lookback_bars": 3}
    results = LevelDetector(config).detect(df, store, pivot, 0, pivot.index)
    assert isinstance(results, list)
    # With 3-bar lookback we expect no levels (< 4 pivots)
    assert len(results) == 0


# ── Result quality tests ────────────────────────────────────────────────────

def test_result_pattern_types():
    """All results are SUPPORT or RESISTANCE."""
    df = _make_oscillating_df()
    store, pivot = _last_pivot(df)
    if pivot is None:
        pytest.skip("No pivots")

    results = LevelDetector(DEFAULT_CONFIG).detect(
        df, store, pivot, 0, pivot.index
    )
    for r in results:
        assert r.pattern_type in (PatternType.SUPPORT, PatternType.RESISTANCE)


def test_confidence_in_range():
    """Confidence values are in [0, 1]."""
    df = _make_oscillating_df()
    store, pivot = _last_pivot(df)
    if pivot is None:
        pytest.skip("No pivots")

    results = LevelDetector(DEFAULT_CONFIG).detect(
        df, store, pivot, 0, pivot.index
    )
    for r in results:
        assert 0.0 <= r.confidence <= 1.0


def test_annotations_keys_present():
    """Each result has 'hlines' and 'zones' annotation keys."""
    df = _make_oscillating_df()
    store, pivot = _last_pivot(df)
    if pivot is None:
        pytest.skip("No pivots")

    results = LevelDetector(DEFAULT_CONFIG).detect(
        df, store, pivot, 0, pivot.index
    )
    for r in results:
        assert "hlines" in r.annotations
        assert "zones" in r.annotations
        assert len(r.annotations["hlines"]) >= 1
        assert len(r.annotations["zones"]) >= 1


def test_classification_support_below_price():
    """SUPPORT levels are priced below the current close."""
    df = _make_oscillating_df()
    store, pivot = _last_pivot(df)
    if pivot is None:
        pytest.skip("No pivots")

    current_price = float(df["close"].iloc[pivot.index])
    results = LevelDetector(DEFAULT_CONFIG).detect(
        df, store, pivot, 0, pivot.index
    )
    for r in results:
        level_price = r.annotations["hlines"][0]["price"]
        if r.pattern_type == PatternType.SUPPORT:
            assert level_price < current_price, (
                f"Support at {level_price} should be < current price {current_price}"
            )


def test_classification_resistance_above_price():
    """RESISTANCE levels are priced above the current close."""
    df = _make_oscillating_df()
    store, pivot = _last_pivot(df)
    if pivot is None:
        pytest.skip("No pivots")

    current_price = float(df["close"].iloc[pivot.index])
    results = LevelDetector(DEFAULT_CONFIG).detect(
        df, store, pivot, 0, pivot.index
    )
    for r in results:
        level_price = r.annotations["hlines"][0]["price"]
        if r.pattern_type == PatternType.RESISTANCE:
            assert level_price >= current_price, (
                f"Resistance at {level_price} should be >= current price {current_price}"
            )


def test_pair_timeframe_forwarded():
    """pair and timeframe kwargs are stored in the PatternResult."""
    df = _make_oscillating_df()
    store, pivot = _last_pivot(df)
    if pivot is None:
        pytest.skip("No pivots")

    results = LevelDetector(DEFAULT_CONFIG).detect(
        df, store, pivot, 0, pivot.index,
        pair="EURUSD", timeframe="H4",
    )
    for r in results:
        assert r.pair == "EURUSD"
        assert r.timeframe == "H4"


def test_key_points_contain_touch_indices():
    """key_points reference valid DataFrame indices."""
    df = _make_oscillating_df()
    store, pivot = _last_pivot(df)
    if pivot is None:
        pytest.skip("No pivots")

    results = LevelDetector(DEFAULT_CONFIG).detect(
        df, store, pivot, 0, pivot.index
    )
    for r in results:
        for kp in r.key_points:
            assert 0 <= kp["index"] < len(df)


def test_anchor_rule_current_pivot_is_touch():
    """current_pivot.index must appear in the key_points of every result."""
    df = _make_oscillating_df()
    store, pivot = _last_pivot(df)
    if pivot is None:
        pytest.skip("No pivots")

    results = LevelDetector(DEFAULT_CONFIG).detect(
        df, store, pivot, 0, pivot.index
    )
    for r in results:
        touch_indices = {kp["index"] for kp in r.key_points}
        assert pivot.index in touch_indices, (
            f"current_pivot.index {pivot.index} not found in touch indices {touch_indices}"
        )
