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
conda activate bbg_quant
voila dashboard.ipynb
```
`bql` is injected by BQuant's own kernel on a terminal, so this conda env is
for local/off-terminal work only.

`src/bql_client.py` detects whether `bql` is importable. Off-terminal it falls
back to a deterministic synthetic price series keyed by ticker, so the
dashboard always renders end-to-end.
