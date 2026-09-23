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

import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

#: How far back the app **analyses**: every chart window, every `10Y` label,
#: the deepest window `stat_windows()` offers, and the slice
#: `DashboardApp._analytics_window_start` hands each consumer.
#:
#: 10 since v0.9.34 (#361), up from 5. It is the deepest window the catalog's
#: own strategies can fill: the three BSLX indices launched in mid-2016, so a
#: `15Y` window would be a column of dashes for every QIS strategy and
#: populated only by the beta benchmarks beside them.
LOOKBACK_YEARS = 10

#: (How far back the app **fetches** is `score_history_years()`, further down
#: beside `stat_windows()` — the window set it is derived from. The pair only
#: means anything together, and the boundary between them is
#: `_analytics_window_start()`: everything reads the sliced frame except the
#: scorers, which are the deliberate exceptions.)

NEW_LAUNCH_DAYS = 30
SHARPE_WINDOW = 252
SHARPE_ZSCORE_WINDOW = 252
TRADING_DAYS_PER_YEAR = 252
PERF_TABLE_YEARS = (1, 3, 5)

#: How long a sample **every** score is standardized against, in years of the
#: metric's own rolling history. `score_history_years()` sizes the fetch so
#: this is available at the deepest window either board offers (#310, #311).
#:
#: **Its own number since v0.9.34 (#361), not `LOOKBACK_YEARS`.** The two were
#: one constant while both were 5, and #361 widened the analysis to 10 years
#: without wanting a 10-year sample: a score standardized against ten years is
#: a different statistic, and the half-sample floor below would then have
#: demanded ~22 years of history to rank at the deepest window — more than any
#: strategy in the catalog has. So the sample stays five years and the
#: lookback moves on its own. What the two boards share is *this* constant,
#: which is what keeps a reading comparable between them (#324).
SCORE_SAMPLE_YEARS = 5

#: The same sample in trading days — what the scorers are actually handed.
#: (Named `LEADERBOARD_SCORE_SAMPLE_DAYS` until #324, when it stopped being
#: only the leaderboard's.)
SCORE_SAMPLE_DAYS = SCORE_SAMPLE_YEARS * TRADING_DAYS_PER_YEAR

#: Below this many rolling observations the catalog's ranking column renders a
#: dash instead of a score, and sorts to the bottom with the other blanks.
#:
#: Half the target sample. The header says `5Y Z-Score`, so an index that can
#: only offer two years should say nothing rather than quietly standardize
#: against two and be read as five — the same reasoning that has
#: `_has_enough_history` blank a whole performance block. Half is the point
#: where a sample stops being a short five years and starts being a different
#: statistic; it is a judgement, and it is one number to move.
#:
#: Expected effect, not a regression: at the `10Y` window an index needs about
#: 12.5 years of history to score at all — the window plus half the sample.
#:
#: The leaderboard deliberately does not take this floor — it already drops
#: NaN and infinite readings before ranking, and changing what its board shows
#: was out of scope for #324.
CATALOG_SCORE_MIN_SAMPLE_DAYS = SCORE_SAMPLE_DAYS // 2

#: The metrics the app ranks by, in display order, as (metric key, display
#: label). One set for both boards (#328): the Leaderboard's four columns and
#: the catalog table's ranking column are the same kind of number — a metric
#: z-scored against `SCORE_SAMPLE_DAYS` of its own rolling history — so a
#: reader should be able to carry a reading from one to the other.
#:
#: The catalog's chips used to offer Sharpe / Sortino / Return / **Vol**, which
#: was not just a different set. The ranking column is painted on a symmetric
#: diverging ramp — red below zero, green above — and sorted descending, and
#: both say *higher is better*. That is true of these four and false of
#: volatility: an index two standard deviations above its own vol history
#: rendered bright green at the top of the table, which reads as a
#: commendation. Vol is still available to the sunburst and the Quantitative
#: filter, where nothing claims a direction for it.
#:
#: **Bounded by what can be scored.** Every key here needs a rolling series in
#: `stats.rolling._ROLLING_METRICS` or `rolling_metric_zscore` raises — a fifth
#: metric added here without one fails in CI rather than on a user's click.
#: (Lived in `commentary.py` as `LEADERBOARD_METRICS` until #328, where only
#: the board could reach it.)
RANKABLE_METRICS: tuple[tuple[str, str], ...] = (
    ("return", "Return"),
    ("sharpe", "Sharpe"),
    ("calmar", "Calmar"),
    ("sortino", "Sortino"),
)

#: The metric the catalog's ranking column is scored on before anyone touches
#: a chip. One of `RANKABLE_METRICS`, validated by `rankable_metric_chips`.
DEFAULT_RANKING_METRIC: str = "sharpe"


def rankable_metric_chips() -> list[tuple[str, Any]]:
    """`RANKABLE_METRICS` as a `ChipGroup`/`Dropdown` options list.

    The declaration is (key, label), which is the order a *builder* wants; a
    widget wants (label, value). Flipping it here rather than at the widget
    keeps the flip from being respelled the next time something offers this
    choice.
    """
    return [(label, key) for key, label in RANKABLE_METRICS]


#: How many indices each leaderboard column lists at the top and at the
#: bottom, so "top 3 / bottom 3" is spelled once, not in the builder and again
#: in the widget that draws the slots.
LEADERBOARD_ROWS = 3

#: Hard cap on the Multi-Strategy selection. Analysis over the selected set is
#: O(n²) in the number of picks, so the picker is bounded to keep it fast and
#: the heatmaps legible; a further pick is rejected with an error popup.
#: Enforced by `Basket`, which is the only thing that can write a selection.
MAX_SELECTED_STRATEGIES = 25

#: How long a basket change waits before the analytics re-slice (#347).
#:
#: *Select all shown* of 25 arrives as one `selected_rows` change but a group
#: header's worth can arrive as several, and a 25-name `SelectionSlice.build`
#: is well under a second — so the debounce is not there to make the work
#: cheap, it is there to make sure it happens **once**. Short enough that a
#: single tick reads as immediate.
RESLICE_DEBOUNCE_S: float = 0.3

# Short metric windows (trading days) for the Platform z-score views.
#: One trading day. Offered on the Leaderboard alone (see
#: `LEADERBOARD_WINDOW_OPTIONS`), never in `SHORT_WINDOW_OPTIONS`.
DAY_WINDOW = 1
WEEK_WINDOW = 5
MONTH_WINDOW = 21
QUARTER_WINDOW = 63
HALF_YEAR_WINDOW = 126

#: Shared window options, so the sunburst Z-score control and the Quantitative
#: Z-Score window agree without re-spelling the list at each widget.
SHORT_WINDOW_OPTIONS: list[tuple[str, int]] = [
    ("1W", WEEK_WINDOW),
    ("1M", MONTH_WINDOW),
    ("3M", QUARTER_WINDOW),
    ("6M", HALF_YEAR_WINDOW),
]

#: (`WINDOW_LABELS`, the day → "Past Month" map, lived here until #306. Its one
#: reader captioned the leaderboard `Ranking · Past Month`; the section title
#: and the Window chips say that now, and a label map nothing reads is one more
#: thing to keep in step with a window list.)

#: The leaderboard's own window options (#306). A superset of the shared list
#: rather than an edit to it: `SHORT_WINDOW_OPTIONS` also drives the Platform
#: sunburst's z-control and the Quantitative Z-Score window, and a year — or a
#: day — on those is a change nobody asked for.
#:
#: **1D is offered, and ranks on Return alone** (v0.9.40). It was considered
#: and dropped in #306 because Sharpe, Calmar and Sortino have no defined value
#: over a single observation, so three of the four columns would have blanked
#: whenever it was selected. The answer is not to blank them but to **not draw
#: them**: `leaderboard_metrics` says which metrics a window can rank, and the
#: board hides the rest. A one-day return z-scored against its own five-year
#: history is a well-defined reading, and the desk's most-asked question about
#: yesterday.
LEADERBOARD_WINDOW_OPTIONS: list[tuple[str, int]] = [
    ("1D", DAY_WINDOW),
    *SHORT_WINDOW_OPTIONS,
    ("1Y", TRADING_DAYS_PER_YEAR),
]

#: The Leaderboard metrics that are defined over a **single** observation.
#: Return is a price ratio, so one day has one. Sharpe, Calmar and Sortino
#: each divide by a volatility, a drawdown or a downside deviation, and a
#: single return has none of the three.
_SINGLE_OBSERVATION_METRICS: frozenset[str] = frozenset({"return"})


def leaderboard_metrics(window_days: int) -> tuple[tuple[str, str], ...]:
    """The `RANKABLE_METRICS` a Leaderboard window can rank, in their order.

    One rule with two readers: `build_leaderboard` computes only these, and
    the board hides every column not among them. Deciding it in one place is
    what keeps the builder from computing a ratio the board will not show, or
    the board from showing a column the builder never filled.
    """
    if window_days < 2:
        return tuple(
            pair for pair in RANKABLE_METRICS if pair[0] in _SINGLE_OBSERVATION_METRICS
        )
    return RANKABLE_METRICS


#: Trailing window (trading days) the leaderboard ranks over on load, computed
#: whole-catalog from the already-fetched prices. The Window chips move it
#: live; this is only what the board opens on.
#:
#: It sits **below the options it has to be one of** so it can be spelled as
#: one of their constants rather than as a bare number — it was `21` while the
#: options were a list of names two hundred lines away, which is how a default
#: and the chips that offer it drift apart.
LEADERBOARD_WINDOW_DAYS = WEEK_WINDOW

#: How many trading days the Platform Strip chart draws, one column per date.
#: Read by the stats function, the chart and its header rather than typed at
#: three sites (#331 decision 12). Six since v0.9.25, spanning **T-1 back to
#: T-6** — weekdays only, and never today, whose return is against a price
#: still moving.
STRIP_DAYS: int = 6

# Quantitative-filter defaults (Multi-Strategy "Quantitative" filter).
VAR_CONFIDENCE = 0.95  # historical daily VaR confidence level
RSI_WINDOW = 14  # Wilder RSI lookback in trading days

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "indexdb.json"
#: The QIS Bulletin's commentary notes (#304): a JSON list of
#: `{"title", "date", "text"}`, newest rendered first. It replaced a single
#: author-written HTML blob — one undated body the app stamped with today —
#: whose loader, renderer, templates and stylesheet block went in #308.
COMMENTARY_PATH = REPO_ROOT / "data" / "commentary.json"
PERFORMANCE_DISCLAIMER_PATH = REPO_ROOT / "data" / "performance_disclaimer.html"
LEGAL_DISCLOSURE_PATH = REPO_ROOT / "data" / "legal_disclosure.html"
TEMPLATES_DIR = REPO_ROOT / "data" / "templates"
LOGO_PATH = REPO_ROOT / "assets" / "logo.png"

#: Where the app's **regenerable** files live. **Outside the project folder**
#: (v0.9.41): on a BQuant terminal the parquet price cache was written into the
#: project, where it counts against the size limit — about 1.4 MB for the
#: shipped catalog at the 15-year fetch (#361 took it from ~0.6 MB), which with
#: ~0.9 MB of `src` bytecode is what put the project over. The cache is data
#: nobody keeps: it expires in `CACHE_TTL_HOURS`. (Bytecode is handled in the
#: notebook, by not writing it at all.)
#:
#: The system temp directory rather than a dotfile under the home folder,
#: because on a terminal the home folder can *be* the project. Override with
#: `BBG_DASHBOARD_CACHE_DIR` where temp is unsuitable.
RUNTIME_DIR = Path(
    os.environ.get("BBG_DASHBOARD_CACHE_DIR")
    or Path(tempfile.gettempdir()) / "bbg_quant_dashboard"
)

#: On-disk parquet tier of the price cache, one file per `end` date.
CACHE_DIR = RUNTIME_DIR / "prices"
#: How stale a same-day disk cache may be before it counts as a miss.
CACHE_TTL_HOURS = 12

#: Benchmarks the user added at runtime. A sibling of the catalog rather than a
#: file under `CACHE_DIR`: the cache is semantically deletable at any time and
#: user configuration is not — which is also why this one **stays** in the
#: project when the cache moved out (v0.9.41). It is small, and it is the
#: user's. Gitignored, so one user's benchmarks are never
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


#: The Platform analytics hierarchy above the ticker leaves, outermost grouping
#: first — the one tree the Icicle draws, the Scatter and Strip aggregate over,
#: and the drill walks (epic #331). Every renderer walks it rather than naming
#: its levels, so the shape is a config flip with no code edit; any number of
#: levels works and the leaf is always the ticker.
#:
#: `solution` leads it, above `asset_class`. Epic #331 shipped without it and
#: called a solution stop a non-goal; the desk's reading is the other way —
#: the catalog is browsed *by solution first*, so that is where a drill should
#: start. Nesting it is safe on the shipped catalog for the reason recorded
#: when it was left out: no category there spans more than one solution, so
#: inserting the level only nests and cannot break the row contiguity RowGroup
#: needs.
ANALYTICS_LEVELS: tuple[str, ...] = (
    "solution",
    "asset_class",
    "category",
    "family",
)


def analytics_levels() -> tuple[str, ...]:
    """`ANALYTICS_LEVELS`, validated against the schema.

    Read through a call so a reconfigured hierarchy reaches the frame builders,
    the renderers and the drill together. The validation earns its keep because
    a missing level is filled with "Other": a mistyped one would otherwise
    render as a single undifferentiated band rather than fail.
    """
    for key in ANALYTICS_LEVELS:
        catalog_field(key)  # raises KeyError naming the offending level
    return ANALYTICS_LEVELS


#: What the Scope breadcrumb calls the un-narrowed catalog. "All" said nothing
#: about *all what*; this names the thing being browsed.
DRILL_ROOT_LABEL: str = "QIS Strategy"

#: The drill's leaf — every strategy drawn on its own. Not a schema field
#: (`ticker` is derived from the catalog's keys, not one of its columns), so it
#: carries its label here instead of through `field_label`.
DRILL_LEAF_LEVEL: str = "ticker"
DRILL_LEAF_LABEL: str = "Strategy"


def drill_levels() -> tuple[str, ...]:
    """Every depth the drill can stop at: the hierarchy, then the ticker leaf.

    **Every** level is a stop, including the first. It was a suffix *after*
    the first element while the root drew one point per `DRILL_LEVELS[0]` and
    the first level served only as the root's colour key — so the root view
    was categories and asset class was a colour. With `solution` leading the
    hierarchy the desk wants the root to be solutions, which makes the first
    level somewhere to stand rather than only something to colour by, and the
    two tuples collapse into one.

    Derived rather than declared for that reason: a second tuple could only
    disagree with this one.

    The Platform card bases its drill at the first level and offers
    ``drill_levels()[1:]`` as stops (v0.9.27) — that is how one surface chooses
    to browse the tree, not a property of the tree, so it lives there.
    """
    return (*analytics_levels(), DRILL_LEAF_LEVEL)


def drill_level_label(key: str) -> str:
    """The display label for a drill stop, the ticker leaf included."""
    return DRILL_LEAF_LABEL if key == DRILL_LEAF_LEVEL else field_label(key)


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


def score_history_years() -> int:
    """How far back the app **fetches**, in years — always further than it
    analyses.

    Sized for the deepest score the app will ask for. The catalog's ranking
    column standardizes a metric against `SCORE_SAMPLE_YEARS` of that metric's
    *own rolling history*, at whichever window the table is showing (#324), so
    the deepest case needs the longest offered window **plus** the sample
    behind it: at `10Y` that is 10 + 5 = 15 calendar years. Fetch only the
    window and its sample is a single observation long, which
    `rolling_metric_zscore` standardizes against without saying so.

    Derived rather than typed, and for the reason the accessors above are:
    #311 wrote `6` — `1Y window + 5Y sample`, the leaderboard's deepest case —
    as a literal that nothing checked against the windows on offer. A second
    consumer with a deeper window would have been a second literal. The
    relationship is the fact worth storing, so widening `LOOKBACK_YEARS`,
    lengthening `SCORE_SAMPLE_YEARS` or adding a window to `STAT_WINDOWS`
    carries the fetch with it instead of leaving a quietly truncated sample
    behind.

    `stat_windows()` is itself capped by `LOOKBACK_YEARS`, so the two can never
    disagree: the offered set never outruns the lookback, and the fetch never
    outruns what the offered set needs. Rounded up because a window may be a
    fraction of a year (`6M`) while `pd.DateOffset(years=...)` takes an int.

    Until v0.9.34 the sample *was* the lookback, so this read
    `LOOKBACK_YEARS + longest window` and widening the analysis to 10 years
    would have meant a 20-year pull with a 10-year sample behind every score.
    #361 wanted 15 years pulled and the scores left comparable, which is the
    reading that made the sample its own constant.
    """
    return math.ceil(max(years for _, years in stat_windows()) + SCORE_SAMPLE_YEARS)


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


def leaderboard_window_days() -> int:
    """`LEADERBOARD_WINDOW_DAYS`, validated against the chips that offer it.

    `universe_grid_default_window`'s argument, one board over: a default the
    Window chips do not offer would open the board on a window no chip is lit
    for, so the first click on any chip would look like it had done nothing.
    """
    offered = [days for _label, days in LEADERBOARD_WINDOW_OPTIONS]
    if LEADERBOARD_WINDOW_DAYS not in offered:
        raise ValueError(
            f"LEADERBOARD_WINDOW_DAYS={LEADERBOARD_WINDOW_DAYS!r} is not one of "
            f"LEADERBOARD_WINDOW_OPTIONS ({offered})"
        )
    return LEADERBOARD_WINDOW_DAYS


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
#: The cross-asset **carry** factor. Already a curated benchmark, so it costs
#: no extra ticker — the β is taken against its own returns, like Trend's.
CARRY_TICKER = "BSLXAC Index"  # Bloomberg cross-asset carry
#: The bond-volatility leg of the cross-asset **Volatility** factor (#371).
#: `VIX_TICKER` is the equity leg and is already a `REGIME_TICKER`, so this is
#: the one new name the factor costs — and it joins `FACTOR_TICKERS` so it
#: rides the single startup fetch rather than a second call (#9's rule).
MOVE_TICKER = "MOVE Index"  # ICE BofA MOVE — implied Treasury volatility
FACTOR_TICKERS: list[str] = [
    LONG_TREASURY_TICKER,
    SHORT_RATE_TICKER,
    TREND_TICKER,
    MOVE_TICKER,
]

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
    # MOVE runs an order of magnitude above VIX, which is the whole reason the
    # Volatility factor z-scores each leg before averaging them (#371): a raw
    # average of the two would be mostly this one.
    MOVE_TICKER: (105.0, 6.0, 50.0, 220.0),  # MOVE-like, hovers ~105
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
