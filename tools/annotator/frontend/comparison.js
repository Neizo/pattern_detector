/**
 * ComparisonManager — displays algo vs human comparison overlays on the chart.
 *
 * Colors:
 *   Matched:         green  (#4caf50)
 *   False positive:  red    (#ef5350)
 *   False negative:  orange (#ff9800)
 */
class ComparisonManager {
  constructor(chartManager) {
    this.chart = chartManager;
    this.report = null;
    this.active = false;

    // Visibility toggles
    this._visible = { matched: true, fp: true, fn: true };

    // Track drawn overlay ids for toggle management
    this._drawnIds = { matched: [], fp: [], fn: [] };
  }

  // ── Main entry point ─────────────────────────────────────────────────

  async compare(pair, timeframe, lastN, before) {
    const params = new URLSearchParams({ pair, timeframe, last_n: lastN });
    if (before) params.set('before', before);

    const resp = await fetch(`/api/compare?${params}`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `Compare failed: ${resp.status}`);
    }

    this.report = await resp.json();
    this.active = true;
    this._visible = { matched: true, fp: true, fn: true };
    this._drawnIds = { matched: [], fp: [], fn: [] };

    this._drawAll();
    this._renderPanel();
  }

  clear() {
    this.chart.clearComparison();
    this.report = null;
    this.active = false;
    this._drawnIds = { matched: [], fp: [], fn: [] };

    // Hide comparison panel, show annotation panel
    document.getElementById('comparison-panel').classList.add('hidden');
    document.getElementById('annotation-content').classList.remove('hidden');
  }

  // ── Toggle visibility ────────────────────────────────────────────────

  setVisible(category, visible) {
    this._visible[category] = visible;
    const ids = this._drawnIds[category] || [];
    for (const id of ids) {
      this.chart.removeComparisonZone(id);
    }
    this._drawnIds[category] = [];

    if (visible) {
      this._redrawCategory(category);
    }
    // Redraw pivot markers (combined into one call)
    this._drawPivots();
  }

  // ── Drawing ──────────────────────────────────────────────────────────

  _drawAll() {
    this.chart.clearComparison();
    this._drawnIds = { matched: [], fp: [], fn: [] };
    this._drawLevels();
    this._drawPivots();
  }

  _redrawCategory(category) {
    // Redraw only levels for this category
    if (!this.report) return;
    const levels = this.report.levels || {};

    if (category === 'matched') {
      (levels.matched || []).forEach((m, i) => {
        this._drawLevelMatch(m, i);
      });
    } else if (category === 'fp') {
      (levels.false_positives || []).forEach((fp, i) => {
        this._drawLevelFP(fp, i);
      });
    } else if (category === 'fn') {
      (levels.false_negatives || []).forEach((fn, i) => {
        this._drawLevelFN(fn, i);
      });
    }
  }

  _drawLevels() {
    if (!this.report) return;
    const levels = this.report.levels || {};

    if (this._visible.matched) {
      (levels.matched || []).forEach((m, i) => this._drawLevelMatch(m, i));
    }
    if (this._visible.fp) {
      (levels.false_positives || []).forEach((fp, i) => this._drawLevelFP(fp, i));
    }
    if (this._visible.fn) {
      (levels.false_negatives || []).forEach((fn, i) => this._drawLevelFN(fn, i));
    }
  }

  _drawLevelMatch(match, idx) {
    const human = match.human;
    const algo = match.algo;
    // Human zone in blue
    const hId = `cmp_m_h_${idx}`;
    const startIdx = human.start_index || 0;
    this.chart.addComparisonZone(hId, human.price_high, human.price_low, 'rgba(41, 98, 255, 0.5)', startIdx);
    this._drawnIds.matched.push(hId);

    // Algo zone in green
    const aId = `cmp_m_a_${idx}`;
    const aStart = algo.start_index || 0;
    this.chart.addComparisonZone(aId, algo.zone_top, algo.zone_bottom, 'rgba(76, 175, 80, 0.5)', aStart);
    this._drawnIds.matched.push(aId);
  }

  _drawLevelFP(fp, idx) {
    const algo = fp.algo;
    const id = `cmp_fp_${idx}`;
    const start = algo.start_index || 0;
    this.chart.addComparisonZone(id, algo.zone_top, algo.zone_bottom, 'rgba(239, 83, 80, 0.5)', start);
    this._drawnIds.fp.push(id);
  }

  _drawLevelFN(fn, idx) {
    const human = fn.human;
    const id = `cmp_fn_${idx}`;
    const start = human.start_index || 0;
    this.chart.addComparisonZone(id, human.price_high, human.price_low, 'rgba(255, 152, 0, 0.5)', start);
    this._drawnIds.fn.push(id);
  }

  _drawPivots() {
    if (!this.report) return;
    const pivots = this.report.pivots || {};
    const markers = [];

    if (this._visible.matched) {
      for (const m of (pivots.matched || [])) {
        markers.push({
          index: m.algo.index,
          type: m.algo.type,
          color: '#4caf50',
          label: 'M',
        });
      }
    }

    if (this._visible.fp) {
      for (const fp of (pivots.false_positives || [])) {
        markers.push({
          index: fp.algo.index,
          type: fp.algo.type,
          color: '#ef5350',
          label: 'FP',
        });
      }
    }

    if (this._visible.fn) {
      for (const fn of (pivots.false_negatives || [])) {
        markers.push({
          index: fn.human.index,
          type: fn.human.type,
          color: '#ff9800',
          label: 'FN',
        });
      }
    }

    this.chart.setComparisonMarkers(markers);
  }

  // ── Panel rendering ──────────────────────────────────────────────────

  _renderPanel() {
    const panel = document.getElementById('comparison-panel');
    panel.classList.remove('hidden');
    document.getElementById('annotation-content').classList.add('hidden');

    const summary = this.report.summary || {};

    // Build summary HTML
    let summaryHtml = '<div class="cmp-summary">';
    for (const [type, stats] of Object.entries(summary)) {
      if (stats.matched === 0 && stats.false_positives === 0 && stats.false_negatives === 0) continue;
      summaryHtml += `
        <div class="summary-card">
          <div class="summary-title">${type.charAt(0).toUpperCase() + type.slice(1)}</div>
          <div class="summary-metrics">
            <span class="metric matched">M: ${stats.matched}</span>
            <span class="metric fp">FP: ${stats.false_positives}</span>
            <span class="metric fn">FN: ${stats.false_negatives}</span>
          </div>
          <div class="summary-scores">
            <span>P: ${(stats.precision * 100).toFixed(0)}%</span>
            <span>R: ${(stats.recall * 100).toFixed(0)}%</span>
          </div>
        </div>
      `;
    }
    summaryHtml += '</div>';

    // Toggles
    const togglesHtml = `
      <div class="cmp-toggles">
        <label class="toggle-row">
          <input type="checkbox" data-cat="matched" checked>
          <span class="dot matched-dot"></span> Matched
        </label>
        <label class="toggle-row">
          <input type="checkbox" data-cat="fp" checked>
          <span class="dot fp-dot"></span> Faux positifs
        </label>
        <label class="toggle-row">
          <input type="checkbox" data-cat="fn" checked>
          <span class="dot fn-dot"></span> Faux négatifs
        </label>
      </div>
    `;

    // Divergence list
    let listHtml = '<div class="cmp-divergences">';
    listHtml += this._renderDivergenceSection('Levels', this.report.levels);
    listHtml += this._renderDivergenceSection('Pivots', this.report.pivots);
    listHtml += this._renderDivergenceSection('Trendlines', this.report.trendlines);
    listHtml += '</div>';

    // Back button
    const backHtml = `<button class="btn-validate" id="btn-cmp-back" style="width:100%;margin-top:8px;">Retour annotations</button>`;

    panel.innerHTML = summaryHtml + togglesHtml + listHtml + backHtml;

    // Bind toggle events
    panel.querySelectorAll('.cmp-toggles input[type="checkbox"]').forEach(cb => {
      cb.addEventListener('change', () => {
        this.setVisible(cb.dataset.cat, cb.checked);
      });
    });

    // Bind back button
    document.getElementById('btn-cmp-back').addEventListener('click', () => {
      this.clear();
    });
  }

  _renderDivergenceSection(title, typeReport) {
    if (!typeReport) return '';
    const { matched, false_positives, false_negatives } = typeReport;
    const total = (matched?.length || 0) + (false_positives?.length || 0) + (false_negatives?.length || 0);
    if (total === 0) return '';

    const prec = this.chart.pricePrecision;
    let html = `<div class="cmp-section-title">${title}</div>`;

    // Matched
    for (const m of (matched || [])) {
      const price = m.algo?.price ?? m.algo?.index ?? '?';
      const detail = typeof price === 'number' ? price.toFixed(prec) : price;
      html += `<div class="divergence-item matched" data-price="${price}">
        <span class="dot matched-dot"></span>
        <span>Match · ${detail}</span>
      </div>`;
    }

    // False positives
    for (const fp of (false_positives || [])) {
      const price = fp.algo?.price ?? fp.algo?.index ?? '?';
      const detail = typeof price === 'number' ? price.toFixed(prec) : price;
      html += `<div class="divergence-item fp" data-price="${price}">
        <span class="dot fp-dot"></span>
        <span>FP · ${detail}</span>
      </div>`;
    }

    // False negatives
    for (const fn of (false_negatives || [])) {
      const price = fn.human?.price_high ?? fn.human?.index ?? '?';
      const detail = typeof price === 'number' ? price.toFixed(prec) : price;
      html += `<div class="divergence-item fn" data-price="${price}">
        <span class="dot fn-dot"></span>
        <span>FN · ${detail}</span>
      </div>`;
    }

    return html;
  }
}
