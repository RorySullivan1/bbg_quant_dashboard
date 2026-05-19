import numpy as np
import pandas as pd

from .config import SHARPE_WINDOW, SHARPE_ZSCORE_WINDOW, TRADING_DAYS_PER_YEAR


def daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change().dropna(how="all")


def cum_perf(prices: pd.DataFrame) -> pd.DataFrame:
    if prices.empty:
        return prices
    first = prices.bfill().iloc[0]
    return prices.divide(first).multiply(100)


def total_return(prices: pd.DataFrame) -> pd.Series:
    if prices.empty:
        return pd.Series(dtype=float)
    first = prices.bfill().iloc[0]
    last = prices.ffill().iloc[-1]
    return (last / first - 1).rename("total_return")


def weekly_change(prices: pd.DataFrame) -> pd.Series:
    if prices.empty or len(prices) < 6:
        return pd.Series(dtype=float)
    last = prices.ffill().iloc[-1]
    prior = prices.ffill().iloc[-6]
    return (last / prior - 1).rename("weekly_change")


def corr_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.corr()


def rolling_sharpe(
    returns: pd.DataFrame, window: int = SHARPE_WINDOW
) -> pd.DataFrame:
    mean = returns.rolling(window).mean() * TRADING_DAYS_PER_YEAR
    std = returns.rolling(window).std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    return mean.divide(std.replace(0, np.nan))


def sharpe_zscore(
    returns: pd.DataFrame,
    window: int = SHARPE_WINDOW,
    zscore_window: int = SHARPE_ZSCORE_WINDOW,
) -> pd.Series:
    sharpe = rolling_sharpe(returns, window=window)
    tail = sharpe.tail(zscore_window)
    mean = tail.mean()
    std = tail.std().replace(0, np.nan)
    current = sharpe.ffill().iloc[-1]
    return ((current - mean) / std).rename("sharpe_zscore")
