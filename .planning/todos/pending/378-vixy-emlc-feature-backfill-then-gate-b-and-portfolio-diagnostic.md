---
status: pending
priority: P1
filed: 2026-09-17
source: assistant-driven session applying Renaissance-rigor review to the just-merged
  cross-instrument covariance-aware portfolio diagnostic (see
  docs/superpowers/specs/2026-09-16-cross-instrument-covariance-aware-portfolio-diagnostic-design.md);
  user directed running Gate A for real, which surfaced this gap
---

# VIXY/EMLC feature backfill in progress, then Gate B, then the portfolio diagnostic needs a real run

## What

Gate A (`scripts/analysis/universe_expansion_correlation_structure_check.py`) was run for the
first time ever against the Phase 174 cross-asset candidate list (2026-09-17) and **PASSED**:
unconditional avg pairwise correlation 0.0879 (threshold ≤0.10), `high_bear` 0.1309 (threshold
≤0.30), all 13 symbols retained, `n_eff` 6.33 unconditional. Full result:
`/var/tmp/phase174_crossasset_prereg_gate.json`. This is the first real, measured evidence in
the whole cross-asset thread — previously only a hypothesis. See
[[project_phase174_closed_cross_asset_pivot]].

Checking whether Gate B (per-instrument IC, `ic_engine`) could run next surfaced: only 11 of
13 candidates have ever been scored (`alpha_events`, `weight_version='run_2025122405150000'`,
tf=1d). **VIXY and EMLC have zero `alpha_events` rows.** Root-caused precisely (not assumed):
both were onboarded into `instruments` on 2026-09-16 (`created_at` confirms it) as part of the
same-day cross-asset pre-registration work — price history backfilled fine
(`backfill_status.fetch_complete = true` for all 4 tfs), but the feature-computation stage
(`backfill_feature_factory.py --compute-only`) was never triggered. Not a bug, an unfinished
onboarding step.

## Current state (as of this todo being filed)

`services/backfill_feature_factory.py --compute-only --symbols VIXY,EMLC --refresh` is running
in the background (PID at filing time: 4138555, started 2026-09-17 06:28 local). Confirmed
genuinely computing (forkserver worker subprocesses pegged ~130% CPU each), not stuck — the
first attempt (with a `timeout 580` wrapper) got killed mid-run by the wrapper, not by an
error, leaving all 8 `backfill_status` rows (VIXY/EMLC × 4 tfs) stuck at `in_progress` with no
`completed_at`; the `--refresh` re-run bypasses that ambiguous checkpoint state and forces a
clean recompute. Log output is fully buffered (0 bytes written to
`/tmp/.../scratchpad/vixy_emlc_backfill.log` despite real CPU activity) — check
`backfill_status`/`feature_vectors` row counts directly rather than trusting the log file for
progress, until the process exits.

## Remaining chain, in order, before the portfolio diagnostic can run against real data

1. **`backfill_feature_factory.py --compute-only --symbols VIXY,EMLC`** — in progress, see above.
   Verify on resume: `SELECT symbol, tf, status, completed_at FROM backfill_status WHERE symbol
   IN ('VIXY','EMLC')` — all 8 rows should show `status='complete'`.
2. **`forward_returns` for VIXY/EMLC** — not yet computed (confirmed zero rows before this
   backfill started). Find and run whatever writer populates `forward_returns` from
   `feature_vectors` (`forward_return_writer` per root CLAUDE.md's pipeline description) scoped
   to these two symbols, or as part of its normal incremental sweep once `feature_vectors`
   exist for them.
3. **`ic_engine` / `ensemble_trainer` re-run** — VIXY/EMLC need to enter a `weight_version`
   before `alpha_publisher` can emit `alpha_events` for them. Check whether `ensemble_trainer`
   can be scoped to just these 2 new symbols against the EXISTING `weight_version` cohort, or
   whether getting them in requires a fresh full-corpus `ensemble_trainer` run (a much bigger,
   more consequential operation — do not run this without confirming scope first, per this
   project's own "measure twice" discipline on anything touching the shared `weight_version`
   epoch other symbols already depend on).
4. **Gate B** (per-instrument IC via `ic_engine`, referenced but not yet run per
   [[project_phase174_closed_cross_asset_pivot]]) — run against all 13 once VIXY/EMLC are
   scored, or against the 11 already-scored now if closing the VIXY/EMLC gap turns out to be
   more than a quick follow-on.
5. **`scripts/analysis/portfolio_covariance_weighting_diagnostic.py`** (merged to `main`
   2026-09-16, 27 unit tests, never run against real data) — run only after Gate B, per its own
   design (Gate B's per-instrument IC feeds the `mu_i` calibration; see
   [[project_portfolio_covariance_weighting_diagnostic]]). Recommended first pass: a small,
   intuitively-obvious sanity cohort before trusting output on the full candidate list.

## Cross-refs

- [[project_phase174_closed_cross_asset_pivot]] — the cross-asset candidate list and its
  construction history.
- [[project_portfolio_covariance_weighting_diagnostic]] — the diagnostic itself, its design
  history, and the bugs found/fixed during its own code review.
- `/var/tmp/phase174_crossasset_prereg_gate.json` — Gate A's full result.
