# Run instructions

Part of the `bbg_quant_dashboard` repo memory — split out of `CLAUDE.md`.

**On a BBG terminal (BQuant):**
1. Open `dashboard.ipynb` inside BQuant.
2. Run the single cell — `build_app()` returns the rendered VBox.

**Locally (off-terminal, mock prices):**
```
pip install -r requirements.txt
voila dashboard.ipynb
```

Or provision an isolated interpreter with conda via `environment.yml` (pins
Python 3.11 — required by the `enum.StrEnum` tokens in `src/style.py` — and
installs the deps through pip so the `requirements.txt` pins stay the single
source of truth):
```
conda env create -f environment.yml
conda activate bbg-quant
voila dashboard.ipynb
```
`bql` is injected by BQuant's own kernel on a terminal, so this conda env is
for local/off-terminal work only.

`src/price_source.py` picks the source: `BqlPriceSource` when `bql` is
importable, else `MockPriceSource`, so the dashboard always renders end-to-end.
The mock's series are seeded from a **digest** of the ticker (v0.9.16 #235), so
they are identical in every process — two runs of the same code render the same
numbers, which is what makes an off-terminal before/after comparison meaningful.
(Until #235 the seed was `hash(ticker)`, which Python randomizes per process:
every restart showed different numbers.)


## The terminal runs plotly 5.23.0 — this environment does not (v0.9.26)

`hoverlabel.showarrow` is valid here and **not** in 5.23.0, where it raises
`Invalid property specified for object of type plotly.graph_objs.layout.Hoverlabel: 'showarrow'`
while the figure is being built. Under Voila that is a blank page, not a chart
that looks wrong: the notebook is executed to completion and the page is
assembled from the result, so a raise inside `build_app()` takes the whole
dashboard down.

The trap is that it *was* checked. Enumerating `_valid_props` here proves a
property exists **here**, and the suite runs against the same local plotly, so
neither says anything about the terminal.

**Check against 5.23.0 directly instead.** It installs side by side without
disturbing this environment:

```bash
pip install --target /tmp/plotly523 plotly==5.23.0
python3 - <<'EOF'
import sys; sys.path.insert(0, "/tmp/plotly523")
import plotly.graph_objects as go
go.Figure(layout=dict(hoverlabel=dict(showarrow=False)))   # raises on 5.23.0
EOF
```

Everything the analytics card builds has been run through that and is valid on
5.23.0: the full `go.Icicle` (ids / parents / `branchvalues` / `maxdepth` /
`level` / `tiling.orientation` / the marker's colorscale, `cmid`, `cmin`,
`cmax` and `colorbar.title.text`), the `Scatter3d` scene axes (`zeroline*`,
`showline`, `linecolor`, `gridcolor`, `backgroundcolor`, `aspectmode`), and
the Strip's numeric axis with `tickmode="array"` and `showgrid=False`, plus its
dashed zero shape and the `layer="below"` day dividers added in v0.9.32.

`tests/test_platform.py` holds an allowlist of the `hoverlabel` properties old
enough for it, so a newer one cannot be added silently — but the allowlist is
a backstop for one object. The command above is the check for anything else.

**Also on the terminal, and unrelated:** plotly figures do not draw under a
*headless local* Voila here — the widget's div and layout appear but no trace
reaches it. Checked against `v0.9.23`, where the sunburst is equally blank, so
it predates epic #331. `ipydatagrid` and `itables` are unaffected, so an
off-terminal pass is still worth running for everything that is not a plotly
figure. What it cannot do is confirm a chart, which is exactly the class of
defect a widget-tree assertion cannot see either (#255). **For the Platform
card's charts, a terminal is the only evidence.**
