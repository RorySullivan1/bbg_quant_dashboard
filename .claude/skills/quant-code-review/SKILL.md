---
name: quant-code-review
description: >-
  Expert review of quantitative-finance Python for the defects generic review
  misses — numerical correctness (float precision, catastrophic cancellation),
  look-ahead and survivorship bias, RNG seeding and reproducibility, units and
  sign conventions, vectorization correctness, and statistical soundness. Use
  whenever the user asks to review, audit, or check quant code — pricing/risk
  models, signals, backtests, time-series pipelines — or reports a suspicious
  number, an unreproducible result, or "is this backtest valid". Trigger on
  phrases like "review this quant code", "is this backtest valid", "why are my
  numbers off", "check this pricing/risk code", "is this reproducible", or a
  paste of numerical-finance code with a question. Layered above the generic
  python-review — defer ordinary bugs/security/style to that skill, and the
  underlying domain rules to quantitative-finance, financial-timeseries-analysis,
  and backtesting-validation.
---

# Quant Code Review

Review quantitative-finance Python for the failures that pass generic review yet
produce confidently wrong numbers. The code can be clean, typed, and test-passing
and still be wrong because it leaks the future, loses precision, or mislabels a
convention. **Find the defects that move the numbers**, sorted by impact.

## Core principles

- **Wrong numbers beat ugly code.** A correctly-formatted strategy with look-ahead
  bias is worse than messy code that's right. Prioritize correctness of results.
- **Reproduce or distrust.** A result you can't reproduce bit-for-bit (seeded RNG,
  pinned data) can't be reviewed — flag non-determinism first.
- **Explain why it moves the number.** "Look-ahead here inflates the Sharpe
  because the signal already saw `t`'s close it trades on" is a review; "looks
  off" is not.
- **Verify before flagging.** Confirm the convention/leak in the code; don't guess
  at a numerical bug you can't point to.

## Severity framework

Organize the review with these levels; skip empty ones rather than padding.

- **Blocking** — produces wrong results or invalidates conclusions: look-ahead
  bias, survivorship bias, an annualization/units/sign error, catastrophic
  precision loss, an unconverged optimizer trusted as converged.
- **Should fix** — materially distorts or hides risk: missing transaction costs,
  full-sample normalization, unseeded RNG in a reported result, ignoring NaNs in
  a reduction.
- **Consider** — robustness and method: weak split design, no t-stat/CI on a
  Sharpe, no null baseline, fragile covariance handling.
- **Nit** — minor clarity that doesn't change the number.

## What to actively look for

### Look-ahead & data bias (almost always Blocking)
- Signal and execution on the **same bar**; features not `shift`ed before aligning
  to forward returns.
- **Centered** rolling windows or **full-sample** mean/std used in a predictive
  context.
- **Survivorship:** backtesting the current universe over history; restated /
  as-of-today fundamentals used as point-in-time.
- Train/test split that **shuffles** time order or omits purge/embargo around
  overlapping labels.

### Numerical correctness
- **Cancellation:** variance as `mean(x**2)-mean(x)**2`, naive `exp(x)-1` /
  `log(1+x)` near zero (use `expm1`/`log1p`), differences of nearly equal prices.
- **Float equality** on prices/P&L (`==`), or money modeled as `float` where exact
  cents matter (should be `Decimal`).
- **Matrix conditioning:** `np.linalg.inv` on a near-singular covariance; inverting
  instead of solving; non-PSD covariance fed to an optimizer.
- **Optimizer/root-finder** result used without checking `success`/convergence,
  unscaled variables, missing bounds.

### Conventions & units
- **Annualization:** volatility scaled linearly instead of by `sqrt(periods)`;
  mixing per-period and annual figures.
- **Day-count / compounding** mismatched to the instrument (`days/365` everywhere).
- **Rates** as percent vs decimal mixed; **sign** of cash flows inconsistent in
  NPV/IRR.
- **Return type** misused: summing simple returns over time, averaging log returns
  across a portfolio.

### Reproducibility
- **Unseeded RNG** (`np.random` global state, no `default_rng(seed)`), or a seed set
  once but shared across parallel workers.
- Result depends on **dict/set ordering, wall-clock time, or unpinned data**.
- Nondeterministic parallelism (float reduction order) presented as exact.

### Vectorization correctness
- `apply`/`iterrows` loops that silently misalign vs. a vectorized form — and the
  vectorized rewrite that **changes** results by ignoring index alignment.
- **NaN handling** in reductions: `np.mean` vs `np.nanmean`; a single NaN poisoning
  a whole column; `fillna` masking a real gap.
- Broadcasting that pairs the wrong axes; chained pandas ops on misaligned indexes.

### Statistical soundness
- Sharpe/metrics with **no costs, no t-stat/CI**, or annualized wrong.
- Overfitting: best-of-many reported without deflation; smooth-surface check
  missing; no null/buy-and-hold baseline.
- Assuming normality/homoskedasticity where returns are fat-tailed and
  clustered (use robust SEs / EWMA-GARCH).

## Review output format

```markdown
## Summary
One or two sentences: does this produce trustworthy numbers, and the single most
important issue.

## Blocking
- **[file:line]** What's wrong, and *why it moves the number*. Suggested fix:
  ```python
  # corrected code
  ```

## Should fix
- ...

## Consider
- ...

## Nit
- ...
```

Omit empty categories. If the quant logic is sound, say so — don't invent issues.

## Anti-patterns (in the review itself)

- Reviewing style while missing the look-ahead bias.
- Calling a vectorization "equivalent" without checking index alignment and NaNs.
- Flagging a "bug" you can't point to — say "this may leak if X, confirm" instead.
- Inflating a convention Nit to Blocking, or burying a real leak under style notes.

## Out of scope

- **Generic Python bugs, security, performance, style** → `python-review`.
- **Teaching the correct math/convention** (vs. flagging the violation) →
  `quantitative-finance`.
- **The mechanics of correct series handling and backtest design** →
  `financial-timeseries-analysis` and `backtesting-validation`.
- **Writing the corrected implementation end-to-end** → the
  `finance-quantitative-developer` agent.
