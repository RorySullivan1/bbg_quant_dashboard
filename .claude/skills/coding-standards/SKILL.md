---
name: coding-standards
description: >
  Baseline cross-project coding conventions — descriptive naming, readability,
  immutability, error handling, type safety, and code-quality / code-smell review —
  with worked examples in both C# and Python (this project's stacks: VSTO/.NET and
  Python). Use this skill as the shared floor when starting a new module, reviewing
  code for quality and maintainability, refactoring toward conventions, enforcing
  naming/structure consistency, or onboarding contributors. Trigger on phrases like
  "review this for quality", "is this clean", "refactor to our standards", "naming
  conventions", "code smells", or any request about baseline code hygiene that isn't
  tied to one framework. It is the shared floor, not the framework playbook — defer
  language- and stack-specific patterns to the dedicated skills (`python-development`,
  `python-review`, `VSTO-development`).
---

# Coding Standards & Best Practices

Baseline coding conventions applicable across projects and languages. This skill is
the **shared floor, not the detailed framework playbook** — it covers the conventions
that hold regardless of stack, with examples in C# and Python (this project's two
languages).

For stack-specific depth, use the dedicated skills instead:

- **`python-development`** — writing new Python (idioms, packaging, project layout).
- **`python-review`** — reviewing Python for bugs, security, and design.
- **`python-maintenance`** — debugging, refactoring, modernizing existing Python.
- **`VSTO-development`** — C#/VB.NET Office add-in patterns and the Office object model.

## When to Activate

- Starting a new project or module
- Reviewing code for quality and maintainability
- Refactoring existing code to follow conventions
- Enforcing naming, formatting, or structural consistency
- Setting up linting, formatting, or type-checking rules
- Onboarding new contributors to coding conventions

## Scope Boundaries

Activate this skill for:

- descriptive naming
- immutability defaults
- readability, KISS, DRY, and YAGNI enforcement
- error-handling expectations and code-smell review

Do **not** use this skill as the primary source for:

- deep framework architecture (ASP.NET request pipelines, WinForms/WPF, Office interop)
- backend service/repository layering or database design
- domain-specific guidance when a narrower skill already exists (defer to
  `python-development`, `python-review`, or `VSTO-development`)

## Code Quality Principles

### 1. Readability First

- Code is read far more often than it is written
- Clear variable and member names
- Self-documenting code preferred over comments
- Consistent formatting (let the formatter own it: `dotnet format` + an `.editorconfig`,
  `ruff format`/`black`)

### 2. KISS (Keep It Simple)

- Simplest solution that works
- Avoid over-engineering and premature optimization
- Easy to understand beats clever

### 3. DRY (Don't Repeat Yourself)

- Extract common logic into well-named methods
- Share utilities across modules
- Avoid copy-paste programming — but don't abstract before the duplication is real

### 4. YAGNI (You Aren't Gonna Need It)

- Don't build features before they're needed
- Avoid speculative generality
- Start simple; refactor when the requirement actually arrives

## Naming

Descriptive names in both languages; follow each language's case convention.

```csharp
// PASS — descriptive
string marketSearchQuery = "election";
bool isUserAuthenticated = true;
double CalculateSimilarity(double[] a, double[] b) { /* ... */ }
bool IsValidEmail(string email) { /* ... */ }

// FAIL — unclear / wrong case
string q = "election";
double similarity(double[] a, double[] b) { /* ... */ }   // method should be PascalCase
```

```python
# PASS — descriptive, snake_case for vars/functions, PascalCase for classes
market_search_query = "election"
is_user_authenticated = True

def calculate_similarity(a: list[float], b: list[float]) -> float: ...

class MarketRepository: ...

# FAIL — unclear / wrong case
q = "election"
def similarity(a, b): ...
class market_repository: ...
```

Conventions: C# → `PascalCase` for types, methods, properties, and public members;
`camelCase` for locals/parameters; `_camelCase` for private fields; `PascalCase` for
constants; `I`-prefix for interfaces. Python → `snake_case` for
functions/variables/modules, `PascalCase` for classes, `UPPER_SNAKE` for constants.
Use verb-first method names (`FetchMarketData` / `fetch_market_data`, `IsValidEmail`).

## Immutability (CRITICAL)

Prefer new values over in-place mutation; it makes change-tracking and concurrency
far safer.

```csharp
// PASS — records + `with` produce new values; init-only/readonly lock the rest
public record User(string Id, string Name);
var updatedUser = user with { Name = "New Name" };

// immutable collections (System.Collections.Immutable)
ImmutableList<Item> updatedItems = items.Add(newItem);

// FAIL — mutating shared state
user.Name = "New Name";        // requires a mutable setter; avoid
sharedList.Add(newItem);       // mutates a list other code holds
```

```python
# PASS — build new values
updated_user = {**user, "name": "New Name"}
updated_items = [*items, new_item]

from dataclasses import dataclass, replace

@dataclass(frozen=True)        # frozen = immutable instances
class User:
    id: str
    name: str

updated = replace(user, name="New Name")

# FAIL — mutate shared state
user.name = "New Name"
items.append(new_item)

# FAIL — the classic mutable-default-argument trap
def add_item(item, bucket=[]):     # `bucket` is shared across all calls!
    bucket.append(item)
    return bucket

# PASS — use None as the sentinel
def add_item(item, bucket=None):
    bucket = [*(bucket or []), item]
    return bucket
```

## Error Handling

Handle failures explicitly; never swallow errors silently.

```csharp
public sealed class DataFetchException : Exception
{
    public DataFetchException(string message, Exception inner) : base(message, inner) { }
}

// PASS — catch the specific exception, preserve the inner cause, log don't Console.Write
public async Task<JsonDocument> FetchDataAsync(string url)
{
    try
    {
        using var response = await _httpClient.GetAsync(url);
        response.EnsureSuccessStatusCode();
        await using var stream = await response.Content.ReadAsStreamAsync();
        return await JsonDocument.ParseAsync(stream);
    }
    catch (HttpRequestException ex)
    {
        _logger.LogError(ex, "Fetch failed for {Url}", url);
        throw new DataFetchException("Failed to fetch data", ex);
    }
}

// FAIL — swallow everything, lose the cause
catch (Exception) { return null; }
```

```python
import logging

logger = logging.getLogger(__name__)

class DataFetchError(Exception):
    """Raised when upstream data cannot be retrieved."""

# PASS — specific exceptions, preserve the cause, log don't print
def fetch_data(url: str) -> dict:
    try:
        response = httpx.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as error:
        logger.error("Fetch failed for %s: %s", url, error)
        raise DataFetchError("Failed to fetch data") from error

# FAIL — bare except hides bugs and swallows KeyboardInterrupt/SystemExit
def fetch_data(url):
    try:
        return httpx.get(url).json()
    except:           # never do this
        return None
```

Rules: catch the **narrowest** exception that fits; preserve the cause (C# inner
exception / Python `raise … from`); use the logging framework, not `Console.Write` /
`print`; define domain exceptions instead of throwing/raising bare `Exception`.

## Async / Concurrency

Run independent work in parallel; await sequentially only when there's a real
dependency.

```csharp
// PASS — start the tasks, then await them together
var usersTask = FetchUsersAsync();
var marketsTask = FetchMarketsAsync();
var statsTask = FetchStatsAsync();
await Task.WhenAll(usersTask, marketsTask, statsTask);
var users = await usersTask;

// FAIL — needlessly sequential (each await blocks the next call)
var users = await FetchUsersAsync();
var markets = await FetchMarketsAsync();
```

```python
import asyncio

# PASS — parallel
users, markets, stats = await asyncio.gather(
    fetch_users(), fetch_markets(), fetch_stats()
)

# FAIL — needlessly sequential
users = await fetch_users()
markets = await fetch_markets()
```

Also: don't `async void` (C#) or fire-and-forget coroutines (Python) — you lose errors.

## Type Safety

Make types explicit; avoid escape hatches (`dynamic`/`object` in C#, `Any` in Python).

```csharp
// PASS — enable nullable reference types; an enum models a closed set
public enum MarketStatus { Active, Resolved, Closed }

public record Market(string Id, string Name, MarketStatus Status, DateTime CreatedAt);

public Task<Market> GetMarketAsync(string id);

// FAIL — dynamic/object defeat the compiler's checks
public Task<object> GetMarketAsync(dynamic id);
```

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

# PASS — annotate; check with mypy/pyright; Literal models a closed set
@dataclass(frozen=True)
class Market:
    id: str
    name: str
    status: Literal["active", "resolved", "closed"]
    created_at: datetime

async def get_market(market_id: str) -> Market: ...

# FAIL — untyped / Any everywhere defeats the checker
async def get_market(market_id):  # no hints
    ...
```

Turn on `<Nullable>enable</Nullable>` (C#) and run `mypy`/`pyright` (Python); reach for
`dynamic`/`object`/`Any` only at true boundaries, and comment why.

## Input Validation

Validate at the boundary with a schema/attributes; don't trust raw input.

```csharp
using System.ComponentModel.DataAnnotations;

public record CreateMarket(
    [Required, StringLength(200, MinimumLength = 1)] string Name,
    [Required] DateTime EndDate,
    [MinLength(1)] IReadOnlyList<string> Categories);

// throws ValidationException on invalid input
Validator.ValidateObject(model, new ValidationContext(model), validateAllProperties: true);
```

```python
from datetime import datetime
from pydantic import BaseModel, Field

class CreateMarket(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    end_date: datetime
    categories: list[str] = Field(min_length=1)

validated = CreateMarket.model_validate(raw_body)   # raises ValidationError on bad input
```

## File Organization

Keep a predictable layout; group by role. A typical Python package:

```
src/
└── taskmaster/
    ├── __init__.py
    ├── api/                # entry points / handlers
    ├── services/          # business logic
    ├── repositories/      # data access
    ├── models/            # dataclasses / pydantic schemas
    └── utils/             # helpers
tests/                     # mirrors src/ layout
pyproject.toml             # deps, tool config (ruff, mypy, pytest)
```

A typical C#/.NET solution groups by project and folder, one public type per file:

```
src/
├── TaskMaster.AddIn/      # VSTO add-in entry points (ThisAddIn, Ribbon)
├── TaskMaster.Core/       # domain models + business logic
│   ├── Models/
│   ├── Services/
│   └── Repositories/
└── TaskMaster.Tests/      # xUnit tests, mirrors Core
```

File naming by language:

```
# C# — PascalCase, one public type per file, interfaces prefixed I
MarketRepository.cs
IMarketRepository.cs

# Python — snake_case modules, tests prefixed test_
market_repository.py
test_market_repository.py
```

## Comments & Documentation

Explain **why**, not **what** — the code already says what.

```csharp
// PASS: why — exponential backoff avoids hammering the API during outages
var delay = Math.Min(1000 * Math.Pow(2, retryCount), 30_000);

/// <summary>Searches markets by semantic similarity.</summary>
/// <param name="query">Natural-language search query.</param>
/// <param name="limit">Maximum number of results.</param>
/// <returns>Markets sorted by similarity score, highest first.</returns>
/// <exception cref="DataFetchException">If the embedding service is unavailable.</exception>
public Task<IReadOnlyList<Market>> SearchMarketsAsync(string query, int limit = 10) { /* ... */ }

// FAIL: noise
count++; // increment counter
```

```python
# PASS: why
# Exponential backoff avoids hammering the API during outages.
delay = min(1000 * 2 ** retry_count, 30_000)

def search_markets(query: str, limit: int = 10) -> list[Market]:
    """Search markets by semantic similarity.

    Args:
        query: Natural-language search query.
        limit: Maximum number of results.

    Returns:
        Markets sorted by similarity score, highest first.

    Raises:
        DataFetchError: If the embedding service is unavailable.
    """
    ...

# FAIL: noise
count += 1  # increment counter
```

Document public APIs (XML doc comments / docstrings); skip comments that restate code.

## Performance

Optimize where it's measured, not speculatively.

```csharp
// PASS — compute an expensive result once; Lazy<T> defers and caches single init
private readonly Lazy<IReadOnlyList<Market>> _sortedMarkets =
    new(() => markets.OrderByDescending(m => m.Volume).ToList());

// PASS — stream large data with yield instead of building a huge list
IEnumerable<Row> ReadRows(string path)
{
    foreach (var line in File.ReadLines(path))
        yield return Parse(line);
}

// PASS — project only the columns you need (EF Core)
var rows = await db.Markets
    .Select(m => new { m.Id, m.Name, m.Status })
    .Take(10)
    .ToListAsync();
```

```python
from functools import lru_cache

# PASS — cache pure, repeated computations
@lru_cache(maxsize=512)
def cosine_similarity_key(vector_id: str) -> float: ...

# PASS — stream large data with a generator instead of building a huge list
def read_rows(path: str):
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            yield parse(line)

# PASS — fetch only the columns you need (any ORM / query builder)
rows = session.query(Market.id, Market.name, Market.status).limit(10).all()
```

Don't materialize large sequences you can stream; enumerate a query once; select only
the columns/fields you use.

## Testing

### AAA pattern (Arrange / Act / Assert)

```csharp
[Fact]
public void CalculatesSimilarityCorrectly()
{
    // Arrange
    double[] a = [1, 0, 0];
    double[] b = [0, 1, 0];

    // Act
    var similarity = CalculateCosineSimilarity(a, b);

    // Assert
    Assert.Equal(0, similarity);
}
```

```python
def test_calculates_similarity_correctly():
    a, b = [1, 0, 0], [0, 1, 0]                 # Arrange
    similarity = calculate_cosine_similarity(a, b)  # Act
    assert similarity == 0                      # Assert
```

### Descriptive test names

```csharp
// PASS
[Fact] public void ReturnsEmptyListWhenNoMarketsMatchQuery() { }
[Fact] public void ThrowsWhenApiKeyIsMissing() { }

// FAIL
[Fact] public void Works() { }
[Fact] public void TestSearch() { }
```

Cover input variations without copy-paste: `[Theory]` + `[InlineData]` (xUnit) or
`pytest.mark.parametrize` (Python).

## Code Smell Detection

### 1. Long functions — split by responsibility

```python
# FAIL: one function doing everything
def process_market_data(): ...   # 100 lines

# PASS: compose small, named steps
def process_market_data(raw):
    validated = validate(raw)
    transformed = transform(validated)
    return save(transformed)
```

### 2. Deep nesting — use guard clauses / early returns

```csharp
// FAIL: arrow code
if (user != null)
    if (user.IsAdmin)
        if (market is { IsActive: true })
            DoSomething();

// PASS: guard clauses
if (user is null || !user.IsAdmin) return;
if (market is not { IsActive: true }) return;
DoSomething();
```

### 3. Magic numbers — name them

```python
# FAIL
if retry_count > 3: ...
sleep(0.5)

# PASS
MAX_RETRIES = 3
DEBOUNCE_DELAY_SECONDS = 0.5
if retry_count > MAX_RETRIES: ...
sleep(DEBOUNCE_DELAY_SECONDS)
```

Other smells to watch: duplicated logic (DRY violation), boolean/positional flag
parameters, mutable global state, and `dynamic`/`object`/`Any` spreading through a
module.

---

**Remember:** code quality is not negotiable. Clear, maintainable code enables rapid
development and confident refactoring — the baseline here is what every stack-specific
skill builds on top of.
