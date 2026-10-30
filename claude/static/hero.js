// The animated diagram on the home page: it cycles through a few example
// R, G, B settings and draws an illustrative spectrum for each. The numbers
// come from a rough response model, not from the instrument.

(function () {
  const svg = document.getElementById('hero-diagram');
  if (!svg) return;

  // How strongly each LED shows up in each sensor channel (R, G, B).
  const RESPONSE = [
    [0.00, 0.02, 0.18],  // 415nm
    [0.00, 0.05, 0.95],  // 445nm
    [0.00, 0.30, 0.50],  // 480nm
    [0.02, 0.95, 0.08],  // 515nm
    [0.05, 0.55, 0.02],  // 555nm
    [0.25, 0.10, 0.00],  // 590nm
    [0.95, 0.02, 0.00],  // 630nm
    [0.45, 0.00, 0.00],  // 680nm
    [0.55, 0.60, 0.55],  // clear
    [0.18, 0.03, 0.03],  // nir
  ];
  const PRESETS = [
    [0.12, 0.45, 1.00],
    [1.00, 0.00, 0.00],
    [0.00, 1.00, 0.00],
    [0.00, 0.00, 1.00],
    [0.80, 0.60, 0.10],
    [0.50, 0.50, 0.50],
    [0.20, 0.90, 0.70],
  ];

  const leds = ['R', 'G', 'B'].map((c) => svg.querySelector(`[data-led="${c}"]`));
  const beams = ['R', 'G', 'B'].map((c) => svg.querySelector(`[data-beam="${c}"]`));
  const bars = [...svg.querySelectorAll('[data-bar]')];
  const mix = svg.querySelector('[data-mix]');
  const call = document.getElementById('hero-call');

  function show([r, g, b]) {
    [r, g, b].forEach((v, i) => {
      leds[i].style.opacity = 0.15 + 0.85 * v;
      beams[i].style.opacity = 0.6 * v;
    });
    bars.forEach((bar, i) => {
      const [kr, kg, kb] = RESPONSE[i];
      const y = Math.min(1, kr * r + kg * g + kb * b);
      bar.style.transform = `scaleY(${Math.max(0.02, y)})`;
    });
    const m = Math.max(r, g, b, 0.01);
    mix.style.fill = `rgb(${255 * r / m}, ${255 * g / m}, ${255 * b / m})`;
    mix.style.opacity = 0.25 + 0.75 * m;
    const f = (x) => x.toFixed(2);
    call.textContent = `/api?R=${f(r)}&G=${f(g)}&B=${f(b)}`;
  }

  let i = 0;
  show(PRESETS[0]);
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  setInterval(() => {
    if (document.hidden) return;
    i = (i + 1) % PRESETS.length;
    show(PRESETS[i]);
  }, 2800);
})();
