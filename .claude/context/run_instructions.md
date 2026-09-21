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


## A limit of the off-terminal render (found v0.9.24, epic #331)

**Plotly `FigureWidget` figures do not draw under a headless local Voila.**
The widget's div is created and the layout is applied — axes, grid, the dark
theme — but no trace reaches it: the browser's `div.data` is empty and the
chart area shows an empty cartesian plot whatever the figure holds.

Checked both ways before it was believed: the same probe against `v0.9.23`,
before any of epic #331's charts existed, finds the **sunburst** equally
blank. So it is the environment, not a regression, and it predates the epic
by a long way.

The `ipydatagrid` and `itables` widgets are unaffected — the catalog table and
the chart's points table both render — so an off-terminal pass is still worth
running for everything that is not a plotly figure. What it cannot do is
confirm a chart, which is precisely the class of defect a widget-tree
assertion cannot see either (#255). **For the Platform card's charts, a
terminal is the only evidence**, and `testing_notes.md`'s checklist for that
card should be read as terminal-only.

Not yet diagnosed. The most likely cause is the one #269 records for widget
packages generally: a labextension is enumerated once at server startup, and
`jupyterlab-plotly` may not be reaching this Voila the way `anywidget` does.
