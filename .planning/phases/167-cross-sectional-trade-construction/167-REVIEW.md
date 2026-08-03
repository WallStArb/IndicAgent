---
phase: 167-cross-sectional-trade-construction
reviewed: 2026-07-27T12:08:08Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - docs/foundation/glossary.md
  - docs/operations/operations-infrastructure.md
  - docs/reference/cheatsheet.md
  - docs/research/data-edge-source-thesis.md
  - docs/research/trade-construction-layer.md
  - production/migrations/260_construction_spreads_schema.sql
  - scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh
  - services/cross_sectional_spread_tracker.py
  - tests/integration/test_construction_spreads_schema.py
  - tests/integration/test_cross_sectional_spread_tracker.py
  - tests/unit/test_cross_sectional_spread_tracker.py
findings:
  critical: 1
  warning: 5
  info: 0
  total: 6
status: issues_found
---

# Phase 167: Code Review Report

**Reviewed:** 2026-07-27T12:08:08Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

`services/cross_sectional_spread_tracker.py` is unusually well-engineered for the failure
modes it explicitly sets out to prevent (crash-recovery tail-truncation, NULL-vs-0.0 turnover
semantics, tie-break determinism, non-finite feature guards, strict-JSON verdict artifacts).
The unit and integration test suites exercise exactly the edge cases the module's own
docstrings call out (Codex HIGH concerns, Pitfall 4, design decision 9's alignment guard), and
cross-checking the arithmetic in `attribution_verdict`/`shuffled_ranking_null_p` against the
statistics did not turn up a computation error. `frame_gate_passes`/`evaluate_frame_gate` reuse
from `counterfactual_tracker.py` is verified call-compatible (argument order, group_key 2-tuple
shape, `min_clusters=None` default).

One real correctness gap survived that level of care: `CrossSectionalSpreadTracker`'s
`--backfill` mode seeds prior-leg turnover state from the globally *latest* persisted
`construction_spreads` row unconditionally, which is only valid when the table is actually
empty at invocation time (the documented, intended use of `--backfill`). Nothing in the code
enforces that precondition — see CR-01.

The remaining findings are all in the phase's documentation layer (`data-edge-source-thesis.md`,
`trade-construction-layer.md`, `glossary.md`), which this phase edited as part of its final
Plan 06 update. Spot-checking the live `logs/construction_verdicts/gate{1,2}_*.json` artifacts
against the numbers transcribed into `trade-construction-layer.md` turned up one real numeric
transcription error (WR-03) despite the doc's own claim to have verified every value before
writing it down, plus five broken/dead file-path cross-references (WR-02) and a stale `Status:`
field in the new glossary entry (WR-04). None of these affect the shipped code's behavior, but
this project treats documentation as load-bearing evidence (Validation Gate verdicts are
transcribed into research docs as the system of record), so a wrong number here is a real
defect, not a typo to wave off.

## Critical Issues

### CR-01: `--backfill` mode's prior-leg seed is only correct on an empty table, and nothing enforces that precondition

**File:** `services/cross_sectional_spread_tracker.py:854-906`
**Issue:**

`_execute_inner` resolves the panel scan's starting point from `self.backfill` (step 2), but
resolves the **prior-leg seed** for turnover computation independently, from whichever row is
currently the latest in `construction_spreads` (step 3), regardless of mode:

```python
prior_row = await conn.fetchrow(
    "SELECT bar_ts, long_leg_symbols, short_leg_symbols FROM construction_spreads "
    "WHERE construction_name = $1 AND tf = $2 ORDER BY bar_ts DESC LIMIT 1",
    _CONSTRUCTION_NAME,
    _TF,
)
```

For `mode="incremental"` this is correct: the panel scan starts strictly after the watermark,
which *is* this same latest row, so it is genuinely the immediate chronological predecessor of
the first bar about to be processed.

For `mode="backfill"`, the panel scan (`_PANEL_SQL_BACKFILL`) has no watermark and starts from
the true beginning of history. If `construction_spreads` already contains *any* rows for this
`(construction_name, tf)` at the moment `--backfill` is invoked — the module docstring and
`docs/operations/operations-infrastructure.md` both say `--backfill` is "correct only for the
first run, or immediately after a construction_spreads truncate," implying the table is assumed
empty, but nothing in the code checks or enforces this — `prior_row` returns the table's
globally *latest* bar, which for a backfill scan starting at the true beginning of history is
almost certainly unrelated in time to the first bar about to be (re)computed.

Consequence: the true earliest bar processed by this backfill run gets a fabricated, non-null
`one_way_turnover` computed against an unrelated, chronologically-later bar's leg membership,
instead of the `NULL` ("no predecessor exists") the migration's own column comment declares
load-bearing:

> `COMMENT ON COLUMN construction_spreads.one_way_turnover`: "... A NULL count greater than 1
> in this table indicates a broken incremental run (Pitfall 4: never fake this as 0.0), never a
> data property."

If that bar's row does not already exist (e.g. a newly onboarded instrument whose OHLCV/feature
history reaches further back than what has already been persisted, and an operator correctly
runs `--backfill` — not `--backfill` again for a routine re-run, which `ON CONFLICT ...
DO NOTHING` makes harmless — to pick up the new symbol's earlier bars), this fabricated value
is written and permanently corrupts that bar's `one_way_turnover` and both
`net_spread_*_by_cost_bps` columns with numbers derived from an unrelated leg composition. This
silently violates the exact "NULL vs. fabricated value" invariant this module's docstrings,
tests, and the migration comment all treat as the module's central correctness property (Pitfall
4), and it would silently distort Gate 1/Gate 2 if that corrupted row ever entered the
day-clustered bootstrap.

The existing crash-recovery integration test (`test_cross_sectional_spread_recovers_from_interrupted_run`)
does not catch this because its recovery path uses `backfill=False` (the documented, correct
recovery invocation) — it never exercises `--backfill` against a non-empty table.

**Fix:**

Seed `prior_long`/`prior_short` unconditionally as empty when `self.backfill` is true (a
backfill scan always starts at the true beginning of its own scanned range, which by
definition has no predecessor within this run), and treat any pre-existing rows purely as
`ON CONFLICT` no-ops as already happens for the rest of the range:

```python
if self.backfill:
    prior_long = frozenset()
    prior_short = frozenset()
    prior_leg_seed_bar_ts = None
    self.logger.info(
        "cross_sectional_spread_tracker.prior_legs_seeded",
        source="backfill_no_predecessor",
        bar_ts=None,
    )
else:
    prior_row = await conn.fetchrow(...)
    ...
```

Optionally also add a defensive check that raises (rather than silently proceeding) if
`self.backfill` is true and `construction_spreads` already has rows for this
`(construction_name, tf)` whose `bar_ts` predates the panel's first row — that is exactly the
scenario this bug can silently corrupt, and CLAUDE.md's "silent wrong answers are worse than
loud crashes" argues for failing loud rather than relying on operators never running
`--backfill` except on a truly empty table.

## Warnings

### WR-01: Hardcoded `0.05` significance threshold, not APR-backed

**File:** `services/cross_sectional_spread_tracker.py:1284-1285`
**Issue:** Gate 1's shuffled-ranking-null clearance uses a literal magic number:

```python
fast_null_clears = null_by_scale["fast"]["null_p"] < 0.05
slow_null_clears = null_by_scale["slow"]["null_p"] < 0.05
```

CLAUDE.md's Adaptive Parameter Registry mandate is explicit and forceful: "Hard-coded numeric
thresholds, weights, periods, or counts in `src/` or `services/` are an architecture violation,"
and "Migrate-as-you-go: Any numeric threshold... encountered in `src/` or `services/` that is
not APR-backed MUST be migrated in the same session." Every other tunable in this same module
(`decile_fraction`, `cost_hurdle_bps_round_trip`, `null_shuffles`, `attribution_max_static_r2`)
was correctly migrated to `alpha.construction.*` in migration 260; this one significance level
was not.

**Fix:** Add `alpha.construction.null_p_threshold` (float, default `0.05`,
`[conventional]`) to migration 260 (or a follow-up migration), load it via `_cfg()` alongside
`decile_fraction`/`null_shuffles` in `_load_gate_evaluation_context`, and pass it through to the
`< 0.05` comparisons and the persisted verdict payload's `apr` block.

### WR-02: Broken/dead file-path cross-references in this phase's own doc updates

**File:** `docs/research/data-edge-source-thesis.md:144,269,279,320,322,323`;
`docs/research/trade-construction-layer.md:52,56,391,398,400`
**Issue:** Both docs were edited as part of this phase (2026-07-26/27 entries) and repeatedly
cite five file paths that no longer exist at those locations — all renamed or deleted *before*
this phase began, so the references were already stale when this phase's authors added new
prose around them and did not correct them:

| Cited path | Status |
|---|---|
| `docs/research/intel-15-measurement-engine.md` | Renamed to `docs/research/measurement-ic-engine.md` (2026-07-06) — the "Cross-Sectional Rank IC addendum" content both docs point at actually lives at `measurement-ic-engine.md:316`. |
| `.planning/todos/pending/030-cost-hurdle-apr-calibration.md` | Deleted entirely on 2026-07-09 (was in `completed/`, not `pending/`, before deletion). Cited 3 times as if still live. |
| `docs/plans/2026-06-29-feature-scoring-beyond-ic.md` | Moved to `docs/plans/archive/2026-06-29-feature-scoring-beyond-ic.md`. |
| `docs/research/canonical-simulator.md` | Never existed at that path; the live doc is `docs/research/platform-canonical-simulator.md`. |
| `.planning/research/2026-07-03-intel10-11-fable-review.md` | Wrong directory and name; the live doc is `docs/research/fable-2026-07-03-intel10-11-review.md`. |

**Fix:** Update the five citations above to their current paths in both docs.

### WR-03: `trade-construction-layer.md`'s in-sample diagnostic table misstates a transcribed number

**File:** `docs/research/trade-construction-layer.md:265-270`
**Issue:** The doc states:

> **In-sample diagnostic (NOT the gate)** ... fast `ci_lower` ranges 0.0006 (1bp) down to 0.0004
> (10bp), slow `ci_lower` ranges 0.0009 (1bp) down to 0.0008 (10bp), all `passes=true`.

The persisted verdict artifact this doc claims to transcribe from
(`logs/construction_verdicts/gate1_20260727T112626Z.json`, `in_sample_diagnostic_grid`) shows
the fast-scale, 1bp cell's `ci_lower` as `0.0005374622931064887`, which rounds to **0.0005**,
not 0.0006. (The 10bp fast value, `0.00036128951127276375` → 0.0004, and both slow-scale bounds
are correctly transcribed.) This is the one figure in the doc's otherwise-verified numeric
claims (all Gate 1 binding-verdict and Gate 2 numbers spot-checked clean against the same
artifacts during this review) that does not match its cited source, despite the doc's own
methodology note: "spot-checked against the matching `gate1_summary`/`gate2_summary` structlog
lines... before transcription; log and artifact agreed on every sampled value."

**Fix:** Change `0.0006 (1bp)` to `0.0005 (1bp)` in the in-sample diagnostic sentence.

### WR-04: `glossary.md`'s new entry has a stale `Status:` field

**File:** `docs/foundation/glossary.md:972-973`
**Issue:** The `cross-sectional spread construction` glossary entry (added in commit `e3e43001`,
Phase 167 Plan 01, and never touched again per `git log -- docs/foundation/glossary.md`) reads:

> **Status:** v3.0 (Phase 167, `construction_spreads` hypertable + APR seeds live; the
> `CrossSectionalSpreadTracker` compute/persist service itself lands in later Phase 167 plans)

This describes the state as of Plan 01 (schema-only). Every other file in this review's scope
(`cheatsheet.md`, `operations-infrastructure.md`, `trade-construction-layer.md`,
`data-edge-source-thesis.md`) was updated through Plan 06 and confirms the service is fully
live, both Validation Gates have run against the real OOS population, and both passed. The
glossary — this project's single-canonical-definition source per its own stated purpose — was
not updated to match and now contradicts every other doc it should agree with.

**Fix:** Update the `Status:` line to reflect the shipped state, e.g.: "v3.0 (Phase 167,
complete 2026-07-27 — `construction_spreads` hypertable, APR seeds, and
`CrossSectionalSpreadTracker` compute/persist + `--evaluate-gate`/`--evaluate-attribution` all
live; both Validation Gates PASSED against the real OOS population, see
`docs/research/trade-construction-layer.md`)."

### WR-05: `write_verdict_artifact`'s "never overwrites" guarantee has second-level collision risk

**File:** `services/cross_sectional_spread_tracker.py:460-489`
**Issue:** The function's docstring states the timestamped artifact file "a later run never
overwrites (the record accumulates)" — an explicitly load-bearing audit-trail property (design
decision 7, T-167-17). The timestamp has only second-level resolution
(`strftime("%Y%m%dT%H%M%SZ")`). Two calls to `write_verdict_artifact` with the same
`verdict_name` within the same wall-clock second produce the same `timestamped_path` and the
second call's `write_text()` silently overwrites the first — there is no existence check. In
normal operation each CLI mode calls this function exactly once per process invocation, so the
realistic trigger is an operator (or a retry wrapper) invoking `--evaluate-gate` /
`--evaluate-attribution` twice in rapid succession, or a future caller invoking it
programmatically in a loop.

**Fix:** Either disambiguate on collision (append a short counter/suffix if the target path
already exists) or raise if the intended timestamped path already exists, rather than silently
overwriting a prior audit record — consistent with this file's own "silent wrong answers are
worse than loud crashes" discipline applied everywhere else in the module.

---

_Reviewed: 2026-07-27T12:08:08Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
