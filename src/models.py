"""Shared data structures for the Forex Pattern Detector pipeline."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class PatternType(Enum):
    """Enumeration of all detectable pattern types."""

    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    TRENDLINE_UP = "trendline_up"
    TRENDLINE_DOWN = "trendline_down"
    SUPPORT = "support"
    RESISTANCE = "resistance"
    DOUBLE_TOP = "double_top"
    DOUBLE_BOTTOM = "double_bottom"
    HEAD_SHOULDERS = "head_shoulders"
    INV_HEAD_SHOULDERS = "inv_head_shoulders"
    TRIANGLE_ASC = "triangle_asc"
    TRIANGLE_DESC = "triangle_desc"
    FLAG = "flag"
    CONSOLIDATION = "consolidation"


@dataclass
class PatternResult:
    """Result of a single pattern detection.

    Attributes:
        pattern_type: Type of the detected pattern.
        pair: Forex pair (e.g. "EURUSD").
        timeframe: Chart timeframe (e.g. "H4").
        timestamp_detected: Timestamp of the detection candle.
        start_index: DataFrame index where the pattern begins.
        end_index: DataFrame index where the pattern ends (= detection candle).
        confidence: Detection confidence score [0.0, 1.0].
        key_points: List of key price points composing the pattern.
            Each entry: {"label": str, "index": int, "price": float}.
        atr_at_detection: ATR(14) value at the detection candle.
        window_start_index: Start of the rendering context window.
        window_end_index: End of the rendering context window (= current pivot index).
        annotations: Extra pattern-specific data (e.g. neckline, target price).
    """

    pattern_type: PatternType
    pair: str
    timeframe: str
    timestamp_detected: datetime
    start_index: int
    end_index: int
    confidence: float
    key_points: list[dict]
    atr_at_detection: float
    window_start_index: int
    window_end_index: int
    annotations: dict = field(default_factory=dict)


@dataclass
class Pivot:
    """A single swing high or swing low point.

    Attributes:
        index: Position in the source DataFrame.
        timestamp: Candle timestamp.
        price: High price for swing_high, low price for swing_low.
        pivot_type: "swing_high" or "swing_low".
        strength: Number of detection scales (1=minor, 2=medium, 3=major).
        prominence: Peak prominence in price units (from scipy find_peaks).
        detection_index: DataFrame index at which this pivot is fully
            confirmed (= index + max right_bars across detecting scales).
            The chart should be rendered up to this index, not the pivot index,
            because the pivot is only known after right_bars candles.
    """

    index: int
    timestamp: datetime
    price: float
    pivot_type: str
    strength: int
    prominence: float
    detection_index: int = 0
