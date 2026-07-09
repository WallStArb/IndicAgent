# Phase 142B: Frame Simulation + Counterfactual Tracking - Pattern Map

**Mapped:** 2026-07-09
**Files analyzed:** 8 (2 new services, 1 new migration, 1 new doc, 4 new test files distilled into 6 test-family patterns)
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `services/alpha_frame_writer.py` (`AlphaFrameWriter`) | service (batch writer) | CRUD (DB read `alpha_events`+`feature_vectors` → DB write `alpha_frames`) | `services/alpha_publisher.py` | exact — same `BaseBatch` chunked accumulate-and-flush shape, same 12M-row order of magnitude, same `content_key()`-derived idempotent PK |
| `services/counterfactual_tracker.py` (`CounterfactualTracker`) | service (batch compute + writer) | batch / transform (DB read `market_data_ohlcv`+`alpha_ensemble_ic` → DB write `alpha_frames` updates) | `services/ensemble_ic_engine.py` | exact — same `ProcessPoolExecutor` per-symbol dispatch, named server-side cursor, single serial main-process write |
| `production/migrations/214_alpha_frames_schema.sql` | migration | batch (DDL + APR seed) | `production/migrations/195_alpha_ensemble_ic.sql` | exact — same shape: `CREATE TABLE IF NOT EXISTS` + CHECK constraint + hypertable + APR key seed block (`config_schema`/`config_state`/`config_history` triads) |
| `docs/plans/SHADOW-REVIEW.md` | config/doc (pre-commitment) | N/A (static doc, no runtime tier) | `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` (structure/tone only) | role-match — no code analog exists for a frozen pre-commitment doc; use the schema doc's section-heading discipline as the closest structural precedent |
| `services/service_auditor.py` (edit: register 2 units) | config (registry edit) | N/A | Existing `indicagent-ensemble-ic-engine` entry in same file | exact — literal 3-line pattern to replicate twice |
| `tests/unit/test_alpha_frame_writer_geometry.py`, `test_alpha_frame_writer.py` | test | pure-fn / unit | `tests/unit/test_ensemble_ic_config.py` | exact — pure dataclass/pure-fn binding tests, no DB |
| `tests/unit/test_counterfactual_tracker_exit_priority.py`, `test_counterfactual_tracker.py` | test | pure-fn / unit (grep-based no-DB-write guard) | `tests/unit/test_ic_engine_compute_split.py` | exact — `test_compute_symbol_tf_has_no_db_write_code`'s grep-for-`execute_batch` idiom is the direct template for asserting `CounterfactualTracker`'s worker never writes |
| `tests/unit/test_alpha_frames_schema.py`, `test_frame_gate.py` | test | schema assertion / pure-fn | `tests/unit/test_ensemble_ic_config.py` (schema-adjacent), `docs`/migration DDL itself | role-match — no exact "assert CHECK constraint values" test exists yet; build from migration DDL text directly |

## Pattern Assignments

### `services/alpha_frame_writer.py` (service, CRUD batch writer)

**Analog:** `services/alpha_publisher.py` (full file read, 515 lines)

**Imports pattern** (`services/alpha_publisher.py:26-53`):
```python
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async as _load_apr
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.core.service_utils import format_iso_ts
from src.observability.corpus_manifest import CorpusManifest
from src.observability.metrics import (
    ALPHA_PUBLISHER_BARS_SCORED_TOTAL,
    ALPHA_PUBLISHER_EMISSIONS_TOTAL,
)
from src.observability.otel import OTelInitError, init_otel_providers
```
`AlphaFrameWriter` drops the `KafkaProducerClient`/`topic_alpha_events` import entirely (Pitfall 5: no Kafka topic for this service — mirror `ensemble_ic_engine.py`'s import list instead, which has none of the Kafka imports either).

**BaseBatch subclass skeleton + job_name convention** (`services/alpha_publisher.py:62-83`):
```python
class AlphaPublisher(BaseBatch):
    job_name = "alpha-publisher"
    compute_version = "1.0.0"
    ensemble_version = "v1.0.0"
    _CHUNK_SIZE = 50_000

    def __init__(self, db_dsn: str, skip_kafka: bool = False, weight_version_override: str | None = None) -> None:
        super().__init__(db_dsn)
        self.skip_kafka = skip_kafka
        self._weight_version_override = weight_version_override
```
For `AlphaFrameWriter`: `job_name = "alpha-frame-writer"`, `compute_version = "1.0.0"`, constructor takes `db_dsn: str, backfill: bool = False` (D-05's `--backfill` flag, no Kafka analog needed).

**Manifest-wrapped error handling** (`services/alpha_publisher.py:107-118`, identical shape in `ensemble_ic_engine.py:877-887`):
```python
async def execute(self, pool: asyncpg.Pool) -> None:  # type: ignore[override]
    manifest = CorpusManifest("alpha_publisher", CorpusManifest.DEFAULT_MANIFEST_DIR)
    try:
        await self._execute_inner(pool, manifest)
    except Exception as error:  # CLAUDE.md: exception variable name is `error`
        manifest.add_error(str(error))
        try:
            manifest.write()
        except Exception:
            pass
        raise
```
Copy verbatim, substituting `"alpha_frame_writer"` as the manifest name.

**Core CRUD pattern — chunked accumulate-and-flush write** (`services/alpha_publisher.py:220-234`, `:396-401`):
```python
_CHUNK_SIZE = 50_000
_chunk: list[tuple] = []
async for row in conn.cursor(SQL, *params, prefetch=10000):
    _chunk.append(row_to_tuple(row))
    if len(_chunk) >= _CHUNK_SIZE:
        async with pool.acquire() as wconn:
            await wconn.executemany(_INSERT_SQL, _chunk)
        _chunk.clear()
if _chunk:
    async with pool.acquire() as wconn:
        await wconn.executemany(_INSERT_SQL, _chunk)
```
Note (research-verified): `conn.cursor(SQL, prefetch=10000)` here is **asyncpg's** cursor (safe, already streams server-side) — not the same object as a plain psycopg2 cursor. Fine to use as-is in the main process for `AlphaFrameWriter`'s single-pass, non-parallel design (Open Question 1's recommendation: start single-process, matching this file exactly; do not add `ProcessPoolExecutor` unless the one-time backfill benchmarks too slow).

**--backfill mode as anti-join query-scope switch (D-05)** — no literal precedent line range exists in `alpha_publisher.py` (it always does a full weight_version-scoped delete+rewrite, a different idempotency strategy); the pattern to build is described in RESEARCH.md Pattern 4 and must be written fresh:
```sql
-- Same query serves both nightly-incremental and --backfill; only the anti-join's
-- "pending" set differs by data state, not by code path.
SELECT ae.* FROM alpha_events ae
LEFT JOIN alpha_frames af
  ON af.event_id = ae.event_id AND af.bar_ts = ae.bar_ts AND af.frame_variant = 'primary'
WHERE af.frame_id IS NULL
```

**Idempotent ID generation via `content_key()`** (`services/alpha_publisher.py:337`):
```python
event_id = BaseBatch.content_key(symbol, tf, bar_ts_ns, self.ensemble_version, weight_version)
```
For `AlphaFrameWriter`: `frame_id = BaseBatch.content_key(event_id, str(bar_ts), frame_variant)`, paired with `ON CONFLICT (event_id, bar_ts, frame_variant) DO NOTHING` per RESEARCH.md Pattern 1.

**CLI entrypoint pattern** (`services/alpha_publisher.py:483-515`):
```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="...")
    parser.add_argument("--skip-kafka", action="store_true", help="...")
    parser.add_argument("--weight-version", default=None, help="...")
    args = parser.parse_args()
    try:
        init_otel_providers("indicagent-alpha-publisher")
    except OTelInitError as error:
        _logger.warning("alpha_publisher.otel_init_failed", error=str(error))
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(AlphaPublisher(db_dsn=db_dsn, ...).run())
```
Replace `--skip-kafka`/`--weight-version` with `--backfill` (`action="store_true"`); keep the `init_otel_providers("indicagent-alpha-frame-writer")` / DSN-strip / `asyncio.run(...)` shape identical.

---

### `services/counterfactual_tracker.py` (service, batch transform + writer)

**Analog:** `services/ensemble_ic_engine.py` (targeted read: lines 634-973, plus migration/config sections)

**ProcessPoolExecutor worker dispatch — one task per symbol, read-only connection** (`services/ensemble_ic_engine.py:634-691`):
```python
def _run_ensemble_ic_worker(args: tuple) -> dict[str, Any]:
    """ProcessPoolExecutor worker -- runs in subprocess. Opens ONE read-only connection
    for this symbol and loops over all its TFs...
    One connection per worker dispatch (not per (symbol, tf) pair) amortizes connection
    setup across the symbol's TFs.
    """
    symbol, tfs, dsn, oos_start, config, run_ts, weight_version = args
    rows, pvals, pval_idxs, errors = [], [], [], []
    try:
        conn = connect_db_from_url(dsn)
    except Exception as error:
        return {"rows": rows, "pvals": pvals, "pval_idxs": pval_idxs,
                "is_pooled": False, "errors": [f"{symbol}: connection failed: {error}"]}
    try:
        for tf in tfs:
            try:
                ...  # fetch + compute per tf
            except Exception as error:
                errors.append(f"{symbol}/{tf}: {error}")
                try:
                    conn.rollback()
                except Exception:
                    pass
                continue
            ...
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {"rows": rows, "pvals": pvals, "pval_idxs": pval_idxs, "is_pooled": False, "errors": errors}
```
`CounterfactualTracker`'s worker mirrors this exactly: one task per symbol, looping its `(tf, open_frame)` set over a single read-only psycopg2 connection, returning `list[dict]` outcome rows — never writing.

**Named (server-side) cursor for large per-symbol fetch — CRITICAL, do not use a plain cursor** (`services/ensemble_ic_engine.py:710-716`):
```python
conn.commit()  # clear any open transaction before declaring a named cursor (required precondition)
with conn.cursor(
    name=f"pooled_fetch_{tf}", cursor_factory=psycopg2.extras.RealDictCursor
) as cur:
    cur.itersize = config.pooled_fetch_itersize
    cur.execute(_POOLED_WORKER_FETCH_SQL, (tf, weight_version, oos_start))
    fetched = _aggregate_pooled_series(cur, tf)
```
Verified via `git show e9b3bcde`: a *plain* `conn.cursor()` in psycopg2 pulls the entire result set client-side at `execute()` time regardless of subsequent iteration — `itersize` is a no-op on an unnamed cursor. `CounterfactualTracker`'s bar-path scan over `market_data_ohlcv` (up to `hold_max_bars` subsequent bars × up to 12M+ frames) MUST use `conn.cursor(name=..., cursor_factory=psycopg2.extras.RealDictCursor)` with `cur.itersize` set from an APR key (e.g. `infra.counterfactual_tracker.itersize`), never `conn.cursor()`.

**Main-process dispatch + result aggregation (DAG invariant #3: workers never write)** (`services/ensemble_ic_engine.py:966-973`):
```python
with ProcessPoolExecutor(max_workers=config.n_workers) as exe:
    for result in exe.map(_run_ensemble_ic_worker, worker_args, chunksize=1):
        worker_errors.extend(result["errors"])
        offset = len(corpus_all_results)
        corpus_all_results.extend(result["rows"])
        corpus_pvals_flat.extend(result["pvals"])
        corpus_pval_result_idxs.extend(offset + i for i in result["pval_idxs"])
# ... single serial async batch write happens AFTER this loop, in the main process only
```

**Connection-staleness check before each unit of work** (`scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py:1044-1052`):
```python
try:
    db_conn.cursor().execute("SELECT 1")
except Exception:
    print("  DB connection stale — reconnecting before next symbol...")
    try:
        db_conn.close()
    except Exception:
        pass
    db_conn = connect_db(settings)
```
Apply the same shape inside `CounterfactualTracker`'s per-symbol dispatch loop (or per-chunk in `--backfill` mode) before each unit of work — directly portable per RESEARCH.md Pattern 4 point 4.

**Exit-trigger priority order (FRAME-02/03, pure function target for unit-testability)** — from ROADMAP.md FRAME-02 text (RESEARCH.md Code Examples section, no direct codebase line range since this is new logic, styled after `_select_hold_bars_from_decay`'s pure-function shape in `ensemble_ic_engine.py:262`):
```python
def determine_exit(
    bars_since_entry: list[Bar], stop_price: float, target_price: float,
    hold_max_bars: int, ic_ci_lower: float | None,
) -> ExitResult | None:
    for i, bar in enumerate(bars_since_entry, start=1):
        if bar.low <= stop_price:
            return ExitResult(status="closed_stop", bars=i, exit_price=stop_price)
        if bar.high >= target_price:
            return ExitResult(status="closed_target", bars=i, exit_price=target_price)
        if i >= hold_max_bars:
            return ExitResult(status="closed_max_hold", bars=i, exit_price=bar.close)
    if ic_ci_lower is not None and ic_ci_lower < 0:
        return ExitResult(status="closed_ic_decay", bars=len(bars_since_entry),
                           exit_price=bars_since_entry[-1].close if bars_since_entry else None)
    return None  # still open
```
D-08: read `ic_ci_lower` from the most recent `alpha_ensemble_ic` row regardless of age. D-10: instrument the row's age via a point gauge (see Shared Patterns below).

---

### `production/migrations/214_alpha_frames_schema.sql` (migration)

**Analog:** `production/migrations/195_alpha_ensemble_ic.sql` (full file, 212 lines)

**CREATE TABLE + CHECK constraint + hypertable shape** (`migrations/195_alpha_ensemble_ic.sql:34-69`):
```sql
CREATE TABLE IF NOT EXISTS alpha_ensemble_ic (
    event_row_id text NOT NULL,
    ...
    PRIMARY KEY (event_row_id, scored_at),
    CONSTRAINT alpha_ensemble_ic_pooled_symbol_consistent CHECK ((symbol = 'POOLED') = is_pooled)
);
SELECT create_hypertable('alpha_ensemble_ic', 'scored_at', chunk_time_interval => INTERVAL '3 months', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS alpha_ensemble_ic_cell_idx ON alpha_ensemble_ic (symbol, tf, regime, lookahead, scored_at DESC);
```
For `alpha_frames`: apply D-04's corrected CHECK constraint directly —
```sql
status text NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'closed_stop', 'closed_target', 'closed_max_hold', 'closed_ic_decay')),
```
(no `closed_reversal`; includes `closed_ic_decay`) — every other column/index/FK from the 2026-06-25 schema doc's DDL (lines 122-193) still governs, plus new `corpus_run_id text` and `weight_epoch text` provenance columns (Pitfall 6).

**APR key seed block (config_schema + config_state + config_history triad)** (`migrations/195_alpha_ensemble_ic.sql:75-164`):
```sql
INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES (
    'alpha.ensemble_ic.decay_threshold', 'float', '0.1',
    '[initial_estimate] EIC-02: ... NOT an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ensemble_ic.decay_threshold', '0.1', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'alpha.ensemble_ic.decay_threshold', 1, '0.1', 'migration_195', 'Initial estimate: ... [initial_estimate]');
```
Reuse this exact triad shape for every new key this migration must seed: `alpha.frame.stop_atr_mult`, `alpha.frame.target_r_multiple` (NOT `target_r_fallback` — Pitfall 3), `alpha.scoring.min_strategy_n` (Pitfall 4 — do not defer to Phase 144), and any `infra.counterfactual_tracker.*`/`infra.alpha_frame_writer.*` batch-size/worker-count keys. Provenance tag every description with `[initial_estimate]` or `[conventional]` per CLAUDE.md's APR lifecycle mandate.

**Bulk per-cell APR seed via `DO $$ ... FOREACH ... END $$` loop** (`migrations/195_alpha_ensemble_ic.sql:174-209`) — reuse directly if `alpha.frame.*` needs any per-(regime, tf) cell key beyond the already-existing `hold_max_bars` keys (unlikely per CONTEXT.md, but the idiom is here if needed).

---

### `docs/plans/SHADOW-REVIEW.md` (pre-commitment doc)

No code analog — this is a frozen markdown document, not a runtime artifact. Structural precedent: `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md`'s section-heading discipline (numbered sections, explicit "Open Question N" callouts, explicit APR key tables). Content must be locked in per D-01/D-02/D-03:
- Pass/fail criteria evaluated on **gross** `counterfactual_pnl_r` (D-01) — not `alpha.quant.cost_hurdle.*`-adjusted.
- `net_expected_r` (gross minus `alpha.quant.cost_hurdle.*`) reported as a **mandatory column, not a gate** (D-02).
- Must exist in git, frozen, **before** either service's first production run (research: "static doc, no runtime tier... must exist in git before either service's first production run").

---

## Shared Patterns

### BaseBatch lifecycle (mandatory for both services)
**Source:** `src/core/agent/base_batch.py` (full file, 170 lines)
**Apply to:** `AlphaFrameWriter` and `CounterfactualTracker` both extend `BaseBatch` directly; implement only `async def execute(self, pool)`.
```python
class BaseBatch(abc.ABC):
    job_name: str
    compute_version: str

    async def run(self) -> None:
        await self._setup_pool()
        t0 = time.monotonic()
        status = "success"
        try:
            await self.execute(self._pool)
        except Exception as error:
            status = "failure"
            self.logger.error("batch_computer.failed", job=self.job_name, error=str(error))
            raise
        finally:
            self._emit_completion(status, time.monotonic() - t0)
            await self._teardown_pool()
            flush_and_shutdown_metrics()

    @staticmethod
    def content_key(*parts: str) -> str:
        raw = "|".join(str(p) for p in parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
```
`_emit_completion()` auto-calls `JOB_COMPLETED_TOTAL.add(1, {"job": self.job_name, "status": status})` — D-06 contract, no per-service code needed. `job_name` must be kebab-case matching the systemd unit `%n` suffix exactly (`alpha-frame-writer`, `counterfactual-tracker`).

### Error handling — exception variable name and manifest wrapping
**Source:** `services/ensemble_ic_engine.py:877-887`, `services/alpha_publisher.py:107-118`
**Apply to:** Both services' `execute()` method.
```python
async def execute(self, pool: asyncpg.Pool) -> None:
    manifest = CorpusManifest("<service_name>", CorpusManifest.DEFAULT_MANIFEST_DIR)
    try:
        await self._execute_inner(pool, manifest)
    except Exception as error:  # CLAUDE.md: exception variable name is `error`, never `exc`
        manifest.add_error(str(error))
        try:
            manifest.write()
        except Exception:
            pass
        raise
```

### Service registration (`_DAG_ORDER` / `_ONESHOT_UNITS`)
**Source:** `services/service_auditor.py` (grep-verified lines)
**Apply to:** Both new services, registered exactly like `indicagent-ensemble-ic-engine`'s precedent — priority 8, oneshot set, **no** `_AGENT_ID_TO_UNIT` entry (that dict is for `BaseDaemon` lag-metric services, not oneshots).
```python
# _DAG_ORDER dict:
"indicagent-alpha-frame-writer": 8,  # Phase 142B oneshot; alpha_events -> alpha_frames (geometry)
"indicagent-counterfactual-tracker": 8,  # Phase 142B oneshot; alpha_frames -> alpha_frames (lifecycle outcome); inactive between IC pipeline runs is correct

# _ONESHOT_UNITS frozenset, in the "Phase 139 ensemble + alpha emission..." comment block:
"indicagent-alpha-frame-writer",  # Phase 142B oneshot; Type=oneshot; inactive between IC pipeline runs is correct
"indicagent-counterfactual-tracker",  # Phase 142B oneshot; Type=oneshot; inactive between IC pipeline runs is correct
```
Per Pitfall 5: do **not** add either service to `_AGENT_ID_TO_UNIT`, and do **not** add `topic_alpha_frames` to `stream_keys.py` unless a concrete downstream Kafka consumer is identified during planning (none is named in ROADMAP.md's FRAME-01..04 text).

### Named server-side cursor discipline (anti-OOM)
**Source:** `services/ensemble_ic_engine.py:710-716`; fix commit `e9b3bcde`; migration `212_ic_engine_symbol_fetch_chunk_rows.sql`
**Apply to:** `CounterfactualTracker`'s per-symbol bar-path scan over `market_data_ohlcv`, exclusively. Never a plain `psycopg2.connect().cursor()` for any fetch that could exceed a few thousand rows.
```python
conn.commit()  # clear any open transaction before declaring a named cursor
with conn.cursor(name=f"cf_scan_{symbol}_{tf}", cursor_factory=psycopg2.extras.RealDictCursor) as cur:
    cur.itersize = config.symbol_fetch_chunk_rows  # APR-backed, e.g. infra.counterfactual_tracker.itersize
    cur.execute(SQL, params)
    for r in cur:
        ...  # reduce-as-you-go, never fetchall()
```

### IC-staleness observability (D-10)
**Source:** `src/observability/metrics.py:83-88` (`point_gauge` helper), `:1179-1198` (`ALPHA_PUBLISHER_*` counter definition style)
**Apply to:** `CounterfactualTracker`'s IC-decay exit trigger read.
```python
# In src/observability/metrics.py, alongside ALPHA_PUBLISHER_* definitions:
COUNTERFACTUAL_TRACKER_IC_ROW_AGE_SECONDS = _meter.create_gauge(
    "counterfactual_tracker_ic_row_age_seconds",
    description=(
        "Age in seconds of the most recent alpha_ensemble_ic row consumed for the "
        "IC-decay exit trigger, per (symbol, tf, regime) cell. D-08: no freshness gate "
        "blocks the read; this gauge makes staleness observable, not silent (D-10)."
    ),
)
# At the call site:
COUNTERFACTUAL_TRACKER_IC_ROW_AGE_SECONDS.set(
    age_seconds, {"symbol": symbol, "tf": tf, "regime": regime}
)
```
Use `.set(value, attrs)` (point gauge — direct OTel SDK, never `prometheus_client`).

### Bootstrap CI gate (FRAME-04)
**Source:** RESEARCH.md Code Examples section; `scipy.stats.bootstrap` (confirmed installed v1.17.1)
```python
from scipy.stats import bootstrap
import numpy as np

def frame_gate_passes(pnl_r_values: np.ndarray, min_n: int) -> tuple[bool, float, float]:
    """Returns (passes, ci_lower, ci_upper). One-tailed: passes iff ci_lower > 0."""
    if len(pnl_r_values) < min_n:
        return False, float("nan"), float("nan")
    res = bootstrap((pnl_r_values,), np.mean, confidence_level=0.95, alternative="greater", method="BCa")
    return bool(res.confidence_interval.low > 0), res.confidence_interval.low, res.confidence_interval.high
```
Do not hand-roll a percentile-bootstrap loop — no existing helper in `ic_math.py` covers this (Fisher-z CIs are a different statistic).

### Test pattern — pure-fn/dataclass config binding (no DB)
**Source:** `tests/unit/test_ensemble_ic_config.py:1-53` (full pattern)
**Apply to:** `test_alpha_frame_writer_geometry.py`, `test_frame_gate.py`
```python
_FULL_CFG_DICT = {"alpha.frame.stop_atr_mult": "2.0", "alpha.frame.target_r_multiple": "3.0", ...}

def test_from_apr_binds_all_keys():
    cfg = FrameConfig.from_apr(_FULL_CFG_DICT)
    assert cfg.stop_atr_mult == 2.0
    ...

def test_from_apr_applies_defaults_when_keys_missing():
    cfg = FrameConfig.from_apr({})
    assert cfg.stop_atr_mult == <documented_default>
```

### Test pattern — grep-based "worker never writes" guard
**Source:** `tests/unit/test_ic_engine_compute_split.py:55-74`
**Apply to:** `test_counterfactual_tracker.py` (FRAME-02's "no DB write inside worker" requirement)
```python
def test_worker_has_no_db_write_code():
    """The ProcessPoolExecutor worker function must not contain execute_batch/executemany
    calls -- DAG invariant #3: workers are compute-only, main process does the one serial write.
    A leading conn.commit() is permitted (clears a stale read-only transaction before a
    named-cursor declaration) -- that's a transaction-boundary reset, not a persistence op.
    """
    source = inspect.getsource(_run_counterfactual_worker)
    assert "execute_batch" not in source
    assert "executemany" not in source
```

## No Analog Found

None. All 8 classified file/pattern groups have a strong (exact or role-match) analog in the existing codebase.

## Metadata

**Analog search scope:** `services/` (batch oneshots), `src/core/agent/` (base classes), `production/migrations/` (recent schema migrations 190-213), `tests/unit/` (ensemble_ic and ic_engine test families), `scripts/infrastructure/backfill/` (chunking/backfill precedent), `src/observability/metrics.py` (OTel gauge/counter conventions)
**Files scanned:** `src/core/agent/base_batch.py` (full, 170 lines), `services/alpha_publisher.py` (full, 515 lines), `services/ensemble_ic_engine.py` (targeted, lines 634-973 + config/imports), `production/migrations/195_alpha_ensemble_ic.sql` (full, 212 lines), `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` (targeted, lines 1015-1194), `services/service_auditor.py` (targeted, `_DAG_ORDER`/`_ONESHOT_UNITS`/`_AGENT_ID_TO_UNIT` sections), `tests/unit/test_ensemble_ic_config.py` (full, 92 lines), `tests/unit/test_ic_engine_compute_split.py` (targeted, lines 26-127), `src/observability/metrics.py` (targeted, gauge/counter helper + `ALPHA_PUBLISHER_*` definitions)
**Pattern extraction date:** 2026-07-09
