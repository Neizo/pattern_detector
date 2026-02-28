/**
 * ChartManager — wraps TradingView Lightweight Charts.
 *
 * Responsibilities:
 *  - Create and resize the chart
 *  - Load candle data from the API
 *  - Provide helpers for drawing annotations (zones, lines, markers)
 *  - Expose price↔coordinate conversion for annotation interactions
 */
class ChartManager {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.chart = null;
    this.candleSeries = null;
    this.candles = [];           // raw candle data from API
    this.lwcCandles = [];        // formatted for lightweight-charts
    this.pricePrecision = 5;     // auto-detected from data
    this.displayMode = 'candles'; // 'candles' or 'line'

    // Close line series (toggle)
    this.lineSeries = null;

    // Annotation overlays managed externally
    this._levelSeries = [];      // list of { id, areaSeries }
    this._markers = [];          // pivot markers on candle series
    this._lineSeries = [];       // trendline series

    // Comparison overlays (separate from annotation overlays)
    this._comparisonSeries = []; // list of { id, topSeries, bottomSeries, labelLine }
    this._comparisonMarkers = [];

    this._init();
  }

  _init() {
    this.chart = LightweightCharts.createChart(this.container, {
      width: this.container.clientWidth,
      height: this.container.clientHeight,
      layout: {
        background: { type: 'solid', color: '#131722' },
        textColor: '#d1d4dc',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#1e222d' },
        horzLines: { color: '#1e222d' },
      },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#363a45',
      },
      timeScale: {
        borderColor: '#363a45',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    this.candleSeries = this.chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderUpColor: '#26a69a',
      borderDownColor: '#ef5350',
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });

    this.lineSeries = this.chart.addLineSeries({
      color: '#d1d4dc',
      lineWidth: 1,
      crosshairMarkerVisible: true,
      priceLineVisible: false,
      lastValueVisible: false,
      visible: false,
    });

    // Resize on window resize
    const ro = new ResizeObserver(() => {
      this.chart.applyOptions({
        width: this.container.clientWidth,
        height: this.container.clientHeight,
      });
    });
    ro.observe(this.container);
  }

  /**
   * Load candles from the API and display them.
   */
  async loadCandles(pair, timeframe, lastN, before) {
    const params = new URLSearchParams({ pair, timeframe, last_n: lastN });
    if (before) params.set('before', before);

    const resp = await fetch(`/api/candles?${params}`);
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);

    const data = await resp.json();
    this.candles = data.candles;

    // Detect precision from first candle
    if (this.candles.length > 0) {
      const sample = this.candles[0].close.toString();
      const dot = sample.indexOf('.');
      this.pricePrecision = dot >= 0 ? sample.length - dot - 1 : 2;
    }

    // Convert to LWC format (time as UTC unix timestamp)
    this.lwcCandles = this.candles.map(c => ({
      time: Math.floor(new Date(c.timestamp).getTime() / 1000),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    this.candleSeries.setData(this.lwcCandles);

    // Also feed close-only line series
    const lineData = this.lwcCandles.map(c => ({ time: c.time, value: c.close }));
    this.lineSeries.setData(lineData);

    this.chart.timeScale().fitContent();
  }

  /**
   * Get the candle index (in this.candles[]) closest to a given LWC time value.
   */
  getCandleIndexByTime(lwcTime) {
    let best = 0;
    let bestDiff = Infinity;
    for (let i = 0; i < this.lwcCandles.length; i++) {
      const diff = Math.abs(this.lwcCandles[i].time - lwcTime);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = i;
      }
    }
    return best;
  }

  /**
   * Convert a pixel Y coordinate on the chart to a price value.
   */
  yToPrice(y) {
    const series = this.candleSeries;
    const coord = series.coordinateToPrice(y);
    return coord;
  }

  /**
   * Convert a price value to a pixel Y coordinate.
   */
  priceToY(price) {
    return this.candleSeries.priceToCoordinate(price);
  }

  // ── Display mode toggle ──────────────────────────────────────────────

  /**
   * Switch between 'candles' and 'line' (close only) display.
   */
  setDisplayMode(mode) {
    this.displayMode = mode;
    const transparent = '#131722';
    if (mode === 'line') {
      // Make candles invisible but keep the series active (annotations stay visible)
      this.candleSeries.applyOptions({
        upColor: transparent,
        downColor: transparent,
        borderUpColor: transparent,
        borderDownColor: transparent,
        wickUpColor: transparent,
        wickDownColor: transparent,
      });
      this.lineSeries.applyOptions({ visible: true });
    } else {
      this.candleSeries.applyOptions({
        upColor: '#26a69a',
        downColor: '#ef5350',
        borderUpColor: '#26a69a',
        borderDownColor: '#ef5350',
        wickUpColor: '#26a69a',
        wickDownColor: '#ef5350',
      });
      this.lineSeries.applyOptions({ visible: false });
    }
  }

  // ── Level zones ──────────────────────────────────────────────────────

  /**
   * Add a horizontal zone (level annotation) between priceHigh and priceLow.
   * startIndex: candle index where the zone starts (extends to the right edge).
   */
  addLevelZone(id, priceHigh, priceLow, type, startIndex) {
    this.removeLevelZone(id);

    const lineColor = type === 'resistance'
      ? 'rgba(239, 83, 80, 0.6)'
      : 'rgba(38, 166, 154, 0.6)';

    const start = (startIndex != null && startIndex >= 0) ? startIndex : 0;
    const end = this.lwcCandles.length - 1;
    if (end < 0) return;

    // Build horizontal line data from startIndex to the right edge
    const topData = [];
    const bottomData = [];
    for (let i = start; i <= end; i++) {
      const t = this.lwcCandles[i].time;
      topData.push({ time: t, value: priceHigh });
      bottomData.push({ time: t, value: priceLow });
    }

    const topSeries = this.chart.addLineSeries({
      color: lineColor,
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Solid,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    topSeries.setData(topData);

    const bottomSeries = this.chart.addLineSeries({
      color: lineColor,
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Solid,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    bottomSeries.setData(bottomData);

    // Label line at midpoint (price line for axis label)
    const midPrice = (priceHigh + priceLow) / 2;
    const labelLine = this.candleSeries.createPriceLine({
      price: midPrice,
      color: 'transparent',
      lineWidth: 0,
      lineStyle: LightweightCharts.LineStyle.Solid,
      axisLabelVisible: true,
      title: id,
      axisLabelColor: lineColor,
    });

    this._levelSeries.push({ id, topSeries, bottomSeries, labelLine, priceHigh, priceLow, startIndex: start });
  }

  removeLevelZone(id) {
    const idx = this._levelSeries.findIndex(s => s.id === id);
    if (idx < 0) return;
    const entry = this._levelSeries[idx];
    this.chart.removeSeries(entry.topSeries);
    this.chart.removeSeries(entry.bottomSeries);
    this.candleSeries.removePriceLine(entry.labelLine);
    this._levelSeries.splice(idx, 1);
  }

  clearAllLevelZones() {
    for (const entry of [...this._levelSeries]) {
      this.removeLevelZone(entry.id);
    }
  }

  // ── Pivot markers ───────────────────────────────────────────────────

  /**
   * Set all pivot markers at once (replaces previous markers).
   * markers: array of { index, type: 'swing_high'|'swing_low', importance }
   */
  setPivotMarkers(markers) {
    const lwcMarkers = markers.map(m => {
      const candle = this.lwcCandles[m.index];
      if (!candle) return null;
      const isHigh = m.type === 'swing_high';
      return {
        time: candle.time,
        position: isHigh ? 'aboveBar' : 'belowBar',
        color: isHigh ? '#ef5350' : '#26a69a',
        shape: isHigh ? 'arrowDown' : 'arrowUp',
        text: m.importance === 'major' ? '★' : '',
      };
    }).filter(Boolean);

    // Sort by time (required by LWC)
    lwcMarkers.sort((a, b) => a.time - b.time);
    this.candleSeries.setMarkers(lwcMarkers);
    this._markers = markers;
  }

  // ── Trendlines ──────────────────────────────────────────────────────

  /**
   * Add a trendline between two points.
   * Returns an id for later removal.
   */
  addTrendline(id, index1, price1, index2, price2, type) {
    this.removeTrendline(id);

    const color = type === 'ascending'
      ? 'rgba(38, 166, 154, 0.8)'
      : 'rgba(239, 83, 80, 0.8)';

    // Extend line beyond anchor points
    const candle1 = this.lwcCandles[index1];
    const candle2 = this.lwcCandles[index2];
    if (!candle1 || !candle2) return;

    const slope = (price2 - price1) / (index2 - index1);

    // Start at first anchor, extend to the right edge
    const extStart = Math.min(index1, index2);
    const extEnd = this.lwcCandles.length - 1;

    const lineData = [];
    for (let i = extStart; i <= extEnd; i++) {
      const p = price1 + slope * (i - index1);
      lineData.push({ time: this.lwcCandles[i].time, value: p });
    }

    const lineSeries = this.chart.addLineSeries({
      color,
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    lineSeries.setData(lineData);

    this._lineSeries.push({ id, series: lineSeries });
  }

  removeTrendline(id) {
    const idx = this._lineSeries.findIndex(s => s.id === id);
    if (idx < 0) return;
    this.chart.removeSeries(this._lineSeries[idx].series);
    this._lineSeries.splice(idx, 1);
  }

  clearAllTrendlines() {
    for (const entry of [...this._lineSeries]) {
      this.removeTrendline(entry.id);
    }
  }

  // ── Comparison overlays ────────────────────────────────────────────

  /**
   * Add a comparison zone with custom color. Separate from annotation zones.
   */
  addComparisonZone(id, priceHigh, priceLow, color, startIndex) {
    this.removeComparisonZone(id);

    const start = (startIndex != null && startIndex >= 0) ? startIndex : 0;
    const end = this.lwcCandles.length - 1;
    if (end < 0) return;

    const topData = [];
    const bottomData = [];
    for (let i = start; i <= end; i++) {
      const t = this.lwcCandles[i].time;
      topData.push({ time: t, value: priceHigh });
      bottomData.push({ time: t, value: priceLow });
    }

    const topSeries = this.chart.addLineSeries({
      color,
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Solid,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    topSeries.setData(topData);

    const bottomSeries = this.chart.addLineSeries({
      color,
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Solid,
      crosshairMarkerVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    bottomSeries.setData(bottomData);

    const midPrice = (priceHigh + priceLow) / 2;
    const labelLine = this.candleSeries.createPriceLine({
      price: midPrice,
      color: 'transparent',
      lineWidth: 0,
      lineStyle: LightweightCharts.LineStyle.Solid,
      axisLabelVisible: true,
      title: id,
      axisLabelColor: color,
    });

    this._comparisonSeries.push({ id, topSeries, bottomSeries, labelLine });
  }

  removeComparisonZone(id) {
    const idx = this._comparisonSeries.findIndex(s => s.id === id);
    if (idx < 0) return;
    const entry = this._comparisonSeries[idx];
    this.chart.removeSeries(entry.topSeries);
    this.chart.removeSeries(entry.bottomSeries);
    this.candleSeries.removePriceLine(entry.labelLine);
    this._comparisonSeries.splice(idx, 1);
  }

  /**
   * Set comparison pivot markers on the lineSeries (doesn't overwrite annotation markers).
   */
  setComparisonMarkers(markers) {
    const lwcMarkers = markers.map(m => {
      const candle = this.lwcCandles[m.index];
      if (!candle) return null;
      const isHigh = m.type === 'swing_high';
      return {
        time: candle.time,
        position: isHigh ? 'aboveBar' : 'belowBar',
        color: m.color || '#ffffff',
        shape: isHigh ? 'arrowDown' : 'arrowUp',
        text: m.label || '',
      };
    }).filter(Boolean);

    lwcMarkers.sort((a, b) => a.time - b.time);
    this.lineSeries.setMarkers(lwcMarkers);
    this._comparisonMarkers = markers;
  }

  /**
   * Clear all comparison overlays (zones + markers).
   */
  clearComparison() {
    for (const entry of [...this._comparisonSeries]) {
      this.removeComparisonZone(entry.id);
    }
    this.lineSeries.setMarkers([]);
    this._comparisonMarkers = [];
  }

  // ── Coordinate helpers ──────────────────────────────────────────────

  /**
   * Subscribe to crosshair moves. Callback receives { time, price, x, y }.
   */
  onCrosshairMove(callback) {
    this.chart.subscribeCrosshairMove(param => {
      if (!param.time || !param.point) return;
      const price = this.candleSeries.coordinateToPrice(param.point.y);
      callback({
        time: param.time,
        price,
        x: param.point.x,
        y: param.point.y,
      });
    });
  }

  /**
   * Get the chart DOM element (for attaching mouse event listeners).
   */
  getChartElement() {
    return this.container;
  }

  /**
   * Subscribe to chart clicks. Callback receives { index, time, price }.
   */
  onClick(callback) {
    this.chart.subscribeClick(param => {
      if (!param.time || !param.point) return;
      const price = this.candleSeries.coordinateToPrice(param.point.y);
      const index = this.getCandleIndexByTime(param.time);
      callback({ index, time: param.time, price });
    });
  }

  /**
   * Subscribe to right-clicks on the chart. Callback receives { index, price }.
   */
  onRightClick(callback) {
    this.container.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      const rect = this.container.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const price = this.candleSeries.coordinateToPrice(y);
      // Find closest candle by x coordinate
      const logicalRange = this.chart.timeScale().getVisibleLogicalRange();
      if (!logicalRange || price == null) return;
      // Use time from coordinate
      const time = this.chart.timeScale().coordinateToTime(x);
      if (time == null) return;
      const index = this.getCandleIndexByTime(time);
      callback({ index, price });
    });
  }
}
