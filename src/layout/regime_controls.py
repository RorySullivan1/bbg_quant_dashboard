"""The regime controls, as one object both tabs construct (#363).

Regime resolution had exactly one implementation and it lived on
`PlatformAnalytics`: the four widgets, the indicator lookup, the bucket
resolution and the visibility sync were all methods of the card that happened
to need them first. Epic #363 gives two Single Strategy charts the same
question to ask, and the risk it names is the obvious one — copying four
methods into a second class, where the two copies then drift.

So they move here, as `RegimeControls`. The card holds one and delegates;
Single Strategy holds its own. What the two share is the *rule*: which days
the regime selects. What they do not share is the widgets, because two tabs
each conditioning their own chart is two independent selections.

**The toggle is gated in `indicator()`**, which returns None while the box is
clear. That is already what an absent indicator returns, so the unconditioned
view is a path both states share rather than a second branch at every render
(v0.9.33) — and no future reader of the indicator can miss the switch.

Pure widget + lookup: nothing here fetches. Every indicator ticker rides the
single startup request, because `REGIME_TICKERS` is derived from the specs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ipywidgets as W
import pandas as pd

from ..config import REGIME_SPECS, LevelRegime, TercileRegime
from ..stats import daily_returns, regime_mask, rolling_autocorr, tercile_bounds
from .rails import ChipGroup

if TYPE_CHECKING:
    # `state.py` reaches this module through its own imports, so a runtime
    # import of `DashboardState` would hit a partially initialized module.
    from .state import DashboardState


def regime_bucket_options(regime_type: str) -> list[tuple[str, object]]:
    """Bucket-chip options for a regime: ``(label, (low, high))`` for the
    fixed-level mode, ``(label, tercile_key)`` for the tercile modes."""
    spec = REGIME_SPECS[regime_type]
    if isinstance(spec, LevelRegime):
        return [(label, (low, high)) for label, low, high in spec.buckets]
    return [(label, key) for label, key in spec.bucket_labels]


def regime_window_mask(
    indicator: pd.Series | None,
    index: pd.Index,
    low: float | None,
    high: float | None,
) -> pd.Series:
    """Boolean mask over ``index``: the regime bucket, or **all-True** when
    there is no indicator or no bucket.

    The all-True fallback is the unconditioned view, and it is the same answer
    for three different situations — the regime is switched off, its ticker is
    not in the cache, or its bucket has not resolved. Collapsing them here is
    what lets every caller take one path.
    """
    if indicator is None or indicator.empty or low is None or high is None:
        return pd.Series(True, index=index)
    return regime_mask(indicator.reindex(index), low, high)


class RegimeControls:
    """The four regime widgets and the rules that read them.

    `on` heads the section and is **off by default** (v0.9.33): every bucket
    is a subset of the window, so an always-on regime meant a chart opened on
    `VIX < 15` with most of its days dropped, nothing on screen saying the
    sample had been narrowed, and no way to ask for the plain view.

    A `Checkbox` rather than a fourth chip in the type group: an "Off" chip
    beside Volatility / Trend / Rate-level would read as a fourth regime, and
    the state it carries is a different question from *which* regime — which
    is why unticking it keeps the type and bucket the user last chose.

    `buckets` is optional. A chart that draws **all three** buckets at once
    (#370) has no single bucket to select, so it builds without one and
    `resolve_bucket` is simply never asked.

    `state` is optional too, and for a different reason — see its comment in
    `__init__`.
    """

    def __init__(
        self,
        state: DashboardState | None = None,
        *,
        sample_days: int | None = None,
        buckets: bool = True,
    ) -> None:
        #: **May be None.** A pane builds its controls at construction and is
        #: handed its state after, and a `SingleAnalysisPane` field that is
        #: None is a renderer's `AttributeError` waiting to happen (#216). So
        #: the widgets always exist and the *lookups* answer "no regime"
        #: until a state arrives — which is the same answer an absent
        #: indicator gives, so nothing downstream needs a third case.
        self.state = state
        #: How many trailing days a tercile's quantiles are taken over. None
        #: means the whole indicator — the caller sets it when its chart has a
        #: window of its own, as the Platform card's does.
        self.sample_days = sample_days
        self.on = W.Checkbox(
            value=False,
            description="Condition on regime",
            indent=False,
            layout=W.Layout(width="auto", margin="0 0 2px 0"),
        )
        self.types = ChipGroup(list(REGIME_SPECS.keys()), row=True)
        # Source stays a dropdown: its options are the live benchmark registry
        # or a region list, and a dropdown is the right control for a long
        # list (#331 decision 13, #302's reasoning).
        self.source = W.Dropdown(
            options=[("—", "")],
            value="",
            description="Source",
            style={"description_width": "60px"},
            layout=W.Layout(width="240px"),
        )
        self.buckets: ChipGroup | None = None
        if buckets:
            options = regime_bucket_options(self.types.value)
            self.buckets = ChipGroup(options, value=options[0][1], row=True)
        # Start matching the unticked box. `sync` owns this from `wire`
        # onwards but cannot run here: its source options come from the
        # benchmark registry, which is not populated at construction.
        for dependent in self.dependents:
            dependent.layout.display = "none"

    @property
    def dependents(self) -> tuple[W.Widget, ...]:
        """The controls that only apply while the regime is on."""
        if self.buckets is None:
            return (self.types, self.source)
        return (self.types, self.source, self.buckets)

    # --- resolution -----------------------------------------------------------

    def indicator(self) -> pd.Series | None:
        """The indicator series from the cache, per the active regime's shape.

        None when the regime is **switched off** or its ticker(s) are absent —
        the unconditioned view either way, which is the whole reason the
        toggle is gated here rather than at each render.
        """
        if not self.on.value or self.state is None:
            return None
        spec = REGIME_SPECS.get(self.types.value)
        if spec is None:
            return None
        prices = self.state.universe_prices
        if isinstance(spec, TercileRegime) and spec.kind == "autocorr":
            ticker = self.source.value
            if not ticker or ticker not in prices.columns:
                return None
            rets = daily_returns(prices[[ticker]])[ticker]
            return rolling_autocorr(rets, window=spec.autocorr_window)
        # Both remaining shapes read a raw level; only the ticker's source
        # differs — a tercile regime's comes from its dropdown, a level
        # regime's is fixed.
        ticker = spec.ticker if isinstance(spec, LevelRegime) else self.source.value
        if not ticker or ticker not in prices.columns:
            return None
        return prices[ticker]

    def bucket_bounds(self, key: object) -> tuple[float | None, float | None]:
        """``(low, high)`` for one bucket of the active regime.

        A fixed-level regime's bounds *are* the key; a tercile regime's are
        derived from the live indicator's 1/3 and 2/3 quantiles over
        `sample_days`. ``(None, None)`` when no indicator is available, which
        `regime_window_mask` reads as the unconditioned view.
        """
        spec = REGIME_SPECS.get(self.types.value)
        if isinstance(spec, LevelRegime):
            low, high = key
            return (low, high)
        indicator = self.indicator()
        if indicator is None:
            return (None, None)
        sample = (
            indicator.tail(self.sample_days)
            if self.sample_days is not None
            else indicator
        )
        return tercile_bounds(sample, key)

    def resolve_bucket(self) -> tuple[float | None, float | None]:
        """The bounds of the bucket the chips have selected."""
        if self.buckets is None:
            return (None, None)
        return self.bucket_bounds(self.buckets.value)

    def bucket_keys(self) -> list[tuple[str, object]]:
        """Every bucket of the active regime, as ``(label, key)``.

        What a chart drawing all three needs, and what `sync` repopulates the
        chips from — one source, so a bucket cannot exist on the chips and
        not in the chart.
        """
        return regime_bucket_options(self.types.value)

    def selector_options(self) -> list[tuple[str, object]]:
        """The indicator-source options for the active regime.

        Trend sources its list from the **live** benchmark registry rather
        than one frozen into `REGIME_SPECS` at import, so a benchmark added at
        runtime is offered here too. Rate-level carries a literal `selector`;
        a fixed-level regime has one ticker and so offers no source at all.
        """
        spec = REGIME_SPECS.get(self.types.value)
        if not isinstance(spec, TercileRegime):
            return []
        if spec.selector_source == "benchmarks":
            registry = getattr(self.state, "benchmarks", None)
            return registry.options(labeled=True) if registry is not None else []
        return list(spec.selector)

    # --- the visibility sync --------------------------------------------------

    def sync(self) -> None:
        """Repopulate the source and bucket controls, and show / hide them.

        Re-run on a benchmark-registry change too, so this keeps the current
        source **selected** whenever it survives into the new option list.
        Switching regime type still falls back to the first option, since the
        old value belongs to a different domain (a benchmark ticker is not a
        rate region).

        The on/off toggle runs through here for the same reason: while it is
        off, *which* regime and *which* bucket describe nothing being drawn.
        They are hidden rather than rebuilt — the bar's own rule (#331
        decision 3) — so switching the regime back on finds the type, source
        and bucket the user last chose still chosen.
        """
        active = bool(self.on.value)
        selector = self.selector_options()
        if selector:
            previous = self.source.value
            values = [value for _, value in selector]
            self.source.options = selector
            self.source.value = previous if previous in values else selector[0][1]
        if self.buckets is not None:
            options = self.bucket_keys()
            # Preserve the active bucket across a registry change, likewise.
            previous_bucket = self.buckets.value
            keys = [value for _, value in options]
            self.buckets.set_options(
                options,
                value=previous_bucket if previous_bucket in keys else options[0][1],
            )
        # The source needs both conditions: a fixed-level regime offers no
        # source to pick even while the regime is on.
        self.source.layout.display = "" if active and selector else "none"
        for control in self.dependents:
            if control is self.source:
                continue
            control.layout.display = "" if active else "none"
