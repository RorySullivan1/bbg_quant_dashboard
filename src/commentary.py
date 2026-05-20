from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import LOOKBACK_YEARS, NEW_LAUNCH_DAYS
from .stats import corr_matrix, total_return, weekly_change


def build_highlights(
    meta: pd.DataFrame,
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    sharpe_z: pd.Series,
    as_of: date | None = None,
) -> list[dict]:
    cards: list[dict] = []
    as_of = as_of or date.today()

    if prices.empty or returns.empty:
        return [{
            "category": "info",
            "label": "Universe",
            "value": "—",
            "ticker": "",
            "name": "Select tickers and click Apply to generate highlights.",
            "sentiment": "neutral",
        }]

    name_lookup = meta.set_index("ticker")["name"].to_dict()

    def name_of(ticker: str) -> str:
        return name_lookup.get(ticker, ticker)

    tr = total_return(prices).dropna()
    if not tr.empty:
        best, worst = tr.idxmax(), tr.idxmin()
        cards.append({
            "category": "return",
            "label": f"Best total return ({LOOKBACK_YEARS}Y)",
            "value": f"{tr[best]:+.1%}",
            "ticker": best,
            "name": name_of(best),
            "sentiment": "positive",
        })
        cards.append({
            "category": "return",
            "label": f"Worst total return ({LOOKBACK_YEARS}Y)",
            "value": f"{tr[worst]:+.1%}",
            "ticker": worst,
            "name": name_of(worst),
            "sentiment": "negative",
        })

    wk = weekly_change(prices).dropna()
    if not wk.empty:
        up, down = wk.idxmax(), wk.idxmin()
        cards.append({
            "category": "move",
            "label": "Biggest 1-week move up",
            "value": f"{wk[up]:+.2%}",
            "ticker": up,
            "name": name_of(up),
            "sentiment": "positive",
        })
        cards.append({
            "category": "move",
            "label": "Biggest 1-week move down",
            "value": f"{wk[down]:+.2%}",
            "ticker": down,
            "name": name_of(down),
            "sentiment": "negative",
        })

    sz = sharpe_z.dropna()
    if not sz.empty:
        hot, cold = sz.idxmax(), sz.idxmin()
        cards.append({
            "category": "sharpe",
            "label": "Highest Sharpe z-score",
            "value": f"{sz[hot]:+.2f}",
            "ticker": hot,
            "name": name_of(hot),
            "sentiment": "positive",
        })
        cards.append({
            "category": "sharpe",
            "label": "Lowest Sharpe z-score",
            "value": f"{sz[cold]:+.2f}",
            "ticker": cold,
            "name": name_of(cold),
            "sentiment": "negative",
        })

    if returns.shape[1] >= 2:
        cm = corr_matrix(returns)
        upper = cm.where(np.triu(np.ones(cm.shape, dtype=bool), k=1))
        flat = upper.stack()
        if not flat.empty:
            (a_hi, b_hi), v_hi = flat.idxmax(), flat.max()
            (a_lo, b_lo), v_lo = flat.idxmin(), flat.min()
            cards.append({
                "category": "corr",
                "label": "Most correlated pair",
                "value": f"{v_hi:.2f}",
                "ticker": f"{a_hi} vs {b_hi}",
                "name": f"{name_of(a_hi)} vs {name_of(b_hi)}",
                "sentiment": "neutral",
            })
            cards.append({
                "category": "corr",
                "label": "Least correlated pair",
                "value": f"{v_lo:.2f}",
                "ticker": f"{a_lo} vs {b_lo}",
                "name": f"{name_of(a_lo)} vs {name_of(b_lo)}",
                "sentiment": "neutral",
            })

    cutoff = pd.Timestamp(as_of) - timedelta(days=NEW_LAUNCH_DAYS)
    recent = meta[meta["live_date"] >= cutoff]
    for _, row in recent.iterrows():
        cards.append({
            "category": "launch",
            "label": "Recently launched",
            "value": row["live_date"].date().isoformat(),
            "ticker": row["ticker"],
            "name": row["name"],
            "sentiment": "neutral",
        })

    return cards
