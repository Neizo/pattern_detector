"""Visual validation of pivot detection on real forex data.

Generates one annotated candlestick image per (pair, timeframe), showing the
last WINDOW candles with ALL detected swing highs (red v) and swing lows
(teal ^) overlaid.

Usage:
    python scripts/test_pivots_visual.py
    python scripts/test_pivots_visual.py --window 300
    python scripts/test_pivots_visual.py --pair EURUSD --pair GBPJPY
    python scripts/test_pivots_visual.py --pair EURUSD --timeframes H4 D
"""

import argparse
import logging
import sys
from pathlib import Path

# Resolve project root so imports work regardless of CWD
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.config import DEFAULT_CONFIG
from src.enricher import Enricher
from src.detector.pivots import PivotDetector
from src.models import PatternResult, PatternType
from src.renderer.chart_renderer import ChartRenderer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

DATA_ROOT = ROOT / "data" / "raw"
OUTPUT_BASE = ROOT / "output" / "test" / "pivots"

# Map filename stem → enricher timeframe key (for Savgol parameters)
TF_MAP: dict[str, str] = {
    "M15": "M15",
    "M30": "M30",
    "M45": "M30",   # nearest standard
    "M90": "H1",    # nearest standard
    "H1":  "H1",
    "H2":  "H1",    # nearest standard
    "H4":  "H4",
    "H8":  "H4",    # nearest standard
    "D":   "D1",
    "W":   "W1",
}


def load_csv(path: Path) -> pd.DataFrame:
    """Load and normalise a single OHLCV CSV file.

    Args:
        path: Path to the CSV file.

    Returns:
        DataFrame with DatetimeIndex (UTC), columns: open high low close volume.
    """
    df = pd.read_csv(path)
    df.columns = df.columns.str.lower()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df


def _available_pairs() -> list[str]:
    """Return sorted list of pair names that have a data directory."""
    return sorted(p.name for p in DATA_ROOT.iterdir() if p.is_dir())


def _available_timeframes(pair: str) -> list[str]:
    """Return sorted list of CSV stems available for a given pair."""
    pair_dir = DATA_ROOT / pair
    if not pair_dir.exists():
        return []
    return sorted(p.stem for p in pair_dir.glob("*.csv"))


def run(pairs: list[str], timeframes: list[str] | None, window: int) -> None:
    """Detect pivots and render one image per (pair, timeframe).

    Args:
        pairs: List of forex pair names to process.
        timeframes: List of CSV filename stems to process, or None for all.
        window: Number of candles to show in each rendered image.
    """
    enricher = Enricher()
    detector = PivotDetector()
    renderer = ChartRenderer({
        **DEFAULT_CONFIG,
        "render_figsize": (19.2, 10.8),
        "render_dpi": 100,
    })

    for pair in pairs:
        pair_dir = DATA_ROOT / pair
        if not pair_dir.exists():
            logger.warning("No data directory for %s — skipping", pair)
            continue

        out_dir = OUTPUT_BASE / pair
        out_dir.mkdir(parents=True, exist_ok=True)

        tf_list = timeframes if timeframes else _available_timeframes(pair)

        for tf_stem in tf_list:
            csv_path = pair_dir / f"{tf_stem}.csv"
            if not csv_path.exists():
                logger.warning("File not found: %s — skipping", csv_path)
                continue

            logger.info("[%s] Loading %s ...", pair, csv_path.name)
            df = load_csv(csv_path)
            logger.info("  %d candles, %s to %s", len(df), df.index[0].date(), df.index[-1].date())

            tf_key = TF_MAP.get(tf_stem, "H4")
            df = enricher.enrich(df, tf_key)

            pivot_store = detector.compute_all(df)
            logger.info(
                "  %d swing highs, %d swing lows detected",
                len(pivot_store.highs),
                len(pivot_store.lows),
            )

            # Rendering window: last `window` candles
            we = len(df) - 1
            ws = max(0, we - window + 1)

            # Collect all pivots within the window as key_points
            window_pivots = pivot_store.in_range(ws, we)
            key_points = [
                {"label": p.pivot_type, "index": p.index, "price": p.price, "strength": p.strength}
                for p in window_pivots
            ]

            n_high = sum(1 for p in window_pivots if p.pivot_type == "swing_high")
            n_low  = sum(1 for p in window_pivots if p.pivot_type == "swing_low")
            logger.info(
                "  Window [%d:%d] — %d highs, %d lows visible",
                ws, we, n_high, n_low,
            )

            if not key_points:
                logger.warning("  No pivots in window, skipping render")
                continue

            result = PatternResult(
                pattern_type=PatternType.SWING_HIGH,  # re-used as "pivots" category
                pair=pair,
                timeframe=tf_stem,
                timestamp_detected=df.index[we].to_pydatetime(),
                start_index=ws,
                end_index=we,
                confidence=1.0,
                key_points=key_points,
                atr_at_detection=float(df["atr"].iloc[we]),
                window_start_index=ws,
                window_end_index=we,
                annotations={},
            )

            # Redirect output to output/test/pivots/{pair}/
            from src.renderer import chart_renderer as _cm
            _orig = _cm.OUTPUT_ROOT
            _cm.OUTPUT_ROOT = out_dir
            try:
                path = renderer.render(df, result)
            finally:
                _cm.OUTPUT_ROOT = _orig

            # Rename file to something more descriptive
            dest = out_dir / f"{tf_stem}_pivots_last{window}.png"
            if path.exists() and path != dest:
                path.replace(dest)
                path = dest

            logger.info("  Saved -> %s", path.name)

    logger.info("Done. Images in: %s", OUTPUT_BASE)


def _parse_args() -> argparse.Namespace:
    all_pairs = _available_pairs()
    parser = argparse.ArgumentParser(description="Visual pivot detection test on forex data")
    parser.add_argument(
        "--pair", action="append", dest="pairs", metavar="PAIR",
        help=f"Forex pair(s) to process (repeatable). Available: {all_pairs}. "
             "Default: all pairs with data.",
    )
    parser.add_argument(
        "--timeframes", nargs="+", default=None,
        metavar="TF",
        help="Timeframes to process (default: all found for each pair).",
    )
    parser.add_argument(
        "--window", type=int, default=500,
        help="Number of candles to display in each image (default: 500)",
    )
    args = parser.parse_args()
    if not args.pairs:
        args.pairs = all_pairs
    return args


if __name__ == "__main__":
    args = _parse_args()
    run(args.pairs, args.timeframes, args.window)
