"""Centralized style tokens for the dashboard.

All hex colors, font stacks, and typography sizes used by `src/layout.py`
live here. Inline literals in HTML/CSS strings should reference these
enums so colors and fonts can be changed in one place.

Members of the `StrEnum` token enums (e.g. `Color`, `Font`) are `str`
subclasses whose `str()`/`format()` return the value, so they interpolate
into f-strings without needing `.value`.
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

    # ---- Chart theme (Bloomberg / Barclays blend, dark) -------------------
    # Near-black with a hint of blue (GitHub-dark vibe; reads better than
    # pure #000 under typical browser displays).
    CHART_BG = "#0d1117"
    # Fully transparent — lets the host page surface show through the chart
    # (paper + plot area). Used when charts should read as part of the chrome
    # rather than sitting on their own near-black panel.
    TRANSPARENT = "rgba(0,0,0,0)"
    # Subtle grid lines that don't compete with the data.
    CHART_GRID = "#1f2937"
    # Axis line + tick color — medium slate for legibility on the dark bg.
    CHART_AXIS = "#475569"
    # Primary chart text (axis labels, tick text).
    CHART_TEXT = "#cbd5e1"
    # Chart title — bright near-white for contrast.
    CHART_TITLE = "#f9fafb"
    # Hover tooltip background.
    CHART_HOVER_BG = "#1f2937"

    # ---- Dark technical chrome (navy blue theme) --------------------------
    # Cohesive dark *navy* surface palette anchored by the cyan action accent
    # below. Charts render on a transparent background (`TRANSPARENT`), so they
    # sit on this navy through-color; only the chrome (masthead, loading
    # overlay, buttons, grids, tab band) hangs off these tokens.
    # Page background — deep navy.
    CHROME_BG = "#0a1322"
    # Raised panel surface (filter box, cards, masthead) — one step up in navy.
    SURFACE = "#101d33"
    # Second raised surface (nested panels, hover rows, the tab band).
    SURFACE_2 = "#1a2b45"
    # Hairline borders / dividers / scrollbar thumb — navy-tinted.
    BORDER = "#293c59"
    # Primary chrome text — bright near-white for legibility on the navy bg.
    TEXT = "#e6edf3"
    # Muted secondary text (captions, metadata, placeholders) — cool slate.
    TEXT_MUTED = "#93a4c0"
    # Accent — cyan; the primary action / highlight / rule color (was the
    # Bloomberg orange). Drives the masthead rule, active tab fill, focus
    # outlines, progress bar, and highlight emphasis.
    ACCENT = "#00AFE9"
    # Secondary accent — a lighter azure that complements the cyan primary.
    ACCENT_2 = "#66c6f0"
    # Dimmed loading-overlay backdrop — CHROME_BG at ~90% alpha (8-digit hex).
    SCRIM = "#0a1322e6"

    # ---- Conditional-format heatmap (v0.7.0 Platform grid) ----------------
    # Diverging red→neutral→green cell backgrounds for the all-catalog grid's
    # Sharpe + Z-Score columns. Low-alpha tints (8-digit hex) over the dark
    # body so the bright cell text stays legible; built from GREEN_600 /
    # RED_600 so the heatmap shares the dashboard's sentiment palette.
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

    TITLE = "32px"  # masthead title (v0.6.5) — largest in the scale
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


# Bloomberg / Barclays-blend palette — high-chroma colors tuned to pop
# against the dark chart background. Bloomberg orange + Barclays cyan
# anchor the first two slots (most-selected position). Order matters
# (positional assignment in the marks loop), so keep this as a tuple.
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


# Asset-class color map for the v0.7.0 Platform factor-scatter
# (colored by asset class). The original `AssetClassColor`/`ASSET_CLASS_COLORS`
# were deleted in v0.6.0 Workstream G as dead code; this is a small, focused
# reintroduction drawn from `LINE_PALETTE` so the colors stay token-driven and
# sit naturally in the dark chart theme. Keys match the `AssetClass` values in
# `data/indexdb.json`; `ASSET_CLASS_FALLBACK_COLOR` covers anything unmapped.
ASSET_CLASS_COLORS: dict[str, str] = {
    "Equity": LINE_PALETTE[1],  # cyan
    "Fixed Income": LINE_PALETTE[3],  # mint
    "Commodity": LINE_PALETTE[0],  # orange
    "FX": LINE_PALETTE[5],  # lavender
}
ASSET_CLASS_FALLBACK_COLOR: str = Color.SLATE_400
