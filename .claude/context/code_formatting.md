# Code formatting & lint

Part of the `bbg_quant_dashboard` repo memory — split out of `CLAUDE.md`.

Style is enforced by **ruff** (lint) + **black** (format, 88-char), configured
in `pyproject.toml` (tooling config only — not a packaging manifest). Dev tools
are pinned in the `requirements.txt` dev-tooling section. Run before committing:

```
ruff check src tests
black src tests    # or: black --check src tests
```

Black owns line width (ruff ignores `E501`). The style-token enums in
`src/style.py` use the stdlib `enum.StrEnum` base (Python 3.11+) so members
interpolate cleanly into f-strings.

A `.pre-commit-config.yaml` wires the same tools as `repo: local` hooks (so
versions match `requirements.txt`/CI): `ruff check --fix` + `black` on commit,
`pytest -q` on push. Opt in once with `pre-commit install` (and
`pre-commit install --hook-type pre-push` for the test hook); run everything
with `pre-commit run --all-files`.
