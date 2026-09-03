# Phase 148: Alpha Scoring System - Pattern Map

**Mapped:** 2026-07-22
**Files analyzed:** 9 (3 new source files, 1-2 migrations, 3 test files, 1 doc)
**Analogs found:** 9 / 9

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `services/alpha_scorer.py` (`AlphaScorer`, SCORE-01) | service (batch compute, `BaseBatch`) | CRUD (read `alpha_frames`, aggregate, batch-write `alpha_strategy_scores`) | `services/counterfactual_tracker.py` (bootstrap-gate reuse) + `services/ensemble_ic_engine.py` (`BaseBatch` shape) | exact (role) / exact (statistics reuse) |
| `production/migrations/248_alpha_scoring_gate_tables.sql` (single combined file, DDL + APR seed — see the migration-numbering correction below; table cells below still describe DDL/APR-seed as separate analog targets within that one file) | migration (DDL) | batch | `production/migrations/236_alpha_frames_is_shadow.sql` | role-match (DDL structure) |
| ↳ same file, APR-key seed portion | migration (APR seed triple) | batch | `production/migrations/244_regime_gate_min_clusters.sql` | exact |
| `scripts/ops/corpus/ops_oos_gate1_signal_eval.py` (SCORE-02) | script (standalone one-shot governance) | request-response / batch (read-only SELECT + one write to `gate_evaluations`) | `scripts/ops/corpus/ops_oos_holdout_eval.py` | exact |
| `scripts/analysis/score03_gate2_execution_eval.py` (SCORE-03) | script (standalone one-shot governance) | batch (read `alpha_frames`, evaluate, one write to `gate_evaluations`) | `scripts/analysis/phase143_1_08_shadow_validation.py` | exact |
| `tests/unit/test_alpha_scorer.py` | test | CRUD/transform | `tests/unit/test_ensemble_ic_gate.py` (pure-function unit test shape) + `tests/unit/test_counterfactual_tracker.py` (bootstrap-gate test shape) | role-match |
| `tests/unit/test_oos_gate1_signal_eval.py` | test | request-response | `tests/unit/test_oos_holdout_eval.py` | exact |
| `tests/unit/test_score03_gate2_execution_eval.py` | test | batch | `tests/unit/test_ensemble_ic_gate.py` (pure-function extraction pattern) | role-match |
| `docs/plans/archive/2026-07-22-phase148-promotion-decision.md` | doc (governance artifact) | — | `docs/plans/SHADOW-REVIEW.md` / `docs/plans/OOS-EVAL-PROTOCOL.md` | role-match (doc conventions, not code) |

**Reused, not modified (library code — do not duplicate):**
- `services/ensemble_ic_engine.py` — IC helpers import list, `compute_walk_forward_stable`, `_WORKER_FETCH_SQL` join shape
- `services/counterfactual_tracker.py` — `evaluate_frame_gate`, `frame_gate_passes`, `_DEFAULT_BOOTSTRAP_RANDOM_STATE`
- `src/intelligence/statistics/ic_math.py` — `_fisher_z_ci`, `_vectorized_ic`, `_p_values_from_ic`, `_nan_to_none`
- `services/_batch_utils.py` — `cfg()`, `load_apr_dict_async()`, `connect_db_from_url()`

## Pattern Assignments

### `services/alpha_scorer.py` (service, CRUD — new `AlphaScorer(BaseBatch)`)

**Analogs:** `src/core/agent/base_batch.py` (contract), `services/counterfactual_tracker.py` (bootstrap-gate reuse), `services/ensemble_ic_engine.py` (`BaseBatch` class shape + APR-load pattern)

**`BaseBatch` full contract** (`src/core/agent/base_batch.py`, lines 30-68 — read in full, 170 lines total):
```python
class BaseBatch(abc.ABC):
    job_name: str
    compute_version: str

    def __init__(self, db_dsn: str) -> None:
        self._db_dsn = db_dsn
        self._pool: asyncpg.Pool | None = None
        log_name = getattr(self, "job_name", type(self).__name__).replace("-", "_")
        setup_service_logging(f"logs/{log_name}.log")
        self.logger = structlog.get_logger(type(self).__name__)

    @abc.abstractmethod
    async def execute(self, pool: asyncpg.Pool) -> None:
        """Run the batch computation. Called with an open asyncpg Pool."""

    async def run(self) -> None:
        """Template method: pool setup -> execute -> D-06 emission -> teardown."""
        # (BaseBatch.run() owns pool lifecycle, D-06 job_completed_total emission,
        #  and re-raises on failure after logging with error=str(error))
```
`AlphaScorer` only needs: `job_name = "alpha-scorer"`, `compute_version = "1.0.0"`, and `async def execute(self, pool)`. No `__init__` override needed unless a CLI weight-version-style override is added (see `EnsembleICEngine.__init__`, lines 910-912, for that pattern if needed).

**Class + `_execute_inner` skeleton pattern** (`services/ensemble_ic_engine.py`, lines 900-930):
```python
class EnsembleICEngine(BaseBatch):
    job_name = "ensemble-ic-engine"
    compute_version = "1.0.0"

    async def execute(self, pool: asyncpg.Pool) -> None:
        manifest = CorpusManifest("ensemble_ic_engine", CorpusManifest.DEFAULT_MANIFEST_DIR)
        try:
            await self._execute_inner(pool, manifest)
        except Exception as error:  # CLAUDE.md: exception variable name is `error`
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise

    async def _execute_inner(self, pool: asyncpg.Pool, manifest: CorpusManifest) -> None:
        run_ts = datetime.now(UTC)   # pin ONE run_ts, reuse for every written row
        async with pool.acquire() as conn:
            apr_cfg = await _load_apr_dict(conn, extra_like_patterns=_INFRA_LIKE_PATTERNS)
            ...
```
`AlphaScorer` does not need a `CorpusManifest` unless SCORE-01 is registered as a corpus-pipeline stage — confirm with planner; simpler services (e.g. `ops_ensemble_ic_gate.py`) skip it entirely.

**Day-clustered bootstrap reuse — the core statistic** (`services/counterfactual_tracker.py`, `evaluate_frame_gate`, lines 906-979; `frame_gate_passes`, lines 172-235 — both read in full):
```python
# evaluate_frame_gate signature (generalized todo 165 specifically for a 3rd caller like this):
def evaluate_frame_gate(
    rows: Iterable[dict[str, Any]],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int = _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    group_key: Callable[[dict[str, Any]], tuple[Any, Any]] | None = None,
    min_clusters: int | None = None,
) -> list[dict[str, Any]]:
    ...
    # returns one dict per group_key cell: tf, regime, n_frames, n_clusters,
    # ci_lower, ci_upper, passes, coverage ("evaluated" | "insufficient")
```
For SCORE-01's 4-key grain, call with `group_key=lambda row: (row["symbol"], row["tf"], row["regime"], row["alpha_score_decile"])` — note the function's returned dict keys are always named `tf`/`regime` regardless of what `group_key` actually groups by (see docstring lines 937-940); `AlphaScorer` must remap those two output field names to its own 4-key grain, not assume they line up literally. `frame_gate_passes` itself (lines 172-235) does the day-cluster aggregation, BCa-vs-analytic-CLT branch at `bootstrap_max_n`, and returns `(passes: bool, ci_lower: float, ci_upper: float)` — this IS the reusable bootstrap CI; do not reimplement.

**Decile binning input query shape** — base on `_GATE_QUERY_SQL` (`services/counterfactual_tracker.py`, lines 985-992):
```python
_GATE_QUERY_SQL = """
    SELECT tf, regime, bar_ts::date AS cluster_id, counterfactual_pnl_r AS pnl_r
    FROM alpha_frames
    WHERE frame_variant = 'primary'
      AND status != 'open'
      AND bar_ts < $1
      AND counterfactual_pnl_r IS NOT NULL
"""
```
`AlphaScorer` extends this by also selecting `symbol`, `alpha_score` (for `NTILE(10)` decile binning per (symbol, tf, regime) cohort — see RESEARCH.md Assumption A3) and `bar_ts` (no `< oos_start` filter needed if this is scored over the full closed-frame population, but confirm at plan time whether SCORE-01 should itself respect `alpha.validation.oos_start` or run corpus-wide).

**APR read pattern** (`services/_batch_utils.py`, lines 109-144, read in full):
```python
async def load_apr_dict_async(conn: Any, extra_like_patterns: list[str] | None = None) -> Any:
    patterns = ["alpha.%", *(extra_like_patterns or [])]
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        patterns,
    )
    ...

def cfg(cfg_dict: dict[str, Any], key: str, default: Any) -> Any:
    val = cfg_dict.get(key)
    if val is None:
        return default
    if isinstance(default, bool):
        return str(val).strip().lower() == "true"
    return type(default)(val)
```
Use exactly this pair (`load_apr_dict_async` + `cfg`) for `alpha.scoring.min_strategy_n`/`bootstrap_max_n`/`bootstrap_batch`/`bootstrap_random_state` and any newly-seeded `alpha.scoring.min_sharpe`/`max_drawdown_ratio`/`min_ic_alpha_score_corr` keys — same idiom `phase143_1_08_shadow_validation.py`'s `_load_apr` helper (lines 71-84) already uses.

**Error handling / naming conventions:** exception variable is always `error`, never `exc` (see `EnsembleICEngine.execute`, line 918). All timestamps `datetime.now(UTC)`.

**ProcessPoolExecutor note (if SCORE-01 parallelizes per-cohort):** mirror `services/ensemble_ic_engine.py`'s `_run_ensemble_ic_worker` (line 671) / `services/counterfactual_tracker.py`'s `_run_counterfactual_worker` (line 508) pattern — worker opens its own read-only `psycopg2` connection (never asyncpg inside a `ProcessPoolExecutor` worker), returns `list[dict]` rows only, and the single serial async batch INSERT happens in the main process after all workers complete.

---

### `production/migrations/24N_alpha_scoring_gate_tables.sql` (migration, DDL)

**Analog:** `production/migrations/236_alpha_frames_is_shadow.sql` (read in full, 26 lines — simplest DDL-only precedent)

```sql
-- Migration 236 structure (verbatim shape to follow):
BEGIN;

ALTER TABLE alpha_frames ADD COLUMN IF NOT EXISTS is_shadow BOOLEAN NOT NULL DEFAULT TRUE;

COMMIT;
```
For `alpha_strategy_scores`/`gate_evaluations` (new tables, not `ALTER TABLE`), use `CREATE TABLE IF NOT EXISTS` inside the same `BEGIN`/`COMMIT` block. Follow live `alpha_frames` conventions per RESEARCH.md Pitfall 4: `frame_id` is `text`, not `uuid` — new tables' ID columns should match this text-ID convention for consistency, not introduce `uuid`.

**IMPORTANT — migration numbering correction:** RESEARCH.md's suggested filenames (`248_alpha_scoring_gate_tables.sql` / `249_alpha_scoring_apr_keys.sql`) are now stale. Live-verified 2026-07-22: `245_ensemble_1h_eligibility_thresholds.sql` and `246_ensemble_1h_meta_fdr_min_cells.sql` already exist. **Next available migration number is 247**, not 248. Confirm the actual head number again at execution time (`ls production/migrations/ | sort -V | tail -5`) — this project has had concurrent-session migration-number collisions before (`240_counterfactual_tracker_chunk_size.sql` and `240_cross_symbol_corroboration_apr_key.sql` share number 240).

**Second correction (2026-07-22, later same day):** the above is itself now stale — 247 landed
same day as `247_regime_groups_dual_write_symbol_hmm.sql` (an unrelated concurrent
workstream, symbol_hmm restoration). **This phase's migration is 248**, not 247, and it is a
single combined file (`248_alpha_scoring_gate_tables.sql`, DDL + APR-key seed together, not
split 248/249 as this section and RESEARCH.md's structure diagram originally suggested) — see
`148-01-PLAN.md`, the executable artifact, which is correct as written. Phase 162, also
planned this session but scheduled to execute after this phase, has reserved 249-252 for its
own four migrations. Re-check the actual head at execution time regardless
(`ls production/migrations/ | sort -V | tail -5`) — this is the third same-week collision on
this exact mechanism.

---

### `production/migrations/24N_alpha_scoring_apr_keys.sql` (migration, APR seed triple)

**Analog:** `production/migrations/244_regime_gate_min_clusters.sql` (read in full, 54 lines)

```sql
BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.scoring.min_sharpe',
    'float',
    '0.5',
    0.0, 5.0,
    '[conventional] SHADOW-REVIEW.md criterion 3 frozen threshold. PRE-REGISTERED: '
    'not tunable post-hoc.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.scoring.min_sharpe', '0.5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.scoring.min_sharpe', 1, '0.5', 'migration_NNN',
     'Seed SHADOW-REVIEW.md frozen Sharpe gate threshold, never previously migrated')
ON CONFLICT DO NOTHING;

COMMIT;
```
Repeat the `config_schema`/`config_state`/`config_history` triple for each missing key (`alpha.scoring.max_drawdown_ratio=0.25`, `alpha.scoring.min_ic_alpha_score_corr=0.3`, and any `gate_evaluations`-adjacent threshold). Use the exact "PRE-REGISTERED, NOT TUNABLE POST-HOC" provenance language migration 244 established (its header comment block, lines 1-23, is itself a template for the "why this exists, why the value was chosen, why it can't be tuned later" narrative every new gate-threshold migration in this phase should include).

**Live-verified existing `alpha.scoring.*` keys (do NOT re-seed, `ON CONFLICT DO NOTHING` makes this safe regardless):** `min_strategy_n=30`, `bootstrap_max_n=5000`, `bootstrap_batch=1000`, `bootstrap_random_state=42`.

---

### `scripts/ops/corpus/ops_oos_gate1_signal_eval.py` (script, SCORE-02)

**Analog:** `scripts/ops/corpus/ops_oos_holdout_eval.py` (read in full, 431 lines)

**Imports pattern** (lines 25-57):
```python
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import structlog
from scipy.stats import rankdata
from statsmodels.stats.multitest import multipletests

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from src.config.settings import Settings, get_active_contracts
from src.core.service_utils import format_iso_ts, setup_service_logging
from src.intelligence.statistics.ic_math import (
    _fisher_z_ci,
    _nan_to_none,
    _p_values_from_ic,
    _vectorized_ic,
)
```
**SCORE-02 must swap** `services.ic_engine._FEATURE_NAMES` / `services.forward_return_writer.forward_log_return` (feature-vector-specific) for `services.ensemble_ic_engine`'s exact helper set — `compute_walk_forward_stable` — since SCORE-02 scores `ensemble_alpha`/`alpha_score` (one predictor), not per-feature IC. Per RESEARCH.md Pitfall 1, this MUST stay on `_fisher_z_ci` (imported above), never `ic_engine.py`'s newer `circular_block_bootstrap_ic_serial`.

**Fail-loud OOS-boundary read pattern** (lines 114-130 — copy near-verbatim):
```python
async def _read_oos_start(pool: asyncpg.Pool) -> datetime:
    """Read alpha.validation.oos_start from config_state. Raises if unset."""
    row = await pool.fetchrow(
        "SELECT NULLIF(config_value, '') FROM config_state "
        "WHERE config_key = 'alpha.validation.oos_start'"
    )
    if row is None or row[0] is None:
        raise RuntimeError(
            "OOS boundary unset -- nothing to evaluate. "
            "Set alpha.validation.oos_start in config_state before running this harness."
        )
    oos_start = row[0]
    if isinstance(oos_start, str):
        oos_start = datetime.fromisoformat(oos_start)
    if oos_start.tzinfo is None:
        oos_start = oos_start.replace(tzinfo=UTC)
    return oos_start.astimezone(UTC)
```
An equivalent fail-loud form also exists in `services/ensemble_ic_engine.py` lines 952-967 (raises a pre-built `RuntimeError` on `asyncpg.DataError`/`InvalidTextRepresentationError` or `None`) — either shape is acceptable; SCORE-02 should pick whichever matches the rest of its structural template (`ops_oos_holdout_eval.py`'s).

**Query shape to adapt — `ensemble_alpha` join, OOS side** (`services/ensemble_ic_engine.py`, `_WORKER_FETCH_SQL`, lines 516-532 — read in full):
```python
_WORKER_FETCH_SQL = """
    SELECT ea.alpha_score,
           CASE WHEN fr.return_fast_suspect THEN NULL ELSE fr.return_fast END AS return_fast,
           CASE WHEN fr.return_mid_suspect THEN NULL ELSE fr.return_mid END AS return_mid,
           CASE WHEN fr.return_slow_suspect THEN NULL ELSE fr.return_slow END AS return_slow,
           CASE WHEN fr.return_extended_suspect THEN NULL ELSE fr.return_extended END
               AS return_extended,
           mr.regime_label
    FROM ensemble_alpha ea
    JOIN forward_returns fr
      ON fr.symbol = ea.symbol AND fr.tf = ea.tf AND fr.bar_ts = ea.bar_ts
      AND fr.return_type = 'executable_open_to_open'
    JOIN market_regimes mr
      ON mr.regime_group = 'equity' AND mr.tf = ea.tf AND mr.ts = ea.bar_ts
    WHERE ea.symbol = %s AND ea.tf = %s AND ea.weight_version = %s AND ea.bar_ts < %s
    ORDER BY ea.bar_ts
"""
```
**SCORE-02's only required change:** `ea.bar_ts < %s` → `ea.bar_ts >= %s` (OOS side, per D-02/D-03), keeping the exact same table (`ensemble_alpha`, NOT `alpha_events` — RESEARCH.md Pitfall 2), the exact same `fr.return_type = 'executable_open_to_open'` filter (already present — this resolves RESEARCH.md Open Question 1: the filter IS explicit in this query, not enforced only at write time), and the exact same `market_regimes` join shape.

**BH-FDR correction** (lines 242-250):
```python
def _apply_corpus_fdr(results: list[dict[str, Any]], fdr_alpha: float) -> None:
    """Apply ONE BH-FDR correction across all OOS cells (mutates results in place)."""
    if not results:
        return
    p_values = [r["p_value"] for r in results]
    reject, p_corrected, _, _ = multipletests(p_values, alpha=fdr_alpha, method="fdr_bh")
    for i, r in enumerate(results):
        r["bh_adjusted_p"] = float(p_corrected[i])
        r["passes_fdr"] = bool(reject[i])
```

**Look-log pattern (D-04's "run once" auditability)** (lines 323-347 — copy near-verbatim, redirect to a `gate_look_log.jsonl` per RESEARCH.md Pattern 2):
```python
def _append_look_log(
    look_log_path: Path, run_ts: datetime, symbols: list[str], tfs: list[str], report_path: Path,
) -> None:
    report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    entry = {
        "run_ts": format_iso_ts(run_ts),
        "symbols": symbols,
        "tfs": tfs,
        "report_path": str(report_path),
        "report_sha256": report_hash,
    }
    look_log_path.parent.mkdir(parents=True, exist_ok=True)
    with look_log_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")
```

**Argparse entrypoint shape** (lines 355-368):
```python
async def main() -> None:
    parser = argparse.ArgumentParser(description="...")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--tf", nargs="*", default=_DEFAULT_TFS)
    args = parser.parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        ...
    finally:
        await pool.close()
```

**Write target — differs from the analog:** the analog only writes a markdown report (`_write_report`, lines 283-320) and never touches the DB for writes. SCORE-02 additionally needs one `INSERT INTO gate_evaluations (gate_id, result, evidence, ...) VALUES (...)` — no existing analog for that specific write shape exists yet in this codebase (new table); follow the plain `config_history`-style single-row INSERT idiom (see migration triple above) for the actual write statement shape, wrapped in the same `pool`/`conn` already open.

---

### `scripts/analysis/score03_gate2_execution_eval.py` (script, SCORE-03)

**Analog:** `scripts/analysis/phase143_1_08_shadow_validation.py` (read in full, 257 lines)

This is the closest 1:1 analog in the entire codebase — SCORE-03 is explicitly described (D-08, RESEARCH.md) as "this function minus challenger/c6, plus a `gate_evaluations` INSERT."

**Imports + APR-load pattern** (lines 11-30, 71-84 — read in full):
```python
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services._batch_utils import cfg as _cfg
from services.counterfactual_tracker import (
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    evaluate_frame_gate,
    frame_gate_passes,
)
from src.config.settings import Settings

async def _load_apr(conn: asyncpg.Connection) -> tuple[int, int, int, int, int]:
    apr_rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        ["alpha.scoring.%", "alpha.validation.regime_gate_min_clusters"],
    )
    apr_cfg = {row["config_key"]: row["config_value"] for row in apr_rows}
    min_n = _cfg(apr_cfg, "alpha.scoring.min_strategy_n", 30)
    bootstrap_max_n = _cfg(apr_cfg, "alpha.scoring.bootstrap_max_n", 5000)
    bootstrap_batch = _cfg(apr_cfg, "alpha.scoring.bootstrap_batch", 1000)
    bootstrap_random_state = _cfg(
        apr_cfg, "alpha.scoring.bootstrap_random_state", _DEFAULT_BOOTSTRAP_RANDOM_STATE
    )
    regime_gate_min_clusters = _cfg(apr_cfg, "alpha.validation.regime_gate_min_clusters", 20)
    return min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state, regime_gate_min_clusters
```

**OOS query for champion-only data** (lines 32-41):
```python
_OOS_QUERY_SQL = """
    SELECT bar_ts, direction, regime, bar_ts::date AS cluster_id, counterfactual_pnl_r AS pnl_r
    FROM alpha_frames
    WHERE weight_epoch = $1
      AND frame_variant = 'primary'
      AND status != 'open'
      AND bar_ts >= $2
      AND counterfactual_pnl_r IS NOT NULL
    ORDER BY bar_ts ASC
"""
```
SCORE-03 calls this with `weight_epoch = '143.1-08-champion'` only (D-06 — no challenger comparison needed for this gate).

**Pure statistics functions to import/reuse verbatim** (lines 44-68):
```python
def _max_drawdown(pnl_r_ordered: np.ndarray) -> tuple[float | None, bool]:
    """WR-03 frozen edge case: peak <= 0 at max-decline point -> fails outright."""
    cum = np.cumsum(pnl_r_ordered)
    peak = np.maximum.accumulate(cum)
    decline = peak - cum
    trough_idx = int(np.argmax(decline))
    peak_at_trough = float(peak[trough_idx])
    if peak_at_trough <= 0:
        return None, True
    dd = float(decline[trough_idx] / peak_at_trough)
    return dd, dd >= 0.25

def _annualized_sharpe(pnl_r_ordered: list[float], bar_ts_ordered: list[Any]) -> float | None:
    df = pd.DataFrame({"day": pd.to_datetime(bar_ts_ordered).date, "pnl_r": pnl_r_ordered})
    daily = df.groupby("day")["pnl_r"].mean()
    if len(daily) < 2 or daily.std(ddof=1) == 0:
        return None
    return float(daily.mean() / daily.std(ddof=1) * np.sqrt(252))
```
Either import these two functions directly from `phase143_1_08_shadow_validation.py` (if SCORE-03 is meant to literally reuse that module) or copy them verbatim with a citation comment — planner's call, but do NOT rederive.

**Pooled + regime-stratified evaluation, the exact D-07 shape** (lines 87-166 — `evaluate_epoch`, the core function SCORE-03 slims down):
```python
async def evaluate_epoch(conn, weight_epoch, oos_start, min_n, bootstrap_max_n,
                          bootstrap_batch, bootstrap_random_state, regime_gate_min_clusters):
    rows = [dict(r) for r in await conn.fetch(_OOS_QUERY_SQL, weight_epoch, oos_start)]
    n_days = len({r["cluster_id"] for r in rows})
    pnl_r = [r["pnl_r"] for r in rows]
    cluster_ids = [r["cluster_id"] for r in rows]
    bar_ts = [r["bar_ts"] for r in rows]

    c2_passes, ci_lower, ci_upper = frame_gate_passes(
        pnl_r, cluster_ids, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
    )
    sharpe = _annualized_sharpe(pnl_r, bar_ts) if pnl_r else None
    dd, dd_fails = _max_drawdown(np.array(pnl_r)) if pnl_r else (None, True)

    # Regime-stratified companion (D-07) -- exact call shape, never omit this.
    regime_cells = evaluate_frame_gate(
        rows,
        min_n=1,
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
        group_key=lambda row: (row["direction"], row["regime"]),
        min_clusters=regime_gate_min_clusters,
    )
    evaluated_cells = [c for c in regime_cells if c["coverage"] == "evaluated"]
    c2_regime_stratified_passes = (
        all(c["passes"] for c in evaluated_cells) if evaluated_cells else None
    )
    ...
    return {"weight_epoch": weight_epoch, "n_rows": len(rows), "n_days": n_days,
            "c1_min_60_days": n_days >= 60, "c2_ci_lower": ci_lower, "c2_ci_upper": ci_upper,
            "c2_passes": c2_passes, "c3_sharpe": sharpe, "c3_passes": sharpe is not None and sharpe > 0.5,
            "c4_max_dd": dd, "c4_passes": not dd_fails, "regime_cells": regime_cells,
            "c2_regime_stratified_passes": c2_regime_stratified_passes, ...}
```
**SCORE-03's known-going-in numbers to cite verbatim (D-06 — do not recompute)**, extracted from `143.1-08-SHADOW-VALIDATION.md` §6/§7 by this same script's prior run:
- `c2_ci_lower = -0.1214896346368989` (fails `> 0`)
- `c3_sharpe = 0.38512018365944` (fails `> 0.5`)
- `c4_max_dd = 9.598299843093644` (fails `< 0.25` ratio)
- `c1_min_60_days = True` (69 OOS days, passes)
- Regime-stratified: only 2 of 8 champion cells clear `min_clusters=20` coverage (long/mid_bull `ci_lower=-0.077` fails; short/mid_bull `ci_lower=-0.278` fails); the other 6 cells are `coverage="insufficient"`.

**Verdict-assembly + human-readable print pattern** (lines 228-253) — SCORE-03 should keep this reporting shape (print cell-by-cell regime coverage, never print a pooled verdict without the regime table alongside it) but redirect the final verdict into a `gate_evaluations` INSERT instead of (or in addition to) stdout, with `gate_id = 'gate2_execution'` (also serving as `FRAME-04`'s formal re-run per D-08 — do not create a second `FRAME-04` gate_id).

---

## Shared Patterns

### `BaseBatch` lifecycle (SCORE-01 only)
**Source:** `src/core/agent/base_batch.py` (full file, 170 lines)
**Apply to:** `services/alpha_scorer.py`
```python
class AlphaScorer(BaseBatch):
    job_name = "alpha-scorer"
    compute_version = "1.0.0"

    async def execute(self, pool: asyncpg.Pool) -> None:
        ...  # BaseBatch.run() owns pool lifecycle + D-06 job_completed_total emission
```

### APR load + cast (all three: SCORE-01/02/03)
**Source:** `services/_batch_utils.py` lines 109-144
**Apply to:** `services/alpha_scorer.py`, `scripts/ops/corpus/ops_oos_gate1_signal_eval.py`, `scripts/analysis/score03_gate2_execution_eval.py`
```python
apr_cfg = await load_apr_dict_async(conn, extra_like_patterns=["alpha.scoring.%", "alpha.validation.%"])
min_strategy_n = cfg(apr_cfg, "alpha.scoring.min_strategy_n", 30)
```

### Fail-loud OOS boundary read (SCORE-02/03)
**Source:** `services/ensemble_ic_engine.py` lines 952-967 and `scripts/ops/corpus/ops_oos_holdout_eval.py` lines 114-130
**Apply to:** `scripts/ops/corpus/ops_oos_gate1_signal_eval.py`, `scripts/analysis/score03_gate2_execution_eval.py`
Never default to `MAX(bar_ts)` or silently skip if `alpha.validation.oos_start` is unset — raise loud, matching either cited shape.

### Day-clustered bootstrap gate (SCORE-01 aggregation + SCORE-03 pooled/regime verdicts)
**Source:** `services/counterfactual_tracker.py` lines 172-235 (`frame_gate_passes`) and 906-979 (`evaluate_frame_gate`)
**Apply to:** `services/alpha_scorer.py`, `scripts/analysis/score03_gate2_execution_eval.py`
Never hand-roll a new `scipy.stats.bootstrap` call — always route through `evaluate_frame_gate`'s `group_key`/`min_clusters` parameters.

### Exception variable naming + UTC timestamps (all new Python files)
**Source:** CLAUDE.md Key Rules + `services/ensemble_ic_engine.py` line 918
**Apply to:** all new `.py` files this phase
```python
except Exception as error:   # never `exc`
    ...
run_ts = datetime.now(UTC)   # never datetime.now() / datetime.utcnow()
```

### Migration triple (APR keys)
**Source:** `production/migrations/244_regime_gate_min_clusters.sql` (full file, 54 lines)
**Apply to:** the new `alpha.scoring.*` APR-key migration
`config_schema` INSERT (with `[conventional]`/`PRE-REGISTERED, NOT TUNABLE POST-HOC` provenance language) + `config_state` INSERT + `config_history` INSERT, all `ON CONFLICT DO NOTHING`, wrapped in one `BEGIN`/`COMMIT`.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `gate_evaluations` INSERT statement (the actual write, both SCORE-02 and SCORE-03) | — | write | New table, no prior write-path precedent in this codebase; follow the plain single-row `INSERT ... VALUES (...) ON CONFLICT ...` idiom used throughout `config_history`/`llm_calls`-style audit-log tables (loose JSONB evidence column, no enforced sub-schema per RESEARCH.md Open Question 3) rather than copying any specific existing INSERT verbatim |
| `docs/plans/archive/2026-07-22-phase148-promotion-decision.md` structure | doc | — | No prior "two-gate promotion verdict" doc exists in this codebase; `SHADOW-REVIEW.md`/`OOS-EVAL-PROTOCOL.md` are governance-*rule* docs, not *verdict-record* docs — planner has structural discretion per CONTEXT.md's Claude's Discretion section; recommend a simple sections-per-gate + final verdict + citations structure, no template to copy |

## Metadata

**Analog search scope:** `services/`, `scripts/ops/corpus/`, `scripts/analysis/`, `production/migrations/`, `src/core/agent/`, `src/intelligence/statistics/`, `tests/unit/`
**Files scanned (read in full or targeted sections):** `src/core/agent/base_batch.py` (full), `services/ensemble_ic_engine.py` (imports, class, walk-forward, worker-fetch SQL sections), `services/counterfactual_tracker.py` (imports, `frame_gate_passes`, `evaluate_frame_gate` sections), `scripts/ops/corpus/ops_oos_holdout_eval.py` (full), `scripts/analysis/phase143_1_08_shadow_validation.py` (full), `production/migrations/244_regime_gate_min_clusters.sql` (full), `production/migrations/236_alpha_frames_is_shadow.sql` (full), `services/_batch_utils.py` (targeted), `tests/unit/test_ensemble_ic_gate.py` (targeted)
**Pattern extraction date:** 2026-07-22
