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
