"""Centralised configuration for the Forex Pattern Detector pipeline.

All adjustable parameters live here. No magic constants elsewhere in the codebase.
"""

DEFAULT_CONFIG: dict = {
    # Pivot detection
    "pivot_left_bars": 5,
    "pivot_right_bars": 5,
    # Support / Resistance
    "level_tolerance_pct": 0.15,
    "level_min_touches": 3,
    "level_lookback_bars": 600,
    # Trendlines
    "trendline_min_touches": 3,
    "trendline_min_r_squared": 0.85,
    "trendline_lookback_bars": 600,
    # Rendering
    "render_candle_window": 600,
    "render_min_confidence": 0.55,
    "render_dpi": 100,
    "render_figsize": (19.2, 10.8),
    # Pipeline
    "context_window_size": 600,
}

PAIRS: list[str] = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "NZDUSD",
    "USDCAD",
    "GBPJPY",
]

TIMEFRAMES: list[str] = ["M15", "M30", "H1", "H4", "D1", "W1"]
