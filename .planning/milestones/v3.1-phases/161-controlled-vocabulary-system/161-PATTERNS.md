# Phase 161: Controlled Vocabulary System - Pattern Map

**Mapped:** 2026-07-16
**Files analyzed:** 9 (2 migrations, 1 service, 1 drift-audit module + oneshot CLI entrypoint
(counted as one unit below), 1 API route, 1 ops-script edit, 3 test files)
**Analogs found:** 9 / 9

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `production/migrations/237_controlled_vocabulary_schema.sql` | migration | batch (DDL) | `production/migrations/233_concept_registry_mvp.sql` | exact (4-table registry-family schema migration, same author/era) |
| `production/migrations/238_controlled_vocabulary_seed_namespaces.sql` | migration | batch (seed data) | `production/migrations/227_instrument_tag_vocabulary.sql` (seed section) + `234_concept_registry_seed_ensemble_strategy.sql` | exact (idempotent `INSERT ... ON CONFLICT DO NOTHING` seed pattern for a controlled taxonomy table) |
| `production/migrations/239_vocabulary_drift_window_apr_key.sql` (added during plan revision — APR fix for blocker 1) | migration | batch (APR seed) | `production/migrations/219_ic_staleness_apr_key.sql` | exact (single-key `config_schema`/`config_state`/`config_history` triple-insert for an `infra.*` tunable) |
| `src/config/vocabulary_service.py` | service | CRUD (read-only, cached) | `src/config/config_service.py` | exact (same directory, same cached-library-not-microservice shape, same author intent per RESEARCH.md) |
| `src/config/vocabulary_drift.py` (importable module) | utility | batch (bounded scan + compare) | `services/ic_engine.py`'s `_run_lifecycle_hook` (integrity_monitor write section, lines 2490-2651) | role-match (periodic check → threshold compare → `integrity_monitor` INSERT) |
| oneshot CLI entrypoint for `vocabulary_drift.py` | utility (D-06 oneshot) | batch | `services/signal_probe_auditor.py` (`main()`/`_amain()`, lines 395-414) | exact (D-06 `JOB_COMPLETED_TOTAL` oneshot wrapper around an async body) |
| `src/api/routes/vocabulary.py` | route | request-response | `src/api/routes/drift.py` | exact (bare `APIRouter()`, try/except-on-DB-error, `get_connection()`, JSON dict return) |
| `scripts/ops/corpus/ops_corpus_pipeline_run.sh` (one-line append) | config (shell orchestration) | batch | same file, existing `check_canary_integrity()` / `run_step` calls | exact (same file, same convention, no new pattern to source elsewhere) |
| `tests/unit/test_vocabulary_service.py` | test | CRUD (pure-Python, no DB) | `tests/unit/test_concept_registry_service.py` | exact (dataclass-fixture `_state(**overrides)` builder, pure decision-core testing, no DB/Kafka) |
| `tests/unit/test_vocabulary_drift_audit.py` | test | batch (pure-Python, no DB) | `tests/unit/test_concept_registry_service.py` | role-match (same pure-logic no-DB style, applied to the drift-comparison function instead of the promotion decision function) |
| `tests/integration/test_vocabulary_api.py` (**relocate - see note**) | test | request-response | `tests/unit/api/test_features_route.py` | exact - **but wrong directory per RESEARCH.md's suggestion; see "Anti-Pattern" note below** |

## Pattern Assignments

### `production/migrations/237_controlled_vocabulary_schema.sql` (migration)

**Analog:** `production/migrations/233_concept_registry_mvp.sql` (full file read; also cross-checked
against `production/migrations/218_integrity_monitor.sql` for hypertable/idempotency conventions)

**Header/provenance comment pattern** (lines 1-44 of 233):
```sql
-- Migration 233: Concept Registry MVP - four-table schema + APR gate keys (todo 058)
--
-- Builds the Minimal Viable Version from docs/research/concept-unified-registry.md: ...
-- MVP deltas vs the canonical doc's sketches, each with provenance:
--   * concept_transition_log.corpus_build_ref (F3): ...
-- Review-driven corrections applied (phase 160 cross-AI review):
--   * M-3: ...
--
-- All statements idempotent: CREATE TABLE IF NOT EXISTS, ON CONFLICT DO NOTHING, or
-- WHERE NOT EXISTS guards where the PK does not support ON CONFLICT. Safe to re-run.

BEGIN;
```
Copy this shape exactly: a provenance header citing the canonical design doc
(`docs/research/concept-controlled-vocabulary.md`) and this CONTEXT.md's D-01/D-03/D-04/D-04b
revisions, then `BEGIN;` ... `COMMIT;`.

**Table + FK + CHECK pattern** (lines 48-64, 73-96 of 233 - `concept_registry`/`concept_gate` shape):
```sql
CREATE TABLE IF NOT EXISTS concept_registry (
    concept_id        UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    domain            TEXT    NOT NULL
        CHECK (domain IN ('feature', 'ensemble_strategy')),
    name              TEXT    NOT NULL,
    description       TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'shadow_only', 'active', 'deprecated')),
    ...
    UNIQUE (domain, name)
);

COMMENT ON TABLE concept_registry IS '...';
```
`controlled_vocabulary` should follow this exact shape: `(namespace, code)` composite identity
(mirrors `UNIQUE (domain, name)`), `label`, `description`, `sort_order`, `is_deprecated`,
`created_at`. `vocabulary_group` mirrors `concept_gate`'s 1-row-per-parent shape but keyed by
`(namespace, group_name)`; `vocabulary_group_member` is the join table (mirrors nothing in 233
directly - closest is `instrument_tags` in migration 227, a plain `(symbol, tag)` PK join table).
Every `CREATE TABLE` gets a `COMMENT ON TABLE` explaining the row's epistemic kind, matching this
codebase's house style (`concept_registry`'s comment explicitly states what the row "is" - do the
same to reinforce D-02's authoritative/flat vs weighted/hypothesis distinction against
`tag_vocabulary`).

**Idempotency guard for non-hypertable inserts** (join-table membership rows have no natural
single-column ON CONFLICT target when membership is the whole row):
```sql
-- Source: production/migrations/233_concept_registry_mvp.sql lines 219-230 pattern
INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), '<key>', 1, '<value>', 'migration_233', '<reason>'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history WHERE config_key = '<key>' AND version = 1
);
```
Use `ON CONFLICT (namespace, code) DO NOTHING` for `controlled_vocabulary` (has a real composite
key) and `ON CONFLICT (namespace, group_name, code) DO NOTHING` for `vocabulary_group_member`
(also a real composite key) - the `WHERE NOT EXISTS` fallback above is only needed if a table
lacks a usable natural key, which none of these three do.

---

### `production/migrations/238_controlled_vocabulary_seed_namespaces.sql` (migration, seed data)

**Analog:** `production/migrations/227_instrument_tag_vocabulary.sql` (seed section, lines 49-60+)
and `production/migrations/234_concept_registry_seed_ensemble_strategy.sql` (not opened in full -
227's seed shape is the stronger match since it seeds a flat code/category/description table, the
same shape as `controlled_vocabulary`)

**Seed INSERT pattern** (lines 49-60 of 227):
```sql
-- ── Tag vocabulary ─────────────────────────────────────────────────────────────

INSERT INTO tag_vocabulary (tag, category, description) VALUES

-- exposure
('eq_broad',          'exposure', 'Broad equity market index'),
('eq_sector',         'exposure', 'Single GICS sector equity basket'),
('eq_growth',         'exposure', 'Growth-tilted equity factor'),
...
```
Copy this comment-banner-per-category + aligned-column literal-tuple style for the 6 namespaces
(`regime_hmm`, `regime_cross_sectional_equity`, `regime_cross_sectional_rates`, `timeframe`,
`asset_class`, `tier`). **Live-verified seed counts (2026-07-16, re-checked during pattern mapping,
matches CONTEXT.md D-01/D-04/D-04b exactly):**
- `regime_cross_sectional_equity`: 9 codes (`{low,mid,high}_{bull,neutral,bear}`) - verified live via
  `SELECT regime_group, regime_label, count(*) FROM market_regimes GROUP BY 1,2` (9 equity rows,
  313k-850k count each)
- `regime_cross_sectional_rates`: 6 codes (`{flat,steep,inverted}_{tight,wide}`) - verified live (6
  rates rows, 19k-618k count each)
- `tier`: 3 codes live today (`0_atomic`=135, `1_interaction`=8, `2_theory`=12) - confirmed via
  `SELECT tier, count(*) FROM feature_registry GROUP BY 1`. **Seed all 3**, not the 2 CONTEXT.md's
  code_context section states (that section is stale; D-01's locked namespace list is unaffected).
- `timeframe`: 5 codes live (`1m`, `5m`, `15m`, `1h`, `1d`) - verified via
  `SELECT DISTINCT timeframe FROM market_data_ohlcv`.
- `asset_class`: 3 codes live (`equity`, `futures`, `fx`) - verified via
  `SELECT DISTINCT contract_details->>'asset_class' FROM instruments`.
- `regime_hmm`: 5 codes (design doc's list, not independently re-queried here - CONTEXT.md D-03
  already treats this as settled).

**Group-seed pattern** (no direct existing analog - this is the one genuinely novel piece of SQL
in this migration; write as plain `INSERT INTO vocabulary_group (namespace, group_name, label)
VALUES (...)` followed by `INSERT INTO vocabulary_group_member (namespace, group_name, code)
VALUES (...)`, using the same `ON CONFLICT DO NOTHING` idempotency convention as the rest of this
migration). D-03/D-04/D-04b enumerate every group and its members explicitly - copy those lists
directly, they need no further design work.

---

### `src/config/vocabulary_service.py` (service, CRUD/cached-read)

**Analog:** `src/config/config_service.py` (full file read, 314 lines)

**Class shape / imports pattern** (lines 1-33, 55-58):
```python
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, ClassVar

import asyncpg
import structlog

from src.core.database_manager import create_pool

logger = structlog.get_logger(__name__)


class ConfigService:
    def __init__(self, database_url: str, pool: asyncpg.Pool | None = None) -> None:
        self._database_url = database_url
        self._db_pool: asyncpg.Pool | None = pool
        self._cache: dict[str, Any] = {}
```
`VocabularyService.__init__` should be identical in shape but with two cache dicts instead of one
(per RESEARCH.md's Code Examples section, already verified against this file):
`self._entries: dict[str, dict[str, VocabEntry]]` (namespace -> code -> entry) and
`self._groups: dict[tuple[str, str], frozenset[str]]` ((namespace, group) -> codes).

**Lifecycle pattern** (lines 60-69):
```python
async def initialize(self) -> None:
    """Initialize the database pool (no-op if pool already provided)."""
    if self._db_pool is None:
        self._db_pool = await create_pool(self._database_url, pool_name="config_service")

async def close(self) -> None:
    """Close the database pool, releasing all connections."""
    if self._db_pool is not None:
        await self._db_pool.close()
        self._db_pool = None
```
Copy verbatim except `pool_name="vocabulary_service"`. `VocabularyService.initialize()` additionally
calls a private `_load_all()` to prewarm both cache dicts in one pass (three `SELECT * FROM
<table>` - no per-namespace lazy-fill, unlike `ConfigService.get()`'s miss-then-fetch, since the
whole vocabulary corpus is ~100 rows and D-05 mandates zero DB calls on the hot path - no fallback
to a DB fetch is acceptable even on a "miss").

**Hot-path read pattern** (lines 99-105 - `get_sync`):
```python
def get_sync(self, key: str, default: Any = None) -> Any:
    """Return a cached config value synchronously - no DB I/O.

    MUST be called only after the cache has been pre-warmed via get().
    Safe to call from synchronous hot-path code (e.g., plugin compute_full).
    """
    return self._cache.get(key, default)
```
`VocabularyService.codes()`/`.label()`/`.group_codes()` all follow this exact "dict.get on
pre-warmed cache, no I/O, no async" shape - see RESEARCH.md's Code Examples section for the
already-drafted method bodies (`codes()`, `label()`, `group_codes()`), which are consistent with
this analog and ready to use as-is.

**Assert-not-initialized guard** (line 119, repeated at every DB-touching method):
```python
assert self._db_pool is not None, "ConfigService.initialize() not called"
```
Reuse this exact assertion message shape (`"VocabularyService.initialize() not called"`) at the top
of `_load_all()`.

---

### `src/config/vocabulary_drift.py` + oneshot CLI entrypoint (utility, batch/event-driven)

**Analogs:**
1. `services/ic_engine.py` lines 2490-2651 (`_run_lifecycle_hook` - the bounded-check +
   `integrity_monitor` INSERT pattern)
2. `services/signal_probe_auditor.py` lines 1-60, 395-414 (the D-06 oneshot wrapper shape)

**Idempotency-short-circuit / bounded-check pattern** (ic_engine.py lines 2506-2526, adapt the
shape, not the specific SQL - this phase's audit is a fresh-comparison run each time, not
`training_window_end`-keyed, so the "already ran" check does not directly transfer, but the
*shape* - pre-check before any write, structured log on skip - does):
```python
# Source: services/ic_engine.py:2506-2526 (live, verified)
with write_conn.cursor() as cur:
    cur.execute(
        """
        SELECT 1 FROM integrity_monitor
        WHERE monitor_type = 'ic_lifecycle'
          AND training_window_end = %s
          AND metric_name IN ('decay_cells_flagged', 'regime_shift_fraction')
        LIMIT 1
        """,
        (training_window_end,),
    )
    already_ran = cur.fetchone() is not None
if already_ran:
    log.info("ic_engine.lifecycle_hook_already_ran", training_window_end=str(training_window_end))
    return
```

**`integrity_monitor` INSERT pattern** (ic_engine.py lines 2637-2649 - the exact statement shape to
replicate, values only, per RESEARCH.md's Pattern 3):
```python
# Source: services/ic_engine.py:2637-2649 (live, verified)
cur.execute(
    """
    INSERT INTO integrity_monitor
        (monitor_type, subject, metric_name, metric_value,
         threshold_value, passed, training_window_end)
    VALUES ('ic_lifecycle', NULL, 'regime_shift_fraction', %s, %s, false, %s)
    ON CONFLICT (monitor_type, training_window_end, metric_name,
                 COALESCE(subject, ''), evaluated_at) DO NOTHING
    """,
    (regime_shift_fraction, config.decay_regime_shift_fraction, training_window_end),
)
```
For vocabulary drift: `monitor_type='vocabulary_drift'`, `subject=<namespace>`,
`metric_name='unregistered_code_count'`, `metric_value=<count>`, `threshold_value=0`,
`passed=(count == 0)`, `training_window_end=NULL` (per RESEARCH.md's Pattern 3 - this monitor type
has no training-window concept).

**Bounded `SELECT DISTINCT` query shape** (per RESEARCH.md's Code Examples, already vetted against
the live schema - copy these two queries verbatim, they encode Findings 1-3):
```sql
-- regime_hmm - note the '' filter (empty-string placeholder, not a 6th code) and the
-- recent-window bound (never a full-hypertable distinct-scan)
SELECT DISTINCT regime
FROM feature_vectors
WHERE bar_ts > now() - interval '30 days'
  AND regime <> '';

-- regime_cross_sectional_equity / _rates - MUST scope by regime_group (two independent
-- taxonomies share one column; D-01's split makes this a hard requirement, not optional)
SELECT DISTINCT regime_label
FROM market_regimes
WHERE ts > now() - interval '30 days'
  AND regime_group = 'equity';   -- or 'rates' for the sibling namespace
```
Also add the D-09-mandated `SELECT DISTINCT regime_group FROM market_regimes` guard (compare
against `{'equity', 'rates'}` - the namespace suffixes the registry knows - so a future third
`regime_group` value can't drift past both namespace-specific queries silently).

**Oneshot D-06 entrypoint wrapper** (signal_probe_auditor.py lines 27-46, 395-414 - full pattern,
this is the strongest live analog for "importable module + thin oneshot CLI" in the entire
codebase):
```python
# Source: services/signal_probe_auditor.py (live, verified)
from src.config.settings import Settings
from src.core.database_manager import create_pool as create_db_pool
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

# D-06 contract: label MUST match the systemd unit suffix exactly (kebab-case).
_JOB_LABEL: str = "signal-probe-auditor"

async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_probe(pool)
    finally:
        await pool.close()


def main() -> None:
    """Run the signal probe auditor once and emit a completion counter before exit."""
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB_LABEL, "status": "success"})
    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB_LABEL, "status": "failure"})
        raise error
    finally:
        flush_and_shutdown_metrics()
```
**Important divergence from CONTEXT.md's D-09 phrasing:** D-09 says "chain the oneshot into
`ops_corpus_pipeline_run.sh`," which is a bash script, not a systemd unit - so the `_JOB_LABEL`
convention (kebab-case matching a `%n` systemd suffix) doesn't strictly apply here since there is
no unit. Two reasonable choices: (a) still emit `JOB_COMPLETED_TOTAL` with a descriptive
`job="vocabulary-drift-audit"` label for OTel consistency even though no systemd unit consumes it
today (recommended - cheap, forward-compatible if a timer is added later), or (b) skip the OTel
emission entirely and rely solely on the `integrity_monitor` row + exit code, since
`ops_canary_integrity_assert.py` (the *other* thing chained into this exact bash script,
immediately preceding this pattern) does neither - it just returns 0/1 and prints to stdout (see
`scripts/ops/alpha/ops_canary_integrity_assert.py` lines 305-348). **Recommend following
`ops_canary_integrity_assert.py`'s simpler `async def main() -> int: ... sys.exit(asyncio.run(main()))`
shape instead of `signal_probe_auditor.py`'s, since it is the actual sibling already living in this
exact bash script** - but the `integrity_monitor` INSERT is still mandatory per D-09/Pattern 3.

**`main()`/`sys.exit` pattern for a script chained into bash** (ops_canary_integrity_assert.py lines
305-348, the more directly relevant sibling since it's the file immediately preceding this one in
`ops_corpus_pipeline_run.sh`):
```python
# Source: scripts/ops/alpha/ops_canary_integrity_assert.py (live, verified)
async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        ...
        print("\nPASS -- ... gate cleared.")
        return 0
    except SomeViolation as violation:
        print(f"\nFATAL: ... -- {violation}", file=sys.stderr)
        return 1
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

---

### `src/api/routes/vocabulary.py` (route, request-response)

**Analog:** `src/api/routes/drift.py` (full 65-line file read, verified)

**Full pattern** (lines 1-27, 60-64):
```python
# Source: src/api/routes/drift.py (live, verified in full)
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("")
async def get_drift_state() -> dict[str, Any]:
    """Return current KS and CUSUM drift state from drift_state table."""
    from src.core.database_manager import get_connection

    ...
    try:
        async with get_connection() as conn:
            rows = await conn.fetch("SELECT ... FROM drift_state ORDER BY updated_at DESC")
        for row in rows:
            ...
    except Exception as error:
        logger.warning("drift endpoint: DB query error", error=str(error))

    return {...}
```
`vocabulary.py` needs a path-parameterized route (`@router.get("/{namespace}")`) instead of
`drift.py`'s bare `@router.get("")` - the closer structural shape for path-param + validated-set
behavior is `src/api/routes/features.py`'s `/{symbol}/{timeframe}` handler (not re-read here since
`drift.py`'s try/except-on-DB-error shape already covers the error-handling requirement; consult
`features.py` directly if a path-param precedent beyond `drift.py`'s is needed). Per RESEARCH.md's
ASVS V5 note: validate `namespace` against the known 6-namespace set and return an empty/404-style
response for unknown namespaces rather than a raw SQL error - same defensive posture as `drift.py`'s
blanket `except Exception`.

**Registration pattern** (`src/api/main.py` lines 195-204, imports lines ~19-29):
```python
# Source: src/api/main.py (live, verified)
from .routes import (
    ai_stats,
    drift,
    features,
    health,
    instruments,
    market_data,
    narrative,
    signals,
    sse,
    ...
)
...
app.include_router(drift.router, prefix="/api/drift", tags=["drift"])
app.include_router(validation.router, prefix="/api/validation", tags=["validation"])
```
Add `vocabulary` to the import tuple and append
`app.include_router(vocabulary.router, prefix="/api/vocabulary", tags=["vocabulary"])` after the
existing `validation.router` line (last registered route in the file).

---

### `scripts/ops/corpus/ops_corpus_pipeline_run.sh` (config, one-line append)

**Analog:** the file's own existing conventions - no external file needed.

**`run_step` invocation pattern** (already live in this file, lines for Step 6 "ic_shrinkage"):
```bash
# Step 6 - IC Shrinkage (E1): ...
run_step 6 "ic_shrinkage" \
    "$PYTHON" scripts/ops/alpha/ops_ic_shrinkage.py
```
And the standalone non-`run_step` gate pattern (`check_canary_integrity`, called directly after
Step 5, not wrapped in `run_step` since it's a hard-halt gate rather than a numbered pipeline
stage):
```bash
# Canary integrity gate - abort if a control feature proves the measurement
# pipeline is broken (see check_canary_integrity() for the full rule).
check_canary_integrity
```
Per D-09, the vocabulary drift audit is observability-only (never gates the pipeline - "never gates
writes, always read-side" per RESEARCH.md's architecture diagram), so it should be appended as a
plain command **after** Step 8 (`alpha_publisher`, the last step) - not wrapped in `run_step`
(which halts the whole pipeline non-zero-exit) and not modeled on `check_canary_integrity` (which
is a hard gate). A bare `"$PYTHON" scripts/ops/... 2>&1 | tee -a "$LOG_DIR/vocabulary_drift_$(date +%Y%m%d_%H%M%S).log" || true`
(swallowing a non-zero exit with `|| true`) is the correct shape - the audit's job is to write a
loud `integrity_monitor` row and log, not to block `alpha_publisher`'s completion.

---

### `tests/unit/test_vocabulary_service.py` (test, pure-Python/no-DB)

**Analog:** `tests/unit/test_concept_registry_service.py` (full relevant section read, lines 1-120)

**Fixture-builder + no-DB pure test pattern** (lines 1-40):
```python
# Source: tests/unit/test_concept_registry_service.py (live, verified)
from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from src.intelligence.concept_registry_service import GateState, decide_comparison_action


def _state(**overrides) -> GateState:
    base = dict(
        status="candidate",
        promotion_consecutive=0,
        ...
    )
    base.update(overrides)
    return GateState(**base)


def test_deprecated_is_untouchable():
    decision = decide_comparison_action(_state(status="deprecated"), won=True, ...)
    assert decision.action == "noop_deprecated"
```
For `VocabularyService`, this style applies directly to the cache-lookup methods
(`.codes()`/`.label()`/`.group_codes()`): build a `VocabularyService` instance, populate
`_entries`/`_groups` dicts directly (bypassing `initialize()`/DB entirely - same spirit as
`_state(**overrides)` bypassing a real `concept_gate` row), then assert on the pure lookup methods.
The three-way ENUM divergence check (mechanism, not exercised by any of the 6 live TEXT-backed
namespaces) should get its own pure-Python test against a small fixture "registry rows / Python
enum / pg_enum-catalog-stub" triple, per RESEARCH.md's test map.

---

### `tests/unit/test_vocabulary_drift_audit.py` (test, pure-Python/no-DB)

**Analog:** same as above (`tests/unit/test_concept_registry_service.py`'s no-DB style), applied to
the drift-comparison pure function (whatever `vocabulary_drift.py` factors out as its
"observed-codes-vs-registered-codes" comparison core - keep DB I/O in a thin wrapper, test the
comparison logic directly against literal `list[str]` fixtures for `''`-filtering (Finding 3) and
`regime_group` scoping (Finding 1) - no DB connection needed for either).

---

### `tests/unit/api/test_vocabulary_api.py` (test, request-response) - **relocated from RESEARCH.md's suggested path**

**Analog:** `tests/unit/api/test_features_route.py` (full 188-line file read, verified)

**Anti-pattern flag (important divergence from RESEARCH.md):** RESEARCH.md's Validation
Architecture section proposes `tests/integration/test_vocabulary_api.py` marked `requires_db`. That
directory/marker convention is **not what this codebase actually does** for FastAPI route tests -
`tests/integration/` has zero files using `TestClient`/`httpx.AsyncClient` (confirmed via grep); the
real, live convention for API route tests is `tests/unit/api/*.py` using `fastapi.testclient.TestClient`
against a minimal `FastAPI()` test app with `dependency_overrides` and `AsyncMock` - **no real DB
required at all**. Follow `test_features_route.py`'s pattern instead; this is a stronger, more
accurate analog than RESEARCH.md's suggestion and removes an unnecessary `requires_db`-marked test.

**Full pattern** (lines 1-73):
```python
# Source: tests/unit/api/test_features_route.py (live, verified)
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.routes.features import router as features_router

# Minimal test app - avoids lifespan startup (no DB/Redis required)
test_app = FastAPI()
test_app.include_router(features_router, prefix="/api")


@pytest.fixture
def mock_db():
    """AsyncMock database manager."""
    db = AsyncMock()
    return db


@pytest.fixture
def client(mock_db):
    """TestClient with dependency override for get_db_manager."""
    test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    yield TestClient(test_app)
    test_app.dependency_overrides.clear()
```

**Assertion pattern for a happy-path GET + a not-found case** (lines 79-99, 139-148 - adapt for
namespace lookups):
```python
def test_get_features_returns_paginated_rows(self, client, mock_db):
    mock_db.fetch = AsyncMock(return_value=[row1, row2])
    response = client.get("/api/features/ESH6/1m")
    assert response.status_code == 200
    data = response.json()
    assert "rows" in data
    ...

def test_get_features_returns_empty_list_when_no_data(self, client, mock_db):
    mock_db.fetch = AsyncMock(return_value=[])
    response = client.get("/api/features/ESH6/1m")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
```
Note `vocabulary.py`'s route in Pattern Assignments above uses `get_connection()` (drift.py's style)
rather than `dependencies.get_db_manager` (features.py's style) - check which DB-access convention
the actual implementation picks before writing this test's `dependency_overrides` target; if
`get_connection()` is used, the override may need to patch `src.core.database_manager.get_connection`
directly (e.g., via `unittest.mock.patch`) rather than a FastAPI dependency override, since
`get_connection` is imported inline inside the handler (`drift.py` line 23), not injected via
`Depends()`.

## Shared Patterns

### Cached-library-not-microservice service shape (D-05)
**Source:** `src/config/config_service.py` (`__init__`, `initialize()`, `close()`, `get_sync()`)
**Apply to:** `src/config/vocabulary_service.py` in its entirety - this is the single most
load-bearing pattern in the phase; every method on `VocabularyService` should mirror `ConfigService`'s
cache-first, zero-hot-path-I/O contract.

### `integrity_monitor` fact-row persistence
**Source:** `services/ic_engine.py` lines 2637-2649 (the `INSERT INTO integrity_monitor ...
ON CONFLICT ... DO NOTHING` statement)
**Apply to:** `src/config/vocabulary_drift.py` - every drift-audit run writes one row per namespace
per run (`monitor_type='vocabulary_drift'`, `subject=<namespace>`).

### D-06 oneshot completion contract
**Source:** `services/signal_probe_auditor.py` (`main()`/`_amain()` split, `JOB_COMPLETED_TOTAL`
emission) and `scripts/ops/alpha/ops_canary_integrity_assert.py` (`async def main() -> int` +
`sys.exit(asyncio.run(main()))`, the more directly relevant sibling since both live in
`ops_corpus_pipeline_run.sh`)
**Apply to:** the oneshot CLI entrypoint wrapping `vocabulary_drift.py`. Since this script has no
systemd unit (per D-09, it rides a bash script, not a timer), the `_JOB_LABEL`-matches-`%n`-suffix
rule is informational only here - still fine to emit for OTel consistency, but not load-bearing.

### FastAPI route registration
**Source:** `src/api/main.py` lines 195-204 + `src/api/routes/drift.py` (full file)
**Apply to:** `src/api/routes/vocabulary.py` + its one-line registration in `main.py`.

### API route unit-test convention (TestClient + dependency_overrides, not integration/requires_db)
**Source:** `tests/unit/api/test_features_route.py`
**Apply to:** `tests/unit/api/test_vocabulary_api.py` - corrects RESEARCH.md's suggested
`tests/integration/` placement, which has no precedent in this codebase for API route tests.

## No Analog Found

None. All 9 files/units in this phase have a strong (exact or role-match) live analog; no file
requires falling back to RESEARCH.md's Code Examples as a first resort (though RESEARCH.md's
already-drafted `VocabularyService`/query snippets remain useful cross-checks and are cited above
where they add value beyond the analog itself).

## Metadata

**Analog search scope:** `src/config/`, `src/api/routes/`, `src/api/main.py`, `src/intelligence/
concept_registry_service.py` + its test, `services/ic_engine.py`, `services/signal_probe_auditor.py`,
`services/data_quality_auditor.py`, `services/bar_auditor.py`, `services/service_auditor.py`
(`_DAG_ORDER`), `production/migrations/` (218, 227, 229, 233, 234, 236), `scripts/ops/corpus/
ops_corpus_pipeline_run.sh`, `scripts/ops/alpha/ops_canary_integrity_assert.py`, `tests/unit/
test_concept_registry_service.py`, `tests/unit/api/test_features_route.py`, direct psql queries
against the live `indicagent` database.

**Files scanned:** ~20 read in full or targeted ranges; live DB queried directly for 4 tables
(`market_regimes`, `feature_registry`, `market_data_ohlcv`, `instruments`) to re-verify RESEARCH.md's
Critical Findings 1/2 - all confirmed still accurate as of this mapping pass (15 `market_regimes`
labels across `equity`/`rates`, 3 live `feature_registry.tier` values, 5 `timeframe` values, 3
`asset_class` values).

**Pattern extraction date:** 2026-07-16
