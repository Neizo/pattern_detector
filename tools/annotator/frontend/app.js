/**
 * App — main orchestrator.
 * Wires up the UI controls, chart, and annotation manager.
 */
(function () {
  'use strict';

  // ── State ───────────────────────────────────────────────────────────
  let chartManager = null;
  let annotationManager = null;
  let comparisonManager = null;
  let currentPair = null;
  let currentTimeframe = null;
  let autoSaveTimer = null;
  let algoData = null;        // cached /api/detections response

  // ── DOM refs ────────────────────────────────────────────────────────
  const selPair = document.getElementById('sel-pair');
  const selTf = document.getElementById('sel-tf');
  const inpLastN = document.getElementById('inp-lastn');
  const inpBefore = document.getElementById('inp-before');
  const btnLoad = document.getElementById('btn-load');
  const btnSave = document.getElementById('btn-save');
  const btnDisplayToggle = document.getElementById('btn-display-toggle');
  const btnCompare = document.getElementById('btn-compare');
  const btnHideHuman = document.getElementById('btn-hide-human');
  const btnToggleAlgo = document.getElementById('btn-toggle-algo');
  const modeBtns = document.querySelectorAll('.mode-btn');

  // ── Init ────────────────────────────────────────────────────────────

  async function init() {
    chartManager = new ChartManager('chart-container');
    annotationManager = new AnnotationManager(chartManager);
    comparisonManager = new ComparisonManager(chartManager);

    await loadPairs();
    bindControls();
    bindAlgoNoteDblClick();
    bindKeyboardShortcuts();
    startAutoSave();
  }

  async function loadPairs() {
    try {
      const resp = await fetch('/api/pairs');
      const data = await resp.json();

      selPair.innerHTML = '';
      for (const p of data.pairs) {
        const opt = document.createElement('option');
        opt.value = p.pair;
        opt.textContent = p.pair;
        selPair.appendChild(opt);
      }

      if (data.pairs.length > 0) {
        updateTimeframes(data.pairs[0].timeframes);
      }

      // Store pairs data for TF updates
      selPair._pairsData = data.pairs;

      selPair.addEventListener('change', () => {
        const pair = selPair.value;
        const pairData = selPair._pairsData.find(p => p.pair === pair);
        if (pairData) updateTimeframes(pairData.timeframes);
      });
    } catch (err) {
      console.error('Failed to load pairs:', err);
    }
  }

  function updateTimeframes(tfs) {
    selTf.innerHTML = '';
    for (const tf of tfs) {
      const opt = document.createElement('option');
      opt.value = tf;
      opt.textContent = tf;
      selTf.appendChild(opt);
    }
    // Default to H4 if available
    if (tfs.includes('H4')) selTf.value = 'H4';
  }

  function bindControls() {
    btnLoad.addEventListener('click', loadChart);

    btnSave.addEventListener('click', saveAnnotations);

    modeBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        modeBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        annotationManager.setMode(btn.dataset.mode);
      });
    });

    // Display mode toggle: candles ↔ line
    btnDisplayToggle.addEventListener('click', () => {
      if (chartManager.displayMode === 'candles') {
        chartManager.setDisplayMode('line');
        btnDisplayToggle.textContent = 'Chandeliers';
        btnDisplayToggle.classList.add('active');
      } else {
        chartManager.setDisplayMode('candles');
        btnDisplayToggle.textContent = 'Courbe';
        btnDisplayToggle.classList.remove('active');
      }
    });

    // Hide/show human annotations
    btnHideHuman.addEventListener('click', () => {
      const visible = !chartManager._annotationsVisible;
      // Update button state first (even if chart method throws)
      btnHideHuman.textContent = visible ? 'Masquer humain' : 'Afficher humain';
      btnHideHuman.classList.toggle('active', !visible);
      try {
        chartManager.setAnnotationsVisible(visible);
      } catch (err) {
        console.error('setAnnotationsVisible failed:', err);
      }
    });

    // Toggle algo detections
    btnToggleAlgo.addEventListener('click', async () => {
      if (!currentPair || !currentTimeframe) {
        alert('Chargez un graphique d\'abord.');
        return;
      }

      // If visible → hide
      if (chartManager._algoVisible) {
        chartManager.setAlgoVisible(false);
        btnToggleAlgo.textContent = 'Algo';
        btnToggleAlgo.classList.remove('active');
        return;
      }

      // If already loaded → just show
      if (algoData) {
        chartManager.setAlgoVisible(true);
        btnToggleAlgo.textContent = 'Masquer algo';
        btnToggleAlgo.classList.add('active');
        return;
      }

      // First time → fetch and draw
      btnToggleAlgo.disabled = true;
      btnToggleAlgo.textContent = 'Chargement...';
      try {
        const lastN = parseInt(inpLastN.value, 10) || 500;
        const before = inpBefore.value || null;
        const params = new URLSearchParams({ pair: currentPair, timeframe: currentTimeframe, last_n: lastN });
        if (before) params.set('before', before);

        const resp = await fetch(`/api/detections?${params}`);
        if (!resp.ok) throw new Error(`API error: ${resp.status}`);
        algoData = await resp.json();

        drawAlgoDetections(algoData);
        applyAlgoNoteHighlights();
        chartManager._algoVisible = true;
        btnToggleAlgo.textContent = 'Masquer algo';
        btnToggleAlgo.classList.add('active');
      } catch (err) {
        console.error('Algo detections failed:', err);
        alert(`Erreur détections algo: ${err.message}`);
      } finally {
        btnToggleAlgo.disabled = false;
      }
    });

    // Compare button
    btnCompare.addEventListener('click', async () => {
      if (!currentPair || !currentTimeframe) {
        alert('Chargez un graphique d\'abord.');
        return;
      }

      if (comparisonManager.active) {
        comparisonManager.clear();
        btnCompare.classList.remove('active');
        return;
      }

      btnCompare.disabled = true;
      btnCompare.textContent = 'Comparaison...';
      try {
        const lastN = parseInt(inpLastN.value, 10) || 500;
        const before = inpBefore.value || null;
        await comparisonManager.compare(currentPair, currentTimeframe, lastN, before);
        btnCompare.classList.add('active');
      } catch (err) {
        console.error('Comparison failed:', err);
        alert(`Erreur comparaison: ${err.message}`);
      } finally {
        btnCompare.disabled = false;
        btnCompare.textContent = 'Comparer';
      }
    });
  }

  // ── Chart loading ───────────────────────────────────────────────────

  async function loadChart() {
    const pair = selPair.value;
    const tf = selTf.value;
    const lastN = parseInt(inpLastN.value, 10) || 500;
    const before = inpBefore.value || null;

    if (!pair || !tf) return;

    btnLoad.disabled = true;
    btnLoad.textContent = 'Chargement...';

    try {
      // Clear comparison if active
      if (comparisonManager.active) {
        comparisonManager.clear();
        btnCompare.classList.remove('active');
      }

      // Clear algo overlays
      chartManager.clearAlgo();
      algoData = null;
      btnToggleAlgo.textContent = 'Algo';
      btnToggleAlgo.classList.remove('active');

      await chartManager.loadCandles(pair, tf, lastN, before);
      currentPair = pair;
      currentTimeframe = tf;

      // Try to load existing annotations
      await loadExistingAnnotations(pair, tf);

      btnSave.disabled = false;
    } catch (err) {
      console.error('Failed to load chart:', err);
      alert(`Erreur de chargement: ${err.message}`);
    } finally {
      btnLoad.disabled = false;
      btnLoad.textContent = 'Charger';
    }
  }

  // ── Annotations persistence ─────────────────────────────────────────

  async function loadExistingAnnotations(pair, tf) {
    // Clear previous annotations before loading new pair/timeframe
    annotationManager.clear();

    try {
      const resp = await fetch(`/api/annotations?pair=${pair}&timeframe=${tf}`);
      const data = await resp.json();
      if (data && data.annotations) {
        annotationManager.loadFromPayload(data);
      }
    } catch (err) {
      console.warn('No existing annotations:', err);
    }
  }

  async function saveAnnotations() {
    if (!currentPair || !currentTimeframe) return;

    const lastN = parseInt(inpLastN.value, 10) || 500;
    const before = inpBefore.value || null;
    const payload = annotationManager.toPayload(currentPair, currentTimeframe, lastN, before);

    try {
      const resp = await fetch('/api/annotations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (resp.ok) {
        annotationManager.dirty = false;
        annotationManager._updateSaveStatus();
      }
    } catch (err) {
      console.error('Save failed:', err);
    }
  }

  // ── Algo detections drawing ─────────────────────────────────────────

  function drawAlgoDetections(data) {
    // Draw level zones
    const levels = data.levels || [];
    for (let i = 0; i < levels.length; i++) {
      const lv = levels[i];
      const isSupport = lv.type === 'support';
      const color = isSupport
        ? 'rgba(38, 166, 154, 0.4)'
        : 'rgba(239, 83, 80, 0.4)';
      const label = isSupport ? 'S' : 'R';
      const id = `algo_${label}${i}`;
      chartManager.addAlgoZone(id, lv.zone_top, lv.zone_bottom, color, lv.start_index);
    }

    // Draw pivot markers
    const pivots = data.pivots || [];
    const markers = pivots.map(p => ({
      index: p.index,
      type: p.type,
      color: '#888888',
    }));
    chartManager.setAlgoPivotMarkers(markers);
  }

  // ── Algo note on double-click ───────────────────────────────────────

  function bindAlgoNoteDblClick() {
    const chartEl = chartManager.getChartElement();
    chartEl.addEventListener('dblclick', (e) => {
      if (!chartManager._algoVisible) return;

      const rect = chartEl.getBoundingClientRect();
      const y = e.clientY - rect.top;
      const price = chartManager.yToPrice(y);
      if (price == null) return;

      const zone = chartManager.getAlgoZoneAtPrice(price);
      if (!zone) return;

      e.preventDefault();
      e.stopPropagation();
      showAlgoNoteForm(zone);
    });
  }

  function showAlgoNoteForm(zone) {
    const formEl = document.getElementById('annotation-form');
    formEl.classList.remove('hidden');

    const prec = chartManager.pricePrecision;
    const isSupport = zone.id.startsWith('algo_S');
    const typeLabel = isSupport ? 'Support' : 'Resistance';

    // Check for existing note
    const existing = annotationManager.getAlgoNote(zone.priceHigh, zone.priceLow);
    const existingNote = existing ? existing.note : '';

    formEl.innerHTML = `
      <div class="form-row">
        <label>Algo ${typeLabel}</label>
        <span style="color: var(--text-primary); font-size: 12px;">
          ${zone.priceLow.toFixed(prec)} — ${zone.priceHigh.toFixed(prec)}
        </span>
      </div>
      <div class="form-row">
        <label>Note</label>
        <textarea id="algo-note-text" rows="3" placeholder="Note libre sur ce niveau algo..." style="width: 100%; resize: vertical; background: var(--bg-secondary); color: var(--text-primary); border: 1px solid var(--border); border-radius: 4px; padding: 6px; font-size: 12px;">${existingNote}</textarea>
      </div>
      <div class="form-actions">
        <button class="btn-validate" id="btn-algo-note-ok">Valider</button>
        <button class="btn-delete" id="btn-algo-note-cancel">Annuler</button>
        ${existing ? '<button class="btn-delete" id="btn-algo-note-delete" style="margin-left: auto;">Supprimer</button>' : ''}
      </div>
    `;

    const type = isSupport ? 'support' : 'resistance';

    const validate = () => {
      const note = document.getElementById('algo-note-text').value.trim();
      if (note) {
        annotationManager.addAlgoNote(zone.priceHigh, zone.priceLow, type, note);
        chartManager.highlightAlgoZone(zone.id, true);
      }
      formEl.classList.add('hidden');
    };

    const cancel = () => {
      formEl.classList.add('hidden');
    };

    const deleteNote = () => {
      annotationManager.removeAlgoNote(zone.priceHigh, zone.priceLow);
      chartManager.highlightAlgoZone(zone.id, false);
      formEl.classList.add('hidden');
    };

    document.getElementById('btn-algo-note-ok').addEventListener('click', validate);
    document.getElementById('btn-algo-note-cancel').addEventListener('click', cancel);
    if (existing) {
      document.getElementById('btn-algo-note-delete').addEventListener('click', deleteNote);
    }

    // Keyboard: Enter to validate, Escape to cancel
    const keyHandler = (e) => {
      if (e.key === 'Escape') { cancel(); document.removeEventListener('keydown', keyHandler); }
      if (e.key === 'Enter' && e.ctrlKey) { validate(); document.removeEventListener('keydown', keyHandler); }
    };
    document.addEventListener('keydown', keyHandler);

    setTimeout(() => document.getElementById('algo-note-text')?.focus(), 50);
  }

  /**
   * After algo detections are drawn, highlight zones that already have notes.
   */
  function applyAlgoNoteHighlights() {
    for (const note of annotationManager.annotations.algo_notes) {
      // Find matching algo zone by price
      const zone = chartManager.getAlgoZoneAtPrice((note.zone_top + note.zone_bottom) / 2);
      if (zone && Math.abs(zone.priceHigh - note.zone_top) < 1e-6 && Math.abs(zone.priceLow - note.zone_bottom) < 1e-6) {
        chartManager.highlightAlgoZone(zone.id, true);
      }
    }
  }

  // ── Keyboard shortcuts ──────────────────────────────────────────────

  function bindKeyboardShortcuts() {
    const modeKeys = { '1': 'levels', '2': 'trendlines', '3': 'pivots', '4': 'patterns' };

    document.addEventListener('keydown', (e) => {
      const tag = (e.target.tagName || '').toLowerCase();
      const inInput = tag === 'input' || tag === 'select' || tag === 'textarea';

      // Ctrl+S — save (always active)
      if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        saveAnnotations();
        return;
      }

      // Ctrl+Z — undo
      if (e.ctrlKey && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        annotationManager.undo();
        return;
      }

      // Ctrl+Y or Ctrl+Shift+Z — redo
      if ((e.ctrlKey && e.key === 'y') || (e.ctrlKey && e.shiftKey && e.key === 'Z')) {
        e.preventDefault();
        annotationManager.redo();
        return;
      }

      // Escape — cancel pending operation
      if (e.key === 'Escape' && !inInput) {
        annotationManager._cancelPending();
        annotationManager._hideForm();
        return;
      }

      // Skip remaining shortcuts if focused on an input
      if (inInput) return;

      // Mode switching: 1-4
      if (modeKeys[e.key]) {
        const mode = modeKeys[e.key];
        modeBtns.forEach(b => {
          b.classList.toggle('active', b.dataset.mode === mode);
        });
        annotationManager.setMode(mode);
        return;
      }

      // Arrow keys — scroll chart
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        chartManager.scrollBy(-10);
        return;
      }
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        chartManager.scrollBy(10);
        return;
      }

      // +/- — zoom
      if (e.key === '+' || e.key === '=') {
        e.preventDefault();
        chartManager.zoomIn();
        return;
      }
      if (e.key === '-') {
        e.preventDefault();
        chartManager.zoomOut();
        return;
      }
    });
  }

  function startAutoSave() {
    autoSaveTimer = setInterval(() => {
      if (annotationManager && annotationManager.dirty && currentPair) {
        saveAnnotations();
      }
    }, 30000);
  }

  // ── Boot ────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', init);
})();
