# Phase 162: ic_engine Corpus Pipeline Throughput - Pattern Map

**Mapped:** 2026-07-21
**Files analyzed:** 10 (1 heavily modified, 2 lightly modified, 1 new migration, 3 modified tests, 3 new tests)
**Analogs found:** 10 / 10 (every file has a same-file or same-directory precedent — this phase
is explicitly "generalize an existing pattern," per RESEARCH.md's "Don't Hand-Roll" table)

No CONTEXT.md exists for this phase. File list below is extracted from RESEARCH.md's
"Recommended Project Structure" + "Wave 0 Gaps" sections, cross-checked against the phase's
Locked Decisions.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/ic_engine.py` (modify) | service (batch oneshot) | batch / CRUD (read cells, compute, upsert) | itself — `_compute_one_regime_cell` (already-extracted symbol-side sibling) is the analog for the cross-sectional extraction; `_short_lived_conn`/`_checkpoint_content_key`/`existing_keys` are the analogs for the fingerprint work | exact (in-file precedent) |
| `services/_batch_utils.py` (modify: add `short_lived_conn(dsn)`) | utility | connection lifecycle (context manager) | `connect_db_from_url` (same file) + `_short_lived_conn` (`services/ic_engine.py:383-400`, Settings-based sibling) | exact |
| `src/intelligence/statistics/ic_math.py` (modify: add `build_walk_forward_folds`) | utility (pure math) | transform | `apply_bh_fdr` (`ic_math.py:513-532`) — same module, same "extract a duplicated inline block into one pure function" shape (todo 048/069 precedent) | exact |
| `production/migrations/248_ic_cell_fingerprints.sql` (new) | migration | batch (schema + APR seed) | `production/migrations/225_concept_registry_mvp.sql` (table shape + config triple-insert) + `157_alpha_ic_apr_keys.sql` (per-tf flat-key APR pattern) + `156_ic_engine_tables.sql` (non-hypertable plain-table + partial-index precedent) | exact |
| `tests/unit/test_ic_engine_compute_split.py` (extend) | test | unit (source-inspection, no DB) | itself — existing `test_compute_cross_sectional_tf_takes_dsn_not_live_connection` / `test_per_symbol_rankdata_output_is_float32_not_float64` pair is the exact template for a new cross-sectional-extraction-parity case | exact |
| `tests/unit/test_ic_engine_idempotency.py` (extend, do NOT rewrite) | test | unit (module-constant/SQL-string inspection, no DB) | itself — existing `test_pooled_insert_sql_contains_do_nothing` pattern | exact |
| `tests/unit/test_ic_engine_parallelism.py` (extend) | test | unit (signature/inspect, no DB) | itself — existing `test_worker_accepts_single_tuple_arg` (`inspect.signature`) | exact |
| `tests/unit/test_ic_engine_fingerprint.py` (new) | test | unit (new; DELETE-path + fingerprint match/mismatch logic, no DB — mock/pure-function level) | `tests/unit/test_ic_engine_idempotency.py` (SQL-string-assertion style) + `tests/unit/test_ic_engine_compute_split.py` (source-inspection style) | role-match (two existing files combine to cover the needed assertion styles) |
| `tests/unit/test_ic_math_walk_forward_folds.py` (new) | test | unit (pure-function, parametrized against 4 known call sites) | `tests/unit/` sibling for another `ic_math.py` extraction — no direct `test_ic_math_*.py` file exists yet, so nearest analog is `test_ic_engine_compute_split.py`'s inline-formula-vs-extracted-function comparison style | role-match |
| `tests/unit/test_batch_utils_short_lived_conn.py` (new) | test | unit (context-manager exception-safety test) | `tests/unit/test_ic_engine_compute_split.py::test_compute_cross_sectional_tf_closes_connection_before_clustering` (source-inspection for connection-close ordering) — new file additionally needs a live mock-based exception-mid-fetch-still-closes test, which has no existing analog in this test dir (see "No Analog Found") | partial |

## Pattern Assignments

### `services/ic_engine.py` (service, batch/CRUD) — the central file, 5 distinct sub-patterns

This file is not "replaced by an analog" — it extends itself. Four sub-patterns inside it, each
with its own precedent already living in the file:

#### Sub-pattern A: Extracting `_compute_cross_sectional_tf`'s inline block to match `_compute_one_regime_cell`

**Analog:** `_compute_one_regime_cell` (`services/ic_engine.py:779-1107`) — already extracted
from `_compute_symbol_tf` by Task 1 (commits `0e38bf8e`/`2f5334f2`) of the concurrent
symbol_hmm-restoration work on this same worktree. This is the shape 162-01 must replicate for
`_compute_cross_sectional_tf`'s still-fully-inline per-scale block.

**Signature precedent to mirror** (`_compute_cross_sectional_tf`, current, `ic_engine.py:1765-1778`):
```python
def _compute_cross_sectional_tf(
    dsn: str,
    tf: str,
    regime_label: str,
    regime_group: str,
    symbol_list: list[str],
    training_window_end: Any,
    existing_keys: frozenset[tuple],
    config: ICEngineConfig,
    tracer: Any,
    run_ts: datetime,
    rng: np.random.Generator,
    feature_status_map: dict[str, str] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
```

**Still-inline per-scale block to extract** (`ic_engine.py:2054-2179`, the `for scale_idx, scale
in enumerate(_SCALES):` loop) — subsample slice → rankdata (float32 cast) → `_vectorized_ic` →
`_circular_block_bootstrap_ic` → walk-forward fold loop → `_compute_ic_rolling_metrics` →
`sign_hit_rate`/`magnitude_conditional_ic` → per-feature cell_key/existing_keys skip → row dict
build. This is byte-similar (not identical — cross-sectional has an extra e-value-pilot column
and a `max_workers=` bootstrap knob) to `_compute_one_regime_cell`'s equivalent loop
(`ic_engine.py:~900-1049`). Extract into a function with a comparable name/signature
(e.g. `_compute_one_cross_sectional_cell`), not a re-wrap of the whole outer function.

**Idempotency short-circuit precedent to preserve** (`ic_engine.py:1834-1851`, the
whole-cell-level `existing_keys` prefilter — this is exactly the level the NEW fingerprint check
in `main()` must operate at, per Anti-Pattern 3 below):
```python
all_cells_for_regime = frozenset(
    (feat_name, _CROSS_SECTIONAL_SYMBOL, tf, regime_label, lh, True)
    for feat_name in _FEATURE_NAMES
    for lh in lookaheads.values()
)
if all_cells_for_regime.issubset(existing_keys):
    _logger.info(
        "ic_engine.cross_sectional_already_complete",
        tf=tf, regime=regime_label, n_cells=len(all_cells_for_regime),
    )
    return [], {"n_committed": 0, "n_skipped": len(all_cells_for_regime)}
```

#### Sub-pattern B: Feature-axis memory-blocking rewrite (todo 139/140)

**Analog:** `Float32ChunkAccumulator` (`services/_batch_utils.py:147-192`) — row-axis chunked
accumulator; this phase needs the same idiom on the feature axis instead. See Shared Patterns
below (`Float32ChunkAccumulator`) — the new feature-block helper should live as a sibling
function/class near it in `_batch_utils.py` or directly in `ic_engine.py` next to
`_compute_one_regime_cell`, matching whichever extraction boundary 162-01 settles on.

**Root cause to bound** (`ic_engine.py:2085-2094`, verified live, confirms the transient this
rewrite targets):
```python
# float32, not float64 (2026-07-19 OOM fix): rankdata() always
# returns float64 regardless of input dtype, so without this cast
# ranks_X_scale silently defeats X_raw's float32 optimization above and
# becomes the single largest live allocation at the least-subsampled
# ("fast") scale for the biggest cross-sectional cells...
ranks_X_scale = rankdata(X_sub_nd, axis=0).astype(np.float32)[valid_mask]
```
The feature-block rewrite must process this `rankdata(..., axis=0)` call in bounded column
blocks (not the whole `n_sub × n_features` array at once), matching the "preallocate output,
process bounded blocks, discard intermediate" idiom `Float32ChunkAccumulator` already
establishes on the row axis.

#### Sub-pattern C: Fingerprint validity check replacing `existing_keys`'s code-blind skip

**Analog:** the existing `existing_keys` query + `_checkpoint_content_key()`, both in this file.

**`existing_keys` query to replace/extend** (`ic_engine.py:3448-3460`, exact current text):
```python
with conn.cursor() as cur:
    cur.execute(
        """
        SELECT feature_name, symbol, tf, regime, lookahead_bars, is_pooled
        FROM feature_ic_scores
        WHERE training_window_end = %s
        """,
        (training_window_end,),
    )
    existing_keys: set[tuple] = {
        (r[0], r[1], r[2], r[3], r[4], r[5]) for r in cur.fetchall()
    }
_logger.info("ic_engine.existing_keys", count=len(existing_keys))
```
The fingerprint check must run at this exact point in `main()` — before `worker_args` is
constructed (`ic_engine.py:3570`) — replacing this query's role, not living deeper in the
per-cell skip logic (`ic_engine.py:1049`, `:2183`) where `existing_keys` is ALSO checked today.

**Content-key precedent to reuse verbatim** (`ic_engine.py:2360-2401`, `_checkpoint_content_key`)
— this IS the "code content-key" fingerprint component; call it directly rather than
reimplementing:
```python
def _checkpoint_content_key() -> str:
    repo_root = Path(__file__).resolve().parent.parent
    first_party_roots = (repo_root / "src", repo_root / "services")
    hasher = hashlib.sha256()
    paths: set[Path] = set()
    for module in list(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        path = Path(module_file).resolve()
        if any(path.is_relative_to(root) for root in first_party_roots):
            paths.add(path)
    for path in sorted(paths):
        try:
            hasher.update(path.read_bytes())
        except OSError:
            continue
    return hasher.hexdigest()[:12]
```
For the APR-snapshot component, use `BaseBatch.content_key(*parts)` (see Shared Patterns).

#### Sub-pattern D: DELETE-then-insert for fingerprint-invalidated cells (NOT upsert)

**Analog:** the 3 existing INSERT SQL constants + their write functions, unchanged in shape.

**INSERT constants to leave untouched** (`ic_engine.py:311-331`):
```python
_POOLED_INSERT_SQL = (
    _INSERT_BODY
    + "    ON CONFLICT (feature_name, symbol, tf, lookahead_bars, training_window_end)\n"
    + "        WHERE is_pooled = true AND symbol <> 'POOLED'\n"
    + "    DO NOTHING\n"
)
_REGIME_INSERT_SQL = (
    _INSERT_BODY
    + "    ON CONFLICT (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)\n"
    + "        WHERE is_pooled = false AND regime IS NOT NULL\n"
    + "    DO NOTHING\n"
)
_CROSS_SECTIONAL_INSERT_SQL = (
    _INSERT_BODY
    + "    ON CONFLICT (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)\n"
    + "        WHERE is_pooled = true AND symbol = 'POOLED'\n"
    + "    DO NOTHING\n"
)
```
**Write functions these feed** (`ic_engine.py:2332-2357` `_write_ic_results`,
`:2502-2515` `_write_cross_sectional_results`) — both run `psycopg2.extras.execute_batch(cur,
<INSERT_SQL>, rows)` then `conn.commit()`. The new DELETE step is a separate statement executed
in `main()` BEFORE a fingerprint-invalidated cell is added to `worker_args`, scoped to the exact
cell key columns (`feature_name`, `symbol`, `tf`, `regime`|`is_pooled`, `lookahead_bars`,
`training_window_end`) — same place and same granularity as the `existing_keys` query above, not
a blanket `DELETE ... WHERE training_window_end = %s`.

#### Sub-pattern E: `cross_sectional_bootstrap_threads` per-tf dict (todo 133)

**Analog:** `config.bootstrap_block_size[tf]`, already a per-tf dict read at the exact call site
this phase's new knob feeds (`ic_engine.py:2107-2114`):
```python
ci_lower_nd, ci_upper_nd = _circular_block_bootstrap_ic(
    X_raw_scale,
    Y_scale,
    config.bootstrap_block_size[tf],
    config.bootstrap_resamples,
    rng,
    max_workers=config.cross_sectional_bootstrap_threads,
)
```
`cross_sectional_bootstrap_threads` is currently a scalar; convert it to a per-tf dict assembled
in `ICEngineConfig.from_apr()` from 4 flat APR keys, exactly mirroring how `bootstrap_block_size`
itself is assembled (see migration precedent in the migration section below), then index it
`config.cross_sectional_bootstrap_threads[tf]` at this call site, matching `bootstrap_block_size[tf]`'s
existing subscript pattern one line above it.

---

### `services/_batch_utils.py` (utility, connection lifecycle)

**Analog:** `connect_db_from_url` (same file, `_batch_utils.py:27-36`) is the function the new
helper wraps; `_short_lived_conn` (`services/ic_engine.py:383-400`) is the Settings-based sibling
this dsn-based helper must NOT be confused with.

**Imports pattern** (`_batch_utils.py:1-16`, module already has everything needed — `contextmanager`
is the only new import required):
```python
"""Shared utilities for batch oneshot services (psycopg2-based, plus a small asyncpg
APR-loading helper for the async batch services)."""

from __future__ import annotations

import csv
import io
from typing import Any

import numpy as np
import psycopg2
import structlog

from src.config.config_service import ConfigService

_logger = structlog.get_logger()
```

**Function to wrap** (`_batch_utils.py:27-36`):
```python
def connect_db_from_url(db_url: str) -> Any:
    """Open a psycopg2 connection from a raw DB URL, autocommit off.

    Shared by ic_engine.py and ensemble_ic_engine.py's ProcessPoolExecutor workers
    (each opens its own read-only connection per dispatch) and by ic_engine's
    higher-level _connect_db(settings) wrapper (todo 047 follow-up, 2026-07-02).
    """
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    return conn
```

**Core pattern — the Settings-based sibling to mirror, dsn-based** (`services/ic_engine.py:383-400`,
existing, verified live):
```python
@contextmanager
def _short_lived_conn(settings: Settings):
    """Open a connection scoped to one unit of work, guaranteeing it closes.
    ...
    Worker-side connections (`connect_db_from_url(dsn)` in
    `_compute_symbol_tf`/`_compute_cross_sectional_tf`) are a separate pattern --
    they cross a ProcessPoolExecutor boundary and take a `dsn: str`, not a
    `Settings`, so they don't fit this helper (todo 129).
    """
    conn = _connect_db(settings)
    try:
        yield conn
    finally:
        conn.close()
```

**New function to add, place immediately after `connect_db_from_url`:**
```python
@contextmanager
def short_lived_conn(dsn: str):
    """Worker-side sibling of ic_engine.py's Settings-based _short_lived_conn (todo 129).
    Takes a dsn string (picklable, crosses ProcessPoolExecutor boundary) instead of a
    Settings object. Guarantees conn.close() even on exception mid-fetch -- the 3
    hand-rolled call sites this replaces (_compute_symbol_tf x2, _compute_cross_sectional_tf
    x1) have no try/finally today and leak a connection on any exception between open and
    the nearest explicit conn.close() call.
    """
    conn = connect_db_from_url(dsn)
    try:
        yield conn
    finally:
        conn.close()
```
Requires `from contextlib import contextmanager` added to the import block. The 3 dsn-based call
sites to migrate onto this helper (per RESEARCH.md's Architectural Responsibility Map, narrow
scope — do NOT widen to `regime_writer.py`/`equity_regime_model.py`/`backfill_feature_factory.py`/
`cross_sectional_regime_model.py`, explicitly deferred): `_compute_symbol_tf` (×2 call sites) and
`_compute_cross_sectional_tf` (×1 call site) in `services/ic_engine.py`.

---

### `src/intelligence/statistics/ic_math.py` (utility, pure math)

**Analog:** `apply_bh_fdr` (`ic_math.py:513-532`) — same module, same extraction shape (todo
048/069's "3+ near-identical inline copies → one pure function here" pattern).

**Module docstring / contract to honor** (`ic_math.py:1-18`):
```python
"""Shared IC (Information Coefficient) math ...
Extracted from services/ic_engine.py (todo 048, 2026-07-02): services/ensemble_ic_engine.py
and scripts/ops/corpus/ops_oos_holdout_eval.py were each importing these same
underscore-prefixed "private" functions directly from ic_engine.py -- three Ring 2
consumers reaching into one module's internals instead of a shared public API. Moving the
math here (Ring 1, no domain-vocab restriction like Ring 0) gives all three a stable import
target; a change to ic_engine.py's internals can no longer silently break its siblings.

Pure functions only -- no DB, no config loading, no module-global mutable state (besides
the _Z95 constant). config.sharpe_window_size / config.sharpe_min_windows are accessed via
the SharpeWindowConfig protocol rather than importing ICEngineConfig or EnsembleICConfig,
so this module has no dependency back on either concrete config dataclass.
"""
```

**Analog function to place `build_walk_forward_folds` next to** (`ic_math.py:508-532`):
```python
# ---------------------------------------------------------------------------
# Shared BH-FDR correction (todo 069)
# ---------------------------------------------------------------------------


def apply_bh_fdr(p_values: list[float], alpha: float) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg FDR correction over one family of p-values.

    Thin, deliberately minimal wrapper around statsmodels' multipletests: this
    "collect p-values -> one multipletests call -> scatter reject/corrected-p back by
    index" shape was independently hand-rolled at three call sites ...
    Only the multipletests call itself is shared here, not the scatter-back-into-a-container
    step -- each caller's result container shape differs...

    Returns (reject, p_corrected) as parallel arrays in the same order as p_values.
    Returns two empty arrays for an empty input (no family to correct).
    """
    if not p_values:
        return np.array([], dtype=bool), np.array([], dtype=float)
    reject, p_corrected, _, _ = multipletests(p_values, alpha=alpha, method="fdr_bh")
    return reject, p_corrected
```

**Protocol pattern for config access** (`ic_math.py:100-116`, `SharpeWindowConfig`) — if
`build_walk_forward_folds` needs any config field beyond its own plain int args (it shouldn't per
its recommended signature — pure boundary math only), follow this Protocol shape rather than
importing `ICEngineConfig`:
```python
class SharpeWindowConfig(Protocol):
    """Duck-typed shape _compute_ic_rolling_metrics needs from a frozen IC config
    dataclass. Both ICEngineConfig and EnsembleICConfig satisfy this structurally.
    ...
    """
    sharpe_window_size_subsampled: int
    sharpe_min_windows: int
    hac_max_lag: int
```

**New function to add** (signature already refined in RESEARCH.md against all 4 real call
sites — `services/ic_engine.py:978,1533,2123`, `services/ensemble_ic_engine.py:818`):
```python
def build_walk_forward_folds(
    n_valid: int, n_folds: int, embargo_bars: int, min_reliable_n: int
) -> list[tuple[int, int]]:
    """Yield (test_start, test_end) pairs for a fixed-origin expanding-window walk-forward
    split with embargo. Pure boundary math -- no ranking, no IC computation. All 4 existing
    call sites (services/ic_engine.py:978,1533,2123; services/ensemble_ic_engine.py:818)
    compute this identical formula inline today.
    """
    folds = []
    for k in range(n_folds):
        train_end = int(n_valid * (k + 1) / (n_folds + 1))
        test_start = train_end + embargo_bars
        test_end = int(n_valid * (k + 2) / (n_folds + 1))
        if test_start >= test_end or (test_end - test_start) < min_reliable_n:
            continue
        folds.append((test_start, test_end))
    return folds
```
Note: line 1533's call site (daily context-features scalar loop) has its own additional
`n_valid >= folds*2+embargo` guard the other 3 lack — leave that guard at the call site, do not
fold it into the shared function (it's a caller-specific precondition, not shared boundary math).

---

### `production/migrations/248_ic_cell_fingerprints.sql` (migration, new table + APR seed)

**Analog 1 — plain (non-hypertable) table + partial-index convention:**
`production/migrations/156_ic_engine_tables.sql:31-51` (`forward_returns`, and its sibling
`feature_ic_scores` table further down the same file — not itself a hypertable; only
`forward_returns` and `concept_transition_log` use `create_hypertable()` in this codebase):
```sql
CREATE TABLE IF NOT EXISTS forward_returns (
    symbol                  text             NOT NULL,
    tf                      text             NOT NULL,
    bar_ts                  timestamptz      NOT NULL,
    pipeline_version        text             NOT NULL,
    ...
    computed_at             timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tf, bar_ts)
);
```
`ic_cell_fingerprints` should follow this same plain-table + composite-PK shape (its row count is
bounded the same way `feature_ic_scores` itself is: O(symbols × tfs × pass_types × windows), not
O(bars)) — do NOT call `create_hypertable()` on it.

**Analog 2 — table creation + config triple-insert (schema+state+history), idempotent guards:**
`production/migrations/225_concept_registry_mvp.sql`. Table declaration style
(`225_concept_registry_mvp.sql:48-72`, abbreviated):
```sql
CREATE TABLE IF NOT EXISTS concept_registry (
    ...
);
```
Config triple-insert pattern (`225_concept_registry_mvp.sql:210-231`, exact — the
`config_history` guard is the load-bearing part, since `config_history`'s PK is
`(timestamp, config_key, version)` and `NOW()` never repeats, so a plain `ON CONFLICT` can't
make this insert idempotent — must use `WHERE NOT EXISTS` instead):
```sql
INSERT INTO config_state (config_key, config_value, version)
VALUES
('alpha.concept_registry.ensemble_strategy_min_promotion_consecutive', '2', 1),
...
ON CONFLICT (config_key) DO NOTHING;

-- M-3: config_history's PK is (timestamp, config_key, version); the insert below uses NOW(),
-- so ON CONFLICT can never fire on re-run. Guard each insert with WHERE NOT EXISTS on
-- (config_key, version) so re-applying this migration inserts zero new config_history rows.

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.concept_registry.ensemble_strategy_min_promotion_consecutive', 1, '2',
       'migration_233', 'Concept Registry MVP gate seed (todo 058) [initial_estimate]'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history
    WHERE config_key = 'alpha.concept_registry.ensemble_strategy_min_promotion_consecutive'
      AND version = 1
);
```
This exact `config_schema` → `config_state ON CONFLICT DO NOTHING` → `config_history WHERE NOT
EXISTS` triple is mandatory for the new `alpha.ic.feature_block_columns`, `alpha.ic.max_cell_rows`
APR keys this phase's memory-bound work introduces (per CLAUDE.md's APR mandate).

**Analog 3 — per-tf flat-key APR pattern (for `cross_sectional_bootstrap_threads.{5m,15m,1h,1d}`,
todo 133):** `production/migrations/157_alpha_ic_apr_keys.sql:44-71`, the existing
`bootstrap_block_size.*` seed (exact text, this IS the template — 4 separate flat keys, not a
JSON blob):
```sql
(
    'alpha.ic.bootstrap_block_size.5m',
    'int',
    '78',
    5, 500,
    '[initial_estimate] Circular block bootstrap block size for 5m bars. ~78 bars per trading day captures one day of autocorrelation structure per Hall & Horowitz 1996 O(N^(1/3)) guideline. APR-backed so empirical optimal block length can be updated without code change. Not an ML learning target.'
),
(
    'alpha.ic.bootstrap_block_size.15m',
    'int',
    '26',
    5, 200,
    '[initial_estimate] Circular block bootstrap block size for 15m bars. ~26 bars per trading day. See alpha.ic.bootstrap_block_size.5m for methodology. Not an ML learning target.'
),
(
    'alpha.ic.bootstrap_block_size.1h',
    'int',
    '10',
    3, 100,
    '[conventional] Circular block bootstrap block size for 1h bars. Conventional lower bound of 10; fewer than 10 bars per day at this timeframe. See alpha.ic.bootstrap_block_size.5m for methodology. Not an ML learning target.'
),
(
    'alpha.ic.bootstrap_block_size.1d',
    'int',
    '10',
    3, 100,
    '[conventional] Circular block bootstrap block size for 1d bars. Conventional lower bound of 10 for daily frequency. See alpha.ic.bootstrap_block_size.5m for methodology. Not an ML learning target.'
),
```
Then seeded into `config_state` as 4 parallel rows (`157_alpha_ic_apr_keys.sql:151-154`):
```sql
('alpha.ic.bootstrap_block_size.5m',     '78',     1),
('alpha.ic.bootstrap_block_size.15m',    '26',     1),
('alpha.ic.bootstrap_block_size.1h',     '10',     1),
('alpha.ic.bootstrap_block_size.1d',     '10',     1),
```
`cross_sectional_bootstrap_threads.{5m,15m,1h,1d}` should be seeded identically, then assembled
into a dict by `ICEngineConfig.from_apr()`, mirroring however `bootstrap_block_size` is currently
assembled from its own 4 keys in that same method.

**Draft CREATE TABLE** (RESEARCH.md's own synthesis, confidence MEDIUM per that doc — treat as
strong starting point, not gospel; verify `pass_type` CHECK values against
`_resolve_regime_scope`, `ic_engine.py:210-239`, before finalizing):
```sql
CREATE TABLE IF NOT EXISTS ic_cell_fingerprints (
    symbol               TEXT        NOT NULL,  -- or 'POOLED' for cross-sectional cells
    tf                   TEXT        NOT NULL,
    pass_type            TEXT        NOT NULL
        CHECK (pass_type IN ('pooled', 'symbol_hmm', 'cross_sectional')),
    training_window_end  TIMESTAMPTZ NOT NULL,
    code_content_key     TEXT        NOT NULL,   -- _checkpoint_content_key() output (12 hex)
    apr_snapshot_key     TEXT        NOT NULL,   -- BaseBatch.content_key() over the
                                                  -- computation-affecting ICEngineConfig
                                                  -- field tuple
    upstream_watermark   JSONB       NOT NULL,
    computed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, tf, pass_type, training_window_end)
);
```

**Verified next-free migration number:** `ls production/migrations/ | sort -t_ -k1 -n | tail`
shows the highest landed migration on this worktree is `246_ensemble_1h_meta_fdr_min_cells.sql`;
`247_regime_groups_dual_write_symbol_hmm.sql` is reserved (not yet landed) by the concurrent
symbol_hmm-restoration workstream on this same worktree — **use 248**, and re-check
`ls production/migrations/ | sort -t_ -k1 -n | tail -3` immediately before writing the file
during execution, per Pitfall 4.

---

### `tests/unit/test_ic_engine_compute_split.py` (test, extend)

**Analog:** itself — the existing `test_compute_cross_sectional_tf_takes_dsn_not_live_connection`
/ `test_per_symbol_rankdata_output_is_float32_not_float64` pair is the exact style for the new
"extraction parity" case 162-01 needs.

**Imports pattern** (`test_ic_engine_compute_split.py:13-23`):
```python
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import (
    ...
)
```

**Source-inspection assertion style to extend** (`test_ic_engine_compute_split.py:145-167`,
exact — connection-close-before-CPU-work ordering check; the same idiom applies to asserting the
new cross-sectional extraction has the same shape as `_compute_one_regime_cell`):
```python
def test_compute_cross_sectional_tf_closes_connection_before_clustering():
    """The connection opened inside _compute_cross_sectional_tf must be closed
    before the CPU-only clustering/bootstrap phase begins -- not held open across
    it (todo 125, same pattern as _compute_symbol_tf's todo 102 fix).
    ...
    """
    source = inspect.getsource(_compute_cross_sectional_tf)
    assert "conn.close()" in source, (...)
    close_idx = source.index("conn.close()")
    cluster_idx = source.index("_cluster_features(")
    assert close_idx < cluster_idx, (...)
```

**Extraction-parity pattern to mirror for the new cross-sectional helper** (`:181-193`, exact —
this is the template for asserting "the extracted function preserves guard X"):
```python
def test_per_symbol_rankdata_output_is_float32_not_float64():
    """Same fix, sibling function: _compute_symbol_tf's ranks_X_scale must cast
    to float32 too.

    This per-cell logic now lives in _compute_one_regime_cell (extracted from
    _compute_symbol_tf, restore-symbol-hmm-ic-measurement Task 1) -- the guard
    moved with it, unchanged.
    """
    source = inspect.getsource(_compute_one_regime_cell)
    rankdata_idx = source.index("ranks_X_scale = rankdata(X_sub_nd, axis=0)")
    line_end = source.index("\n", rankdata_idx)
    assert "astype(np.float32)" in source[rankdata_idx:line_end]
```
New tests should add the equivalent `test_cross_sectional_..._matches_extracted_helper`-style
case once the new cross-sectional helper function exists, following this exact
`inspect.getsource` + `source.index(...)` idiom — no DB, no fixtures, no mocking.

---

### `tests/unit/test_ic_engine_idempotency.py` (test, extend — do NOT rewrite)

**Analog:** itself.

**Full existing style** (`test_ic_engine_idempotency.py:1-27`, imports + module purpose):
```python
"""Unit test: IC engine idempotency and ON CONFLICT DO NOTHING SQL assertions.

Verifies:
  1. The skip-set dedup logic: cells already in existing_keys are skipped.
  2. Both INSERT SQL constants (_POOLED_INSERT_SQL, _REGIME_INSERT_SQL) contain
     ON CONFLICT ... DO NOTHING (idempotent upsert).
  3. is_pooled handling: pooled and regime rows use separate SQL with separate
     ON CONFLICT column lists.

No DB, no Kafka. Pure Python inspection of module constants and logic.
"""
from __future__ import annotations
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import (
    _POOLED_INSERT_SQL,
    _POOLED_REGIME_SENTINEL,
    _REGIME_INSERT_SQL,
)
```

**SQL-string-assertion pattern to add a DELETE-path sibling for** (`:107-113`, exact):
```python
def test_pooled_insert_sql_contains_do_nothing():
    """_POOLED_INSERT_SQL must contain ON CONFLICT ... DO NOTHING (idempotent)."""
    assert "DO NOTHING" in _POOLED_INSERT_SQL, (
        "_POOLED_INSERT_SQL does not contain 'DO NOTHING'. "
        "This means re-runs will raise duplicate key violations instead of "
        "being idempotent. Check the ON CONFLICT clause in services/ic_engine.py."
    )
```
Add new cases asserting: (a) these 3 constants remain byte-unchanged (still `DO NOTHING`, not
converted to `DO UPDATE`) after 162-03 lands; (b) the new DELETE statement's SQL string is scoped
to the full cell-key column set (not a blanket `training_window_end` filter) — same
string-assertion idiom, new constant name (e.g. `_FINGERPRINT_INVALIDATE_DELETE_SQL`).

---

### `tests/unit/test_ic_engine_parallelism.py` (test, extend)

**Analog:** itself — currently a 25-line file testing only `_run_ic_worker`'s signature via
`inspect.signature`.

**Full existing content** (`test_ic_engine_parallelism.py:1-26`):
```python
"""Unit tests for ic_engine ProcessPoolExecutor worker contract.

Tests validate the worker function signature without a live DB connection.
_derive_worker_rng_seed was removed when the circular block bootstrap was
replaced by Fisher z-transform CI (no RNG needed).
"""
from __future__ import annotations
import inspect
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _run_ic_worker


def test_worker_accepts_single_tuple_arg():
    """_run_ic_worker must accept a single 'args' tuple parameter."""
    sig = inspect.signature(_run_ic_worker)
    params = list(sig.parameters.keys())
    assert params == ["args"], f"Expected single 'args' param, got {params}"
```
Note: this file's own docstring is stale (says "replaced by Fisher z-transform CI" — the file's
module docstring, lines 9-21, confirms the circular block bootstrap is what's actually live
today; correct this stale comment while extending the file for todo 133's per-tf dict test,
since a doc/comment correction in a file you're already editing is in-scope). Add a
`test_icengineconfig_assembles_per_tf_bootstrap_threads_dict`-style case following the same
`inspect.signature`-or-direct-attribute-access idiom, asserting `ICEngineConfig.from_apr()`
produces a `{5m:.., 15m:.., 1h:.., 1d:..}` dict, not a scalar.

---

### `tests/unit/test_ic_engine_fingerprint.py` (test, NEW)

**Analog (style, combined from 2 existing files):**
`tests/unit/test_ic_engine_idempotency.py` (SQL-string / module-constant assertions, no DB) +
`tests/unit/test_ic_engine_compute_split.py` (`inspect.getsource`/`inspect.signature`
source-level assertions, no DB). No live-DB fixture pattern exists in this test directory for
`ic_engine.py` — all 3 existing `test_ic_engine_*.py` files are DB-free, pure-Python/source
inspection. The new file should follow the same DB-free convention: test the fingerprint
match/mismatch/DELETE-trigger *logic* as a pure function (e.g. `_fingerprint_is_valid(stored,
current) -> bool`) rather than exercising it against a live `ic_cell_fingerprints` table —
matches this project's existing pattern of keeping `tests/unit/` DB-free and reserving DB-backed
checks for the `162-04` equivalence harness (an ops script per RESEARCH.md's Validation
Architecture section, explicitly NOT a `tests/unit/` case).

**Required coverage per RESEARCH.md's Phase Requirements → Test Map:** fingerprint
match → skip; fingerprint mismatch → DELETE + recompute; an unclassified APR field → crash loud
(not silently partial-stale) — mirrors CLAUDE.md's "Silent wrong answers are worse than loud
crashes" north star and RESEARCH.md's own stated invariant in the migration's `COMMENT ON TABLE`.

---

### `tests/unit/test_ic_math_walk_forward_folds.py` (test, NEW)

**Analog:** no direct `test_ic_math_*.py` file exists yet in this test directory (confirmed —
`ic_math.py`'s functions are currently tested indirectly through `test_ic_engine_compute_split.py`
and similar, not directly). Nearest structural analog is `test_ic_engine_compute_split.py`'s
approach of asserting extracted-function output against the pre-extraction inline formula.
Required coverage: parametrize `build_walk_forward_folds` against the boundary values all 4
existing inline call sites (`services/ic_engine.py:978,1533,2123`;
`services/ensemble_ic_engine.py:818`) would independently compute, confirming bit-identical
`(test_start, test_end)` pairs, including the line-1533 caller's extra
`n_valid >= folds*2+embargo` guard staying local to that call site (not absorbed into the shared
function).

---

### `tests/unit/test_batch_utils_short_lived_conn.py` (test, NEW)

**Analog (partial):** `test_ic_engine_compute_split.py::test_compute_cross_sectional_tf_closes_connection_before_clustering`
covers the "closes before X" ordering assertion style via source inspection, but this new test
also needs a genuinely new case with no existing analog in this test dir: exception-mid-fetch
still closes the connection. Use a mock/fake `connect_db_from_url` (monkeypatch
`services._batch_utils.connect_db_from_url`) that returns a `Mock()` connection, raise inside the
`with short_lived_conn(dsn):` block, and assert `conn.close()` was still called — a
`pytest.raises` + `mock_conn.close.assert_called_once()` pair. No existing test in this codebase
does exactly this for a context manager; this is new test-authoring, not a copy, but should keep
the DB-free / no-fixture style consistent with its 3 siblings above.

## Shared Patterns

### Content-addressed hashing (fingerprint identity)
**Source:** `_checkpoint_content_key()` (`services/ic_engine.py:2360-2401`, code component) +
`BaseBatch.content_key(*parts)` (`src/core/agent/base_batch.py:103-117`, APR-snapshot component)
**Apply to:** the new fingerprint validity check in `main()`, `services/ic_engine.py`
```python
# src/core/agent/base_batch.py:103-117
@staticmethod
def content_key(*parts: str) -> str:
    """SHA-256 content key from arbitrary string parts.

    Returns the first 32 hex characters of SHA-256(parts joined with '|').
    Deterministic: same parts always produce the same key. Used for
    app-layer uniqueness in tables where TimescaleDB hypertable constraints
    prevent standard unique indexes.

    Example:
        BaseBatch.content_key("SPY", "5m", "1719014400000000000")
        # -> 32-character hex string, e.g. "a3f4b2c1d0e5f6a7b8c9d0e1f2a3b4c5"
    """
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
```
Use `_checkpoint_content_key()` unmodified for `code_content_key`; use `BaseBatch.content_key()`
over a stringified tuple of `(key, value)` pairs for the computation-affecting `ICEngineConfig`
fields for `apr_snapshot_key`.

### Feature-axis chunked accumulation (memory bound, todo 139/140)
**Source:** `Float32ChunkAccumulator` (`services/_batch_utils.py:147-192`)
**Apply to:** the feature-blocked rank/CI/fold compute inside `_compute_one_regime_cell` and its
new cross-sectional sibling
```python
class Float32ChunkAccumulator:
    """Buffers rows into vstack-ready float32 chunks, freeing each chunk's Python-list
    intermediate as soon as it's converted (todo 087).
    ...
    """
    def __init__(self, flush_at: int | None = None) -> None:
        self._flush_at = flush_at
        self._chunks: list[np.ndarray] = []
        self._buf: list = []
    # append_row (streaming) / append_chunk (pre-fetched batch) / finalize (vstack once)
```
This is the row-axis precedent; the new feature-axis helper needs the identical
"preallocate, bound each block's size, discard intermediates" idea, applied to columns of the
already-in-memory per-scale array instead of streamed DB rows.

### Per-tf APR key assembly (todo 133)
**Source:** `production/migrations/157_alpha_ic_apr_keys.sql:44-71` (4 flat keys) +
`config.bootstrap_block_size[tf]` subscript usage at `services/ic_engine.py:2110`
**Apply to:** `cross_sectional_bootstrap_threads` — seed 4 flat keys
(`alpha.ic.cross_sectional_bootstrap_threads.5m` / `.15m` / `.1h` / `.1d`), assemble into a dict
in `ICEngineConfig.from_apr()` the same way `bootstrap_block_size` is assembled there today, and
subscript by `tf` at the `_circular_block_bootstrap_ic(...)` call site
(`services/ic_engine.py:2107-2114`), matching `config.bootstrap_block_size[tf]` one argument over.

### Exception handling / `error` naming
**Source:** `_load_checkpoint` (`services/ic_engine.py:2409-2419`)
**Apply to:** any new `try/except` in `short_lived_conn`, the fingerprint check, or new tests
```python
try:
    with path.open("rb") as f:
        return pickle.load(f)
except Exception as error:
    _logger.warning("ic_engine.checkpoint_load_failed", symbol=symbol, error=str(error))
    return None
```
CLAUDE.md mandates the exception variable name be `error`, never `exc` — confirmed as the live
local idiom at this exact site.

## No Analog Found

None. Every file in this phase's scope has at least a partial-match analog in the same file, same
module, or same test directory — this phase is explicitly scoped as "generalize a pattern that
already exists locally," per RESEARCH.md's "Don't Hand-Roll" table and "State of the Art" section
("every mechanism this phase needs ... already has a load-bearing precedent inside this exact
file or its immediate siblings"). The one file needing genuinely new test-authoring beyond
adapting an existing style is `tests/unit/test_batch_utils_short_lived_conn.py`'s
exception-mid-fetch-still-closes case (noted above under that file's Pattern Assignment, not
listed separately here since a partial analog does exist).

## Metadata

**Analog search scope:** `services/ic_engine.py` (full file, targeted non-overlapping reads:
imports 1-105, INSERT SQL 300-340, `_compute_cross_sectional_tf` 1765-1855 + 2054-2200,
`_write_ic_results`/checkpoint/`_write_symbol_results`/`_write_cross_sectional_results`/
`_backfill_bh_fdr` 2332-2530, `existing_keys`/`worker_args` construction 3440-3520),
`services/_batch_utils.py` (full, 192 lines), `src/intelligence/statistics/ic_math.py`
(docstring + `SharpeWindowConfig` + `apply_bh_fdr`, lines 1-30, 95-125, 505-555),
`src/core/agent/base_batch.py` (docstring + `content_key`, lines 1-60), `production/migrations/`
(156, 157, 173, 225 read/grepped; directory listing confirmed 246 is highest landed, 247
reserved-not-landed), `tests/unit/test_ic_engine_idempotency.py` (full, 156 lines),
`tests/unit/test_ic_engine_parallelism.py` (full, 25 lines),
`tests/unit/test_ic_engine_compute_split.py` (def-name grep + targeted read, lines 120-200).
**Files scanned:** 12 (5 read in full, 7 targeted-range reads)
**Pattern extraction date:** 2026-07-21
