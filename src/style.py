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

    # ---- Dark technical chrome (v0.6.5) -----------------------------------
    # Cohesive dark surface palette aligned with the chart theme above, so the
    # surrounding chrome reads as the same "terminal-grade" surface as the
    # charts. Workstreams B/C/D (masthead, loading overlay, buttons, grids)
    # hang their styling off these tokens.
    # Page background — matches the chart canvas so chrome and charts blend.
    CHROME_BG = "#0d1117"
    # Raised panel surface (filter box, cards) — one step above the page bg.
    SURFACE = "#161b22"
    # Second raised surface (nested panels, hover rows).
    SURFACE_2 = "#1f2937"
    # Hairline borders / dividers / scrollbar thumb.
    BORDER = "#30363d"
    # Primary chrome text — bright near-white for legibility on the dark bg.
    TEXT = "#e6edf3"
    # Muted secondary text (captions, metadata, placeholders).
    TEXT_MUTED = "#8b949e"
    # Accent — Bloomberg orange (LINE_PALETTE[0]); primary highlight / rule.
    ACCENT = "#FFA000"
    # Secondary accent — Barclays cyan (LINE_PALETTE[1]).
    ACCENT_2 = "#00B5E2"
    # Dimmed loading-overlay backdrop — CHROME_BG at ~90% alpha (8-digit hex).
    SCRIM = "#0d1117e6"


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


class TabButtonTone(Enum):
    """Active / inactive state for the top-level pill tab buttons.
    Bundles `(background, foreground, font-weight)`."""

    ACTIVE = (Color.BRAND_NAVY, Color.WHITE, "600")
    INACTIVE = (Color.SLATE_100, Color.SLATE_600, "500")

    @property
    def bg(self) -> str:
        return self.value[0]

    @property
    def fg(self) -> str:
        return self.value[1]

    @property
    def weight(self) -> str:
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
