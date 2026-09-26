# Phase 182: Security classification hierarchy (todo 384) - Pattern Map

**Mapped:** 2026-09-25
**Files analyzed:** 12 (new + modified)
**Analogs found:** 12 / 12

RESEARCH.md already did deep precedent-hunting for this phase (Patterns 1-5, Anti-Patterns,
Don't-Hand-Roll). This file re-verifies each cited analog by reading the actual source and
pins exact excerpts/line numbers for the planner to copy from directly — it does not
re-derive the architecture, only grounds it in real code.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `production/migrations/364_indicagent_v1_classification_scheme.sql` | migration | batch (schema + seed DML) | `production/migrations/363_sector_label_fixes.sql` | role-match (guard idiom exact; schema shape from design doc, no live 3-table analog) |
| `src/config/classification_service.py` | service (cached read-layer library) | CRUD (read-only, prewarm-then-lookup) | `src/config/vocabulary_service.py` | exact |
| `src/core/classification_access.py` | NOT BUILT in phase 182 (decision in 182-01: no consumer yet, and an unregistered process-wide wrapper would silently return `unclassified`; builders read via a SQL fragment instead) | - | `src/core/vocabulary_access.py` | deferred |
| `src/config/instrument_onboarding.py` (modify: add classification gate) | service (transactional write path) | CRUD | itself — `onboard_instrument()`'s existing `metadata`/`metadata_skip_reason` gate, same file | exact (same function, mirror an existing arg pair) |
| `scripts/infrastructure/classification_ibkr_sourcing.py` | utility (one-off sourcing script) | file-I/O / batch (IBKR fetch -> CSV/JSON for human review) | `src/providers/ibkr.py::qualify_instrument()` (call site to extend) + `scripts/infrastructure/*` one-off sourcing script family | role-match |
| `src/providers/ibkr.py` (modify: new method for industry/category/subcategory) | provider (external API wrapper) | request-response | itself — `qualify_instrument()`'s `reqContractDetailsAsync` call, same file | exact (same file, adjacent method) |
| `src/config/settings.py` (modify: `_build_instrument_from_db_row` / non-futures builder) | transform (DB row -> domain object) | CRUD (read) | itself — the sibling non-futures builder branch, same file | exact (same file, same pattern, different branch) |
| `src/intelligence/pipeline/cache_manager.py` (modify: `_instrument_from_row`) | transform (DB row -> domain object) | CRUD (read) | itself + `settings.py`'s equivalent builder | exact |
| `tests/unit/test_classification_service.py` | test | request-response (pure-Python assertions) | `tests/unit/test_vocabulary_service.py` | exact |
| `tests/unit/_classification_fakes.py` | test (shared double) | request-response | `tests/unit/_vocabulary_fakes.py` | exact |
| `tests/integration/test_instrument_classification_coverage.py` | test (live-DB) | request-response | `tests/integration/test_instrument_registry.py` | exact |
| `tests/integration/test_classification_schema.py` (optional, may fold into coverage test) | test (live-DB, schema shape) | request-response | `tests/integration/test_instrument_registry.py` (trigger-existence check, lines 39-62) | role-match |

## Pattern Assignments

### `production/migrations/364_indicagent_v1_classification_scheme.sql` (migration, batch)

**Analog:** `production/migrations/363_sector_label_fixes.sql` (full file read, 66 lines) for
the guard idiom; schema shape comes from the design doc
(`docs/research/stratification-security-classification-hierarchy.md`) per D-01, since no
live 3-table analog exists in this codebase yet.

**Transaction + guard pattern** (`363_sector_label_fixes.sql` lines 15-16, 54-66):
```sql
BEGIN;

-- ... DDL / seed INSERT/UPDATE statements ...

DO $$
DECLARE
    bad TEXT;
BEGIN
    SELECT string_agg(symbol, ', ' ORDER BY symbol) INTO bad
    FROM instruments
    WHERE compute_eligible AND coalesce(contract_details->>'sector', '') IN ('', 'equity');
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'compute_eligible instruments still without a real sector: %', bad;
    END IF;
END $$;

COMMIT;
```
Copy this shape exactly for D-09's seed-time coverage guard, substituting the
`NOT EXISTS (SELECT 1 FROM instrument_classification ic WHERE ic.symbol = i.symbol
AND ic.scheme = 'indicagent_v1' AND ic.valid_to IS NULL)` predicate given in
RESEARCH.md's Pattern 4. Also add a second `DO $$ ... RAISE EXCEPTION` block for the
node-immutability guard (D-01: "the seed crashes on disagreement" if a code's parent/level
disagrees with a prior definition) — same `RAISE EXCEPTION` idiom, different predicate
(compare inserted `parent_code`/`level` against any pre-existing `classification_node` row
for the same `code`).

**Point-in-time close-and-insert pattern** (for `instrument_classification`'s seed rows and
any future reclassification-writing code, not the migration seed's `valid_from` itself,
which is the fixed build date per D-07):

**Analog:** `services/context_writer.py` lines 46-62 (full read):
```python
# Close out the currently-active snapshot for this (symbol, event_type) before
# inserting the new one — sets valid_to to the new row's valid_from.
_CLOSE_PRIOR_SNAPSHOT_SQL = """
UPDATE ctx_snapshots
   SET valid_to = $3
 WHERE symbol IS NOT DISTINCT FROM $1
   AND event_type = $2
   AND valid_to IS NULL
"""

_UPSERT_CTX_SNAPSHOT_SQL = """
INSERT INTO ctx_snapshots (symbol, event_type, valid_from, valid_to, ctx)
VALUES ($1, $2, $3, NULL, $4)
ON CONFLICT (symbol, event_type, valid_from) DO UPDATE
    SET ctx = EXCLUDED.ctx,
        valid_to = NULL
"""
```
This is the "close prior row, insert new row" idiom to mirror for any future
reclassification write path (out of this phase's seed-only scope per D-07, but the shape
any later write helper must follow). **Do not copy `ctx_snapshots`' `ON CONFLICT` upsert
verbatim** — `instrument_classification`'s PK is `(symbol, scheme, valid_from)` per D-01/
Pitfall 1, and a true point-in-time table never upserts an existing closed row, only closes
the old one (`UPDATE ... SET valid_to`) and inserts a genuinely new row. `ctx_snapshots`'
`ON CONFLICT (symbol, event_type, valid_from) DO UPDATE` is there to make same-instant
re-delivery idempotent, not to permit overwriting history — keep that same idempotency
guarantee if the seed migration's own INSERT is ever re-run, but do not generalize it into
a mutable-history pattern.

**Anti-pattern (do not copy):** `instrument_tags`' schema. `PRIMARY KEY (symbol, tag)` even
though it carries `valid_from`/`valid_to` (Phase 175) — verified live via `\d instrument_tags`
per RESEARCH.md Pitfall 1. `instrument_classification` must use
`PRIMARY KEY (symbol, scheme, valid_from)` plus the partial unique index:
```sql
CREATE UNIQUE INDEX uq_instrument_classification_current
    ON instrument_classification (symbol, scheme)
    WHERE valid_to IS NULL;
```

---

### `src/config/classification_service.py` (service, CRUD read-only)

**Analog:** `src/config/vocabulary_service.py` (full file read, 193 lines).

**Imports pattern** (lines 23-32):
```python
from __future__ import annotations

from dataclasses import dataclass

import asyncpg
import structlog

from src.core.database_manager import create_pool

logger = structlog.get_logger(__name__)
```

**Constructor + initialize pattern** (lines 56-86):
```python
class VocabularyService:
    def __init__(self, database_url: str, pool: asyncpg.Pool | None = None) -> None:
        self._database_url = database_url
        self._db_pool: asyncpg.Pool | None = pool
        self._entries: dict[str, dict[str, VocabEntry]] = {}
        self._groups: dict[tuple[str, str], frozenset[str]] = {}
        self._group_meta: dict[tuple[str, str], GroupEntry] = {}

    async def initialize(self) -> None:
        if self._db_pool is None:
            self._db_pool = await create_pool(self._database_url, pool_name="vocabulary_service")
        await self._load_all()

    async def close(self) -> None:
        if self._db_pool is not None:
            await self._db_pool.close()
            self._db_pool = None
```
For `ClassificationService`, replace `_entries`/`_groups` with the shape RESEARCH.md's
Pattern 1 specifies: `self._assignments: dict[tuple[str, str], list[_Assignment]]` keyed by
`(scheme, symbol)`, sorted by `valid_from` for as-of lookup, and `self._nodes: dict[tuple[str,
str], _Node]` keyed by `(scheme, code)`. Use `pool_name="classification_service"`.

**Prewarm-all-in-one-pass pattern** (lines 88-144, the exact query-then-populate-dicts shape
to mirror):
```python
async def _load_all(self) -> None:
    assert self._db_pool is not None, "VocabularyService.initialize() not called"
    async with self._db_pool.acquire() as conn:
        entry_rows = await conn.fetch(
            "SELECT namespace, code, label, description, sort_order, is_deprecated "
            "FROM controlled_vocabulary "
            "ORDER BY namespace, sort_order, code"
        )
        # ... more fetches on the same connection ...
    entries: dict[str, dict[str, VocabEntry]] = {}
    for row in entry_rows:
        namespace = row["namespace"]
        entries.setdefault(namespace, {})[row["code"]] = VocabEntry(...)
    self._entries = entries
```
For `ClassificationService`, the equivalent single-pass load is:
`SELECT symbol, scheme, code, valid_from, valid_to, source_ref FROM instrument_classification
ORDER BY symbol, scheme, valid_from` plus `SELECT scheme, code, parent_code, level, name
FROM classification_node`, both inside one `async with self._db_pool.acquire() as conn:`
block, then two Python loops populating `self._assignments`/`self._nodes` — no lazy
DB fallback on a cache miss, same as `VocabularyService`'s zero-hot-path-DB-calls mandate.

**Hot-path reader pattern** (lines 150-165, all synchronous dict lookups, fallback instead
of raising):
```python
def codes(self, namespace: str) -> list[str]:
    return list(self._entries.get(namespace, {}).keys())

def label(self, namespace: str, code: str) -> str:
    entry = self._entries.get(namespace, {}).get(code)
    return entry.label if entry is not None else code
```
`ClassificationService.node_at_level(symbol, scheme, level, as_of=None)` follows this same
shape: walk `self._assignments[(scheme, symbol)]` for the entry whose `[valid_from, valid_to)`
window contains `as_of` (default today), then walk that entry's node ancestry up/down to
`level` via `self._nodes`; return `f"{scheme}:unclassified"` instead of `None`/raising when
no assignment reaches that level or none exists as-of the date (D-08's never-NULL contract —
exactly `VocabularyService.label()`'s "fall back instead of raising" shape, applied to a
richer key).

---

### `src/core/classification_access.py` (utility, Ring 0 wrapper)

**Analog:** `src/core/vocabulary_access.py` (full file read, 140 lines).

**Module-level registration state + prewarm collapse pattern** (lines 33-75):
```python
_vocab_service: Any | None = None

def set_vocabulary_service(vocab: Any) -> None:
    global _vocab_service
    _vocab_service = vocab

def reset_vocabulary_service_for_test() -> None:
    global _vocab_service
    _vocab_service = None

async def prewarm(database_url: str, pool: asyncpg.Pool | None) -> VocabularyService:
    vocab = VocabularyService(database_url, pool=pool)
    await vocab.initialize()
    set_vocabulary_service(vocab)
    return vocab
```
Copy this triplet verbatim, renamed to `_classification_service` /
`set_classification_service()` / `reset_classification_service_for_test()` / `prewarm()`
returning `ClassificationService`.

**Fallback-with-warning-log reader pattern** (lines 78-99):
```python
def codes(namespace: str, default: tuple[str, ...]) -> tuple[str, ...]:
    if _vocab_service is None:
        return default
    result = _vocab_service.active_codes(namespace)
    if not result:
        logger.warning(
            "vocabulary_access.empty_registry_fallback",
            namespace=namespace,
            default=default,
        )
        return default
    return tuple(result)
```
Mirror for a `node_at_level(symbol, scheme, level, default="unclassified")`-style wrapper —
though note D-08 already makes the *service itself* never return `None`, so this Ring 0
wrapper's only job is the "no service registered yet" case (a script running outside daemon
startup), not a second fallback layer for empty results the way CVR's wrapper needs (CVR's
`codes()` can legitimately return an empty list for an unseeded namespace; classification's
`node_at_level()` cannot, by design).

**Discretion note (from RESEARCH.md Pattern 2):** this phase's actual consumers
(`settings.py`, `cache_manager.py`, `instrument_onboarding.py`) are library/script call
sites, not long-running daemons with a `VocabularyService`-style multi-consumer registration
problem — a direct `ClassificationService(...)` construction using the caller's own pool may
be simpler at those three call sites than routing through `prewarm()`/`set_...`. Still build
`classification_access.py` (future daemon/API consumers will want it), but the planner should
decide per call site whether to use the wrapper or construct directly, rather than forcing
every one of the three D-10 edit sites through it.

---

### `src/config/instrument_onboarding.py` (modify: add classification gate)

**Analog:** the same file's existing `metadata`/`metadata_skip_reason` gate (lines 188-268,
full section read).

**Signature + no-silent-omission guard pattern** (lines 188-199, 262-268):
```python
async def onboard_instrument(
    conn: asyncpg.Connection,
    instrument: Instrument,
    *,
    qualifier: InstrumentQualifier,
    tags: Sequence[tuple[str, float, dict]] = (),
    timeframes: Sequence[str] | None = None,
    metadata: dict | None = None,
    metadata_skip_reason: str = "",
    compute_eligible: bool = False,
    live_tradeable: bool = False,
) -> OnboardResult:
    ...
    if metadata is None and not metadata_skip_reason:
        raise ValueError(
            "onboard_instrument: metadata is None and metadata_skip_reason is empty -- "
            "a silent instrument_metadata omission is not permitted (D-08, todo 282). "
            "Pass metadata=... or a non-empty metadata_skip_reason=... explaining why "
            f"this instrument (symbol={instrument.symbol!r}) has no metadata row."
        )
```
**Deliberate deviation, per D-09/Open-Question-1's recommendation:** do NOT add a
`classification_skip_reason` escape hatch mirroring `metadata_skip_reason` — RESEARCH.md's
Open Question 1 recommends hard-failing unconditionally (classification is always
determinable to at least the asset-class level, unlike metadata's genuine "no data
available" case). The new gate should look like:
```python
if classification_code is None:
    raise ValueError(
        "onboard_instrument: classification_code is required -- a new instrument must "
        "carry an indicagent_v1 assignment at onboarding time (D-09, todo 384). No skip "
        "escape hatch: classification is always determinable to at least the asset-class "
        f"level for (symbol={instrument.symbol!r})."
    )
```
placed alongside the existing metadata check, before the qualification gate, and the write
itself follows the same "insert inside the existing `async with conn.transaction():` block"
pattern as `_INSERT_METADATA_SQL`'s call site (lines 324-334) — write to
`instrument_classification` in that same transaction, not a separate one, so onboarding
stays all-or-nothing per the function's existing transaction contract (docstring lines
210-222).

---

### `src/providers/ibkr.py` (modify: new industry/category/subcategory sourcing method)

**Analog:** `qualify_instrument()`, same file, lines 973-1042 (full method read).

**Contract-details fetch + timeout-wrapped call pattern** (lines 1019-1028):
```python
# [rca_analysis 2026-07-05, F4] reqContractDetailsAsync has NO timeout of its
# own in ib_async (unlike reqHistoricalDataAsync's internal default=60) --
# fully unbounded without this wrapper. Same failure class as the historical-
# data hang migration 199 fixed elsewhere in this file.
details = await asyncio.wait_for(
    self._ib.reqContractDetailsAsync(contract), timeout=_CONTRACT_DETAILS_TIMEOUT_SEC
)
if details:
    qualified = details[0].contract
    self._qualified_contracts[instrument.symbol] = qualified
    ...
    return True
```
`details[0]` is the `ContractDetails` object, not `details[0].contract` — `.industry`/
`.category`/`.subcategory` live on `details[0]` directly (RESEARCH.md's Code Examples
section, live-verified). Add a new method (e.g. `fetch_contract_classification_hints`)
reusing this exact `asyncio.wait_for(self._ib.reqContractDetailsAsync(contract),
timeout=_CONTRACT_DETAILS_TIMEOUT_SEC)` call and the same `Stock(symbol=..., exchange=...,
currency="USD")` contract construction used in `qualify_instrument`'s `AssetClass.EQUITY`
branch (lines 1010-1015) — do not overload `qualify_instrument` itself, which is on the hot
connect path per RESEARCH.md's Code Examples note. Client ID: pick unused 35-50 range value
per `src/providers/CLAUDE.md`'s VIX/client-ID guidance, not already claimed by a
concurrently-running script.

---

### `scripts/infrastructure/classification_ibkr_sourcing.py` (new, one-off sourcing script)

**Analog:** the new `IBKRProvider` method above, called from a standalone script — no
existing one-off classification-sourcing script exists yet in this codebase to copy
structurally; follow the general `scripts/infrastructure/` one-off pattern (argparse entry
point, `_path_bootstrap` import, structured per-symbol output written to a file for human
review, per D-06's "committed as data ... never computed at runtime"). Output should be a
CSV/JSON keyed by symbol with `industry`/`category`/`subcategory` plus a `fetched_at`
timestamp column (RESEARCH.md Pitfall 4 — must not silently reuse the stale 2026-09-18
probe's output).

---

### `src/config/settings.py` (modify: non-futures builder branch)

**Analog:** the same file's non-futures `Instrument` construction, lines 624-647 (full
section read).

**Current sector-reading fallback branch** (lines 633-647):
```python
non_futures: list[Instrument] = []
for row in nf_rows:
    cd = _json.loads(row[2]) if isinstance(row[2], str) else row[2]
    if cd is None:
        continue
    try:
        non_futures.append(Instrument(**cd))
    except Exception:
        # Fallback: build with available columns if contract_details is partial
        non_futures.append(
            Instrument(
                symbol=cd.get("symbol") or row[0],
                base=cd.get("base") or row[1] or "",
                name=cd.get("name", ""),
                asset_class=cd.get("asset_class", "equity"),
                exchange=cd.get("exchange", ""),
                sector=cd.get("sector", ""),
                tick_size=cd.get("tick_size", 0),
                point_value=cd.get("point_value", 0),
                session_id=cd.get("session_id", "equity_rth"),
                provider_meta=cd.get("provider_meta", {}),
                expiry=cd.get("expiry", ""),
            )
        )
```
Per D-10, `sector=cd.get("sector", "")` on this line must become a call into
`ClassificationService`/`classification_access` (sector = level-2 node name), e.g.
`sector=node_at_level(symbol=..., scheme="indicagent_v1", level=2)` (falling back to
`"unclassified"` per D-08, never `""`). Note the other `Instrument(**cd)` construction two
lines above (the non-exception path) reconstructs straight from the frozen
`contract_details` JSON blob — that path is untouched by D-10 (it's reading the historical
snapshot, not deciding a live sector), only the fallback branch's explicit `sector=` kwarg
changes. Also check `_build_instrument_from_db_row` (lines 473-509) — it does not read
`sector` directly (it inherits config-file template values via `model_copy`), so no edit
needed there; confirmed by reading the full function.

---

### `src/intelligence/pipeline/cache_manager.py` (modify: `_instrument_from_row`)

**Analog:** the same function, lines 74-97 (full read) — and `settings.py`'s equivalent
fallback branch above (same fix, same shape, two files).

**Current sector-reading pattern** (lines 84-97):
```python
def _instrument_from_row(row: dict) -> Any:
    from src.core.models import Instrument  # noqa: PLC0415 — avoids circular import

    cd: dict = row["contract_details"] or {}
    return Instrument(
        symbol=cd.get("symbol") or row["symbol"],
        base=row.get("base", ""),
        name=cd.get("name", ""),
        asset_class=cd.get("asset_class", "equity"),
        exchange=cd.get("exchange", ""),
        sector=cd.get("sector", ""),
        tick_size=float(cd.get("tick_size") or 0),
        point_value=float(cd.get("point_value") or 0),
        session_id=cd.get("session_id", "equity_regular"),
        provider_meta=cd.get("provider_meta") or {},
        expiry=cd.get("expiry", ""),
    )
```
`sector=cd.get("sector", "")` is the exact D-10 edit site — replace with the same
`ClassificationService` lookup used in `settings.py`'s builder, keyed on `row["symbol"]`.
Since this function has no `async`/DB-pool access itself (it's a synchronous row transform
called from `_load_instruments` at line 453), it must go through the Ring 0
`classification_access` wrapper's synchronous reader (not a direct `ClassificationService`
construction, since there's no natural place to hold a pool reference here) — this is the
one D-10 call site where `classification_access.py`'s wrapper earns its keep over a direct
construction, unlike the `instrument_onboarding.py`/one-off-script call sites noted in
Pattern 2's discretion above.

---

### `tests/unit/test_classification_service.py` (test, pure-Python no-DB)

**Analog:** `tests/unit/test_vocabulary_service.py` (full file read, 173 lines).

**Fixture-by-direct-dict-population pattern** (lines 1-67):
```python
"""Unit tests: VocabularyService (Phase 161, Controlled Vocabulary System).

Pure-Python, no-DB style (mirrors tests/unit/test_concept_registry_service.py): builds a
VocabularyService, populates `_entries`/`_groups` caches directly (bypassing
initialize()/DB entirely), and asserts the synchronous hot-path readers.
"""
def _service_with_fixture() -> VocabularyService:
    service = VocabularyService("postgresql://unused")
    service._entries = {
        "timeframe": {
            "1m": VocabEntry(code="1m", label="1 Minute", description=None,
                              sort_order=0, is_deprecated=False),
            ...
        },
    }
    return service
```
For `ClassificationService`, build `_service_with_fixture()` that directly populates
`service._assignments` and `service._nodes` with a small `indicagent_v1` tree (e.g. one
single-name symbol assigned to level 4, one ETF assigned to level 2, matching D-05's
depth-follows-instrument rule) and one `_Assignment` with a closed `valid_to` plus one
still-open row, to exercise the as-of lookup.

**No-DB-calls-after-init assertion pattern** (lines 147-172, copy near-verbatim):
```python
def test_no_db_calls_after_init():
    service = _service_with_fixture()
    assert service._db_pool is None
    for method_name in ("codes", "active_codes", "label", ...):
        method = getattr(service, method_name)
        assert not inspect.iscoroutinefunction(method)
    assert service.codes("timeframe")
```
Mirror exactly for `node_at_level` and any other hot-path reader `ClassificationService`
exposes — proves D-08's zero-hot-path-DB-calls mandate the same way `VocabularyService`'s
own test proves it.

**Never-NULL fallback assertion pattern** (lines 95-97, the shape to copy for
`unclassified`):
```python
def test_label_unknown_code_falls_back_to_code():
    service = _service_with_fixture()
    assert service.label("timeframe", "99z") == "99z"
```
Equivalent: `test_node_at_level_no_assignment_returns_unclassified()` asserting
`service.node_at_level("NOSUCHSYM", "indicagent_v1", 2) == "indicagent_v1:unclassified"`,
and a second test for "assignment exists but doesn't reach the requested level" (D-05's ETF
case, e.g. SPY assigned to level 1 but queried at level 4).

---

### `tests/unit/_classification_fakes.py` (test, shared double)

**Analog:** `tests/unit/_vocabulary_fakes.py` (full file read, 48 lines).

**Constructor-as-callable double pattern** (lines 17-48):
```python
class FakeVocabularyService:
    def __init__(self, codes: list[str], groups: dict[str, list[str]] | None = None) -> None:
        self._codes = codes
        self._groups = groups or {}
        self.initialized = False

    def __call__(self, database_url, pool=None) -> FakeVocabularyService:
        """Matches VocabularyService's `(database_url, pool=None)` constructor
        signature -- lets `FakeVocabularyService(codes)` itself be passed
        wherever the real class name is expected."""
        self.database_url = database_url
        self.pool = pool
        return self

    async def initialize(self) -> None:
        self.initialized = True

    def active_codes(self, namespace: str) -> list[str]:
        assert namespace == "timeframe"
        return self._codes
```
Build `FakeClassificationService` with the same `__call__`-as-constructor shape (so
`monkeypatch.setattr(..., ClassificationService)` works identically) and a
`node_at_level(symbol, scheme, level, as_of=None)` method returning a caller-supplied
mapping, defaulting to `f"{scheme}:unclassified"` when the symbol isn't in the fixture —
same never-NULL contract the real service enforces.

---

### `tests/integration/test_instrument_classification_coverage.py` (test, live-DB)

**Analog:** `tests/integration/test_instrument_registry.py` (full file read, 62 lines).

**Marker + plain-assertion-against-live-DB pattern** (lines 11-26):
```python
import asyncpg
import pytest

from src.config.settings import get_active_contracts, get_settings

pytestmark = pytest.mark.integration


def test_get_active_contracts_returns_nonzero():
    settings = get_settings()
    result = get_active_contracts(settings)
    assert (
        len(result) > 0
    ), "No active contracts returned — DB unreachable or instruments table empty"
```
**Direct-connection query pattern** (lines 39-62, the shape for the coverage/depth/
source_ref/valid_from checks D-05-D-09 need):
```python
@pytest.mark.asyncio
async def test_trigger_installed():
    settings = get_settings()
    conn = await asyncpg.connect(settings.database_url)
    try:
        trigger_names = await conn.fetch(
            "SELECT trigger_name FROM information_schema.triggers "
            "WHERE event_object_table = 'instruments'"
        )
        names = {row["trigger_name"] for row in trigger_names}
        assert "trg_instruments_notify" in names, (
            f"trg_instruments_notify trigger not found. ..."
        )
    finally:
        await conn.close()
```
Mirror this exact `pytestmark = pytest.mark.integration` + `asyncpg.connect(...)` +
`try/finally` shape for: (1) every active instrument has a current `indicagent_v1` row
(D-09 coverage), (2) every row's `source_ref` is one of the two allowed values (D-06), (3)
every row's `valid_from >= <build date>` (D-07), (4) a sampled single name lands at level 4
and a sampled broad ETF lands above it (D-05). This suite runs under `pytest -m integration`
only, per `tests/integration/conftest.py`'s own docstring confirming it never runs in
GitHub CI — document that explicitly in the phase's verification notes (RESEARCH.md
Pitfall 2), do not add a `tests/unit/` file that opens a DB connection.

---

## Shared Patterns

### Cached read-layer service (constructor / initialize / sync readers)
**Source:** `src/config/vocabulary_service.py` (full file, 193 lines)
**Apply to:** `src/config/classification_service.py`
See Pattern Assignments above for the three excerpted blocks (imports, constructor/
initialize, prewarm-all-in-one-pass, hot-path readers). This is the single most important
shared pattern in the phase — `ClassificationService` should be structurally
indistinguishable from `VocabularyService` apart from its richer as-of/hierarchy lookup.

### Ring 0 access wrapper (prewarm / set_.../reset_..._for_test triplet)
**Source:** `src/core/vocabulary_access.py` (full file, 140 lines)
**Apply to:** `src/core/classification_access.py`, and any daemon/script call site that
needs classification lookups without threading an instance through its constructor.

### No-silent-omission required-argument gate
**Source:** `src/config/instrument_onboarding.py` lines 262-268 (`metadata`/
`metadata_skip_reason` check)
**Apply to:** the new classification-required check in the same function — but see the
deliberate no-skip-hatch deviation noted above (Open Question 1's recommendation).

### Migration-time hard-fail guard (`DO $$ ... RAISE EXCEPTION`)
**Source:** `production/migrations/363_sector_label_fixes.sql` lines 54-64
**Apply to:** migration 364's coverage guard (D-09 seed-time check) and its
node-immutability guard (D-01).

### Point-in-time close-prior-row/insert-new-row idiom
**Source:** `services/context_writer.py` lines 46-62
**Apply to:** conceptual template only for this phase (the seed migration inserts rows
directly, all with the same `valid_from` per D-07) — the real applicability is to any
future reclassification write path this schema enables, which the plan should document as
out-of-scope-but-schema-ready.

### Transactional multi-table write inside one `conn.transaction()` block
**Source:** `src/config/instrument_onboarding.py` lines 281-334 (the existing tags/
metadata/instrument insert sequence)
**Apply to:** the new classification-row insert added to the same transaction block,
keeping the function's existing all-or-nothing atomicity contract (docstring lines
210-222) intact.

## No Analog Found

None — RESEARCH.md's own "Don't Hand-Roll" section already confirms every piece of
infrastructure this phase needs has 1-3 live precedents in this exact codebase. The only
partial gap is the 3-table point-in-time schema itself (`classification_scheme`/
`classification_node`/`instrument_classification`), which has no single existing analog
combining all three shapes at once — it is assembled from `controlled_vocabulary`'s
namespace/hierarchy-adjacent shape (name only, not code) plus `context_writer.py`'s
point-in-time close/insert idiom plus the design doc's explicit schema (D-01). This is
flagged, not blocking: the design doc is itself the authoritative schema source per
CONTEXT.md, and RESEARCH.md's Pattern 3 already gives the literal DDL to use.

## Metadata

**Analog search scope:** `src/config/`, `src/core/`, `src/providers/`, `src/intelligence/
pipeline/`, `production/migrations/`, `services/`, `tests/unit/`, `tests/integration/`
**Files scanned:** ~20 (targeted reads guided by RESEARCH.md's own file citations, cross-
verified against live source rather than re-derived independently)
**Pattern extraction date:** 2026-09-25
