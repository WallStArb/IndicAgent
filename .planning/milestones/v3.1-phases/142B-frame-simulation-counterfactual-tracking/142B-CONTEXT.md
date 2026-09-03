# Phase 142B: Frame Simulation + Counterfactual Tracking - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Prove that a reasonable execution rule (stop/target/hold) can capture the signal IC proven in
Phase 142A as positive counterfactual P&L. This is a binary question — does any sensible frame
work — not a calibration exercise. Two services: `AlphaFrameWriter` (writes hypothetical
positions from `alpha_events`) and `CounterfactualTracker` (scans price paths, writes lifecycle
outcomes). One pre-committed document: `docs/plans/SHADOW-REVIEW.md`, frozen before any
counterfactual data is collected.

Both phase dependencies are satisfied as of 2026-07-09: EIC-04 gate PASSes (35/1585 = 2.21%
against a `[rca_analysis]`-recalibrated 0.02 threshold), and `hold_max_bars` APR keys are
calibrated from real decay-curve evidence for 16/36 (regime, tf) cells (remaining 20 correctly
retain `[initial_estimate]` seeds — no qualifying evidence exists there, not a gap). Full detail:
[Corpus pipeline state](../../../.claude/projects/-home-bg-dev-indicagent/memory/project_corpus_pipeline_state.md)
memory — don't re-derive the numbers here.

**Out of scope (already decided, do not re-litigate):**
- Calibration of which frame variant is optimal (the 4-variant stop_atr_mult grid described in
  the 2026-06-25 schema doc) — ROADMAP.md's stated Goal is explicit that this is a refinement
  question for after validation passes, not during it. `AlphaFrameWriter` writes
  `frame_variant='primary'` only, using the current APR default.
- Fill-calibrated real cost model (`alpha.cost.*` slippage/commission) — v4.0 scope, no real
  fill data exists yet.
- `alpha_executions` table / `AlphaExecutionWriter` — v4.0 scope.
- `is_shadow` column on `alpha_events` (todo 011) — separate, gated on Phase 142A (already
  complete) but not part of this phase's deliverable.

</domain>

<decisions>
## Implementation Decisions

### Cost basis for SHADOW-REVIEW.md (canonical-simulator.md Open Question 2)
- **D-01:** FRAME-04's exit gate and SHADOW-REVIEW.md's pre-committed pass/fail criteria are
  evaluated on **gross** `counterfactual_pnl_r` — matches ROADMAP's proposed criteria as
  drafted. Rationale: gating on the externally-calibrated `alpha.quant.cost_hurdle.*` keys
  (calibrated at the emission-threshold layer, todo 030 — not validated against real fills)
  would conflate "does the frame capture IC as P&L" with "is our unvalidated cost estimate
  right." That is a third question, and the whole point of splitting 142A (signal) from 142B
  (frame) was to never answer two questions with one number.
- **D-02:** SHADOW-REVIEW.md additionally reports `net_expected_r` (gross minus the calibrated
  `alpha.quant.cost_hurdle.*` keys) as a **mandatory reporting column** alongside every gross
  metric it commits to — not a gate, purely visible. This closes the "gross P&L reads
  optimistic" gap canonical-simulator.md flags (most events sit in the cost-marginal band per
  todo 030's calibration) and makes the shared cost kernel's first real consumer land inside
  142B, per canonical-simulator.md's own suggested resolution.
- **D-03:** `alpha_frames.net_expected_r` and `cost_r` columns (already in the 2026-06-25 schema
  doc's DDL) are populated at frame-creation time as diagnostic snapshots — this was already
  designed, just confirming it's not dead schema.

### Lifecycle state machine (schema doc vs. ROADMAP conflict)
- **D-04:** The `alpha_frames.status` CHECK constraint in the P1 migration is
  `('open', 'closed_stop', 'closed_target', 'closed_max_hold', 'closed_ic_decay')`.
  **`closed_reversal` is dropped entirely** — not reserved, not half-supported. The 2026-06-25
  schema design doc's literal DDL (which has `closed_reversal` and lacks `closed_ic_decay`) is
  **superseded on this specific point** by ROADMAP.md's FRAME-02/03 (written later, 2026-07-03,
  with an explicit, reasoned rationale: bar-level alpha-sign reversal is noise at intraday
  resolution and destroys returns via excessive turnover; the IC-decay trigger at weekly
  IC-engine cadence is the correct signal-based early exit). Research/planner must build the
  migration DDL and `CounterfactualTracker`'s exit-trigger logic from ROADMAP's FRAME-02/03 text,
  not from the schema doc's SQL block. Everything else in the schema doc (table shape, columns,
  indexes, FK to `alpha_events`) still governs.

### Initial run scale
- **D-05:** `AlphaFrameWriter` and `CounterfactualTracker` both support a `--backfill` mode
  (same pattern as `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`)
  that processes the full existing `alpha_events` backlog (12,258,206 rows as of 2026-07-09) in
  chunks on first run. This is a validation gate, not a live trading service — it needs to reach
  a verdict now, not accrue N over weeks of nightly-only accumulation.
- **D-06:** Nightly oneshot cadence (`BaseBatch`, D-06 `job_completed_total` contract) takes over
  incrementally for new `alpha_events` once the backfill completes. FRAME-04's exit gate is
  evaluated against the backfilled in-sample population.
- **D-07:** Frames are written for the full `alpha_events` population, not a filtered subset
  (matches FRAME-01 as written and the Renaissance data-retention principle — never filter
  backfill signals, all firings are training data).

### IC-decay trigger cadence
- **D-08:** `CounterfactualTracker`'s exit trigger (4) reads the most recent `alpha_ensemble_ic`
  row for the frame's (symbol, tf, regime) cell **regardless of its age** — no freshness gate
  blocks the read. Confirmed: no systemd timer exists for `ensemble_ic_engine` today (not even
  disabled — the unit doesn't exist); it currently only runs ad hoc inside the manual corpus
  pipeline script.
- **D-09:** Establishing a recurring `ensemble_ic_engine` schedule is **explicitly out of scope**
  for this phase. Bundling it in would blur the 142A/142B measurement-instrument boundary
  (142A owns signal IC and its cadence; 142B owns frame outcome) and expand past ROADMAP's
  stated 2-plan scope. A stale IC read degrades gracefully here — the early IC-decay exit
  simply fires later than ideal; frames still close correctly via stop/target/max_hold, so
  nothing produces a wrong P&L number.
- **D-10:** `CounterfactualTracker` instruments the age of the `alpha_ensemble_ic` row it
  consumes (log field or OTel metric) so staleness is observable, not silent, per this
  project's "instrument everything" principle. File a follow-on todo for the recurring
  `ensemble_ic_engine` cadence as separate, non-blocking future work (not created yet — planner
  or executor should file it during/after this phase).

### Claude's Discretion
- Exact metric/log field name and emission point for the IC-staleness observability signal
  (D-10) — follow this codebase's existing OTel patterns (`src/observability/metrics.py`).
- Chunk size and checkpoint/resume strategy for the `--backfill` mode (D-05) — follow
  `infrastructure_run_historical_pipeline.py`'s existing pattern; must not hold long-running
  write transactions given this codebase's documented deadlock/idle-timeout history on
  concurrent writers.
- Whether `sr_support_dist`/`sr_resist_dist` (needed for frame geometry's target-price logic)
  are still NULL in the current corpus or were fixed by the 142.5 Renaissance primitives work —
  verify empirically during research; the 2026-06-25 schema doc's ATR-fallback-is-primary-path
  note may be stale.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Schema and design (primary specs)
- `docs/plans/archive/2026-06-25-v30-alpha-lifecycle-schema.md` — `alpha_frames` table DDL, APR keys,
  naming derivation. **Superseded by ROADMAP.md on the lifecycle CHECK constraint only (D-04)**
  — every other section (columns, indexes, FK, frame geometry logic, APR key defaults) still
  governs.
- `.planning/ROADMAP.md` §"Phase 142B: Frame Simulation + Counterfactual Tracking" (search
  `### Phase 142B:`) — FRAME-01..04 requirements, SHADOW-REVIEW.md pre-commitment criteria,
  dependency verdict log. This is the authoritative requirements source for this phase.
- `docs/research/platform-canonical-simulator.md` — binding rule (all counterfactual claims are
  `alpha_frames` rows, no parallel replay paths), provenance requirement
  (`corpus_run_id`/`weight_epoch` columns at this phase's P1 migration — already locked in
  ROADMAP, not re-litigated here), and Open Questions 2/3 (resolved by D-01/D-02 and the
  provenance columns respectively). Note: ROADMAP.md's own text cites this doc at the stale path
  `docs/research/canonical-simulator.md` — the real path is `platform-canonical-simulator.md`.

### Corpus and measurement state
- [Corpus pipeline state](memory:project_corpus_pipeline_state.md) — current row counts,
  6th-rebuild status; single source of truth, don't duplicate counts in planning docs.
- `.planning/todos/pending/030-cost-hurdle-apr-calibration.md` — closed; the calibrated
  `alpha.quant.cost_hurdle.*` inputs D-02's net reporting column consumes.
- `.planning/todos/pending/011-alpha-events-is-shadow-column.md` — related but separate scope,
  gated on Phase 142A (complete); not part of this phase.
- `.planning/todos/pending/078-frame-outcome-labels-second-outcome-definition.md` and
  `.planning/todos/pending/082-simulation-validation-lenses-post-142b.md` — both explicitly
  hard-blocked on this phase shipping and explicitly state 142B's design should NOT change to
  accommodate them. Confirmed out of scope, not re-raised.

### Code patterns to follow
- `services/alpha_publisher.py` — `BaseBatch` subclass pattern, `event_id`/frame-id generation
  via `BaseBatch.content_key()`, async batch writes.
- `services/ensemble_ic_engine.py` — `ProcessPoolExecutor` per-symbol parallelism pattern,
  chunked named server-side cursor for large scans (commit `e9b3bcde`) — directly relevant to
  `CounterfactualTracker`'s bar-scanning workload at 12M+ frame scale.
- `src/core/agent/base_batch.py` — pool lifecycle, D-06 oneshot contract, `content_key()`.
- `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` — `--backfill`
  mode / chunking pattern referenced in D-05.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BaseBatch` (`src/core/agent/base_batch.py`, 170 lines) — both `AlphaFrameWriter` and
  `CounterfactualTracker` extend this per ROADMAP's "nightly oneshot, BaseBatch" requirement.
- `BaseBatch.content_key()` — used by `AlphaPublisher` for deterministic `event_id` generation;
  same pattern applies to frame identity if content-addressable IDs are preferred over the
  schema doc's `gen_random_uuid()` default (planner's call).

### Established Patterns
- `ensemble_ic_engine.py`'s chunked named server-side cursor (migration 212, commit `e9b3bcde`)
  — the exact fix needed to avoid the per-symbol OOM `CounterfactualTracker` will otherwise hit
  scanning 12M+ frames' subsequent bars.
- All batch services in this codebase are oneshot processes (not daemons) invoked by systemd
  timers or manual/ops scripts — "nightly oneshot" means "one full pass over pending work per
  invocation," which naturally absorbs a backlog on first run without a structurally distinct
  code path (grounds D-05's `--backfill` flag as a mode switch, not a separate service).

### Integration Points
- `alpha_events` (12,258,206 rows) — `AlphaFrameWriter`'s read source, FK target for
  `alpha_frames`.
- `feature_vectors` — `sr_support_dist`/`sr_resist_dist` for frame geometry target-price logic
  (verify NULL status per Claude's Discretion above).
- `alpha_ensemble_ic` — `CounterfactualTracker`'s read source for the IC-decay exit trigger.
- `service_auditor.py`'s `_DAG_ORDER` / `_AGENT_ID_TO_UNIT` — both new services must be
  registered here per the schema doc's migration checklist.
- `stream_keys.py` — `topic_alpha_frames` must be added per the schema doc's migration checklist.

</code_context>

<specifics>
## Specific Ideas

User's directive, applied throughout the Decisions section above: design every open question
the way a Renaissance Technologies engineering council would — absolute rigor, ruthless
simplicity, data integrity paramount, no silent wrong answers, don't automate what isn't proven,
don't conflate independent questions. This is not a one-off preference; treat it as the standing
lens for any remaining implementation judgment calls during research and planning for this
phase.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. The two adjacent todos (078, 082) that reference
142B are already correctly filed as post-142B and were not reopened.

### Reviewed Todos (not folded)
- **011-alpha-events-is-shadow-column** — reviewed for relevance (frame population scope, D-07)
  but not folded; it's a separate deliverable gated on Phase 142A, not this phase's work.
- **078-frame-outcome-labels-second-outcome-definition** — reviewed; explicitly hard-blocked on
  142B shipping and explicitly states 142B's design should not change for it. Correctly
  deferred, not folded.
- **082-simulation-validation-lenses-post-142b** — same as above; explicitly deferred by its own
  text, not folded.
- **088-hold-max-bars-censoring-not-tracked** — reviewed (relevant to the `hold_max_bars` APR
  values this phase's frame geometry consumes) but out of scope; it's about improving
  `ensemble_ic_engine.py`'s calibration provenance, not this phase's deliverable.

</deferred>

---

*Phase: 142B-Frame Simulation + Counterfactual Tracking*
*Context gathered: 2026-07-09*
