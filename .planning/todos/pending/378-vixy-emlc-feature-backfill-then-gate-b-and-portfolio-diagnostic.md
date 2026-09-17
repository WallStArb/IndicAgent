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
