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
      algo_notes: [],
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

    // Pivot batch mode: importance selected in panel before clicking
    this._pivotImportance = 'medium';

    // Dirty flag for save indicator
    this.dirty = false;

    // Undo/redo stacks
    this._undoStack = [];
    this._redoStack = [];
    this._maxUndoSize = 50;

    // Form keyboard handler ref (for cleanup)
    this._formKeyHandler = null;

    this._bindEvents();
  }

  // ── Mode switching ──────────────────────────────────────────────────

  setMode(mode) {
    this.mode = mode;
    this._updateInstructions();
    this._cancelPending();
    this._hideForm();
    this._showPivotPanel(mode === 'pivots');
  }

  _updateInstructions() {
    const el = document.getElementById('instr-text');
    const instructions = {
      levels: 'Cliquez-glissez verticalement sur le chart pour tracer une zone S/R.',
      trendlines: 'Cliquez sur un premier point, puis un deuxième pour tracer une trendline.',
      pivots: 'Clic gauche = ajouter pivot · Clic droit = supprimer. Choisissez l\'importance ci-dessous.',
      patterns: 'Sélectionnez un type de pattern puis cliquez les key_points dans l\'ordre.',
    };
    el.textContent = instructions[this.mode] || '';
  }

  _showPivotPanel(show) {
    const formEl = document.getElementById('annotation-form');
    if (!show) return;

    formEl.classList.remove('hidden');
    formEl.innerHTML = `
      <div class="form-row">
        <label>Import.</label>
        <div class="radio-group">
          <label><input type="radio" name="pivot-imp-batch" value="minor" ${this._pivotImportance === 'minor' ? 'checked' : ''}> Minor</label>
          <label><input type="radio" name="pivot-imp-batch" value="medium" ${this._pivotImportance === 'medium' ? 'checked' : ''}> Medium</label>
          <label><input type="radio" name="pivot-imp-batch" value="major" ${this._pivotImportance === 'major' ? 'checked' : ''}> Major</label>
        </div>
      </div>
      <div class="form-row" style="margin-top: 4px;">
        <span style="color: var(--text-secondary); font-size: 11px;">
          Pivots: ${this.annotations.pivots.length}
        </span>
      </div>
    `;

    formEl.querySelectorAll('input[name="pivot-imp-batch"]').forEach(radio => {
      radio.addEventListener('change', () => {
        this._pivotImportance = formEl.querySelector('input[name="pivot-imp-batch"]:checked').value;
      });
    });
  }

  // ── Event binding ───────────────────────────────────────────────────

  _bindEvents() {
    const chartEl = this.chart.getChartElement();

    chartEl.addEventListener('mousedown', (e) => this._onMouseDown(e));
    chartEl.addEventListener('mousemove', (e) => this._onMouseMove(e));
    chartEl.addEventListener('mouseup', (e) => this._onMouseUp(e));

    // Chart left-click for pivots and trendlines
    this.chart.onClick((info) => this._onChartClick(info));

    // Chart right-click for pivot removal
    this.chart.onRightClick((info) => this._onChartRightClick(info));
  }

  // ── Level creation (click-drag) ─────────────────────────────────────

  _onMouseDown(e) {
    if (this.mode !== 'levels') return;
    if (e.button !== 0) return;

    const rect = this.chart.getChartElement().getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const price = this.chart.yToPrice(y);
    if (price == null) return;

    // Capture the candle index where the level starts
    const time = this.chart.chart.timeScale().coordinateToTime(x);
    const startIndex = time != null ? this.chart.getCandleIndexByTime(time) : 0;

    this._dragState = { startY: y, startPrice: price, startIndex };
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
    this.chart.addLevelZone('__preview__', priceHigh, priceLow, 'resistance', this._dragState.startIndex);
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
    const startIndex = this._dragState.startIndex;

    // Remove preview
    this.chart.removeLevelZone('__preview__');
    this._previewLine = null;
    this._dragState = null;

    // Show form for this level
    this._showLevelForm(priceHigh, priceLow, startIndex);
  }

  _showLevelForm(priceHigh, priceLow, startIndex) {
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
    this.chart.addLevelZone('__pending__', priceHigh, priceLow, 'resistance', startIndex);

    // Update preview on type change
    formEl.querySelectorAll('input[name="level-type"]').forEach(radio => {
      radio.addEventListener('change', () => {
        const type = formEl.querySelector('input[name="level-type"]:checked').value;
        this.chart.removeLevelZone('__pending__');
        this.chart.addLevelZone('__pending__', priceHigh, priceLow, type, startIndex);
      });
    });

    const validateLevel = () => {
      const type = formEl.querySelector('input[name="level-type"]:checked').value;
      const note = document.getElementById('level-note').value.trim();
      this.chart.removeLevelZone('__pending__');
      this._addLevel(priceHigh, priceLow, type, note, startIndex);
      this._hideForm();
    };

    const cancelLevel = () => {
      this.chart.removeLevelZone('__pending__');
      this._hideForm();
    };

    document.getElementById('btn-level-ok').addEventListener('click', validateLevel);
    document.getElementById('btn-level-cancel').addEventListener('click', cancelLevel);
    this._bindFormKeys(validateLevel, cancelLevel);

    // Auto-focus note field
    setTimeout(() => document.getElementById('level-note')?.focus(), 50);
  }

  _addLevel(priceHigh, priceLow, type, note, startIndex) {
    const prefix = type === 'support' ? 'S' : 'R';
    this._labelCounters[prefix]++;
    const label = `${prefix}${this._labelCounters[prefix]}`;

    const level = {
      id: label,
      price_high: priceHigh,
      price_low: priceLow,
      type,
      note,
      start_index: startIndex != null ? startIndex : 0,
    };

    this.annotations.levels.push(level);
    this.chart.addLevelZone(label, priceHigh, priceLow, type, level.start_index);
    this._pushUndo({ action: 'add', type: 'levels', data: { ...level }, index: this.annotations.levels.length - 1 });
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
    // Batch mode: auto-detect type, add immediately with current importance
    const candle = this.chart.candles[info.index];
    if (!candle) return;
    const mid = (candle.high + candle.low) / 2;
    const type = info.price >= mid ? 'swing_high' : 'swing_low';

    this._addPivot(info.index, type, this._pivotImportance);
    // Refresh the pivot panel counter
    this._showPivotPanel(true);
  }

  _onChartRightClick(info) {
    if (this.mode !== 'pivots') return;

    // Find closest pivot within ±2 candles
    const tolerance = 2;
    let closest = -1;
    let closestDist = Infinity;
    this.annotations.pivots.forEach((p, i) => {
      const dist = Math.abs(p.index - info.index);
      if (dist <= tolerance && dist < closestDist) {
        closestDist = dist;
        closest = i;
      }
    });

    if (closest >= 0) {
      this.annotations.pivots.splice(closest, 1);
      this.dirty = true;
      this._refreshPivotMarkers();
      this._updateUI();
      this._showPivotPanel(true);
    }
  }

  _addPivot(index, type, importance) {
    // Check for duplicate at same index
    const existing = this.annotations.pivots.findIndex(p => p.index === index);
    if (existing >= 0) {
      this.annotations.pivots.splice(existing, 1);
    }

    const pivotData = { index, type, importance };
    this.annotations.pivots.push(pivotData);
    this._pushUndo({ action: 'add', type: 'pivots', data: { ...pivotData }, index: this.annotations.pivots.length - 1 });
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

    const validateTl = () => {
      const type = formEl.querySelector('input[name="tl-type"]:checked').value;
      const note = document.getElementById('tl-note').value.trim();
      this.chart.removeTrendline(tempId);
      this._addTrendline(index1, price1, index2, price2, type, note);
      this._hideForm();
    };

    const cancelTl = () => {
      this.chart.removeTrendline(tempId);
      this._hideForm();
      this._updateInstructions();
    };

    document.getElementById('btn-tl-ok').addEventListener('click', validateTl);
    document.getElementById('btn-tl-cancel').addEventListener('click', cancelTl);
    this._bindFormKeys(validateTl, cancelTl);

    // Auto-focus note field
    setTimeout(() => document.getElementById('tl-note')?.focus(), 50);
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
    this._pushUndo({ action: 'add', type: 'trendlines', data: { ...trendline, points: [...trendline.points] }, index: this.annotations.trendlines.length - 1 });
    this.dirty = true;
    this._updateUI();
    this._updateInstructions();
  }

  // ── Remove annotation ───────────────────────────────────────────────

  removeAnnotation(type, index) {
    const list = this.annotations[type];
    if (!list || index < 0 || index >= list.length) return;

    const item = list[index];
    this._pushUndo({ action: 'remove', type, data: { ...item }, index });

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
        () => this.chart.scrollToIndex(lvl.start_index || 0, 30),
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
        () => this.chart.scrollToIndex(tl.points[0].index, 30),
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
        () => this.chart.scrollToIndex(p.index, 30),
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

  _createListItem(label, labelClass, info, onRemove, onNavigate) {
    const div = document.createElement('div');
    div.className = 'annotation-item';
    div.innerHTML = `
      <span class="label ${labelClass}">${label}</span>
      <span class="info">${info}</span>
    `;

    if (onNavigate) {
      div.addEventListener('click', () => {
        onNavigate();
        div.classList.add('highlighted');
        setTimeout(() => div.classList.remove('highlighted'), 600);
      });
    }

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
    this._removeFormKeyHandler();
  }

  _bindFormKeys(onValidate, onCancel) {
    this._removeFormKeyHandler();
    this._formKeyHandler = (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        onValidate();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onCancel();
      }
    };
    document.addEventListener('keydown', this._formKeyHandler);
  }

  _removeFormKeyHandler() {
    if (this._formKeyHandler) {
      document.removeEventListener('keydown', this._formKeyHandler);
      this._formKeyHandler = null;
    }
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

  // ── Algo notes CRUD ────────────────────────────────────────────────

  /**
   * Find an algo note matching the given zone prices (tolerance 1e-6).
   */
  getAlgoNote(zoneTop, zoneBottom) {
    const tol = 1e-6;
    return this.annotations.algo_notes.find(
      n => Math.abs(n.zone_top - zoneTop) < tol && Math.abs(n.zone_bottom - zoneBottom) < tol
    ) || null;
  }

  /**
   * Add or update an algo note. Returns the note object.
   */
  addAlgoNote(zoneTop, zoneBottom, type, note) {
    const existing = this.getAlgoNote(zoneTop, zoneBottom);
    if (existing) {
      const oldNote = existing.note;
      existing.note = note;
      existing.type = type;
      this._pushUndo({ action: 'update_algo_note', data: { zone_top: zoneTop, zone_bottom: zoneBottom, old_note: oldNote, new_note: note, type } });
    } else {
      const entry = { zone_top: zoneTop, zone_bottom: zoneBottom, type, note };
      this.annotations.algo_notes.push(entry);
      this._pushUndo({ action: 'add_algo_note', data: { ...entry }, index: this.annotations.algo_notes.length - 1 });
    }
    this.dirty = true;
    this._updateUI();
    return this.getAlgoNote(zoneTop, zoneBottom);
  }

  /**
   * Remove an algo note by zone prices.
   */
  removeAlgoNote(zoneTop, zoneBottom) {
    const tol = 1e-6;
    const idx = this.annotations.algo_notes.findIndex(
      n => Math.abs(n.zone_top - zoneTop) < tol && Math.abs(n.zone_bottom - zoneBottom) < tol
    );
    if (idx >= 0) {
      const removed = this.annotations.algo_notes.splice(idx, 1)[0];
      this._pushUndo({ action: 'remove_algo_note', data: { ...removed }, index: idx });
      this.dirty = true;
      this._updateUI();
    }
  }

  // ── Undo / Redo ────────────────────────────────────────────────────

  _pushUndo(entry) {
    this._undoStack.push(entry);
    if (this._undoStack.length > this._maxUndoSize) {
      this._undoStack.shift();
    }
    this._redoStack = [];
  }

  undo() {
    if (this._undoStack.length === 0) return;
    const entry = this._undoStack.pop();
    this._redoStack.push(entry);
    this._applyUndoEntry(entry, true);
  }

  redo() {
    if (this._redoStack.length === 0) return;
    const entry = this._redoStack.pop();
    this._undoStack.push(entry);
    this._applyUndoEntry(entry, false);
  }

  _applyUndoEntry(entry, isUndo) {
    // Handle algo note undo/redo separately
    if (entry.action === 'add_algo_note' || entry.action === 'remove_algo_note') {
      const shouldAdd = isUndo ? entry.action === 'remove_algo_note' : entry.action === 'add_algo_note';
      if (shouldAdd) {
        this.annotations.algo_notes.splice(entry.index, 0, { ...entry.data });
      } else {
        const tol = 1e-6;
        const idx = this.annotations.algo_notes.findIndex(
          n => Math.abs(n.zone_top - entry.data.zone_top) < tol && Math.abs(n.zone_bottom - entry.data.zone_bottom) < tol
        );
        if (idx >= 0) this.annotations.algo_notes.splice(idx, 1);
      }
      this.dirty = true;
      this._updateUI();
      return;
    }
    if (entry.action === 'update_algo_note') {
      const tol = 1e-6;
      const note = this.annotations.algo_notes.find(
        n => Math.abs(n.zone_top - entry.data.zone_top) < tol && Math.abs(n.zone_bottom - entry.data.zone_bottom) < tol
      );
      if (note) {
        note.note = isUndo ? entry.data.old_note : entry.data.new_note;
      }
      this.dirty = true;
      this._updateUI();
      return;
    }

    // isUndo: true → reverse the action, false → replay it
    const shouldAdd = isUndo ? entry.action === 'remove' : entry.action === 'add';

    if (shouldAdd) {
      // Re-add the annotation without pushing to undo stack
      if (entry.type === 'levels') {
        const l = entry.data;
        this.annotations.levels.splice(entry.index, 0, l);
        this.chart.addLevelZone(l.id, l.price_high, l.price_low, l.type, l.start_index);
      } else if (entry.type === 'trendlines') {
        const t = entry.data;
        this.annotations.trendlines.splice(entry.index, 0, t);
        this.chart.addTrendline(t.id, t.points[0].index, t.points[0].price, t.points[1].index, t.points[1].price, t.type);
      } else if (entry.type === 'pivots') {
        this.annotations.pivots.splice(entry.index, 0, entry.data);
        this._refreshPivotMarkers();
      }
    } else {
      // Remove the annotation without pushing to undo stack
      const list = this.annotations[entry.type];
      const idx = entry.type === 'pivots'
        ? list.findIndex(p => p.index === entry.data.index)
        : list.findIndex(a => a.id === entry.data.id);
      if (idx >= 0) {
        if (entry.type === 'levels') {
          this.chart.removeLevelZone(list[idx].id);
        } else if (entry.type === 'trendlines') {
          this.chart.removeTrendline(list[idx].id);
        }
        list.splice(idx, 1);
        if (entry.type === 'pivots') {
          this._refreshPivotMarkers();
        }
      }
    }

    this.dirty = true;
    this._updateUI();
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
          start_index: l.start_index,
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
        algo_notes: this.annotations.algo_notes.map(n => ({
          zone_top: n.zone_top,
          zone_bottom: n.zone_bottom,
          type: n.type,
          note: n.note,
        })),
      },
    };
  }

  /**
   * Clear all annotations and reset state.
   */
  clear() {
    this.chart.clearAllLevelZones();
    this.chart.clearAllTrendlines();
    this.chart.setPivotMarkers([]);
    this.annotations = { levels: [], trendlines: [], pivots: [], patterns: [], algo_notes: [] };
    this._labelCounters = { S: 0, R: 0 };
    this.dirty = false;
    this._hideForm();
    this._updateUI();
  }

  /**
   * Load annotations from a saved payload and redraw everything.
   */
  loadFromPayload(data) {
    this.clear();

    if (!data || !data.annotations) return;

    const ann = data.annotations;

    // Restore levels
    if (ann.levels) {
      for (const l of ann.levels) {
        this._addLevel(l.price_high, l.price_low, l.type, l.note || '', l.start_index || 0);
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

    // Restore algo notes
    if (ann.algo_notes) {
      this.annotations.algo_notes = ann.algo_notes.map(n => ({ ...n }));
    }

    this.dirty = false;
    this._updateUI();
  }
}
