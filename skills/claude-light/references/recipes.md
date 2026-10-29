# Claude-Light recipes

Worked examples. All use `measure` and `measure_many` from
`scripts/claude_light.py`, plus numpy, pandas, scipy and (for the last two)
scikit-learn or scikit-optimize. Each one says how many measurements it takes.

```python
import numpy as np
import pandas as pd
from claude_light import measure, measure_many, CHANNELS
```

## Contents

1. Repeatability (20 measurements)
2. Calibration line for one channel (13)
3. Multivariate linear model (25)
4. Inverse problem: inputs for target outputs (25 + a few)
5. Latin hypercube design (20)
6. Bayesian optimization (about 25)
7. Caching measurements

## 1. Repeatability

```python
rows = measure_many([(0, 0.5, 0)] * 20)
x = pd.DataFrame(rows)['515nm']
mean, sd = x.mean(), x.std(ddof=1)
sem = sd / np.sqrt(len(x))
from scipy import stats
ci = stats.t.interval(0.95, len(x) - 1, loc=mean, scale=sem)
print(f'mean {mean:.0f}, sd {sd:.0f} ({100 * sd / mean:.2f}%), 95% CI {ci}')
```

Plot `x` against the measurement time `t` too: a trend means drift, not noise.

## 2. Calibration line

Bracket the run with background measurements.

```python
G = np.linspace(0, 1, 11)
rows = measure_many([(0, 0, 0)] + [(0, g, 0) for g in G] + [(0, 0, 0)])
df = pd.DataFrame(rows)
bg = df.loc[[0, len(df) - 1], '515nm'].mean()
data = df.iloc[1:-1]

from scipy import stats
fit = stats.linregress(data['G'], data['515nm'])
print(f'slope {fit.slope:.0f} ± {fit.stderr:.0f}, intercept {fit.intercept:.0f}, '
      f'R² {fit.rvalue**2:.5f}, background {bg:.0f}')
resid = data['515nm'] - (fit.intercept + fit.slope * data['G'])
```

Inspect `resid` against `G`. Curvature near G=1 on some channels means
saturation; drop those points or fit a lower range.

## 3. Multivariate linear model

One model per output channel, all three inputs.

```python
rng = np.random.default_rng(0)
X = rng.uniform(0, 1, size=(25, 3))
df = pd.DataFrame(measure_many([tuple(x) for x in X]))

from sklearn.linear_model import LinearRegression
models = {}
for ch in CHANNELS:
    m = LinearRegression().fit(df[['R', 'G', 'B']], df[ch])
    models[ch] = m
    print(f'{ch:>6}: R²={m.score(df[["R", "G", "B"]], df[ch]):.4f} '
          f'coef={np.round(m.coef_).astype(int)} b={m.intercept_:.0f}')
```

For parameter uncertainties use `statsmodels.api.OLS` (`.summary()`,
`.conf_int()`), or `pycse.regress`.

## 4. Inverse problem

Find R, G, B so that 480nm, 515nm and 630nm are each 25000. With the linear
models from recipe 3 this is a small bounded least-squares problem; solve it on
the model, not on the instrument.

```python
from scipy.optimize import lsq_linear

targets = {'480nm': 25000, '515nm': 25000, '630nm': 25000}
A = np.array([models[ch].coef_ for ch in targets])
b = np.array([t - models[ch].intercept_ for ch, t in targets.items()])
sol = lsq_linear(A, b, bounds=(0, 1))
R, G, B = sol.x
out = measure(R, G, B)                       # verify
print(sol.x, {ch: out[ch] for ch in targets})
```

If the check misses by more than the noise, add the new point to the data, refit
and solve again. One or two rounds is usually enough. If `sol.x` sits on a bound,
the targets may not be reachable together.

## 5. Latin hypercube design

```python
from scipy.stats import qmc
X = qmc.LatinHypercube(d=3, seed=1).random(n=20)
df = pd.DataFrame(measure_many([tuple(x) for x in X]))
```

Space-filling designs give good models with far fewer points than grids.
Randomize the order (already random here) so drift isn't confounded with inputs.

## 6. Bayesian optimization

When there is no good model form, optimize the instrument directly with a
small budget. Here: make 515nm equal 30000 while keeping 630nm low.

```python
from skopt import gp_minimize

def loss(x):
    out = measure(*x)
    return ((out['515nm'] - 30000) / 1000) ** 2 + out['630nm'] / 10000

res = gp_minimize(loss, [(0.0, 1.0)] * 3, n_calls=25, n_initial_points=8,
                  noise='gaussian', random_state=0)
print(res.x, res.fun)
```

Avoid gradient-based optimizers (L-BFGS-B, BFGS, CG) on the instrument: they
estimate gradients by finite differences of noisy readings and burn
measurements.

## 7. Caching measurements

Keep a CSV of everything measured, and reuse it, so rerunning a notebook does
not repeat experiments.

```python
from pathlib import Path

CACHE = Path('claude_light_cache.csv')

def cached_measure_many(points):
    old = pd.read_csv(CACHE) if CACHE.exists() else pd.DataFrame()
    key = lambda R, G, B: (round(R, 6), round(G, 6), round(B, 6))
    seen = {key(r.R, r.G, r.B) for r in old.itertuples()} if len(old) else set()
    new = [p for p in points if key(*p) not in seen]
    if new:
        old = pd.concat([old, pd.DataFrame(measure_many(new))], ignore_index=True)
        old.to_csv(CACHE, index=False)
    want = {key(*p) for p in points}
    return old[[key(r.R, r.G, r.B) in want for r in old.itertuples()]]
```

This caches by exact input. It is the wrong tool for repeatability studies,
where you want repeats.
