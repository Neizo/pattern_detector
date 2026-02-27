"""Chart renderer: generates annotated candlestick PNG images per pattern.

For each PatternResult, extracts the rendering window from the DataFrame,
draws a candlestick chart with mplfinance, annotates key points and lines,
and saves a 1920x1080 PNG to output/{pattern_type}/{pair}_{tf}_{timestamp}.png.

Annotation conventions (annotations dict keys populated by detectors):
    lines : list[dict]
        Diagonal lines. Each entry:
        {"x0_idx": int, "y0": float, "x1_idx": int, "y1": float,
         "color": str, "width": float}
        x0_idx / x1_idx are absolute DataFrame integer indices.
    hlines : list[dict]
        Horizontal price lines. Each entry:
        {"price": float, "color": str, "width": float, "label": str}
    zones : list[dict]
        Semi-transparent price bands. Each entry:
        {"ymin": float, "ymax": float, "color": str, "alpha": float}
"""

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend, must be before pyplot import

import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd

from src.models import PatternResult

logger = logging.getLogger(__name__)

OUTPUT_ROOT = Path("output")

# ── Colour palette ─────────────────────────────────────────────────────────────
_C: dict[str, str] = {
    "up":        "#26a69a",   # teal  — bullish candle
    "down":      "#ef5350",   # red   — bearish candle
    "trendline": "#2196F3",   # blue
    "hline":     "#FF9800",   # orange (generic horizontal level)
    "zone":      "#2196F3",   # blue
    "bg":        "#131722",   # chart background
}

# Pivot marker colours by strength (1=minor, 2=medium, 3=major)
_HIGH_COLORS: dict[int, str] = {
    1: "#FFD600",   # yellow      — minor swing high
    2: "#FF6D00",   # orange      — medium swing high
    3: "#B71C1C",   # dark red    — major swing high
}
_LOW_COLORS: dict[int, str] = {
    1: "#00E5FF",   # cyan        — minor swing low
    2: "#00C853",   # green       — medium swing low
    3: "#0D47A1",   # dark blue   — major swing low
}
_STRENGTH_SIZES: dict[int, int] = {1: 40, 2: 80, 3: 150}

# ── mplfinance style — built once at module level ──────────────────────────────
_MC = mpf.make_marketcolors(
    up=_C["up"], down=_C["down"],
    edge="inherit", wick="inherit", volume="in",
)
_STYLE = mpf.make_mpf_style(
    base_mpl_style="dark_background",
    marketcolors=_MC,
    gridstyle="--",
    gridcolor="#2a2a2a",
    facecolor=_C["bg"],
    figcolor=_C["bg"],
    rc={
        "axes.labelcolor": "#aaaaaa",
        "xtick.color": "#aaaaaa",
        "ytick.color": "#aaaaaa",
    },
)


class ChartRenderer:
    """Generates annotated candlestick PNG images for detected patterns.

    Args:
        config: Pipeline configuration dictionary.

    Example:
        renderer = ChartRenderer(config)
        path = renderer.render(df, result)
    """

    def __init__(self, config: dict) -> None:
        """Initialise with pipeline configuration.

        Args:
            config: Dictionary with rendering parameters:
                render_dpi (int), render_figsize (tuple[float, float]).
        """
        self._config = config

    def render(self, df: pd.DataFrame, result: PatternResult) -> Path:
        """Generate and save a candlestick chart for a pattern result.

        Extracts df[window_start_index : window_end_index + 1], plots
        candlesticks with mplfinance, overlays key-point markers and
        annotation layers, then saves as PNG.

        The mplfinance price axis uses positional integers (0, 1, 2 ...)
        regardless of the DatetimeIndex. All line drawing therefore converts
        absolute DataFrame indices to relative slice positions.

        Args:
            df: Full enriched OHLCV DataFrame (must have an "atr" column).
            result: Detected pattern with rendering metadata.

        Returns:
            Path to the saved PNG file. May not exist if the window is too
            short to render (logged as WARNING in that case).
        """
        ws = result.window_start_index
        we = result.window_end_index + 1

        # mplfinance only accepts OHLCV columns
        df_slice = df.iloc[ws:we][["open", "high", "low", "close", "volume"]].copy()

        out_dir = OUTPUT_ROOT / result.pattern_type.value / result.pair / result.timeframe
        out_dir.mkdir(parents=True, exist_ok=True)
        ts_str = result.timestamp_detected.isoformat().replace(":", "-")
        out_path = out_dir / f"{result.pair}_{result.timeframe}_{ts_str}.png"

        if len(df_slice) < 2:
            logger.warning(
                "Window too short (%d candles) for %s — skipping render",
                len(df_slice),
                result.pattern_type.value,
            )
            return out_path

        # ATR-based marker offset (place markers slightly off the candle body)
        atr_val = (
            float(df["atr"].iloc[result.window_end_index])
            if "atr" in df.columns
            else 0.0
        )
        offset = atr_val * 0.4

        addplots = self._build_key_point_addplots(df_slice, result, ws, offset)

        plot_kwargs: dict = {
            "type": "candle",
            "style": _STYLE,
            "figsize": self._config.get("render_figsize", (19.2, 10.8)),
            "returnfig": True,
            "warn_too_much_data": len(df_slice) + 1,
        }
        if addplots:
            plot_kwargs["addplot"] = addplots

        fig, axes = mpf.plot(df_slice, **plot_kwargs)
        ax = axes[0]

        # Title
        pattern_label = result.pattern_type.value.replace("_", " ").title()
        ts_fmt = result.timestamp_detected.strftime("%Y-%m-%d %H:%M")
        ax.set_title(
            f"{result.pair}  {result.timeframe}  |  {pattern_label}  "
            f"@ {ts_fmt} UTC  (conf: {result.confidence:.2f})",
            color="white",
            fontsize=13,
            pad=10,
            loc="left",
        )

        # Annotation layers
        self._draw_lines(ax, df_slice, result, ws)
        self._draw_hlines(ax, result)
        self._draw_zones(ax, result)

        dpi = self._config.get("render_dpi", 100)
        fig.savefig(
            str(out_path),
            dpi=dpi,
            bbox_inches="tight",
            facecolor=fig.get_facecolor(),
        )
        plt.close(fig)
        logger.info("Saved %s", out_path)
        return out_path

    # ── Private helpers ────────────────────────────────────────────────────────

    def _build_key_point_addplots(
        self,
        df_slice: pd.DataFrame,
        result: PatternResult,
        ws: int,
        offset: float,
    ) -> list:
        """Build mplfinance addplot objects for key-point markers.

        Classifies each key point as a high or low by comparing its price to
        the candle mid-range, then groups by strength (1/2/3) to apply
        distinct colours and marker sizes:

        Highs (v):  minor=#FF8A80  medium=#ef5350  major=#B71C1C
        Lows  (^):  minor=#80CBC4  medium=#26a69a  major=#004D40
        Sizes:      minor=40       medium=80       major=150

        The optional key_point field "strength" (int 1-3) controls grouping.
        Missing or out-of-range strength values default to 2 (medium).

        Args:
            df_slice: OHLCV slice used for the chart (DatetimeIndex).
            result: PatternResult containing key_points.
            ws: Absolute window start index in the full DataFrame.
            offset: Vertical offset in price units (ATR-based).

        Returns:
            List of mplfinance addplot objects (up to 6, one per type×strength).
        """
        # One Series per (direction, strength)
        highs: dict[int, pd.Series] = {
            s: pd.Series(np.nan, index=df_slice.index, dtype=float)
            for s in (1, 2, 3)
        }
        lows: dict[int, pd.Series] = {
            s: pd.Series(np.nan, index=df_slice.index, dtype=float)
            for s in (1, 2, 3)
        }

        for kp in result.key_points:
            rel = kp["index"] - ws
            if not (0 <= rel < len(df_slice)):
                continue
            strength = int(kp.get("strength", 2))
            if strength not in (1, 2, 3):
                strength = 2
            mid = (df_slice["high"].iloc[rel] + df_slice["low"].iloc[rel]) / 2.0
            if kp["price"] >= mid:
                highs[strength].iloc[rel] = kp["price"] + offset
            else:
                lows[strength].iloc[rel] = kp["price"] - offset

        addplots = []
        for s in (1, 2, 3):
            if highs[s].notna().any():
                addplots.append(mpf.make_addplot(
                    highs[s], type="scatter",
                    markersize=_STRENGTH_SIZES[s], marker="v",
                    color=_HIGH_COLORS[s],
                ))
            if lows[s].notna().any():
                addplots.append(mpf.make_addplot(
                    lows[s], type="scatter",
                    markersize=_STRENGTH_SIZES[s], marker="^",
                    color=_LOW_COLORS[s],
                ))
        return addplots

    def _draw_lines(
        self,
        ax: plt.Axes,
        df_slice: pd.DataFrame,
        result: PatternResult,
        ws: int,
    ) -> None:
        """Draw diagonal annotation lines on the price axis.

        x-coords are positional (relative to the slice start) to match
        how mplfinance labels its x-axis. Lines are clamped to the visible
        window with y-values interpolated at the clamp points.

        Args:
            ax: mplfinance price axis.
            df_slice: OHLCV slice (for bounds checking).
            result: PatternResult with annotations["lines"].
            ws: Absolute window start index.
        """
        n = len(df_slice)
        for line in result.annotations.get("lines", []):
            x0 = line["x0_idx"] - ws
            x1 = line["x1_idx"] - ws
            if x1 < 0 or x0 >= n:
                continue
            x0c = max(0, x0)
            x1c = min(n - 1, x1)
            if x1 != x0:
                slope = (line["y1"] - line["y0"]) / (x1 - x0)
                y0p = line["y0"] + slope * (x0c - x0)
                y1p = line["y0"] + slope * (x1c - x0)
            else:
                y0p, y1p = line["y0"], line["y1"]
            ax.plot(
                [x0c, x1c], [y0p, y1p],
                color=line.get("color", _C["trendline"]),
                linewidth=line.get("width", 1.5),
                linestyle="--",
                alpha=0.85,
            )

    def _draw_hlines(self, ax: plt.Axes, result: PatternResult) -> None:
        """Draw horizontal price levels across the full chart width.

        Lines whose price falls inside a zone (ymin ≤ price ≤ ymax) are
        skipped, since the zone already conveys the level visually.

        Args:
            ax: mplfinance price axis.
            result: PatternResult with annotations["hlines"].
        """
        zones = result.annotations.get("zones", [])
        for hline in result.annotations.get("hlines", []):
            price = hline["price"]
            color = hline.get("color", _C["hline"])
            # Skip the dashed line if a zone already covers this price
            in_zone = any(z["ymin"] <= price <= z["ymax"] for z in zones)
            if not in_zone:
                ax.axhline(
                    y=price,
                    color=color,
                    linewidth=hline.get("width", 1.0),
                    linestyle="--",
                    alpha=0.8,
                )
            # Always draw the label (zone or not)
            if "label" in hline:
                ax.text(
                    0.01, price, hline["label"],
                    transform=ax.get_yaxis_transform(),
                    color=color, fontsize=9, va="bottom", alpha=0.9,
                )

    def _draw_zones(self, ax: plt.Axes, result: PatternResult) -> None:
        """Draw semi-transparent horizontal price bands.

        If a zone dict contains ``x_start_idx`` (absolute DataFrame index),
        the band starts at that candle position instead of the chart origin.
        The band always extends to the right edge of the chart.

        Args:
            ax: mplfinance price axis.
            result: PatternResult with annotations["zones"].
        """
        ws = result.window_start_index
        n = result.window_end_index - ws + 1
        for zone in result.annotations.get("zones", []):
            color = zone.get("color", _C["zone"])
            alpha = zone.get("alpha", 0.12)
            if "x_start_idx" in zone:
                # Convert absolute DataFrame index → positional x in slice
                x_start = max(0, zone["x_start_idx"] - ws)
                # Use data coordinates so the zone aligns with candles
                ax.fill_between(
                    [x_start, n - 1],
                    zone["ymin"], zone["ymax"],
                    color=color, alpha=alpha,
                )
            else:
                ax.axhspan(
                    zone["ymin"], zone["ymax"],
                    color=color, alpha=alpha,
                )
