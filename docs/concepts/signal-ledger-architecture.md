# Signal Ledger Architecture (SLA)

**Version:** 1.0
**Status:** stale (v2.x, see banner)
**Last Updated:** 2026-06-16
**Tags:** sla, signal-events, trade-frames, trade-executions, counterfactual, ml-training, survivorship-bias

> Every signal fire, every trade hypothesis, every execution — three concerns, three tables, one unbiased training set.

---

> **Staleness note (2026-08-01):** This doc describes the Signal Ledger Architecture
> (`signal_events`/`trade_frames`/`trade_executions`/`signal_ledger`) as the live ML training
> foundation. That v2.x SLA has no live consumer as of 2026-07-02 per CLAUDE.md;
> `feature_vectors` is the current training corpus. Not yet rewritten for v3.0 -- tracked for a
> future doc pass, not fixed here.

## What the SLA Is

The **Signal Ledger Architecture** is the three-table schema that captures the complete signal lifecycle: `signal_events` (detection) + `trade_frames` (hypothesis) + `trade_executions` (execution), with a join view (`signal_ledger`) as the canonical query surface (renamed from `signal_ledger_full` in Phase 130).

The design replaces the legacy `signal_ledger` monolith, which mixed all three concerns in 47 columns across a single table. The separation is not cosmetic — it is what makes an unbiased ML training set possible.

---

## What the Monolith Conflated

The legacy `signal_ledger` mixed three semantically distinct categories of data:

**Detection state** — what the I7 plugin observed: `raw_confidence`, `cis_score`, `factor_scores`, `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `hmm_regime_at_fire`, `garch_sigma_at_fire`.

**Hypothesis state** — what trade entry was proposed: `entry_price`, `stop_loss`, `targets`, `entry_zone_low`, `entry_zone_high`, `entry_type`, `ttl_bars`, `trailing_stop_price`.

**Execution state** — what actually happened: shadow lifecycle fields (`shadow_mae`, `shadow_mfe`, `shadow_outcome`), `pnl_r`, `outcome`.

Mixing these three concerns in one table creates the Bias Layer 2 problem: to train on outcomes, you must join on `pnl_r IS NOT NULL`, which silently excludes all signals that were never executed (regime-suppressed, unfilled). The model learns "among signals that were executed, which ones worked" — a fundamentally different question than "among all signals that fired, which ones were worth executing."

---

## Why Three Tables

### The Separation of Concerns

Each table owns exactly one semantic concern and is immutable after its write contract completes:

**`signal_events`** answers: *did the pattern fire?*
Written once at I7 emit time. Carries intrinsic quality (`raw_confidence`, `factor_scores`) and extrinsic market context at fire time (ECL vectors: `ctf_score`, `ctf_confirmed`, `zone_friction_score`). Never updated after initial write, except `status` (lifecycle transitions).

**`trade_frames`** answers: *what trade was hypothesized?*
One row per `entry_type` per signal fire. `at_close` and `at_pullback` produce two rows; a plugin that proposes only one entry type produces one row. The key design decision: `counterfactual_pnl_r` lives here, populated by CounterfactualTracker for every row regardless of whether the trade was ever executed.

**`trade_executions`** answers: *what was actually traded?*
One row per live execution. Most trade frames have zero rows here. `actual_pnl_r` is the realized outcome; it is only meaningful relative to the counterfactual when comparing execution quality to the hypothetical.

### Why Counterfactual Goes on `trade_frames`, Not `signal_events`

The counterfactual is measured at the `entry_type` level, not at the signal level. A signal with `at_close` and `at_pullback` frames may have `counterfactual_pnl_r = +1.2R` for the `at_close` frame and `counterfactual_pnl_r = +2.8R` for the `at_pullback` frame — because the pullback never triggered and then the target was hit anyway. These are different hypotheses from the same signal event.

If counterfactual were on `signal_events`, it would have to be the aggregate across entry types, losing the ability to learn which entry type adds the most value. The frame-level granularity is required for ML to optimize entry selection.
<!-- src: production/migrations/137_3table_schema.sql -->

---

## The Training Set Problem This Solves

### Before SLA: Selection Bias on Execution

With the monolith, ML training queries looked like this:

```sql
SELECT feature_vector, pnl_r FROM signal_ledger
WHERE pnl_r IS NOT NULL;
```

`pnl_r IS NOT NULL` implicitly means `trade was executed`. The training set is the intersection of:
- Signals that fired (not suppressed by ECL gates — Bias Layer 1, fixed in Phase 123)
- AND signals that were regime-eligible (not suppressed by HMM regime gate)
- AND signals that activated (price entered the entry zone)
- AND signals whose trade was closed (not open at training time)

The model fits to the *executed and closed* subset. It never sees:
- Patterns that fired when the regime gate blocked them (would they have worked?)
- Patterns that fired but price never entered the entry zone (what was the counterfactual?)
- Patterns that are currently open (selection bias on closing time)

### After SLA: Counterfactual Eliminates Selection Bias

With `counterfactual_pnl_r` on `trade_frames`:

```sql
SELECT se.feature_vector, tf.counterfactual_pnl_r
FROM signal_events se
JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
WHERE tf.counterfactual_pnl_r IS NOT NULL;
-- No longer filters on execution status, regime status, or trade closure
```

`counterfactual_pnl_r IS NOT NULL` means CounterfactualTracker has measured the outcome — which it does for every frame after the signal's TTL expires. The training set now includes:
- All signals, regardless of regime suppression (Bias Layer 2 closed)
- All entry types, regardless of whether they activated
- All frames, regardless of whether they were executed

The model can now answer: "for this pattern in this market context, which entry type produces the best counterfactual outcome?" This is the correct question.

---

## Key Design Decisions

### Hypertable FK Constraints Require Composite Keys

`signal_events` is a TimescaleDB hypertable partitioned by `ts`. TimescaleDB requires the partition dimension in the primary key: `(signal_id, ts)` rather than just `signal_id`.

Any foreign key pointing to `signal_events` must therefore include both columns. `trade_frames` carries `signal_ts` as a denormalized copy of `signal_events.ts` specifically to satisfy this constraint:

```sql
CONSTRAINT fk_trade_frames_signal
    FOREIGN KEY (signal_id, signal_ts)
    REFERENCES signal_events (signal_id, ts)
```

This denormalization is a TimescaleDB requirement, not a design choice. `signal_ts` is always equal to the `signal_events.ts` it references.
<!-- src: production/migrations/137_3table_schema.sql -->

### The Join View Is the Query Surface

`signal_ledger` (the join view, renamed from `signal_ledger_full` in Phase 130) joins all three tables and is the canonical read surface for all queries that span multiple layers. Direct table queries are permitted only when the query is strictly within one semantic layer (e.g., counting `signal_events` fires by plugin does not need the join). Mixed-layer queries (detection + outcome) always go through the view.

The legacy `signal_ledger` monolith and `signal_outcomes` table were dropped in Phase 130. The join view now provides the same backward-compat query surface.

### Immutability After Write

Each table's non-lifecycle fields are write-once. `signal_events` rows are not updated when activation or exit occurs — that information flows to `trade_executions`. The only mutable field on `signal_events` is `status` (the lifecycle state machine), which `LifecycleWriter` updates.

This immutability makes replay safe: a historical backfill can re-insert detection rows without risking corruption of live execution data.

---

## What Was Rejected

**Single table with NULLable outcome columns:** The monolith approach. Every `pnl_r IS NOT NULL` training query implicitly introduces execution selection bias. Rejected because it makes an unbiased ML training set impossible without manual correction that is easy to forget.

**Event-sourced approach (append-only transitions):** Storing every state transition as a separate row and deriving current state by aggregation. Rejected because query complexity for training becomes prohibitive — reconstructing the "what was hypothesized" row requires replaying a sequence of events. The three-table design gives the same auditability without the query burden.

**Embedding trade frames in JSONB on `signal_events`:** Avoids the FK complexity but makes per-entry-type queries non-indexable and prevents row-level counterfactual population. Rejected.

**Separate counterfactual table:** A fourth table `signal_counterfactuals` instead of a column on `trade_frames`. Rejected because the counterfactual is defined at the entry-type hypothesis level — it belongs on the row that defines the hypothesis, not on a separate audit row.

---

## See Also

- `docs/signals/signals-schema.md` — complete DDL reference for all three tables and the join view
- `docs/signals/signal-trade-separation-ADR.md` — formal ADR with implementation decision and migration plan
- `docs/concepts/extrinsic-confidence-layer.md` — ECL; why the detection layer must be unfiltered
- `docs/foundation/glossary.md` — SLA, CFL, counterfactual pnl_r, survivorship bias canonical definitions
- `docs/foundation/canonical-truth-registry.md` — canonical writer for each SLA table
