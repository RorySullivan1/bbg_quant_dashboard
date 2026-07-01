---
name: quantitative-finance
description: >-
  Domain floor for quantitative-finance code in Python — financial-math
  conventions, numerical stability, library selection, and validating outputs
  against closed-form benchmarks. Use whenever the work involves pricing
  (options, bonds, swaps), discounting/present value, greeks, risk metrics
  (VaR, expected shortfall, duration), or "is this formula numerically stable /
  using the right convention". Trigger on phrases like "price this option",
  "compute the greeks", "annualize this", "day-count", "discount factor",
  "Black-Scholes", "is this stable", or any quant computation where the math
  convention matters. This is the shared quant floor — defer time-series
  mechanics to financial-timeseries-analysis, backtest design to
  backtesting-validation, and generic Python to python-development.
---

# Quantitative Finance

The domain floor for writing correct quantitative code. The job is to get the
**math conventions and the numerics right** — a result that is off by an
annualization factor, a sign, or a day-count basis is wrong even when the code
is clean. Always know which convention you are using and validate against a
reference value when one exists.

## Core principles

- **State your conventions.** Every quant number carries hidden assumptions:
  compounding frequency, day-count, annualization factor, sign of a cash flow,
  whether a rate is decimal or percent. Make them explicit in code and comments;
  most "bugs" are convention mismatches, not logic errors.
- **Validate against closed form.** When a formula has an analytic answer
  (Black–Scholes for a European option, analytic VaR for a normal P&L, a bond's
  price from its yield), test the implementation against it before trusting it on
  real data.
- **Numerical stability is correctness.** Floating-point math is not real-number
  math. Work in log-space for products of probabilities, avoid subtracting nearly
  equal numbers, and watch ill-conditioned matrices.
- **Money is not a float to compare.** Never test monetary equality with `==`;
  use tolerances, and use `Decimal` for accounting/settlement amounts where exact
  cents matter (vs. `float` for model math).
- **Reach for the right library.** Don't hand-roll an optimizer, a special
  function, or a covariance estimator that scipy/numpy/statsmodels already ships,
  tested.

## Conventions that bite

- **Day-count.** ACT/360, ACT/365, 30/360 give different accruals. Match the
  instrument; never assume `days / 365`.
- **Annualization.** Scale returns by the period count, volatility by its square
  root: `ann_vol = vol * sqrt(periods_per_year)`, `ann_ret = mean * periods`.
  Mixing the two (scaling vol linearly) is a classic error.
- **Compounding.** Simple vs. discrete vs. continuous compounding change the
  discount factor: `exp(-r*t)` (continuous) ≠ `1/(1+r)**t` (annual). Pick one and
  be consistent across the calculation.
- **Rates units.** 5% is `0.05`, not `5`. Decide decimal-vs-percent at the
  boundary and keep it decimal internally.
- **Sign of cash flows.** Outflows negative, inflows positive — IRR/NPV silently
  return nonsense if signs are inconsistent.
- **Returns.** Simple returns `p_t/p_{t-1} - 1` aggregate across assets;
  log returns `ln(p_t/p_{t-1})` aggregate across time. Don't sum simple returns
  over time or average log returns across a portfolio.

## Numerical stability

- **Log-space for products.** Sum `log` values instead of multiplying many small
  probabilities/factors; exponentiate at the end. Use `scipy.special.logsumexp`
  for normalizing.
- **Catastrophic cancellation.** Subtracting nearly equal large numbers destroys
  precision (e.g. naive variance `E[x²] - E[x]²`). Use `numpy.var` /
  Welford-style updates, or `numpy.expm1`/`log1p` for `exp(x)-1` and `log(1+x)`
  near zero.
- **Covariance conditioning.** Sample covariance matrices are often near-singular
  or non-PSD. Shrink (Ledoit–Wolf, `sklearn.covariance.LedoitWolf`) or add a
  ridge before inverting; prefer solving a linear system over explicit inversion.
- **Optimizer hygiene.** Give `scipy.optimize` analytic gradients when cheap,
  scale variables to comparable magnitudes, set sensible bounds, and check
  `result.success` — a silently non-converged optimizer returns garbage.

## Library selection

- **numpy** — array math, linear algebra, the vectorized core.
- **scipy** — `optimize` (calibration, root-finding), `stats` (distributions),
  `interpolate` (curves), `linalg`, `special`.
- **pandas** — labeled/time-indexed data and alignment (see
  `financial-timeseries-analysis`).
- **statsmodels** — regression, time-series models, statistical tests with
  inference (std errors, p-values) that sklearn omits.
- **Specialized** (justify + pin, ask before adding): `QuantLib` for full
  curve/instrument machinery, `arch` for GARCH-family volatility.

## Validation checklist

- [ ] Conventions (day-count, compounding, annualization, units, signs) are
      explicit and consistent end-to-end.
- [ ] Implementation tested against a closed-form / reference value where one
      exists; otherwise known-input → known-output pins.
- [ ] No `==` on floats/money; tolerances or `Decimal` used appropriately.
- [ ] Stability handled: log-space, `log1p`/`expm1`, conditioned/shrunk matrices,
      converged optimizer.
- [ ] Edge cases covered: zero/negative rates, zero volatility, expiry `t→0`,
      empty or single-point inputs.
- [ ] Used a tested library routine instead of a hand-rolled numerical method.

## Anti-patterns

- Annualizing volatility linearly instead of by `sqrt(periods)`.
- `days / 365` regardless of the instrument's day-count basis.
- Variance via `mean(x**2) - mean(x)**2` (cancellation) instead of `numpy.var`.
- Inverting a covariance matrix with `np.linalg.inv` and trusting the result.
- Comparing prices/P&L with `==`, or modeling settlement cash in `float`.
- Hand-rolling Newton's method when `scipy.optimize.brentq`/`newton` exists.
- Trusting an optimizer's output without checking convergence.

## Out of scope

- **Time-series mechanics** (resampling, calendars, rolling windows, volatility
  estimation, look-ahead in features) → `financial-timeseries-analysis`.
- **Backtest design and model validation** (splits, costs, overfitting,
  performance metrics) → `backtesting-validation`.
- **Reviewing existing quant code** for defects → `quant-code-review`.
- **General Python idioms, packaging, non-quant code** → `python-development`.
