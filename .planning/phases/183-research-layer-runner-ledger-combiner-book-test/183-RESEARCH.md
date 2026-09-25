# Phase 183: Research layer: runner, ledger, combiner, book test - research

**Researched:** 2026-09-25
**Domain:** research-DAG infrastructure (numpy compute, git provenance, Postgres ledger), family 1 intraday periodicity
**Confidence:** HIGH on code seams, costs and git/DB mechanics (all measured or read in this session); MEDIUM on the power design (sound, but two inputs need owner pinning, see open questions 1 and 2)

<user_constraints>
## User constraints (from CONTEXT.md)

### Locked decisions

#### Runner (architecture step 4, spec as pre-registration)

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

#### Ledger (architecture step 5, S6)

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

#### Combiner and book test (architecture step 6, S7 and S8)

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

#### Family 1 build items (prereg section 9)

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

#### Invariants

- **D-16 Bit identity.** `scripts/analysis/sleeve_walk_forward/repro_frozen.py` must stay
  bit-identical after every plan that touches `src/intelligence/research/` (R1, R2, S7, S8).
  Defaults preserve every existing call path.
- **D-17 Research DAG shape.** S0 is the only reader of production tables; S6 the only
  writer. S1-S5 and S7-S8 are compute-only and may run in `ProcessPoolExecutor` workers
  that return arrays (CLAUDE.md worker rule; pool from `make_worker_pool`).
- **D-18 Worktree discipline.** Phase 182 executes in parallel on the main checkout. Work
  only in this worktree; rebase on `origin/main` and push `branch:main` after each plan.

### Claude's discretion

- Module split inside `src/intelligence/research/` (runner, ledger, combiner, book test,
  families).
- Exact `research_run` columns and indexes beyond D-06/D-07, and the CLI shape of the runner.
- Synthetic panel generator reuse (`scripts/analysis/sleeve_walk_forward/synthetic.py` holds
  V2/V3 planting code that may be promoted).

### Deferred ideas (out of scope)

- Families 2-4 and the first-to-last half-hour family (peer session writes their preregs).
- Freeze, forward shadow and confirmation (S9).
- Capital sizing.
</user_constraints>

<phase_requirements>
## Phase requirements

ROADMAP lists `Requirements: TBD`. The locked decisions are the requirement set; the planner
should use the D-ids as requirement ids.

| ID | Description | Research support |
|----|-------------|------------------|
| D-01 | YAML spec, canonical-JSON sha256 hash | PyYAML safe_load pitfalls measured (section "Common pitfalls" 1); pydantic 2.13 available for a strict schema |
| D-02 | Git refusals before snapshot | Plumbing verified in a temp repo: `git cat-file -e HEAD:<p>`, `git diff --quiet HEAD -- <p>`, `git status --porcelain=v1 --untracked-files=all -- <paths>` (pattern 5) |
| D-03 | Run order, crash leaves `started` | Ledger transaction design (pattern 6); S3 cost on the real panel forces a guard split (pitfall 6) |
| D-04 | Synthetic mode | New residual-space generator (pattern 8); sleeve `synthetic.py` not promotable (section "Don't hand-roll") |
| D-05 | Sole-writer grep test | `tests/unit/_source_grep_helpers.py` scan-and-allow-list pattern; legacy migrations 329-335 need allow-list entries |
| D-06/D-07 | `research_run` table, terminal-once trigger, partial unique index | DDL sketch (code example 4); snapshot hash must be set at terminal update (pitfall 9) |
| D-08 | Budget with APR keys | APR seed pattern from migration 340; advisory-lock-then-count transaction |
| D-09 | Evidence record | Field map to `EvaluationResult` (pattern 7); jsonb rejects NaN (pitfall 8) |
| D-10 | S7 ridge | Moment-prefix-sum closed form, measured 0.3-0.6 s per walk-forward pass (question 3) |
| D-11 | S8 book test | Flattened `[n, m*K]` stack through unchanged `shift_panel` (question 2) |
| D-12 | Power check | Exact per-replicate decision via Besag-Clifford stopping on the full shift set, curtailed fixed R (pattern 9); runtime estimate below |
| D-13 | R1 | New `rank_vol_neutral_returns` in portfolio.py; must not use `CovariancePlan` admission (pitfall 3) |
| D-14 | R2 | `session_scoring` kwarg in `evaluate()`, bootstrap block in sessions (pitfall 4) |
| D-15 | P1-P4 + spec + synthetic guards | Member signature over precomputed S1 residuals (pattern 3) |
| D-16 | Bit identity | Baseline `repro_frozen.py` passes today in 19 s from the worktree with `--logs /home/bg/dev/indicagent/logs` |
| D-17 | DAG shape, worker rule | `evaluate()` already takes an injected `pool_factory` (evaluate.py:49-51, 242-248) |
| D-18 | Worktree | Migration numbering: origin/main tops at 364; 182 claims 365; take 366 |
</phase_requirements>

## Project constraints (from CLAUDE.md)

- APR: numeric thresholds, weights, periods, counts in `src/` or `services/` must come from
  `config_state` via `ConfigService`, seeded by migration with provenance tags. Precedents in
  this package for exemptions: pre-registered test constants (`scripts/analysis/sleeve_walk_forward/config.py:1-3`),
  decision-rule constants (`guards.py:34-42`, `MIN_POWER`). D-01 puts per-run constants in the
  spec; D-08 puts vintage id, M and alpha in APR. Worker count is an infra constant:
  `infra.research_runner.workers` following `infra.ic_engine.workers` (live key, value 8).
- Ring rule: `src/intelligence/` is Ring 1 and today has zero `from services` imports.
  `make_worker_pool` lives in `services/_batch_utils.py:759`; the CLI entry point injects it
  (evaluate.py:49-51 already documents this). The runner must not import
  `services.ic_engine._checkpoint_content_key` (sleeve `run.py:55` does; it drags ~300 MB).
- Timestamps UTC only (`datetime.now(UTC)`); DB defaults `now()` on timestamptz are fine.
- `except X as error:` naming.
- asyncpg: a bare connection has no jsonb codec; use `src.core.database_manager.connect_with_codecs`
  (database_manager.py:33) for the ledger's write connection.
- Worker rule: ProcessPoolExecutor workers are compute-only and return arrays; all DB writes
  through one serial connection in the main process.
- `market_data_ohlcv` reads go through `market_data_ohlcv_tradeable`; S0 already does
  (snapshot.py:47-51). The boundary test regex (`tests/unit/test_market_data_ohlcv_boundary.py`)
  only matches `FROM|JOIN market_data_ohlcv` without `_tradeable`, so new code that never
  touches the table needs no allow-list entry.
- Migration numbers unique (`tests/unit/test_migration_number_uniqueness.py`); a migration
  applied live must be committed in the same breath; `tests/integration/test_migration_schema_sync.py`
  diffs replayed migrations (above cutoff 234) against the live schema.
- Concept registry Invariant 1: only `ConceptRegistryService` flips an existing concept's
  status. The ledger inserts identity rows and never updates status. `concept_parent` writers
  outside a single-transaction seed must take `pg_advisory_xact_lock()` on a fixed key
  (migration 283 lines 29-33, `tests/integration/test_concept_parent_lineage.py` docstring).
- Done-coding SOP: `/simplify`, `/review`, `pytest tests/unit/ -q` green, feature branch,
  ff-merge. Worktree plans push `branch:main` after rebasing (D-18).
- Writing style for docs and comments: no em dashes, sentence-case headings.

## Summary

Every seam the phase needs already exists and every one can be extended without touching an
existing call path. `evaluate()` takes an arbitrary picklable `Construction`
`(alpha, fwd_ret, plan) -> {arm: returns}` (evaluate.py:48) and hands the unshifted `fwd_ret`
to every shifted call (evaluate.py:191), so the S7 combiner fits inside a construction and
reads its ridge target straight from `fwd_ret` with no closure over the target. The stacked
`[t, i, k]` member panel goes through as `[n, m*K]`: `shift_panel` rejects 3-D input
(panel_null.py:49-50) but a row roll of the flattened array is identical to a joint roll of
the stack, so `panel_null` needs no change. R2 is a new `session_scoring` keyword on
`evaluate()`, R1 a new function beside `fixed_sign_returns`; both default off, and the
bit-identity check passes today in 19 s.

Costs were measured with the real code and a prototype on a panel of the real size (4,900
sessions x 26 bars = 127,400 rows, 233 names, 4 members; 15m bars run 2006-07-07 to
2025-12-23 for SPY). One S7 walk-forward ridge pass plus one R1 construction pass costs about
3.0 s single-threaded as first written and about 1 s with two cheap optimizations (moment
prefix sums on decision rows only, chunked float64 accumulation from a float32 stack). The
real book null (about 4,460 whole-session shifts) is then about 75 CPU-minutes, under 10
minutes on 12 workers. S1 is the expensive stage: 3.0 s per refit, about 11 minutes per
residualization of the full panel, and the family needs two (bar returns and forward
returns). That cost decides two designs: S3 guards cannot probe a signal that recomputes S1
on the full real panel (each call would take 11 minutes), and power replicates should be
planted in residual space instead of rerunning S1 per replicate.

The power check can be made exact to the refusal rule per replicate: run the replicate's
book against the same full admissible shift set the real test would use, in a seeded random
order, and stop at the first shift count that already decides failure (Besag-Clifford
sequential p-value). The decision is identical to running every shift. Across replicates,
fix R (for example 100, Monte Carlo standard error 0.05 at power 0.5) and stop as soon as
the fixed-R outcome is determined (curtailment), which is also exact. Estimated cost at
about 1 s per shift: roughly 60-75 CPU-hours, 5-6 hours on 12 workers, dominated by passing
replicates, which must see every shift. Two inputs decide whether that number means
anything, and both belong to the owner: what "planted per-slot rank IC 0.002" is measured
on, and how much cross-sectional correlation the synthetic residuals carry. The prereg's own
arithmetic puts the book near the 50% boundary.

**Primary recommendation:** build in five plans plus the real run (R1/R2; migration 366 and
ledger; spec loader and runner; S7/S8 and the power estimator; family 1 members, spec and
synthetic guards; then the real run), keep `panel_null` and every existing function
signature unchanged, and get open questions 1 and 2 pinned in the book spec before the power
code is finalized.

## Architectural responsibility map

| Capability | Primary tier | Secondary tier | Rationale |
|------------|-------------|----------------|-----------|
| Spec load, canonical hash, git refusals | Research library (`src/intelligence/research/spec.py`, `runner.py`) | CLI (`scripts/research/`) | Pure logic plus git subprocess; the CLI only wires DSN and pool |
| Ledger writes (identity rows, `research_run`, budget) | Database (Postgres, sole writer `ledger.py`) | DB triggers and partial index | D-05/D-07: invariants enforced in the database, not only in Python |
| S0 snapshot | Database read-only (existing `snapshot.build_panel`) | Content-hashed store | Unchanged; runner verifies the hash and checks the manifest against the spec |
| S1, S2 members, S7 ridge, R1, R2, S8 null | Compute (numpy, worker pool) | none | D-17: compute-only, workers return arrays |
| S3 guards | Compute | none | Split into S1 probe on a bounded sub-panel and S2 probes on the full residual array (pitfall 6) |
| Power estimator | Compute (synthetic mode, pool) | none | No DB, no ledger row (D-04) |
| APR keys (vintage, M, alpha, workers) | Database (`config_schema`/`config_state`) | ConfigService or direct read in the runner | D-08 |

## Standard stack

No new packages. Everything is already pinned in `requirements.txt`.

### Core
| Library | Version (installed, verified) | Purpose | Why standard |
|---------|-------------------------------|---------|--------------|
| numpy | 2.4.2 | all compute | project standard; `requirements.txt:31` caps below 2.5 for numba |
| scipy | 1.17.1 | already used by evaluate/factors | existing |
| PyYAML | 6.0.3 | `yaml.safe_load` for specs | already required (`requirements.txt:83`) |
| pydantic | 2.13.4 | strict spec schema (reject strings where numbers are expected, forbid extra keys) | already required (`requirements.txt:80`) |
| asyncpg | existing | ledger write connection via `connect_with_codecs` | project standard |

### Alternatives considered
| Instead of | Could use | Tradeoff |
|------------|-----------|----------|
| YAML spec | frozen dataclass in Python | Locked by D-01 (YAML). Not an option. |
| pydantic schema | hand-written type checks on the parsed dict | Either works; pydantic `model_config = ConfigDict(extra="forbid", strict=True)` gives loud failures for free. Recommend pydantic. |
| Generalizing `shift_panel` to N-D | flatten stack to `[n, m*K]` | Flatten keeps a shared statistics primitive untouched; a one-line test pins equivalence. Recommend flatten. |

**Installation:** none.

## Package legitimacy audit

No external package is installed by this phase. PyYAML and pydantic are existing,
version-pinned dependencies imported today (`src/core/ai/registry.py` imports yaml). slopcheck
was not run because there is nothing new to check.

| Package | Registry | Disposition |
|---------|----------|-------------|
| (none new) | - | - |

## Architecture patterns

### System architecture diagram

```
research/specs/family1.yaml  research/specs/book_v1.yaml   (committed, parsed from HEAD blob)
            |                          |
            v                          v
   [spec loader: safe_load -> pydantic -> canonical JSON -> sha256]
            |
            v
   [refusal gate, real mode only]  -- spec in HEAD? clean vs HEAD? loaded modules clean?
            |                          prior real run for hash? (ledger read)  -> REFUSE (no row)
            v
   [ledger: BEGIN; advisory lock; budget count (book only); upsert identity rows +
            concept_parent edges; INSERT research_run status='started'; COMMIT]
            |
            v
   S0 panel (build or load, verify content hash, manifest vs spec)
            |
            v
   S1 residual bar returns ----------------------------+
   S1 residual forward returns (target, lag fwd_span)  |
            |                                          |
            v                                          v
   S2 members P1..P4 (from residual bar returns) -> stack [n, m, K]
            |
            v
   S3 guards: integrity (full panel), S2 probes on full residual array,
              S1 probe on a bounded real sub-panel      -> fail: terminal 'guard_failed'
            |
            v
   require_testable: n_shifts >= ceil(M/alpha); power (book only) -> fail: terminal 'refused'
            |
     +------+----------------------+
     | evidence run (per member)   | book test
     v                             v
   evaluate(alpha_k, fwd_resid,    evaluate(stack.reshape(n, m*K), fwd_resid,
     construction=R1,                construction=partial(book_returns, m, K, ridge spec, vol),
     session_scoring=True)           session_scoring=True)
            |                             |  (each shift: roll stack rows, refit ridge, R1, sum per session)
            v                             v
   evidence record (D-09)          evidence record + screen outcome p < alpha/M
            |                             |
            +-------------+---------------+
                          v
   [ledger: UPDATE research_run SET status=terminal, snapshot_hash, evidence, finished_at]
```

### Recommended project structure

```
research/specs/
  family1_intraday_periodicity.yaml   # members P1-P4, construction R1, scoring R2, constants
  book_v1.yaml                         # families by spec path, ridge window/cadence/penalty, power
src/intelligence/research/
  spec.py          # load from git blob, schema, canonical hash, family/book resolution
  runner.py        # refusal gate, ordered pipeline, evidence assembly (no services import)
  ledger.py        # sole writer: identity rows, concept_parent, research_run, budget
  combiner.py      # S7 walk-forward ridge over a [n, m, K] stack
  book.py          # S8 construction (flatten/unflatten, ridge, R1), power estimator
  synthetic.py     # residual-space intraday generator with planted same-slot persistence
  families/
    __init__.py
    intraday_periodicity.py  # P1-P4 over residual bar returns
  (existing) panel.py snapshot.py factors.py signals.py guards.py evaluate.py portfolio.py store.py
scripts/research/
  run_spec.py      # CLI: DSN from Settings, pool from make_worker_pool, workers from APR
production/migrations/
  366_research_run_ledger.sql
tests/unit/research/  test_spec.py test_runner_git.py test_combiner.py test_book.py
                      test_synthetic.py test_families_intraday.py test_portfolio_r1.py
                      test_evaluate_session_scoring.py test_ledger_sole_writer.py
tests/integration/    test_research_ledger.py
```

### Pattern 1: R1 as a new construction (question 1)

**What:** `rank_vol_neutral_returns(alpha, fwd_ret, plan, *, vol, direction, coverage_floor) -> {"rank_vol_neutral": r}`
beside `fixed_sign_returns` (portfolio.py:184). It ignores `plan`. `vol` is a precomputed
`[n, m]` array of each name's trailing volatility known at row t; it depends only on returns,
so like `CovariancePlan` it is computed once and shared by the observed run and every shift
(evaluate.py:5-8 states the same rule for the plan). Bind with `functools.partial` so it stays
picklable (evaluate.py:216-218 requires a module-level function or partial).

Per row: names with finite alpha and finite positive vol; if fewer than `coverage_floor`, NaN
(no position, excluded from the Sharpe, which is how `annualized_sharpe` already treats NaN,
evaluate.py:120). Centred rank `rank / (n_valid - 1) - 0.5`, times `direction`, divided by
vol; positive side scaled to sum +0.5, negative to -0.5; P&L `sum w * fwd` with missing
forward return held at 0 (same convention as `fixed_sign_returns`, portfolio.py:199). A row
where either side is empty (ties, all zero ranks) carries no position.

**Why not reuse the plan:** measured on a 127,400 x 233 panel with 3% random missing bars,
`plan_covariance` admitted 0 names at every one of 222 refits: `instrument_covariance`
requires jointly complete rows on 95% of the window (weighting.py:84-106), which a ragged
233-name intraday grid never has. It costs about 1 s, so leaving evaluate's unconditional
call in place (evaluate.py:225) is harmless, but anything reading `plan.sigma` gets nothing.
`fixed_sign_returns` on this panel would return all-NaN and `annualized_sharpe` would raise.

**Which volatility:** the prereg says "each name's volatility" without a definition. The spec
must pin it. Recommendation: trailing standard deviation of the name's S1 residual bar returns
over `vol_window_sessions` sessions ending at row t (the P&L is residual, so residual vol is
the consistent scale; within one row every name is in the same slot, so a pooled-bar vol is
enough for relative weights).

### Pattern 2: R2 as an evaluate() keyword (question 1)

Add `session_scoring: bool = False` to `evaluate()` (not to `EvaluationConfig`: every config
field must be classified, `tests/unit/research/test_evaluate_intraday.py:57-60`, and
`HarnessConfig` is the frozen sleeve config). When on, one helper converts each per-row
series to a per-session series, used in exactly three places so observed and null match:

- observed: evaluate.py:229-232 (`obs_daily`, `sharpe_obs`);
- each shift: `_run_shifts`, evaluate.py:190-194 (the Sharpe and the stored `daily` row);
- readouts: `trade`, `sub_masks`, bootstrap and diagnostics then run on sessions, with
  `periods_per_year = 252` and the bootstrap block `cfg.bootstrap_mean_block` in sessions,
  not `rcfg`'s row-scaled one (evaluate.py:277).

Session value = sum over the session's rows that are in `trade` and finite; NaN when none is
finite (a session with no position is not a zero-return day). Session index is
`row // bars_per_session` (the grid is regular, panel.py:58-61), not calendar date. A session
is in the scored span when any of its rows is in `trade`; sub-period masks use the session's
date. `EvaluationResult.observed_daily` and `null_median_daily` then hold per-session series;
document that in the dataclass comment.

Side benefit: without R2 the null stores `[shifts, arms, rows]` float32 (evaluate.py:189),
about 2.3 GB for 4,460 shifts x 127,400 rows; with R2 it is about 87 MB. The bootstrap also
allocates `reps x n` int64 twice plus a Python loop over n (evaluate.py:307-312): with rows it
is about 4 GB and 127k iterations; with sessions it is small.

### Pattern 3: members over precomputed residuals (D-15)

A member that recomputes S1 inside `compute(panel)` costs about 11 minutes per call on the
real panel. S1 is shared by all four members and by the target. Recommendation: the family
module exposes pure functions `same_slot_mean(resid_bar_returns, *, bars_per_session,
window_sessions, min_finite_fraction) -> alpha [n, m]` (centred rank applied by a shared
helper with the coverage floor), and the spec names them by dotted path. For guards and
`SignalSource`-shaped consumers, a thin composition `lambda p: member(residual_returns(bar_returns(p), bars_per_session=bps, spec=S).residual)`
is used on synthetic panels with a small `FactorSpec` (as `tests/unit/research/test_factors.py`
already does). Declared memory in rows = `window_sessions * 26` plus the S1 reach
`(window_sessions + refit_sessions) * 26` of `VINTAGE_1` (factors.py:102-103), as the prereg
section 3 states.

Placement per prereg section 3: slot j of session d is formed at row `d*26 + 2j - 1`
(slot 0 at the previous session's last row); other rows NaN. Slot residual return is the sum
of bars `2j` and `2j+1`, NaN if either is missing. "At least half the window's days finite"
means `count >= ceil(w / 2)` (for w = 5 that is 3); write it with integer arithmetic.

Target: `forward_returns(panel.open, 2, panel.session, closes=panel.close)` (panel.py:92-129)
gives the slot-12 market-on-close exit; residualize with
`residual_returns(fwd, bars_per_session=26, horizon=2)` (factors.py:261-307, lag
`fwd_span(2) = 3`).

### Pattern 4: S8 as evaluate() with the combiner inside the construction (question 2)

```python
# book.py (sketch)
def book_returns(alpha_flat, fwd_ret, plan, *, n_members, ridge, vol, direction, coverage_floor):
    n, mk = alpha_flat.shape
    stack = alpha_flat.reshape(n, mk // n_members, n_members)  # a view, no copy
    combined = walk_forward_ridge(stack, fwd_ret, ridge)        # S7, target = fwd_ret
    return rank_vol_neutral_returns(combined, fwd_ret, plan, vol=vol,
                                    direction=direction, coverage_floor=coverage_floor)

construction = functools.partial(book_returns, n_members=K, ridge=spec.ridge, vol=vol, ...)
res = evaluate(stack.reshape(n, m * K), fwd_resid, panel.close, panel.timestamps, cfg,
               construction=construction, memory=book_memory_rows, embargo=fwd_span(2),
               bars_per_session=26, valid=panel.valid, session_scoring=True,
               workers=w, pool_factory=pool, mv_condition_max=..., ic_shrinkage_k=...)
```

Why it works:
- `np.roll(x, k, axis=0)` on `[n, m*K]` moves the same rows as on `[n, m, K]`; the reshape is
  C-order, so each row's `m*K` block is that row's `[m, K]` slab. A unit test asserts
  `shift_panel(stack.reshape(n, -1), k).reshape(n, m, K) == np.roll(stack, k, axis=0)`.
- `evaluate()` reads `alpha` only for `alpha.shape[0]` (evaluate.py:219, 189) and passes it to
  the construction and `shift_panel`; `arm_weights` runs only for the calibrated arms
  (evaluate.py:262). So a 2-D flattened stack is a legal `alpha`.
- The construction receives the unshifted `fwd_ret` on every call (evaluate.py:191), so the
  shifted refit trains shifted member alphas against the true target, which is D-11's null.
- The book has one arm, so Westfall-Young (panel_null.py:57-86) reduces to the plain rank
  p `(1 + #{null >= obs}) / (1 + K)`; `excess`, `excess_ci`, `sub_period_excess` come for free.
- Memory for the shift set: max member memory plus `fwd_span(2)`, rounded up to whole
  sessions by `session_shifts` (evaluate.py:168-174). The ridge adds no read-ahead: its
  training pairs `(alpha_shifted[s], y[s])` only reach the true alignment within the same
  memory distance of a full rotation that the member memory already excludes.

### Pattern 5: git refusal checks (question 5), verified in a temp repo this session

| Check | Command | Verified behavior |
|---|---|---|
| spec committed | `git -C <root> cat-file -e HEAD:<spec>` | exit 0 in HEAD; 128 for a file that is only staged. `git ls-files --error-unmatch` returns 0 for a staged-but-uncommitted file, so it is the wrong check |
| spec equals HEAD | `git -C <root> diff --quiet HEAD -- <spec>` | exit 1 for staged or unstaged edits |
| code clean | `git -C <root> status --porcelain=v1 --untracked-files=all -- <paths>` | empty when clean; shows `M ` staged, ` M` unstaged, `??` untracked |
| spec content | `git -C <root> show HEAD:<spec>` | parse this blob, not the working file |
| provenance | `git rev-parse HEAD`, `git rev-parse HEAD:<spec>` | commit sha and the spec's blob sha |

Recommendations:
- Parse the spec from `git show HEAD:<spec>` after the equality check, so the hashed content
  is provably the committed content.
- D-02 names `src/intelligence/`. The run also loads `src/core/` (market_calendar,
  database_manager), `src/config/`, and the CLI's `services/_batch_utils.py`. Check the
  union of `src/intelligence`, `research/specs`, and every first-party module actually
  loaded (`sys.modules` files under `src/`, `services/`, `scripts/research/`, the approach of
  `services/ic_engine.py:5376-5415`) after the family modules are imported. Include untracked
  files: an untracked `families/*.py` could be imported by dotted path yet absent from the
  recorded commit.
- Restrict dotted paths to the `src.intelligence.research.families.` prefix before
  `importlib.import_module` (a YAML file should not name arbitrary code).
- Unit-test the git layer against a throwaway repo in `tmp_path` (`git init`, commit, edit,
  stage, add untracked); CI runners have git.

### Pattern 6: ledger transaction and budget (D-05 to D-08)

One `ledger.py` with async functions over a connection from `connect_with_codecs`:

1. `start_run(conn, spec, kind, concepts, code_commit, vintage)`:
   `BEGIN; SELECT pg_advisory_xact_lock(<fixed key>)` (covers `research_run`, identity rows
   and `concept_parent`, satisfying migration 283's writer contract); refuse if any real-mode
   row exists for the spec hash; for `book_test`, count charged rows in the vintage and
   refuse at M; `INSERT ... ON CONFLICT (domain, name) DO NOTHING` identity rows
   (status `candidate`, `enabled false`, `added_phase '183'`, `metadata.kind` in
   `family | member | book_version`); `INSERT ... ON CONFLICT DO NOTHING` the
   `concept_parent` edges; `INSERT research_run (..., status 'started')`; `COMMIT`.
2. `finish_run(conn, run_id, status, snapshot_hash, evidence)`: one `UPDATE` guarded by the
   trigger.

Charged count: `kind = 'book_test' AND vintage = $1 AND status NOT IN ('refused', 'guard_failed')`
(so `started`, `completed` and `failed` count, per D-08). Refuse when `count >= M`.

A family spec yields one evidence row per member; the unique index is therefore on
`(spec_hash, concept_id) WHERE mode = 'real'`, and the Python check refuses when any real row
exists for the spec hash. Add a `run_group uuid` column so one invocation's member rows can be
read together. The book spec's canonical content embeds the canonical content of every
family spec it names, so a family edit changes the book hash (a new book version).

### Pattern 7: evidence record from EvaluationResult (D-09)

| D-09 field | Source |
|---|---|
| estimate | `res.excess[0]` (evaluate.py:269) |
| bootstrap interval | `res.excess_ci[0]` (evaluate.py:273-284) |
| bootstrap standard error | not returned today; add an optional sd of the bootstrap Sharpe draws (no effect on existing outputs if returned only when asked) or record interval width / 3.92 and say so |
| permutation p | `res.adjusted_p[0]` (one arm, so the rank p) |
| per-period estimates | `res.sub_period_excess[0]` (mean per-session excess with R2) |
| shape diagnostics | `res.diagnostics` |
| n_shifts | `len(res.shifts)` |
| turnover, cost band | computed outside evaluate from the observed R1 weights (the construction can expose a `weights` twin like `arm_weights`); cost band = turnover x the spec's cost figures; diagnostic only |
| coverage | `IntegrityReport.coverage` summary (guards.py:52-55) |
| power | book only (see open question 3) |
| resolution time | from framework section 2: years for 80% power `((1.645 + 0.842) / e)^2`, or years to t = 2 `(2 / e)^2`; pin one (recommend the 80% power figure, which section 7 uses), NaN when e <= 0 |
| hashes | spec hash, spec blob sha, snapshot hash, code commit |
| screen outcome (book only) | `p < alpha / M` with alpha and M read from APR at start and stored in the row |

### Pattern 8: residual-space synthetic generator (question 6, D-04)

Plant in residual space and skip S1 in power replicates. S1 is 11 minutes per
residualization (measured: 2.96 s per refit, about 221 refits); running it twice per
replicate for 100 replicates would add about 37 CPU-hours, and S1's job (removing market,
cluster and PC structure) is not what the power question asks about. Justify the shortcut
with a one-time fidelity check: on 3 replicates with realistic factor structure, run the full
S1 path and confirm the members' realized IC is within a stated tolerance of the residual-space
plant's.

Generator shape (all pinned in the book spec):
- Grid: the real panel's `n`, `m`, `bars_per_session`, and its finite mask (which names trade
  when; about 160 names in 2010 growing to 233). The mask carries no return information and
  makes coverage realistic. Using it means the power run happens after S0, inside the real
  run, which is what D-03 already orders.
- Residual bar returns: Gaussian (or Student t) with a low-rank common component so the
  cross-section's participation ratio matches a pinned breadth figure (open question 2).
  Independent residuals would roughly double the book's IR relative to 60 effective names
  and make power meaningless.
- Plant: same-slot persistence at the slot level, `u[d, j, i] = e[d, j, i] + c * mean_{k=1..L}
  u[d-k, j, i]` (HKS find similar coefficients out to about 40 days; L = 40), cross-sectionally
  demeaned, `c` calibrated so the pinned IC definition equals 0.002 (open question 1). The
  target is the slot's own residual return, so members computed from the synthetic bars see
  exactly what the plant put there.

The sleeve's `scripts/analysis/sleeve_walk_forward/synthetic.py` is not promotable: it is
1d-only, equicorrelated over 13 names, plants through `SIGNALS` or an AR(1)-plus-target
alpha, subsamples shifts, and decides through the sleeve `decide()` tokens
(synthetic.py:40-74, 87-116, 153-176). It is the frozen record of the phase 179/181 V2/V3
verdicts. Write a new module; reuse only the AR idea.

### Pattern 9: power exact to the refusal rule (D-11, D-12, question 3)

Per replicate (one planted panel):
1. Compute members, the observed book Sharpe `S_obs` with the same construction and R2
   scoring as the real test (share the session-aggregation helper with `evaluate()`).
2. Enumerate the same admissible shift set the real test uses for this `n` and memory.
   With K shifts the real test passes when `(1 + b) / (1 + K) < alpha / M`, that is
   `b <= b_max = ceil((alpha / M) * (1 + K)) - 2` (compute it exactly with integers and
   assert on the boundary; at K = 4,461 it is 6).
3. Visit shifts in a seeded random permutation, count `b` = shifted Sharpe >= `S_obs`; stop
   and record FAIL as soon as `b = b_max + 1` (Besag and Clifford 1991). A replicate that
   reaches the end PASSes. The decision is identical to evaluating every shift, because
   the count can only grow.

Across replicates: fix R in the spec (recommend R = 100; Monte Carlo standard error at power
0.5 is 0.05, 95% band about +-0.10). Rule: power estimate = passes / R >= 0.5. Stop as soon as
the outcome is determined (50 passes accept; 51 failures refuse). That curtailment gives the
fixed-R decision exactly. Record passes, failures, R and the stopping point in the evidence.

What is not exact and why it is rejected: a random subsample of 600 shifts per replicate
(the sleeve's method, synthetic.py:92-98). Its pass condition (`b = 0` in 600) is a
different function of the replicate's exceedance rate than the full test's (`b <= 6` in
about 4,461); near q = 0.0016 the two pass with probability about 0.39 and about 0.5, so it
is not even uniformly conservative. A shared null across replicates is not provably
equivalent either: each replicate's shifted Sharpes depend on its own returns.

Runtime (measured components, see question 3 below): passing replicates evaluate every shift
(about 4,461 x 1 s = 75 CPU-min); failing replicates stop after about `(b_max + 1) / q`
shifts, typically a few hundred. At power near 0.5, R = 100 with curtailment: about 50 x 75
+ 50 x 10 CPU-min, 60-75 CPU-hours, 5-6.5 hours wall on 12 workers. Parallelize over
replicates (one replicate per worker), not over shifts, so each early stop frees a worker.

### Anti-patterns to avoid

- Recomputing S1 inside a member's `compute(panel)` on the real panel (pitfall 6).
- Using `CovariancePlan` admission or `plan.sigma` for R1 (pattern 1).
- Putting `session_scoring` on `EvaluationConfig` (breaks the field-classification test and
  the frozen `HarnessConfig`).
- Reading the spec from the working tree instead of the HEAD blob.
- Checking "tracked" with `git ls-files` (passes for staged-only files).
- Running a power replicate on a subsample of shifts and calling it exact.
- A ledger that updates `concept_registry.status` (Invariant 1) or writes `concept_parent`
  without the advisory lock.

## Don't hand-roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| Whole-session shift sets | a new shift enumerator | `evaluate.session_shifts` / `panel_null.admissible_shifts` | memory rounding and bounds already pinned and tested |
| Shifting the stack | a 3-D shift | `shift_panel` on `reshape(n, m*K)` | identical rows, no change to a shared primitive |
| Permutation p, bootstrap CI, sub-periods | new statistics in the book module | `evaluate()` with `session_scoring=True` | D-11: one statistics path |
| Worker pool | bare `ProcessPoolExecutor` | `make_worker_pool` injected via `pool_factory` | BLAS oversubscription (todo 216) |
| jsonb on a bare connection | `json.loads` shims | `connect_with_codecs` | CLAUDE.md asyncpg rule |
| Sole-writer scan | a bespoke regex walker | `tests/unit/_source_grep_helpers.py` (`find_pattern_references`, `assert_no_unlisted_references`, `assert_allow_list_has_no_stale_entries`) | existing, two-direction allow-list diff |
| Snapshot integrity | a new hash | `store.verify` (store.py:45-50) | content hash already in the directory name; have it return the full digest for the ledger |
| APR seeding | ad hoc inserts | migration 340's `config_schema` + `config_state` `ON CONFLICT DO NOTHING` pattern | provenance tags, idempotent replay |
| Residualization | per-member neutralization | `factors.residual_returns` on bar and forward returns | factors.py's rule: return-built signals are built from residual returns |

## Runtime state inventory

Not a rename or migration phase. Omitted, with one related note: a real-data run leaves state
in the live DB (`research_run` rows, identity rows, `concept_parent` edges) that no code
change can undo, by design. Migration 366 must be applied live and committed in the same
step, or `tests/integration/test_migration_schema_sync.py` will diverge.

## Measurements (question 3)

All single-threaded (`OPENBLAS_NUM_THREADS=1`), this machine (24 cores, 29 GB RAM, about 18 GB
available at measurement time), worktree code, prototypes in the session scratchpad.

| Item | Size | Measured |
|---|---|---|
| `repro_frozen.py` baseline | phase 179 + 181 artifacts | bit-identical, 19.3 s wall |
| `pytest tests/unit/research` | 84 tests | 14.4 s wall |
| S1 `residual_returns` | 8,190 rows x 233, 26 bars/session | 2.96 s per refit; full panel about 221 refits, about 11 min per residualization, two needed |
| `plan_covariance` | 127,400 x 233, warmup 252 sessions, refit 21 | 1.0 s total, 0 names admitted at all 222 refits |
| members P1-P4 + centred ranks | 127,400 x 233 x 4 | 7.3 s (float64), 2.2 s (float32) |
| S7 ridge walk-forward, first cut (einsum moments, all rows) | same | 2.3 s |
| ridge moments, chunked matmul from float32 | same | 0.62 s all rows, 0.33 s decision rows only |
| R1 construction pass (argsort ranks) | 127,400 x 233 | 0.7-0.8 s |
| `np.roll` of the stack | float32 0.47 GB | 0.03 s |
| peak RSS, whole prototype process | float64 / float32 | 5.9 GB / 4.2 GB |
| peak RSS, moments benchmark | float32 inputs | 1.4 GB |

Stack memory: `127,400 x 233 x 4` is 0.95 GB in float64, 0.47 GB in float32. `evaluate()`
pickles `alpha` to every worker chunk (evaluate.py:245-248), so worker count times the stack
size is resident. Recommendation: float32 stack (members are ranks in [-0.5, 0.5]; float32
resolves them exactly enough), float64 accumulation in the ridge, and 8 workers to start
(about 8 x (0.47 + 0.12 + about 1.5 transient) GB, within 18 GB); make the count
`infra.research_runner.workers`.

Derived estimates (about 1 s per shift after the two optimizations, 12 workers):

| Stage | Estimate |
|---|---|
| S1, two residualizations | about 22 CPU-min, serial as written |
| evidence run per member (R1 only, about 0.5-1 s per shift, about 4,460 shifts) | about 40-75 CPU-min, 4-7 min wall |
| book test null | about 75 CPU-min, 7-10 min wall |
| power, R = 100, exact design | 60-75 CPU-hours, 5-6.5 h wall |

Admissible shifts: with the panel from 2006-07 (about 4,900 sessions), min_shift 63 and book
memory about 314 sessions (40 slot sessions + 252 + 21 S1 reach + the forward span rounded up),
`4,900 - 126 - 314 + 1 = 4,461`, well above 600. A panel starting later loses sessions one for
one.

Power, analytic sanity check (not a substitute for the synthetic run): the prereg's IR 0.9 at
IC 0.002 over 16 scored years gives a null Sharpe sd of about 0.25 and a critical value of
about 2.94 x 0.25 = 0.73. If walk-forward ridge and R1 keep a fraction eta of the IR, power is
about Phi((0.9 eta - 0.73) / 0.25): 0.74 at eta = 1, 0.47 at eta = 0.8. The gate is live,
which is why the Monte Carlo error and the IC definition matter.

## Common pitfalls

### Pitfall 1: YAML silently changes types
**What goes wrong:** measured with PyYAML 6.0.3 `safe_load`: `1e-4` parses as the string
`'1e-4'`, `2025-12-24` as `datetime.date` (then `json.dumps` fails), `no` as `False`.
**How to avoid:** validate with a strict pydantic model (`extra="forbid"`, `strict=True`),
require dates as quoted strings, write floats with a decimal point; hash
`json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)`.
Never `yaml.load`.
**Warning signs:** a hash that changes when only formatting changed, or a numeric field that
arrives as a string.

### Pitfall 2: "tracked" is not "committed"
`git ls-files --error-unmatch` returns 0 for a staged new file (verified). Use
`git cat-file -e HEAD:<path>`.

### Pitfall 3: R1 on the covariance plan
See pattern 1. The symptom is an all-NaN return series and a `ValueError` from
`annualized_sharpe`, or worse, a book traded on a handful of admitted names.

### Pitfall 4: R2 with row-scaled readouts
**What goes wrong:** `rcfg.bootstrap_mean_block` is in rows (evaluate.py:68, 164); with
session scoring the block must be `cfg.bootstrap_mean_block` sessions, `periods_per_year` 252
not `252 * 26` (evaluate.py:221), and sub-period masks built on sessions. Missing any one
silently changes the interval or the Sharpe scale.
**How to avoid:** one helper returns `(series, trade_mask, dates, periods_per_year, block)`
for the chosen unit; a test runs R2 on a 1-bar-per-session panel and asserts equality with
the default path (which also proves D-16 on the new branch).

### Pitfall 5: S1 is the bottleneck, not the combiner
Two residualizations are about 22 CPU-minutes; the combiner null is seconds per shift.
Plans that parallelize the null and leave S1 serial are fine; plans that call S1 per shift or
per replicate are not.

### Pitfall 6: S3 guards on the real panel with S1 inside the signal
`causality_probe` recomputes the signal once per probe row per fill (guards.py:124-145),
`memory_check` once per row (guards.py:162-181). With S1 inside, each call is about 11
minutes: 20 probe rows would take about 11 hours per member. Split the real-data S3: integrity
on the full panel (cheap, guards.py:185-211); S2 probes on the full-size residual array
(members are about 2 s per call; needs an array-input variant of `causality_probe` and
`memory_check`, or an adapter, because both edit Panel price fields, guards.py:106-109); S1
probed once on a bounded real sub-panel (for example the first 300 to 350 sessions, a few
refits, about 10 s per call). On synthetic panels (D-15) the composed function with a small
`FactorSpec` is fine, as `test_factors.py` does today.

### Pitfall 7: the snapshot hash is written after `started`
D-03 writes `started` before S0, so `snapshot_hash` is unknown at insert. The trigger must
allow it to go from NULL to a value in the single terminal update, together with `status`,
`evidence` and `finished_at`, and nothing else.

### Pitfall 8: jsonb rejects NaN, and numpy types do not serialize
`json.dumps(float('nan'))` emits `NaN`, which Postgres jsonb refuses; numpy scalars and
arrays are not JSON types. Convert with `.tolist()`/`float()`, map NaN and inf to `None`,
serialize with `allow_nan=False` before the terminal update, and on a serialization error
write `failed` with the error text, never leave the row stuck because the final write crashed.

### Pitfall 9: concurrent budget or lineage writes
Two runners can both see `count < M`. Take `pg_advisory_xact_lock` on one fixed key, then
count and insert in the same transaction. The same lock satisfies the `concept_parent` writer
contract (migration 283 lines 29-33).

### Pitfall 10: importing services from src
The runner in `src/intelligence/research/` must not import `services.*` (Ring 1). The CLI in
`scripts/research/` injects `make_worker_pool`, the DSN and the APR values.

### Pitfall 11: worktree paths
`repro_frozen.py` needs `--logs /home/bg/dev/indicagent/logs` from the worktree (frozen
artifacts are in the main checkout's gitignored `logs/`). The runner should resolve the repo
root with `git rev-parse --show-toplevel` and run every git command with `-C <root>`.

### Pitfall 12: evidence-run null memory without R2
An intraday evaluate without session scoring stores `[shifts, rows]` null series (about
2.3 GB here) and runs a row-level bootstrap (about 4 GB). Family 1 always uses R2; if a
future caller does not, it needs the memory.

### Pitfall 13: oos_start is not midnight
`alpha.validation.oos_start` is `2025-12-24T05:15:00Z` (live DB). The spec's `end_exclusive`
check in S0 compares timestamps (snapshot.py:159-166), so a spec that writes `2025-12-24` is
accepted as UTC midnight, which is before oos_start. Fine, but state it in the spec comments.

## Code examples

### 1. Canonical spec hash
```python
# spec.py (sketch)
text = subprocess.run(["git", "-C", root, "show", f"HEAD:{rel}"], check=True,
                      capture_output=True, text=True).stdout
model = FamilySpec.model_validate(yaml.safe_load(text))           # strict, extra="forbid"
canonical = json.dumps(model.model_dump(mode="json"), sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False, allow_nan=False)
spec_hash = hashlib.sha256(canonical.encode()).hexdigest()
```

### 2. Walk-forward ridge from moment prefix sums (S7)
```python
# combiner.py (sketch). X [n, m, K] float32, y [n, m]; rows < hi train, hi = p - embargo + 1
ok = np.isfinite(y) & np.isfinite(X).all(axis=2)                    # complete cases only
# per-row count, sum x, sum xx', sum xy, sum y; cumulative over rows; chunked float64
...
c, sx, sxx, sxy, sy = (P[hi] - P[lo] for P in prefix)                # training window
mu = sx / c
cov = sxx / c - np.outer(mu, mu); sd = np.sqrt(np.diag(cov))
b = np.linalg.solve(cov / np.outer(sd, sd) + lam * np.eye(K),       # standardized in-fold
                    (sxy / c - mu * (sy / c)) / sd)
combined[p:q] = ((X[p:q] - mu) / sd) @ b                             # NaN where a member is NaN
```
Standardization uses only the fold's training moments; the penalty is on the standardized
scale; `lam`, window and cadence come from the book spec. Prediction where any member is NaN
is NaN (no fill), which is the conservative choice (open question 4).

### 3. Exact per-replicate decision (power)
```python
def replicate_passes(s_obs, shifts, shifted_sharpe, b_max, rng):
    b = 0
    for k in rng.permutation(shifts):
        if shifted_sharpe(int(k)) >= s_obs:
            b += 1
            if b > b_max:
                return False, b          # decided: cannot pass whatever follows
    return True, b
```

### 4. research_run DDL sketch (migration 366)
```sql
CREATE TABLE research_run (
    run_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_group      uuid NOT NULL,
    concept_id     uuid NOT NULL REFERENCES concept_registry (concept_id),
    kind           text NOT NULL CHECK (kind IN ('evidence', 'book_test')),
    mode           text NOT NULL CHECK (mode IN ('real')),
    spec_path      text NOT NULL,
    spec_hash      text NOT NULL,
    spec_blob      text NOT NULL,
    code_commit    text NOT NULL,
    snapshot_hash  text,
    vintage        text NOT NULL,
    budget_m       integer,
    screen_alpha   double precision,
    status         text NOT NULL DEFAULT 'started'
                   CHECK (status IN ('started','completed','guard_failed','refused','failed')),
    evidence       jsonb,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz
);
CREATE UNIQUE INDEX research_run_real_spec_once
    ON research_run (spec_hash, concept_id) WHERE mode = 'real';
CREATE INDEX research_run_budget_idx ON research_run (vintage, kind, status);
-- BEFORE UPDATE trigger: OLD.status must be 'started'; NEW.status terminal; every column
-- except status, snapshot_hash (NULL -> value only), evidence, finished_at unchanged.
-- BEFORE DELETE and BEFORE TRUNCATE triggers: RAISE EXCEPTION.
```
Plus APR seeds (`alpha.research.vintage_id` string `vintage_1`, `alpha.research.budget_m`
int 30, `alpha.research.screen_alpha` float 0.05, `infra.research_runner.workers` int), each
description tagged `[user_preference]` and stating that a change needs a
methodology-change-ledger entry (`docs/plans/methodology-change-ledger.md`). The header
records why `concept_evaluation` is not used (D-06). Not a hypertable; no VACUUM step. Mode
could allow `'synthetic'` for symmetry, but D-04 writes no synthetic rows, so `'real'` only
keeps the CHECK honest.

## State of the art

| Old approach | Current approach | When changed | Impact |
|---|---|---|---|
| Construction verdict rows inserted by hand-written migrations (329-335) | `ledger.py` sole writer, runs in `research_run` | this phase | the sole-writer test must allow-list the legacy migrations by name |
| Monte Carlo subsample of shifts per synthetic seed (sleeve V2/V3) | full shift set with sequential early stopping | this phase | power exact to the real test's decision |
| PASS/FAIL tokens (`verdict.decide`) | evidence records; book screen outcome only | E15, 2026-09-25 | no token field in evidence JSON |

## Assumptions log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | About 1 s per shift is reachable with the two measured optimizations; the full book construction was only prototyped, not built | Measurements | power runtime scales linearly; at 3 s per shift power is about 15-20 h wall |
| A2 | Failing power replicates stop after a few hundred shifts on average | Pattern 9 | cost rises toward R x K shifts if many replicates sit near the threshold |
| A3 | S1 passes an idiosyncratic, cross-sectionally demeaned plant nearly unchanged | Pattern 8 | power overstated; the 3-replicate fidelity check measures it |
| A4 | Worker RSS about 2 GB with float32 inputs and chunked moments | Measurements | fewer workers, longer wall time |
| A5 | Full S0 build time for 233 names at 15m is minutes, not hours (not measured, read-only DB fetch of about 30M rows) | Summary | real-run wall time only |
| A6 | 15m history starts 2006-07 for most early names (checked for SPY only) | Measurements | fewer sessions, fewer shifts (still far above 600) |

## Open questions

1. **What "planted per-slot rank IC 0.002" is measured on.**
   - What we know: prereg section 5 derives IR about 0.9 from IC 0.002 x sqrt(13 x 252 x 60),
     treating 0.002 as the IC of the tradeable per-slot bet.
   - What's unclear: with the HKS-shaped plant (flat persistence out to 40 days), member ICs
     differ by about sqrt(window): if 0.002 is P1's lag-1 IC, P4's is about 0.013 and the gate
     becomes vacuous (AGY's objection to 0.01); if it is the latent drift's IC, members see
     almost nothing and power is near the size.
   - Recommendation: define it as the per-slot cross-sectional rank IC of the population-best
     linear combination of the members (for a flat 40-day plant, about P4's IC), which is the
     reading consistent with the prereg's IR arithmetic. The owner pins it in the book spec
     before the power code is finalized; per the prereg, a mismatch is a methodology change.

2. **Breadth of the synthetic residuals.**
   - What we know: step 0 measured 51-66 effective bets at 1d after market and sector, 72 at
     15m (Epps-inflated), 95-120 after 10 PCs; the prereg's arithmetic used about 60.
   - Recommendation: pin a participation ratio of 60 in the book spec (conservative, matches
     the prereg), generated by a low-rank common component in the residuals.

3. **Do evidence runs need the power refusal?** D-03 lists `require_testable` for every
   real run; D-11 and the prereg define power for the book only. Recommendation: evidence
   runs check the shift count, record `power: null`, and never refuse on power; the book test
   runs the power check.

4. **Missing members at prediction time.** P4 needs 20 of 40 sessions; early rows have P1
   finite and P4 NaN. Recommendation: complete cases only for training and prediction (no
   imputation). The alternative (z = 0 for a missing member) is a fill.

5. **Rank-IC readout.** Architecture 3.5 and prereg section 5 mention the cross-sectional
   rank-IC readout "once it exists"; D-09 does not list it. Recommendation: out of scope
   unless the planner has slack; it gates nothing.

6. **Where the ridge output meets R1.** R1 ranks the combined alpha, so only the sign and
   relative size of the ridge coefficients matter. Worth one sentence in the book spec so no
   one tunes the penalty scale expecting a leverage effect.

## Environment availability

| Dependency | Required by | Available | Version | Fallback |
|---|---|---|---|---|
| Python venv | everything | yes | worktree `.venv` symlink | none needed |
| PostgreSQL / TimescaleDB | S0 (read), ledger (write), integration tests (`indicagent_test`) | yes | live on localhost | none |
| git | runner checks | yes | system | none |
| psql client | integration conftest rebuild | yes (used this session) | - | integration tests skip without it |
| Frozen artifacts for `repro_frozen.py` | D-16 | yes, `/home/bg/dev/indicagent/logs/phase179/rerun_e14`, `logs/phase181` | - | none; pass `--logs` from the worktree |
| CPU / RAM for the power run | D-12 | 24 cores, 29 GB (about 18 GB free) | - | fewer workers, longer wall |

Missing dependencies with no fallback: none. Migration 366 is not yet applied (verified:
`to_regclass('research_run')` is NULL; no `alpha.research.*` keys).

## Validation architecture

### Test framework
| Property | Value |
|----------|-------|
| Framework | pytest (`pytest.ini`, `--strict-markers`, asyncio auto) |
| Config file | `/home/bg/dev/indicagent-183/pytest.ini` |
| Quick run command | `.venv/bin/pytest tests/unit/research -q` (14 s today) |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |
| Bit identity | `.venv/bin/python scripts/analysis/sleeve_walk_forward/repro_frozen.py <scratch> --logs /home/bg/dev/indicagent/logs` (19 s) |
| DB tests | `.venv/bin/pytest tests/integration/test_research_ledger.py -m integration` (rebuilds `indicagent_test`, replays migrations above 234) |

### Phase requirements to test map
| Req | Behavior | Type | Automated command | File exists? |
|-----|----------|------|-------------------|--------------|
| D-13 | R1 legs sum to +0.5/-0.5 per row; floor 20 gives NaN; direction flips sign; ignores plan; vol NaN excludes name | unit, synthetic | `pytest tests/unit/research/test_portfolio_r1.py -q` | no, Wave 0 |
| D-14 | R2 on a 1-bar panel equals the default path; per-session sums match a slow loop; bootstrap block in sessions; observed and every shift aggregated alike | unit, synthetic | `pytest tests/unit/research/test_evaluate_session_scoring.py -q` | no, Wave 0 |
| D-16 | frozen 179/181 artifacts bit-identical | script, real frozen artifacts | `repro_frozen.py` as above | yes |
| D-01 | same content with different whitespace/comments hashes equal; `1e-4` unquoted rejected; extra key rejected; dotted path outside `families.` rejected; book hash moves when a family spec changes | unit | `pytest tests/unit/research/test_spec.py -q` | no, Wave 0 |
| D-02 | refuse: spec untracked, staged-only, modified; untracked or modified file under checked paths; accept clean; parse from HEAD blob | unit (temp git repo) | `pytest tests/unit/research/test_runner_git.py -q` | no, Wave 0 |
| D-02, D-07 | second real run for the same spec hash refused by Python and by the partial unique index | integration | `pytest tests/integration/test_research_ledger.py -m integration -k spec_once` | no, Wave 0 |
| D-07 | trigger: started to terminal once; terminal to anything raises; other column edits raise; snapshot_hash NULL to value only; DELETE and TRUNCATE raise | integration | `... -k trigger` | no, Wave 0 |
| D-08 | charged count rules (started, completed, failed charged; refused, guard_failed not; evidence never); refuse at M; APR keys seeded | integration | `... -k budget` | no, Wave 0 |
| D-05 | no other file writes `research_run` or construction `concept_registry` rows; legacy migrations 329-335 allow-listed; no stale entries | unit (repo grep) | `pytest tests/unit/research/test_ledger_sole_writer.py -q` | no, Wave 0 |
| D-03, D-04 | real mode calls ledger start before S0 and terminal after; crash leaves started (fake ledger, fake panel); synthetic mode never touches git or ledger | unit (fakes) | `pytest tests/unit/research/test_runner_order.py -q` | no, Wave 0 |
| D-09 | evidence JSON has every field, no NaN, no numpy types; book adds screen outcome | unit | `pytest tests/unit/research/test_runner_evidence.py -q` | no, Wave 0 |
| D-10 | ridge uses no row at or after `p - embargo + 1` (causality probe on the combiner); matches a slow per-fold `np.linalg.lstsq` reference; standardization from training rows only; recovers planted coefficients on a synthetic stack | unit, synthetic | `pytest tests/unit/research/test_combiner.py -q` | no, Wave 0 |
| D-11 | flattened roll equals joint roll; evaluate with book construction refits per shift (a counter or a planted-edge difference proves the null is not a post-fit shift); shifts whole sessions; refusal below 600 | unit, synthetic | `pytest tests/unit/research/test_book.py -q` | no, Wave 0 |
| D-12 | early-stopped decision equals full-set decision on random cases; curtailment equals fixed-R decision; b_max boundary arithmetic exact | unit | `pytest tests/unit/research/test_power.py -q` | no, Wave 0 |
| D-11 V2 | book null calibration: rejection rate at nominal 0.05 within binomial band on unplanted panels (small panels, few shifts) | slow, synthetic | `pytest tests/unit/research/test_book.py -m slow -q` | no, Wave 0 |
| D-15 | P1-P4 placement rows, slot sums, half-window rule, centred rank and floor, declared memory; `run_guards` passes on synthetic panels with a small FactorSpec; spec parses and resolves every dotted path | unit, synthetic | `pytest tests/unit/research/test_families_intraday.py -q` | no, Wave 0 |
| D-15 final plan | real evidence runs, then book v1, through the runner only | manual-by-runner, real data | `scripts/research/run_spec.py --spec research/specs/...` then ledger query | n/a |

Synthetic vs real: every automated check above is synthetic or uses the frozen 179/181
artifacts; only the final plan touches real 15m data, and only through the runner.

### Sampling rate
- Per task commit: `pytest tests/unit/research -q`, plus `repro_frozen.py` for any change
  under `src/intelligence/research/`.
- Per wave merge: `pytest tests/unit/ -q`; integration ledger tests after the migration plan.
- Phase gate: full unit suite green, `repro_frozen.py` bit-identical, integration ledger
  tests green, migration 366 applied live and committed.

### Wave 0 gaps
- [ ] `tests/unit/research/test_portfolio_r1.py`, `test_evaluate_session_scoring.py`
- [ ] `tests/unit/research/test_spec.py`, `test_runner_git.py`, `test_runner_order.py`, `test_runner_evidence.py`
- [ ] `tests/unit/research/test_combiner.py`, `test_book.py`, `test_power.py`, `test_synthetic.py`
- [ ] `tests/unit/research/test_families_intraday.py`, `test_ledger_sole_writer.py`
- [ ] `tests/integration/test_research_ledger.py` (reuse `test_concept_parent_lineage.py`'s connection and cleanup pattern; rows created with unique names)
- [ ] `slow` marker already registered in `pytest.ini`; no framework install needed

## Security domain

Local research tooling; no network surface, no user input beyond committed specs.

| ASVS category | Applies | Standard control |
|---|---|---|
| V2 authentication | no | local Postgres role |
| V3 session management | no | - |
| V4 access control | partly | S0 connections `default_transaction_read_only = on` (snapshot.py:55-62); ledger is the only write path; DB triggers enforce append-only |
| V5 input validation | yes | `yaml.safe_load` only, pydantic strict schema, dotted-path prefix allow-list before import |
| V6 cryptography | no (integrity hashing only) | `hashlib.sha256`, never a custom digest |

| Pattern | STRIDE | Mitigation |
|---|---|---|
| Spec names arbitrary code via dotted path | elevation | prefix allow-list `src.intelligence.research.families.` |
| YAML object construction | elevation | `safe_load`, never `load` |
| SQL built from spec strings | tampering | asyncpg `$n` parameters only |
| Ledger row edited after the fact | repudiation | BEFORE UPDATE/DELETE/TRUNCATE triggers, partial unique index |
| Artifact tampering | tampering | content-hashed snapshot verified before use; `.npy` with `allow_pickle=False` (store.py:37, 58) |

## Sources

### Primary (HIGH confidence, read or measured this session)
- `src/intelligence/research/evaluate.py` (lines cited inline), `portfolio.py`, `panel.py`,
  `factors.py`, `guards.py`, `signals.py`, `store.py`, `snapshot.py`
- `src/intelligence/statistics/panel_null.py` (shift_panel 44-54, admissible_shifts 20-41, Westfall-Young 57-86)
- `scripts/analysis/sleeve_walk_forward/{repro_frozen,synthetic,config,run,verdict}.py`
- `services/_batch_utils.py:759-774` (`make_worker_pool`), `services/ic_engine.py:5376-5415` (loaded-module hashing)
- `src/intelligence/portfolio/weighting.py:75-110` (`instrument_covariance` admission)
- `src/core/database_manager.py:19-40` (codecs, `connect_with_codecs`)
- `production/migrations/329_*`, `334_*`, `340_*`, `357_*`, `283_*` (lines 29-33)
- `tests/unit/test_migration_number_uniqueness.py`, `test_market_data_ohlcv_boundary.py`,
  `_source_grep_helpers.py`, `tests/integration/conftest.py` (cutoff 234), `test_concept_parent_lineage.py`
- Live DB (read-only): `\d concept_registry`, `\d concept_parent`, APR tables, construction rows (5, all deprecated), `alpha.validation.oos_start`, 15m span for SPY, compute_eligible count 233, `infra.*workers` keys
- `git ls-tree origin/main production/migrations/` (tops at 364)
- Timing runs: `repro_frozen.py`, pytest research suite, S1, plan_covariance, member/ridge/R1 prototypes
- Git plumbing behavior verified in a scratch repository

### Secondary
- `docs/plans/2026-09-25-alpha-research-architecture.md`, `2026-09-24-evidence-framework.md`,
  `2026-09-25-family1-intraday-periodicity-prereg.md`, `docs/research/measurement-residual-breadth.md`,
  `docs/foundation/unified-concept-registry.md`
- Besag, J. and Clifford, P. (1991), "Sequential Monte Carlo p-values", Biometrika 78(2) [ASSUMED from training knowledge; the stopping argument in pattern 9 is elementary and does not depend on the citation]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH, no new packages, versions read from the venv
- Architecture seams: HIGH, every seam cited to a line and the flatten trick reasoned from the code
- Runtime: MEDIUM-HIGH, components measured; the assembled book construction is a prototype
- Power design: MEDIUM, the exactness argument is sound; the planted-IC definition and breadth are owner inputs

**Research date:** 2026-09-25
**Valid until:** 2026-10-25, or earlier if phase 182 or another session changes `evaluate.py`, `portfolio.py` or migration numbering
