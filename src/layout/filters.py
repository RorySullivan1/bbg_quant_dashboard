"""The one filter helper the grids still need.

What used to live here — `_checkbox_group`, `_section_label` and `_q_row` —
built the Single Strategy *Filters* accordion: a scrollable checkbox column
per dimension and nine `≥ / ≤` threshold rows. Epic #341 replaced the Multi
tab's copy with the *Filter* bar and the table's own comparison filter row,
and #365 did the same for Single Strategy, which was their last caller. They
went with `filter_panel.py`.

`_ticker_options` stays because it is not a filter at all: it is the
`(label, ticker)` pairing the benchmark registry offers the catalog's indices
through, and the shape a ticker is named in wherever one has to be chosen
from a list.
"""

from __future__ import annotations

import pandas as pd


def _ticker_options(df: pd.DataFrame) -> list[tuple[str, str]]:
    return [(f"{r['ticker']} — {r['name']}", r["ticker"]) for _, r in df.iterrows()]
