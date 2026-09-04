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
