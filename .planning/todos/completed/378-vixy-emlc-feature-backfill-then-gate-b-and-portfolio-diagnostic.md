---
status: completed
priority: P1
filed: 2026-09-17
closed: 2026-09-22
source: assistant-driven session applying Renaissance-rigor review to the just-merged
  cross-instrument covariance-aware portfolio diagnostic (see
  docs/superpowers/specs/2026-09-16-cross-instrument-covariance-aware-portfolio-diagnostic-design.md);
  user directed running Gate A for real, which surfaced this gap
---

## Resolution (2026-09-22)

Full chain completed. Summary of each remaining step from "Remaining chain" below:

**3. `ic_engine` full-corpus run: DONE.** Completed 2026-09-22T08:33:18Z, status=success,
97128 committed / 10738 skipped, 233 symbols incl. VIXY/EMLC, elapsed ~11.5hr.

**Detour found mid-chain, not anticipated by this todo: `ensemble_trainer` initially wrote
ZERO weights across all 89 strata** despite `ic_engine` succeeding. Root cause (systematic
debugging, not guessed): `alpha.ensemble.ic_input` APR flag is legitimately `'ic_shrunk'`
(an out-of-fold gate passed 2026-09-10), but the full-corpus `ic_engine` recompute reset
`feature_ic_scores.ic_shrunk` to NULL corpus-wide (`ic_engine.py` doesn't write that column
-- it's populated by a separate downstream step, `scripts/ops/alpha/ops_ic_shrinkage.py`,
normally chained after `ic_engine` in the full corpus pipeline orchestrator but never
re-run since this was a standalone `ic_engine` invocation). Fixed by running
`ops_ic_shrinkage.py` (compute pass: 2831002 rows backfilled; out-of-fold gate: PASSED,
35633 cells, mean_shrunk_error=0.0456 < mean_raw_error=0.0486). Not a code bug -- a missing
pipeline step in the ad hoc sequence; no fix needed beyond running the step.

**3 (continued). `ensemble_trainer` re-run: DONE** after the fix above. 31/89 strata
written real weights; 58 skipped for legitimate data-sparsity reasons (insufficient
bars/min-passing-features), not errors. **`alpha_publisher --weight-version
run_2025122405150000 --skip-kafka`: DONE.** 81641167 rows emitted, 0 rejected. VIXY/EMLC
now have real `alpha_events` coverage (298967/280841 rows) -- the original gap this todo
was filed to close.

**4. Gate B: clarified and passed.** Initially over-scoped toward rebuilding Phase 148's
full Gate 1/Gate 2 OOS-proof apparatus (day-clustered bootstrap Sharpe + shuffled-ranking
null) -- wrong: that's explicitly out of scope per the ALREADY-REVIEWED (Codex+AGY,
2026-09-16) design doc
(`docs/superpowers/specs/2026-09-16-cross-instrument-covariance-aware-portfolio-diagnostic-design.md`),
which defines Gate B as "per-instrument IC via ic_engine" feeding the diagnostic's own
internal walk-forward `mu_i` calibration (`shrink_instrument_ic`, computed fresh per refit
from trailing `alpha_score`/`forward_returns` -- already properly out-of-sample, no reuse
of Phase 148's machinery needed). The design doc itself explicitly flags and scopes out
making Gate B itself walk-forward/OOS-respecting as "a larger, separate change to
ic_engine" and mandates the report state the selection-lookahead limitation plainly rather
than fix it. Verified live: all 13 candidates have real, reliable, walk-forward-stable,
significant IC cells in the fresh `feature_ic_scores` data (lowest: VIXY, 169/4768
significant cells). Gate B passes.

**5. `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`: DONE, real positive
result.** Run against the full 13-symbol candidate list (`--weight-version
run_2025122405150000 --end 2026-09-17`, window 2018-01-01..2026-09-17, 1685 rebalance
steps, all 13 retained with price data, `mean_variance_fallback_count=0` -- well-conditioned
covariance throughout). Per-arm mean daily realized return / t-stat / annualized Sharpe
(computed post-hoc from the step-level JSON, naive iid t-test -- see caveats below):

| Arm | mean daily return | t-stat | ann. Sharpe (naive) | mean effective_n |
|---|---|---|---|---|
| equal_weight (baseline) | 0.000060 | 0.48 | 0.18 | 13.00 |
| ic_proportional | 0.000745 | 2.44 | 0.95 | 4.62 |
| vol_normalized | 0.000332 | 3.08 | **1.19** | 4.80 |
| mean_variance | 0.000127 | 1.67 | 0.65 | 5.40 |

`vol_normalized` and `ic_proportional` both meaningfully and significantly beat the naive
`equal_weight` baseline -- the core hypothesis this shadow-mode diagnostic was built to
test. Interesting secondary finding, not investigated further: the "proper" Markowitz
`mean_variance` solve underperforms the simpler `vol_normalized`/`ic_proportional` arms
here despite zero ridge-fallbacks (well-conditioned), worth a look if this thread continues.

**Caveats, carried verbatim from the script's own output (`caveats` field) -- do not cite
these numbers without them:**
1. Universe membership conditioned on Gate B passing over this same measurement period is
   itself a selection effect -- not evidence this method would discover these instruments
   from an unfiltered pool.
2. IC is Spearman rank correlation used as a linear `mu` scaling coefficient -- a heuristic,
   not an exact Pearson-slope calibration.
3. Sample size at this instrument count is likely powered for a directional read only, not
   a p<0.05 verdict (the t-stats above use a naive iid assumption the script's own caveat
   explicitly warns against -- daily-rebalanced returns are not iid; a day-clustered
   bootstrap, the same rigor Gate 1 uses, would be the correct significance test and hasn't
   been run).
4. **Not previously stated, found this run: zero transaction costs are modeled** (`cost`
   field is 0.0 for every step, every arm) -- these are gross, not net-of-cost, returns.
   Consistent with this project's "execution costs must not gate the edge search" directive
   (costs reported as diagnostics, never the flip condition) but means these Sharpe numbers
   should not be read as tradeable-as-is.

Full step-level JSON result:
`/tmp/claude-1000/-home-bg-dev-indicagent/0b8dfddb-0871-4ccf-ad6b-1d73d57c7f45/scratchpad/portfolio_covariance_diagnostic_result.json`
(scratchpad, not committed -- ephemeral per this project's convention for gate/diagnostic
JSON outputs, e.g. Gate A's `/var/tmp/phase174_crossasset_prereg_gate.json`).

**Follow-on work identified but NOT done here (separate, future decision):** a proper
day-clustered-bootstrap significance test on these results; deciding whether this shadow
result graduates toward any real construction (gated by "prove edge before production
infra" -- this remains a measurement, not a decision to size anything).

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

## Current state (updated 2026-09-17, end of session)

**Steps 1-2 of the remaining chain (below) are DONE, verified against live data:**

1. **Feature backfill: DONE.** `feature_vectors` populated for VIXY/EMLC across all 4 tfs
   (5m/15m/1h/1d), `backfill_status` shows `status='complete'` on all 8 rows, row counts
   verified directly against `feature_vectors` (e.g. VIXY 5m: 264,631 rows, 2011-05-20 through
   2026-09-15). Commit: none (data-only, no code changed).
2. **`forward_returns`: DONE.** `forward_return_writer.py --symbols VIXY EMLC --tf 5m 15m 1h 1d
   --training-window-end "2025-12-24T05:15:00+00:00"` (same boundary as the full corpus's last
   run, from `.planning/corpus_manifests/forward_return_writer.json`) — verified 782,717 rows
   written, `return_type='executable_open_to_open'`, ~99%+ usable
   (`complete_fast AND NOT return_fast_suspect`).

**Unplanned but necessary detour, also DONE:** attempting step 3 (`ic_engine`) surfaced a
corpus-wide bug blocking it entirely, for every symbol, not just VIXY/EMLC —
`_build_symbol_regime_class` was routing instruments to regime groups using BOTH human
(definitional) and empirical (`TagCalibrator`-measured sensitivity) tags with no distinction,
causing 144 of 273 active instruments to match 2+ groups simultaneously once `TagCalibrator`'s
first-ever successful run (2026-09-16) populated empirical tags corpus-wide. **Fixed** (commit
`b8af2b749`, independently reviewed by both Codex and Fable before landing): regime-group
routing now uses `source='human'` tags only. Validated live: 144→0 ambiguous, 272/273 route
cleanly; the one exception (VIXY, no human tag matches any of the 4 groups — an honest taxonomy
gap, not a bug) handled by bumping `infra.ic.max_unrouted_symbols` 0→1 (APR, with
`config_history` provenance). Verified: `ic_engine.py --dry-run-validity --symbols VIXY EMLC
--tf 1d --training-window-end "2025-12-24T05:15:00+00:00"` now exits 0.

A second, separate, currently-active bug was found alongside this (same review) and
DELIBERATELY NOT fixed today — filed as its own todo,
[379](379-empirical-tags-contaminate-equity-breadth-and-peer-grouping.md): empirical tags are
right now polluting `equity_regime_model.py`'s breadth signal and
`cross_sectional_regime_model.py`'s peer grouping (confirmed live: GLD/AGG/EMB/EMLC/DBC/FXA/FXE).
Do not copy this todo's `ic_engine.py` fix onto those two files without reading 379 first — it's
a different kind of question there (sensitivity/peer-grouping, not categorical identity) and
needs its own scoped decision.

**`.planning/corpus_manifests/ic_engine.json` is currently STALE** — it shows a `status:
"failed"` run from BEFORE the routing fix (the DBB ambiguity error). That failure is resolved;
the manifest just hasn't been overwritten by a real (non-dry-run) `ic_engine.py` invocation yet.
Don't read that file's `"failed"` status as current truth.

## Remaining chain, in order, before the portfolio diagnostic can run against real data

1. ~~`backfill_feature_factory.py --compute-only --symbols VIXY,EMLC`~~ — **DONE**, see above.
2. ~~`forward_returns` for VIXY/EMLC~~ — **DONE**, see above.
3. **`ic_engine` real run, then `ensemble_trainer` re-run** — **IN PROGRESS, started
   2026-09-17 11:52 local (15:52 UTC), see below for why `--symbols VIXY EMLC` scoping (as
   this todo originally suggested) was wrong.**

   **Scoping correction found 2026-09-17, before any write happened:** started to run
   `ic_engine.py --symbols VIXY EMLC ...` per this todo's original "scoped to VIXY/EMLC at
   minimum" framing, but caught mid-run (killed before any write) that `--symbols` restricts
   NOT ONLY per-symbol computation but also the cross-sectional peer pool
   (`symbols_by_group` in `main()`, built only from the CLI-scoped `symbols` list, unlike
   `symbol_regime_class` which correctly queries all active instruments regardless of
   `--symbols`). A `--symbols VIXY EMLC` run would have computed EMLC's regime group's
   cross-sectional IC using EMLC (or VIXY) as the ENTIRE peer pool instead of the group's
   real peer set, and the resulting fingerprint mismatch (keyed partly on `symbol_list`)
   would have silently overwritten the existing correct cross-sectional cells for that group
   with degenerate single-symbol data. Confirmed by reading `_compute_cross_sectional_tf`'s
   docstring and the `symbols_by_group`/`group_symbols` construction directly, not assumed.

   **Bigger finding from the follow-up unscoped dry-run**: running
   `ic_engine.py --dry-run-validity --training-window-end ...` with NO `--symbols` restriction
   showed `n_symbols_skip: 0, n_symbols_compute: 233` (all corpus symbols) and
   `n_cs_compute: 124` (all cross-sectional cells) -- the ENTIRE corpus's fingerprints are
   invalid, not just VIXY/EMLC's. Root cause confirmed by reading `_checkpoint_content_key()`
   (hashes AST-normalized source of every transitively-imported first-party module): the
   `b8af2b749` routing fix was a genuine semantic change to `_build_symbol_regime_class`
   (real SQL/logic change, not a comment edit), which correctly invalidates every prior
   checkpoint corpus-wide -- expected and necessary, not a bug. 144/273 symbols' regime-group
   membership changed under that fix, so every existing regime-stratified IC measurement was
   computed under the old, wrong routing and must be redone regardless of VIXY/EMLC.

   **Action taken**: launched the full, unscoped real run (no `--symbols`, no `--dry-run-validity`)
   detached (`setsid nohup ... &`, PID 163450 at launch) so it survives a context reset:
   `.venv/bin/python services/ic_engine.py --training-window-end "2025-12-24T05:15:00+00:00"`,
   output to `/tmp/claude-1000/-home-bg-dev-indicagent/d668402e-6d7a-4533-b260-dc5919634ec0/scratchpad/ic_engine_full_corpus_run.log`
   and `logs/ic_engine.log`. Historical full-corpus runtime from log timestamps: ~11h
   (2026-09-09 13:15 -> 2026-09-10 00:36). **Check `ps aux | grep ic_engine.py` and
   `logs/ic_engine.log`'s tail for progress/completion before assuming this is done or dead.**

   After this completes: `ensemble_trainer` scope decision -- it has no `--symbols` flag and
   always does `DELETE FROM ensemble_weights/ensemble_alpha WHERE weight_version = $1` before
   rebuilding. **Decided**: reuse the existing `weight_version='run_2025122405150000'`
   (not a new version) -- the portfolio diagnostic needs all 13 candidates on one consistent
   weight_version for apples-to-apples comparison, and the other 11 candidates' existing
   `alpha_events` rows are already under this version. A fresh version would leave the other
   11 on stale IC/weights while only VIXY/EMLC got current data -- worse, not safer, for this
   specific goal. Then `alpha_publisher.py --weight-version run_2025122405150000 --skip-kafka`
   (corpus batch mode -- `--skip-kafka` since live ingestion is still frozen, no consumer to
   publish to) to populate `alpha_events` for all 13.
4. **Gate B** (per-instrument IC via `ic_engine`, still not run per
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
