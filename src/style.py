"""Centralized style tokens for the dashboard.

All hex colors, font stacks, and typography sizes used by `src/layout/` live
here; inline literals in HTML/CSS strings should reference these enums so a
color or font changes in one place.

Members of the `StrEnum` token enums (`Color`, `Font`, `FontSize`, `Sentiment`)
are `str` subclasses whose `str()`/`format()` return the value, so they
interpolate into f-strings without `.value`.

The palette is layered. `Color` holds the raw hex scale; the semantic enums
(`StatusTone`, `Sentiment`) and the module-level maps below group it by
meaning. Two surfaces coexist: the **chrome** (masthead, overlay, buttons,
grids, tab band) hangs off the `CHROME_*`/`SURFACE`/`ACCENT` navy tokens, while
**charts** render on `TRANSPARENT` and therefore sit on that same navy
through-color rather than on their own panel. The `CHART_*` tokens style what
plotly draws on top of it.
"""

from __future__ import annotations

from enum import Enum, StrEnum


class Color(StrEnum):
    """Pure hex palette. Semantic groupings live in the dedicated enums
    below (`StatusTone`, `Sentiment`)."""

    # Brand
    BRAND_NAVY = "#0b1f3a"

    # Neutrals — slate scale
    WHITE = "#ffffff"
    SLATE_50 = "#f8fafc"
    SLATE_100 = "#f1f5f9"
    SLATE_200 = "#e5e7eb"
    SLATE_300 = "#cbd5e1"
    SLATE_400 = "#94a3b8"
    SLATE_500 = "#64748b"
    SLATE_600 = "#475569"

    # Status — emerald / amber / red scales
    EMERALD_50 = "#ecfdf5"
    EMERALD_200 = "#a7f3d0"
    EMERALD_800 = "#065f46"
    AMBER_50 = "#fffbeb"
    AMBER_200 = "#fde68a"
    AMBER_800 = "#92400e"
    RED_50 = "#fef2f2"
    RED_200 = "#fecaca"
    RED_600 = "#dc2626"
    RED_900 = "#7f1d1d"

    # Sentiment accents — also the "Refresh prices" primary-action button color.
    GREEN_600 = "#16a34a"

    # ---- Chart theme (dark) ----------------------------------------------
    # Near-black with a hint of blue; reads better than pure #000 on typical
    # browser displays.
    CHART_BG = "#0d1117"
    # Lets the host page surface show through paper + plot area, so charts read
    # as part of the chrome rather than sitting on their own near-black panel.
    TRANSPARENT = "rgba(0,0,0,0)"
    CHART_GRID = "#1f2937"
    CHART_AXIS = "#475569"
    # A 3D scene takes no paper shapes, which is why the factor scatter used
    # translucent mesh planes to mark the origin — and why they dimmed the
    # markers behind them. These two let the scene's own axes carry it instead
    # (#335): the zero line bright enough to read against `TRANSPARENT` at the
    # default camera, the wall edge a step below it so the box reads as a frame
    # rather than as three more zero lines.
    CHART_ZERO_LINE = "#94a3b8"
    CHART_AXIS_LINE = "#334155"
    CHART_TEXT = "#cbd5e1"
    CHART_TITLE = "#f9fafb"
    CHART_HOVER_BG = "#1f2937"

    # ---- Dark technical chrome (navy blue theme) --------------------------
    CHROME_BG = "#0a1322"
    SURFACE = "#101d33"  # raised panel (filter box, cards, masthead)
    SURFACE_2 = "#1a2b45"  # nested panels, hover rows, the tab band
    BORDER = "#293c59"
    TEXT = "#e6edf3"
    TEXT_MUTED = "#93a4c0"  # captions, metadata, placeholders
    # Primary action / highlight / rule color: masthead rule, active tab fill,
    # focus outlines, progress bar, highlight emphasis.
    ACCENT = "#00AFE9"
    ACCENT_2 = "#66c6f0"
    # Translucent BLACK mask (~60% alpha), not a CHROME_BG scrim: blended into
    # the navy dashboard, a near-opaque navy scrim looked like no mask at all.
    SCRIM = "#00000099"

    # ---- Conditional-format heatmap (all-catalog grid) --------------------
    # Diverging red→neutral→green cell backgrounds for the Sharpe and Z-Score
    # columns. Low-alpha tints over the dark body keep the bright cell text
    # legible; built from GREEN_600 / RED_600 so the heatmap shares the
    # dashboard's sentiment palette.
    HEAT_POS_STRONG = "#16a34acc"  # GREEN_600 @ ~80%
    HEAT_POS_SOFT = "#16a34a55"  # GREEN_600 @ ~33%
    HEAT_NEG_SOFT = "#dc262655"  # RED_600 @ ~33%
    HEAT_NEG_STRONG = "#dc2626cc"  # RED_600 @ ~80%

    # ---- Nested group-header bands (all-catalog grid, #284) ---------------
    # One cyan fill per nesting level, stepping DOWN in tint, so the tiers read
    # as bands rather than as a text colour on the body background. Level 0 is
    # `ACCENT` itself and is not repeated here.
    #
    # The step is not uniform, and cannot be: the top two fills are bright
    # enough that light text fails contrast on them, so they carry dark text
    # (as `.bbg-tabband .bbg-pill.is-active` already does) while the lower two
    # carry the normal light text. The scale therefore jumps down at level 2,
    # where the foreground flips — a smooth ramp through the middle would put a
    # band exactly where neither text colour is legible.
    #
    # Four levels because four fields are groupable
    # (`UNIVERSE_GRID_GROUPABLE_FIELDS`), so level 3 is reachable today.
    GROUP_BAND_1 = "#3fbdee"  # ACCENT lightened — still dark-text territory
    GROUP_BAND_2 = "#0a6183"  # deep cyan; light text from here down
    GROUP_BAND_3 = "#0a4a64"  # deepest, one step off the chrome


#: The all-catalog table's label-row height, and therefore the sticky `top`
#: of the per-column filter row beneath it (#285). One value because the two
#: CSS rules must agree: a sticky offset cannot be a percentage, so if the
#: label row's height and the filter row's offset were written separately,
#: nothing would stop them drifting apart — and the symptom would be a filter
#: row parked over the labels it belongs to.
CATALOG_HEADER_ROW_HEIGHT: str = "30px"

#: How tall the Platform row stands: the catalog table's box **and** the ranking
#: rail beside it, both set to this exact value.
#:
#: How tall the all-catalog table stands. Plainly its own height since #326;
#: it was the number the table and the ranking rail beside it *shared*, because
#: stretching made whichever box held more content set the row — the table grew
#: to the rail on a small catalog and the rail to the table on a large one.
#: With the rail gone there is nothing to keep in step with, and a fixed height
#: is now simply how the table gets a box its internals can fill.
#:
#: Those internals fill it: the search row and the row-count readout take what
#: they need and the row area scrolls in the remainder, so this is the one
#: number to change and nothing has to be adjusted to match it.
#: Raised 10% from 460px, when the table's rows read as squeezed. Worth
#: re-tuning at a terminal's fonts now that the table is full width.
CATALOG_TABLE_HEIGHT: str = "506px"


#: How tall the Platform analytics card's row stands: the active chart's box
#: **and** the points table beside it, both this exact value (#331 dec. 7).
#:
#: Fixed rather than stretched, which is the `CATALOG_TABLE_HEIGHT` lesson one
#: block up: stretching lets whichever box holds more content set the row, so
#: a long points list would grow the chart and a tall chart would stretch a
#: three-row table. The chart's own `height` in `_chart_layout` follows this
#: token, so the figure fills its box rather than sitting in the top of it.
#:
#: **Height is the Icicle's only lever, which is why this is the big number
#: on the card.** Its `tiling.orientation="h"` runs *depth* left to right, one
#: column per level, so the width is divided four ways whatever the catalog
#: holds — while the height is divided among **siblings**, every strategy in
#: the pinned solution stacked in the last column. Widening the card does
#: nothing for that; only this does.
#:
#: 420px (v0.9.24) → 504px (v0.9.27) → 720px (v0.9.28), each raise from the
#: same terminal reading: the cells were still too short to carry their
#: labels. It now stands *above* `CATALOG_TABLE_HEIGHT` rather than a little
#: under it. That inverts the original "a chart as tall as the catalog pushes
#: the page" sizing, deliberately: the table's height is a scroll viewport
#: onto rows that keep their size, and the chart's is the whole drawing.
#:
#: **The figures are built at this height too** (`ANALYTICS_HEIGHT_PX`). They
#: were not until v0.9.27: `_chart_layout`'s default is the app-wide
#: `CHART_HEIGHT`, which at 520px was *taller* than the 420px box, so the card
#: clipped every chart it drew and the comment here claiming otherwise was
#: wrong.
ANALYTICS_HEIGHT: str = "720px"
ANALYTICS_HEIGHT_PX: int = int(ANALYTICS_HEIGHT.removesuffix("px"))

#: The analytics card's chart:table split, as flex bases rather than pixels —
#: the `COMMENTARY_*_SHARE` pattern, and for the same reason. The 360px basis
#: this replaces squeezed the table into a strip on a wide screen and read as
#: a different layout at every width; a share holds the proportion the card
#: was designed at. Both boxes carry `min-width: 0` so a long strategy name
#: wraps inside its column instead of widening it.
ANALYTICS_CHART_SHARE: str = "60%"
ANALYTICS_TABLE_SHARE: str = "40%"

#: How tall a `section_panel`'s container stands in the commentary block — the
#: Leaderboard's and the QIS Bulletin's, both from this one token, so neither
#: can set the row for the other (the `CATALOG_TABLE_HEIGHT` argument, one
#: block up).
#:
#: Sized from the leaderboard, the taller of the two: a column is its title
#: plus six 22px rows plus the divider, ~180px with the board's own padding.
#: 300px clears that and leaves the bulletin about five launch cards before it
#: scrolls. It is one number for both sections, so it is one edit to tune once
#: it has been seen at a terminal's fonts — which is where it should be tuned.
COMMENTARY_BOX_HEIGHT: str = "300px"

#: How tall the Multi-Strategy Basket strip stands (#346).
#:
#: Fixed for `CATALOG_TABLE_HEIGHT`'s reason and one more of its own: an empty
#: basket has no cards, and a box that sized itself to its content would
#: collapse to nothing and shift everything below it the moment the last card
#: was removed. Tall enough for two rows of cards at the cap; beyond that the
#: strip scrolls rather than growing the page.
BASKET_STRIP_HEIGHT: str = "104px"

#: The diverging heat bands: the four thresholds a value is placed in to pick
#: one of `Color.HEAT_*`. `(t0, t1, t2, t3)` reads as strong-negative below
#: `t0`, soft-negative to `t1`, **neutral** to `t2`, soft-positive to `t3`,
#: strong-positive above.
#:
#: Here rather than in `grids.py` because two stacks read them now (v0.9.36,
#: #366): the ipydatagrid renderers, and the HTML calendar that replaced the
#: `CalendarGrid`. A band is a visual decision keyed to the colour tokens it
#: sits beside, so this is where it belongs either way — and it is the one
#: place a band can be retuned without one table disagreeing with another.
#:
#: The bands themselves: Sharpe's neutral straddles 0–0.5; a Z-Score is
#: already centred at 0 so its bands are symmetric; a **return** cell is
#: neutral within ±1% and strong beyond ±5%; a vol-adjusted cell is a
#: unitless ratio on a wider band; correlation diverges around 0 and **beta
#: around 1.0**, the market-beta neutral point, since what the ramp encodes
#: there is distance from the market rather than good or bad.
HeatBand = tuple[float, float, float, float]
SHARPE_HEAT_BAND: HeatBand = (-0.5, 0.0, 0.5, 1.0)
ZSCORE_HEAT_BAND: HeatBand = (-1.5, -0.5, 0.5, 1.5)
RETURN_HEAT_BAND: HeatBand = (-0.05, -0.01, 0.01, 0.05)
VOLADJ_HEAT_BAND: HeatBand = (-1.0, -0.25, 0.25, 1.0)
CORR_HEAT_BAND: HeatBand = (-0.5, -0.1, 0.1, 0.5)
BETA_HEAT_BAND: HeatBand = (0.0, 0.7, 1.3, 2.0)

#: Empty (NaN) numeric cells render as this rather than "NaN" / "NaN%", in
#: every table on both stacks.
MISSING_DASH: str = "-"

#: How tall the Single Strategy monthly-return calendar's box stands (#366).
#:
#: Sized for the ten years `LOOKBACK_YEARS` offers plus the header; a longer
#: history scrolls inside the box rather than growing the page, which is the
#: same trade `CATALOG_TABLE_HEIGHT` makes and for the same reason — what is
#: below it should not move when a strategy with more history is picked.
CALENDAR_HEIGHT: str = "336px"

#: How tall the Single Strategy metrics table's box stands (#366).
#:
#: Fixed for `CATALOG_TABLE_HEIGHT`'s reason: the number of rows is constant
#: (`STRATEGY_METRICS`) but the number of *columns* is not — `stat_windows()`
#: grows with `LOOKBACK_YEARS` — and a box that sized itself would move
#: everything below it when the fetch widens. Tall enough for the eight rows
#: plus the header; beyond that it scrolls.
STRATEGY_METRICS_HEIGHT: str = "292px"

#: How wide the asset-class colour block on a selected-strategy card is.
#:
#: 3px when the cards shipped, which read as trim rather than as the card's
#: colour — the whole job of the block is to say *which strategy is which* at
#: a glance across a wrapping strip. A border rather than a child element, so
#: widening it cannot displace the ticker or the x.
BASKET_TAG_WIDTH: str = "10px"

#: The commentary block's 60:40 split, as flex bases rather than pixels: the
#: leaderboard's four columns have to stay readable at a terminal width, and a
#: pixel basis would hold its width while the pane beside it took whatever was
#: left (which is what #303 replaced — 620px reads as 60% at 1030px wide and
#: 43% at 1440px). Declared here as a pair so the ratio is one fact, not two
#: literals at a call site that could drift to 65:40.
COMMENTARY_LEADERBOARD_SHARE: str = "60%"
COMMENTARY_BULLETIN_SHARE: str = "40%"

#: A filter bar's split: the dimension chips left, that dimension's values
#: right. **Shares, not a pixel column** (v0.9.31) — the 280px basis this
#: replaced gave the chips a third of a narrow screen and a tenth of a wide
#: one, and the values are what need the room: a dimension can carry forty of
#: them where the chip set is always the same seven. The `COMMENTARY_*_SHARE`
#: pattern above, applied as `flex: 1 1 <share>` with `min-width: 0` on both.
FILTER_CHIPS_SHARE: str = "20%"
FILTER_VALUES_SHARE: str = "80%"


class Font(StrEnum):
    """Font-family stacks. Use `Font.SANS` / `Font.MONO` in inline styles."""

    SANS = "system-ui,sans-serif"
    MONO = "ui-monospace,SFMono-Regular,Menlo,monospace"


class FontSize(StrEnum):
    """Typography scale. Pick the smallest semantic name that fits."""

    TITLE = "32px"  # masthead title — largest in the scale
    HERO = "22px"  # page-banner title (secondary)
    DISPLAY = "20px"  # highlight-card value
    H3 = "15px"  # section heading
    BODY = "14px"  # default body / commentary
    SMALL = "13px"  # small body / error block
    LABEL = "12px"  # form labels / status banner
    CAPTION = "11px"  # legend / metadata caption
    MICRO = "10px"  # uppercase micro-label


class StatusTone(Enum):
    """Color triple for the status banner. Each tone bundles
    `(background, border, foreground)`."""

    INFO = (Color.SLATE_100, Color.SLATE_300, Color.BRAND_NAVY)
    SUCCESS = (Color.EMERALD_50, Color.EMERALD_200, Color.EMERALD_800)
    WARN = (Color.AMBER_50, Color.AMBER_200, Color.AMBER_800)
    ERROR = (Color.RED_50, Color.RED_200, Color.RED_900)

    @property
    def bg(self) -> str:
        return self.value[0]

    @property
    def border(self) -> str:
        return self.value[1]

    @property
    def fg(self) -> str:
        return self.value[2]


class Sentiment(StrEnum):
    """Highlight-card sentiment colors."""

    POSITIVE = Color.GREEN_600
    NEGATIVE = Color.RED_600
    NEUTRAL = Color.BRAND_NAVY


#: High-chroma line colors tuned to pop against the dark chart background,
#: orange and cyan anchoring the first two (most-selected) slots. Order matters
#: — the marks loop assigns positionally — so keep this a tuple.
LINE_PALETTE: tuple[str, ...] = (
    "#FFA000",  # Bloomberg orange
    "#00B5E2",  # Barclays cyan
    "#FFD400",  # Yellow
    "#1DE9B6",  # Mint
    "#FF5252",  # Coral
    "#B388FF",  # Lavender
    "#FF80AB",  # Pink
    "#80D8FF",  # Sky
    "#69F0AE",  # Lime
    "#FFAB40",  # Light orange
)

#: Asset-class colors for the Platform factor-scatter, drawn from
#: `LINE_PALETTE` so they stay token-driven and sit naturally in the dark chart
#: theme. Keys match the `AssetClass` values in `data/indexdb.json`.
ASSET_CLASS_COLORS: dict[str, str] = {
    "Equity": LINE_PALETTE[1],  # cyan
    "Fixed Income": LINE_PALETTE[3],  # mint
    "Commodity": LINE_PALETTE[0],  # orange
    "FX": LINE_PALETTE[5],  # lavender
}
ASSET_CLASS_FALLBACK_COLOR: str = Color.SLATE_400  # anything unmapped
