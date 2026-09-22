"""Shared chart theming: layout defaults, reference lines, and color lookups.

The single source of the dark plotly look. `_chart_layout` returns the base
layout every figure starts from — transparent paper so charts sit on the app's
navy through-color, tokenized grid/axis/text colors, and a uniform height — and
accepts overrides for the per-chart bits.

Also holds the small helpers that must agree across every figure: `_h_ref` /
`_v_ref` for zero-reference lines, `_v_divider` for the rule between two
columns, `_palette_color` for positional series colors, and `_short_ticker` for
axis and legend labels.
"""

from __future__ import annotations

from ..config import SHARPE_WINDOW, TRADING_DAYS_PER_YEAR
from ..style import LINE_PALETTE, Color, Font, Sentiment

# Uniform height for every chart that lives inside an analysis pane.
# `PerfGrid` / `UniverseGrid` / the return-distribution stats grid keep their
# own heights — they're tables, not charts.
CHART_HEIGHT = "520px"


SHARPE_WINDOW_LABEL = (
    f"{SHARPE_WINDOW // TRADING_DAYS_PER_YEAR}Y"
    if SHARPE_WINDOW % TRADING_DAYS_PER_YEAR == 0
    else f"{SHARPE_WINDOW}d"
)


_CHART_HEIGHT_PX: int = int(CHART_HEIGHT.removesuffix("px"))


def _chart_layout(*, title: str, **overrides) -> dict:
    """Shared plotly Layout kwargs — Bloomberg/Barclays dark theme.

    Charts render on a transparent background (`Color.TRANSPARENT`) so the
    host page surface shows through, with white titles and light slate text.
    Axis grid/tick styling inherits from the `plotly_dark` template; we
    override only background, title, font color, and hover styling.

    Pass `xaxis`, `yaxis`, `hovermode`, `barmode`, `shapes`, `margin`,
    etc. via `overrides`.
    """
    base = dict(
        template="plotly_dark",
        paper_bgcolor=Color.TRANSPARENT.value,
        plot_bgcolor=Color.TRANSPARENT.value,
        height=_CHART_HEIGHT_PX,
        margin=dict(t=44, b=50, l=60, r=20),
        title=dict(
            text=title,
            font=dict(size=14, color=Color.CHART_TITLE.value),
            x=0.02,
            xanchor="left",
        ),
        showlegend=False,
        font=dict(family=Font.SANS.value, color=Color.CHART_TEXT.value, size=12),
        # **One hover treatment for every chart in the app** (v0.9.31). `align`
        # and `namelength` were the Platform Scatter's alone, passed as its own
        # `hoverlabel=` — and because `base.update(overrides)` replaces a key
        # rather than merging into it, that override was silently dropping the
        # four theme tokens beside them, so the one chart with the best hover
        # geometry was also the only one not wearing the dark chrome.
        #
        # `align="left"` keeps a multi-line tooltip's lines on a common left
        # edge instead of centring each one; `namelength=-1` stops plotly
        # truncating a trace name to 15 characters with an ellipsis, which on
        # this catalog cuts most strategy names mid-word.
        hoverlabel=dict(
            font_family=Font.SANS.value,
            bgcolor=Color.CHART_HOVER_BG.value,
            font_color=Color.CHART_TEXT.value,
            bordercolor=Color.CHART_AXIS.value,
            align="left",
            namelength=-1,
        ),
    )
    base.update(overrides)
    return base


def _h_ref(y: float) -> dict:
    """Dashed horizontal reference line spanning the chart's full width."""
    return dict(
        type="line",
        xref="paper",
        x0=0,
        x1=1,
        yref="y",
        y0=y,
        y1=y,
        line=dict(color=Color.CHART_AXIS.value, dash="dash", width=1),
    )


def _v_divider(x: float) -> dict:
    """A solid vertical rule at ``x``, dividing one column from the next.

    Not `_v_ref`: that one is a dashed hairline in the axis colour, for marking
    a *value* on a continuous axis. This one is chrome — it says where one
    column ends and the next begins, so it is solid, brighter and twice the
    width. The Strip's six weekdays sat in one undivided field of markers
    until v0.9.32, with nothing but the tick labels to say which cloud was
    which day.

    Drawn **below** the traces. The jitter keeps every marker within
    `StripChart.JITTER` of its column's centre, so a boundary at the halfway
    point can never be crossed by a point — but a rule painted over the data
    is a rule that can hide it, and there is nothing to gain by risking it.
    """
    return dict(
        type="line",
        xref="x",
        x0=x,
        x1=x,
        yref="paper",
        y0=0,
        y1=1,
        layer="below",
        line=dict(color=Color.CHART_ZERO_LINE.value, width=2),
    )


def _v_ref(x: float) -> dict:
    """Dashed vertical reference line spanning the chart's full height."""
    return dict(
        type="line",
        xref="x",
        x0=x,
        x1=x,
        yref="paper",
        y0=0,
        y1=1,
        line=dict(color=Color.CHART_AXIS.value, dash="dash", width=1),
    )


def _palette_color(i: int) -> str:
    return LINE_PALETTE[i % len(LINE_PALETTE)]


def _rgba(hex_color: str, alpha: float) -> str:
    """`#RRGGBB` plus an alpha, as the `rgba()` Plotly wants.

    Plotly's `bgcolor` takes a CSS colour, and the style tokens are hex — so
    an overlay that has to let the chart through needs the two combined
    somewhere. Here rather than at the call site, because a second caller
    would otherwise re-derive the same three `int(..., 16)` slices.
    """
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _short_ticker(ticker: str) -> str:
    """Drop the BBG ' Index' suffix, leaving the core ticker (e.g. 'SPX')."""
    return ticker.removesuffix(" Index")


def _sentiment_color(name: str) -> str:
    try:
        return Sentiment[name.upper()].value
    except KeyError:
        return Sentiment.NEUTRAL.value
