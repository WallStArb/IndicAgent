# Phase 162: ic_engine Corpus Pipeline Throughput - Research

**Researched:** 2026-07-21
**Domain:** Batch measurement pipeline throughput (incremental recompute + fingerprinting +
memory-bounded compute) in a single 3,928-line psycopg2/ProcessPoolExecutor oneshot,
`services/ic_engine.py`
**Confidence:** HIGH (all findings are direct reads of live `main` at commit `2f5334f2`, not
training-data recall; no external library research was needed — this phase touches only
first-party code)

<user_constraints>
## User Constraints (from CONTEXT.md)

No CONTEXT.md exists for this phase — no `/gsd:discuss-phase` was run. Per the phase-kickoff
instructions, the ROADMAP.md phase description (two Fable design passes, 2026-07-18 and
2026-07-19) serves as the equivalent of discuss-phase's locked decisions. Copied verbatim below.

### Locked Decisions (from the ROADMAP.md phase description, both Fable passes)
- Feature-axis chunking for the memory bound (todo 140) — time-axis chunking is explicitly
  rejected as a statistics change, not just an optimization choice.
- Structural work (todos 129 + 009E + 139/140) goes first as 162-01, before the benchmark
  (162-02) and the fingerprint (162-03) — the fingerprint hashes `_checkpoint_content_key()`
  (source bytes), so any refactor after it ships invalidates every fingerprint.
- `ic_cell_fingerprints` new table, one row per (symbol|'POOLED', tf, pass_type,
  training_window_end); fingerprint = code content-key + APR computation-affecting field hash +
  upstream data watermarks.
- Fingerprint validity check runs in `main()` before `worker_args` construction, replacing the
  existing fingerprint-blind `existing_keys` skip.
- `--refresh` and `--dry-run-validity` CLI flags.
- Staleness threshold: a fingerprint-valid cell is never auto-stale. Data-driven refresh is an
  explicit act via `--training-window-end`. Wall-clock staleness stays alerting-only
  (`alpha.ic.staleness_alert_days=5`), not an auto-recompute trigger.
- No statistical-methodology change: BH-FDR still runs over the complete current-window
  hypothesis family including skipped cells.
- Absorbs todo 122 (checkpoint APR drift) as a special case of the fingerprint.
- Do not build a scheduler — incremental recompute is the precondition for a cadence, not the
  cadence itself.

### Claude's Discretion
- Exact `ic_cell_fingerprints` column shape/migration number (this research proposes 248 with a
  draft CREATE TABLE — see Code Examples).
- DELETE-then-insert vs. upsert mechanism for invalidating stale rows (this research recommends
  DELETE-then-insert — see Common Pitfalls, Pitfall 1 — but flags it as A2 in the Assumptions
  Log, not a locked decision).
- Exact extraction boundaries for `_compute_cross_sectional_tf`'s still-inline per-scale block
  (162-01), given Task 1 already restructured the symbol-side equivalent out from under the
  original design (see Summary, Pitfall 3).
- Upstream watermark computation method (row count vs. `MAX(bar_ts)` vs. content-ish hash) — see
  Open Questions #1.

### Deferred Ideas (OUT OF SCOPE)
- Building a scheduler/cadence on top of incremental recompute (explicit risk #6 in the phase
  description).
- Wider cross-service `short_lived_conn` adoption beyond `ic_engine.py`'s 3 dsn-based sites
  (todo 129's "Update 2026-07-18" scope-widening to `regime_writer.py`/`equity_regime_model.py`/
  `backfill_feature_factory.py`/`cross_sectional_regime_model.py` is explicitly NOT part of
  Phase 162 per that todo's own "Moved to deferred" note — narrow scope only).
- Any statistical-methodology change to IC/CI/walk-forward computation itself — this phase is
  throughput/correctness-of-recompute only.
</user_constraints>

## Summary

Two rounds of Fable design work (2026-07-18/19, folded into ROADMAP.md) already resolved the
hard design questions for this phase: feature-axis (not time-axis) chunking for the memory
bound, structural-work-first sequencing (162-01 before 162-02/03), and the fingerprint table
shape. This research does not re-litigate those. Its job was narrower: verify the design's
concrete file/line/function references against `main` as it stands today (2026-07-21), because
the design was written against a version of `ic_engine.py` that has since been restructured by
an unrelated in-flight change (Task 1 of the symbol_hmm restoration, commits `0e38bf8e` +
`2f5334f2`), and locate the real precedents the design gestured at but didn't cite exactly
(`_short_lived_conn`, `ic_math.py`'s extraction pattern, migration conventions).

**Primary finding: the file has moved out from under the design in one specific, actionable
way.** The 2026-07-18/19 design assumed `_compute_symbol_tf`'s per-scale subsample/rank/CI/
walk-forward loop was still inline (matching `_compute_cross_sectional_tf`'s shape). It is not
— Task 1 (this same worktree, already merged to `main`) extracted it into its own function,
`_compute_one_regime_cell` (`services/ic_engine.py:779-1107`), so that it can run multiple times
per (symbol, tf): once pooled, once per primary label source, optionally once more for the
dual-write pass. `_compute_cross_sectional_tf`'s equivalent block (`ic_engine.py:2054-2179`) is
still fully inline. This is good news for 162-01/todo 139: half the promised extraction already
happened as a side effect of unrelated work, on the symbol side; the remaining work is (a)
extracting `_compute_cross_sectional_tf`'s inline block into a comparable shared/parallel
helper, and (b) applying the feature-axis memory-blocking rewrite to whichever shared shape
results. The two blocks are still near-identical (not byte-identical — cross-sectional has an
extra e-value-pilot column and a `max_workers=` bootstrap knob the per-symbol path doesn't),
confirming todo 139's premise still holds post-extraction.

A second, load-bearing finding: `production/migrations/247_regime_groups_dual_write_symbol_hmm.sql`
is already reserved by Task 2 of that same in-flight symbol_hmm restoration work (not yet run —
STATE.md documents it as the next unstarted task on this worktree). Phase 162's fingerprint
table migration must use **248**, not 247, and the planner should flag this as a
sequencing/collision risk between two independent workstreams touching the same file, not
silently pick a number and hope no collision occurs.

Third: the existing `test_ic_engine_idempotency.py` unit test directly asserts `"DO NOTHING" in
_POOLED_INSERT_SQL` / `_REGIME_INSERT_SQL` / `_CROSS_SECTIONAL_INSERT_SQL`. 162-03's own risk #1
("`ON CONFLICT DO NOTHING` silently discards recomputes") is real and confirmed live at exactly
the cited insert sites, but the fix that best preserves the existing idempotency contract (and
this test) is a targeted `DELETE FROM feature_ic_scores WHERE <cell key match> AND
training_window_end = %s` immediately before recompute of a fingerprint-invalidated cell —
**not** converting the INSERT statements to `DO UPDATE`. Converting to upsert would require
rewriting this test's entire premise; delete-then-insert leaves the existing INSERT SQL, its
test, and its "idempotent, DO NOTHING, re-run inserts 0 rows" module docstring invariant
completely untouched, and only adds a new, narrow, fingerprint-gated DELETE step in `main()`
ahead of `worker_args` construction — the same place `existing_keys` is already computed.

**Primary recommendation:** Plan 162-01 as "finish the extraction Task 1 already started,
apply it to `_compute_cross_sectional_tf` too, then do the feature-block memory rewrite on the
now-shared shape" rather than "extract two inline loops into one new helper" — the second framing
describes a file state that no longer exists. Plan 162-03's schema at migration **248** (not
247), and its recompute-invalidation mechanism as **DELETE-then-insert**, not upsert, to avoid
touching (and needing to rewrite the intent of) `test_ic_engine_idempotency.py`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Per-cell fingerprint compute + validity check | API/Backend (batch oneshot, `main()`) | — | Must run before `worker_args` construction, single-threaded, same tier as the existing `existing_keys` query it replaces |
| Fingerprint persistence (`ic_cell_fingerprints`) | Database/Storage | — | New table, same tier as `feature_ic_scores`; no hypertable needed (row count bounded by symbol×tf×pass_type×window, same order of magnitude as `feature_registry`) |
| Feature-blocked rank/IC/CI/fold compute | API/Backend (`ProcessPoolExecutor` workers for per-symbol; single-process for cross-sectional) | — | Compute-only, no DB or transport involvement; stays inside the existing worker/main-process split |
| Connection lifecycle (`short_lived_conn`) | API/Backend (`services/_batch_utils.py`) | — | Shared utility module already used by `ic_engine.py` and `ensemble_ic_engine.py`; natural home for the new dsn-based context manager |
| Cross-sectional bootstrap thread-count tuning | API/Backend (`ICEngineConfig`/APR) | — | Pure performance knob, no behavior change; existing per-tf dict precedent (`bootstrap_block_size`) is the template |
| Checkpoint (`.pkl`) system fate | API/Backend | — | Candidate for deletion (risk #4) once fingerprinting supersedes its "resume a killed run" purpose — needs an explicit decision, not silent removal |

No browser/frontend/CDN tier involvement — this is a pure backend batch measurement service
with no UI surface.

## Standard Stack

This phase adds no new third-party dependencies. Everything it touches is already imported in
`services/ic_engine.py`: `psycopg2`/`psycopg2.extras`, `numpy`, `scipy.stats.rankdata`,
`hashlib`, `concurrent.futures.ProcessPoolExecutor`. No `## Package Legitimacy Audit` section is
included — no packages are being installed.

### Core (existing, reused)
| Module | Role | Why reused, not replaced |
|--------|------|---------------------------|
| `services/_batch_utils.py` | `connect_db_from_url(dsn)`, `Float32ChunkAccumulator` | `connect_db_from_url` is the exact function todo 129's `short_lived_conn(dsn)` wraps; `Float32ChunkAccumulator` (todo 087) is the direct structural precedent for a feature-axis chunked accumulator |
| `src/intelligence/statistics/ic_math.py` | Pure-function math extraction target (todo 048 precedent) | `build_walk_forward_folds` belongs here, matching the module's own stated contract: "Pure functions only — no DB, no config loading, no module-global mutable state" |
| `src/core/agent/base_batch.py` | `BaseBatch.content_key(*parts) -> str` (SHA-256, 32 hex chars) | Existing content-addressed-key primitive, already used by `alpha_frame_writer.py`, `alpha_publisher.py`, `ensemble_ic_engine.py`; candidate for hashing `ICEngineConfig`'s computation-affecting field snapshot in the fingerprint |

No new library needed for the APR-field-classification hash either — Python's stdlib
`hashlib.sha256` (already imported in `ic_engine.py` for `_checkpoint_content_key`) is
sufficient and is the established local idiom.

## Package Legitimacy Audit

Not applicable — this phase adds zero external packages. Confirmed by reading
`services/ic_engine.py`'s existing import block (lines 56-105): all imports are stdlib,
already-installed scientific stack (numpy/scipy/statsmodels), or first-party modules.

## Project Constraints (from CLAUDE.md)

Directives from `./CLAUDE.md` that bind this phase's plan, extracted for planner verification:

- **APR mandate** — any new numeric threshold/weight/period/count must be added to
  `config_state` via `ConfigService.get(key, default=X)`, never a hard-coded constant. This
  phase's new knobs (`alpha.ic.feature_block_columns`, `alpha.ic.max_cell_rows`, and the per-tf
  `cross_sectional_bootstrap_threads.{5m,15m,1h,1d}` split) MUST follow the
  seed→`config_schema`+`config_state`→`config_history` migration pattern, described with
  provenance (`[initial_estimate]`/`[conventional]`/`[rca_analysis]`/`[user_preference]`).
- **Migrate-as-you-go** — any hard-coded numeric threshold encountered in the touched code
  during this phase must be migrated to APR in the same session, not deferred.
- **DAG invariant 3** — "A compute daemon never writes its own computed output" — does NOT
  apply to `ic_engine.py`, which is explicitly exempted in its own module docstring ("this
  oneshot is exempt... it is a batch measurement tool, not a real-time daemon"). No change
  needed here, but the planner should not mistakenly try to "fix" this by splitting compute
  from write — that would contradict the file's own documented, correct exemption.
- **Exception variable name is `error`** — `except X as error:`, not `exc`. Applies to any new
  `try/except` in `short_lived_conn`, the fingerprint check, or new tests.
- **`ProcessPoolExecutor` workers are compute-only** — already honored by `_compute_symbol_tf`'s
  existing "No DB writes — returns rows" contract; any new worker-side code (e.g. the feature-
  blocked compute helper) must preserve this, never open a write connection from inside a worker.
- **Never log per-row inside a loop over the full corpus** — the fingerprint check's per-symbol
  watermark queries must accumulate a counter and log once, not log per-cell/per-feature.
- **Timestamp serialization** — `format_iso_ts(dt)` from `service_utils.py`, never inline
  `.isoformat()` — applies if the fingerprint's `upstream_watermark` JSONB serializes any
  timestamp fields.
- **All timestamps UTC** — `datetime.now(UTC)` only, matches this file's existing `run_ts`
  parameter usage throughout.
- **File/class renames require a test sweep** — `grep -r "OldName" tests/` — applies if
  `_compute_cross_sectional_tf`'s extracted helper is given a new name during 162-01; the
  existing `test_ic_engine_compute_split.py`/`test_ic_engine_parallelism.py` tests reference
  function names directly and will break at collection, not lint, if renamed without updating.
- **ON CONFLICT for partial indexes** — "use column list + WHERE clause, not ON CONSTRAINT"
  (STATE.md's Key Decisions) — directly relevant to Pitfall 1's DELETE-then-insert
  recommendation; any new `ic_cell_fingerprints` upsert (if the design ultimately needs one)
  must follow this same convention, matching `feature_ic_scores`'s existing pooled/regime/
  cross-sectional partial-index pattern.

## Architecture Patterns

### System Data Flow (relevant slice)

```
feature_vectors ┐
forward_returns ├─► _assert_prerequisites (crash-loud gate)
market_regimes  ┘
        │
        ▼
main(): compute existing_keys  ──────────────────►  [NEW 162-03: replace with
   (SELECT feature_ic_scores                          fingerprint validity check —
    WHERE training_window_end=%s)                      same query shape, adds fingerprint
        │                                               comparison + DELETE for stale cells]
        ▼
worker_args = [(symbol, tfs, dsn, training_window_end,
                existing_keys_frozen, config, ...), ...]
        │
        ▼ (ProcessPoolExecutor, n_workers)
_run_ic_worker(args) ──► _compute_symbol_tf(dsn, symbol, tf, ...)
        │                     │
        │                     ├─► connect_db_from_url(dsn)   [fetch phase, 2 conns]
        │                     ├─► _compute_one_regime_cell(...) × (pooled + primary [+ dual-write])
        │                     │        │
        │                     │        └─► per-scale loop: subsample → rankdata → IC →
        │                     │            bootstrap CI → walk-forward folds → Sharpe
        │                     │            [NEW 162-01: feature-blocked, O(n_sub × block) not
        │                     │             O(n_sub × n_features) peak]
        │                     └─► returns (pooled_rows, regime_rows, stats)
        │
        ▼ (main process, serial, as_completed)
_record_symbol_result → _write_symbol_results → _write_ic_results
        (psycopg2.extras.execute_batch, ON CONFLICT DO NOTHING)
        [NEW 162-03: DELETE stale rows for this cell key BEFORE this INSERT,
         only when fingerprint says stale]
        │
        ▼
_compute_cross_sectional_tf(dsn, tf, regime_label, symbol_list, ...)  (single-process, after pool shuts down)
        │  same per-scale shape as above, still inline as of 2026-07-21
        │  [NEW 162-01: extract to match _compute_one_regime_cell's shape, then feature-block it]
        ▼
_write_cs_cell_results → _write_cross_sectional_results
        │
        ▼
_backfill_bh_fdr (corpus-wide UPDATE over ALL rows at this training_window_end,
                   skipped cells included — unaffected by fingerprinting, must stay this way
                   per success criterion 3 / risk #2)
```

### Recommended Project Structure (files touched, no new files except migration + tests)
```
services/
├── ic_engine.py            # _compute_one_regime_cell, _compute_cross_sectional_tf,
│                            # main() existing_keys→fingerprint swap, INSERT/DELETE sites
├── _batch_utils.py          # + short_lived_conn(dsn) contextmanager (todo 129)
src/intelligence/statistics/
├── ic_math.py               # + build_walk_forward_folds(n_obs, n_folds, embargo_bars)
production/migrations/
├── 248_ic_cell_fingerprints.sql   # NEW — see Code Examples below for shape precedent
tests/unit/
├── test_ic_engine_compute_split.py       # extend: cross-sectional extraction parity
├── test_ic_engine_idempotency.py         # extend, do NOT rewrite: add DELETE-path tests
├── test_ic_engine_fingerprint.py         # NEW
├── test_ic_math_walk_forward_folds.py    # NEW
```

### Pattern 1: Content-addressed hashing for cache/fingerprint identity
**What:** `BaseBatch.content_key(*parts) -> str` — SHA-256 of `"|".join(parts)`, truncated to 32
hex chars. `_checkpoint_content_key()` — SHA-256 over the read bytes of every first-party module
actually present in `sys.modules` under `src/`/`services/`, truncated to 12 hex chars.
**When to use:** `_checkpoint_content_key()` is exactly the "code content-key" component the
fingerprint needs — reuse it directly (it already exists, already handles the
git-HEAD-invalidates-everything failure mode from 2026-07-15). `BaseBatch.content_key()` is the
right tool for hashing the APR-field snapshot (a tuple of `(key, value)` pairs, stringified) into
the fingerprint's second component.
**Example:**
```python
# Source: services/ic_engine.py:2360-2401 (existing, verified live)
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

### Pattern 2: Main-process short-lived connection (existing precedent for todo 129)
**What:** `_short_lived_conn(settings)` — a `@contextmanager` wrapping
`connect_db_from_url(settings.database_url)` with a guaranteed `finally: conn.close()`.
**When to use:** This IS the model todo 129 asks the worker-side helper to mirror. It is
**Settings-based** (main-process only — a `Settings` object can't cross a `ProcessPoolExecutor`
boundary). The new worker-side sibling must take `dsn: str` instead, per the existing docstring
that already explains why they're two different helpers.
**Example:**
```python
# Source: services/ic_engine.py:383-400 (existing, verified live)
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
The new helper (place in `services/_batch_utils.py`, next to `connect_db_from_url`):
```python
@contextmanager
def short_lived_conn(dsn: str):
    """Worker-side sibling of ic_engine.py's Settings-based _short_lived_conn (todo 129).
    Takes a dsn string (picklable, crosses ProcessPoolExecutor boundary) instead of a
    Settings object. Guarantees conn.close() even on exception mid-fetch — the 3
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

### Pattern 3: Pure-function extraction into ic_math.py (todo 048 precedent)
**What:** `ic_math.py`'s own docstring states the contract: functions extracted here must be
pure (no DB, no config loading, no module-global mutable state besides one documented constant),
and must access config via a `Protocol` (see `SharpeWindowConfig`, `ic_math.py:100`) rather than
importing the concrete `ICEngineConfig`/`EnsembleICConfig` dataclass, so the module stays free of
a dependency back onto either caller.
**Note on the research prompt's function names:** `compute_ic_for_window` and `apply_corpus_fdr`
(as named in the phase-kickoff prompt) do not exist verbatim anywhere in the codebase — this was
an inexact paraphrase. The real precedent functions are `apply_bh_fdr` (`ic_math.py:513`, the
actual FDR extraction) and `_vectorized_ic`/`_compute_ic_rolling_metrics` (the actual
todo-048-extracted IC/Sharpe functions). Cite `apply_bh_fdr` as the placement precedent for
`build_walk_forward_folds`, not the prompt's function names.
**Example — the shared fold-boundary math already exists in 4 near-identical copies, confirmed
live:**
```python
# Source: services/ic_engine.py:978 (inside _compute_one_regime_cell)
#         services/ic_engine.py:1533 (inside _compute_symbol_tf's separate daily
#             context-features scalar loop — a genuinely distinct 3rd copy, not a duplicate
#             of the above; has its own n_valid >= folds*2+embargo guard the others lack)
#         services/ic_engine.py:2123 (inside _compute_cross_sectional_tf)
#         services/ensemble_ic_engine.py:818 (separate service, same math)
for k in range(walk_forward_folds):
    train_end = int(n_valid * (k + 1) / (walk_forward_folds + 1))
    test_start = train_end + embargo_bars
    test_end = int(n_valid * (k + 2) / (walk_forward_folds + 1))
    if test_start >= test_end or (test_end - test_start) < min_reliable_n:
        continue
    # ... callers diverge here: 3 do vectorized array rank+IC, 1 (line 1533) does
    # scalar single-feature rank+IC. build_walk_forward_folds should extract ONLY the
    # boundary math (train_end/test_start/test_end + the skip predicate), returning an
    # iterator of (test_start, test_end) or None, leaving the rank/IC step to each caller —
    # that's the shape all 4 call sites can share without forcing the scalar-vs-vector
    # difference into the shared function.
```
Recommended signature (matches the design doc's `build_walk_forward_folds(n_obs, n_folds,
embargo_bars)`, refined against what all 4 sites actually need):
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

### Pattern 4: Feature-axis chunked accumulator (extends the todo-087 row-axis precedent)
**What:** `Float32ChunkAccumulator` (`services/_batch_utils.py:147-187`) already establishes
"buffer into chunks, convert to float32 array per chunk, discard the Python-list intermediate" —
but along the **row** axis (streaming DB fetch). Todo 140's fix needs the identical idiom applied
along the **feature** axis, inside the already-in-memory per-scale compute loop, not the fetch.
**When to use:** As the structural template for whatever `_subsample_and_rank`-equivalent helper
162-01 introduces — same "preallocate output, process in bounded blocks, never materialize a
full `n_sub × n_features` float64 intermediate" idea `Float32ChunkAccumulator`'s docstring already
argues for, just on the other axis. The 2026-07-19 reconciliation's confirmed root cause
(`ic_engine.py:1941-1949`'s inline comment: `rankdata()` always returns float64 regardless of
input dtype, defeating the float32 cast one line earlier) is the exact transient this must bound.

### Anti-Patterns to Avoid
- **Time-axis chunking of `rankdata`:** explicitly rejected by the 2026-07-19 design pass —
  `rankdata` on a row-block is a different statistic than `rankdata` on the whole cell. Verified
  live: `rankdata(X_sub_nd, axis=0)` (`ic_engine.py:931`, `:2094`) ranks each feature column
  independently across ALL rows in that axis-0 call, so splitting rows changes the answer;
  splitting columns (features) does not, since `axis=0` ranking of column j never touches
  column j+1's values.
- **Converting `ON CONFLICT DO NOTHING` to `DO UPDATE`:** breaks `test_ic_engine_idempotency.py`
  outright (it asserts the literal string `"DO NOTHING"` is present) and rewrites the module's
  own documented invariant ("Idempotent: ON CONFLICT DO NOTHING. Re-run inserts 0 rows.",
  `ic_engine.py:30`). Use DELETE-then-insert for the fingerprint-invalidated path instead — see
  Common Pitfalls below.
- **Reusing `existing_keys`'s exact per-cell-key shape for the fingerprint join:** the fingerprint
  needs to be checked BEFORE deciding whether to include a symbol in `worker_args` at all (to
  skip the fetch, not just skip individual result rows) — `existing_keys` today is checked
  per-feature deep inside the compute loop (`ic_engine.py:1049`, `:2183`) AND as a whole-cell
  pre-filter one level up (`ic_engine.py:1844`, `_compute_cross_sectional_tf`'s
  `all_cells_for_regime.issubset(existing_keys)`). The fingerprint check needs to happen at the
  `main()` level, one step further out, before `worker_args` is built at all (`ic_engine.py:3570`)
  — matching where `existing_keys` itself is currently queried (`ic_engine.py:3448-3460`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Content-addressed hash for fingerprint identity | A new ad-hoc hash scheme | `_checkpoint_content_key()` (code component) + `BaseBatch.content_key()` (APR-snapshot component) | Both already exist, already tested, already solve the exact "code/config change must invalidate a cached result" problem this phase needs, at two different granularities |
| Row-buffering-to-array bookkeeping | A new feature-axis buffer class from scratch | Extend/mirror `Float32ChunkAccumulator`'s pattern | Same problem shape (bound peak memory by processing in bounded blocks, discard intermediates), different axis |
| Per-tf performance knob storage | A single scalar APR key threaded uniformly to every tf | The `bootstrap_block_size.{5m,15m,1h,1d}` flat-key pattern (`production/migrations/157_alpha_ic_apr_keys.sql`, `173_ic_sharpe_hac.sql`) | `cross_sectional_bootstrap_threads` (todo 133) needs exactly this treatment — 4 separate flat APR keys assembled into a dict inside `ICEngineConfig.from_apr()`, not a JSON blob key |

**Key insight:** every mechanism this phase needs (content hashing, chunked accumulation,
per-tf config) already has a load-bearing precedent inside this exact file or its immediate
siblings, put there by prior incident-driven fixes (2026-07-08 OOM, 2026-07-12 checkpoint
staleness, 2026-07-15 git-HEAD invalidation, 2026-07-18 second OOM). This phase is explicitly a
"generalize the pattern, don't invent a new one" phase.

## Common Pitfalls

### Pitfall 1: `ON CONFLICT DO NOTHING` silently discards a fingerprint-triggered recompute
**What goes wrong:** All 3 INSERT sites (`_POOLED_INSERT_SQL` line ~311-316,
`_REGIME_INSERT_SQL` line ~317-322, `_CROSS_SECTIONAL_INSERT_SQL` line ~326-331 — confirmed
still present and unchanged at these line ranges as of 2026-07-21) use `ON CONFLICT ... DO
NOTHING`. If a fingerprint mismatch triggers a recompute of a cell that already has rows, the
recompute's fresh INSERT is a no-op — the stale row silently survives, and downstream BH-FDR/
ensemble/publisher reads keep serving the old (possibly wrong) IC value.
**Why it happens:** The `DO NOTHING` clause was designed for a different scenario entirely
(safe re-run after a crash, where re-inserting an already-correct row should be a no-op) and was
never designed to handle "this row exists but is now known-wrong."
**How to avoid:** Add a `DELETE FROM feature_ic_scores WHERE feature_name=... AND symbol=... AND
tf=... AND [regime=... | is_pooled=true] AND lookahead_bars=... AND training_window_end=%s`
step, scoped to exactly the cell keys the fingerprint check flagged stale, executed in `main()`
immediately before that cell is added to `worker_args`/before its rows are written — NOT a
blanket `DELETE ... WHERE training_window_end=%s` (would also delete valid, unrelated cells at
the same window). This keeps the existing INSERT SQL constants, their `DO NOTHING` clause, and
`test_ic_engine_idempotency.py` completely untouched.
**Warning signs:** A `--refresh` run reports 100% of cells recomputed but `feature_ic_scores`
row `computed_at` timestamps don't advance for the "recomputed" cells — the tell that inserts
silently no-op'd.

### Pitfall 2: BH-FDR family coherence breaks if fingerprinting changes which rows are "current"
**What goes wrong:** `_backfill_bh_fdr` (`ic_engine.py:2529`) runs a single corpus-wide
`multipletests` call over every representative row at a given `training_window_end`, skipped
cells included — this is deliberate (the module docstring notes a prior per-cell FDR bug
inflated the effective false-discovery rate ~232x). If a fingerprint-skip path leaves stale
`bh_adjusted_p`/`passes_fdr` values on skipped rows while fresh rows get a NEW backfill pass
scoped only to the newly-written subset, the family is no longer coherent — skipped rows carry
FDR results computed against a different hypothesis family than fresh rows.
**Why it happens:** Skipping compute is easy to reason about per-cell; BH-FDR correctness is a
whole-corpus property that doesn't compose per-cell.
**How to avoid:** `_backfill_bh_fdr` must continue running unconditionally over the complete
current-window hypothesis family (`WHERE training_window_end = %s AND passes_fdr IS NULL`, per
`test_ic_engine_incremental_write.py`'s existing test) every run, regardless of how many cells
were skipped by the fingerprint check — do not gate this backfill on "did anything change."
**Warning signs:** `passes_fdr` values differ between two runs against an identical corpus state
purely because one run skipped more cells than the other.

### Pitfall 3: Task 1's extraction changed the file shape the design was written against
**What goes wrong:** Planning 162-01 as "extract two inline loops" (the literal 2026-07-18/19
design text) produces a plan whose first step (extracting `_compute_symbol_tf`'s loop) is
already done, leading to either wasted re-verification work or, worse, a plan step that tries to
re-extract an already-extracted function and produces a confusing double-wrapped result.
**Why it happens:** The design predates Task 1 (commits `0e38bf8e`/`2f5334f2`, merged to `main`
2026-07-21, same day this research ran) by 2-3 days; nobody re-diffed the design against `main`
before this research pass.
**How to avoid:** Frame 162-01 as: (1) extract `_compute_cross_sectional_tf`'s still-inline
per-scale block (`ic_engine.py:2054-2179`) into a function with a comparable signature/shape to
`_compute_one_regime_cell`; (2) apply the shared `build_walk_forward_folds`/connection-manager/
feature-block memory work to both `_compute_one_regime_cell` and the newly-extracted
cross-sectional function. Gate each step on bit-identical output against the `be74f4a1`
regression fixture, per the design's own stated methodology — that part of the design is still
correct, only the starting file shape assumption needs correcting.
**Warning signs:** A plan task description that says "extract the inline loop from
`_compute_symbol_tf`" — that loop no longer exists in that function; it was moved.

### Pitfall 4: Migration number collision with an independent in-flight workstream
**What goes wrong:** Migration `247_regime_groups_dual_write_symbol_hmm.sql` is reserved (text
exists in a not-yet-executed plan doc, `docs/superpowers/plans/2026-07-21-restore-symbol-hmm-ic-measurement-for-routed-symbols.md`)
by Task 2 of the symbol_hmm restoration work on this exact worktree — separate from Phase 162,
not yet run. If Phase 162's planner also picks 247, whichever migration lands second either
fails outright (file already exists) or silently overwrites migration history depending on how
it's applied.
**Why it happens:** Migration numbers are assigned by "next free number at authoring time," and
two independent workstreams can pick the same "next free number" if authored close together
without cross-checking.
**How to avoid:** Phase 162's `ic_cell_fingerprints` migration should be authored as **248**.
Re-check `ls production/migrations/ | sort -t_ -k1 -n | tail -3` immediately before actually
writing the migration file during execution (not just at planning time) in case 247 has landed
by then, and increment accordingly.
**Warning signs:** `git status` shows a migration file collision, or two migrations with the
same leading number in the same commit.

## Code Examples

### `ic_cell_fingerprints` migration shape (follows the live 225/171/169 conventions)
```sql
-- Source: pattern verified against production/migrations/225_concept_registry_mvp.sql
-- (idempotent CREATE TABLE IF NOT EXISTS, ON CONFLICT DO NOTHING / WHERE NOT EXISTS guards,
-- config_schema+config_state+config_history triple-insert for APR keys) and
-- production/migrations/156_ic_engine_tables.sql (feature_ic_scores itself: NOT a
-- hypertable -- only forward_returns and concept_transition_log use create_hypertable()
-- in this codebase; feature_ic_scores is a plain table with a composite PK + partial
-- unique indexes, and ic_cell_fingerprints should follow that same non-hypertable shape,
-- since its row count is bounded the same way: O(symbols x tfs x pass_types x windows),
-- not O(bars)).

BEGIN;

CREATE TABLE IF NOT EXISTS ic_cell_fingerprints (
    symbol               TEXT        NOT NULL,  -- or 'POOLED' for cross-sectional cells
    tf                   TEXT        NOT NULL,
    pass_type            TEXT        NOT NULL
        CHECK (pass_type IN ('pooled', 'symbol_hmm', 'cross_sectional')),  -- see
        -- _resolve_regime_scope's existing 3-value vocabulary, ic_engine.py:210-239 --
        -- reuse it verbatim rather than inventing a new enum
    training_window_end  TIMESTAMPTZ NOT NULL,
    code_content_key     TEXT        NOT NULL,   -- _checkpoint_content_key() output (12 hex)
    apr_snapshot_key     TEXT        NOT NULL,   -- BaseBatch.content_key() over the
                                                  -- computation-affecting ICEngineConfig
                                                  -- field tuple
    upstream_watermark   JSONB       NOT NULL,   -- {feature_vectors: ..., forward_returns: ...,
                                                  -- market_regimes: ..., instrument_tags: ...,
                                                  -- feature_registry_status: ...} -- see note
                                                  -- below: none of these source tables carry
                                                  -- an updated_at column today, so the
                                                  -- watermark must be a computed value
                                                  -- (MAX(bar_ts), row count, or content hash),
                                                  -- not a column read
    computed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, tf, pass_type, training_window_end)
);

COMMENT ON TABLE ic_cell_fingerprints IS
    'Per-cell (symbol|POOLED, tf, pass_type, training_window_end) validity fingerprint for '
    'ic_engine.py incremental recompute (Phase 162). A cell is skip-eligible only when ALL '
    'THREE components (code, APR snapshot, upstream watermark) match the current run -- a '
    'partial match is treated as a full miss (crash-loud, not silently partial-stale).';

COMMIT;
```

### Watermark computation note (no existing column to read)
```sql
-- Source: verified against production/migrations/171_market_regimes.sql (PK: asset_class,
-- tf, ts -- no updated_at) and production/migrations/169_feature_registry.sql (status
-- column exists, no last-modified timestamp on the row itself). Neither market_regimes nor
-- feature_vectors nor instrument_tags carries a column suitable for a cheap watermark read.
-- The watermark component must therefore be COMPUTED per check, e.g.:
SELECT MAX(bar_ts), COUNT(*) FROM feature_vectors WHERE symbol = %s AND tf = %s;
SELECT MAX(bar_ts), COUNT(*) FROM forward_returns WHERE symbol = %s AND tf = %s;
-- market_regimes for cross-sectional cells: keyed by regime_group, not symbol
SELECT MAX(ts), COUNT(*) FROM market_regimes WHERE regime_group = %s AND tf = %s;
-- feature_registry status per feature (affects feature_status_at_eval column):
SELECT feature_name, status FROM feature_registry ORDER BY feature_name;
```
This is a real cost the fingerprint validity check pays on every run (a handful of aggregate
queries per symbol×tf, not per feature) — worth sizing against the design's success criterion 1
(no-op re-run <30min) during planning, though it is orders of magnitude cheaper than the compute
it's gating.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `existing_keys` set, code-blind, per-feature-key skip only | Fingerprint-gated skip at the whole-cell level, before `worker_args` construction | This phase (162-03) | Skips the entire fetch+compute, not just the final insert — the actual throughput win |
| `.pkl` checkpoint dir, keyed by `_checkpoint_content_key()`, intra-run crash-resume only | Candidate for deletion once cross-run fingerprinting supersedes its purpose (risk #4) | This phase, pending an explicit decision | Removes a second, overlapping "is this cell already done" mechanism — Musk step 2 (delete before optimize) |
| `_compute_symbol_tf`'s per-scale loop: inline in a single 616-line function | Extracted to `_compute_one_regime_cell` (328 lines), callable per-pass | 2026-07-21, commits `0e38bf8e`/`2f5334f2` (unrelated symbol_hmm restoration work, Task 1) | Half of todo 139's dedup work already landed as a side effect; 162-01 should build on it, not redo it |
| `cross_sectional_bootstrap_threads`: single scalar APR key | Should become a per-tf dict (todo 133), matching `bootstrap_block_size`'s existing 4-flat-key pattern | Not yet done — this phase's 162-01 scope | Avoids paying 6-thread dispatch overhead on 15m/1h/1d cells that finish in minutes serially |

**Deprecated/outdated:** The 2026-07-18/19 design's literal line-number citations (existing_keys
skip at "3128-3140", inline loops at "~1119, ~1396, ~1979") are all stale — the file grew from
~3,600 to 3,928 lines and was restructured between when the design was written and today. Use
this research's line numbers (verified live 2026-07-21) instead when the plan cites specific
locations.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|----------------|
| A1 | `ic_cell_fingerprints` should NOT be a TimescaleDB hypertable | Code Examples | Low — row count is bounded (symbols × tfs × pass_types × windows, same order as `feature_registry`'s ~150 rows), matching `feature_ic_scores`'s own non-hypertable precedent; if corpus scales to 1000+ symbols with frequent re-windowing this could need revisiting, but that's explicitly out of scope per risk #6 (no scheduler/cadence this phase) |
| A2 | DELETE-then-insert (not upsert) is the right fix for Pitfall 1 | Common Pitfalls, Pattern list | Low-medium — this is a recommendation based on minimizing blast radius to existing tests/docstrings, not a locked decision from CONTEXT.md (none exists for this phase); the planner should confirm this tradeoff explicitly rather than treating it as settled, since an upsert is also a valid, arguably simpler design if the test/docstring updates are considered acceptable churn |
| A3 | `pass_type` CHECK values (`'pooled'`, `'symbol_hmm'`, `'cross_sectional'`) match `_resolve_regime_scope`'s existing vocabulary exactly | Code Examples | Low — verified `_resolve_regime_scope` exists at `ic_engine.py:210-239` and is the canonical 3-value source, but this research did not re-print its exact string literals; confirm the 3 exact strings during implementation rather than trusting this table verbatim |

## Open Questions

1. **Should the fingerprint's upstream watermark be a row count, a MAX(timestamp), or a content
   hash?**
   - What we know: no source table (`feature_vectors`, `forward_returns`, `market_regimes`,
     `instrument_tags`) carries an `updated_at` column, so the watermark must be computed, not
     read.
   - What's unclear: a `MAX(bar_ts)` is cheap but blind to a corrective UPDATE that doesn't add
     new rows (e.g. the `price_sanity_status` corrections referenced in project memory — a
     `KRE`/`VWO`/`DIA` recompute that fixes existing rows in place wouldn't move `MAX(bar_ts)`).
     A row count catches inserts/deletes but not in-place corrections either. A full content
     hash over the relevant row set is the only option that catches everything but is far more
     expensive to compute per symbol×tf on every run.
   - Recommendation: given this project's own recent history (`price_sanity_status` corrections
     that mutate rows in place without changing row count or `MAX(bar_ts)`), lean toward
     including a cheap content-ish signal (e.g. a hash of `COUNT(*) FILTER (WHERE
     price_sanity_status != 'clean')` alongside `MAX(bar_ts)`/`COUNT(*)`) rather than trusting
     `MAX(bar_ts)`/`COUNT(*)` alone — but this needs an explicit decision during
     planning/discuss-phase, not a silent choice, since getting it wrong reproduces exactly the
     "silent stale IC" failure class risk #3 warns about.

2. **Does `--refresh` force-recompute everything, or force-recompute cells whose fingerprint
   check the operator distrusts?**
   - What we know: the design's success criteria treat `--refresh` and the fingerprint-skip path
     as two distinct, comparable code paths (162-04's equivalence harness runs both and asserts
     identical output).
   - What's unclear: whether `--refresh` should bypass the fingerprint check entirely (force
     100% recompute, existing `--cross-sectional-only`-style blunt flag) or narrow to specific
     symbols/cells via the existing `--symbols`/`--tf` args combined with the fingerprint check
     disabled just for those.
   - Recommendation: blunt full-bypass is simpler and matches the existing CLI flag style
     (`--cross-sectional-only` is also all-or-nothing); combine with `--symbols`/`--tf` for
     scoping rather than adding new cell-selection syntax.

## Environment Availability

Not applicable — this phase has no new external dependencies (no new services, tools, or
runtimes). All required infrastructure (PostgreSQL/TimescaleDB, the existing Python
environment, `ProcessPoolExecutor`) is already in continuous production use by this exact file.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 6.0+ (`pytest.ini`, `testpaths = tests`, `python_files = test_*.py`) |
| Config file | `pytest.ini` (repo root) |
| Quick run command | `.venv/bin/pytest tests/unit/test_ic_engine_compute_split.py tests/unit/test_ic_engine_idempotency.py tests/unit/test_ic_engine_incremental_write.py -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements -> Test Map
No locked requirement IDs exist for this phase (predates formal REQUIREMENTS.md IDs — confirmed
no `.planning/REQUIREMENTS.md` exists in this project at all). Mapping is against the phase
description's own success criteria instead:

| Criterion | Behavior | Test Type | Automated Command | File Exists? |
|-----------|----------|-----------|---------------------|--------------|
| 162-01 structural equivalence | `_compute_one_regime_cell`/extracted cross-sectional fn produce bit-identical rows pre/post refactor | unit (regression fixture, extends `be74f4a1`'s existing methodology) | `pytest tests/unit/test_ic_engine_compute_split.py -x` | Partial — file exists, needs new cross-sectional-extraction cases |
| Todo 139/140 memory-bounded rank/CI | feature-blocked output bit-identical to unblocked | unit | `pytest tests/unit/test_ic_engine_compute_split.py::test_cross_sectional_rankdata_output_is_float32_not_float64 -x` (extend, don't replace) | Partial |
| `build_walk_forward_folds` extraction | boundary math matches all 4 existing inline call sites | unit (NEW) | `pytest tests/unit/test_ic_math_walk_forward_folds.py -x` | Wave 0 gap |
| `short_lived_conn(dsn)` extraction | 3 dsn call sites use the new helper; exception mid-fetch still closes conn | unit (NEW) | `pytest tests/unit/test_batch_utils_short_lived_conn.py -x` | Wave 0 gap |
| Todo 133 per-tf bootstrap threads | `ICEngineConfig.from_apr()` assembles a dict from 4 flat per-tf keys | unit | extend `tests/unit/test_ic_engine_parallelism.py` | Partial |
| 162-03 fingerprint skip/invalidate | matching fingerprint skips; mismatched fingerprint DELETEs+recomputes; unclassified APR field crashes loud | unit (NEW) | `pytest tests/unit/test_ic_engine_fingerprint.py -x` | Wave 0 gap |
| 162-03 idempotency preserved | `test_ic_engine_idempotency.py`'s existing `DO NOTHING` assertions still pass unchanged | unit (existing, must NOT need editing per Pitfall 1's recommended design) | `pytest tests/unit/test_ic_engine_idempotency.py -x` | Exists |
| BH-FDR family coherence (risk #2) | `_backfill_bh_fdr` still scoped to full `training_window_end`, unconditional on skip count | unit (existing) | `pytest tests/unit/test_ic_engine_incremental_write.py -x` | Exists |
| 162-04 equivalence harness | fresh-compute vs fingerprint-skip on ~5 symbols produce identical `feature_ic_scores` | integration (NEW, DB-backed) | manual/ops script, not a `pytest tests/unit/` case — needs a live corpus subset | Wave 0 gap (this is explicitly an ops-script-level check per the design, not a unit test) |

### Sampling Rate
- **Per task commit:** the quick-run command above (targeted files only, <30s)
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q` (full suite)
- **Phase gate:** full suite green before `/gsd:verify-work`; 162-04's equivalence harness run
  separately (real DB, ~5 symbols) before the phase is declared done, since it cannot run inside
  the unit-test sandbox

### Wave 0 Gaps
- [ ] `tests/unit/test_ic_math_walk_forward_folds.py` — covers `build_walk_forward_folds`
      against all 4 existing inline call sites' expected boundary values
- [ ] `tests/unit/test_batch_utils_short_lived_conn.py` — covers the new dsn-based
      `short_lived_conn` context manager, including the exception-mid-fetch-still-closes case
      the 3 existing hand-rolled sites fail today
- [ ] `tests/unit/test_ic_engine_fingerprint.py` — covers the fingerprint validity check (match/
      mismatch/unclassified-field-crashes-loud), the DELETE-then-insert invalidation path, and
      that `existing_keys`'s replacement still integrates correctly with `worker_args`
      construction
- [ ] Framework install: none — pytest and all dependencies already present

## Security Domain

Not applicable in the ASVS web-app sense — this is an internal batch measurement service with
no HTTP surface, no user input, no authentication boundary. The one security-adjacent property
worth naming: the fingerprint's "silent wrong answer" risk (risk #3 in the phase description) is
this project's own analogue of ASVS's "fail loud, not silent" principle (already codified in
CLAUDE.md's north-star: "Silent wrong answers are worse than loud crashes"). No ASVS category
table is included since none apply.

## Sources

### Primary (HIGH confidence — direct reads of live `main`, this session, 2026-07-21)
- `services/ic_engine.py` (3,928 lines, full read of relevant sections: imports, `_short_lived_conn`,
  `_assert_prerequisites`, `_compute_one_regime_cell`, `_compute_symbol_tf`,
  `_compute_cross_sectional_tf`, `_checkpoint_content_key`, `_write_ic_results`/
  `_write_symbol_results`/`_write_cs_cell_results`, `main()`'s `existing_keys`/`worker_args`
  construction, CLI `add_argument` block)
- `services/_batch_utils.py` (full read: `connect_db_from_url`, `load_config_service_sync`,
  `Float32ChunkAccumulator`)
- `src/intelligence/statistics/ic_math.py` (function inventory + module docstring)
- `src/core/agent/base_batch.py` (`content_key` staticmethod)
- `services/ensemble_ic_engine.py` (walk-forward fold copy at line 818, for the 4th-copy claim)
- `production/migrations/156_ic_engine_tables.sql`, `169_feature_registry.sql`,
  `171_market_regimes.sql`, `225_concept_registry_mvp.sql`, `157_alpha_ic_apr_keys.sql`,
  `173_ic_sharpe_hac.sql` (schema/index/APR-key conventions)
- `tests/unit/test_ic_engine_idempotency.py`, `test_ic_engine_compute_split.py`,
  `test_ic_engine_incremental_write.py` (existing test contract, DO NOTHING assertions)
- `git log`/`git show` on commits `2f5334f2`, `0e38bf8e` (Task 1 extraction, confirmed merged
  to `main`)
- `.planning/todos/deferred/{129,133,134,139,140}-*.md`, `.planning/todos/completed/122-*.md`
  (deferred-todo source text, cross-checked against live code)
- `.planning/STATE.md`, `docs/superpowers/plans/2026-07-21-restore-symbol-hmm-ic-measurement-for-routed-symbols.md`
  (migration 247 reservation, confirmed via grep — not yet executed)
- `pytest.ini`, `ls production/migrations/` (test framework config, next-free-migration-number check)

### Secondary (MEDIUM confidence)
None — no WebSearch/WebFetch was needed for this phase; it is entirely internal, first-party
code with no external library surface to verify against Context7/official docs.

### Tertiary (LOW confidence)
None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, all reused code read directly
- Architecture: HIGH — data flow diagram traced through live function bodies, not inferred
- Pitfalls: HIGH — all 4 pitfalls confirmed against live line numbers and existing test assertions
- Fingerprint schema (Code Examples): MEDIUM — the table shape follows verified live
  conventions, but the exact column set is this research's own synthesis of the design doc's
  requirements against those conventions, not itself a locked/verified artifact; the planner
  should treat the CREATE TABLE statement as a strong starting draft, not gospel

**Research date:** 2026-07-21
**Valid until:** ~14 days (this file is under active, fast-moving development — a 2-3 day gap
already invalidated the prior design's line numbers once this session; re-verify line numbers
and function boundaries against `main` before planning if more than a few days elapse, especially
if Task 2-5 of the symbol_hmm restoration work lands on `main` in the meantime, since that touches
the same functions this phase's plans will touch)
