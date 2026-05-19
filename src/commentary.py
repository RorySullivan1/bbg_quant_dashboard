from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import NEW_LAUNCH_DAYS
from .stats import corr_matrix, total_return, weekly_change


def build_commentary(
    meta: pd.DataFrame,
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    sharpe_z: pd.Series,
    as_of: date | None = None,
) -> list[str]:
    bullets: list[str] = []
    as_of = as_of or date.today()

    if prices.empty or returns.empty:
        return ["Select at least two tickers and click Apply to generate commentary."]

    name_lookup = meta.set_index("ticker")["name"].to_dict()

    def label(ticker: str) -> str:
        return f"{name_lookup.get(ticker, ticker)} ({ticker})"

    tr = total_return(prices).dropna()
    if not tr.empty:
        best, worst = tr.idxmax(), tr.idxmin()
        bullets.append(
            f"Best total return over the window: {label(best)} at {tr[best]:.1%}."
        )
        bullets.append(
            f"Worst total return over the window: {label(worst)} at {tr[worst]:.1%}."
        )

    wk = weekly_change(prices).dropna()
    if not wk.empty:
        up, down = wk.idxmax(), wk.idxmin()
        bullets.append(
            f"Biggest 1-week move higher: {label(up)} at {wk[up]:+.2%}."
        )
        bullets.append(
            f"Biggest 1-week move lower: {label(down)} at {wk[down]:+.2%}."
        )

    sz = sharpe_z.dropna()
    if not sz.empty:
        hot, cold = sz.idxmax(), sz.idxmin()
        bullets.append(
            f"Highest Sharpe z-score vs own history: {label(hot)} at {sz[hot]:+.2f}."
        )
        bullets.append(
            f"Lowest Sharpe z-score vs own history: {label(cold)} at {sz[cold]:+.2f}."
        )

    if returns.shape[1] >= 2:
        cm = corr_matrix(returns)
        upper = cm.where(np.triu(np.ones(cm.shape, dtype=bool), k=1))
        flat = upper.stack()
        if not flat.empty:
            (a_hi, b_hi), v_hi = flat.idxmax(), flat.max()
            (a_lo, b_lo), v_lo = flat.idxmin(), flat.min()
            bullets.append(
                f"Most correlated pair: {label(a_hi)} and {label(b_hi)} at {v_hi:.2f}."
            )
            bullets.append(
                f"Least correlated pair: {label(a_lo)} and {label(b_lo)} at {v_lo:.2f}."
            )

    cutoff = pd.Timestamp(as_of) - timedelta(days=NEW_LAUNCH_DAYS)
    recent = meta[meta["live_date"] >= cutoff]
    for _, row in recent.iterrows():
        bullets.append(
            f"Recently launched: {row['name']} ({row['ticker']}) went live on "
            f"{row['live_date'].date().isoformat()}."
        )

    return bullets
