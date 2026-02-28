"""Data provider — wraps CSVLoader & Enricher for the annotation tool."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# Add project root to path so we can import src.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.loader.csv_loader import CSVLoader
from src.enricher import Enricher
from src.config import DEFAULT_CONFIG
from src.detector.pivots import PivotDetector, PivotStore
from src.detector.levels import LevelDetector
from src.detector.trendlines import TrendlineDetector

# Map CSV file stems to canonical timeframe keys used by detectors
TF_MAP: dict[str, str] = {
    "M15": "M15",
    "M30": "M30",
    "M45": "M30",
    "M90": "H1",
    "H1": "H1",
    "H2": "H1",
    "H4": "H4",
    "H8": "H4",
    "D": "D1",
    "W": "W1",
}

# Canonical TFs we expose in the UI (subset of the ones with actual CSV files)
CANONICAL_TFS = {"M15", "M30", "H1", "H4", "D"}


class DataProvider:
    """Provides candle data to the annotation tool backend."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else PROJECT_ROOT / "data" / "raw"
        self._loader = CSVLoader(data_dir=self._data_dir)
        self._enricher = Enricher()
        self._cache: dict[tuple[str, str], pd.DataFrame] = {}
        self._pivot_cache: dict[tuple[str, str], PivotStore] = {}
        self._pivot_detector = PivotDetector()
        self._level_detector = LevelDetector(DEFAULT_CONFIG)
        self._trendline_detector = TrendlineDetector(DEFAULT_CONFIG)

    def get_available_pairs(self) -> list[dict]:
        """Scan data/raw/ and return available pairs with their timeframes."""
        pairs_out = []
        if not self._data_dir.is_dir():
            return pairs_out

        for pair_dir in sorted(self._data_dir.iterdir()):
            if not pair_dir.is_dir():
                continue
            tfs = []
            for csv_file in sorted(pair_dir.glob("*.csv")):
                stem = csv_file.stem  # e.g. "H4", "D", "M30"
                if stem in CANONICAL_TFS:
                    tfs.append(stem)
            if tfs:
                pairs_out.append({"pair": pair_dir.name, "timeframes": tfs})

        return pairs_out

    def get_candles(
        self,
        pair: str,
        timeframe: str,
        last_n: int = 500,
        before: str | None = None,
    ) -> list[dict]:
        """Load candles for a pair/timeframe, return last_n before a date.

        Args:
            pair: e.g. "EURUSD"
            timeframe: CSV stem, e.g. "H4", "D"
            last_n: number of candles to return
            before: ISO date string cutoff (inclusive), default=no cutoff

        Returns:
            List of candle dicts with timestamp, open, high, low, close, volume.
        """
        df = self._load_enriched(pair, timeframe)

        if before:
            cutoff = pd.Timestamp(before, tz="UTC")
            df = df[df.index <= cutoff]

        df = df.iloc[-last_n:]

        candles = []
        for ts, row in df.iterrows():
            candles.append({
                "timestamp": ts.isoformat(),
                "open": round(float(row["open"]), 6),
                "high": round(float(row["high"]), 6),
                "low": round(float(row["low"]), 6),
                "close": round(float(row["close"]), 6),
                "volume": float(row["volume"]),
            })
        return candles

    def get_enriched_df(
        self,
        pair: str,
        timeframe: str,
        last_n: int = 500,
        before: str | None = None,
    ) -> pd.DataFrame:
        """Return the enriched DataFrame slice (for detection use)."""
        df = self._load_enriched(pair, timeframe)

        if before:
            cutoff = pd.Timestamp(before, tz="UTC")
            df = df[df.index <= cutoff]

        return df.iloc[-last_n:]

    def get_detections(
        self,
        pair: str,
        timeframe: str,
        last_n: int = 500,
        before: str | None = None,
    ) -> dict:
        """Run algorithmic detection on the same window as displayed candles.

        Returns dict with keys: pivots, levels, trendlines, patterns.
        All indices are relative to the visible window (0 = first displayed candle).
        """
        df = self._load_enriched(pair, timeframe)

        if before:
            cutoff = pd.Timestamp(before, tz="UTC")
            df = df[df.index <= cutoff]

        total_len = len(df)
        win_end_abs = total_len - 1
        win_start_abs = max(0, total_len - last_n)

        # Compute pivots on the full df (cached)
        cache_key = (pair, timeframe)
        if cache_key not in self._pivot_cache:
            self._pivot_cache[cache_key] = self._pivot_detector.compute_all(df)
        pivot_store = self._pivot_cache[cache_key]

        tf_key = TF_MAP.get(timeframe, timeframe)

        # ── Pivots in visible window ─────────────────────────────────────
        visible_pivots = pivot_store.in_range(win_start_abs, win_end_abs)
        pivots_out = []
        for p in visible_pivots:
            pivots_out.append({
                "index": p.index - win_start_abs,
                "price": round(float(p.price), 6),
                "type": p.pivot_type,
                "strength": p.strength,
                "prominence": round(float(p.prominence), 6),
            })

        # ── Levels (run LevelDetector on each visible pivot) ─────────────
        raw_levels: list = []
        for p in visible_pivots:
            try:
                results = self._level_detector.detect(
                    df, pivot_store, p,
                    win_start_abs, win_end_abs,
                    pair=pair, timeframe=tf_key,
                    visual_mode=True,
                )
                raw_levels.extend(results)
            except Exception:
                continue

        # Deduplicate levels by price (keep highest confidence)
        atr_median = float(df["atr"].iloc[win_start_abs:win_end_abs + 1].median())
        dedup_tol = atr_median * 0.3 if atr_median > 0 else 0.001
        levels_out = self._dedup_levels(raw_levels, dedup_tol, win_start_abs)

        # ── Trendlines (stub — returns [] until implemented) ─────────────
        trendlines_out: list = []

        # ── ATR median for comparator ────────────────────────────────────
        return {
            "pivots": pivots_out,
            "levels": levels_out,
            "trendlines": trendlines_out,
            "patterns": [],
            "atr_median": round(atr_median, 6),
        }

    @staticmethod
    def _dedup_levels(
        raw_levels: list,
        tolerance: float,
        win_start_abs: int,
    ) -> list[dict]:
        """Deduplicate levels by price proximity, keeping highest confidence."""
        if not raw_levels:
            return []

        # Sort by confidence descending
        raw_levels.sort(key=lambda r: r.confidence, reverse=True)
        kept: list[dict] = []
        used_prices: list[float] = []

        for result in raw_levels:
            # Extract the level price from annotations
            hlines = result.annotations.get("hlines", [])
            if not hlines:
                continue
            level_price = hlines[0]["price"]

            # Check if a similar price is already kept
            if any(abs(level_price - up) < tolerance for up in used_prices):
                continue

            used_prices.append(level_price)

            # Build zone bounds from annotations
            zones = result.annotations.get("zones", [])
            zone_top = level_price + tolerance
            zone_bottom = level_price - tolerance
            if zones:
                zone_top = zones[0].get("ymax", zone_top)
                zone_bottom = zones[0].get("ymin", zone_bottom)

            kept.append({
                "price": round(level_price, 6),
                "type": result.pattern_type.value,
                "confidence": round(result.confidence, 4),
                "touches": len(result.key_points),
                "zone_top": round(zone_top, 6),
                "zone_bottom": round(zone_bottom, 6),
                "start_index": max(0, result.start_index - win_start_abs),
                "key_points": [
                    {
                        "index": kp["index"] - win_start_abs,
                        "price": round(kp["price"], 6),
                    }
                    for kp in result.key_points
                ],
            })

        return kept

    def _load_enriched(self, pair: str, timeframe: str) -> pd.DataFrame:
        """Load and cache enriched DataFrame."""
        cache_key = (pair, timeframe)
        if cache_key not in self._cache:
            df = self._loader.load(pair, timeframe)
            tf_key = TF_MAP.get(timeframe, timeframe)
            df = self._enricher.enrich(df, tf_key)
            self._cache[cache_key] = df
        return self._cache[cache_key]
