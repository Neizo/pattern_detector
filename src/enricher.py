"""DataFrame enricher: adds ATR(14) and Savitzky-Golay smoothed columns.

Called once after loading, before any detection. Results are stored in-place
in the DataFrame as new columns: 'atr', 'smoothed_high', 'smoothed_low'.
"""

import logging

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

logger = logging.getLogger(__name__)

# Savitzky-Golay parameters per timeframe
_SAVGOL_PARAMS: dict[str, dict[str, int]] = {
    "M15": {"window_length": 11, "polyorder": 3},
    "M30": {"window_length": 11, "polyorder": 3},
    "H1":  {"window_length": 7,  "polyorder": 3},
    "H4":  {"window_length": 7,  "polyorder": 3},
    "D1":  {"window_length": 5,  "polyorder": 2},
    "W1":  {"window_length": 5,  "polyorder": 2},
}

_DEFAULT_SAVGOL = {"window_length": 7, "polyorder": 3}


class Enricher:
    """Adds computed columns required by all downstream detectors.

    Computes:
    - ``df['atr']``: ATR(14) using Wilder's EMA method.
    - ``df['smoothed_high']``: Savitzky-Golay filtered highs.
    - ``df['smoothed_low']``: Savitzky-Golay filtered lows.

    Example:
        enricher = Enricher()
        df = enricher.enrich(df, "H4")
    """

    def enrich(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """Compute and attach ATR and Savitzky-Golay columns to the DataFrame.

        Args:
            df: Clean OHLCV DataFrame (DatetimeIndex, float columns).
            timeframe: Chart timeframe identifier (e.g. "H4").

        Returns:
            The same DataFrame with three additional columns:
            'atr', 'smoothed_high', 'smoothed_low'.
        """
        df = self._compute_atr(df)
        df = self._compute_savgol(df, timeframe)
        params = _SAVGOL_PARAMS.get(timeframe, _DEFAULT_SAVGOL)
        logger.info(
            "ATR(14) + Savgol computed (window=%d, polyorder=%d)",
            params["window_length"],
            params["polyorder"],
        )
        return df

    # ── Private helpers ────────────────────────────────────────────────────────

    def _compute_atr(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute ATR(14) using Wilder's EMA smoothing.

        True Range = max(high - low, |high - prev_close|, |low - prev_close|)
        ATR = EMA(TR, span=14) using adjust=False (Wilder's method).

        Args:
            df: OHLCV DataFrame.

        Returns:
            DataFrame with 'atr' column added.
        """
        high = df["high"]
        low = df["low"]
        prev_close = df["close"].shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        # Wilder's EMA: alpha = 1/14, equivalent to EWM with span=14, adjust=False
        df["atr"] = tr.ewm(span=14, adjust=False).mean()
        return df

    def _compute_savgol(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """Apply Savitzky-Golay filter to high and low columns.

        Parameters are adaptive per timeframe. The filter requires at least
        window_length data points; for very short DataFrames we fall back to
        the raw values.

        Args:
            df: OHLCV DataFrame (must have 'high' and 'low' columns).
            timeframe: Chart timeframe identifier.

        Returns:
            DataFrame with 'smoothed_high' and 'smoothed_low' columns added.
        """
        params = _SAVGOL_PARAMS.get(timeframe, _DEFAULT_SAVGOL)
        win = params["window_length"]
        poly = params["polyorder"]

        if len(df) >= win:
            df["smoothed_high"] = savgol_filter(df["high"].to_numpy(), win, poly)
            df["smoothed_low"] = savgol_filter(df["low"].to_numpy(), win, poly)
        else:
            # Not enough data: use raw values
            df["smoothed_high"] = df["high"]
            df["smoothed_low"] = df["low"]

        return df
