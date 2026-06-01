---
name: python-deployment
description: Expert Python deployment, packaging, and operations — preparing Python code to ship to production, including pyproject.toml setup, Dockerfiles, dependency pinning, environment configuration, observability (logging, metrics, tracing), CI/CD pipelines, and platform-specific deployment (Lambda, Cloud Run, Kubernetes, ECS, bare metal). Use this skill whenever the user wants to package, containerize, deploy, ship, or operationalize a Python application. Trigger on phrases like "Dockerfile for", "deploy to", "package this", "production-ready", "pyproject.toml", "requirements.txt", "CI/CD", "GitHub Actions for Python", "AWS Lambda Python", "structured logging", "12-factor", "health check", or any work focused on getting Python from "works on my machine" to "runs in production."
---

# Python Deployment

Expert Python deployment and operations. The job is to get Python code running reliably in production — which means packaging, containerization, configuration, observability, and CI/CD that don't surprise the team at 2 AM.

## Core principles

- **Reproducibility over convenience.** A build that works today and breaks next month because a dependency floated is not a build. Pin everything.
- **Twelve-factor by default.** Config from environment variables, logs to stdout, stateless processes. Don't fight this unless you have a specific reason.
- **Smallest viable image, smallest viable surface.** Bigger images are slower to deploy and have more vulnerabilities. Don't ship build tools to production.
- **Observability is not optional.** A service you can't debug in production will be debugged in production anyway — just badly.
- **Match the deployment target.** Lambda, container, and bare metal have different constraints. Don't apply a Kubernetes pattern to a cron job.

## What to ask before deployment work

For non-trivial deployment work, confirm:

1. **Deployment target** — Lambda, Cloud Run, ECS/Fargate, Kubernetes, EC2/VM, bare metal, on-prem?
2. **Python version** — and whether the target platform constrains it (Lambda runtimes, Alpine quirks, etc.).
3. **Stateful vs stateless** — does the service hold state, depend on local disk, or need sticky sessions?
4. **Traffic pattern** — request/response, batch, scheduled, streaming, long-lived connections?
5. **Scale** — single instance vs autoscaled fleet? Cold-start sensitive?
6. **Secrets management** — env vars, AWS Secrets Manager, Vault, K8s secrets?
7. **CI/CD platform** — GitHub Actions, GitLab CI, CircleCI, Jenkins, Buildkite?
8. **Compliance constraints** — SOC 2, HIPAA, FedRAMP can dictate base images, logging, network controls.

For small clear requests ("write me a Dockerfile for this Flask app"), make a reasonable assumption, state it, and write it.

## Packaging

### pyproject.toml (PEP 621)

Use `pyproject.toml` for all new projects. Don't use `setup.py` for new code.

Minimum viable structure:

```toml
[project]
name = "myapp"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110,<0.120",
    "pydantic>=2.6,<3",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "ruff",
    "mypy",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Choose a build backend deliberately: `hatchling` (modern, simple), `setuptools` (familiar, ubiquitous), `poetry-core` (if using Poetry), `flit-core` (minimal). For pure-Python projects, hatchling is a solid default.

### Dependency pinning

There are two layers and they have different jobs:

- **`pyproject.toml`** — abstract dependencies with version *ranges*. What your code needs.
- **Lockfile** (`uv.lock`, `poetry.lock`, or `requirements.txt` with hashes) — exact versions, transitively resolved. What you actually install.

For production deployments, install from the lockfile. Don't `pip install` from `pyproject.toml` directly in prod — you'll get a different resolution every time.

Generating a hashed `requirements.txt` with `uv` (recommended) or `pip-tools`:

```bash
uv pip compile pyproject.toml -o requirements.txt --generate-hashes
```

### Separate dev and runtime dependencies

Production images shouldn't include `pytest`, `mypy`, `ruff`, `ipython`, or anything else that's only used for development. Use optional dependency groups, separate requirements files, or build stages to keep them out.

## Containerization

### Multi-stage Dockerfile (the pattern that matters)

```dockerfile
# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder
WORKDIR /app

# Install build deps only in the builder stage
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a venv that we'll copy to the runtime stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY . .
RUN pip install --no-deps --no-cache-dir .

# --- Runtime stage ---
FROM python:3.12-slim AS runtime

# Create non-root user
RUN groupadd --system app && useradd --system --gid app --no-create-home app

# Copy the venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER app
WORKDIR /app

EXPOSE 8000
CMD ["python", "-m", "myapp"]
```

### Container rules of thumb

- **Pin base image tags.** `python:3.12-slim` is OK; `python:3.12.4-slim-bookworm` is better. Never `python:latest`.
- **Run as non-root.** Always. Many compliance regimes require it; even when they don't, it's free defense in depth.
- **Don't write the app code into `/`.** Use `/app` or similar.
- **Set `PYTHONDONTWRITEBYTECODE=1`** to skip `.pyc` generation, and `PYTHONUNBUFFERED=1` so logs flush.
- **Use `.dockerignore`** to keep `.git`, `__pycache__`, `.venv`, `.env`, `tests/`, and IDE files out of the image.
- **Avoid Alpine for Python** unless you really need the size. `musl` causes obscure problems with manylinux wheels — `slim` (Debian-based) is usually a better default.
- **One process per container.** Don't run a database, a web server, and a cron in the same container.

### .dockerignore template

```
.git
.gitignore
.dockerignore
.venv
venv
__pycache__
*.pyc
*.pyo
.pytest_cache
.mypy_cache
.ruff_cache
.coverage
htmlcov
.env
.env.*
!.env.example
*.md
!README.md
tests/
docs/
```

## Configuration

### Twelve-factor: config from environment

Don't hardcode environment-specific values (DB URLs, API keys, feature flags). Read them from environment variables.

Use `pydantic-settings` for typed config:

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    log_level: str = "INFO"
    api_key: str = Field(..., repr=False)  # don't print this
    max_workers: int = 4


settings = Settings()
```

### Secrets

- **Never commit `.env`.** Provide `.env.example` with placeholder values.
- **Don't bake secrets into images.** Pass them at runtime via env vars or a secrets manager.
- **Don't log secrets.** Pydantic's `Field(repr=False)` and structlog's processors can help; explicit redaction lists also help.
- **Rotate secrets** that have leaked even once. Git history is forever.

## Observability

### Logging

Use **structured logging** for production services. JSON logs are easy for tools to parse; unstructured logs are not.

Stdlib approach (no extra deps):

```python
import logging
import sys
from pythonjsonlogger import jsonlogger  # python-json-logger

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(jsonlogger.JsonFormatter(
    "%(asctime)s %(name)s %(levelname)s %(message)s"
))
logging.basicConfig(level=logging.INFO, handlers=[handler])
```

Or `structlog` for richer structured logging.

Logging rules:

- Log to **stdout/stderr**, never to files inside the container. Let the platform handle log collection.
- Include a **request ID / correlation ID** in every log line for a request. This is the single most useful field you'll add.
- **Don't log sensitive data**: passwords, tokens, full request bodies, PII. Audit your log statements.
- **Use levels deliberately**: `DEBUG` for development noise, `INFO` for routine events, `WARNING` for unexpected-but-handled, `ERROR` for failures, `CRITICAL` rarely.

### Health checks

Web services need a `/healthz` (or `/health`) endpoint that returns 200 when the process is up. For Kubernetes, distinguish:

- **Liveness** — "is the process stuck?" Restart if it fails.
- **Readiness** — "can it serve traffic?" Pull from load balancer if it fails (e.g., DB connection lost).

Don't include expensive dependency checks in liveness probes — you don't want a slow database to cause a restart loop.

### Metrics & tracing

For production services with real traffic, consider:

- **Metrics:** `prometheus-client` for Prometheus, or platform-native (CloudWatch, Datadog).
- **Tracing:** OpenTelemetry. The Python autoinstrumentation handles common frameworks (FastAPI, Flask, requests, SQLAlchemy) without code changes.

Don't add these on day one for a simple service. Add them when "I don't know why it's slow" becomes a real question.

## CI/CD

### Minimum viable pipeline

Every Python project's CI should run, at minimum:

1. **Lint** — `ruff check .`
2. **Format check** — `ruff format --check .` (or `black --check .`)
3. **Type check** — `mypy` or `pyright`
4. **Tests** — `pytest` (with coverage if you care)
5. **Security** — `pip-audit` for dependency vulnerabilities, `bandit` for code patterns
6. **Build** — actually build the artifact (wheel, container) so CI catches packaging errors

### Test matrix

Test against the **lowest and highest** Python versions you support. If you support 3.10–3.12, run 3.10 and 3.12 — middle versions rarely catch unique bugs.

### GitHub Actions skeleton

```yaml
name: ci
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - name: Install uv
        run: pip install uv
      - name: Install deps
        run: uv pip install --system -r requirements.txt -r requirements-dev.txt
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy .
      - run: pytest --cov
      - run: pip-audit
```

### Reproducible builds

- **Pin everything** including the Python version (`.python-version` or matrix).
- **Use lockfiles** in CI installs.
- **Pin GitHub Actions** by SHA, not tag, for security-sensitive workflows.
- **Don't branch on `main` vs `dev`** in app code. Use config / environment, not code paths.

## Platform-specific notes

### AWS Lambda

- Cold starts matter. Minimize import time; lazy-import heavy libs inside the handler if possible.
- Package size limits: 250 MB unzipped (layers + function). Use container image deployments (10 GB) if you exceed this.
- The runtime is read-only except `/tmp` (512 MB by default, up to 10 GB).
- Use Powertools for AWS Lambda (Python) for logging, tracing, and metrics if you're going deep on Lambda.

### Cloud Run / container PaaS

- Listen on `$PORT` (Cloud Run sets it; default 8080).
- Stateless: instances can be killed any time. Don't rely on local disk or in-memory state across requests.
- Cold starts exist but are cheaper than Lambda.

### Kubernetes

- Liveness + readiness probes (separate, as above).
- Resource requests and limits — don't deploy without them.
- `terminationGracePeriodSeconds` long enough for in-flight requests to finish.
- `SIGTERM` handling in your app — `uvicorn`/`gunicorn` handle it; custom code may not.

### Bare metal / VMs

- Use a process manager (`systemd`, `supervisord`) — don't run `python app.py` in a screen session.
- Rotate logs (`logrotate`) if writing to files; better, use `journald` or ship to a log aggregator.
- `gunicorn` or `uvicorn` for WSGI/ASGI servers, not the framework's dev server.

## Output format

When delivering deployment artifacts:

- **One file per artifact** (Dockerfile, .dockerignore, pyproject.toml, CI yaml). Don't smush them.
- **Inline comments** explaining non-obvious choices (why this base image, why this flag).
- **State assumptions** at the top: "Assuming Python 3.12, deploying to ECS Fargate, no GPU."
- **Note next steps** the user has to do themselves: register the ECR repo, set the IAM role, configure the load balancer.

## Examples

**Example 1 — "Dockerfile for my Flask app":**

Ask: Python version? Production or dev? Then write a multi-stage Dockerfile with a non-root user, a slim base image, and `gunicorn` (not `flask run`). Include a `.dockerignore`. Note that `requirements.txt` should be pinned with hashes for production.

**Example 2 — "Help me deploy this to Lambda":**

Ask: deployment method (zip vs container image)? Existing infrastructure (IaC tool)? Cold-start tolerance? Recommend the container image route for anything non-trivial; show the Dockerfile (using the AWS base image), the handler signature, and how to keep imports cheap.

**Example 3 — "Make this 12-factor":**

Audit: where's config coming from? Where do logs go? Is state local or external? Then change one thing at a time — don't rewrite the app.

## Out of scope

- Don't write infrastructure-as-code (Terraform, CloudFormation, Pulumi) unless asked. Deployment ≠ infrastructure provisioning.
- Don't recommend Alpine-based Python images as a default. The pain isn't worth the size savings for most apps.
- Don't add observability tooling the user didn't ask for. A 50-line script doesn't need OpenTelemetry.
- Don't bake secrets, API keys, or environment-specific URLs into images or repos.
