/* InsightAI dashboard. All data strings are written with textContent, never innerHTML. */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  };

  const state = { me: null, requestId: 0 };

  // ---- formatting -------------------------------------------------------------------
  let currency = 'USD';
  const money = (v) => new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 2 }).format(v);
  const moneyCompact = (v) => new Intl.NumberFormat(undefined, {
    style: 'currency', currency, notation: Math.abs(v) >= 10000 ? 'compact' : 'standard', maximumFractionDigits: Math.abs(v) >= 10000 ? 1 : 0,
  }).format(v);
  const number = (v) => new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(v);
  const percent = (v) => new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 1 }).format(v);
  const monthLabel = (ym) => new Date(ym + '-01T00:00:00').toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
  const FORMATS = {
    money: (v) => (v === null ? 'No cost' : money(v)),
    number: (v) => (v === null ? '' : number(v)),
    percent: (v) => (v === null ? 'Not rated' : percent(v)),
    days: (v) => (v === null ? '' : number(v)),
    date: (v) => v || 'Never',
    month: monthLabel,
    text: (v) => (v === null ? '' : String(v).trim()),
  };

  // ---- chart catalogue --------------------------------------------------------------
  // kind: columns (time or ordered categories), bars (ranking), table (a list is the right form)
  const CHARTS = [
    { id: 'sales_monthly', title: 'Monthly sales', kind: 'columns', series: 'sales', x: 'month', xFormat: 'month', y: 'amount',
      columns: [['month', 'Month', 'month'], ['amount', 'Sales', 'money'], ['documents', 'Invoices', 'number']] },
    { id: 'purchases_monthly', title: 'Monthly purchases', kind: 'columns', series: 'purchases', x: 'month', xFormat: 'month', y: 'amount',
      columns: [['month', 'Month', 'month'], ['amount', 'Purchases', 'money'], ['documents', 'Invoices', 'number']] },
    { id: 'sales_by_product', title: 'Top products by sales', kind: 'bars', series: 'sales', x: 'label', y: 'amount',
      columns: [['label', 'Product', 'text'], ['amount', 'Sales', 'money'], ['quantity', 'Quantity', 'number']] },
    { id: 'sales_by_category', title: 'Sales by product category', kind: 'bars', series: 'sales', x: 'label', y: 'amount',
      columns: [['label', 'Category', 'text'], ['amount', 'Sales', 'money'], ['quantity', 'Quantity', 'number']] },
    { id: 'sales_by_customer', title: 'Top customers by sales', kind: 'bars', series: 'sales', x: 'label', y: 'amount',
      columns: [['label', 'Customer', 'text'], ['amount', 'Sales', 'money'], ['quantity', 'Quantity', 'number']] },
    { id: 'receivables_aging', title: 'Receivables aging', kind: 'columns', series: 'sales', x: 'bucket', y: 'amount', xTitle: 'Days past due',
      columns: [['bucket', 'Days past due', 'text'], ['amount', 'Open amount', 'money'], ['items', 'Invoices', 'number']] },
    { id: 'inventory_by_warehouse', title: 'Inventory value by warehouse', kind: 'bars', series: 'inventory', x: 'label', y: 'value',
      columns: [['label', 'Warehouse', 'text'], ['value', 'Value', 'money'], ['quantity', 'Quantity', 'number'], ['products', 'Products', 'number'], ['uncosted', 'Without cost', 'number']] },
    { id: 'inventory_by_category', title: 'Inventory value by product category', kind: 'bars', series: 'inventory', x: 'label', y: 'value',
      columns: [['label', 'Category', 'text'], ['value', 'Value', 'money'], ['quantity', 'Quantity', 'number'], ['products', 'Products', 'number'], ['uncosted', 'Without cost', 'number']] },
    { id: 'receivables_open', title: 'Open customer invoices', kind: 'table', wide: true,
      columns: [['invoice', 'Invoice', 'text'], ['customer', 'Customer', 'text'], ['date_invoiced', 'Invoiced', 'date'], ['due_date', 'Due', 'date'],
                ['days_due', 'Days past due', 'days'], ['bucket', 'Bucket', 'text'], ['open_amount', 'Open amount', 'money']] },
    { id: 'slow_moving', title: 'Slow-moving stock', kind: 'table', wide: true,
      columns: [['product', 'Product', 'text'], ['warehouse', 'Warehouse', 'text'], ['quantity', 'On hand', 'number'], ['value', 'Value', 'money'],
                ['last_outbound', 'Last outbound movement', 'date'], ['days_since', 'Days since', 'days']] },
    { id: 'supplier_performance', title: 'Supplier delivery performance', kind: 'table', wide: true,
      columns: [['supplier', 'Supplier', 'text'], ['receipt_lines', 'Receipt lines', 'number'], ['matched_lines', 'Linked to an order', 'number'],
                ['on_time_rate', 'On time', 'percent'], ['avg_days_late', 'Average days late', 'days'], ['max_days_late', 'Worst days late', 'days']] },
  ];
  const cards = {};   // chart id -> { def, body, basis, notes, toggle, view, data }

  // ---- data access ------------------------------------------------------------------
  function filterParams() {
    const p = new URLSearchParams();
    const add = (key, value) => { if (value) p.set(key, value); };
    add('date_from', $('f-from').value);
    add('date_to', $('f-to').value);
    add('org_id', $('f-org').value);
    add('warehouse_id', $('f-warehouse').value);
    add('category_id', $('f-category').value);
    add('bpartner_id', $('f-bpartner').value);
    return p.toString();
  }

  async function api(path) {
    let response;
    try {
      response = await fetch(path, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    } catch (e) {
      throw new Error('The InsightAI service is not responding.');
    }
    if (response.status === 401) {
      showPageMessage('Your InsightAI session has ended. Open InsightAI again from the ADempiere menu.');
      throw new Error('Not signed in.');
    }
    let payload = null;
    try { payload = await response.json(); } catch (e) { /* non-JSON error body */ }
    if (!response.ok) {
      const detail = payload && payload.detail;
      throw new Error(typeof detail === 'string' ? detail : 'InsightAI could not load this (HTTP ' + response.status + ').');
    }
    return payload;
  }

  function showPageMessage(text) {
    const box = $('page-message');
    box.textContent = text;
    box.hidden = !text;
  }

  // ---- KPI cards --------------------------------------------------------------------
  function formatKpi(card) {
    if (card.unit === 'currency') return moneyCompact(card.value);
    if (card.unit === 'percent') return percent(card.value);
    if (card.unit === 'ratio') return number(card.value) + '×';
    return number(card.value);
  }

  function renderKpis(payload) {
    const host = $('kpis');
    host.replaceChildren();
    for (const card of payload.cards) {
      const node = el('article', 'kpi' + (card.available ? '' : ' unavailable'));
      node.append(el('div', 'label', card.label));
      if (!card.available) {
        node.append(el('div', 'value', 'Data unavailable'));
        node.append(el('div', 'detail', card.reason));
      } else {
        const value = el('div', 'value', formatKpi(card));
        if (card.unit === 'currency') value.title = money(card.value);
        node.append(value);
        if (card.delta !== null) {
          const delta = el('div', 'delta');
          const up = card.delta >= 0;
          delta.append(el('span', up ? 'up' : 'down', (up ? '▲ +' : '▼ ') + percent(card.delta)));
          delta.append(' ' + card.delta_label);
          node.append(delta);
        }
        if (card.detail) node.append(el('div', 'detail', card.detail));
      }
      for (const note of card.notes) node.append(el('div', 'note', note));
      if (card.ignored.length) node.append(el('div', 'note', 'Not filtered by ' + card.ignored.join(' or ')));
      host.append(node);
    }
  }

  function renderKpiError(message) {
    const host = $('kpis');
    host.replaceChildren();
    const node = el('article', 'kpi unavailable');
    node.append(el('div', 'label', 'Key figures'), el('div', 'value', 'Could not load'), el('div', 'detail', message));
    host.append(node);
  }

  // ---- chart cards ------------------------------------------------------------------
  function buildCards() {
    const host = $('charts');
    for (const def of CHARTS) {
      const card = el('article', 'card' + (def.wide ? ' wide' : ''));
      const header = el('header');
      const titles = el('div');
      const basis = el('p', 'basis');
      titles.append(el('h2', null, def.title), basis);
      header.append(titles);
      let toggle = null;
      if (def.kind !== 'table') {
        toggle = el('button', 'ghost', 'Table');
        toggle.type = 'button';
        toggle.setAttribute('aria-pressed', 'false');
        toggle.addEventListener('click', () => {
          const entry = cards[def.id];
          entry.view = entry.view === 'table' ? 'chart' : 'table';
          draw(entry);
        });
        header.append(toggle);
      }
      const body = el('div', 'body');
      const notes = el('ul', 'notes');
      card.append(header, body, notes);
      host.append(card);
      cards[def.id] = { def, body, basis, notes, toggle, view: def.kind === 'table' ? 'table' : 'chart', data: null };
    }
  }

  function showState(entry, text, retry) {
    if (window.Plotly) Plotly.purge(entry.body);
    const box = el('div', 'state', text);
    if (retry) {
      const button = el('button', 'ghost', 'Try again');
      button.type = 'button';
      button.addEventListener('click', () => loadChart(entry, state.requestId));
      box.append(document.createElement('br'), button);
    }
    entry.body.replaceChildren(box);
  }

  async function loadChart(entry, requestId) {
    entry.body.classList.add('is-loading');   // keep the previous render visible while refetching
    try {
      const data = await api('/api/charts/' + entry.def.id + '?' + filterParams());
      if (requestId !== state.requestId) return;   // a newer filter change superseded this request
      entry.data = data;
      draw(entry);
    } catch (e) {
      if (requestId !== state.requestId) return;
      entry.data = null;
      entry.notes.replaceChildren();
      showState(entry, e.message, true);
    } finally {
      if (requestId === state.requestId) entry.body.classList.remove('is-loading');
    }
  }

  function draw(entry) {
    const { def, data } = entry;
    if (!data) return;
    entry.basis.textContent = data.basis + (data.period ? '' : '. The date range does not apply.');
    entry.notes.replaceChildren();
    for (const note of data.notes) entry.notes.append(el('li', null, note));
    if (data.ignored.length) entry.notes.append(el('li', null, 'Not filtered by ' + data.ignored.join(' or ') + '.'));

    if (!data.rows.length) {
      showState(entry, data.period ? 'No completed documents in this period for this selection.' : 'Nothing to show for this selection.');
      if (entry.toggle) entry.toggle.hidden = true;
      return;
    }
    let view = entry.view;
    if (view === 'chart' && !window.Plotly) {
      view = 'table';
      entry.notes.append(el('li', null, 'The chart library did not load, so this is shown as a table.'));
    }
    if (entry.toggle) {
      entry.toggle.hidden = !window.Plotly;
      entry.toggle.textContent = view === 'table' ? 'Chart' : 'Table';
      entry.toggle.setAttribute('aria-pressed', String(view === 'table'));
    }
    if (view === 'table') drawTable(entry); else drawChart(entry);
  }

  function drawTable(entry) {
    if (window.Plotly) Plotly.purge(entry.body);
    const table = el('table');
    const head = el('tr');
    for (const [, label, format] of entry.def.columns) head.append(el('th', format === 'text' || format === 'date' || format === 'month' ? null : 'num', label));
    const thead = el('thead');
    thead.append(head);
    const tbody = el('tbody');
    for (const row of entry.data.rows) {
      const tr = el('tr');
      for (const [key, , format] of entry.def.columns) {
        const numeric = !(format === 'text' || format === 'date' || format === 'month');
        const td = el('td', numeric ? 'num' : null, FORMATS[format](row[key]));
        if (key === 'days_due' && row[key] > 0) td.classList.add('flag');
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(thead, tbody);
    const wrap = el('div', 'table-wrap');
    wrap.append(table);
    entry.body.replaceChildren(wrap);
  }

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function drawChart(entry) {
    const { def, data, body } = entry;
    const color = css('--series-' + def.series);
    const font = { family: 'system-ui, -apple-system, "Segoe UI", sans-serif', size: 12, color: css('--text-secondary') };
    const axis = { gridcolor: css('--grid'), linecolor: css('--axis'), zeroline: true, zerolinecolor: css('--axis'),
                   tickfont: { color: css('--text-muted'), size: 11 }, fixedrange: true };
    const hoverlabel = { bgcolor: css('--surface'), bordercolor: css('--axis'), font: { color: css('--text'), size: 12 } };
    const labels = data.rows.map((r) => (def.xFormat ? FORMATS[def.xFormat](r[def.x]) : String(r[def.x]).trim()));
    const values = data.rows.map((r) => r[def.y]);
    const full = values.map((v) => money(v));
    if (!body.classList.contains('js-plotly-plot')) body.replaceChildren();   // leaving a table or message state
    let trace, layout;

    if (def.kind === 'columns') {
      const plotWidth = Math.max(200, body.clientWidth - 70);
      trace = {
        type: 'bar', x: labels, y: values, customdata: full,
        width: Math.min(0.7, (24 * labels.length) / plotWidth),          // cap columns at about 24px
        marker: { color, cornerradius: 4 },
        hovertemplate: '%{x}<br><b>%{customdata}</b><extra></extra>',
      };
      layout = {
        height: 280, margin: { l: 56, r: 14, t: 10, b: def.xTitle ? 52 : 36 },
        xaxis: Object.assign({}, axis, { type: 'category', showgrid: false, zeroline: false, nticks: 14,
                                         title: def.xTitle ? { text: def.xTitle, font: { size: 11, color: css('--text-muted') } } : undefined }),
        yaxis: Object.assign({}, axis, { tickformat: '~s', showline: false, rangemode: 'tozero' }),
      };
    } else {
      // Ranking: largest at the top, value at the bar tip, long names shortened on the axis only
      const short = labels.map((l) => (l.length > 30 ? l.slice(0, 29) + '…' : l));
      trace = {
        type: 'bar', orientation: 'h', y: short.slice().reverse(), x: values.slice().reverse(),
        customdata: full.slice().reverse(), hovertext: labels.slice().reverse(),
        text: values.slice().reverse().map((v) => moneyCompact(v)), cliponaxis: false,
        // a tip label on a negative bar would sit on top of the category name; hover and the table still carry it
        textposition: values.slice().reverse().map((v) => (v < 0 ? 'none' : 'outside')),
        textfont: { color: css('--text-secondary'), size: 11 },
        width: 0.6, marker: { color, cornerradius: 4 },
        hovertemplate: '%{hovertext}<br><b>%{customdata}</b><extra></extra>',
      };
      layout = {
        height: Math.max(120, labels.length * 34 + 30), margin: { l: 10, r: 70, t: 6, b: 24 },
        xaxis: Object.assign({}, axis, { tickformat: '~s', showline: false, rangemode: 'tozero' }),
        yaxis: Object.assign({}, axis, { type: 'category', showgrid: false, zeroline: false, automargin: true,
                                         tickfont: { color: css('--text-secondary'), size: 12 } }),
      };
    }
    Object.assign(layout, { paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font, hoverlabel,
                            showlegend: false, bargap: 0.3, dragmode: false });
    Plotly.react(body, [trace], layout, { displayModeBar: false, responsive: true });
  }

  // ---- filters ----------------------------------------------------------------------
  const iso = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');

  function applyPeriod() {
    const choice = $('f-period').value;
    const today = new Date();
    let from = null;
    if (choice === 'custom') return;
    if (choice === 'default') { $('f-from').value = state.me.default_from; $('f-to').value = state.me.default_to; return; }
    if (choice === 'year') from = new Date(today.getFullYear(), 0, 1);
    else if (choice === 'all') from = new Date(2000, 0, 1);
    else { from = new Date(today); from.setDate(from.getDate() - Number(choice)); }
    $('f-from').value = iso(from);
    $('f-to').value = iso(today);
  }

  function fillSelect(select, items, allLabel) {
    const previous = select.value;
    select.replaceChildren();
    const all = el('option', null, allLabel);
    all.value = '';
    select.append(all);
    for (const item of items) {
      const option = el('option', null, item.name);
      option.value = String(item.id);
      select.append(option);
    }
    if ([...select.options].some((o) => o.value === previous)) select.value = previous;
  }

  function fillWarehouses() {
    const org = $('f-org').value;
    const list = state.me.filters.warehouses.filter((w) => !org || String(w.org_id) === org);
    fillSelect($('f-warehouse'), list, 'All warehouses');
  }

  let timer = null;
  function refreshSoon() {
    clearTimeout(timer);
    timer = setTimeout(refresh, 150);
  }

  async function refresh() {
    if ($('f-from').value && $('f-to').value && $('f-from').value > $('f-to').value) {
      showPageMessage('The start date is after the end date.');
      return;
    }
    showPageMessage('');
    const requestId = ++state.requestId;
    refreshKpis();
    for (const entry of Object.values(cards)) loadChart(entry, requestId);
    window.InsightAIForecast.refresh();
  }

  function refreshKpis() {
    const requestId = state.requestId;
    $('kpis').classList.add('is-loading');
    api('/api/kpis?' + filterParams())
      .then((payload) => { if (requestId === state.requestId) renderKpis(payload); })
      .catch((e) => { if (requestId === state.requestId) renderKpiError(e.message); })
      .finally(() => { if (requestId === state.requestId) $('kpis').classList.remove('is-loading'); });
  }

  // Shared with forecast.js
  window.InsightAI = { api, el, css, number, filterParams, refreshKpis, drawChart, drawTable };

  async function start() {
    // Shown inside an ADempiere window: signing out there is done by closing the window
    if (new URLSearchParams(location.search).get('embedded') === '1') document.body.classList.add('embedded');
    buildCards();
    try {
      state.me = await api('/api/me');
    } catch (e) {
      showPageMessage(e.message);
      return;
    }
    const me = state.me;
    currency = me.currency || 'USD';
    $('client-name').textContent = me.client;
    $('who').textContent = me.user + ' · ' + me.role;
    $('currency-name').textContent = currency;
    document.title = 'InsightAI · ' + me.client;

    fillSelect($('f-org'), me.filters.orgs, me.filters.orgs.length > 1 ? 'All my organisations' : 'My organisation');
    fillWarehouses();
    fillSelect($('f-category'), me.filters.categories, 'All categories');
    fillSelect($('f-bpartner'), me.filters.bpartners, 'All partners');
    applyPeriod();

    $('f-period').addEventListener('change', () => { applyPeriod(); refreshSoon(); });
    for (const id of ['f-from', 'f-to']) $(id).addEventListener('change', () => { $('f-period').value = 'custom'; refreshSoon(); });
    $('f-org').addEventListener('change', () => { fillWarehouses(); refreshSoon(); });
    for (const id of ['f-warehouse', 'f-category', 'f-bpartner']) $(id).addEventListener('change', refreshSoon);
    $('f-reset').addEventListener('click', () => {
      for (const id of ['f-org', 'f-category', 'f-bpartner']) $(id).value = '';
      fillWarehouses();
      $('f-warehouse').value = '';
      $('f-period').value = 'default';
      applyPeriod();
      refresh();
    });
    // Chart colours come from CSS, so redraw when the OS switches between light and dark.
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      for (const entry of Object.values(cards)) if (entry.data) draw(entry);
    });
    window.InsightAIForecast.init();
    window.InsightAIAssistant.init();
    refresh();
  }

  start();
})();
