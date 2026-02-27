/**
 * AnnotationManager — handles creation, editing, deletion of annotations.
 *
 * Modes: levels, trendlines, pivots, patterns
 * Phase 1 implements: levels
 */
class AnnotationManager {
  constructor(chartManager) {
    this.chart = chartManager;
    this.mode = 'levels';

    // Annotation storage by type
    this.annotations = {
      levels: [],
      trendlines: [],
      pivots: [],
      patterns: [],
    };

    // Auto-label counters
    this._labelCounters = { S: 0, R: 0 };

    // Drag state for level creation
    this._dragState = null;   // { startY, startPrice }
    this._previewLine = null;

    // Trendline creation state
    this._trendlineState = null;  // { index1, price1 }

    // Pattern creation state
    this._patternState = null;

    // Dirty flag for save indicator
    this.dirty = false;

    this._bindEvents();
  }

  // ── Mode switching ──────────────────────────────────────────────────

  setMode(mode) {
    this.mode = mode;
    this._updateInstructions();
    this._cancelPending();
    this._hideForm();
  }

  _updateInstructions() {
    const el = document.getElementById('instr-text');
    const instructions = {
      levels: 'Cliquez-glissez verticalement sur le chart pour tracer une zone S/R.',
      trendlines: 'Cliquez sur un premier point, puis un deuxième pour tracer une trendline.',
      pivots: 'Cliquez sur une bougie pour marquer un pivot (haut du chart = swing_high, bas = swing_low).',
      patterns: 'Sélectionnez un type de pattern puis cliquez les key_points dans l\'ordre.',
    };
    el.textContent = instructions[this.mode] || '';
  }

  // ── Event binding ───────────────────────────────────────────────────

  _bindEvents() {
    const chartEl = this.chart.getChartElement();

    chartEl.addEventListener('mousedown', (e) => this._onMouseDown(e));
    chartEl.addEventListener('mousemove', (e) => this._onMouseMove(e));
    chartEl.addEventListener('mouseup', (e) => this._onMouseUp(e));

    // Chart click for pivots and trendlines
    this.chart.onClick((info) => this._onChartClick(info));
  }

  // ── Level creation (click-drag) ─────────────────────────────────────

  _onMouseDown(e) {
    if (this.mode !== 'levels') return;
    if (e.button !== 0) return;

    const rect = this.chart.getChartElement().getBoundingClientRect();
    const y = e.clientY - rect.top;
    const price = this.chart.yToPrice(y);
    if (price == null) return;

    this._dragState = { startY: y, startPrice: price };
  }

  _onMouseMove(e) {
    if (!this._dragState || this.mode !== 'levels') return;

    const rect = this.chart.getChartElement().getBoundingClientRect();
    const y = e.clientY - rect.top;
    const currentPrice = this.chart.yToPrice(y);
    if (currentPrice == null) return;

    // Preview: show temporary price lines
    const priceHigh = Math.max(this._dragState.startPrice, currentPrice);
    const priceLow = Math.min(this._dragState.startPrice, currentPrice);

    // Remove previous preview
    if (this._previewLine) {
      this.chart.removeLevelZone('__preview__');
    }
    this.chart.addLevelZone('__preview__', priceHigh, priceLow, 'resistance');
    this._previewLine = true;
  }

  _onMouseUp(e) {
    if (!this._dragState || this.mode !== 'levels') return;

    const rect = this.chart.getChartElement().getBoundingClientRect();
    const y = e.clientY - rect.top;
    const endPrice = this.chart.yToPrice(y);

    // Minimum drag distance (at least a few pixels)
    if (Math.abs(y - this._dragState.startY) < 5) {
      this._dragState = null;
      if (this._previewLine) {
        this.chart.removeLevelZone('__preview__');
        this._previewLine = null;
      }
      return;
    }

    const priceHigh = Math.max(this._dragState.startPrice, endPrice);
    const priceLow = Math.min(this._dragState.startPrice, endPrice);

    // Remove preview
    this.chart.removeLevelZone('__preview__');
    this._previewLine = null;
    this._dragState = null;

    // Show form for this level
    this._showLevelForm(priceHigh, priceLow);
  }

  _showLevelForm(priceHigh, priceLow) {
    const formEl = document.getElementById('annotation-form');
    formEl.classList.remove('hidden');

    const prec = this.chart.pricePrecision;

    formEl.innerHTML = `
      <div class="form-row">
        <label>Zone</label>
        <span style="color: var(--text-primary); font-size: 12px;">
          ${priceLow.toFixed(prec)} — ${priceHigh.toFixed(prec)}
        </span>
      </div>
      <div class="form-row">
        <label>Type</label>
        <div class="radio-group">
          <label><input type="radio" name="level-type" value="support"> Support</label>
          <label><input type="radio" name="level-type" value="resistance" checked> Resistance</label>
        </div>
      </div>
      <div class="form-row">
        <label>Note</label>
        <input type="text" id="level-note" placeholder="Optionnel...">
      </div>
      <div class="form-actions">
        <button class="btn-validate" id="btn-level-ok">Valider</button>
        <button class="btn-delete" id="btn-level-cancel">Annuler</button>
      </div>
    `;

    // Temporary preview
    this.chart.addLevelZone('__pending__', priceHigh, priceLow, 'resistance');

    // Update preview on type change
    formEl.querySelectorAll('input[name="level-type"]').forEach(radio => {
      radio.addEventListener('change', () => {
        const type = formEl.querySelector('input[name="level-type"]:checked').value;
        this.chart.removeLevelZone('__pending__');
        this.chart.addLevelZone('__pending__', priceHigh, priceLow, type);
      });
    });

    document.getElementById('btn-level-ok').addEventListener('click', () => {
      const type = formEl.querySelector('input[name="level-type"]:checked').value;
      const note = document.getElementById('level-note').value.trim();

      this.chart.removeLevelZone('__pending__');
      this._addLevel(priceHigh, priceLow, type, note);
      this._hideForm();
    });

    document.getElementById('btn-level-cancel').addEventListener('click', () => {
      this.chart.removeLevelZone('__pending__');
      this._hideForm();
    });
  }

  _addLevel(priceHigh, priceLow, type, note) {
    const prefix = type === 'support' ? 'S' : 'R';
    this._labelCounters[prefix]++;
    const label = `${prefix}${this._labelCounters[prefix]}`;

    const level = {
      id: label,
      price_high: priceHigh,
      price_low: priceLow,
      type,
      note,
    };

    this.annotations.levels.push(level);
    this.chart.addLevelZone(label, priceHigh, priceLow, type);
    this.dirty = true;
    this._updateUI();
  }

  // ── Pivot creation (click) ──────────────────────────────────────────

  _onChartClick(info) {
    if (this.mode === 'pivots') {
      this._handlePivotClick(info);
    } else if (this.mode === 'trendlines') {
      this._handleTrendlineClick(info);
    }
  }

  _handlePivotClick(info) {
    // Auto-detect type: if click is above candle midpoint → swing_high, else swing_low
    const candle = this.chart.candles[info.index];
    if (!candle) return;
    const mid = (candle.high + candle.low) / 2;
    const type = info.price >= mid ? 'swing_high' : 'swing_low';

    this._showPivotForm(info.index, type, info.price);
  }

  _showPivotForm(index, detectedType, clickPrice) {
    const formEl = document.getElementById('annotation-form');
    formEl.classList.remove('hidden');

    const candle = this.chart.candles[index];
    const prec = this.chart.pricePrecision;
    const price = detectedType === 'swing_high' ? candle.high : candle.low;

    formEl.innerHTML = `
      <div class="form-row">
        <label>Bougie</label>
        <span style="color: var(--text-primary); font-size: 12px;">#${index} — ${price.toFixed(prec)}</span>
      </div>
      <div class="form-row">
        <label>Type</label>
        <div class="radio-group">
          <label><input type="radio" name="pivot-type" value="swing_high" ${detectedType === 'swing_high' ? 'checked' : ''}> Swing High</label>
          <label><input type="radio" name="pivot-type" value="swing_low" ${detectedType === 'swing_low' ? 'checked' : ''}> Swing Low</label>
        </div>
      </div>
      <div class="form-row">
        <label>Import.</label>
        <div class="radio-group">
          <label><input type="radio" name="pivot-imp" value="minor"> Minor</label>
          <label><input type="radio" name="pivot-imp" value="medium" checked> Medium</label>
          <label><input type="radio" name="pivot-imp" value="major"> Major</label>
        </div>
      </div>
      <div class="form-actions">
        <button class="btn-validate" id="btn-pivot-ok">Valider</button>
        <button class="btn-delete" id="btn-pivot-cancel">Annuler</button>
      </div>
    `;

    // Show temporary marker
    this._showTempPivotMarker(index, detectedType, 'medium');

    // Update preview on type change
    formEl.querySelectorAll('input[name="pivot-type"], input[name="pivot-imp"]').forEach(radio => {
      radio.addEventListener('change', () => {
        const t = formEl.querySelector('input[name="pivot-type"]:checked').value;
        const imp = formEl.querySelector('input[name="pivot-imp"]:checked').value;
        this._showTempPivotMarker(index, t, imp);
      });
    });

    document.getElementById('btn-pivot-ok').addEventListener('click', () => {
      const type = formEl.querySelector('input[name="pivot-type"]:checked').value;
      const importance = formEl.querySelector('input[name="pivot-imp"]:checked').value;
      this._addPivot(index, type, importance);
      this._hideForm();
    });

    document.getElementById('btn-pivot-cancel').addEventListener('click', () => {
      this._refreshPivotMarkers();
      this._hideForm();
    });
  }

  _showTempPivotMarker(index, type, importance) {
    // Show all existing markers plus the temp one
    const allMarkers = [
      ...this.annotations.pivots.map(p => ({ index: p.index, type: p.type, importance: p.importance })),
      { index, type, importance },
    ];
    this.chart.setPivotMarkers(allMarkers);
  }

  _addPivot(index, type, importance) {
    // Check for duplicate at same index
    const existing = this.annotations.pivots.findIndex(p => p.index === index);
    if (existing >= 0) {
      this.annotations.pivots.splice(existing, 1);
    }

    this.annotations.pivots.push({ index, type, importance });
    this.dirty = true;
    this._refreshPivotMarkers();
    this._updateUI();
  }

  _refreshPivotMarkers() {
    this.chart.setPivotMarkers(
      this.annotations.pivots.map(p => ({ index: p.index, type: p.type, importance: p.importance }))
    );
  }

  // ── Trendline creation (two clicks) ─────────────────────────────────

  _handleTrendlineClick(info) {
    if (!this._trendlineState) {
      // First click
      this._trendlineState = { index1: info.index, price1: info.price };
      document.getElementById('instr-text').textContent =
        `Point 1 sélectionné (#${info.index}). Cliquez le deuxième point.`;
    } else {
      // Second click
      const { index1, price1 } = this._trendlineState;
      const index2 = info.index;
      const price2 = info.price;
      this._trendlineState = null;

      if (index1 === index2) {
        this._updateInstructions();
        return;
      }

      // Snap to candle high/low
      const candle1 = this.chart.candles[index1];
      const candle2 = this.chart.candles[index2];
      const slope = (price2 - price1);
      const type = slope > 0 ? 'ascending' : 'descending';

      // Snap: for ascending, prefer lows; for descending, prefer highs
      const snap1 = type === 'ascending' ? candle1.low : candle1.high;
      const snap2 = type === 'ascending' ? candle2.low : candle2.high;

      this._showTrendlineForm(index1, snap1, index2, snap2, type);
    }
  }

  _showTrendlineForm(index1, price1, index2, price2, detectedType) {
    const formEl = document.getElementById('annotation-form');
    formEl.classList.remove('hidden');
    const prec = this.chart.pricePrecision;

    formEl.innerHTML = `
      <div class="form-row">
        <label>Points</label>
        <span style="color: var(--text-primary); font-size: 12px;">
          #${index1} (${price1.toFixed(prec)}) → #${index2} (${price2.toFixed(prec)})
        </span>
      </div>
      <div class="form-row">
        <label>Type</label>
        <div class="radio-group">
          <label><input type="radio" name="tl-type" value="ascending" ${detectedType === 'ascending' ? 'checked' : ''}> Ascending</label>
          <label><input type="radio" name="tl-type" value="descending" ${detectedType === 'descending' ? 'checked' : ''}> Descending</label>
        </div>
      </div>
      <div class="form-row">
        <label>Note</label>
        <input type="text" id="tl-note" placeholder="Optionnel...">
      </div>
      <div class="form-actions">
        <button class="btn-validate" id="btn-tl-ok">Valider</button>
        <button class="btn-delete" id="btn-tl-cancel">Annuler</button>
      </div>
    `;

    // Preview
    const tempId = '__pending_tl__';
    this.chart.addTrendline(tempId, index1, price1, index2, price2, detectedType);

    document.getElementById('btn-tl-ok').addEventListener('click', () => {
      const type = formEl.querySelector('input[name="tl-type"]:checked').value;
      const note = document.getElementById('tl-note').value.trim();
      this.chart.removeTrendline(tempId);
      this._addTrendline(index1, price1, index2, price2, type, note);
      this._hideForm();
    });

    document.getElementById('btn-tl-cancel').addEventListener('click', () => {
      this.chart.removeTrendline(tempId);
      this._hideForm();
      this._updateInstructions();
    });
  }

  _addTrendline(index1, price1, index2, price2, type, note) {
    const id = `TL${this.annotations.trendlines.length + 1}`;
    const trendline = {
      id,
      points: [
        { index: index1, price: price1 },
        { index: index2, price: price2 },
      ],
      type,
      note,
    };
    this.annotations.trendlines.push(trendline);
    this.chart.addTrendline(id, index1, price1, index2, price2, type);
    this.dirty = true;
    this._updateUI();
    this._updateInstructions();
  }

  // ── Remove annotation ───────────────────────────────────────────────

  removeAnnotation(type, index) {
    const list = this.annotations[type];
    if (!list || index < 0 || index >= list.length) return;

    const item = list[index];

    if (type === 'levels') {
      this.chart.removeLevelZone(item.id);
    } else if (type === 'trendlines') {
      this.chart.removeTrendline(item.id);
    } else if (type === 'pivots') {
      // Will refresh all markers
    }

    list.splice(index, 1);

    if (type === 'pivots') {
      this._refreshPivotMarkers();
    }

    this.dirty = true;
    this._updateUI();
  }

  // ── UI updates ──────────────────────────────────────────────────────

  _updateUI() {
    this._updateCounts();
    this._updateList();
    this._updateSaveStatus();
  }

  _updateCounts() {
    for (const type of ['levels', 'trendlines', 'pivots', 'patterns']) {
      const badge = document.querySelector(`.count-badge[data-type="${type}"] b`);
      if (badge) badge.textContent = this.annotations[type].length;
    }
  }

  _updateList() {
    const listEl = document.getElementById('annotation-list');
    listEl.innerHTML = '';

    const prec = this.chart.pricePrecision;

    // Levels
    this.annotations.levels.forEach((lvl, i) => {
      const item = this._createListItem(
        lvl.id,
        lvl.type === 'support' ? 'support' : 'resistance',
        `${lvl.price_low.toFixed(prec)} — ${lvl.price_high.toFixed(prec)}${lvl.note ? ' · ' + lvl.note : ''}`,
        () => this.removeAnnotation('levels', i),
      );
      listEl.appendChild(item);
    });

    // Trendlines
    this.annotations.trendlines.forEach((tl, i) => {
      const item = this._createListItem(
        tl.id,
        'trendline',
        `${tl.type} #${tl.points[0].index}→#${tl.points[1].index}${tl.note ? ' · ' + tl.note : ''}`,
        () => this.removeAnnotation('trendlines', i),
      );
      listEl.appendChild(item);
    });

    // Pivots
    this.annotations.pivots.forEach((p, i) => {
      const cls = p.type === 'swing_high' ? 'pivot-high' : 'pivot-low';
      const item = this._createListItem(
        `P#${p.index}`,
        cls,
        `${p.type} [${p.importance}]`,
        () => this.removeAnnotation('pivots', i),
      );
      listEl.appendChild(item);
    });

    // Patterns
    this.annotations.patterns.forEach((pat, i) => {
      const item = this._createListItem(
        pat.pattern_type,
        'pattern',
        `${pat.key_points?.length || 0} points${pat.note ? ' · ' + pat.note : ''}`,
        () => this.removeAnnotation('patterns', i),
      );
      listEl.appendChild(item);
    });
  }

  _createListItem(label, labelClass, info, onRemove) {
    const div = document.createElement('div');
    div.className = 'annotation-item';
    div.innerHTML = `
      <span class="label ${labelClass}">${label}</span>
      <span class="info">${info}</span>
    `;

    const btn = document.createElement('button');
    btn.className = 'btn-remove';
    btn.textContent = '×';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      onRemove();
    });
    div.appendChild(btn);

    return div;
  }

  _updateSaveStatus() {
    const el = document.getElementById('save-status');
    if (this.dirty) {
      el.textContent = 'Non sauvegardé •';
      el.style.color = 'var(--accent-orange)';
    } else {
      el.textContent = 'Sauvegardé ✓';
      el.style.color = 'var(--accent-green)';
    }
    document.getElementById('btn-save').disabled = !this.dirty;
  }

  // ── Helpers ─────────────────────────────────────────────────────────

  _hideForm() {
    document.getElementById('annotation-form').classList.add('hidden');
  }

  _cancelPending() {
    this._dragState = null;
    this._trendlineState = null;
    this._patternState = null;
    if (this._previewLine) {
      this.chart.removeLevelZone('__preview__');
      this._previewLine = null;
    }
  }

  // ── Serialization ───────────────────────────────────────────────────

  toPayload(pair, timeframe, lastN, before) {
    return {
      pair,
      timeframe,
      window: { last_n: lastN, before: before || null },
      annotations: {
        levels: this.annotations.levels.map(l => ({
          price_high: l.price_high,
          price_low: l.price_low,
          type: l.type,
          note: l.note,
        })),
        trendlines: this.annotations.trendlines.map(t => ({
          points: t.points,
          type: t.type,
          note: t.note,
        })),
        pivots: this.annotations.pivots.map(p => ({
          index: p.index,
          type: p.type,
          importance: p.importance,
        })),
        patterns: this.annotations.patterns.map(p => ({
          pattern_type: p.pattern_type,
          key_points: p.key_points,
          note: p.note,
        })),
      },
    };
  }

  /**
   * Load annotations from a saved payload and redraw everything.
   */
  loadFromPayload(data) {
    if (!data || !data.annotations) return;

    // Clear existing
    this.chart.clearAllLevelZones();
    this.chart.clearAllTrendlines();
    this.chart.setPivotMarkers([]);
    this.annotations = { levels: [], trendlines: [], pivots: [], patterns: [] };
    this._labelCounters = { S: 0, R: 0 };

    const ann = data.annotations;

    // Restore levels
    if (ann.levels) {
      for (const l of ann.levels) {
        this._addLevel(l.price_high, l.price_low, l.type, l.note || '');
      }
    }

    // Restore trendlines
    if (ann.trendlines) {
      for (const t of ann.trendlines) {
        if (t.points && t.points.length >= 2) {
          this._addTrendline(
            t.points[0].index, t.points[0].price,
            t.points[1].index, t.points[1].price,
            t.type, t.note || ''
          );
        }
      }
    }

    // Restore pivots
    if (ann.pivots) {
      for (const p of ann.pivots) {
        this.annotations.pivots.push({ index: p.index, type: p.type, importance: p.importance });
      }
      this._refreshPivotMarkers();
    }

    // Restore patterns
    if (ann.patterns) {
      this.annotations.patterns = ann.patterns.map(p => ({ ...p }));
    }

    this.dirty = false;
    this._updateUI();
  }
}
