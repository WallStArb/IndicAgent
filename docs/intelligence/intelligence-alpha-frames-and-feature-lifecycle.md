# Feature lifecycle: data-quality governance of feature status

**Version:** 2.0.0
**Last Updated:** 2026-10-01
**Status:** current
**Milestone:** v3.5 (phase 186 plans 09, 19, 22)

This doc describes how a feature's `status` in `concept_registry` moves between `active` and
`shadow_only`. The filename keeps its original name so existing links resolve. The
`alpha_frames` hypothetical-trade layer, `CounterfactualTracker` and the ensemble interplay it
once covered were deleted in phase 186 (services in 186-19, tables dropped by migration 426 in
186-22); git history is the archive and the summary cards under `docs/research/summary-cards/`
record what those tables taught.

---

## Lifecycle state machine

**Base migration:** `production/migrations/169_feature_registry.sql` (Phase 140.5), since
superseded by `concept_registry`; lifecycle evidence lives in `concept_evaluation` (migration 357).

**States:** `candidate`, `active`, `shadow_only`, `deprecated`.

```
candidate ──(operator promotes)──► active ──(data_quality_fail)──► shadow_only
                                     ▲                                  │
                                     └────(data_quality_restored)───────┘

any state ──(operator_override only)──► deprecated
```

`deprecated` is operator-only, enforced in code: `ConceptRegistryService.record_transition()`
raises `ValueError` if an automated reason ever targets `'deprecated'`. An automated process can
move a feature between `active` and `shadow_only`; only a human can retire it
(`scripts/ops/alpha/ops_concept_registry_override.py`).

---

## What triggers a transition

`services/feature_lifecycle.py` is a `BaseBatch` oneshot that reads only persisted
`feature_vectors` rows. A governed feature (status `active` or `shadow_only`) must be:

1. computed: at least one non-NULL value at some timeframe over the span;
2. valid: no NaN or infinite value at any timeframe;
3. covered: at each timeframe where it is populated, the share of symbols carrying a value
   reaches `feature.coverage.min_symbol_fraction`.

The span is `[window_end - feature.lifecycle.lookback_days, window_end)`; the statistic is defined
once in `src/intelligence/statistics/feature_coverage.py`. Weak standalone IC never changes status
(design 11, E15: data that could contain signal stays computed).

One run evaluates one window and writes one `concept_evaluation` row per governed feature. The
primary key `(concept, window, evidence_key)` makes a rerun on identical evidence a no-op. Status
is derived from the ledger by the pure `derive_feature_transition`: `active` to `shadow_only`
after `feature.lifecycle.demotion_min_consecutive` failing windows in a row, `shadow_only` to
`active` after `feature.lifecycle.recovery_min_passes` passing windows. There is no calendar
clock, only evidence. `--dry-run` logs the transitions it would make without writing.

**Readers and writers**

- `feature_lifecycle.py` is the sole writer of automated feature transitions, through
  `ConceptRegistryService.record_transition()`.
- `ic_engine.py` reads `concept_registry` only for its membership and broadcast alignment gate and
  fingerprint watermark. It does not read or write lifecycle status.
- `scripts/ops/alpha/ops_canary_integrity_assert.py` reads
  `concept_registry.is_control`/`control_expectation` joined to `feature_ic_scores` and hard-halts
  the corpus pipeline if a negative-control canary clears significance in the pooled stratum, or
  the positive control fails to. It writes nothing to the registry and runs in
  `ops_corpus_pipeline_run.sh` before `feature_lifecycle`.

---

## `integrity_monitor`: decision audit trail

`integrity_monitor` is a table (`production/migrations/211_integrity_monitor.sql`), not a
service. Its `ic_lifecycle` facts are written by `feature_lifecycle.py` through
`emit_integrity_facts_async`. They are observability only; `concept_transition_log` is the
authoritative record of what transitioned. Schema (selected): `monitor_type`, `subject`
(NULL for run-level facts), `metric_name`, `metric_value`, `threshold_value`, `passed`,
`training_window_end`, `evaluated_at` (hypertable partition column, 3-month chunks).

---

## Invocation

`feature_lifecycle` is step 5 of `scripts/ops/corpus/ops_corpus_pipeline_run.sh`, which is
operator-invoked; no cron or systemd timer schedules it.

## See also

- `docs/foundation/unified-concept-registry.md`: the registry that owns feature status.
- `docs/plans/2026-09-26-unified-research-to-production-design.md` section 11: the design this node implements.
