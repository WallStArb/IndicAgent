---
status: completed
priority: P2
filed: 2026-07-19
started: 2026-07-20
completed: 2026-07-20
source: /simplify altitude review of todo 148 (services/forward_return_writer.py's
  return_{scale}_suspect guard) -- the review agent flagged that the fix landed two
  layers downstream of where the defect actually enters the system.
---

## Disposition (2026-07-20)

Shipped to `main` (`dabf5fc5`, fast-forwarded from branch `todo-149-price-sanity-guard`,
rebased onto main's tip first since main had gained one docs-only commit in the interim).
Design: `docs/superpowers/specs/2026-07-20-bar-ingestion-price-sanity-guard-design.md`. Plan:
`docs/superpowers/plans/2026-07-20-bar-ingestion-price-sanity-guard.md`. All 6 tasks complete,
each individually reviewed and approved, plus a final whole-branch review (Opus) before merge.
Full suite green throughout (4311 passed, 3 pre-existing skips, 0 failures).

**What shipped:** `price_sanity_status` tri-state column on `market_data_ohlcv`
(NULL=unaudited/`plausible`/`confirmed_corrupt`/`market_event`/`ambiguous`), a NULL-safe view
predicate on `market_data_ohlcv_tradeable` (`IS DISTINCT FROM 'confirmed_corrupt'`), a partial
index, 3 APR keys, and an 18-row reconciliation of todo 151's earlier corrections onto the new
column (Task 1). Classification logic (`classify_candidate_bar`, `apply_cross_symbol_downgrade`,
`build_subject_key`) promoted to a new shared module `src/intelligence/statistics/price_sanity.py`
(Task 2), plus a new batched async cross-symbol corroboration primitive,
`count_corroborating_symbols_batch()` (Task 3, exact-match mode only -- window-mode deliberately
deferred). `ops_known_corrupt_print_cleanup.py`'s `--apply` unified onto `price_sanity_status`,
replacing its old `volume=0` mechanism (Task 4). A new bounded audit task,
`BarAuditor._run_price_sanity_audit()`, wired into the existing `BarAuditor` service with its
own small `asyncpg.Pool` (isolated from gap-detection's pool), classifying + corroborating +
writing verdicts every 5-minute cycle, with full OTel metrics added in final review (Task 5).

**Two real, non-obvious TimescaleDB compressed-hypertable cost traps** found only by live
execution during Task 1 (not visible from code/SQL review): a reconciliation `UPDATE` driven
from `WHERE volume=0` scanned the whole ~215M-row table instead of 18 known rows; and even
correctly joined on primary-key columns, the write was still slow because 248/250 chunks are
compressed -- a read-only `SELECT` test was misleadingly fast and didn't exercise the write
path's decompression cost. Both documented in the migration file's own comments. Worth
remembering for any future migration touching `market_data_ohlcv`.

**Live pilot (Task 6) surfaced a real rollout-pacing problem, resolved by judgment, not
deferred:** at the default batch size (500/cycle) and BarAuditor's existing 300s cadence,
clearing the 215.6M-row historical backlog would take ~4.1 years. Decided NOT to raise the
daemon's batch size to compensate (risks exceeding `indicagent-bar-auditor.service`'s
`WatchdogSec=60`, and conflates a one-time historical-debt problem with the daemon's actual
job of auditing the live incoming stream) -- filed `todo 155` for a dedicated one-time backfill
tool instead. Also surfaced (and captured in 155) that oldest-first candidate ordering means
the guard provides **no live-stream protection** until that backfill lands, not just no
historical coverage.

**Final whole-branch review** (Opus) found the new audit task had zero OTel metrics --
fixed pre-merge (commit `e5d0d8e7` on the branch, rebased to `dabf5fc5` on main): added
`bar_auditor_price_sanity_rows_classified_total`, `..._audit_errors_total`, and
`..._audit_duration_seconds`, plus 3 minor polish fixes (migration DR comment, boundary
allow-list completeness, pool-sizing comment). A user question during this same session about
end-to-end traceability prompted two broader architecture follow-ups, filed separately: `todo
156` (OTel SPAN coverage gaps in the v3.0 critical path -- `ensemble_trainer.py`/
`alpha_publisher.py` have zero spans, distinct from the metrics fixed here) and `todo 157` (no
mechanical check enforces base-class reuse or observability wiring at all -- convention/review
only, unlike the naming/boundary checks this project's pre-commit hook does enforce).

## Problem

Todo 148 added a price-sanity guard (`return_{scale}_suspect`, sqrt-scaled per-tf
ceilings) to `forward_returns`, catching the specific failure mode that poisoned the
EM-CAL sweep: a corrupt IBKR print (UUP 5m 2007-06-20: `open=1000` on a ~$25 ETF,
`volume=200`) that passes `market_data_ohlcv_tradeable` (`WHERE volume > 0` only --
no price check) and fabricates a 368% "executable" forward return.

That fix protects `forward_returns` and its own downstream consumers
(`ops_emission_threshold_sweep.py`, `ops_ic_shrinkage.py`, `EnsembleICEngine`,
`ops_cost_hurdle_calibration.py` -- all patched same-session). But the corrupt bar
itself still flows unguarded through `market_data_ohlcv` into every OTHER consumer
that reads OHLCV directly, none of which get any protection from the 148 fix:
`services/backfill_feature_factory.py`, `services/equity_regime_model.py`,
`services/cross_sectional_regime_model.py`, `services/regime_writer.py`,
`services/counterfactual_tracker.py`, and any future consumer. `ProviderMerger` (the
sole writer to `market.bars` per DAG Invariant 1) currently applies no price
plausibility check at all.

## References

- `docs/superpowers/specs/2026-07-20-bar-ingestion-price-sanity-guard-design.md`
- `docs/superpowers/plans/2026-07-20-bar-ingestion-price-sanity-guard.md`
- `.planning/todos/pending/155-price-sanity-status-historical-backfill.md` -- rollout-pacing
  follow-up
- `.planning/todos/pending/156-otel-span-coverage-gap-v3-pipeline.md` -- tracing gap found in
  final review
- `.planning/todos/pending/157-no-mechanical-base-class-compliance-check.md` -- broader
  enforcement gap found investigating 156
- `src/intelligence/statistics/price_sanity.py` -- shared classification/corroboration module
- `services/bar_auditor.py` -- live audit task
