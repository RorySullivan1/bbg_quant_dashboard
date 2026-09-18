"""Tunable constants for the dashboard: windows, thresholds, paths, and tickers.

Values here are read at import by `src/stats/`, `src/layout/`, and
`src/bql_client.py`; nothing in this module computes or fetches.

Two conventions govern the ticker lists at the bottom of the file:

1. **They ride the single startup BQL fetch.** `BENCHMARK_TICKERS`,
   `FACTOR_TICKERS`, and `REGIME_TICKERS` are appended to the universe request
   rather than fetched separately, so adding a ticker costs no extra BQL call.
2. **They are excluded from ARP-universe views.** The all-catalog grid and the
   highlights cards reindex to the metadata tickers, which drops them; they
   surface only in the correlation, beta, factor, and regime views.

Because `bql_client` fetches only `px_last`, anything here described as a
"premium" is a total-return *spread*, not a true excess-of-risk-free premium.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

#: How far back the app **analyses**: every chart window, every `5Y` label, and
#: the slice `DashboardApp._analytics_window_start` hands each consumer.
LOOKBACK_YEARS = 5

#: How far back the app **fetches** (v0.9.22 #311). Longer than it analyses,
#: because the leaderboard's score z-scores a metric against its own rolling
#: history: at the 1Y window that is 252 (window) + 1260 (5y sample) = 1512
#: trading days, about six calendar years. Widening `LOOKBACK_YEARS` instead
#: would have turned every whole-lookback analytic on two other tabs into a
#: 6-year figure.
#:
#: The pair only means anything together, and the boundary between them is
#: `_analytics_window_start()`: everything reads the sliced frame except the
#: leaderboard's scorer, which is the one deliberate exception.
SCORE_HISTORY_YEARS = 6

NEW_LAUNCH_DAYS = 30
SHARPE_WINDOW = 252
SHARPE_ZSCORE_WINDOW = 252
TRADING_DAYS_PER_YEAR = 252
PERF_TABLE_YEARS = (1, 3, 5)

#: Trailing window (trading days, ~1 month) the leaderboard ranks over on load,
#: computed whole-catalog from the already-fetched prices. The Ranking window
#: toggle moves it live; this is only the default.
LEADERBOARD_WINDOW_DAYS = 21

#: How many indices each leaderboard column lists at the top and at the
#: bottom, so "top 3 / bottom 3" is spelled once, not in the builder and again
#: in the widget that draws the slots.
LEADERBOARD_ROWS = 3

#: Hard cap on the Multi-Strategy selection. Analysis over the selected set is
#: O(n²) in the number of picks, so the picker is bounded to keep it fast and
#: the heatmaps legible; a further pick is rejected with an error popup.
#: See `CheckboxMultiSelect(max_selected=...)`.
MAX_SELECTED_STRATEGIES = 25

# Short metric windows (trading days) for the Platform z-score views.
WEEK_WINDOW = 5
MONTH_WINDOW = 21
QUARTER_WINDOW = 63
HALF_YEAR_WINDOW = 126

#: Shared window options and day → label map, so the ranking-window toggle, the
#: sunburst Z-score control, and the Quantitative Z-Score window agree without
#: re-spelling the list at each widget.
SHORT_WINDOW_OPTIONS: list[tuple[str, int]] = [
    ("1W", WEEK_WINDOW),
    ("1M", MONTH_WINDOW),
    ("3M", QUARTER_WINDOW),
    ("6M", HALF_YEAR_WINDOW),
]
WINDOW_LABELS: dict[int, str] = {
    WEEK_WINDOW: "Past Week",
    MONTH_WINDOW: "Past Month",
    QUARTER_WINDOW: "Past Quarter",
    HALF_YEAR_WINDOW: "Past 6 Months",
}

# Quantitative-filter defaults (Multi-Strategy "Quantitative" filter).
VAR_CONFIDENCE = 0.95  # historical daily VaR confidence level
RSI_WINDOW = 14  # Wilder RSI lookback in trading days

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "indexdb.json"
WEEKLY_COMMENTARY_PATH = REPO_ROOT / "data" / "weekly_commentary.html"
#: The QIS Bulletin's commentary notes (#304): a JSON list of
#: `{"title", "date", "text"}`, newest rendered first. Replaces the single
#: `weekly_commentary.html` blob, which stays until nothing reads it (#308).
COMMENTARY_PATH = REPO_ROOT / "data" / "commentary.json"
PERFORMANCE_DISCLAIMER_PATH = REPO_ROOT / "data" / "performance_disclaimer.html"
LEGAL_DISCLOSURE_PATH = REPO_ROOT / "data" / "legal_disclosure.html"
TEMPLATES_DIR = REPO_ROOT / "data" / "templates"
LOGO_PATH = REPO_ROOT / "assets" / "logo.png"

#: On-disk parquet tier of the price cache, one file per `end` date.
CACHE_DIR = REPO_ROOT / "data" / ".cache"
#: How stale a same-day disk cache may be before it counts as a miss.
CACHE_TTL_HOURS = 12

#: Benchmarks the user added at runtime. A sibling of the catalog rather than a
#: file under `CACHE_DIR`: the cache is semantically deletable at any time and
#: user configuration is not. Gitignored, so one user's benchmarks are never
#: committed and shipped to everyone.
USER_BENCHMARKS_PATH = REPO_ROOT / "data" / "user_benchmarks.json"

#: Tickers per BQL request. The startup fetch is batched because a single
#: request for hundreds of tickers over a multi-year window risks BQL's
#: per-request row and wall-clock limits. Tune purely for throughput against
#: those limits: it is the per-ticker retry pass, not this size, that stops one
#: bad ticker blanking the load (batch-level isolation isolates nothing when the
#: universe fits in one batch).
BQL_BATCH_SIZE = 100
BQL_MAX_RETRIES = 2  # extra attempts per batch after the first (so up to 3 tries)
BQL_RETRY_BACKOFF_S = 1.0  # base backoff; attempt n waits BACKOFF * 2**n seconds

#: A user-added benchmark whose history starts more than this many days after
#: the lookback window opens is accepted but flagged — a partial series is
#: usable for correlation and beta, but the user should know the comparison does
#: not span the whole window rather than wondering why a chart starts late.
BENCHMARK_SHORT_HISTORY_DAYS = 30


@dataclass(frozen=True)
class CatalogField:
    """One column of the index catalog, as fed and as displayed.

    `sources` is the accepted JSON keys in preference order — the first is
    canonical and the rest are legacy aliases kept so a stale feed still loads
    (`load_metadata` warns rather than raising). `role` drives behaviour:
    `"tier"` fields form the classification hierarchy, `"attribute"` fields are
    filterable flat dimensions, `"date"` fields are coerced to timestamps, and
    `"text"` fields are free prose that is displayed but never filtered on.
    """

    key: str
    sources: tuple[str, ...]
    label: str
    role: str


#: The catalog contract in one place: every internal column, the JSON keys it
#: accepts, and the label it is shown under. Adding a source alias or changing a
#: display label is an edit here and nowhere else. Order fixes the metadata
#: frame's column order (after the derived `ticker`).
CATALOG_SCHEMA: tuple[CatalogField, ...] = (
    CatalogField("name", ("Name",), "Name", "text"),
    CatalogField("asset_class", ("AssetClass",), "Asset Class", "attribute"),
    CatalogField("family", ("Family", "IndexFamilyName"), "Family", "tier"),
    CatalogField("category", ("Category", "Theme"), "Category", "tier"),
    CatalogField("solution", ("Solution",), "Solution", "tier"),
    CatalogField("return_type", ("ReturnType",), "Return Type", "attribute"),
    CatalogField("live_date", ("LiveDate",), "Launch Date", "date"),
    CatalogField("currency", ("Currency",), "Currency", "attribute"),
    CatalogField("description", ("Description",), "Description", "text"),
)

#: The classification hierarchy, top tier → leaf. The framework names these
#: Class | Category | Family; the top tier is fed by the `Solution` column,
#: which is also what `UNIVERSE_SOLUTION_VALUES` filters on, so the internal key
#: stays `solution`. A feed that arrives keyed `Class` instead is one extra
#: alias on that field, not a rename.
CLASSIFICATION_TIERS: tuple[str, ...] = ("solution", "category", "family")

#: Which metadata fields each renderer shows, in display order. Field *keys*
#: only — every label comes from the schema via `field_label`, so relabelling a
#: column is a `CATALOG_SCHEMA` edit and nothing else. The tiers are splatted
#: from `CLASSIFICATION_TIERS` rather than respelled, so renaming a tier key
#: reaches every renderer without touching these tuples.
#:
#: Each tuple is named for the grid it actually feeds. Until #282 they were
#: named the other way round — `UNIVERSE_GRID_FIELDS` fed `PerfGrid` and
#: `SELECTED_GRID_FIELDS` fed the all-catalog table — so editing the
#: obviously-named constant changed the other grid and reviewed as correct.
PERF_GRID_FIELDS: tuple[str, ...] = ("name", "asset_class", *CLASSIFICATION_TIERS)
CATALOG_GRID_FIELDS: tuple[str, ...] = (
    "name",
    "asset_class",
    *CLASSIFICATION_TIERS,
    "live_date",
)
PROFILE_CARD_FIELDS: tuple[str, ...] = (
    "asset_class",
    "currency",
    "return_type",
    *CLASSIFICATION_TIERS,
    "live_date",
)
#: Fields joined with " · " on a New-Launch card's meta line.
LAUNCH_CARD_META_FIELDS: tuple[str, ...] = ("asset_class", "category", "currency")


def catalog_field(key: str) -> CatalogField:
    """The schema entry for an internal column key.

    Scans `CATALOG_SCHEMA` on each call rather than a dict built at import, so
    a test that swaps the schema to check relabelling is seen by every consumer.
    Nine fields, read at render time — caching would buy nothing but a stale
    lookup.
    """
    for field in CATALOG_SCHEMA:
        if field.key == key:
            return field
    raise KeyError(f"No catalog field named {key!r}")


def field_label(key: str) -> str:
    """The display label for an internal column key."""
    return catalog_field(key).label


def tier_fields() -> tuple[CatalogField, ...]:
    """The classification-tier fields, ordered top tier → leaf."""
    return tuple(catalog_field(key) for key in CLASSIFICATION_TIERS)


def filterable_fields() -> tuple[CatalogField, ...]:
    """The fields `apply_filters` accepts a value list for, in schema order.

    Tiers and attributes; dates take their own min/max arguments and free text
    is not a filter dimension.
    """
    return tuple(f for f in CATALOG_SCHEMA if f.role in ("tier", "attribute"))


#: The Platform sunburst's rings above the ticker leaves, outermost grouping
#: first. This is today's picture — asset class → category → ticker — and the
#: renderer walks it rather than naming the levels, so switching to the full
#: framework hierarchy (`CLASSIFICATION_TIERS`) is a config flip with no code
#: edit. Any number of levels works; the leaf ring is always the ticker.
SUNBURST_LEVELS: tuple[str, ...] = ("asset_class", "category")


def sunburst_levels() -> tuple[str, ...]:
    """`SUNBURST_LEVELS`, validated against the schema.

    Read through a call so a reconfigured hierarchy reaches both the frame
    builder and the renderer. The validation earns its keep because the
    renderer fills a missing level with "Other": a mistyped level would
    otherwise render as one undifferentiated ring rather than fail.
    """
    for key in SUNBURST_LEVELS:
        catalog_field(key)  # raises KeyError naming the offending level
    return SUNBURST_LEVELS


#: The stats windows the all-catalog grid can offer, widest label first in
#: display order, as (label, years). Years are floats because the windows are
#: not all whole years — `ann_return` / `ann_volatility` / `max_drawdown` all
#: take a float, so a half-year window computes correctly; only the *label*
#: needed somewhere to live, which is here rather than as `f"{y}Y"` at the
#: point of use.
STAT_WINDOWS: tuple[tuple[str, float], ...] = (
    ("6M", 0.5),
    ("1Y", 1.0),
    ("3Y", 3.0),
    ("5Y", 5.0),
    ("10Y", 10.0),
    ("15Y", 15.0),
)

#: The window shown on load.
UNIVERSE_GRID_DEFAULT_WINDOW: str = "1Y"


def stat_windows() -> tuple[tuple[str, float], ...]:
    """The windows the fetched price history can actually support.

    `LOOKBACK_YEARS` bounds how far back prices are pulled, so a longer window
    has nothing to measure: `_has_enough_history` blanks every row and the
    column renders as a full column of dashes. That reads as a broken
    dashboard rather than as a pending feature, so those windows are not
    offered at all.

    Deriving the offered set from the fetch — rather than listing the windows
    a desk eventually wants — means widening `LOOKBACK_YEARS` to full history
    makes the longer windows appear on their own, with no UI change and
    nothing to remember.
    """
    return tuple(
        (label, years) for label, years in STAT_WINDOWS if years <= LOOKBACK_YEARS
    )


def stat_window_years(label: str) -> float:
    """The year count behind a window label, e.g. `"6M"` -> `0.5`."""
    for name, years in STAT_WINDOWS:
        if name == label:
            return years
    raise KeyError(f"No stats window named {label!r}")


def stat_window_label(years: float) -> str:
    """The display label for a year count, e.g. `0.5` -> `"6M"`.

    Falls back to `"{years}Y"` for a window not in `STAT_WINDOWS`, so callers
    passing their own year tuples (the selected-strategy perf grid does) keep
    working unchanged.
    """
    for label, value in STAT_WINDOWS:
        if value == years:
            return label
    return f"{years}Y"


def universe_grid_default_window() -> str:
    """`UNIVERSE_GRID_DEFAULT_WINDOW`, validated against what is offered.

    A default naming an unavailable window would render a grid whose statistics
    are all dashes, which reads as "the data didn't load" rather than as a
    misconfiguration.
    """
    offered = [label for label, _ in stat_windows()]
    if UNIVERSE_GRID_DEFAULT_WINDOW not in offered:
        raise ValueError(
            f"UNIVERSE_GRID_DEFAULT_WINDOW={UNIVERSE_GRID_DEFAULT_WINDOW!r} is not "
            f"among the windows the {LOOKBACK_YEARS}-year price history supports "
            f"({offered})"
        )
    return UNIVERSE_GRID_DEFAULT_WINDOW


#: Every catalog field the all-catalog grid can group by, **in nesting order**:
#: whichever subset the user picks, the grid nests them in this sequence. The
#: order is the hierarchy's own, broadest first — asset class sits above the
#: three classification tiers. Ticking order never changes the nesting, so the
#: table reads the same however the user got there (#273).
UNIVERSE_GRID_GROUPABLE_FIELDS: tuple[str, ...] = ("asset_class", *CLASSIFICATION_TIERS)

#: Which of those are grouped on load. `()` renders a flat, ungrouped table.
UNIVERSE_GRID_GROUP_FIELDS: tuple[str, ...] = CLASSIFICATION_TIERS


def universe_grid_groupable_fields() -> tuple[str, ...]:
    """`UNIVERSE_GRID_GROUPABLE_FIELDS`, validated against the schema."""
    for key in UNIVERSE_GRID_GROUPABLE_FIELDS:
        catalog_field(key)  # raises KeyError naming the offending field
    return UNIVERSE_GRID_GROUPABLE_FIELDS


def universe_grid_group_fields(
    selected: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """The grouping fields to use, in nesting order, validated.

    `selected` is the user's current choice; omitted, the configured default is
    used. The return is always ordered by `UNIVERSE_GRID_GROUPABLE_FIELDS`, not
    by the caller's order — nesting is the hierarchy's, never the order boxes
    were ticked.

    Read through a call so a regrouped hierarchy reaches both the frame's row
    ordering and the widget's group configuration, which have to agree: the
    table groups *consecutive* rows only, so a field that orders the frame but
    never reaches the widget (or the reverse) fragments the groups rather than
    failing.
    """
    chosen = UNIVERSE_GRID_GROUP_FIELDS if selected is None else selected
    unknown = set(chosen) - set(UNIVERSE_GRID_GROUPABLE_FIELDS)
    if unknown:
        raise KeyError(
            f"Not groupable in the catalog grid: {sorted(unknown)}. "
            f"Groupable fields are {list(UNIVERSE_GRID_GROUPABLE_FIELDS)}."
        )
    for key in chosen:
        catalog_field(key)  # raises KeyError naming the offending field
    return tuple(k for k in UNIVERSE_GRID_GROUPABLE_FIELDS if k in set(chosen))


def filter_dimensions() -> tuple[CatalogField, ...]:
    """The filterable fields in filter-panel order: tiers broadest-first, then
    the flat attributes in schema order.

    `filterable_fields` reports schema order, which interleaves the tiers with
    the attributes because the frame's column order is not the order a user
    drills down in. The panel wants the hierarchy read top → leaf first, so the
    resequencing lives here rather than as a sort key at the call site.
    """
    tiers = tier_fields()
    return (*tiers, *(f for f in filterable_fields() if f.role != "tier"))


#: Solution values making up the dashboard universe, compared case-insensitively
#: against the metadata `solution` column. Both spellings of Alternative Risk
#: Premia are kept so the filter survives a future JSON rename, and "risk
#: management" is forward-compatible (no records carry it yet). Plain "Beta"
#: stays excluded.
UNIVERSE_SOLUTION_VALUES = frozenset(
    {"arp", "alternative risk premia", "smart beta", "risk management"}
)

#: Curated benchmarks for the Rolling Correlation and Rolling Beta views.
BENCHMARK_TICKERS: list[str] = [
    "SPTR Index",  # S&P 500 Total Return
    "SPXFP Index",  # S&P 500 (equity factor-leg reference)
    "MXWO Index",  # MSCI World
    "LBUSTRUU Index",  # Bloomberg US Aggregate
    "BCOM Index",  # Bloomberg Commodity
    "BMADM64 Index",  # Bloomberg 60/40
    "BSLRP Index",  # Bloomberg systematic risk premia
    "BSLMARP Index",  # Bloomberg multi-asset risk premia
    "BSLXAC Index",  # Bloomberg cross-asset carry
    "BSLXACV Index",  # Bloomberg cross-asset carry/value
    "BSLXAV Index",  # Bloomberg cross-asset value
    "BSLXAT Index",  # Bloomberg cross-asset trend (also TREND_TICKER)
]
DEFAULT_BENCHMARK = "SPTR Index"

# Factor proxies for the Platform factor-beta scatter:
#   equity risk premium ≈ equity TR return − short-rate TR return
#   term premium        ≈ long-Treasury TR return − short-rate TR return
# The equity leg reuses a benchmark, so only the rate/bond proxies and the trend
# index are new tickers — hence FACTOR_TICKERS lists just those three.
EQUITY_FACTOR_TICKER = "SPXFP Index"  # equity proxy (also in BENCHMARK_TICKERS)
LONG_TREASURY_TICKER = "LUTLTRUU Index"  # Bloomberg US Long Treasury TR
SHORT_RATE_TICKER = "LD12TRUU Index"  # Bloomberg US Treasury 1–3M Bills TR
#: The scatter's 3D z-axis is each strategy's β to this index's returns
#: directly, not to a short-rate spread like the two premia above.
TREND_TICKER = "BSLXAT Index"  # Bloomberg cross-asset trend
FACTOR_TICKERS: list[str] = [LONG_TREASURY_TICKER, SHORT_RATE_TICKER, TREND_TICKER]

# Indicator tickers for the Platform "Regime Analysis" section.
VIX_TICKER = "VIX Index"
#: Regional risk-free overnight rates for the Rate-level regime's region dropdown.
RATE_LEVEL_TICKERS: list[tuple[str, str]] = [
    ("US (FEDL01)", "FEDL01 Index"),  # US fed funds effective rate
    ("EU (EONIA)", "EONIA Index"),  # euro overnight rate
    ("JP (MUTKCALM)", "MUTKCALM Index"),  # Japan call rate
]
#: Mock shapes for indicator tickers whose off-terminal series must be an
#: absolute *level* rather than a compounding price, so the regime buckets
#: actually partition the mock. Maps ticker -> (mean, vol, lo, hi) for a clipped
#: mean-reverting level; see `MockPriceSource` in `src/price_source.py`.
LEVEL_INDICATOR_MOCK: dict[str, tuple[float, float, float, float]] = {
    VIX_TICKER: (18.0, 1.5, 9.0, 60.0),  # VIX-like, hovers ~18
    **{t: (2.0, 0.10, 0.0, 8.0) for _, t in RATE_LEVEL_TICKERS},  # short rates
}

_REGIME_INF = float("inf")


@dataclass(frozen=True)
class LevelRegime:
    """A regime bucketed on the indicator's **raw daily level**.

    `buckets` are half-open ``[low, high)`` ``(label, low, high)`` triples using
    ±inf for the open ends, so they partition the whole real line — the bucket
    dropdown offers them verbatim and no quantile is computed.
    """

    ticker: str
    buckets: tuple[tuple[str, float, float], ...]

    def tickers(self) -> tuple[str, ...]:
        """Indicator tickers this regime needs fetched."""
        return (self.ticker,)


@dataclass(frozen=True)
class TercileRegime:
    """A regime bucketed on **live terciles** of a computed indicator series.

    The series is split at its 1/3 and 2/3 quantiles over the lookback, so
    `bucket_labels` are ``(display, key)`` pairs rather than bounds. `kind`
    picks the series: ``"autocorr"`` takes the rolling return-autocorrelation of
    the chosen ticker over `autocorr_window`; ``"level"`` takes the chosen
    ticker's raw level.

    The indicator source is a dropdown, populated either from a literal
    `selector` of ``(label, ticker)`` pairs or, via `selector_source`, from the
    live benchmark registry at render time — a benchmark added at runtime has to
    appear in the Trend picker too, so that list cannot be frozen at import.
    """

    kind: Literal["autocorr", "level"]
    bucket_labels: tuple[tuple[str, str], ...]
    selector: tuple[tuple[str, str], ...] = ()
    selector_source: str | None = None
    autocorr_window: int | None = None

    def __post_init__(self) -> None:
        # An autocorr regime with no window has no series at all; catching it
        # here beats a consumer-side fallback that silently invents one.
        if self.kind == "autocorr" and self.autocorr_window is None:
            raise ValueError("an autocorr regime needs an autocorr_window")

    def tickers(self) -> tuple[str, ...]:
        """Indicator tickers this regime needs fetched.

        Empty for a registry-sourced regime: those tickers are benchmarks, which
        ride the universe fetch already.
        """
        return tuple(ticker for _, ticker in self.selector)


#: Either regime shape. Consumers switch on `isinstance`, not a mode string.
RegimeSpec = LevelRegime | TercileRegime

#: Regime label -> spec. See `platform.regime_bucket_options` /
#: `_regime_indicator` / `_resolve_regime_bucket` / `_regime_selector_options`
#: for the consumer set.
REGIME_SPECS: dict[str, RegimeSpec] = {
    "Volatility": LevelRegime(
        ticker=VIX_TICKER,
        buckets=(
            ("VIX < 15", -_REGIME_INF, 15.0),
            ("15 ≤ VIX < 25", 15.0, 25.0),
            ("VIX ≥ 25", 25.0, _REGIME_INF),
        ),
    ),
    "Trend": TercileRegime(
        kind="autocorr",
        selector_source="benchmarks",
        autocorr_window=21,  # rolling window for benchmark-return autocorrelation
        bucket_labels=(
            ("Low (mean-reverting)", "low"),
            ("Middle", "mid"),
            ("High (trending)", "high"),
        ),
    ),
    "Rate-level": TercileRegime(
        kind="level",
        selector=tuple(RATE_LEVEL_TICKERS),
        bucket_labels=(
            ("Low rates", "low"),
            ("Middle", "mid"),
            ("High rates", "high"),
        ),
    ),
}

#: Every indicator ticker the regimes need, deduped and order-preserving —
#: derived from the specs so a new regime cannot be added without its ticker
#: joining the startup fetch.
REGIME_TICKERS: list[str] = list(
    dict.fromkeys(t for spec in REGIME_SPECS.values() for t in spec.tickers())
)
