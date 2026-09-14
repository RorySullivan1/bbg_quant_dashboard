"""Where prices come from: BQL on a terminal, a deterministic mock off it (#222).

`fetch_prices` used to decide between the two inline and report which one it
used as a bare string, while the mock's two rejection seams were module globals
that tests mutated and had to remember to clear. Both are objects here: which
source you are talking to is a value you can pass, and how the mock behaves is
that instance's state.

**The contract both sources honour** — the reason the mock is worth having at
all — is failure shape, not just output shape:

- a wide frame, date index, one column per *requested* ticker, in request order;
- a ticker that does not resolve among healthy peers degrades to an all-NaN
  column with a warning (#187), so a few bad tickers cannot blank the load;
- a request where **nothing** resolves raises `TickersUnresolved` (#193), which
  is deliberately distinct from a transport failure — adding a single benchmark
  has no healthy peers to degrade against, and "your ticker is wrong" is a very
  different message from "the BQL session dropped".

`MockPriceSource` mirrors that contract rather than BQL's internals; its
`unresolvable` / `first_trade` attributes are how a test drives the two failure
modes without touching the live path.
"""

from __future__ import annotations

import time
import warnings
from datetime import date
from typing import Protocol

import numpy as np
import pandas as pd

from .config import (
    BQL_BATCH_SIZE,
    BQL_MAX_RETRIES,
    BQL_RETRY_BACKOFF_S,
    LEVEL_INDICATOR_MOCK,
)

try:
    import bql  # type: ignore

    HAS_BQL = True
except Exception:
    HAS_BQL = False


BQL_FIELD_KEY = "px_last"


class TickersUnresolved(RuntimeError):
    """No ticker in the request resolved.

    Distinct from a transport or session failure, which is what every *other*
    exception out of a fetch means. Callers that add a single ticker need the
    difference: a one-ticker request has no healthy peers to degrade against,
    so the per-ticker isolation cannot turn a bad ticker into a NaN column — it
    comes back as this. Subclasses ``RuntimeError`` so existing handlers and
    tests are unaffected.
    """


class PriceSource(Protocol):
    """A thing that can produce px_last for tickers over a window."""

    #: What `fetch_prices` reports as the request's source ("bql" / "mock").
    name: str

    def fetch(self, tickers: list[str], start: date, end: date) -> pd.DataFrame: ...


def _chunked(seq: list[str], size: int) -> list[list[str]]:
    """Split ``seq`` into consecutive chunks of at most ``size`` items."""
    size = max(1, size)
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _pick_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = list(df.columns)
    lower = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand in df.columns:
            return cand
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def _reshape_bql_response(
    raw: pd.DataFrame | None,
    batch: list[str],
    start: date,
    end: date,
) -> pd.DataFrame:
    """Pivot one batch's long-form BQL response into a wide date×ticker frame.

    Raises ``RuntimeError`` on an empty response or unlocatable columns so the
    caller can retry the batch or degrade it to NaN columns. The ID column is
    cast to ``category`` before the pivot — a per-row string label over a
    multi-year daily response is a large object-dtype column, and categorizing
    it shrinks the pivot's transient memory.
    """
    if raw is None or raw.empty:
        raise RuntimeError(
            f"BQL returned no rows for {len(batch)} tickers "
            f"({start.isoformat()} → {end.isoformat()}). "
            "Check that the tickers include the ' Index' suffix and resolve on "
            "the terminal."
        )

    df = raw.reset_index()
    df.columns = [str(c) for c in df.columns]

    id_col = _pick_column(df, ["ID", "id", "Security", "security", "TICKER", "ticker"])
    date_col = _pick_column(df, ["DATE", "Date", "date", "AS_OF_DATE", "as_of_date"])
    value_col = _pick_column(
        df,
        [BQL_FIELD_KEY, "px_last", "PX_LAST", "VALUE", "value", "Value"],
    )

    if id_col is None or date_col is None or value_col is None:
        raise RuntimeError(
            f"Could not locate ID/DATE/value columns in BQL response. "
            f"Available columns: {list(df.columns)}. "
            f"Raw shape: {raw.shape}, index: {list(raw.index.names)}."
        )

    df[id_col] = df[id_col].astype("category")
    wide = df.pivot(index=date_col, columns=id_col, values=value_col)
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


class BqlPriceSource:
    """The live path: one batched BQL request per chunk of tickers.

    `service_factory` builds the `bql.Service` (deferred to the first fetch, so
    constructing the source off a terminal is harmless); a test injects a stub
    instead of monkeypatching the module. The batching knobs default to the
    `config` constants.
    """

    name = "bql"

    def __init__(
        self,
        service_factory=None,
        *,
        batch_size: int = BQL_BATCH_SIZE,
        max_retries: int = BQL_MAX_RETRIES,
        backoff_s: float = BQL_RETRY_BACKOFF_S,
    ) -> None:
        self._service_factory = service_factory or (lambda: bql.Service())
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.backoff_s = backoff_s

    def fetch(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        """Batched whole-universe px_last fetch (one request per ticker batch)."""
        bq = self._service_factory()
        px = bq.data.px_last(
            dates=bq.func.range(start.isoformat(), end.isoformat()),
            fill="prev",
        )

        def fetch_batch(batch: list[str], s: date, e: date) -> pd.DataFrame:
            response = bq.execute(bql.Request(batch, {BQL_FIELD_KEY: px}))
            return _reshape_bql_response(response[0].df(), batch, s, e)

        return self.assemble_batches(tickers, start, end, fetch_batch)

    def fetch_batch_with_retry(
        self,
        batch: list[str],
        start: date,
        end: date,
        fetch_batch,
        *,
        retries: int | None = None,
        backoff: float | None = None,
    ) -> pd.DataFrame:
        """Call ``fetch_batch(batch, start, end)`` with bounded exponential backoff.

        Retries transient BQL failures (network blips, momentary server limits)
        up to ``retries`` extra times; re-raises the last error if they all fail
        so the batch can be degraded to NaN columns by the caller.
        """
        retries = self.max_retries if retries is None else retries
        backoff = self.backoff_s if backoff is None else backoff
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return fetch_batch(batch, start, end)
            except Exception as exc:  # noqa: BLE001 — retry any BQL failure
                last_exc = exc
                if attempt < retries and backoff > 0:
                    time.sleep(backoff * (2**attempt))
        assert last_exc is not None
        raise last_exc

    def salvage_batch(
        self,
        batch: list[str],
        start: date,
        end: date,
        fetch_batch,
    ) -> tuple[list[pd.DataFrame], list[str]]:
        """Re-fetch a failed batch's tickers one at a time.

        A batch fails as a unit, so a single unresolvable ticker would otherwise
        take every ticker beside it down. Fetching them individually narrows the
        blast radius to the tickers that are actually bad.

        Each ticker gets a *single* attempt (``retries=0``): the batch has
        already exhausted the retry ladder, so repeating it per ticker would
        multiply an already-slow failure path by the batch size for no signal.

        Returns ``(frames, failed)`` — the single-ticker frames that resolved,
        and the tickers the caller should degrade to NaN columns.
        """
        frames: list[pd.DataFrame] = []
        failed: list[str] = []
        for ticker in batch:
            try:
                frames.append(
                    self.fetch_batch_with_retry(
                        [ticker], start, end, fetch_batch, retries=0
                    )
                )
            except Exception:  # noqa: BLE001 — one bad ticker shouldn't fail peers
                failed.append(ticker)
        return frames, failed

    def assemble_batches(
        self,
        tickers: list[str],
        start: date,
        end: date,
        fetch_batch,
        *,
        batch_size: int | None = None,
    ) -> pd.DataFrame:
        """Fetch ``tickers`` in batches via ``fetch_batch``, isolating failures.

        Each batch of ``batch_size`` tickers is fetched (with retry)
        independently. A batch that still fails is **re-fetched one ticker at a
        time** so only the genuinely unresolvable tickers degrade to NaN columns
        — warned, not fatal. Without that per-ticker pass the isolation is only
        as fine-grained as the batch, which is no isolation at all whenever the
        universe fits in a single batch: one bad ticker would blank the whole
        dashboard. Only when **every** ticker fails, individually, does this
        raise. The surviving frames are concatenated and reindexed to the full
        requested ticker list.

        The per-ticker sweep runs only for a batch that already failed, so the
        healthy path still costs exactly one request per batch.
        """
        batch_size = self.batch_size if batch_size is None else batch_size
        frames: list[pd.DataFrame] = []
        failed: list[str] = []
        for batch in _chunked(tickers, batch_size):
            try:
                frames.append(
                    self.fetch_batch_with_retry(batch, start, end, fetch_batch)
                )
            except Exception as exc:  # noqa: BLE001 — one bad batch shouldn't fail all
                if len(batch) == 1:
                    # Already at ticker granularity — nothing left to narrow.
                    failed.extend(batch)
                    continue
                warnings.warn(
                    f"BQL batch of {len(batch)} tickers failed after retries "
                    f"({exc}); re-fetching its tickers individually. "
                    f"Sample: {batch[:5]}.",
                    stacklevel=2,
                )
                recovered, lost = self.salvage_batch(batch, start, end, fetch_batch)
                frames.extend(recovered)
                failed.extend(lost)

        if not frames:
            raise TickersUnresolved(
                f"Every BQL request failed for {len(tickers)} tickers "
                f"({start.isoformat()} → {end.isoformat()}) — batched, then "
                "retried one ticker at a time. Check the terminal session and "
                "that tickers include the ' Index' suffix."
            )
        if failed:
            warnings.warn(
                f"{len(failed)} of {len(tickers)} tickers could not be fetched "
                f"and are NaN in the result (e.g. {failed[:5]}).",
                stacklevel=2,
            )

        combined = frames[0] if len(frames) == 1 else pd.concat(frames, axis=1)
        combined = combined.sort_index()
        aligned = combined.reindex(columns=tickers)
        if aligned.dropna(how="all", axis=1).empty:
            raise RuntimeError(
                f"BQL response columns {list(combined.columns)[:5]}"
                f"{'…' if len(combined.columns) > 5 else ''} did not match any "
                f"requested ticker (sample requested: {tickers[:5]}). "
                "The reindex produced an all-NaN frame."
            )
        return aligned


class MockPriceSource:
    """The off-terminal path: deterministic synthetic prices per ticker.

    `unresolvable` and `first_trade` are the two seams that let a test drive the
    live contract's failure modes — a ticker that does not resolve at all, and
    one that resolves but has no history before a date. Both default to empty,
    which is always the case in the app, and then every ticker resolves over the
    full window.
    """

    name = "mock"

    def __init__(
        self,
        *,
        unresolvable: set[str] | None = None,
        first_trade: dict[str, date] | None = None,
    ) -> None:
        #: Tickers that do not resolve at all — a wrong ticker.
        self.unresolvable: set[str] = set(unresolvable or ())
        #: Ticker -> first date with data. The ticker resolves but has no
        #: history before that date (a security that launched mid-window, or a
        #: stale one), so earlier rows are NaN.
        self.first_trade: dict[str, date] = dict(first_trade or {})

    def fetch(self, tickers: list[str], start: date, end: date) -> pd.DataFrame:
        """Deterministic synthetic prices, one column per ticker.

        Mirrors the *contract* of the live path rather than its internals: a
        ticker that doesn't resolve comes back as an all-NaN column (warned, not
        fatal) so the rest of the frame still loads, and only a request where
        **nothing** resolves raises.
        """
        idx = pd.bdate_range(start=start, end=end)
        resolved = [t for t in tickers if t not in self.unresolvable]
        unresolved = [t for t in tickers if t in self.unresolvable]

        if tickers and not resolved:
            # Matches `assemble_batches`' terminal raise: a request where
            # nothing resolves is loud, never a silently all-NaN dashboard.
            raise TickersUnresolved(
                f"Mock resolved none of {len(tickers)} tickers "
                f"({start.isoformat()} → {end.isoformat()})."
            )
        if unresolved:
            warnings.warn(
                f"{len(unresolved)} of {len(tickers)} tickers did not resolve in "
                f"the mock and are NaN in the result (e.g. {unresolved[:5]}).",
                stacklevel=2,
            )

        out = pd.DataFrame(index=idx)
        for ticker in resolved:
            rng = np.random.default_rng(abs(hash(ticker)) % (2**32))
            if ticker in LEVEL_INDICATOR_MOCK:
                # Mean-reverting absolute *level* (not a compounding price) so
                # the regime buckets partition the off-terminal mock. Per
                # indicator (mean, vol, lo, hi): VIX hovers ~18 clipped [9, 60];
                # short rates ~2.0.
                mean, vol, lo, hi = LEVEL_INDICATOR_MOCK[ticker]
                level = mean
                vals = np.empty(len(idx))
                for t in range(len(idx)):
                    level += 0.05 * (mean - level) + rng.normal(0.0, vol)
                    level = min(max(level, lo), hi)
                    vals[t] = level
                out[ticker] = vals
                continue
            drift = rng.uniform(0.02, 0.10) / 252
            vol = rng.uniform(0.08, 0.30) / np.sqrt(252)
            steps = rng.normal(loc=drift, scale=vol, size=len(idx))
            out[ticker] = 100 * np.exp(np.cumsum(steps))

        # A ticker that launched mid-window resolves but has no data before its
        # first trade date — NaN there, not a shorter frame, matching how BQL
        # returns a security with no history at the start of the range.
        for ticker, first in self.first_trade.items():
            if ticker in out.columns:
                out.loc[out.index < pd.Timestamp(first), ticker] = np.nan

        # Unresolved tickers come back as all-NaN columns, in requested order.
        out = out.reindex(columns=list(tickers))
        out.index.name = "DATE"
        return out


def default_price_source() -> PriceSource:
    """BQL when the library imported, the mock otherwise — today's fallback."""
    return BqlPriceSource() if HAS_BQL else MockPriceSource()
