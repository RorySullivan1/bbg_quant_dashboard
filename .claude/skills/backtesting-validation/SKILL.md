---
name: backtesting-validation
description: >-
  Backtest correctness and quant-model validation in Python — point-in-time
  data, train/test/walk-forward splits, transaction costs and slippage,
  performance metrics (Sharpe, Sortino, max drawdown, hit rate), and guarding
  against overfitting and multiple-testing bias. Use whenever the work involves
  building or evaluating a backtest, simulating a strategy's P&L, splitting data
  for model selection, computing risk-adjusted performance, or judging whether a
  result will hold out of sample. Trigger on phrases like "backtest this",
  "walk-forward", "Sharpe ratio", "max drawdown", "out-of-sample", "is this
  overfit", "transaction costs", "in-sample vs out-of-sample". Defer return/
  series mechanics to financial-timeseries-analysis, pricing/risk math to
  quantitative-finance, and generic Python to python-development.
---

# Backtesting & Validation

A backtest's job is to estimate out-of-sample performance honestly. Most
backtests flatter the strategy through subtle leakage and over-fitting, so the
discipline is **adversarial**: assume the impressive Sharpe is a bug until the
methodology rules out look-ahead, costs, and data-snooping.

## Core principles

- **Point-in-time only.** At each simulated timestamp, use only data that was
  actually known then — including the fact that prices, fundamentals, and index
  membership get revised. Restated/as-of-today data is the most common silent
  leak.
- **Trade on the next bar.** A signal computed from data through `t` executes at
  `t+1`'s price, not `t`'s close. Aligning signal and execution to the same bar
  fabricates returns.
- **Costs are not optional.** Commissions, spread, slippage, and market impact
  turn many "profitable" strategies negative. Model them from the start, not as
  an afterthought.
- **Out-of-sample is sacred.** Tune nothing on the test set. Every parameter you
  pick by looking at final performance is an in-sample choice, however indirect.
- **Account for the search.** Trying 100 strategies and reporting the best one is
  multiple testing; the winner's Sharpe is inflated. Track how many variants you
  tried.

## Splitting data

- **Respect time order.** Never shuffle or use random k-fold on a time series —
  it trains on the future. Use chronological splits.
- **Walk-forward / rolling origin.** Fit on a window, test on the next block,
  roll forward, concatenate the out-of-sample pieces. This is the realistic
  estimate of live performance.
- **Embargo & purge.** Leave a gap between train and test so overlapping labels
  (e.g. multi-day forward returns) don't leak across the boundary (López de
  Prado's purging/embargo).
- **Keep a final holdout** you touch once, at the very end — not during
  development.

## Costs & execution realism

- Charge spread/commission on every fill; size slippage with the instrument's
  liquidity, not a flat token bps for everything.
- Cap position sizes and turnover to what the modeled liquidity supports.
- Use executable prices (next open/VWAP), and don't assume fills at the exact
  signal-bar close or at the day's high/low.

## Performance metrics (report, don't cherry-pick)

- **Sharpe** = `mean(excess_ret) / std(excess_ret) * sqrt(periods_per_year)` —
  annualize by `sqrt(periods)` (see `quantitative-finance`), and net of costs.
- **Sortino** uses downside deviation; **Calmar** = annual return / max drawdown.
- **Max drawdown** from the running peak of the equity curve; report its length,
  not just its depth.
- **Hit rate, turnover, exposure, capacity** — a high Sharpe at 1000% turnover or
  tiny capacity is not a real strategy.
- Report **net-of-cost** numbers and a **confidence interval / t-stat** on the
  Sharpe; a point estimate hides how noisy it is.

## Overfitting defenses

- Prefer **fewer parameters**; check the performance *surface* is smooth, not a
  lone spike at the chosen settings.
- **Deflate for the search:** the more configurations tried, the higher the
  Sharpe needed to be significant (deflated/probabilistic Sharpe ratio).
- **Sanity baselines:** compare to buy-and-hold, a random-entry strategy, and a
  shuffled-signal null. If the edge survives none, it isn't one.
- **Stability:** consistent across sub-periods and small parameter perturbations,
  not driven by one regime or a handful of trades.

## Checklist

- [ ] All inputs are point-in-time; no restated data or survivorship in the
      universe.
- [ ] Signal acts on the next executable bar; no same-bar look-ahead.
- [ ] Transaction costs and realistic slippage modeled on every fill.
- [ ] Splits preserve time order (walk-forward), with purge/embargo around
      overlapping labels and an untouched final holdout.
- [ ] Metrics annualized correctly and reported net of costs, with a t-stat / CI
      on the Sharpe.
- [ ] Number of configurations tried is recorded and the result deflated for it.
- [ ] Beats buy-and-hold and null baselines; stable across sub-periods.

## Anti-patterns

- Random k-fold or shuffled splits on time-series data.
- Same-bar signal-and-execution; fills at unrealistic prices.
- Zero (or flat-token) transaction costs.
- Survivorship bias: backtesting today's index members over history.
- Tuning parameters on the test set, or reporting only the best of many runs.
- Quoting a headline Sharpe with no costs, no t-stat, and no baseline.

## Out of scope

- **Computing the returns/volatility series and avoiding look-ahead in features**
  → `financial-timeseries-analysis`.
- **Pricing, risk metrics, and the math conventions behind them** →
  `quantitative-finance`.
- **Reviewing an existing backtest's code for defects** → `quant-code-review`.
- **General Python structure, packaging, performance** → `python-development`.
