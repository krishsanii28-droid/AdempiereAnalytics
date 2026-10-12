/* Demand forecast and stockout risk panel. Uses helpers that app.js publishes on window.InsightAI. */
window.InsightAIForecast = (function () {
  'use strict';

  const ui = () => window.InsightAI;
  const $ = (id) => document.getElementById(id);
  const state = { mode: 'real', data: null, selected: null, requestId: 0, polling: null };

  const LEVELS = {
    high: ['▲ High', 'level-high'],
    medium: ['● Medium', 'level-medium'],
    low: ['Low', 'level-low'],
    none: ['No demand forecast', 'level-none'],
    unknown: ['Not forecast', 'level-none'],
  };
  const METHODS = { chronos: 'Chronos', moving_average: 'Moving average', seasonal_naive: 'Seasonal naive', naive: 'Naive' };
  const qty = (v) => (v === null || v === undefined ? '' : ui().number(Math.round(v * 10) / 10));
  const shortDate = (iso) => new Date(iso + 'T00:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });

  function setMode(mode) {
    state.mode = mode;
    state.selected = null;
    for (const button of document.querySelectorAll('#fc-modes button')) {
      button.setAttribute('aria-pressed', String(button.dataset.mode === mode));
    }
    refresh();
  }

  async function refresh() {
    const { api, filterParams } = ui();
    const requestId = ++state.requestId;
    $('fc-body').classList.add('is-loading');
    try {
      const data = await api('/api/forecast?mode=' + state.mode + '&' + filterParams());
      if (requestId !== state.requestId) return;
      state.data = data;
      render();
    } catch (e) {
      if (requestId !== state.requestId) return;
      state.data = null;
      message(e.message, true);
    } finally {
      if (requestId === state.requestId) $('fc-body').classList.remove('is-loading');
    }
  }

  function message(text, retry) {
    const { el } = ui();
    $('fc-banner').hidden = true;
    $('fc-status').textContent = '';
    $('fc-evaluation').replaceChildren();
    $('fc-detail').replaceChildren();
    $('fc-assumptions').hidden = true;
    const box = el('div', 'state', text);
    if (retry) {
      const button = el('button', 'ghost', 'Try again');
      button.type = 'button';
      button.addEventListener('click', refresh);
      box.append(document.createElement('br'), button);
    }
    $('fc-table').replaceChildren(box);
  }

  function render() {
    const { el } = ui();
    const d = state.data;
    if (!d.available) { message(d.reason, false); return; }

    // Synthetic results are labelled before anything else is shown
    $('fc-banner').hidden = !d.synthetic;

    const usedModel = d.model.used === 'chronos' ? 'Chronos model ' + d.model.requested : 'Statistical baseline (no model)';
    $('fc-status').textContent = usedModel + ' · weekly demand · forecast for ' + shortDate(d.forecast_start_week) + ' to ' +
      shortDate(d.forecast_end) + ' · run ' + d.generated_at.replace('T', ' ');
    const notes = $('fc-notes');
    notes.replaceChildren();
    if (d.model.fallback_reason) notes.append(el('li', null, 'Model unavailable, baseline used instead: ' + d.model.fallback_reason));
    if (d.ignored.length) notes.append(el('li', null, 'Not filtered by ' + d.ignored.join(' or ') + '. The date range does not apply.'));
    const c = d.counts;
    if (c.forecast < c.series) {
      notes.append(el('li', null, (c.series - c.forecast) + ' of ' + c.series + ' product and warehouse combinations are not forecast: ' +
        'too little shipment history (' + d.min_history_weeks + ' weeks are needed).'));
    }

    renderEvaluation(d);
    renderTable(d);
    const list = $('fc-assumption-list');
    list.replaceChildren();
    for (const item of d.assumptions) list.append(el('li', null, item));
    $('fc-assumptions').hidden = false;

    const stillThere = state.selected && d.rows.find((r) => r.product_id === state.selected.product_id && r.warehouse_id === state.selected.warehouse_id);
    const first = stillThere || d.rows.find((r) => r.status === 'forecast');
    if (first) select(first); else $('fc-detail').replaceChildren();
  }

  function renderEvaluation(d) {
    const { el } = ui();
    const host = $('fc-evaluation');
    host.replaceChildren();
    const ev = d.evaluation;
    host.append(el('h3', null, 'Measured accuracy'));
    if (!ev.baselines || !Object.keys(ev.baselines).length) {
      host.append(el('p', 'basis', 'Accuracy has not been measured, so no accuracy is claimed. ' + ev.reason + '.'));
      return;
    }
    host.append(el('p', 'basis', ev.windows_evaluated + ' hold-out windows of ' + ev.holdout_weeks + ' weeks across ' + ev.series_evaluated +
      ' series' + (d.synthetic ? ' of synthetic demand' : '') + '. Lower is better; MASE below 1 beats repeating last week’s value.'));
    const table = el('table');
    const head = el('tr');
    for (const [label, cls] of [['Method', null], ['MAE (units per week)', 'num'], ['MASE', 'num'], ['Notes', null]]) head.append(el('th', cls, label));
    const thead = el('thead'); thead.append(head);
    const tbody = el('tbody');
    const fixed = (v) => (v === null ? 'n/a' : v.toFixed(3));
    if (ev.model) {
      const tr = el('tr');
      tr.append(el('td', null, ev.model.name), el('td', 'num', fixed(ev.model.mae)), el('td', 'num', fixed(ev.model.mase)),
        el('td', null, 'Beat the strongest baseline in ' + ev.model.better_than_strongest_on + ' of ' + ev.windows_evaluated + ' windows. Its ' +
          ev.model.interval + ' range held ' + Math.round(ev.model.interval_coverage * 100) + '% of actual values (' +
          Math.round(ev.model.interval_nominal * 100) + '% expected).'));
      tbody.append(tr);
    }
    for (const [name, b] of Object.entries(ev.baselines)) {
      const tr = el('tr');
      tr.append(el('td', null, METHODS[name] + ' (baseline)'), el('td', 'num', fixed(b.mae)), el('td', 'num', fixed(b.mase)),
        el('td', null, name === ev.strongest_baseline ? 'Strongest baseline' : ''));
      tbody.append(tr);
    }
    table.append(thead, tbody);
    const wrap = el('div', 'table-wrap'); wrap.append(table);
    host.append(wrap);
    if (ev.note) host.append(el('p', 'basis', ev.note + '.'));
  }

  function renderTable(d) {
    const { el } = ui();
    const host = $('fc-table');
    if (!d.rows.length) { host.replaceChildren(el('div', 'state', 'No stock or demand for this selection.')); return; }
    const table = el('table', 'selectable');
    const head = el('tr');
    const columns = [['Product', null], ['Warehouse', null], ['Stockout risk', null], ['Available', 'num'], ['Incoming', 'num'],
      ['Forecast demand, ' + d.horizon_weeks + ' weeks', 'num'], ['Likely range', 'num'], ['Runs out', null], ['Weeks of cover', 'num'], ['Flags', null]];
    for (const [label, cls] of columns) head.append(el('th', cls, label));
    const thead = el('thead'); thead.append(head);
    const tbody = el('tbody');
    for (const r of d.rows) {
      const tr = el('tr');
      const forecast = r.status === 'forecast';
      const [label, cls] = LEVELS[r.level];
      const risk = el('td');
      risk.append(el('span', 'level ' + cls, label));
      if (r.probability_text) risk.append(' ' + r.probability_text);
      risk.title = r.reason;
      const flags = [];
      if (r.excess) flags.push('Excess stock');
      if (r.outlier_weeks) flags.push(r.outlier_weeks + ' outlier week' + (r.outlier_weeks > 1 ? 's' : ''));
      if (r.incoming_stale) flags.push(qty(r.incoming_stale) + ' on overdue purchase orders, not counted');
      if (r.available < 0) flags.push('Available stock is negative');
      if (!forecast) flags.push(r.reason);
      tr.append(
        el('td', null, r.product), el('td', null, r.warehouse), risk,
        el('td', 'num', qty(r.available)), el('td', 'num', qty(r.incoming)),
        el('td', 'num', forecast ? qty(r.demand_median) : ''),
        el('td', 'num', forecast ? qty(r.demand_low) + ' – ' + qty(r.demand_high) : ''),
        el('td', null, r.stockout_week ? 'Week ' + r.stockout_week : ''),
        el('td', 'num', r.weeks_of_cover === null || r.weeks_of_cover === undefined ? '' : (r.weeks_of_cover > 104 ? 'Over 104' : qty(r.weeks_of_cover))),
        el('td', 'flags', flags.join('; ')));
      if (forecast) {
        tr.tabIndex = 0;
        tr.dataset.key = r.product_id + ':' + r.warehouse_id;
        tr.addEventListener('click', () => select(r));
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(r); } });
      } else {
        tr.classList.add('muted');
      }
      tbody.append(tr);
    }
    table.append(thead, tbody);
    const wrap = el('div', 'table-wrap'); wrap.append(table);
    host.replaceChildren(wrap);
  }

  async function select(row) {
    const { api, el } = ui();
    state.selected = row;
    for (const tr of document.querySelectorAll('#fc-table tr[data-key]')) {
      tr.classList.toggle('selected', tr.dataset.key === row.product_id + ':' + row.warehouse_id);
    }
    const host = $('fc-detail');
    let s;
    try {
      s = await api('/api/forecast/series?mode=' + state.mode + '&product_id=' + row.product_id + '&warehouse_id=' + row.warehouse_id);
    } catch (e) {
      host.replaceChildren(el('div', 'state', e.message));
      return;
    }
    if (state.selected !== row) return;
    const title = el('h3', null, row.product + ' · ' + row.warehouse + (s.synthetic ? ' · SYNTHETIC DEMAND' : ''));
    const basis = el('p', 'basis', 'Weekly demand in units, last 52 weeks (double-click the chart for the full history). Forecast by ' + (METHODS[s.method] || s.method) + '. ' + row.reason + '.');
    const plot = el('div', 'fc-plot');
    host.replaceChildren(title, basis, plot);
    if (!window.Plotly) { plot.append(el('div', 'state', 'The chart library did not load. The figures are in the table above.')); return; }
    drawSeries(plot, s);
  }

  function drawSeries(plot, s) {
    const { css } = ui();
    const color = css('--series-sales');
    const low = String(s.quantiles[0]), high = String(s.quantiles[s.quantiles.length - 1]);
    const lowPct = Math.round(s.quantiles[0] * 100), highPct = Math.round(s.quantiles[s.quantiles.length - 1] * 100);
    // Join the forecast to the last observed point so the lines meet
    const lastWeek = s.weeks[s.weeks.length - 1], lastValue = s.history[s.history.length - 1];
    const fx = [lastWeek].concat(s.forecast_weeks);
    const band = { r: parseInt(color.slice(1, 3), 16), g: parseInt(color.slice(3, 5), 16), b: parseInt(color.slice(5, 7), 16) };
    const traces = [
      { name: lowPct + 'th percentile', x: fx, y: [lastValue].concat(s.forecast[low]), mode: 'lines', line: { width: 0 },
        hovertemplate: '%{y:.1f}<extra>' + lowPct + 'th percentile</extra>', showlegend: false },
      { name: lowPct + 'th to ' + highPct + 'th percentile', x: fx, y: [lastValue].concat(s.forecast[high]), mode: 'lines', line: { width: 0 },
        fill: 'tonexty', fillcolor: 'rgba(' + band.r + ',' + band.g + ',' + band.b + ',0.16)',
        hovertemplate: '%{y:.1f}<extra>' + highPct + 'th percentile</extra>' },
      { name: 'History', x: s.weeks, y: s.history, mode: 'lines', line: { color, width: 2 },
        hovertemplate: '%{y:.0f}<extra>Shipped</extra>' },
      { name: 'Forecast (median)', x: fx, y: [lastValue].concat(s.forecast['0.5']), mode: 'lines+markers',
        line: { color, width: 2, dash: 'dash' }, marker: { size: 8, color, line: { color: css('--surface'), width: 2 } },
        hovertemplate: '%{y:.1f}<extra>Forecast median</extra>' },
    ];
    if (s.outlier_weeks.length) {
      traces.push({ name: 'Outlier week', x: s.outlier_weeks.map((i) => s.weeks[i]), y: s.outlier_weeks.map((i) => s.history[i]),
        mode: 'markers', marker: { size: 10, symbol: 'diamond-open', color: css('--text'), line: { width: 2 } },
        hovertemplate: '%{y:.0f}<extra>Flagged as an outlier</extra>' });
    }
    const axis = { gridcolor: css('--grid'), linecolor: css('--axis'), zerolinecolor: css('--axis'),
                   tickfont: { color: css('--text-muted'), size: 11 } };
    Plotly.react(plot, traces, {
      height: 320, margin: { l: 48, r: 16, t: 8, b: 36 },
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'system-ui, -apple-system, "Segoe UI", sans-serif', size: 12, color: css('--text-secondary') },
      // open on the last year so the forecast is readable; double-click the chart to see the full history
      xaxis: Object.assign({}, axis, { type: 'date', showgrid: false,
                                       range: [s.weeks[Math.max(0, s.weeks.length - 52)], s.forecast_weeks[s.forecast_weeks.length - 1]] }),
      yaxis: Object.assign({}, axis, { rangemode: 'tozero', showline: false }),
      hovermode: 'x unified', hoverlabel: { bgcolor: css('--surface'), bordercolor: css('--axis'), font: { color: css('--text'), size: 12 } },
      legend: { orientation: 'h', y: 1.12, x: 0, font: { size: 12 } },
    }, { displayModeBar: false, responsive: true });
  }

  async function runNow() {
    const { api } = ui();
    const button = $('fc-run');
    button.disabled = true;
    button.textContent = 'Running…';
    try {
      await fetch('/api/forecast/run', { method: 'POST', credentials: 'same-origin' });
      clearInterval(state.polling);
      state.polling = setInterval(async () => {
        let status;
        try { status = await api('/api/forecast/status'); } catch (e) { return; }
        if (status.running) return;
        clearInterval(state.polling);
        button.disabled = false;
        button.textContent = 'Run forecast';
        if (status.error) message(status.error, true); else { refresh(); ui().refreshKpis(); }
      }, 2000);
    } catch (e) {
      button.disabled = false;
      button.textContent = 'Run forecast';
      message('The InsightAI service is not responding.', true);
    }
  }

  function init() {
    for (const button of document.querySelectorAll('#fc-modes button')) button.addEventListener('click', () => setMode(button.dataset.mode));
    $('fc-run').addEventListener('click', runNow);
    // ?forecast=synthetic opens the page on the synthetic demo
    if (new URLSearchParams(location.search).get('forecast') === 'synthetic') {
      state.mode = 'synthetic';
      for (const button of document.querySelectorAll('#fc-modes button')) button.setAttribute('aria-pressed', String(button.dataset.mode === 'synthetic'));
    }
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (state.selected) select(state.selected); });
  }

  return { init, refresh };
})();
