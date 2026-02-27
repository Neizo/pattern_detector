"""CLI entry point for the Forex Pattern Detector pipeline.

Usage:
    python main.py --pair EURUSD --timeframe H4
    python main.py --pair EURUSD --timeframe H4 --pair GBPUSD --timeframe D1
    python main.py --all
"""

import argparse
import logging
import shutil
import sys
from itertools import product
from pathlib import Path

from src.config import DEFAULT_CONFIG, PAIRS, TIMEFRAMES
from src.models import PatternType
from src.pipeline import Pipeline

OUTPUT_ROOT = Path("output")


def _setup_logging(level: str = "INFO") -> None:
    """Configure root logger to stdout with a timestamped format.

    Args:
        level: Logging level string (e.g. "INFO", "DEBUG").
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Forex Price Action Pattern Detector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py --pair EURUSD --timeframe H4\n"
            "  python main.py --all\n"
            "  python main.py --all --log-level DEBUG\n"
        ),
    )
    parser.add_argument(
        "--pair",
        action="append",
        dest="pairs",
        metavar="PAIR",
        choices=PAIRS,
        help=f"Forex pair to process. Choices: {', '.join(PAIRS)}. "
             "May be repeated for multiple pairs.",
    )
    parser.add_argument(
        "--timeframe",
        action="append",
        dest="timeframes",
        metavar="TF",
        choices=TIMEFRAMES,
        help=f"Timeframe to process. Choices: {', '.join(TIMEFRAMES)}. "
             "May be repeated for multiple timeframes.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all pairs and all timeframes.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser.parse_args()


def _clean_output(runs: list[tuple[str, str]]) -> None:
    """Remove previous output images for the pairs/timeframes about to be processed.

    Deletes output/{pattern}/{pair}/{timeframe}/ for every combination in *runs*
    and every pattern type, so stale images from previous runs don't accumulate.

    Args:
        runs: List of (pair, timeframe) tuples that will be processed.
    """
    logger = logging.getLogger(__name__)
    removed = 0
    for pair, timeframe in runs:
        for pt in PatternType:
            d = OUTPUT_ROOT / pt.value / pair / timeframe
            if d.exists():
                shutil.rmtree(d)
                removed += 1
    if removed:
        logger.info("Cleaned %d output directories", removed)


def main() -> None:
    """Entry point: parse arguments and run the pipeline."""
    args = _parse_args()
    _setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    if args.all:
        runs = list(product(PAIRS, TIMEFRAMES))
    else:
        pairs = args.pairs or []
        timeframes = args.timeframes or []
        if not pairs or not timeframes:
            print(
                "Error: specify --pair and --timeframe, or use --all.\n"
                "Run with --help for usage.",
                file=sys.stderr,
            )
            sys.exit(1)
        runs = list(product(pairs, timeframes))

    # Clean output directories for the pairs being processed
    _clean_output(runs)

    pipeline = Pipeline(DEFAULT_CONFIG)
    total_images = 0

    for pair, timeframe in runs:
        logger.info("Starting %s / %s", pair, timeframe)
        try:
            images = pipeline.run(pair, timeframe)
            total_images += len(images)
        except FileNotFoundError as exc:
            logger.warning("Skipping %s/%s — %s", pair, timeframe, exc)
        except Exception:
            logger.exception("Unexpected error for %s/%s", pair, timeframe)

    logger.info("Done. Total images generated: %d", total_images)


if __name__ == "__main__":
    main()
