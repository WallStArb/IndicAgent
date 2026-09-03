# Phase 142A: Ensemble IC Measurement - Pattern Map

**Mapped:** 2026-06-30
**Files analyzed:** 8 (2 modified, 6 new)
**Analogs found:** 8 / 8 (every file has a strong in-codebase analog)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/ensemble_ic_engine.py` (NEW) | service (batch oneshot) | batch / transform (CPU-bound IC compute) | `services/ensemble_trainer.py` (BaseBatch+asyncpg shell) + `services/ic_engine.py` (IC math to import) | exact (two-part: shell + math) |
| `production/migrations/187_alpha_ensemble_ic.sql` (NEW) | migration / config | file-I/O (DDL + APR seed) | `production/migrations/168_ensemble_tables.sql` (hypertable DDL) + `production/migrations/186_alpha_ensemble_gate_apr_seeds.sql` (APR seed) | exact |
| `scripts/ops/alpha/ops_ensemble_ic_gate.py` (NEW, Wave 2) | utility / ops script | request-response (SQL → verdict) | `scripts/ops/pipeline/ops_pipeline_status.py` (asyncpg + render pattern) | role-match |
| `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py` (NEW, Wave 2) | utility / ops script | request-response (SQL → markdown report) | `scripts/ops/pipeline/ops_pipeline_status.py` | role-match |
| `services/service_auditor.py` (MODIFIED) | config / registry | request-response (dict edits) | itself (existing oneshot registrations) | exact |
| `tests/unit/test_ensemble_ic_math.py` (NEW, Wave 0) | test | transform | `tests/unit/test_fisher_z_ci.py` | exact |
| `tests/unit/test_ensemble_ic_config.py` (NEW, Wave 0) | test | transform | `tests/unit/test_ensemble_trainer.py` (config binding) | role-match |
| `tests/unit/test_ensemble_ic_bh_fdr.py`, `test_ensemble_ic_decay.py`, `test_ensemble_ic_wf_stability.py`, `test_ensemble_ic_gate.py`, `test_ensemble_ic_executable_returns.py` (NEW, Wave 0) | test | transform | `tests/unit/test_fisher_z_ci.py` + `tests/unit/test_ensemble_meta_fdr.py` | exact |

---

## Pattern Assignments

### `services/ensemble_ic_engine.py` (service, batch / transform)

**Analogs:** `services/ensemble_trainer.py` (BaseBatch+asyncpg shell) and `services/ic_engine.py` (IC math to compose — DO NOT subclass, DO NOT fork).

**Imports pattern** (model on `services/ensemble_trainer.py:32-68` + `services/alpha_publisher.py:26-53`):
```python
from __future__ import annotations

import asyncio
import dataclasses
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import structlog
from scipy.stats import rankdata
from statsmodels.stats.multitest import multipletests

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.observability.corpus_manifest import CorpusManifest
from src.observability.otel import OTelInitError, init_otel_providers

# Compose IC math from ic_engine — import the private pure functions (Pattern 1)
from services.ic_engine import (
    ICEngineConfig,        # for shared lookahead mapping
    _compute_ic_rolling_metrics,
    _fisher_z_ci,
    _nan_to_none,
    _p_values_from_ic,
    _vectorized_ic,
)
```

**BaseBatch shell pattern** (copy from `src/core/agent/base_batch.py:30-117` and `services/ensemble_trainer.py:224-249`):
```python
class EnsembleICEngine(BaseBatch):
    job_name = "ensemble-ic-engine"        # D-06 label; matches systemd %n suffix
    compute_version = "1.0.0"              # bump when IC methodology changes

    async def execute(self, pool: asyncpg.Pool) -> None:
        manifest = CorpusManifest("ensemble_ic_engine", Path(".planning/corpus_manifests"))
        try:
            await self._execute_inner(pool, manifest)
        except Exception as error:        # CLAUDE.md: variable name is `error`, not `exc`
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise
```
`BaseBatch.run()` (lines 74-97) owns: pool setup → `execute()` → `_emit_completion(status, elapsed)` (D-06 `JOB_COMPLETED_TOTAL.add(1, {"job": self.job_name, "status": status})`) → teardown → `flush_and_shutdown_metrics()`. Do NOT reimplement.

**Entrypoint pattern** (copy verbatim from `services/ensemble_trainer.py:641-649`):
```python
if __name__ == "__main__":
    try:
        init_otel_providers("indicagent-ensemble-ic-engine")
    except OTelInitError as error:
        _logger.warning("ensemble_ic_engine.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(EnsembleICEngine(db_dsn=db_dsn).run())
```

**APR compile-time binding pattern** (copy from `services/ensemble_trainer.py:76-140`, adapt to `EnsembleICConfig`):
```python
_APR_QUERY = "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.%'"

async def _load_apr(conn: asyncpg.Connection) -> dict[str, Any]:
    rows = await conn.fetch(_APR_QUERY)
    return {r["config_key"]: r["config_value"] for r in rows}

@dataclasses.dataclass(frozen=True)
class EnsembleICConfig:
    decay_threshold: float
    min_qualifying_fraction: float
    wf_stability_ratio: float
    gate_lookahead: str
    # ... reuse ICEngineConfig for shared keys (fdr_alpha, walk_forward_folds,
    # sharpe_window_size, sharpe_min_windows, subsample_min_stride, min_reliable_n,
    # hac_max_lag, lookahead_fast/mid/slow/extended, n_workers)

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> EnsembleICConfig:
        return cls(
            decay_threshold=_cfg_float(cfg, "alpha.ensemble_ic.decay_threshold", 0.1),
            min_qualifying_fraction=_cfg_float(cfg, "alpha.ensemble_ic.min_qualifying_fraction", 0.60),
            # ... etc
        )
```
Frozen dataclass is pickle-safe for `ProcessPoolExecutor` workers (same rationale as `ICEngineConfig`, `services/ic_engine.py:240-308`).

**Startup crash-loud gate** (copy from `services/ensemble_trainer.py:195-216` + `services/ic_engine.py:316-360`):
```python
async def _assert_prerequisites(conn: asyncpg.Connection) -> None:
    n_alpha = await conn.fetchval("SELECT count(*) FROM alpha_events")
    if not n_alpha:
        raise RuntimeError(
            "EnsembleICEngine startup gate FAILED: alpha_events is empty. "
            "Run ensemble_trainer + alpha_publisher (Phase B corpus) first."
        )
    n_fr = await conn.fetchval(
        "SELECT count(*) FROM forward_returns WHERE return_type = 'executable_open_to_open'"
    )
    if not n_fr:
        raise RuntimeError("EnsembleICEngine startup gate FAILED: forward_returns empty.")
    # market_regimes, alpha_score NOT NULL implicitly verified by alpha_events schema.
```

**The alpha_events + forward_returns + market_regimes JOIN** (adapt the regime JOIN from `services/ensemble_trainer.py:464-480` and the forward_returns query from `services/ic_engine.py:723-734`):
```python
# EnsembleTrainer market_regimes JOIN pattern (services/ensemble_trainer.py:472-477):
fv_rows = await conn.fetch(
    """
    SELECT ae.symbol, ae.alpha_score, ae.bar_ts
    FROM alpha_events ae
    JOIN market_regimes mr
      ON mr.asset_class = 'equity' AND mr.tf = ae.tf AND mr.ts = ae.bar_ts
    WHERE ae.tf = $1 AND mr.regime_label = $2
      AND ae.bar_ts < $3              -- OOS boundary: alpha.validation.oos_start
    ORDER BY ae.bar_ts
    """,
    tf, regime, oos_start,
)
# forward_returns MUST filter return_type = 'executable_open_to_open' (Invariant 1)
# Source: services/ic_engine.py:725-731
```

**IC computation cell — compose ic_engine math for alpha_score = 1 predictor** (adapt `services/ic_engine.py:850-954`; alpha_score is shape `[n_obs, 1]` so collinearity clustering is SKIPPED):
```python
# Import & call — DO NOT re-derive. Source: services/ic_engine.py:376-397, 405-422, 456-462, 537-629
ranks_X = rankdata(alpha_scores.reshape(-1, 1), axis=0)   # [n_obs, 1]
ranks_Y = rankdata(forward_returns_scale)                  # [n_obs]
ic_vector = _vectorized_ic(ranks_X, ranks_Y)               # [1]
ic_value = float(ic_vector[0])
p_value = float(_p_values_from_ic(ic_vector, n_valid)[0])
ci_lower_nd, ci_upper_nd = _fisher_z_ci(ic_vector, n_valid)
ic_ci_lower = float(ci_lower_nd[0])

# Walk-forward: expanding window, scale-specific embargo (Phase A P3 fix)
# Source: services/ic_engine.py:913-940
embargo_bars = lookahead_bars          # NOT max(lookaheads) — P3 fix
fold_ics = []
for k in range(walk_forward_folds):    # 3 folds
    train_end = int(n_valid * (k + 1) / (walk_forward_folds + 1))
    test_start = train_end + embargo_bars
    test_end = int(n_valid * (k + 2) / (walk_forward_folds + 1))
    if test_start >= test_end or (test_end - test_start) < min_reliable_n:
        continue
    fold_ic = _vectorized_ic(
        rankdata(ranks_X[test_start:test_end], axis=0),
        ranks_Y[test_start:test_end],
    )[0]
    fold_ics.append(fold_ic)

# IC Sharpe / HAC / Sortino / win-rate via the shared helper (n_total_features=1)
# Source: services/ic_engine.py:537-629, 959-974
(sharpe_arr, sharpe_hac_arr, sortino_arr, win_rate_arr, n_windows) = _compute_ic_rolling_metrics(
    X_sub, returns_sub, scale_idx, complete_mask, config,
    non_degenerate_mask=np.array([True]), n_total_features=1, stride=scale_stride,
)
```

**ProcessPoolExecutor: compute-only workers + serial writes from main** (CLAUDE.md invariant; copy structure from `services/ic_engine.py:2097-2151, 1763-1872`):
```python
# Workers receive (symbol, tf, dsn, config, ...) and return list[dict] rows — NO DB writes.
# Source: services/ic_engine.py:1763-1872 (_run_ic_worker)
worker_args = [(symbol, tf, dsn, config, run_ts, mr_dict, existing_keys_frozen)
               for symbol in symbols for tf in tfs]
with ProcessPoolExecutor(max_workers=n_workers) as exe:
    for result in exe.map(_run_ensemble_ic_worker, worker_args, chunksize=1):
        corpus_all_results.extend(result["rows"])
        corpus_pvals_flat.extend(result["pvals"])
        corpus_pval_result_idxs.extend(offset + i for i in result["pval_idxs"])
```
**Worker MUST NOT open a write connection or call `conn.commit()` for writes** — concurrent writers on the same hypertable cause index-page deadlocks (CLAUDE.md; fixed in regime_writer). Workers return serializable dicts only.

**Corpus-level BH-FDR — ONE multipletests call** (Phase A P2 fix; copy from `services/ic_engine.py:2213-2234`. For EnsembleICEngine there is NO collinearity clustering step because alpha_score is 1 predictor — every cell IS representative):
```python
# Source: services/ic_engine.py:2219-2234
if corpus_pvals_flat:
    reject_all, p_corr_all, _, _ = multipletests(
        corpus_pvals_flat, alpha=config.fdr_alpha, method="fdr_bh"
    )
    for flat_idx, result_idx in enumerate(corpus_pval_result_idxs):
        corpus_all_results[result_idx]["bh_adjusted_p"] = float(p_corr_all[flat_idx])
        corpus_all_results[result_idx]["passes_fdr"] = bool(reject_all[flat_idx])
```

**Serial write from main process via asyncpg executemany** (translate `services/ic_engine.py:1719-1755` from psycopg2 `execute_batch` to asyncpg `executemany`; mirror `services/ensemble_trainer.py:567-577`):
```python
# ic_engine uses psycopg2 execute_batch (services/ic_engine.py:1731-1737) — EnsembleICEngine
# uses asyncpg executemany per the BaseBatch+asyncpg mandate (ensemble_trainer.py:567-577):
async with pool.acquire() as wconn:
    async with wconn.transaction():
        await wconn.executemany(_ENSEMBLE_IC_INSERT_SQL, rows_to_write)
```

**EIC-02 decay → hold_max_bars APR calibration** (use `ConfigService.set()` async; `alpha.` is already in `OPS_PREFIXES` so no code change needed — verified `src/config/config_service.py:51`):
```python
# ConfigService.set signature (src/config/config_service.py:164-171):
#   async def set(self, key, value, changed_by="system", expected_version=None, reason=None)
apr_key = f"alpha.frame.hold_max_bars.{regime}.{tf}"   # 9 regimes × 4 TFs = 36 keys
await config_service.set(
    apr_key, str(hold_bars),
    changed_by="ensemble-ic-engine",
    reason="calibrated from IC decay curve (EIC-02)",
)
```

---

### `production/migrations/187_alpha_ensemble_ic.sql` (migration / config)

**Analogs:** `production/migrations/168_ensemble_tables.sql` (hypertable DDL) and `production/migrations/186_alpha_ensemble_gate_apr_seeds.sql` (APR seed triple-INSERT).

**Hypertable + composite PK pattern** (copy from `production/migrations/168_ensemble_tables.sql:63-87, 95-123`. Composite PK MUST include the partition column `scored_at`/`bar_ts` for TimescaleDB):
```sql
-- Source: production/migrations/168_ensemble_tables.sql:63-87 (ensemble_alpha hypertable)
CREATE TABLE IF NOT EXISTS alpha_ensemble_ic (
    event_row_id     text             NOT NULL,   -- BaseBatch.content_key(symbol,tf,regime,lookahead,scored_at_ns)
    symbol           text             NOT NULL,   -- 'POOLED' for cross-sectional rows
    tf               text             NOT NULL,
    regime           text             NOT NULL,   -- 9 cross-sectional labels {low,mid,high}_{bull,neutral,bear}
    lookahead        text             NOT NULL,   -- 'fast'|'mid'|'slow'|'extended'
    lookahead_bars   integer          NOT NULL,
    is_pooled        boolean          NOT NULL DEFAULT false,
    n_independent    integer,
    reliable         boolean,
    ic_value         double precision,
    ic_ci_lower      double precision,
    ic_ci_upper      double precision,
    ic_sharpe        double precision,
    ic_sharpe_hac    double precision,
    bh_adjusted_p    double precision,
    passes_fdr       boolean,
    walk_forward_stable boolean,                   -- EIC-03 column
    scored_at        timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (event_row_id, scored_at)          -- composite PK: partition col required
);
SELECT create_hypertable(
    'alpha_ensemble_ic', 'scored_at',
    chunk_time_interval => INTERVAL '3 months', if_not_exists => TRUE
);
CREATE INDEX IF NOT EXISTS alpha_ensemble_ic_cell_idx
    ON alpha_ensemble_ic (symbol, tf, regime, lookahead, scored_at DESC);
```

**APR seed triple-INSERT pattern** (copy from `production/migrations/186_alpha_ensemble_gate_apr_seeds.sql:13-38`. ALWAYS insert into all three of `config_schema`, `config_state`, `config_history`; use `ON CONFLICT (config_key) DO NOTHING`; descriptions carry provenance tags `[initial_estimate]`/`[conventional]`):
```sql
-- Source: production/migrations/186_alpha_ensemble_gate_apr_seeds.sql:13-38
INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES ('alpha.ensemble_ic.decay_threshold', 'float', '0.1',
        '[initial_estimate] IC Sharpe below this = edge expired (EIC-02). Recalibrate after first run.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ensemble_ic.decay_threshold', '0.1', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'alpha.ensemble_ic.decay_threshold', 1, '0.1', 'migration_187',
        'Initial estimate: IC decay threshold for hold_max_bars calibration [initial_estimate]');
```

**APR key set to seed** (36 `hold_max_bars` keys + `alpha.ensemble_ic.*` + `infra.ensemble_ic_engine.workers`):
- `alpha.ensemble_ic.decay_threshold` = 0.1 `[initial_estimate]`
- `alpha.ensemble_ic.min_qualifying_fraction` = 0.60 `[initial_estimate]` (EIC-04 gate — DO NOT bake 0.60 into code)
- `alpha.ensemble_ic.wf_stability_ratio` = 3.0 `[initial_estimate]` (EIC-03)
- `alpha.ensemble_ic.gate_lookahead` = 'fast' `[initial_estimate]` (OQ-3/A6)
- `alpha.ensemble_ic.wf_stability_metric` = 'ic_ratio' `[initial_estimate]` (swappable per A5)
- `alpha.ensemble_ic.min_obs_per_regime` (EIC-05 diagnosis threshold)
- `infra.ensemble_ic_engine.workers` = 12 `[conventional]`
- `alpha.frame.hold_max_bars.<regime>.<tf>` × 36 (9 regimes `{low,mid,high}_{bull,neutral,bear}` × 4 TFs `5m,15m,1h,1d`). Values seeded as `[initial_estimate]` — overwritten by EIC-02 after first run.
- **OQ-1 resolution (load-bearing):** use the 9 cross-sectional `market_regimes.regime_label` values, NOT the stale 4-label `bull/bear/sideways/volatile` namespace from the schema doc.

---

### `scripts/ops/alpha/ops_ensemble_ic_gate.py` (utility, request-response) — Wave 2

**Analogs:** `scripts/ops/pipeline/ops_pipeline_status.py` (asyncpg + render pattern).

**Imports + asyncpg pool + render pattern** (copy from `scripts/ops/pipeline/ops_pipeline_status.py:1-29, 120-129`):
```python
#!/usr/bin/env python3
"""ops_ensemble_ic_gate.py — EIC-04 phase-gate evaluation.

Reads alpha_ensemble_ic, computes the fraction of (symbol, tf, regime) cells
WHERE lookahead = gate_lookahead AND ic_ci_lower > 0 AND passes_fdr = true
       AND walk_forward_stable = true
on in-sample data (bar_ts < alpha.validation.oos_start), compares to
alpha.ensemble_ic.min_qualifying_fraction (APR, NOT baked in), and emits
a PASS/FAIL markdown verdict. Phase 144 re-reads the same query on OOS data.
"""
import asyncio, sys
from datetime import UTC, datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
import asyncpg
from src.config.settings import Settings

async def _fetch(conn, method, sql):
    try:
        return await getattr(conn, method)(sql)
    except Exception as error:      # CLAUDE.md: variable is `error`
        return error
```
**EIC-04 SQL is documented in `142A-RESEARCH.md` Code Examples §EIC-04** — use that query verbatim with `WHERE bar_ts < (SELECT config_value::timestamptz FROM config_state WHERE config_key='alpha.validation.oos_start')`. The threshold comes from `config_state` (`alpha.ensemble_ic.min_qualifying_fraction`), NOT a magic number.

---

### `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py` (utility, request-response) — Wave 2

**Analogs:** `scripts/ops/pipeline/ops_pipeline_status.py` (multi-section fetch + `print_section`/`render`).

**Multi-section markdown render pattern** (copy from `scripts/ops/pipeline/ops_pipeline_status.py:120-209`): use `print_section(title)` + `render()` structure to emit the 4 EIC-05 diagnostic sections (N-per-cell, pooled-vs-per-symbol gap, TF breakdown, regime coverage). Each section is one asyncpg `fetch`/`fetchrow`. Reads `alpha_ensemble_ic` and `feature_ic_scores` for comparison. Emit ONLY on EIC-04 FAIL.

---

### `services/service_auditor.py` (MODIFIED, config / registry)

**Analogs:** itself — existing Phase 138/139 oneshot registrations.

**Edits required** (3 dict additions; pattern verified at `services/service_auditor.py:109-112, 177-203`):
1. `_DAG_ORDER`: add `"indicagent-ensemble-ic-engine": 8,` next to `ic-engine`/`ensemble-trainer`/`alpha-publisher` (priority 8 — same IC-pipeline tier; source lines 109-112).
2. `_ONESHOT_UNITS`: add `"indicagent-ensemble-ic-engine",  # Type=oneshot; inactive between IC pipeline runs is correct` to the frozenset (source lines 200-203).
3. `_AGENT_ID_TO_UNIT`: add the `agent_id → unit` mapping if EnsembleICEngine emits an agent_id metric (check lines 140-177 for the pattern).
4. `_LAG_THRESHOLDS`: NOT applicable — oneshot services are excluded from Prometheus lag checks (the comment at line 200 confirms this).

---

### `tests/unit/test_ensemble_ic_*.py` (test, transform) — Wave 0

**Analogs:** `tests/unit/test_fisher_z_ci.py` (pure-numpy parity test) and `tests/unit/test_ensemble_meta_fdr.py` (FDR test) + `tests/unit/test_ensemble_trainer.py` (config binding).

**Pure-numpy parity test pattern** (copy from `tests/unit/test_fisher_z_ci.py:14-55`):
```python
"""Unit tests: EnsembleICEngine math parity vs ic_engine on synthetic alpha_score.

No DB, no Kafka. Pure numpy.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _fisher_z_ci, _p_values_from_ic, _vectorized_ic

def test_alpha_score_single_predictor_ic_matches_feature_ic():
    """IC(alpha_score[1col], returns) must equal IC computed for 1 feature."""
    # ... synthesize alpha_scores + returns; assert the composed call path reproduces
    # the same ic_value / ci_lower / p_value as a direct scipy.stats.spearmanr.
```
**Config-binding test pattern:** copy `tests/unit/test_ensemble_trainer.py` — assert `EnsembleICConfig.from_apr(cfg_dict)` binds all keys and the dataclass is frozen + pickle-safe (required for ProcessPoolExecutor).

---

## Shared Patterns

### IC math composition (DO NOT subclass, DO NOT fork)
**Source:** `services/ic_engine.py:376-397` (`_fisher_z_ci`), `405-422` (`_vectorized_ic`), `456-462` (`_p_values_from_ic`), `537-629` (`_compute_ic_rolling_metrics`)
**Apply to:** `services/ensemble_ic_engine.py` and all Wave 0 math parity tests
**Rule:** Import these private pure functions and call them. They are module-level, stateless, and carry the Phase A corrections (Fisher z replacing bootstrap, HAC Sharpe, scale-specific embargo). Re-deriving them forks the methodology and risks silent divergence when Phase A ships a fix.

### ProcessPoolExecutor: compute-only workers + serial DB writes from main
**Source:** `services/ic_engine.py:1763-1872` (`_run_ic_worker`), `2088-2151` (main loop), `1719-1755` (`_write_ic_results`)
**Apply to:** `services/ensemble_ic_engine.py`
**Rule (CLAUDE.md invariant):** Workers return `list[dict]`; main accumulates, applies corpus BH-FDR, then writes serially via one connection. Never open a write connection or call `conn.commit()` for writes from a worker subprocess (concurrent hypertable writers deadlock).

### Corpus-level BH-FDR (single multipletests call)
**Source:** `services/ic_engine.py:2213-2234`
**Apply to:** `services/ensemble_ic_engine.py` (after all workers complete)
**Rule (Phase A P2 fix):** Collect ALL cell p-values into one flat list; call `multipletests(pvals, alpha=fdr_alpha, method="fdr_bh")` ONCE; scatter results back via offset index lists. Per-symbol FDR inflates the effective rate ~232×. For EnsembleICEngine there is NO collinearity clustering step (alpha_score is 1 predictor — every cell is representative).

### executable_open_to_open forward returns (Invariant 1)
**Source:** `services/ic_engine.py:725-731` (the `WHERE return_type = 'executable_open_to_open'` filter)
**Apply to:** `services/ensemble_ic_engine.py` forward_returns query AND `ops_ensemble_ic_gate.py`
**Rule:** Theoretical returns capture untradeable overnight gaps and overstate IC. Every forward_returns query in this phase MUST filter `return_type = 'executable_open_to_open'`.

### Cross-sectional market_regimes regime stratification (OQ-1 resolution)
**Source:** `services/ic_engine.py:768-799` (mr_dict override), `services/ensemble_trainer.py:472-477` (the JOIN)
**Apply to:** `services/ensemble_ic_engine.py` (regime JOIN), migration 187 (`regime` column values + `hold_max_bars.*` key namespace), both Wave 2 scripts
**Rule:** Use the 9 cross-sectional `market_regimes.regime_label` values `{low,mid,high}_{bull,neutral,bear}`. NOT the stale 4-label `bull/bear/sideways/volatile` from the schema doc. Stratifying on the wrong set means `alpha_ensemble_ic.regime` cannot JOIN back to `alpha_events.regime`.

### APR compile-time binding + `ConfigService.set()` for calibration writes
**Source:** binding: `services/ensemble_trainer.py:109-140`; writes: `src/config/config_service.py:164-171`
**Apply to:** `services/ensemble_ic_engine.py`
**Rule:** Bind all APR reads into a frozen dataclass at startup (`from_apr()`). For EIC-02 `hold_max_bars` writes, use `await config_service.set(key, value, changed_by=..., reason=...)`. `alpha.` is already in `OPS_PREFIXES` (`src/config/config_service.py:51`) — no `ui.`-style prefix registration needed for `alpha.frame.*`.

### D-06 job_completed_total + OTel init (BaseBatch contract)
**Source:** `src/core/agent/base_batch.py:74-97, 157-170`; entrypoint: `services/ensemble_trainer.py:641-649`
**Apply to:** `services/ensemble_ic_engine.py`
**Rule:** Extend `BaseBatch`; define `job_name="ensemble-ic-engine"` + `compute_version`; implement `async def execute(pool)`. The `run()` template emits D-06 on success/failure. `flush_and_shutdown_metrics()` is called in `finally`.

---

## No Analog Found

None. Every file in this phase has a strong in-codebase analog. The phase is a near-mechanical port of `services/ic_engine.py` onto a single composite predictor, wrapped in the `BaseBatch`+asyncpg shell proven by `services/ensemble_trainer.py` and `services/alpha_publisher.py`.

---

## Metadata

**Analog search scope:** `services/` (ic_engine.py, ensemble_trainer.py, alpha_publisher.py), `src/core/agent/base_batch.py`, `src/config/config_service.py`, `services/service_auditor.py`, `production/migrations/` (168, 186), `scripts/ops/pipeline/`, `tests/unit/`.
**Files scanned:** 11 source files + 2 migrations + 6 tests (targeted reads; no full-file re-reads).
**Pattern extraction date:** 2026-06-30
**Load-bearing verifications performed:**
- `alpha_events.alpha_score` is `double precision NOT NULL`; `regime` is nullable `text` (live DB query).
- `alpha.ensemble_ic.*`, `alpha.frame.hold_max_bars.*`, `infra.ensemble_ic_engine.*` keys are ABSENT from `config_state` (greenfield confirmed — the migration is additive).
- `alpha.` is in `OPS_PREFIXES` (`src/config/config_service.py:51`) — `alpha.frame.*` writes need no code change.
- `market_regimes` has 9 distinct `regime_label` values (RESEARCH.md verified via live query).
