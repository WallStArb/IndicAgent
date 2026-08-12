# IC Scale-Handling Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out the three remaining `_SCALES`-hardcoding follow-ups (todos 209/210/211) from
the 2026-07-30 per-tf active-scale-set work — one real measurement-integrity fix
(`ensemble_ic_engine.py`'s worker loop) and three mechanical migrations to the
`active_scales_for(tf)` resolver pattern that file's 12 call sites already use.

**Architecture:** No new files, no new tables, no APR keys. Each task is a scoped edit to an
existing service or ops script, following the `active_scales_for(tf)` resolver pattern already
proven in `services/ic_engine.py` (12 call sites migrated 2026-07-30) and the `complete_{scale}`
masking pattern already proven in `scripts/ops/alpha/ops_ensemble_ablation.py`'s
`apply_complete_gate` — do not invent a new masking approach, reuse this one.

**Tech Stack:** Python 3.14, `psycopg2`/`asyncpg` (file-dependent), `numpy`, pytest.

## Global Constraints

- Gate: Task 1 (the real integrity fix) can be fully unit-tested without live data (mock-fetch
  tests, same pattern `test_ic_engine_active_scales_boundary.py` uses), but its live-data
  verification step (confirming `ensemble_alpha`'s next real run excludes session-crossing
  returns) is blocked until the in-flight corpus rebuild (`forward_return_writer` → `ic_engine`
  → `ensemble_trainer`, started 2026-07-30 ~12:39pm) reaches `ensemble_alpha`. Do not skip the
  live-data check once available — the whole point of this fix is a live-DB-observed defect.
- Tasks 2-4 are pure mechanical migrations (swap a flat `_SCALES` import for
  `config.active_scales_for(tf)` / a locally-loaded equivalent) — no design judgment required,
  do not over-engineer beyond matching the existing pattern.
- `services/ic_engine.py`'s `_SCALES` constant must NOT be deleted until Tasks 2 and 4 (the two
  files that still import it directly) are both done — see `services/ic_engine.py:175`'s
  comment. Re-check with `grep -rn "_SCALES\b" scripts/ src/` after each task; don't delete until
  it's genuinely zero external references.
- Run the full `tests/unit/` suite after every task, not just the new/changed test file — this
  cluster has already produced one cross-file ripple today (the session-gate removal touched
  4 unrelated test files' hardcoded assertions).

---

### Task 1: `ensemble_ic_engine.py`'s `_run_ensemble_ic_worker` — wire `complete_{scale}` masking + `active_scales_for(tf)` (todo 210, P1)

**Files:**
- Edit: `services/ensemble_ic_engine.py`
- Test: `tests/unit/test_ensemble_ic_worker_fetch.py` (existing file — add to it)

**Problem recap:** `_WORKER_FETCH_SQL`/`_POOLED_WORKER_FETCH_SQL` (lines ~687-738) never select
`complete_{scale}` at all — only `return_{scale}` (masked on the unrelated `return_{scale}_suspect`
price-sanity flag). `_run_ensemble_ic_worker`'s per-scale loop (line ~959: `for scale in _SCALES:`)
never checks completeness and never resolves the tf's active scale set. Net effect: once
`ensemble_alpha` is repopulated, this worker will compute real `alpha_ensemble_ic` rows from
returns whose forward window may not actually exist as a valid observation, and will waste
compute attempting scales a tf has excluded.

**Reference implementation, already correct, in this same codebase:**
`scripts/ops/alpha/ops_ensemble_ablation.py` — its fetch SQL (line 365) already selects
`complete_{scale}`, and `apply_complete_gate()` (line 170) already does the masking correctly:
`out[~complete] = np.nan`, so a censored per-symbol return can never enter a pooled mean or an
IC computation. Reuse this exact function (import it, or lift its 4-line body into
`ensemble_ic_engine.py` if importing from a `scripts/` module is against this codebase's layering
— check whether `scripts/` importing into `services/` or vice versa is already a pattern here
before deciding which direction).

**Two distinct fetch paths need the fix, not just one:**

1. **Non-pooled** (`_WORKER_FETCH_SQL`, line ~927 `cur.execute(_WORKER_FETCH_SQL, ...)` →
   `fetched = cur.fetchall()`): straightforward — add `complete_{scale}` columns to the SELECT,
   then in the `returns_by_scale` construction (line ~941-944), apply the same masking
   `ops_ensemble_ablation.py` uses before the per-scale loop consumes it.

2. **Pooled** (`_POOLED_WORKER_FETCH_SQL` → `_aggregate_pooled_series`, line ~768): this path is
   NOT a straightforward copy of (1). `_aggregate_pooled_series` averages raw per-symbol rows
   into one pooled row per `(tf, regime, bar_ts)` cell via `_RunningMean` (a running sum/count)
   BEFORE any IC math runs. `complete_{scale}` is a boolean — you cannot average a boolean
   across symbols and get a meaningful mask (a 0.6 "mostly complete" value has no defined
   meaning). The correct fix masks the return to NaN (`apply_complete_gate`'s pattern) for a
   given raw row BEFORE it enters `_RunningMean.add()` — i.e., inside `_aggregate_pooled_series`'s
   per-row loop, not after aggregation. Confirm `_RunningMean`/the pooling loop already skips
   NaN values (check `_POOLED_VALUE_COLS` usage and the `if value is not None` skip mentioned in
   the module's existing comments) — if so, NaN-ing an incomplete value pre-aggregation is
   sufficient and requires no further change to the averaging logic itself.

3. Replace `for scale in _SCALES:` (line ~959) with `for scale in config.active_scales_for(tf):`
   — `config`/`tf` are both already in scope at this call site.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ensemble_ic_worker_fetch.py (add to existing file)

def test_worker_fetch_sql_selects_complete_columns():
    """_WORKER_FETCH_SQL and _POOLED_WORKER_FETCH_SQL must both select complete_{scale}
    for every scale -- todo 210, the gap that let session-crossing returns through
    uncaught."""
    for scale in ("fast", "mid", "slow", "extended"):
        assert f"complete_{scale}" in _WORKER_FETCH_SQL
        assert f"complete_{scale}" in _POOLED_WORKER_FETCH_SQL


def test_non_pooled_worker_masks_incomplete_returns():
    """A row with complete_fast=False must not contribute a real return_fast value
    to returns_by_scale -- it must read as NaN, same as apply_complete_gate's
    contract in ops_ensemble_ablation.py."""
    # Construct fetched rows via the existing _FakeCursor/_FakeConn fixtures this
    # test file already uses (check the file's existing fixtures before adding new
    # ones), one row with complete_fast=True, real return_fast, one with
    # complete_fast=False, real (but should-be-masked) return_fast.
    # ... assert the masked row's contribution to returns_by_scale["fast"] is NaN.


def test_pooled_worker_masks_incomplete_before_averaging():
    """An incomplete row must be excluded from the pooled cross-symbol mean, not
    just flagged after the fact -- averaging-then-masking would already have
    contaminated the mean. Construct 2 symbols at the same (tf, regime, bar_ts):
    one complete, one incomplete. The pooled result must equal the complete
    symbol's raw value alone, not an average of both."""
    # ...


def test_worker_loop_resolves_active_scales_for_tf():
    """The per-scale loop must call config.active_scales_for(tf), not iterate the
    flat module-level _SCALES tuple -- construct an EnsembleICConfig where
    active_scales_for('1h') excludes 'slow'/'extended' and assert the worker never
    attempts IC computation for those scales at 1h (mock/spy on the per-scale
    compute call, or assert no result row exists for the excluded scale)."""
    # ...
```

- [ ] **Step 2: Implement the fix** — SQL column additions, masking (both paths, respecting
  the pooled-path pre-aggregation ordering above), and the `active_scales_for(tf)` loop swap.

- [ ] **Step 3: Run this file's tests, then the full suite**

```bash
.venv/bin/pytest tests/unit/test_ensemble_ic_worker_fetch.py -v
.venv/bin/pytest tests/unit/ -q
```

- [ ] **Step 4 (gated on corpus rebuild reaching `ensemble_alpha`):** once
  `ensemble_trainer`/`ensemble_alpha` has real post-rebuild rows, run this worker against live
  data and confirm no `alpha_ensemble_ic` row is computed from a `complete_{scale}=false` input
  — spot-check via a direct query joining `alpha_ensemble_ic` back to `forward_returns` on the
  scale's lookahead, or add a one-off assertion script if no existing tool covers this.

---

### Task 2: `ops_vol_normalized_target_ab.py` — migrate off flat `_SCALES` (todo 209, P2) — DONE 2026-07-30

**Files:**
- Edit: `scripts/ops/alpha/ops_vol_normalized_target_ab.py`
- Test: `tests/unit/scripts/test_ops_vol_normalized_target_ab.py` if it exists, else add inline
  coverage matching this file's existing test conventions (check `tests/unit/scripts/` first).

**Call sites to fix** (from `.planning/todos/pending/209-ops-vol-normalized-target-ab-scales.md`):
line 85 (`from services.ic_engine import ..., _SCALES`), lines 192-193 (return/complete column
lists), line 204 (`n_scales = len(_SCALES)`), line 224 (`for j, scale in enumerate(_SCALES)`),
line 332 (`for scale_idx, scale in enumerate(_SCALES)`).

- [ ] **Step 1:** confirm whether this script already has an `ICEngineConfig`/`ConfigService`
  instance in scope at each call site, or (like `ops_vol_normalized_target_ab.py`'s sibling
  scripts) reads `config_state` directly via bespoke helpers. Match whichever pattern is
  already idiomatic in this file — do not introduce a new config-loading style.
- [ ] **Step 2:** replace the `_SCALES` import and all 5 call sites with the resolved per-tf
  active-scale tuple (`ICEngineConfig.active_scales_for(tf)` if a config instance is available,
  else `services._batch_utils.canonicalize_active_scales(...)` over the loaded APR value —
  match `ICEngineConfig.from_apr`'s exact resolution logic, do not re-derive it independently).
- [ ] **Step 3:** run this script's existing tests (if any) plus a dry-run against a small
  `--max-regimes-per-tf` scope once live data exists, confirming no behavior change for tfs
  where all 4 scales remain active (5m/15m/1d as of today) and correct scale exclusion for any
  tf where `active_scales_for` differs from the full set.
- [ ] **Step 4:** `.venv/bin/pytest tests/unit/ -q`

---

### Task 3: `ops_ensemble_ablation.py` — migrate off flat `_SCALES` (todo 211, part 1 of 2, P2)

**Files:**
- Edit: `scripts/ops/alpha/ops_ensemble_ablation.py`

**Scope note:** this script's `complete_{scale}` handling (line 365, `apply_complete_gate` at
line 170) is ALREADY CORRECT — it is in fact the reference pattern Task 1 above reuses. This
task is scale-set resolution only, not a completeness fix.

**Call sites to fix:** line 80 (`from services.ensemble_ic_engine import _SCALE_RETURN_COLUMNS,
_SCALES`), line 363 (return column list), line 365 (complete column list), line 442, line 562,
line 1098 (all `for scale in _SCALES:` loops).

- [ ] **Step 1:** replace `_SCALES` import with `EnsembleICConfig.active_scales_for(tf)`
  (or the equivalent resolution this script already uses for its config — check whether it
  already instantiates `EnsembleICConfig` before this fix).
- [ ] **Step 2:** update all 6 call sites to iterate the resolved per-tf tuple.
- [ ] **Step 3:** `.venv/bin/pytest tests/unit/ -q` — this script's ablation logic is
  numerically sensitive (it's an ablation study), so also manually diff a small dry-run's
  output before/after for a tf where the active set is unchanged (should be byte-identical)
  and confirm no crash for any tf.

---

### Task 4: `ops_interaction_primitives_pilot.py` — migrate off flat `_SCALES` AND fix the stale global lookahead key (todo 211, part 2 of 2, P2)

**Files:**
- Edit: `scripts/ops/alpha/ops_interaction_primitives_pilot.py`

**Two independent bugs in one file, from `.planning/todos/pending/211-ops-scripts-stale-scales.md`:**

1. Own local `_SCALES = ("fast", "mid", "slow", "extended")` (line 54) — same fix as Tasks 2/3.
2. `_LOOKAHEAD_KEYS = tuple(f"alpha.ic.lookahead.{scale}" for scale in _SCALES)` (line 56) reads
   the pre-todo-146 GLOBAL key shape (`alpha.ic.lookahead.{scale}`, no `{tf}` component), which
   **no longer exists in `config_state`** — todo 146 (2026-07-29) replaced it with the per-tf
   `alpha.ic.lookahead.{tf}.{scale}` keys. Line 93's `config.get(f"alpha.ic.lookahead.{scale}")`
   is reading a dead key today; whatever this script currently does with a missing/None config
   value (silent fallback default, or a crash) needs to be identified and fixed independently of
   the `_SCALES` migration — this is NOT caused by today's active-scale-set work, just newly
   found by its review sweep.

- [ ] **Step 1:** run the script today (or trace the `config.get()` call path statically if a
  live run isn't practical) to determine what actually happens right now with the dead key —
  document the current (buggy) behavior before fixing it, so the fix's before/after is provable.
- [ ] **Step 2:** fix the lookahead key to the real per-tf shape
  (`alpha.ic.lookahead.{tf}.{scale}`), matching `ICEngineConfig.from_apr`'s resolution.
- [ ] **Step 3:** fix `_SCALES` the same way as Tasks 2/3 (`active_scales_for(tf)`).
- [ ] **Step 4:** `.venv/bin/pytest tests/unit/ -q`, plus confirm `grep -rn "_SCALES\b"
  scripts/ src/` no longer shows any of the 3 scripts fixed in Tasks 2-4 — at that point decide
  whether `services/ic_engine.py`'s module-level `_SCALES` constant (kept alive solely for these
  3 scripts, per its own comment at line ~175) can finally be deleted.

---

### Task 5: Close out todos

- [ ] Move `209-ops-vol-normalized-target-ab-scales.md`,
  `210-ensemble-ic-worker-scales.md`, `211-ops-scripts-stale-scales.md` from
  `.planning/todos/pending/` to `.planning/todos/completed/`, each with a completion note citing
  the commit(s) that fixed them (matching this project's existing todo-closure convention — see
  `.planning/todos/completed/212-corpus-manifest-verifier-empty-list.md` for the pattern just
  used today).
- [ ] Update `.planning/todos/PRIORITIES.md` to remove the now-closed rows from their P1/P2
  sections.
- [ ] If `services/ic_engine.py`'s `_SCALES` constant was deleted in Task 4, note that in the
  commit message and re-check `docs/superpowers/plans/2026-07-30-per-tf-active-scale-set.md`
  for any stale reference to it still being "kept alive" (it isn't a canonical doc per this
  project's convention, but worth a quick grep so it doesn't mislead a future reader).
