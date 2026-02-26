"""Tests for Enricher (ATR + Savitzky-Golay)."""

import numpy as np
import pandas as pd
import pytest

from src.enricher import Enricher


def _make_df(n: int = 50) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame."""
    rng = np.random.default_rng(42)
    close = 1.1 + np.cumsum(rng.normal(0, 0.001, n))
    high = close + rng.uniform(0.001, 0.003, n)
    low = close - rng.uniform(0.001, 0.003, n)
    open_ = close - rng.normal(0, 0.001, n)
    volume = rng.integers(100, 1000, n).astype(float)

    idx = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def test_enrich_adds_atr_column() -> None:
    """Enricher adds a non-null 'atr' column."""
    df = _make_df(50)
    enricher = Enricher()
    out = enricher.enrich(df, "H4")

    assert "atr" in out.columns
    assert out["atr"].notna().sum() > 0


def test_enrich_adds_smoothed_columns() -> None:
    """Enricher adds 'smoothed_high' and 'smoothed_low' columns."""
    df = _make_df(50)
    enricher = Enricher()
    out = enricher.enrich(df, "H4")

    assert "smoothed_high" in out.columns
    assert "smoothed_low" in out.columns


def test_enrich_atr_positive() -> None:
    """ATR values are positive (after initial NaN warm-up)."""
    df = _make_df(50)
    enricher = Enricher()
    out = enricher.enrich(df, "H4")

    assert (out["atr"].dropna() > 0).all()


def test_enrich_fallback_for_short_df() -> None:
    """Enricher uses raw values when DataFrame is shorter than Savgol window."""
    df = _make_df(5)
    enricher = Enricher()
    out = enricher.enrich(df, "H4")  # H4 window=7, df has only 5 rows

    pd.testing.assert_series_equal(out["smoothed_high"], out["high"], check_names=False)
    pd.testing.assert_series_equal(out["smoothed_low"], out["low"], check_names=False)
