# Phase 171: HMM Walk-Forward Regime Labeling (Parameter-Lookahead Fix) - Pattern Map

**Mapped:** 2026-08-07
**Files analyzed:** 6 (1 modify, 3-4 new scripts, 1 test file modify; no new migration)
**Analogs found:** 6 / 6

This phase does almost no new-mechanism engineering — `_walk_forward_hmm_labels`,
`_walk_forward_hmm_full`, `_compute_symbol_tf_walk_forward`, `_hmm_seed_stability_check`,
`_seed_prior_from_label` already exist and are tested (`services/regime_writer.py`). Every
pattern below is "extend/wire an existing sibling function the same way its neighbor already
does it" — the single-fit path (`_compute_symbol_tf`) is the canonical analog for almost
everything the walk-forward path (`_walk_forward_hmm_full`/`_compute_symbol_tf_walk_forward`)
still needs.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/regime_writer.py` (modify: iters_used logging in `_walk_forward_hmm_full`) | compute (batch, in-process) | batch/transform | `_compute_symbol_tf`'s existing `regime_writer.hmm_convergence_iters` log line (same file, lines 1259-1269) | exact — same file, same log event shape, different call site |
| `services/regime_writer.py` (modify: `n_restarts` threading through `_walk_forward_hmm_full`/`_compute_symbol_tf_walk_forward`, only if D-03's pilot verdict warrants it) | compute (batch, in-process) | batch/transform | `_compute_symbol_tf`'s existing `n_restarts` loop (same file, lines 1181-1257) | exact — same file, same selection logic, per-segment instead of per-cell |
| `services/regime_writer.py` (modify: NULL-out pre-step, main-process-only, single serial write connection) | persistence (batch UPDATE, main process) | CRUD (targeted UPDATE) | `_write_regime_results`/`bulk_update_by_key` (`services/regime_writer.py:1358-1440`, `services/_batch_utils.py:78-119`) | role-match — same table, same column ownership list, opposite direction (NULL instead of populate) |
| `scripts/analysis/hmm_walk_forward_seed_stability_pilot.py` (new) | analysis script (diagnostic, ad hoc) | batch/read-only | `scripts/analysis/hmm_walk_forward_gate4_ic_pilot_spy_1h.py` | exact — same shape: fetch real OHLCV, call a `regime_writer.py` primitive directly (bypassing CLI/DB-write), print a verdict |
| `scripts/analysis/hmm_n_restarts_walk_forward_comparison_pilot.py` (new, D-03's parallel-arm comparison — only if the pilot requires it in-band, see below) | analysis script (diagnostic, ad hoc) | batch/read-only | Same gate4 pilot script pattern + Phase 168 D-02's parallel-construction-never-mutate-baseline principle (conceptual, not code — see Shared Patterns) | role-match — script structure from gate4 pilot, comparison discipline from Phase 168 |
| `scripts/analysis/regime_walk_forward_null_out_and_verify.py` (new, chunked NULL-out + REQ-3 provenance verification, checked-in not ad hoc) | ops/migration script (data-integrity mutation + verification) | CRUD (targeted, chunked UPDATE) + verification query | `bulk_update_by_key` write discipline + Phase 151-07 Task 1's manifest-driven per-partition `--recompute` chunking discipline (`.planning/phases/151-.../151-07-PLAN.md`) | role-match — same "never one corpus-wide statement" discipline, different table/direction |
| `tests/unit/services/test_regime_writer.py` (modify: add tests for the above) | test | unit (synthetic fixtures, no DB) | `test_compute_symbol_tf_logs_convergence_iterations` (lines 513-556), `test_compute_symbol_tf_n_restarts_selects_highest_log_likelihood` (lines 794-870), `test_compute_symbol_tf_walk_forward_returns_tuple_structure` (lines 1201-1241) | exact — same file, same fixture helpers, same `_make_mock_conn`/`capture_logs` idioms |

**No new migration file.** Both APR keys this phase needs already exist and are seeded:
`alpha.hmm.walk_forward.enabled` + the 8 tf-calibrated `refit_every_bars`/`initial_warmup_bars`
keys (migration `292_hmm_walk_forward_apr.sql`, confirmed shipped), and `alpha.hmm.n_restarts`
(migration `277_hmm_multi_seed_restart.sql`, confirmed shipped, default `1`). If D-03's pilot
verdict favors `n_restarts > 1` as the new production default, that is a `config_state` value
UPDATE via `ConfigService` (with `config_history.changed_by`/`reason` recorded), not a new
migration — the key's schema already allows `1-20`. Only write a new migration if the plan
invents a genuinely new APR key (e.g., a pilot-specific config value); the pattern to follow if
so is migration 292's own shape (see excerpt below).

## Pattern Assignments

### `services/regime_writer.py` — Task A: `iters_used`/`n_iter_cap`/`converged` logging in `_walk_forward_hmm_full`

**Analog:** `_compute_symbol_tf`'s existing convergence-iteration log line, same file.

**Exact insertion point:** inside `_walk_forward_hmm_full`'s per-segment `while boundary < n:`
loop (`services/regime_writer.py:725-804`), immediately after the `converged = ...` /
non-convergence retry block (lines 738-754), same relative position `_compute_symbol_tf` uses
(logs right after `model` is finalized, before any downstream use of `model.means_`/`transmat_`).

**Analog log call to copy the shape of** (`services/regime_writer.py:1259-1269`):
```python
# Log HMM convergence iteration count for todo 226 (n_iter=200 headroom check).
# `converged` here is the corrected iter < n_iter signal (todo 229) -- a real
# tolerance-convergence indicator, not hmmlearn's always-True monitor_.converged.
_logger.info(
    "regime_writer.hmm_convergence_iters",
    symbol=symbol,
    tf=tf,
    iters_used=int(model.monitor_.iter),
    n_iter_cap=int(model.monitor_.n_iter),
    converged=converged,
)
```

**Adaptation needed:** `_walk_forward_hmm_full` has no `symbol`/`tf` in scope (it operates on a
bare `obs_matrix`, called by `_compute_symbol_tf_walk_forward` which DOES have them) — either
(a) thread `symbol`/`tf` down as new params to `_walk_forward_hmm_full` purely for logging
(matches this file's existing convention of passing `symbol`/`tf` through every layer for log
context), or (b) log without them and let `_compute_symbol_tf_walk_forward`'s own log calls
provide correlation via timing. Also add `seg_start=boundary, seg_end=seg_end` since one
(symbol, tf) cell now produces MANY log events (one per segment) instead of one — the event
name should probably change to something segment-scoped, e.g.
`regime_writer.walk_forward_hmm_convergence_iters`, to keep the two event shapes distinguishable
downstream (todo 226's analysis query will need to know which path a given event came from).

**Convergence-check pattern already correct in this function** (do not touch, already fixed
todo 229) — `services/regime_writer.py:738-743`:
```python
# hmmlearn 0.3.3's monitor_.converged is always True after fit() completes
# (ConvergenceMonitor.converged's first disjunct is `iter == n_iter`, which is
# trivially satisfied whenever the EM loop runs to its cap) -- iter < n_iter is
# the only signal that distinguishes a genuine tolerance-convergence from a
# cap-hit (todo 229, proven exact against hmmlearn 0.3.3's fit() loop).
converged = model.monitor_.iter < model.monitor_.n_iter
```

---

### `services/regime_writer.py` — Task B (conditional on pilot verdict): `n_restarts` threading through the walk-forward path

**Analog:** `_compute_symbol_tf`'s existing multi-seed restart loop, same file, lines 1181-1257.

**Full pattern to mirror** (adapted per-segment instead of per-cell):
```python
# services/regime_writer.py:1190-1257 (single-fit path, the loop to replicate
# inside _walk_forward_hmm_full's per-segment body)
model = None
converged = False
best_ll = float("-inf")
for i in range(n_restarts):
    seed = hmm_random_state + i
    candidate = GaussianHMM(
        n_components=n_components,
        covariance_type=eff_cov_type,
        n_iter=n_iter,
        random_state=seed,
    )
    candidate.fit(obs_matrix)
    candidate_converged = candidate.monitor_.iter < candidate.monitor_.n_iter
    if not candidate_converged:
        retry_model = GaussianHMM(..., n_iter=n_iter * 2, random_state=seed)
        retry_model.fit(obs_matrix)
        if retry_model.monitor_.iter < retry_model.monitor_.n_iter:
            candidate = retry_model
            candidate_converged = True
    if n_restarts == 1:
        model = candidate
        converged = candidate_converged
        break
    candidate_ll = float(candidate.score(obs_matrix))
    if model is None or (candidate_converged, candidate_ll) > (converged, best_ll):
        model = candidate
        converged = candidate_converged
        best_ll = candidate_ll
```

**Signature changes required:** add `n_restarts: int = 1` to `_walk_forward_hmm_full` and
`_compute_symbol_tf_walk_forward` (both currently fit exactly one seed —
`GaussianHMM(..., random_state=hmm_random_state)`, no loop, `services/regime_writer.py:625-630`
and `731-736`). Thread through `_run_symbol_worker`'s existing `walk_forward` branch
(`services/regime_writer.py:1533-1553`), which already receives `n_restarts` in its arg tuple
but currently only passes it to the `else` (single-fit) branch (line 1572) — add it to the
`if walk_forward_enabled:` call too.

**Only build this if D-03's pilot concludes it is needed** — RESEARCH.md's Second Finding
confirms `n_restarts` is unused on the walk-forward path today; do not thread it through
speculatively before the pilot's out-of-band comparison script (below) produces a verdict.

---

### `services/regime_writer.py` — Task C: NULL-out pre-step (data-integrity, main process only)

**Analog:** `_write_regime_results`'s write discipline (single serial connection, main process,
never a `ProcessPoolExecutor` worker) + `bulk_update_by_key`'s keyed-UPDATE mechanics.

**Write-connection discipline to copy** (`services/regime_writer.py:1358-1373`):
```python
def _write_regime_results(
    conn: Any, symbol: str, tf: str, update_rows: list[tuple],
    converged: bool, heldout_ll: float, tracer: Any,
) -> int:
    """Write HMM regime labels for one (symbol, tf) cell to feature_vectors.

    Runs in the main process — single serial write connection, no concurrency.
    Returns n_updated.
    """
```

**Column ownership list — the authoritative source, never hand-type it again**
(`src/intelligence/features/feature_vector_persistence.py:467-476`):
```python
REGIME_WRITER_OWNED_COLUMN_NAMES: tuple[str, ...] = (
    "regime",
    "hmm_prob_trending_up",
    "hmm_prob_ranging",
    "hmm_prob_trending_down",
    "hmm_regime_prob",
    "hmm_entropy",
    "hmm_duration",
    "hmm_churn",
)
```
Import this tuple (as `_write_regime_results` already does, `regime_writer.py`'s own
`set_cols=list(REGIME_WRITER_OWNED_COLUMN_NAMES)` at line 1391) — never re-type the 8 column
names inline. This is the exact same list a NULL-out statement must target.

**SQL shape (from RESEARCH.md's Critical Finding, not yet written anywhere in the repo)** —
must be scoped per `(symbol, tf)`, issued from main()'s single serial connection, never from a
worker:
```sql
UPDATE feature_vectors
SET regime = NULL, hmm_prob_trending_up = NULL, hmm_prob_ranging = NULL,
    hmm_prob_trending_down = NULL, hmm_regime_prob = NULL, hmm_entropy = NULL,
    hmm_duration = NULL, hmm_churn = NULL
WHERE symbol = %s AND tf = %s;
```

**Chunking discipline analog** (`.planning/phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-07-PLAN.md`,
Task 1 — a different script/table, `backfill_feature_factory.py`'s `--recompute` mode against
the same `feature_vectors` hypertable, but the exact chunking principle this phase's NULL-out
step must follow): never one corpus-wide statement; iterate per-partition (here:
per-`(symbol, tf)`), with a resumability record if the full 231×4tf scope makes a single script
run long enough to need restart-safety. The pilot's 5-10 symbol scope is small enough that a
manifest may be unnecessary — Claude's discretion at planning time — but the "one UPDATE per
(symbol, tf), not one UPDATE for the whole tf" discipline itself is not.

**Compression-awareness note (operational, not a code pattern):** `feature_vectors` is 83
chunks / 80 compressed (~96%) as of 2026-08-07 — check chunk compression status for the specific
`(symbol, tf)` chunks in scope before running, per
`docs/foundation/performance-investigation-sop.md` (cited directly by root `CLAUDE.md`).

---

### `scripts/analysis/hmm_walk_forward_seed_stability_pilot.py` (new)

**Analog:** `scripts/analysis/hmm_walk_forward_gate4_ic_pilot_spy_1h.py` (full file read, 224
lines) — the established shape for every diagnostic-only pilot script in this codebase.

**Imports pattern to copy** (lines 32-55):
```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import psycopg

from scripts.analysis._nonlinear_interaction_combiner_shared import (  # noqa: E402
    bootstrap_ic_stats,
    paired_bootstrap_ic_difference,
)
from services.regime_writer import (  # noqa: E402
    _LABEL_RANGING,
    _LABEL_TRANSITION_DOWN,
    _LABEL_TRANSITION_UP,
    _LABEL_TRENDING_DOWN,
    _LABEL_TRENDING_UP,
    _build_obs_matrix,
    _walk_forward_hmm_labels,   # substitute _hmm_seed_stability_check + _fetch_obs_matrix
)
from src.config.settings import Settings  # noqa: E402
```

**OHLCV fetch pattern to copy verbatim** (lines 104-123 — identical cursor/stream shape to
`_fetch_obs_matrix` inside `regime_writer.py` itself, reused here to bypass the DB-write path
entirely):
```python
settings = Settings()
conn = psycopg.connect(settings.database_url)

timestamps: list = []
closes: list[float] = []
volumes: list[float] = []
with conn.cursor("ohlcv_stream_gate4") as cur:
    cur.execute(
        "SELECT timestamp, close, volume FROM market_data_ohlcv_tradeable "
        "WHERE symbol = %s AND timeframe = %s ORDER BY timestamp ASC",
        (_SYMBOL, _TF),
    )
    while True:
        batch = cur.fetchmany(10000)
        if not batch:
            break
        for r in batch:
            timestamps.append(r[0])
            closes.append(float(r[1]))
            volumes.append(float(r[2]))
conn.commit()

obs_matrix, valid_ts = _build_obs_matrix(
    timestamps, closes, volumes,
    vol_window=_VOL_WINDOW, momentum_window=_MOMENTUM_WINDOW,
    vol_of_vol_window=_VOL_OF_VOL_WINDOW,
)
```

**Core pattern — substitute the primitive under test** (per RESEARCH.md's own Code Examples
section, the intended shape of the new script):
```python
from services.regime_writer import _build_obs_matrix, _hmm_seed_stability_check

# ... fetch real OHLCV for each pilot symbol/tf, build obs_matrix via _build_obs_matrix ...
result = _hmm_seed_stability_check(
    obs_matrix,
    n_components=5,
    covariance_type="full",
    n_iter=200,
    seeds=[42, 43, 44],  # hmm_random_state + i, matching todo 108's deterministic derivation
    full_cov_min_obs=500,
)
# result["min_pairwise_agreement"] is the pass/fail signal the pilot's go/no-go should read
```

**Multi-symbol adaptation needed:** the gate4 pilot is single-symbol (`_SYMBOL = "SPY"`); this
phase's pilot spans 5-10 symbols (D-01) across bar-density buckets (Claude's discretion — pull
candidates from across the 1h/15m/5m/1d calibration buckets migration 292 documents). Loop the
fetch+check over a `_PILOT_SYMBOLS: list[tuple[str, str]]` (symbol, tf) list rather than one
hardcoded pair; print one verdict block per cell plus a corpus-wide summary (min across cells is
the honest go/no-go signal, matching CLAUDE.md's "don't average away a bad outlier" instinct).

**Print/verdict pattern to copy** (lines 189-220 — `"=" * 80` banner blocks, explicit PASS/FAIL
line naming the exact gate being evaluated):
```python
print("=" * 80)
print(f"{_SYMBOL} {_TF}: ...")
print("=" * 80)
...
print(f"\n<gate name> (<threshold>, this pilot): {'PASS' if gate_pass else 'FAIL'}")
print("=" * 80)
```

---

### `scripts/analysis/hmm_n_restarts_walk_forward_comparison_pilot.py` (new, only if Task B is in scope)

**Analog:** same gate4 pilot script structural pattern, PLUS the conceptual discipline from
Phase 168 D-02 (`.planning/phases/168-cost-hurdle-adjusted-spread-construction-follow-on/168-CONTEXT.md`
D-02) — parallel-construction-never-mutate-baseline. RESEARCH.md's Second Finding is explicit
that this pattern does NOT transfer as a schema-level dual-write (unlike Phase 168's
`construction_spreads` table, which has a `construction_name` discriminator column,
`feature_vectors.regime` has none) — the comparison must happen **in-memory, in this script**,
never as two live writes to `feature_vectors`.

**Core pattern:** compute both label sequences via the SAME walk-forward primitive, varying only
`n_restarts` (or, if Task B isn't built, only the pilot's OWN inline multi-seed loop calling
`_walk_forward_hmm_full` per seed manually — do not implement this as a `regime_writer.py` code
change unless the pilot itself concludes it's needed, per RESEARCH.md's Open Question 2, which
recommends defaulting to a one-off script over new CLI surface):
```python
# n_restarts=1 arm (baseline — current production behavior)
labels_1, segments_1 = _walk_forward_hmm_labels(obs_matrix, ..., hmm_random_state=42)

# n_restarts>1 arm (comparison — NOT written to feature_vectors)
# if Task B exists: call the extended _walk_forward_hmm_full/_walk_forward_hmm_labels
# with n_restarts=N directly. If Task B doesn't exist yet: fit N seeds manually here,
# select best-log-likelihood per segment the same way _compute_symbol_tf's loop does,
# entirely inside this script — do not touch regime_writer.py for a one-off comparison.

# Compare via _hmm_seed_stability_check-style pairwise label agreement, or
# paired_bootstrap_ic_difference against forward_returns (same helper the gate4 pilot uses).
```

**Attribution safeguard (D-03's own stated requirement):** this script's output must let the
pilot's go/no-go gate independently attribute any observed change to walk-forward labeling
itself vs. multi-seed-restart — i.e., print BOTH (a) walk-forward vs. production baseline
(reusing the gate4 pilot's existing comparison), AND (b) walk-forward n_restarts=1 vs.
walk-forward n_restarts>1 (this script's own comparison), as two separate verdict blocks, never
conflated into one number.

---

### `scripts/analysis/regime_walk_forward_null_out_and_verify.py` (new)

**Analog:** `bulk_update_by_key`'s keyed-UPDATE mechanics (`services/_batch_utils.py:78-119`)
for the write half; REQ-3's own spot-check query (RESEARCH.md, Validation Architecture table)
for the verify half.

**Purpose:** a single checked-in script (not ad hoc psql lost to shell history, per RESEARCH.md's
Wave 0 Gaps) that (1) NULLs out the 8 `REGIME_WRITER_OWNED_COLUMN_NAMES` columns for a given
`(symbol, tf)` scope (pilot list first, full 231×4tf list for the real rollout), chunked per
cell, and (2) runs the post-relabel provenance verification query.

**Verification query pattern** (from RESEARCH.md's REQ-3 test-map row — not yet written
anywhere, this script is where it should live):
```sql
-- Post-relabel spot-check: warmup-prefix bars (before initial_warmup_bars) must be
-- NULL, never a stale full-history-fit value, for every (symbol, tf) this pass touched.
SELECT count(*) FROM feature_vectors
WHERE symbol = %s AND tf = %s
  AND bar_ts < %s  -- the warmup boundary timestamp for this (symbol, tf)
  AND regime IS NOT NULL;
-- Expected: 0. Nonzero means a stale pre-fix value survived the NULL-out + relabel pass.
```

**Connection/commit discipline to copy** — main-process-only, single serial connection, explicit
`conn.commit()` after each `(symbol, tf)` cell's UPDATE (matching `_write_regime_results`'s
`conn.commit()` at line 1407) so a mid-run failure leaves only fully-committed cells, never a
half-applied one.

---

### `tests/unit/services/test_regime_writer.py` (modify)

**Analog:** three existing tests in the same file, exact fixture/mocking idioms to reuse.

**Imports/fixtures already available — reuse, do not duplicate** (lines 1-99):
```python
import services.regime_writer as regime_writer_module
from services.regime_writer import (
    _LABEL_RANGING, _LABEL_TRENDING_DOWN, _LABEL_TRENDING_UP,
    _build_label_map, _build_obs_matrix, _compute_symbol_tf,
)
# _make_ranging_closes(n), _make_volumes(n), _make_timestamps(n), _make_mock_conn(...)
# already exist in this file — every new test below should use them, not hand-roll fixtures.
```

**Test 1 — walk-forward per-segment `iters_used` logging** (mirror
`test_compute_symbol_tf_logs_convergence_iterations`, lines 513-556): use
`structlog.testing.capture_logs()`, assert one log event per segment (not one total — the
walk-forward path fits ~20 segments over a full history, so a small synthetic fixture with a
small `refit_every_bars`/`initial_warmup_bars` should produce >1 segment and >1 log event, unlike
the single-fit path's exactly-one-event assertion).

**Test 2 — `n_restarts` selection on the walk-forward path** (only if Task B is built; mirror
`test_compute_symbol_tf_n_restarts_selects_highest_log_likelihood`, lines 794-870): same
"engineer a non-obvious winning seed via monkeypatched `GaussianHMM.score()`/`.fit()`" technique,
adapted to assert the selection happens correctly INSIDE each segment of
`_walk_forward_hmm_full`, not just once per cell.

**Test 3 — `_run_symbol_worker` dispatch-on-flag** (genuinely new, no existing analog in this
file — RESEARCH.md confirms this gap explicitly under REQ-2): construct the worker's arg tuple
with `walk_forward_enabled=True` vs `False`, monkeypatch `_compute_symbol_tf_walk_forward` and
`_compute_symbol_tf` to sentinel functions, assert exactly the expected one is called. Follow
`_run_symbol_worker`'s own arg-tuple unpacking order (`services/regime_writer.py:1499-1519`) when
constructing the test's input tuple — an out-of-order tuple will silently misassign params rather
than raise, since it's a positional unpack.

## Shared Patterns

### APR-flagged rollout discipline (already established, no new pattern to build)
**Source:** `production/migrations/292_hmm_walk_forward_apr.sql` (full file, 150 lines) +
`production/migrations/277_hmm_multi_seed_restart.sql` (full file, 44 lines)
**Apply to:** any future migration this phase might add, and to the config-flip step of the
pilot/rollout tasks
```sql
-- migration shape: config_schema INSERT (with provenance tag in description:
-- [initial_estimate] / [rca_analysis] / [conventional] / [user_preference]) +
-- config_state INSERT, both ON CONFLICT DO NOTHING, +
-- (migration 277's pattern, stricter) an explicit config_history INSERT recording
-- changed_by='migration_NNN' and a reason string -- do this for any config_state
-- value changed as part of this phase's rollout (e.g. flipping
-- alpha.hmm.walk_forward.enabled to true), even though it's a data change, not
-- a new key, so ConfigService's own write path (not a raw UPDATE) should be
-- used to keep config_history's provenance trail intact.
```

### Single-serial-write-connection / compute-daemon-never-writes-own-output (DAG Invariant 3)
**Source:** `services/regime_writer.py`'s existing `main()`/`_run_symbol_worker` split (workers
return `update_rows` tuples; only `main()`'s one connection ever calls `_write_regime_results`)
**Apply to:** the NULL-out pre-step and the verification script — both must run from the SAME
kind of single main-process connection, never dispatched into a `ProcessPoolExecutor` worker.

### Bulk keyed-UPDATE via temp table (avoids per-row round trips)
**Source:** `services/_batch_utils.py:78-119` (`bulk_update_by_key`)
**Apply to:** any new chunked-write logic in the NULL-out script; note this helper as written
sets columns from a `rows` param — a pure NULL-out doesn't need it (a plain
`UPDATE ... WHERE symbol = %s AND tf = %s` is simpler and sufficient, no temp table needed since
there's no per-row payload, just a blanket NULL) but the CSV/temp-table technique is the pattern
to reach for if the plan ever needs a per-row NULL-out (it should not — this is a blanket
column-set, not per-row varying data).

### Column-ownership single source of truth (never hand-type the 8-column list twice)
**Source:** `src/intelligence/features/feature_vector_persistence.py:467-476`
(`REGIME_WRITER_OWNED_COLUMN_NAMES`)
**Apply to:** every new file in this phase that touches these 8 columns (NULL-out script,
verification script, any new test asserting on column sets) — import the tuple, never re-type.

## No Analog Found

None — every file this phase needs has a strong same-file or same-directory analog. The one
near-miss is D-03's parallel-arm comparison script, which has no exact precedent (Phase 168's
`construction_spreads` discriminator-column pattern doesn't transfer to `feature_vectors`'
single-column schema) — documented above as a role-match combining the gate4 pilot's script
structure with Phase 168's comparison discipline applied at the analysis-script level instead of
the schema level.

## Metadata

**Analog search scope:** `services/regime_writer.py` (full file, 1888 lines, read across 5
non-overlapping ranges), `services/_batch_utils.py` (lines 1-125), `tests/unit/services/test_regime_writer.py`
(full test-name inventory via grep + 4 targeted reads), `scripts/analysis/hmm_walk_forward_gate4_ic_pilot_spy_1h.py`
(full file), `production/migrations/292_hmm_walk_forward_apr.sql` + `277_hmm_multi_seed_restart.sql`
(full files), `src/intelligence/features/feature_vector_persistence.py` (lines 455-528),
`.planning/phases/151-.../151-07-PLAN.md` (targeted grep), `scripts/ops/corpus/ops_corpus_pipeline_run.sh`
(lines 290-375)
**Files scanned:** ~10 (all read-only, no source files modified by this pattern-mapping pass)
**Pattern extraction date:** 2026-08-07
