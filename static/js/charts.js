/*
 * Odysseus chart renderer — TRUSTED client code only.
 *
 * The model emits a ```chart fence containing a small JSON spec; markdown.js
 * wraps it in <div class="chart-container"> carrying the raw spec in a child
 * <script type="application/json"> plus a visible <pre class="chart-fallback">.
 * This file validates the spec and renders it with the vendored Chart.js
 * (static/js/vendor/chart.umd.js). Model output is DATA, never code: the model
 * controls only type / title / labels / values — every Chart.js option is
 * built here.
 *
 * Spec format (normalized by validaSpec):
 *   { "type": "bar"|"line"|"pie",          // synonyms: column->bar, doughnut/donut->pie
 *     "title": "optional string",
 *     "labels": ["a", "b", ...],           // strings (numbers coerced), max 100
 *     "data": [1, 2, ...]                  // flat single series, OR:
 *     "series": [{ "name": "S1", "data": [1, 2, ...] }, ...] }  // max 10
 *
 * Any invalid spec degrades to a plain <pre><code> block showing the original
 * text, so the user always sees what the model wrote.
 */
(function () {
  'use strict';

  // Fixed categorical palette in fixed order (never re-assigned per render).
  // Tuned for the dark Odysseus surface (#282c34): cyan / orange / green /
  // amber / magenta / green / violet / red / blue / tan. Validated for the
  // OKLCH dark lightness band, >=3:1 contrast on #282c34 and adjacent-pair
  // color-vision-deficiency separation.
  var PALETTE = [
    '#0891b2', // cyan
    '#d95926', // orange
    '#199e70', // green (aqua)
    '#c98500', // amber
    '#d55181', // magenta
    '#0a9600', // green (deep)
    '#9085e9', // violet
    '#e66767', // red
    '#3987e5', // blue
    '#b0883b'  // tan
  ];

  var MAX_SERIES = 10;
  var MAX_POINTS = 100;

  var TYPE_MAP = {
    bar: 'bar', column: 'bar',
    line: 'line',
    pie: 'pie', doughnut: 'pie', donut: 'pie'
  };

  var TICK_COLOR = 'rgba(255,255,255,0.65)';
  var GRID_COLOR = 'rgba(255,255,255,0.07)';
  var AXIS_COLOR = 'rgba(255,255,255,0.15)';
  var TITLE_COLOR = 'rgba(255,255,255,0.87)';
  var SURFACE = '#282c34';

  function toNumber(v) {
    if (v === null || v === undefined) return null;
    var n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  /**
   * Validate + normalize a raw ```chart spec (JSON text).
   * Pure function, never throws. Returns
   *   { type, title, labels, series: [{ name, data }] }
   * or null when the spec is unusable (caller shows the fallback).
   */
  function validaSpec(raw) {
    try {
      if (typeof raw !== 'string' || !raw.trim()) return null;
      var spec = JSON.parse(raw);
      if (!spec || typeof spec !== 'object' || Array.isArray(spec)) return null;

      var type = TYPE_MAP[String(spec.type || '').trim().toLowerCase()];
      if (!type) return null;

      var title = null;
      if (typeof spec.title === 'string' && spec.title.trim()) title = spec.title;
      else if (typeof spec.title === 'number' && Number.isFinite(spec.title)) title = String(spec.title);

      if (!Array.isArray(spec.labels) || spec.labels.length === 0) return null;
      var labels = [];
      for (var i = 0; i < spec.labels.length && labels.length < MAX_POINTS; i++) {
        var lab = spec.labels[i];
        if (typeof lab === 'string') labels.push(lab);
        else if (typeof lab === 'number' && Number.isFinite(lab)) labels.push(String(lab));
        else return null;
      }

      var seriesIn;
      if (Array.isArray(spec.series)) seriesIn = spec.series;
      else if (Array.isArray(spec.data)) seriesIn = [{ name: title || 'Data', data: spec.data }];
      else return null;
      if (seriesIn.length === 0 || seriesIn.length > MAX_SERIES) return null;

      var series = [];
      for (var s = 0; s < seriesIn.length; s++) {
        var entry = seriesIn[s];
        if (!entry || typeof entry !== 'object' || Array.isArray(entry) || !Array.isArray(entry.data)) return null;
        var name = (typeof entry.name === 'string' && entry.name) ? entry.name : ('Serie ' + (s + 1));
        // Truncate/pad to labels.length; every value through Number(),
        // non-finite (and explicit null/undefined) -> null gap.
        var data = [];
        for (var j = 0; j < labels.length; j++) {
          data.push(j < entry.data.length ? toNumber(entry.data[j]) : null);
        }
        series.push({ name: name, data: data });
      }

      return { type: type, title: title, labels: labels, series: series };
    } catch (e) {
      return null;
    }
  }

  /** Full Chart.js config — every option owned by this trusted code. */
  function buildConfig(spec) {
    var isPie = spec.type === 'pie';
    var multi = spec.series.length > 1;

    var datasets;
    if (isPie) {
      datasets = spec.series.map(function (s) {
        return {
          label: s.name,
          data: s.data,
          backgroundColor: spec.labels.map(function (_, i) { return PALETTE[i % PALETTE.length]; }),
          borderColor: SURFACE,
          borderWidth: 2,
          hoverOffset: 6
        };
      });
    } else {
      datasets = spec.series.map(function (s, i) {
        var color = PALETTE[i % PALETTE.length];
        if (spec.type === 'line') {
          return {
            label: s.name,
            data: s.data,
            borderColor: color,
            backgroundColor: color,
            borderWidth: 2,
            pointRadius: 2.5,
            pointHoverRadius: 5,
            tension: 0.25
          };
        }
        return {
          label: s.name,
          data: s.data,
          backgroundColor: color,
          borderColor: color,
          borderWidth: 0,
          borderRadius: 4,
          maxBarThickness: 42
        };
      });
    }

    var options = {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        title: {
          display: !!spec.title,
          text: spec.title || '',
          color: TITLE_COLOR,
          font: { size: 14, weight: '600' },
          padding: { top: 4, bottom: 10 }
        },
        legend: {
          display: isPie || multi,
          position: 'bottom',
          labels: { color: TICK_COLOR, boxWidth: 12, boxHeight: 12, padding: 12 }
        }
      }
    };

    if (!isPie) {
      options.scales = {
        x: {
          grid: { color: GRID_COLOR },
          border: { color: AXIS_COLOR },
          ticks: { color: TICK_COLOR, maxRotation: 45, autoSkip: true }
        },
        y: {
          beginAtZero: spec.type === 'bar',
          grid: { color: GRID_COLOR },
          border: { display: false },
          ticks: { color: TICK_COLOR }
        }
      };
    }

    return { type: spec.type, data: { labels: spec.labels, datasets: datasets }, options: options };
  }

  /** Invalid spec: swap the container for a plain escaped code block. */
  function degrade(box, raw) {
    try {
      var fb = box.querySelector('.chart-fallback code') || box.querySelector('.chart-fallback');
      var original = fb ? fb.textContent : (raw || '');
      var pre = document.createElement('pre');
      var code = document.createElement('code');
      code.setAttribute('data-lang', 'chart');
      code.textContent = original; // textContent escapes on serialization
      pre.appendChild(code);
      if (box.parentNode) box.parentNode.replaceChild(pre, box);
    } catch (e) {
      /* leave the visible fallback as-is */
    }
  }

  function renderOne(box) {
    var raw = '';
    try {
      var scriptEl = box.querySelector('script[type="application/json"]');
      raw = scriptEl ? scriptEl.textContent : (box.getAttribute('data-spec') || '');
      var spec = validaSpec(raw);
      if (!spec) { degrade(box, raw); return; }

      var canvas = box.querySelector('canvas');
      if (!canvas) {
        canvas = document.createElement('canvas');
        box.appendChild(canvas);
      }
      // Re-render safety: kill any chart already bound to this canvas.
      if (typeof window.Chart.getChart === 'function') {
        var prev = window.Chart.getChart(canvas);
        if (prev) prev.destroy();
      }
      new window.Chart(canvas, buildConfig(spec));
      box.setAttribute('data-processed', '1');
    } catch (e) {
      if (window.console && console.warn) console.warn('OdysseusCharts render error:', e);
      degrade(box, raw);
    }
  }

  /**
   * Render all unprocessed ```chart containers inside `container`
   * (or the whole document). Idempotent via the data-processed guard;
   * never throws into the caller.
   */
  function renderCharts(container) {
    try {
      var target = container || document;
      if (!target || typeof target.querySelectorAll !== 'function') return;
      var pending = target.querySelectorAll('.chart-container:not([data-processed])');
      if (!pending.length) return;
      // Library not loaded: keep the visible fallback, retry on a later call.
      if (typeof window.Chart !== 'function') return;
      for (var i = 0; i < pending.length; i++) renderOne(pending[i]);
    } catch (e) {
      if (window.console && console.warn) console.warn('OdysseusCharts error:', e);
    }
  }

  window.OdysseusCharts = {
    renderCharts: renderCharts,
    validaSpec: validaSpec
  };
})();
