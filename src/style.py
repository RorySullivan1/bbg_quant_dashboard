"""Centralized style tokens for the dashboard.

All hex colors, font stacks, and typography sizes used by `src/layout.py`
live here. Inline literals in HTML/CSS strings should reference these
enums so colors and fonts can be changed in one place.

Members of `str`-mixed enums (e.g. `Color`, `Font`) are `str` subclasses,
so they interpolate into f-strings without needing `.value`.
"""

from __future__ import annotations

from enum import Enum


class _StrEnum(str, Enum):
    """`str`-mixed Enum whose `__str__`/`__format__` return the value,
    so members interpolate cleanly into f-strings:

        >>> f"color:{Color.BRAND_NAVY};"
        'color:#0b1f3a;'

    The plain `(str, Enum)` mixin's `__str__` returns `"Color.BRAND_NAVY"`
    in Python 3.11+, which would corrupt every inline style string.
    """

    def __str__(self) -> str:
        return self.value

    def __format__(self, spec: str) -> str:
        return format(self.value, spec)


class Color(_StrEnum):
    """Pure hex palette. Semantic groupings live in the dedicated enums
    below (`StatusTone`, `Sentiment`, `AssetClassColor`)."""

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

    # Sentiment accents
    GREEN_600 = "#16a34a"


class Font(_StrEnum):
    """Font-family stacks. Use `Font.SANS` / `Font.MONO` in inline styles."""

    SANS = "system-ui,sans-serif"
    MONO = "ui-monospace,SFMono-Regular,Menlo,monospace"


class FontSize(_StrEnum):
    """Typography scale. Pick the smallest semantic name that fits."""

    HERO = "22px"     # page-banner title
    DISPLAY = "20px"  # highlight-card value
    H3 = "15px"       # section heading
    BODY = "14px"     # default body / commentary
    SMALL = "13px"    # small body / error block
    LABEL = "12px"    # form labels / status banner
    CAPTION = "11px"  # legend / metadata caption
    MICRO = "10px"    # uppercase micro-label


class StatusTone(Enum):
    """Color triple for the status banner. Each tone bundles
    `(background, border, foreground)`."""

    INFO    = (Color.SLATE_100,  Color.SLATE_300,  Color.BRAND_NAVY)
    SUCCESS = (Color.EMERALD_50, Color.EMERALD_200, Color.EMERALD_800)
    WARN    = (Color.AMBER_50,   Color.AMBER_200,  Color.AMBER_800)
    ERROR   = (Color.RED_50,     Color.RED_200,    Color.RED_900)

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

    ACTIVE   = (Color.BRAND_NAVY, Color.WHITE,     "600")
    INACTIVE = (Color.SLATE_100,  Color.SLATE_600, "500")

    @property
    def bg(self) -> str:
        return self.value[0]

    @property
    def fg(self) -> str:
        return self.value[1]

    @property
    def weight(self) -> str:
        return self.value[2]


class Sentiment(_StrEnum):
    """Highlight-card sentiment colors."""

    POSITIVE = Color.GREEN_600
    NEGATIVE = Color.RED_600
    NEUTRAL = Color.BRAND_NAVY


class AssetClassColor(_StrEnum):
    """Per-asset-class accent colors for the risk/return scatter."""

    EQUITY = "#1f77b4"
    FIXED_INCOME = "#ff7f0e"
    COMMODITY = "#2ca02c"
    FX = "#d62728"
    MULTI_ASSET = "#9467bd"
    CREDIT = "#8c564b"
    UNKNOWN = "#94a3b8"


ASSET_CLASS_COLORS: dict[str, str] = {
    "Equity":       AssetClassColor.EQUITY.value,
    "Fixed Income": AssetClassColor.FIXED_INCOME.value,
    "Commodity":    AssetClassColor.COMMODITY.value,
    "FX":           AssetClassColor.FX.value,
    "Multi-Asset":  AssetClassColor.MULTI_ASSET.value,
    "Credit":       AssetClassColor.CREDIT.value,
}


# Matplotlib's tab10 palette — used for multi-series line/bar marks. Order
# matters (positional assignment in the marks loop), so keep this as a
# tuple rather than an enum.
LINE_PALETTE: tuple[str, ...] = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf",
)
