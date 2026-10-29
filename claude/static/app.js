// Shared behavior for all pages: the instrument status badge, keeping
// sliders and number inputs in sync, and showing "busy" replies from htmx.

(function () {
  // Set window.CLAUDE_LIGHT_API to use these pages from another site
  // (the GitHub Pages copy in docs/ does).
  const API = window.CLAUDE_LIGHT_API || '';
  const badge = document.getElementById('status');

  async function poll() {
    try {
      const s = await (await fetch(API + '/status')).json();
      badge.className = 'status ' + (s.queue > 0 ? 'busy' : 'idle');
      badge.textContent = s.queue > 0 ? `busy · ${s.queue} queued` : 'idle';
    } catch (e) {
      badge.className = 'status';
      badge.textContent = 'offline?';
    }
  }
  if (badge) {
    poll();
    setInterval(() => { if (!document.hidden) poll(); }, 5000);
  }

  // <input type=range data-sync="R"> mirrors <input type=number name="R">.
  document.querySelectorAll('input[data-sync]').forEach((slider) => {
    const box = document.querySelector(`input[name="${slider.dataset.sync}"]`);
    const update = () => document.dispatchEvent(new Event('rgbchange'));
    slider.addEventListener('input', () => { box.value = slider.value; update(); });
    box.addEventListener('input', () => { slider.value = box.value; update(); });
  });

  // Swap 429/503 replies too, so the "busy, try again" message is shown.
  document.addEventListener('htmx:beforeSwap', (e) => {
    if ([429, 503].includes(e.detail.xhr.status)) {
      e.detail.shouldSwap = true;
      e.detail.isError = false;
    }
  });
})();
