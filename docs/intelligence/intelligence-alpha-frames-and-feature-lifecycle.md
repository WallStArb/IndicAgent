# Alpha Frames & Feature Lifecycle — Counterfactual Trade Measurement and Feature Governance

**Version:** 1.0.0
**Last Updated:** 2026-07-15
**Status:** current
**Milestone:** v3.15 (shipped Phase 142B/143, 2026-07-10)

**Companion doc:** `docs/intelligence/intelligence-alphaengine.md` describes the IC-weighted
ensemble that produces `alpha_events`. This doc picks up immediately downstream: how an
`alpha_event` becomes a measurable hypothetical trade (`alpha_frames`), how that trade's
outcome is realized (`CounterfactualTracker`), and how realized outcomes feed back into
whether a feature is allowed to keep voting in the ensemble (`feature_registry` lifecycle,
`integrity_monitor`). Read the AlphaEngine doc for "how is alpha_score computed," read this
doc for "what happens to an alpha_event after it fires, and how a feature gets promoted or
cut off."

---

## Why This Subsystem Exists

`alpha_events` measures whether the ensemble's opinion at a bar correlates with forward
returns. It does not answer a different, harder question: *if a trade had actually been
taken on this signal, what would have happened?* IC is a statistical property of the whole
distribution; a trader needs the distribution of realized R-multiples a specific entry/stop/
target/hold-horizon design would have produced. `alpha_frames` and `CounterfactualTracker`
exist to answer that question without ever placing a live order — Phase D/E (Portfolio,
Execution; see the AlphaEngine doc's Build Sequence) still gate on Phase A/B IC proof, so this
is intentionally paper trading against history, not a live sizing/execution path.

Separately, an ensemble that never re-evaluates its own inputs will keep voting with a feature
whose edge has decayed or reversed. `feature_registry`'s lifecycle state machine and the
`integrity_monitor` audit trail exist so that decay is caught and acted on automatically
(demotion to `shadow_only`), while a market-wide dislocation is not misread as universal
feature failure (the regime-shift guard holds all transitions during a shock).

---

## `alpha_frames` — Hypothetical Trade Frames

**Migration:** `production/migrations/214_alpha_frames_schema.sql` (Phase 142B, FRAME-01),
amended by `215_alpha_frames_target_r_multiple.sql` (adds `target_r_multiple`) and
`221_alpha_frames_compression.sql` (compression policy).

**Note on migration numbering:** two unrelated migrations both claimed `214` under concurrent
sessions (`214_alpha_frames_schema.sql` and `214_partial_ic_interaction_primitives.sql`);
migration `223`'s own header documents this collision and the renumbering that followed. Not
a data problem, just a filename collision worth knowing about if you're reading migrations in
numeric order.

**Writer:** `services/alpha_frame_writer.py` — `class AlphaFrameWriter(BaseBatch)`. Invoked as
a oneshot (`python services/alpha_frame_writer.py [--backfill]`), not a Kafka consumer. Its own
module docstring is explicit: *"No Kafka: this table has no live consumer, matching
EnsembleICEngine's precedent."* It reads pending rows via an anti-join —
`alpha_events ae LEFT JOIN alpha_frames af ... WHERE af.frame_id IS NULL` — and writes one
`alpha_frames` row (`frame_variant='primary'`) per pending event, snapshotting `alpha_score`,
`alpha_ci_lower`/`alpha_ci_upper`, and the D-03 diagnostic triad
(`gross_expected_r`/`cost_r`/`net_expected_r`, computed by `compute_expected_r_snapshot()`).
Entry/stop/target geometry (`entry_price`, `stop_price`, `target_price`, `r_multiple`) is
written NULL — `CounterfactualTracker` fills it at T+1 open. `status` starts `'open'`.

**Where this sits in the base-class architecture:** `AlphaFrameWriter` and
`CounterfactualTracker` are both `BaseBatch` (DB → compute → DB, idempotent, versioned) — the
same lane as `RegimeWriter`/`ForwardReturnLabeler`/`ICEngine`, not `BaseWriter` (Kafka consumer
→ DB persistence). `alpha_frames` is downstream of `alpha_events` via a plain SQL join, not a
Kafka topic. This is a deliberate choice, not an oversight: `alpha_frames` rows are read back
and mutated in place by `CounterfactualTracker` over the following hours-to-days as a trade's
outcome resolves, which is a batch/reconciliation access pattern, not a streaming one.

### Schema (selected columns)

| Column | Type | Notes |
|---|---|---|
| `frame_id` | `text NOT NULL` | Content-addressed (`BaseBatch.content_key(event_id, bar_ts, frame_variant)`), not a UUID |
| `bar_ts` | `timestamptz NOT NULL` | Hypertable partition column |
| `direction` | `text CHECK (direction IN ('long','short'))` | |
| `frame_variant` | `text NOT NULL DEFAULT 'primary'` | Schema supports a 4-variant calibration grid; only `'primary'` is written today |
| `alpha_score`, `alpha_ci_lower`, `alpha_ci_upper` | `double precision` | Snapshot from `alpha_events` at write time |
| `gross_expected_r` | `double precision` | **D-03 diagnostic only** — a directional-confidence magnitude scaled by the frame's design R-multiple on a win, never a gate input |
| `net_expected_r` | `double precision` | `gross_expected_r - cost_r`, reporting-only |
| `cost_r` | `double precision` | Copied from `alpha_events.cost_hurdle`, never re-derived live |
| `entry_price`, `stop_price`, `target_price`, `r_multiple` | `double precision` | NULL until `CounterfactualTracker` fills them at T+1 open |
| `max_hold_bars`, `stop_atr_mult`, `target_r_multiple` | — | APR snapshots at frame-write time (`alpha.frame.hold_max_bars.<regime>.<tf>`, `alpha.frame.stop_atr_mult`, `alpha.frame.target_r_multiple`) |
| `status` | `text CHECK (... IN ('open','closed_stop','closed_target','closed_max_hold','closed_ic_decay'))` | See exit state machine below |
| `counterfactual_pnl_r`, `counterfactual_mfe`, `counterfactual_mae`, `counterfactual_bars` | — | Written by `CounterfactualTracker` |
| `corpus_run_id`, `weight_epoch` | `text` | Provenance |

**Keys:** `PRIMARY KEY (frame_id, bar_ts)` — composite because TimescaleDB requires the
partition column in every unique index. `UNIQUE (event_id, bar_ts, frame_variant)` is the
idempotency target (`ON CONFLICT ... DO NOTHING`).

**No foreign key to `alpha_events`, deliberately.** `alpha_events` is truncated on every corpus
rebuild by `scripts/ops/corpus/infrastructure_truncate_derived_tables.sh`; an FK would either
block that truncate or cascade-wipe every frame along with it.

**Compression:** `compress_after => INTERVAL '60 days'`, longer than the 30-day convention used
by sibling tables (`alpha_events`, `forward_returns`), because `alpha_frames` rows are updated
in place until a terminal `status`, and 60 days covers the worst-case hold horizon across all
`(regime, tf)` cells.

---

## `CounterfactualTracker` — Realizing Trade Outcomes

**File:** `services/counterfactual_tracker.py` — `class CounterfactualTracker(BaseBatch)`.
Invoked as `python services/counterfactual_tracker.py [--backfill] [--evaluate-gate]`. Reads
open `alpha_frames` rows, the latest `alpha_ensemble_ic` row per regime, and
`market_data_ohlcv` directly — no Kafka subscription.

### Fill and exit mechanics

1. **Geometry fill at T+1 open.** `entry_price` = the open of the first bar after
   `frame.bar_ts` (executable, matching Invariant 1's executable-returns rule elsewhere in this
   codebase). A price-unit ATR is computed live from `market_data_ohlcv` (never from
   `feature_vectors`, which has no price-unit ATR column) and fed into
   `compute_frame_geometry()` — imported from `alpha_frame_writer.py`, not duplicated — to
   derive `stop_price`/`target_price`/`r_multiple`.

2. **Exit state machine** (`determine_exit()`), evaluated bar-by-bar in priority order:
   1. Stop hit → `closed_stop`. Fill uses the worst-of-open-or-stop price on a gap-through
      (executable, not theoretical).
   2. Target hit → `closed_target`.
   3. `i >= hold_max_bars` → `closed_max_hold`.
   4. If none of the above trigger within the hold window, and the regime's current
      `alpha_ensemble_ic` row has `ic_ci_lower < 0` (read regardless of row age) →
      `closed_ic_decay`.
   A frame with zero observed forward bars stays `open` — the tracker never fabricates a close.

3. **Realized R** (`compute_frame_pnl_r()`): `risk = abs(entry_price - stop_price)`;
   `long → (exit_price - entry_price) / risk`; `short → (entry_price - exit_price) / risk`. A
   stop-out is approximately −1.0 R; a target hit is approximately +`target_r_multiple` R.

4. **MFE/MAE** (`_compute_excursion()`) are computed over the bars actually observed before
   close.

**Update guard:** the write (`_UPDATE_SQL`) is `WHERE frame_id=$1 AND bar_ts=$2 AND
status='open'` — an immutability guard so a rerun of the tracker never re-closes an
already-closed frame.

**Compute/persistence separation (DAG invariant #3):** work is parallelized via
`ProcessPoolExecutor` (`infra.counterfactual_tracker.workers`, default 12), one task per
symbol. Workers return `list[dict]` rows only and never open a write connection; the main
process performs the serial per-symbol `executemany` UPDATE as results arrive. The module
cites DAG invariant #3 and the project's "ProcessPoolExecutor workers are compute-only" rule
directly in comments at the call site.

### `--evaluate-gate`: the FRAME-04 exit gate

A read-only reporting mode that evaluates whether the frame design (entry/stop/target/hold
rules) has a statistically positive edge, over in-sample rows only
(`bar_ts < alpha.validation.oos_start`, closed frames, `frame_variant='primary'`):

- PnL is aggregated to **per-calendar-day cluster means** before resampling — the block
  bootstrap is day-clustered, not bar-clustered, because hold horizons up to 60 bars overlap
  and naive bar-level bootstrap would understate variance.
- Below `alpha.scoring.bootstrap_max_n` day-clusters: `scipy.stats.bootstrap(method='BCa')`.
  Above that: an analytic one-sided 95% CLT lower bound
  (`mean - 1.645 * std / sqrt(n)`).
- Passes iff `ci_lower > 0`, gated on **GROSS** `counterfactual_pnl_r` only (never
  `net_expected_r` — this project's D-01 rule: cost accounting is a reporting diagnostic, not
  a gate input), and subject to a minimum-N floor (`alpha.scoring.min_strategy_n`).

---

## `feature_registry` Lifecycle State Machine

**Base migration:** `production/migrations/172_feature_registry.sql` (Phase 140.5). Lifecycle
columns added by `216_feature_registry_lifecycle_columns.sql` (Phase 143); control-predictor
columns by `223_canary_predictor_columns.sql` (Phase 143.1).

**States:** `status CHECK (status IN ('candidate', 'active', 'shadow_only', 'deprecated'))`,
default `'candidate'`.

```
candidate ──(operator promotes)──► active ──(ic_demotion)──► shadow_only
                                     ▲                            │
                                     └────────(ic_promotion)──────┘

any state ──(operator_override only)──► deprecated
```

**Transition log:** `feature_transition_log` — append-only, `trigger_reason CHECK (... IN
('ic_promotion', 'ic_demotion', 'parent_cascade', 'operator_override'))`. A DB trigger
(`fn_cascade_parent_deprecation`) auto-deprecates tier-1 interaction children when their parent
feature is deprecated, logged as `parent_cascade`.

**`deprecated` is operator-only, enforced in code, not just convention.**
`FeatureRegistryService.record_transition_sync()` raises `ValueError` if an automated reason
(`ic_promotion`/`ic_demotion`) ever targets `'deprecated'`. An automated process can move a
feature between `active` and `shadow_only`; only a human can retire it entirely.

**What triggers a transition:** `services/ic_engine.py`'s `_run_lifecycle_hook()`, run once at
the end of every `ic_engine.py` corpus run:

1. **Regime-shift guard, checked first.** If a large fraction of currently-`active` cells fail
   simultaneously (`config.decay_regime_shift_fraction`), **every transition is held** for that
   run — zero demotions or promotions execute. This exists so a market dislocation (everything
   stops working at once because the market changed) is never misread as mass, per-feature
   decay. The hold is itself logged to `integrity_monitor` (`metric_name='regime_shift_fraction'`,
   `passed=false`).

2. **`active` → `shadow_only` demotion.** Per feature, if the fraction of that feature's
   `active`-status cells that are "materially failed" — CI includes zero or fails FDR
   (sign-aware), *and* `standing_weight * |bound| > config.decay_materiality_threshold` — meets
   or exceeds a demotion floor, the feature is demoted via `record_transition_sync(...,
   'active', 'shadow_only', 'ic_demotion', ...)`. This also resets
   `consecutive_shadow_passes` and `observations_since_demotion` to zero.

3. **`shadow_only` → `active` promotion.** Every run, `advance_shadow_counters_sync()`
   increments `consecutive_shadow_passes` if that run's pass fraction clears
   `config.meta_fdr_min_fraction`, else resets it to zero, and unconditionally accumulates
   `observations_since_demotion`. Promotion requires both a minimum-observation floor
   (`alpha.decay.recovery_min_observations`) and a minimum-consecutive-passes floor
   (`alpha.decay.recovery_min_passes`, default 2) — there is no calendar/cooldown clock, only
   evidence accumulation.

Promotion is a status flip only. `ic_engine.py` never writes `ensemble_weights` itself (that
remains `ensemble_trainer.py`'s sole-writer responsibility) — the next `ic_engine` run stamps
`feature_status_at_eval='active'` on `feature_ic_scores`, and the next `ensemble_trainer` run
recomputes that feature's weight from scratch.

**Readers/writers:**
- `ic_engine.py` reads status via `FeatureRegistryService.get_status()` and is the sole writer
  of automated transitions (via the lifecycle hook above).
- `ensemble_trainer.py` reads `feature_registry` for a startup drift/alignment gate (comparing
  registered feature names against the live `FeatureVector` dataclass fields) and filters
  `feature_ic_scores` to `feature_status_at_eval = 'active'` when building ensemble
  eligibility. It writes `ensemble_weights`, never `feature_registry`.
- `scripts/ops/alpha/ops_canary_integrity_assert.py` (Phase 143.1, "Component D corpus-run
  integrity gate") reads `feature_registry.is_control`/`control_expectation` joined to
  `feature_ic_scores` and hard-halts the corpus pipeline (non-zero exit) if a negative-control
  canary clears significance in the pooled stratum, or the positive control
  (`canary_acausal_placebo`) fails to. It writes nothing to `feature_registry` — pure read +
  assert. It is wired into `ops_corpus_pipeline_run.sh` immediately after the `ic_engine` step,
  as a separate gate from the lifecycle hook.

---

## `integrity_monitor` — Lifecycle Decision Audit Trail

There is no standalone `IntegrityMonitor` service or class. `integrity_monitor` is a table
(`production/migrations/218_integrity_monitor.sql`, Phase 143), and its only writer is
`ic_engine.py`'s `_run_lifecycle_hook()` — the same hook described above. Its own migration
header states the intent plainly: observability-only gate-evaluation facts, **not**
authoritative state. `feature_transition_log` remains the sole authoritative record of what
actually transitioned; `integrity_monitor` exists purely so a run's decay/hold decision is
queryable after the fact.

**Schema (selected):** `monitor_type` (only `'ic_lifecycle'` is written today), `subject`
(nullable — NULL for run-level facts), `metric_name`, `metric_value`, `threshold_value`,
`passed`, `training_window_end`, `evaluated_at` (hypertable partition column, 3-month chunks).

**Facts written today:**

| `metric_name` | When | `passed` |
|---|---|---|
| `regime_shift_fraction` | Regime-shift guard fires, all transitions held | `false` |
| `decay_cells_flagged` | Every non-hold run | `true` |

**Idempotency:** the hook checks `integrity_monitor` for an existing row at the same
`training_window_end` *before* evaluating anything, so a rerun over an already-processed
window is a no-op. The table's own unique index is defense-in-depth on top of that check, not
the primary guarantee.

**Invocation:** inline, synchronous, at the end of every `ic_engine.py` run, wrapped in a
try/except so a hook failure logs loudly but never corrupts already-committed IC results for
that run. `ic_engine.py` itself has no independent schedule — it is one step of
`scripts/ops/corpus/ops_corpus_pipeline_run.sh`, which is operator-invoked (no cron/systemd
timer schedules the corpus pipeline; see CLAUDE.md's roll-flow note on disabled timers for the
same pattern elsewhere in this codebase).

---

## See Also

- **AlphaEngine IC/ensemble mechanism:** `docs/intelligence/intelligence-alphaengine.md` —
  upstream of everything in this doc; read first for how `alpha_score`/`alpha_events` are
  produced.
- **Generic layer contract:** `docs/intelligence/intelligence-layer-architecture.md` — where
  this subsystem's Stage 2/3 (Edge Measurement, Combination) concepts live in the abstract
  Stage 0-4 model.
- **Dual regime system:** `MEMORY.md` "Dual Regime System" (per-session project memory) — the
  `regime` label this subsystem stratifies by comes from two coexisting mechanisms
  (`regime_writer.py` per-symbol HMM, `cross_sectional_regime_model.py` cross-sectional); no
  standalone doc exists for that split yet.
- **Ensemble weighting methodology:** `docs/intelligence/intelligence-alphaengine-methodology.md`
  — IC shrinkage, weight combination methods, `concept_registry` governance.
