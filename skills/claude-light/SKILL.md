---
name: claude-light
description: Runs and analyzes experiments on Claude-Light, a remote RGB LED and spectral sensor instrument at claude-light.cheme.cmu.edu. Use when the user wants to take measurements, sweep or repeat R/G/B settings, fit regression models to the 415-680nm/clear/nir outputs, do design of experiments or optimization (find inputs that hit target outputs), quantify noise and uncertainty, or download Claude-Light data. Also use for teaching statistics, regression or DOE with Claude-Light.
license: MIT
metadata:
  version: "2.0"
---

# Claude-Light experiments

Claude-Light is a real instrument: an RGB LED shining on an AS7341 spectral
sensor, on a Raspberry Pi at Carnegie Mellon. One instrument is shared by
everyone on the internet, so measurements are a scarce resource.

## The instrument

- **Inputs:** `R`, `G`, `B`, each from 0 (off) to 1 (full). Missing inputs are 0;
  values outside [0, 1] are clipped.
- **Outputs:** 10 integer counts (0 to 65535): `415nm 445nm 480nm 515nm 555nm
  590nm 630nm 680nm` plus `clear` (total visible) and `nir` (near-infrared).
  Readings saturate at 65535; `clear` saturates first when several LEDs are on.
- **Behavior to expect** (useful for sanity checks, not as ground truth):
  - Each channel is close to linear in each input. Green alone at G=1 gives
    515nm around 64000; G=0.5 about half that.
  - Green mostly drives 480-555nm, blue drives 445nm, red drives 590-630nm.
    There is crosstalk, so model all inputs for each output.
  - With the LED off there is a background of a few hundred to ~1000 counts
    from room light. It changes over the day, so measure it near your data.
  - Repeat readings vary by roughly 1%, and drift over hours.
- **Speed:** about 0.65 s per measurement, so ~1.5 measurements/s total for all
  users.

## Taking measurements

Use [scripts/claude_light.py](scripts/claude_light.py). It needs only
`requests`, and handles the busy responses correctly. Copy it next to the
user's code, or run it directly:

```bash
uv run scripts/claude_light.py 0 0.5 0 --repeat 5   # CSV to stdout
uv run scripts/claude_light.py --status
```

```python
from claude_light import measure, measure_many
out = measure(R=0.12, G=0.45, B=1)          # dict of 10 channels
rows = measure_many([(0, g, 0) for g in np.linspace(0, 1, 11)])
df = pd.DataFrame(rows)
```

The raw API, if you can't use the script:

```
GET https://claude-light.cheme.cmu.edu/api?R=0.12&G=0.45&B=1
-> {"in": [0.12, 0.45, 1.0], "out": {"415nm": 1869, ..., "nir": 1559}}
```

### Rules for using the shared instrument

1. **Measure sequentially.** Never send requests in parallel (threads,
   asyncio, `gather`). They are not faster; they wait in the same queue, and a
   client with 3 requests waiting gets HTTP 429.
2. **Handle 429 and 503.** Both carry a `Retry-After` header (seconds). Sleep
   that long and retry. 503 means the global queue is full. Never retry in a
   tight loop.
3. **Save every measurement as you go** (CSV or parquet), with a timestamp.
   Re-running a notebook should not repeat experiments; cache by input.
4. **Budget measurements.** Before a sweep, say how many measurements it will
   take and roughly how long (n × ~0.7 s, more if the instrument is busy). Ask
   before running more than a few hundred.
5. Check `GET /status` (`{"busy", "queue", ...}`) if things seem slow.

## Analysis guidance

- **Background:** measure R=G=B=0 at the start and end of a run (and
  periodically for long runs), and subtract it, or include an intercept.
- **Noise:** use repeats at a few points to estimate the noise level before
  fitting models; report uncertainties (confidence intervals on parameters,
  prediction intervals on outputs).
- **Regression:** a linear model in R, G, B per output channel usually fits
  well (R² > 0.99). Check residuals for curvature or saturation before adding
  terms.
- **Hitting targets (inverse problems):** fit a model from a modest design
  (for example 15-30 points), solve the model for the inputs, then *verify*
  with a new measurement and refine. Do not wrap the instrument directly in a
  gradient-based optimizer (L-BFGS-B, BFGS): finite differences of noisy
  measurements give useless gradients and waste many measurements. If you
  must optimize directly, use Bayesian optimization (scikit-optimize,
  `gp_minimize`) or Nelder-Mead with a small budget.
- **Design of experiments:** prefer space-filling designs (Latin hypercube,
  Sobol) or factorial designs over dense grids; 3 inputs at 11 levels is 1331
  measurements, roughly 15 minutes of the shared instrument.
- **Time effects:** the background drifts. Randomize run order when comparing
  settings, so drift is not confounded with the factors.

Longer worked examples (repeatability, calibration line, multivariate fit,
inverse problem, Latin hypercube, Bayesian optimization) are in
[references/recipes.md](references/recipes.md). Read it when writing a full
analysis.

## Existing data

- `GET https://claude-light.cheme.cmu.edu/data/export.csv?since=<unix>&until=<unix>`
  streams every measurement ever made (hundreds of thousands of rows: `t0`,
  `elapsed`, `origin`, R, G, B, the 10 channels, an anonymous `user` hash, and
  approximate location). Use `since` to limit it. Good for studying drift, or
  for building models without new measurements.
- `GET /stats/data.json` has the usage statistics behind
  https://claude-light.cheme.cmu.edu/stats.

## Other ways in

- Browser pages: https://kitchingroup.cheme.cmu.edu/claude-light/ (Green Machine, RGB,
  Session) or https://claude-light.cheme.cmu.edu/rgb (with a camera photo).
- Google Sheets: `=IMPORTDATA("https://claude-light.cheme.cmu.edu/csv?G=0.5")`
  returns the 515nm reading.
- Python package for notebooks: https://github.com/jkitchin/claude-light-python
- Exercises: https://github.com/jkitchin/claude-light/blob/main/exercises.org
