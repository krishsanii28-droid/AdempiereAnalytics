/* Ask InsightAI panel. Uses helpers that app.js publishes on window.InsightAI. */
window.InsightAIAssistant = (function () {
  'use strict';

  const ui = () => window.InsightAI;
  const $ = (id) => document.getElementById(id);
  let busy = false;

  function chip(text) {
    const button = ui().el('button', 'chip', text);
    button.type = 'button';
    button.addEventListener('click', () => { $('as-input').value = text; ask(); });
    return button;
  }

  async function ask() {
    const { el } = ui();
    const question = $('as-input').value.trim();
    if (!question || busy) return;
    busy = true;
    $('as-button').disabled = true;
    $('as-answer').classList.add('is-loading');
    let data;
    try {
      const response = await fetch('/api/assistant/ask', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ question }),
      });
      if (response.status === 401) throw new Error('Your InsightAI session has ended. Open InsightAI again from the ADempiere menu.');
      data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'InsightAI could not answer (HTTP ' + response.status + ').');
    } catch (e) {
      $('as-answer').replaceChildren(el('p', 'as-text', e.message || 'The InsightAI service is not responding.'));
      data = null;
    } finally {
      busy = false;
      $('as-button').disabled = false;
      $('as-answer').classList.remove('is-loading');
    }
    if (data) render(data);
  }

  function render(d) {
    const { el, drawChart, drawTable } = ui();
    const host = $('as-answer');
    host.replaceChildren();
    host.append(el('p', 'as-question', d.question));
    host.append(el('p', 'as-text', d.answer));

    if (!d.supported) {
      if (d.closest && d.closest.length) {
        host.append(el('p', 'basis', 'Closest questions InsightAI can answer:'));
        const row = el('div', 'chips');
        for (const c of d.closest) row.append(chip(c.example));
        host.append(row);
      }
      const all = el('details');
      all.append(el('summary', null, 'Everything InsightAI can answer'));
      const list = el('ul');
      for (const q of d.supported_questions) list.append(el('li', null, q.title + ': “' + q.example + '”'));
      all.append(list);
      host.append(all);
      if (d.matcher_note) host.append(el('p', 'basis', d.matcher_note));
      return;
    }

    const how = 'Understood as: ' + d.title + ' · ' + d.understood.join(' · ') + ' · match ' + d.confidence.toFixed(2) +
      (d.matcher === 'keyword' ? ' (keywords)' : '');
    host.append(el('p', 'basis', how));
    if (d.basis) host.append(el('p', 'basis', 'Source: ' + d.basis + '.'));
    if (d.notes.length || d.matcher_note) {
      const notes = el('ul', 'notes');
      for (const note of d.notes) notes.append(el('li', null, note));
      if (d.matcher_note) notes.append(el('li', null, d.matcher_note));
      host.append(notes);
    }
    if (!d.rows.length) return;

    if (d.chart && window.Plotly && d.rows.length > 1) {
      const plot = el('div', 'as-plot');
      host.append(plot);
      drawChart({ def: d.chart, data: { rows: d.rows }, body: plot });
    }
    const table = el('div');
    host.append(table);
    drawTable({ def: { columns: d.columns }, data: { rows: d.rows }, body: table });
  }

  async function init() {
    const { api } = ui();
    $('as-form').addEventListener('submit', (e) => { e.preventDefault(); ask(); });
    try {
      const list = await api('/api/assistant/questions');
      const picks = ['top_products', 'overdue_receivables', 'supplier_delays', 'stockout_risk', 'declining_sales_high_stock'];
      const row = $('as-examples');
      for (const id of picks) {
        const q = list.find((x) => x.intent === id);
        if (q) row.append(chip(q.example));
      }
    } catch (e) { /* examples are a convenience; the input still works */ }
    // ?ask=... opens the page with that question already asked
    const preset = new URLSearchParams(location.search).get('ask');
    if (preset) { $('as-input').value = preset.slice(0, 300); ask(); }
  }

  return { init };
})();
