// Statistics page. Loads /stats/data.json once and re-renders the charts
// in the browser when the filters change.

(function () {
  const $ = (id) => document.getElementById(id);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const fmt = (x) => (x == null ? '–' : x.toLocaleString());
  const secs = (x) => (x == null ? '–' : x.toFixed(2) + ' s');

  let D = null;
  const filter = { from: '', to: '', origin: '', country: '' };

  function layout(extra) {
    return Object.assign({
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: css('--text'), family: 'system-ui, sans-serif' },
      margin: { l: 50, r: 10, t: 10, b: 40 },
      xaxis: { gridcolor: css('--border') },
      yaxis: { gridcolor: css('--border'), rangemode: 'tozero' },
    }, extra || {});
  }
  // No scroll-zoom, so the mouse wheel scrolls the page, not the chart.
  const config = { responsive: true, displaylogo: false, scrollZoom: false };

  // Rows of the daily rollup that pass the filters.
  function rows(ignoreCountry) {
    const d = D.daily;
    const out = [];
    for (let i = 0; i < d.date.length; i++) {
      if (filter.from && d.date[i] < filter.from) continue;
      if (filter.to && d.date[i] > filter.to) continue;
      if (filter.origin && d.origin[i] !== filter.origin) continue;
      if (!ignoreCountry && filter.country && d.country_name[i] !== filter.country) continue;
      out.push(i);
    }
    return out;
  }

  function sumBy(idx, key) {
    const m = new Map();
    for (const i of idx) {
      const k = D.daily[key][i];
      m.set(k, (m.get(k) || 0) + D.daily.n[i]);
    }
    return m;
  }

  function drawMap() {
    const layer = document.querySelector('input[name=layer]:checked').value;
    const idx = rows(true);
    const byCountry = sumBy(idx, 'country_name');
    const iso = new Map();
    idx.forEach((i) => iso.set(D.daily.country_name[i], D.daily.country[i]));

    const names = [...byCountry.keys()].filter((n) => iso.get(n));
    const counts = names.map((n) => byCountry.get(n));
    const traces = [];
    if (layer === 'countries') {
      traces.push({
        type: 'choropleth',
        locationmode: 'ISO-3',
        locations: names.map((n) => iso.get(n)),
        z: counts.map((c) => Math.log10(c)),
        customdata: names.map((n, j) => [n, counts[j], D.users_by_country[n] || 0]),
        hovertemplate: '<b>%{customdata[0]}</b><br>%{customdata[1]:,} experiments' +
          '<br>%{customdata[2]:,} users<extra></extra>',
        colorscale: [[0, '#d6f5e1'], [0.5, '#3ccf7a'], [1, '#0b4d2a']],
        marker: { line: { color: css('--surface'), width: 0.5 } },
        colorbar: {
          title: 'experiments', thickness: 12,
          tickvals: [0, 1, 2, 3, 4, 5, 6], ticktext: ['1', '10', '100', '1k', '10k', '100k', '1M'],
        },
      });
    } else {
      // One dot per location (rounded to ~10 km), summed over the filters.
      const p = D.places;
      const at = new Map();
      for (let i = 0; i < p.n.length; i++) {
        if (filter.from && p.date[i] < filter.from) continue;
        if (filter.to && p.date[i] > filter.to) continue;
        if (filter.origin && p.origin[i] !== filter.origin) continue;
        if (filter.country && p.country_name[i] !== filter.country) continue;
        const key = p.lat[i] + ',' + p.lon[i];
        const e = at.get(key) || { lat: p.lat[i], lon: p.lon[i], n: 0,
          place: [p.city[i], p.country_name[i]].filter(Boolean).join(', '),
          country: p.country_name[i] };
        e.n += p.n[i];
        at.set(key, e);
      }
      // Draw big dots first so small ones stay visible on top.
      const dots = [...at.values()].sort((a, b) => b.n - a.n);
      traces.push({
        type: 'scattergeo',
        lat: dots.map((d) => d.lat),
        lon: dots.map((d) => d.lon),
        customdata: dots.map((d) => [d.country, d.n, d.place]),
        hovertemplate: '<b>%{customdata[2]}</b><br>%{customdata[1]:,} experiments<extra></extra>',
        marker: {
          size: dots.map((d) => 5 + 3 * Math.log10(d.n)),
          color: dots.map((d) => Math.log10(d.n)),
          cmin: 0, cmax: 5,
          colorscale: [[0, '#3ccf7a'], [0.5, '#e0a100'], [1, '#d6336c']],
          colorbar: {
            title: 'experiments', thickness: 12,
            tickvals: [0, 1, 2, 3, 4, 5], ticktext: ['1', '10', '100', '1k', '10k', '100k+'],
          },
          opacity: 0.75,
          line: { color: css('--surface'), width: 0.5 },
        },
      });
    }

    Plotly.react('map', traces, layout({
      margin: { l: 0, r: 0, t: 0, b: 0 },
      geo: {
        projection: { type: 'natural earth' },
        showframe: false, showcountries: true,
        countrycolor: css('--border'), coastlinecolor: css('--border'),
        landcolor: css('--bg'), showland: true,
        bgcolor: 'rgba(0,0,0,0)', showocean: false,
      },
    }), config);
  }

  function drawCharts() {
    const idx = rows(false);

    // Experiments per day
    const byDay = sumBy(idx, 'date');
    const days = [...byDay.keys()].sort();
    const traces = [{
      type: 'bar', name: 'experiments', x: days, y: days.map((d) => byDay.get(d)),
      marker: { color: css('--accent') },
    }];
    if (!filter.country && !filter.origin) {
      const u = D.users_by_day;
      const keep = u.date.map((_, i) => i).filter((i) =>
        (!filter.from || u.date[i] >= filter.from) && (!filter.to || u.date[i] <= filter.to));
      traces.push({
        type: 'scatter', mode: 'lines', name: 'unique users', yaxis: 'y2',
        x: keep.map((i) => u.date[i]), y: keep.map((i) => u.users[i]),
        line: { color: '#e0a100', width: 1.5 },
      });
    }
    Plotly.react('timeseries', traces, layout({
      xaxis: { gridcolor: css('--border'), rangeslider: { visible: true }, type: 'date' },
      yaxis: { title: 'experiments', gridcolor: css('--border'), rangemode: 'tozero' },
      yaxis2: { title: 'users', overlaying: 'y', side: 'right', rangemode: 'tozero', showgrid: false },
      legend: { orientation: 'h', y: 1.1 },
      margin: { l: 60, r: 60, t: 10, b: 40 },
    }), config);

    // By source
    const byOrigin = sumBy(idx, 'origin');
    Plotly.react('origins', [{
      type: 'pie', hole: 0.55, labels: [...byOrigin.keys()], values: [...byOrigin.values()],
      textinfo: 'percent', textposition: 'inside',
    }], layout({ margin: { l: 10, r: 10, t: 10, b: 10 }, showlegend: true }), config);

    // Top countries
    const byCountry = [...sumBy(idx, 'country_name').entries()].sort((a, b) => b[1] - a[1]);
    $('top-countries').querySelector('tbody').innerHTML = byCountry.slice(0, 50).map(([n, c]) =>
      `<tr><td style="text-align:left">${n}</td><td>${fmt(c)}</td><td>${fmt(D.users_by_country[n] || 0)}</td></tr>`).join('');

    // Mean measurement time per day
    const sum = new Map(), cnt = new Map();
    for (const i of idx) {
      const d = D.daily.date[i];
      sum.set(d, (sum.get(d) || 0) + D.daily.elapsed_sum[i]);
      cnt.set(d, (cnt.get(d) || 0) + D.daily.n[i]);
    }
    Plotly.react('latency', [{
      type: 'scatter', mode: 'markers', x: days, y: days.map((d) => sum.get(d) / cnt.get(d)),
      marker: { color: css('--accent'), size: 4 },
    }], layout({ yaxis: { title: 'seconds', gridcolor: css('--border'), rangemode: 'tozero' } }), config);

    const total = idx.reduce((s, i) => s + D.daily.n[i], 0);
    $('f-summary').textContent = `${fmt(total)} experiments match`;
  }

  function drawStatic() {
    const t = D.totals, r = D.recent;
    $('k-exp').textContent = fmt(t.experiments);
    $('k-users').textContent = fmt(t.users);
    $('k-countries').textContent = fmt(t.countries);
    $('k-latency').textContent = `${secs(r.elapsed_p50)} / ${secs(r.elapsed_p95)}`;
    $('k-wait').textContent = secs(r.wait_p95);
    const h = r.elapsed_hist;
    Plotly.react('latency-hist', [{
      type: 'bar', x: h.edges.slice(0, -1).map((e, i) => (e + h.edges[i + 1]) / 2), y: h.counts,
      marker: { color: css('--accent') },
    }], layout({ xaxis: { title: 'seconds', gridcolor: css('--border') }, bargap: 0.05 }), config);
    $('generated').textContent = `Updated ${new Date(D.generated * 1000).toLocaleString()}` +
      (t.last_t0 ? ` · last experiment ${new Date(t.last_t0 * 1000).toLocaleString()}` : '');

    const origins = [...new Set(D.daily.origin)].sort();
    $('f-origin').innerHTML = '<option value="">all</option>' +
      origins.map((o) => `<option>${o}</option>`).join('');
    $('f-from').min = $('f-to').min = t.first_date || '';
  }

  function redraw() { drawMap(); drawCharts(); }

  function setCountry(name) {
    filter.country = name;
    $('f-country').textContent = name;
    $('f-country-chip').hidden = !name;
    drawCharts();
    drawMap();
  }

  async function init() {
    D = await (await fetch('/stats/data.json')).json();
    drawStatic();
    redraw();

    $('f-from').addEventListener('change', (e) => { filter.from = e.target.value; redraw(); });
    $('f-to').addEventListener('change', (e) => { filter.to = e.target.value; redraw(); });
    $('f-origin').addEventListener('change', (e) => { filter.origin = e.target.value; redraw(); });
    $('f-country-clear').addEventListener('click', () => setCountry(''));
    document.querySelectorAll('input[name=layer]').forEach((el) => el.addEventListener('change', drawMap));
    $('map').on('plotly_click', (ev) => {
      const p = ev.points[0];
      if (p.customdata) setCountry(p.customdata[0]);
    });
    // Re-theme the charts if the system switches light/dark.
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { drawStatic(); redraw(); });
  }

  window.addEventListener('DOMContentLoaded', init);
})();
