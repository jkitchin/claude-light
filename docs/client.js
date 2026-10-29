// A small browser client for the Claude-Light API, used by the GitHub Pages
// site. The instrument itself runs on the Raspberry Pi; these pages call it
// directly (the API allows cross-origin requests).

window.ClaudeLight = (function () {
  const API = window.CLAUDE_LIGHT_API || '';
  const CHANNELS = ['415nm', '445nm', '480nm', '515nm', '555nm',
    '590nm', '630nm', '680nm', 'clear', 'nir'];
  const COLORS = {
    '415nm': '#7a00e6', '445nm': '#1f3cff', '480nm': '#00b8e6', '515nm': '#2fbf00',
    '555nm': '#a4d400', '590nm': '#f2c200', '630nm': '#ff5a00', '680nm': '#d10000',
    clear: '#9a9a9a', nir: '#7a3b3b',
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const clamp = (x) => Math.min(1, Math.max(0, +x || 0));

  // One measurement. There is one instrument shared by everyone, so when it
  // is busy (HTTP 429/503) wait as the server asks and try again.
  async function measure(R, G, B, { tries = 20, onWait } = {}) {
    const q = new URLSearchParams({ R: clamp(R), G: clamp(G), B: clamp(B) });
    for (let i = 0; i < tries; i++) {
      let resp;
      try {
        resp = await fetch(`${API}/api?${q}`);
      } catch (e) {
        throw new Error('Could not reach Claude-Light. It may be offline.');
      }
      if (resp.ok) return resp.json();
      if (resp.status === 429 || resp.status === 503) {
        const wait = +resp.headers.get('Retry-After') || 3;
        if (onWait) onWait(wait);
        await sleep(wait * 1000);
        continue;
      }
      throw new Error(`Claude-Light returned HTTP ${resp.status}`);
    }
    throw new Error('Claude-Light is very busy right now. Please try again later.');
  }

  function toCSV(rows) {
    return rows.map((r) => r.join(',')).join('\n') + '\n';
  }

  // Point an <a> at a downloadable CSV file.
  function csvLink(a, rows, filename = 'data.csv') {
    if (a.href.startsWith('blob:')) URL.revokeObjectURL(a.href);
    a.href = URL.createObjectURL(new Blob([toCSV(rows)], { type: 'text/csv' }));
    a.download = filename;
    a.hidden = false;
  }

  function table(el, header, rows) {
    const esc = (x) => String(x).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
    el.innerHTML = '<tr>' + header.map((h) => `<th>${esc(h)}</th>`).join('') + '</tr>' +
      rows.map((r) => '<tr>' + r.map((v) => `<td>${esc(v)}</td>`).join('') + '</tr>').join('');
  }

  // Bar chart of one measurement's channels.
  function spectrum(el, out) {
    el.innerHTML = '<div style="display:flex; align-items:flex-end; gap:6px; height:200px">' +
      CHANNELS.map((k) => `
        <div style="flex:1; display:flex; flex-direction:column; align-items:center; height:100%; justify-content:flex-end">
          <div class="muted" style="font-size:11px">${out[k]}</div>
          <div title="${k}: ${out[k]}" style="width:100%; height:${(100 * out[k] / 65535).toFixed(1)}%; min-height:1px; background:${COLORS[k]}; border-radius:3px 3px 0 0"></div>
          <div style="font-size:11px">${k}</div>
        </div>`).join('') + '</div>';
  }

  // A small scatter plot of [x, y] points with x in [0, 1].
  function scatter(el, points, xlabel, ylabel) {
    const ymax = Math.max(1, ...points.map((p) => p[1]));
    el.innerHTML = `
      <svg viewBox="0 0 320 220" width="100%" role="img" aria-label="${ylabel} versus ${xlabel}">
        <line x1="40" y1="190" x2="310" y2="190" stroke="currentColor" opacity="0.4"/>
        <line x1="40" y1="10" x2="40" y2="190" stroke="currentColor" opacity="0.4"/>
        <text x="175" y="214" text-anchor="middle" font-size="12" fill="currentColor">${xlabel}</text>
        <text x="12" y="100" font-size="12" fill="currentColor" transform="rotate(-90 12 100)" text-anchor="middle">${ylabel}</text>
        <text x="40" y="204" font-size="10" fill="currentColor" text-anchor="middle">0</text>
        <text x="310" y="204" font-size="10" fill="currentColor" text-anchor="middle">1</text>
        <text x="36" y="14" font-size="10" fill="currentColor" text-anchor="end">${ymax}</text>
        ${points.map((p) => `<circle cx="${40 + 270 * p[0]}" cy="${190 - 180 * p[1] / ymax}" r="4" fill="var(--accent)"/>`).join('')}
      </svg>`;
  }

  return { API, CHANNELS, measure, csvLink, table, spectrum, scatter, clamp };
})();
