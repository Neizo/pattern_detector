/**
 * App — main orchestrator.
 * Wires up the UI controls, chart, and annotation manager.
 */
(function () {
  'use strict';

  // ── State ───────────────────────────────────────────────────────────
  let chartManager = null;
  let annotationManager = null;
  let currentPair = null;
  let currentTimeframe = null;
  let autoSaveTimer = null;

  // ── DOM refs ────────────────────────────────────────────────────────
  const selPair = document.getElementById('sel-pair');
  const selTf = document.getElementById('sel-tf');
  const inpLastN = document.getElementById('inp-lastn');
  const inpBefore = document.getElementById('inp-before');
  const btnLoad = document.getElementById('btn-load');
  const btnSave = document.getElementById('btn-save');
  const btnDisplayToggle = document.getElementById('btn-display-toggle');
  const modeBtns = document.querySelectorAll('.mode-btn');

  // ── Init ────────────────────────────────────────────────────────────

  async function init() {
    chartManager = new ChartManager('chart-container');
    annotationManager = new AnnotationManager(chartManager);

    await loadPairs();
    bindControls();
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
