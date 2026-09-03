---
phase: 142A-ensemble-ic-measurement
reviewed: 2026-07-02T00:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - production/migrations/195_alpha_ensemble_ic.sql
  - scripts/ops/alpha/ops_ensemble_ic_diagnosis.py
  - scripts/ops/alpha/ops_ensemble_ic_gate.py
  - services/ensemble_ic_engine.py
  - services/service_auditor.py
  - tests/unit/test_ensemble_ic_bh_fdr.py
  - tests/unit/test_ensemble_ic_config.py
  - tests/unit/test_ensemble_ic_decay.py
  - tests/unit/test_ensemble_ic_executable_returns.py
  - tests/unit/test_ensemble_ic_gate.py
  - tests/unit/test_ensemble_ic_idempotency.py
  - tests/unit/test_ensemble_ic_math.py
  - tests/unit/test_ensemble_ic_wf_stability.py
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
status: issues_found
resolution: CR-01, CR-02, WR-01, WR-03 fixed in commit 5baf4cf1 (2026-07-02).
  WR-02 (pooled cross-sectional measurement gap) is a real capability gap, not a
  quick fix -- captured as todo 046. IN-01/IN-02 left as-is per review (no action
  required / minor readability, not correctness).
---

# Phase 142A: Code Review Report

**Reviewed:** 2026-07-02
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Reviewed the EIC-01 through EIC-05 implementation: the `alpha_ensemble_ic` migration
(195), `EnsembleICEngine` batch service, the EIC-04 phase gate, the EIC-05 diagnosis
report, and the `service_auditor.py` DAG registration. The IC math itself (Fisher-z CI,
corpus-level BH-FDR, walk-forward fold construction) correctly composes the existing
`ic_engine.py` primitives and the unit test suite exercises the pure-function surface
(`_select_hold_bars_from_decay`, `compute_walk_forward_stable`, `_evaluate_gate`,
`EnsembleICConfig.from_apr`, `build_ensemble_ic_row`) thoroughly and correctly.

Two BLOCKER-level issues were found. First, `EnsembleICEngine._execute_inner` reads
`alpha.validation.oos_start` from `config_state` and uses it directly in a
`bar_ts < $1` filter with no null/empty-string guard — unlike `ic_engine.py`, which
deliberately requires this value via a mandatory `--training-window-end` CLI flag
specifically because Phase 141.1 (CR-01) already identified that a missing/empty OOS
boundary silently corrupts measurement scope. `ensemble_ic_engine.py` reintroduces
exactly that class of bug: if the key is absent (`NULL` in Postgres) the row filter
silently returns zero rows for every symbol (no crash, no data, no error — the run
"succeeds" with an empty measurement), and if the key still holds the pre-142A
empty-string seed default (`''`) from migration 182, the `::timestamptz` cast will
raise deep inside an unguarded `fetchval`, which is a crash-loud path but is not
covered by `_assert_prerequisites`'s documented "Three COUNT checks" and not the crash
message an operator would expect. Second, the EIC-04 gate SQL's `total` CTE computes
`n_total` across ALL lookahead scales while `qualifying` filters to a single
`gate_lookahead`, inflating the denominator whenever any `(symbol, tf, regime)` cell
has a row at a non-gate lookahead but not at the gate lookahead (e.g., filtered out by
`min_reliable_n` at only one scale) — this can produce a false gate FAIL that the
`_evaluate_gate` unit tests cannot catch because they only test the pure fraction math,
never the SQL that produces the inputs.

Additionally, a design gap: `alpha_events` (written by `alpha_publisher.py`) only ever
contains real ticker symbols, never `symbol = 'POOLED'`, so `EnsembleICEngine` never
actually produces a cross-sectional pooled row despite the migration's CHECK
constraint, the `is_pooled` field, and the diagnosis script's entire "pooled vs
per-symbol IC gap" section (EIC-05 Section 2) being built around that distinction.
This isn't flagged as a BLOCKER because nothing crashes — `is_pooled` is simply always
`False` and Section 2 of the diagnosis report is permanently a no-op — but it means a
documented measurement capability doesn't exist yet.

## Critical Issues

### CR-01: `alpha.validation.oos_start` used unguarded — silent empty-result or opaque crash

**File:** `services/ensemble_ic_engine.py:597-625`
**Issue:** `oos_start` is fetched from `config_state` with no null check and passed
directly into two `WHERE bar_ts < $1` filters (`symbols_rows` query and the per-symbol
`alpha_events JOIN forward_returns JOIN market_regimes` query). `config_state`'s
`alpha.validation.oos_start` key is seeded as an empty string (`''`) by migration 182
before Phase P1-T1.5 sets a real value (see `production/migrations/182_equity_regime_model_apr.sql:25,40`).
Two failure modes exist and neither is handled:
1. If the key row doesn't exist at all, `fetchval` returns Python `None`. Postgres
   `bar_ts < NULL` evaluates to `NULL` (never true) for every row, so
   `symbols_rows` comes back empty and the entire run "succeeds" having measured
   nothing — a silent, non-crashing data-integrity failure, which is exactly the class
   of bug `ic_engine.py`'s docstring explicitly calls out and defends against via a
   mandatory `--training-window-end` CLI argument (`services/ic_engine.py:1932-1940`,
   citing Phase 141.1 CR-01).
2. If the key still holds the `''` seed default, `config_value::timestamptz` inside the
   SQL raises a Postgres cast error, which propagates as an unhandled exception from
   `conn.fetchval` — not one of the three documented "Three COUNT checks" in
   `_assert_prerequisites` (`services/ensemble_ic_engine.py:389-420`), so the crash
   message an operator sees will be a raw asyncpg/Postgres error, not the intended
   crash-loud startup gate.

The class of bug (silently-consumed OOS boundary) was already identified and fixed
once in this codebase (Phase 141.1); this migration reintroduces it in a sibling file.

**Fix:**
```python
oos_start = await conn.fetchval(
    "SELECT config_value::timestamptz FROM config_state "
    "WHERE config_key = 'alpha.validation.oos_start'"
)
if oos_start is None:
    raise RuntimeError(
        "EnsembleICEngine startup gate FAILED: alpha.validation.oos_start is not set "
        "in config_state (or is not a valid timestamp). A missing/invalid OOS boundary "
        "would silently exclude all rows from measurement (bar_ts < NULL never matches) "
        "or crash on cast -- see Phase 141.1 CR-01. Set the key via "
        "ConfigService before running this engine."
    )
```
Add this to `_assert_prerequisites` (or immediately after the fetch) so it fails with
the same clear, documented crash-loud pattern as the other three gates, rather than an
opaque cast error or a silent zero-row run.

### CR-02: EIC-04 gate denominator not scoped to `gate_lookahead` — inflated `n_total` can produce false FAIL

**File:** `scripts/ops/alpha/ops_ensemble_ic_gate.py:37-53`
**Issue:** The `qualifying` CTE filters `WHERE lookahead = $1` (the APR
`gate_lookahead`, e.g. `'fast'`), but the `total` CTE has no `lookahead` filter at all —
it counts `COUNT(DISTINCT (symbol, tf, regime))` across every row at the latest
`scored_at`, i.e. across all 4 lookahead scales combined. A `(symbol, tf, regime)`
triple is only guaranteed to produce one row per scale when `n_valid >= min_reliable_n`
holds at that scale (`services/ensemble_ic_engine.py:475-476`); it is entirely possible
for a triple to qualify (have a row) at `mid`/`slow`/`extended` but be filtered out
(no row at all) at `fast` due to a tighter stride/sample-size constraint at the shortest
horizon. Any such triple inflates `n_total` without any possibility of appearing in
`qualifying`, silently lowering the computed `fraction` and potentially flipping a
genuine PASS into a reported FAIL. The `_evaluate_gate` unit tests
(`tests/unit/test_ensemble_ic_gate.py`) only test the pure `n_qualifying / n_total`
arithmetic with hand-supplied integers — they cannot catch this SQL scoping bug because
the SQL itself is never exercised by any test in this PR.

**Fix:**
```sql
total AS (
    SELECT COUNT(DISTINCT (symbol, tf, regime)) AS n_total FROM alpha_ensemble_ic
    WHERE lookahead = $1
      AND scored_at = (SELECT ts FROM latest)
)
```
Scope `total` to the same `lookahead = $1` filter as `qualifying` so both sides of the
fraction are measuring the same cell population. Add a regression test that builds a
small in-memory/SQL fixture (or at minimum documents this invariant) so a future SQL
edit can't silently re-introduce the mismatch.

## Warnings

### WR-01: EIC-05 diagnosis Section 3 "TF-specific problem" flag applies to every row, not just `5m`

**File:** `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:187-192`
**Issue:** The flag condition `if tf_qual.get("1h", 0) and not tf_qual.get("5m", 0):`
does not reference the loop variable `r` at all — it is a loop-invariant boolean that
evaluates identically on every iteration of `for r in section3_rows`. When the
condition is true, **every** TF row in the printed table (including `1h`, `1d`, and any
other TF with a nonzero qualifying count) gets stamped with the misleading message
"TF-specific problem (5m fewer independent obs per regime)", not just the `5m` row.
This directly undermines the report's stated purpose ("so an operator can immediately
tell WHY the EIC-04 gate failed without re-deriving the diagnosis by hand") by
attributing a 5m-specific problem to unrelated timeframes. Confirmed via direct
simulation: a 3-row fixture (`1h` qualifying=5, `5m` qualifying=0, `1d` qualifying=2)
produces the flag on all three rows.
**Fix:**
```python
for r in section3_rows:
    flag = ""
    if r["tf"] == "5m" and tf_qual.get("1h", 0) and not tf_qual.get("5m", 0):
        flag = "TF-specific problem (5m fewer independent obs per regime)"
    print(f"| {r['tf']} | {r['n_cells']} | {r['n_qualifying']} | {flag} |")
```

### WR-02: `alpha_ensemble_ic.is_pooled` / cross-sectional "POOLED" row is currently unreachable

**File:** `services/ensemble_ic_engine.py:452,602-605`, `production/migrations/195_alpha_ensemble_ic.sql:41,58`, `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:87-99,152-181`
**Issue:** `symbol_tf_pairs` is built exclusively from
`SELECT DISTINCT symbol, tf FROM alpha_events`, and `alpha_events` (written by
`alpha_publisher.py`) contains only real ticker symbols — confirmed against the live
DB (`SELECT DISTINCT symbol FROM alpha_events` returns tickers like AGG, AMLP, ARKK,
..., never `'POOLED'`). Since the engine never constructs or dispatches a pooled
cross-sectional alpha_score series, every row it ever writes has `is_pooled = false`,
which means: the migration's `alpha_ensemble_ic_pooled_symbol_consistent` CHECK
constraint is exercised trivially (always the `False = False` branch); the diagnosis
script's entire Section 2 ("Pooled vs per-symbol IC gap", designed to catch "REGIME
GRANULARITY ISSUE") can never populate a `pooled_ci_lower` value and its flag logic is
permanently a no-op; and `_calibrate_hold_max_bars`'s `if row.get("is_pooled"): continue`
exclusion is dead code. This is a real capability gap relative to what the migration
and diagnosis tooling document/assume, not merely a naming leftover.
**Fix:** Either (a) add a pooled cross-sectional pass to `_execute_inner` that
aggregates `alpha_score` across all symbols per (tf, regime) and dispatches one
additional `symbol='POOLED'` worker task per (tf, regime), matching the design
`feature_ic_scores`/`ensemble_trainer.py` already uses for `symbol='POOLED'` rows, or
(b) if the pooled cross-sectional ensemble measurement is deliberately deferred to a
later phase, update the migration comment, the diagnosis script's Section 2, and the
module docstring to say so explicitly rather than presenting fully-built-but-dead
machinery.

### WR-03: `min_obs_per_regime` fallback default (200) diverges from the seeded APR value (3000)

**File:** `scripts/ops/alpha/ops_ensemble_ic_diagnosis.py:29,60-71`
**Issue:** `_DEFAULT_MIN_OBS_PER_REGIME = 200` is used only when the APR key is
missing from `config_state`, but migration 195 seeds
`alpha.ensemble_ic.min_obs_per_regime = 3000`. A 15x difference between the documented
default and the actual fallback means that if the APR key is ever accidentally deleted
(vs. simply never seeded), Section 1's "DATA STARVATION" flag threshold silently drops
by 15x, masking genuinely under-powered cells. The script does print a `min_obs_warning`
in this case, which mitigates but does not eliminate the risk (an operator skimming the
table output without reading the warning banner would draw wrong conclusions).
**Fix:** Set `_DEFAULT_MIN_OBS_PER_REGIME = 3000` to match the migration 195 seed
value, so the fallback (if ever exercised) is at least consistent with the documented
APR default rather than an independently-chosen, much looser threshold.

## Info

### IN-01: Walk-forward embargo uses raw `lookahead_bars` against stride-subsampled indices (inherited from `ic_engine.py`)

**File:** `services/ensemble_ic_engine.py:468-506`
**Issue:** `embargo_bars = lookahead_bars` (raw-bar count) is used directly as an
index offset (`test_start = train_end + embargo_bars`) into `alpha_valid`/`returns_valid`,
which have already been subsampled by `stride = max(subsample_min_stride,
lookahead_bars)`. This means the effective embargo in subsampled-index space is
`lookahead_bars` *subsampled steps* wide (i.e., `lookahead_bars * stride` raw bars),
not `lookahead_bars` raw bars as the variable name implies. This is not a new bug
introduced by this diff — `ic_engine.py` does exactly the same thing at
`services/ic_engine.py:944` (`embargo_bars = lookahead_bars` against
`ranks_X_scale`, which is likewise pre-subsampled) — and `ensemble_ic_engine.py`
explicitly composes the SAME methodology by design. Flagged as info only because the
engine's own docstring calls this "scale-specific embargo" as a correctness feature;
worth a joint follow-up with `ic_engine.py` rather than a point fix here, since fixing
one without the other would break methodology parity between the two engines.
**Fix:** No action required for this PR. If addressed, fix both `ic_engine.py` and
`ensemble_ic_engine.py` together to preserve parity, and re-validate the walk-forward
stability numbers on the existing corpus since the effective embargo width would
change.

### IN-02: `_load_apr` fetches the entire `alpha.*` namespace, not just the keys this engine needs

**File:** `services/ensemble_ic_engine.py:90-93`
**Issue:** `_APR_QUERY` uses `WHERE config_key LIKE 'alpha.%' OR config_key LIKE
'infra.ensemble_ic_engine.%'`, which pulls in unrelated keys (`alpha.frame.*`,
`alpha.regime.*`, `alpha.validation.*`, per-feature `alpha.ic.*` keys not consumed by
`EnsembleICConfig.from_apr`) into the in-memory dict, all of which are silently
discarded. Not a bug (out of scope per CLAUDE.md performance exclusion), but worth
tightening for readability/maintainability — a future APR key added under `alpha.*`
for an unrelated concern will be loaded here without anyone noticing, and the actual
consumed-key set is only discoverable by reading `EnsembleICConfig.from_apr`.
**Fix:** Consider scoping the query to `config_key LIKE 'alpha.ensemble_ic.%' OR
config_key LIKE 'alpha.ic.%' OR config_key LIKE 'infra.ensemble_ic_engine.%'` to match
exactly the prefixes `from_apr` actually reads.

---

_Reviewed: 2026-07-02_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
