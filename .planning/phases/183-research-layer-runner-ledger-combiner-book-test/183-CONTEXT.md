# Phase 183: Research layer: runner, ledger, combiner, book test - context

**Gathered:** 2026-09-25, from the adopted design docs and the owner-approved phase split
(peer session owns phase 182 and family pre-registrations; this session owns 183).
**Author:** Claude (Opus 5.5).
**Design sources:** `docs/plans/2026-09-25-alpha-research-architecture.md` (build, sections
3.4, 3.6, 5 steps 4-6), `docs/plans/2026-09-24-evidence-framework.md` version 4 (rules,
sections 5-6), `docs/plans/2026-09-25-family1-intraday-periodicity-prereg.md` (section 9, R1
and R2).

## Why now

Family 1 (intraday periodicity) is registered and waits on this phase: no real-data number
may exist outside a recorded run, so nothing has to be re-run or back-recorded. Steps 1-3 of
the architecture (Panel, S1 residual target with per-slot betas, S3 guards) are on main in
`src/intelligence/research/`. Alpha-first rule: build the shortest path to family 1's first
evidence records and book version 1's screen test.

## Decisions (locked)

### Runner (architecture step 4, spec as pre-registration)

- **D-01 Spec format.** A candidate spec is a committed YAML file under
  `research/specs/` (one file per family, members listed inside), naming each member's
  signal function by dotted path into `src/intelligence/research/families/`, plus direction,
  declared memory (rows), universe, tf, horizon, family, prior source, construction and
  scoring options. Constants a run depends on (coverage floor, power effect size, cost band)
  live in the spec, the one reviewed place. The spec hash is sha256 over the canonical JSON of
  the parsed spec (sorted keys), so whitespace and comments do not change it.
- **D-02 Refusals, real-data mode.** The runner refuses before touching the snapshot when:
  the spec file is untracked or differs from HEAD; any tracked file under
  `src/intelligence/` or the spec is dirty (a recorded code commit is meaningless on a dirty
  tree); or the ledger already holds a real-data run for that spec hash (a spec runs once;
  a changed spec is a new hash and a new, recorded run).
- **D-03 Order inside a real-data run:** write the `started` ledger row, then S0 snapshot
  (verified content hash), S1, S2, S3 guards, the `require_testable` refusal checks (shifts
  >= 600, synthetic power >= 50%), then S5 or S8, then the terminal ledger update. A crash
  leaves the row `started`, which counts (framework section 6: an aborted run is still
  counted).
- **D-04 Synthetic mode** runs the same pipeline on synthetic panels with no commit check,
  no ledger row and no budget charge. It is what the power check and the tests use.

### Ledger (architecture step 5, S6)

- **D-05 Sole writer.** One module (`src/intelligence/research/ledger.py`) is the only code
  that writes `concept_registry` rows with `domain='construction'` and the run ledger. A
  unit test greps the repo and fails on any other writer.
- **D-06 Identity vs. runs.** `concept_registry(domain='construction')` holds identity: one
  row per family member and one per book version (members linked to their family and book
  versions to their families via `concept_parent`). Run records go in a new append-only table
  `research_run` (migration 366 or higher, after `git fetch origin`; phase 182 holds 364 and
  365): run id, concept id, kind (`evidence` | `book_test`), mode, spec hash, snapshot hash,
  code commit, vintage, status, evidence JSONB, timestamps. `concept_evaluation` is not used:
  its primary key, lifecycle `evaluated_status` and `guard_status` enumerations belong to the
  feature lifecycle and do not fit a started/terminal run state. This is a deliberate
  deviation from evidence framework draft 3's sketch; record the reason in the migration.
- **D-07 Append-only in effect.** A row is inserted `started`; it may move exactly once to a
  terminal status (`completed`, `guard_failed`, `refused`, `failed`), enforced by a trigger;
  nothing else in a row ever changes. A partial unique index on `spec_hash` for real-data
  rows backs D-02 in the database, not just in Python.
- **D-08 Budget.** Vintage 1 = data before `alpha.validation.oos_start` (2025-12-24), M = 30,
  count restarted at 0 on adoption, one-sided bar alpha / M = 0.05 / 30. The vintage id, M and
  alpha are APR keys seeded by the migration (`alpha.research.*`), each description stating
  that a change needs a methodology-change-ledger entry. A book test is charged unless it
  ended `refused` or `guard_failed` (both terminate before any real-data statistic exists);
  a `started` row with no terminal status is charged. Evidence runs are never charged. The
  writer refuses to start a book test when the charged count has reached M.
- **D-09 Evidence record** (framework section 5): estimate (excess annualized Sharpe over the
  null median), stationary-bootstrap standard error and interval, permutation p, per-period
  estimates, shape diagnostics, turnover and cost band (diagnostics only, never a gate),
  n_shifts, power, coverage, resolution time implied by the estimate, and the hashes. No
  PASS/FAIL token for evidence runs. A book test additionally records `p < alpha / M` as its
  screen outcome.

### Combiner and book test (architecture step 6, S7 and S8)

- **D-10 S7 walk-forward ridge** over every member of every admitted family in the book spec,
  no per-member IC gate. Inputs: factor-residualized member alphas (S1), standardized inside
  each fold on fold-training data only; target: the S1 residual forward return. One
  coefficient vector pooled across names, fitted on stacked (row, name) observations from
  past data only, with an embargo of `fwd_span(horizon)` rows between training end and the
  first predicted row. Window, refit cadence and the ridge penalty are pinned in the book
  spec; the penalty is not tuned on vintage outcomes. Closed form, so a refit per shift is
  cheap. Output: combined alpha, fed to the same construction and scoring as a member.
- **D-11 S8 book test.** Shift the stacked member panel `[t, i, k]` jointly by whole
  sessions, rerun S7 on the shifted stack, construct and score it (owner decision: the null
  refits the combiner). Uses `evaluate()` with the combiner inside the construction, so
  there is one statistics path. Refused if fewer than 600 admissible shifts or synthetic V3
  power below 50% at the pre-declared effect (family 1: planted per-slot rank IC 0.002).
  Budget-charged per D-08.
- **D-12 Power check cost is a planning question, not a license to skip.** A power estimate
  over planted panels, each with a refit-per-shift null, is expensive. Research must propose a
  design that is exact to the refusal rule (for example, fewer replicate panels with a
  stated Monte Carlo error, or a null reused across replicates only where that is provably
  equivalent) and state its runtime on the 233-name 15m panel.

### Family 1 build items (prereg section 9)

- **D-13 R1** in `portfolio.py`: weights proportional to centred rank divided by each name's
  volatility; positive weights scaled to sum to +0.5 and negative to -0.5, exactly
  dollar-neutral per row; rows below the coverage floor (20 finite names) carry no position.
  Direction +1. `fixed_sign_returns` stays for its existing callers.
- **D-14 R2** in `evaluate()`: optional session aggregation, default off. When on, per-row
  construction P&L is summed per session before the Sharpe (annualized with 252) for the
  observed book and every shifted copy alike; the bootstrap and sub-period readouts run on the
  daily series too.
- **D-15 Family 1 members P1-P4** (prereg section 3) are implemented as signal functions and
  a committed spec, with S3 guards passing on synthetic panels. No real-data run happens in
  this phase unless the runner, ledger and all refusal checks are in place; the first real
  run (evidence records, then book version 1) is the phase's final plan and goes through the
  runner only.

### Invariants

- **D-16 Bit identity.** `scripts/analysis/sleeve_walk_forward/repro_frozen.py` must stay
  bit-identical after every plan that touches `src/intelligence/research/` (R1, R2, S7, S8).
  Defaults preserve every existing call path.
- **D-17 Research DAG shape.** S0 is the only reader of production tables; S6 the only
  writer. S1-S5 and S7-S8 are compute-only and may run in `ProcessPoolExecutor` workers
  that return arrays (CLAUDE.md worker rule; pool from `make_worker_pool`).
- **D-18 Worktree discipline.** Phase 182 executes in parallel on the main checkout. Work
  only in this worktree; rebase on `origin/main` and push `branch:main` after each plan.

## Claude's discretion

- Module split inside `src/intelligence/research/` (runner, ledger, combiner, book test,
  families).
- Exact `research_run` columns and indexes beyond D-06/D-07, and the CLI shape of the runner.
- Synthetic panel generator reuse (`scripts/analysis/sleeve_walk_forward/synthetic.py` holds
  V2/V3 planting code that may be promoted).

## Canonical references

- `docs/plans/2026-09-25-alpha-research-architecture.md` - build design, sections 3.4-3.6, 5.
- `docs/plans/2026-09-24-evidence-framework.md` - rules: evidence record (5), budget and
  refusals (6).
- `docs/plans/2026-09-25-family1-intraday-periodicity-prereg.md` - members, target,
  construction, scoring, refusals (sections 3-5, 9).
- `docs/foundation/unified-concept-registry.md` - concept_registry semantics.
- `docs/foundation/adaptive-parameter-registry.md` - APR key rules.
- `src/intelligence/research/` - panel, snapshot, factors (S1), signals, guards (S3),
  evaluate (S5), portfolio, store.
- `src/intelligence/statistics/panel_null.py` - admissible shifts, shift_panel.
- `scripts/analysis/sleeve_walk_forward/repro_frozen.py` - bit-identity check.

## Deferred

- Families 2-4 and the first-to-last half-hour family (peer session writes their preregs).
- Freeze, forward shadow and confirmation (S9).
- Capital sizing.
