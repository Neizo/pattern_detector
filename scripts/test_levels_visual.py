"""Visual validation of S/R level detection on real EURUSD data.

Generates one annotated candlestick image per timeframe showing the last
WINDOW candles with all detected support (teal) and resistance (red) levels
overlaid as horizontal lines and semi-transparent zones.

Detection strategy:
  - Run LevelDetector for every pivot in the visible window
  - Deduplicate levels whose prices are within 0.5×ATR of each other
    (keep highest-confidence representative)
  - Overlay all unique levels on a single chart alongside pivot markers

Usage:
    python scripts/test_levels_visual.py
    python scripts/test_levels_visual.py --window 300
    python scripts/test_levels_visual.py --timeframes H4 D
"""

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src.config import DEFAULT_CONFIG
from src.enricher import Enricher
from src.detector.pivots import PivotDetector
from src.detector.levels import LevelDetector
from src.models import PatternResult, PatternType
from src.renderer.chart_renderer import ChartRenderer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

DATA_ROOT = ROOT / "data" / "raw" / "EURUSD"
OUTPUT_DIR = ROOT / "output" / "levels_test"

TF_MAP: dict[str, str] = {
    "M15": "M15", "M30": "M30", "M45": "M30", "M90": "H1",
    "H1": "H1", "H2": "H1", "H4": "H4", "H8": "H4", "D": "D1", "W": "W1",
}

# Colors re-used from chart_renderer palette
_COLOR_SUPPORT = "#26a69a"
_COLOR_RESISTANCE = "#ef5350"


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = df.columns.str.lower()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df


def _deduplicate_levels(
    results: list[PatternResult],
    atr: float,
    dedup_atr_mult: float = 0.5,
) -> list[PatternResult]:
    """Merge levels whose prices are within dedup_atr_mult×ATR of each other.

    From each cluster, the representative with the highest confidence is kept.
    """
    if not results:
        return []

    tol = atr * dedup_atr_mult
    results_sorted = sorted(results, key=lambda r: r.annotations["hlines"][0]["price"])
    unique: list[PatternResult] = []

    for r in results_sorted:
        price = r.annotations["hlines"][0]["price"]
        merged = False
        for rep in unique:
            rep_price = rep.annotations["hlines"][0]["price"]
            if abs(price - rep_price) <= tol:
                # Keep the higher-confidence one
                if r.confidence > rep.confidence:
                    unique[unique.index(rep)] = r
                merged = True
                break
        if not merged:
            unique.append(r)

    return unique


def run(timeframes: list[str], window: int) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    enricher = Enricher()
    pivot_detector = PivotDetector()
    level_detector = LevelDetector({
        **DEFAULT_CONFIG,
        "render_min_confidence": 0.0,   # collect all levels; filter visually
    })
    renderer = ChartRenderer({
        **DEFAULT_CONFIG,
        "render_figsize": (19.2, 10.8),
        "render_dpi": 100,
    })

    for tf_stem in timeframes:
        csv_path = DATA_ROOT / f"{tf_stem}.csv"
        if not csv_path.exists():
            logger.warning("File not found: %s — skipping", csv_path)
            continue

        logger.info("Loading %s ...", csv_path.name)
        df = load_csv(csv_path)
        logger.info("  %d candles, %s to %s",
                    len(df), df.index[0].date(), df.index[-1].date())

        tf_key = TF_MAP.get(tf_stem, "H4")
        df = enricher.enrich(df, tf_key)

        pivot_store = pivot_detector.compute_all(df)
        logger.info("  %d swing highs, %d swing lows",
                    len(pivot_store.highs), len(pivot_store.lows))

        # Rendering window
        we = len(df) - 1
        ws = max(0, we - window + 1)

        # ATR at window end
        atr_end = float(df["atr"].iloc[we])

        # Run LevelDetector once with skip_anchor=True to find ALL
        # significant levels in the window (visual validation mode).
        window_pivots = pivot_store.in_range(ws, we)
        if not window_pivots:
            logger.warning("  No pivots in window — skipping %s", tf_stem)
            continue

        # Use the last pivot as reference for lookback/reaction cap
        ref_pivot = window_pivots[-1]
        all_level_results = level_detector.detect(
            df, pivot_store, ref_pivot,
            win_start=ws, win_end=we,
            pair="EURUSD", timeframe=tf_stem,
            visual_mode=True,
        )

        # Deduplicate
        unique_levels = _deduplicate_levels(all_level_results, atr_end)

        n_sup = sum(1 for r in unique_levels if r.pattern_type == PatternType.SUPPORT)
        n_res = sum(1 for r in unique_levels if r.pattern_type == PatternType.RESISTANCE)
        logger.info(
            "  Window [%d:%d] — %d unique levels (%d support, %d resistance)",
            ws, we, len(unique_levels), n_sup, n_res,
        )

        # Build key_points from pivots (same as test_pivots_visual.py)
        key_points = [
            {"label": p.pivot_type, "index": p.index, "price": p.price,
             "strength": p.strength}
            for p in window_pivots
        ]

        # Merge annotations from all unique levels
        merged_hlines = []
        merged_zones = []
        for lvl in unique_levels:
            merged_hlines.extend(lvl.annotations.get("hlines", []))
            merged_zones.extend(lvl.annotations.get("zones", []))

        result = PatternResult(
            pattern_type=PatternType.SUPPORT,  # category label only
            pair="EURUSD",
            timeframe=tf_stem,
            timestamp_detected=df.index[we].to_pydatetime(),
            start_index=ws,
            end_index=we,
            confidence=1.0,
            key_points=key_points,
            atr_at_detection=atr_end,
            window_start_index=ws,
            window_end_index=we,
            annotations={"hlines": merged_hlines, "zones": merged_zones},
        )

        # Override OUTPUT_ROOT so images land in levels_test/
        from src.renderer import chart_renderer as _cm
        _orig = _cm.OUTPUT_ROOT
        _cm.OUTPUT_ROOT = OUTPUT_DIR
        try:
            path = renderer.render(df, result)
        finally:
            _cm.OUTPUT_ROOT = _orig

        dest = OUTPUT_DIR / f"EURUSD_{tf_stem}_levels_last{window}.png"
        if path.exists() and path != dest:
            path.replace(dest)
            path = dest

        logger.info("  Saved -> %s", path.name)

    logger.info("Done. Images in: %s", OUTPUT_DIR)


def _parse_args() -> argparse.Namespace:
    available = sorted(p.stem for p in DATA_ROOT.glob("*.csv"))
    parser = argparse.ArgumentParser(
        description="Visual S/R level detection test on EURUSD data"
    )
    parser.add_argument(
        "--timeframes", nargs="+", default=available, metavar="TF",
        help=f"Timeframes to process (default: all found). Available: {available}",
    )
    parser.add_argument(
        "--window", type=int, default=500,
        help="Number of candles to display (default: 500)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(args.timeframes, args.window)
