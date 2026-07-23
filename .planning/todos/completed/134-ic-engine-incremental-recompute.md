---
**Created:** 2026-07-18
**Area:** intelligence / infra
**Type:** architecture
**Priority:** not yet triaged (correctly — this file's own "Sizing" section says size as a GSD
  phase, not a quick todo; registered as ROADMAP **Phase 162** 2026-07-18, plan 162-02 by name).
  Moved to deferred/ same day (priorities/matrix reconciliation pass) alongside siblings
  [122](122-ic-engine-checkpoint-blind-to-apr-config-drift.md) (absorbed here) and
  [133](133-cross-sectional-bootstrap-threads-not-per-tf.md) (162-01) for consistency — all
  three are Phase 162 raw material. Revive at `/gsd-plan-phase 162`.
**Effort:** multi-day (design + validity-check plumbing + migration for persisted fingerprint + benchmark)
**Benefit:** turns full-corpus-every-run into recompute-only-what-changed; the precondition for
  ic_engine to ever run on a cadence (nightly or otherwise) or scale past ~80 symbols
**Risk:** medium — a wrong staleness definition silently serves stale IC to live trading, the
  same failure class the 2026-07-12 checkpoint-invalidation incident was about, just cross-run
  instead of intra-run
**Gate:** none on the prove-edge-first decision — corrected 2026-07-18, see
  [[project_prove_edge_before_production_infra]]'s correction note: `ic_engine` is the
  discovery/measurement mechanism, not a downstream consumer of unproven alpha, so that gate
  doesn't apply here. The real constraint is mundane resource contention — don't design/benchmark
  changes to `ic_engine.py` while the in-flight 143.1-07 corpus run is saturating the same 8
  workers (check `ps aux | grep ic_engine`; was 73/80 symbols as of 2026-07-18 12:11 UTC, likely
  finishes same day). Safe to start design/planning once that run completes.
---

**CLOSED 2026-07-23 — shipped as ROADMAP Phase 162 (4/4 plans), fully executed.** The whole-cell
`ic_cell_fingerprints` mechanism this todo proposed is live: code content-key + APR snapshot +
upstream watermarks, DELETE-then-recompute invalidation, empirically proven equivalent to a
forced `--refresh` recompute (`ops_ic_fingerprint_equivalence.py`, byte-identical
`feature_ic_scores`). A real BLOCKER (per-symbol cross-sectional watermark scoping) was found via
code review and fixed same session. Full-corpus wall-clock/surgical-invalidation benchmarks
(this file's own "benefit" claim) are tracked as open human-verification items in
`162-HUMAN-UAT.md`, not a reason to keep this todo open — the mechanism is shipped and proven at
the 5-symbol scale; only the 80-symbol timing measurement remains.

**Status (moved pending/ 2026-07-18, was briefly filed deferred/ same day):** Surfaced from a
scaling conversation about whether the current corpus pipeline could handle 1000 symbols — it
can't, at anything resembling a nightly cadence, purely because every run recomputes the entire
universe from scratch. Initially filed deferred/ under the prove-edge-first sequencing decision,
which was a mis-application — that decision targets downstream consumers of unproven alpha
(execution, portfolio construction, decay monitoring), not the measurement mechanism itself. See
the Gate line above and the memory's correction note.

# 134 — ic_engine has no incremental recompute; every run is O(full universe)

## Problem

`ic_engine.py --from-step 5` recomputes IC for every (symbol × tf × regime × feature) cell on
every invocation, regardless of whether anything about that cell actually changed since the last
successful write. Confirmed live during the 143.1-07 corpus re-run (started 2026-07-17, still
in-flight as of 2026-07-18): 80 symbols take ~25-30h wall clock at 8-way `ProcessPoolExecutor`
parallelism (`infra.ic_engine.workers=8`), dominated by circular block bootstrap CI (2000
resamples × ~150 features × ~7 regimes × 4 timeframes per symbol, deliberately run as a serial
per-worker Python loop — `ic_math.py:240-261` — because the vectorized broadcast form OOM-kills
workers at production scale).

Linear scaling to 1000 symbols (12.5x the current universe) puts the per-symbol pass alone at
~13-16 days, before the cross-sectional pass, `ic_shrinkage`, `ensemble_trainer`, and
`alpha_publisher` stages run. There is also currently no scheduler at all (`systemctl
list-timers`/`crontab -l` both confirmed empty 2026-07-18) — every run is a manual, full-corpus,
multi-day commitment. Neither fact is sustainable past the current 80-symbol/manual-cadence
regime.

The existing content-keyed checkpoint system (`_checkpoint_content_key()`, added for crash-resume
within a single run) is the wrong tool for this: it invalidates on Python source changes only,
gets deleted on successful run completion, and has no persisted cross-run memory of "this cell
was already computed correctly, skip it." Todo 122 already flagged the narrower version of this
gap (APR config drift mid-run, not caught by the code-only content key).

## Proposed scope

Add a per-cell validity check ahead of compute, so a fresh invocation only recomputes cells whose
last result is actually stale:

1. **Persist a fingerprint per computed cell** — extend what `feature_ic_scores` already tracks
   (`computed_at`, `training_window_end`) with the code content_key and a snapshot of the
   routing/computation-affecting APR keys the cell was computed under (same enumeration task as
   todo 122, generalized from intra-run to cross-run).
2. **Validity check before the compute loop, not a checkpoint dir** — for each (symbol, tf,
   regime) cell: does a row exist whose fingerprint (code + APR snapshot) matches current state,
   and is its `training_window_end` still within the staleness threshold for that symbol/tf? If
   yes, skip; if no, queue for compute.
3. **Staleness threshold is the real design question, not a mechanical one** — how much new bar
   data (or how much wall-clock time) before a cell is considered stale enough to warrant refit,
   independent of code/config changes? Needs an empirical answer (e.g., does IC materially drift
   within N days at this corpus's actual bar cadence per tf), not a guessed constant — this is
   the part that determines whether incremental recompute is a real win or a false economy that
   quietly serves stale IC to live trading.
4. Absorb todo 122's scope into this (same fingerprint mechanism solves both the intra-run and
   cross-run versions of "was this cell computed under config that's since changed").

## Sizing

**Size this as a GSD phase (`/gsd-discuss-phase`), not a quick todo.** Multi-day
effort, a real open design question (the staleness threshold — item 3 above), a schema/migration,
and correctness risk to live trading if the staleness definition is wrong. Todo 122 stays
todo-sized (narrow checkpoint fingerprint extension, no open design question) and doesn't need to
wait for or become part of this phase — it can still land standalone if an APR-drift incident
forces the issue before 134's phase is discussed/planned.

## References

- `services/ic_engine.py` — `_checkpoint_content_key()`, main() compute loop, `ProcessPoolExecutor(max_workers=n_workers)`
- `src/intelligence/statistics/ic_math.py:205-314` — `_circular_block_bootstrap_ic`, the dominant per-cell cost
- `scripts/ops/corpus/ops_corpus_pipeline_run.sh` — the 8-step pipeline this would need to fit into
- [122](122-ic-engine-checkpoint-blind-to-apr-config-drift.md) — narrower, subsumed version of the fingerprint-staleness gap
- [[project_corpus_pipeline_state]], [[project_prove_edge_before_production_infra]]
