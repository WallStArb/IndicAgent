# Phase 142A: Ensemble IC Measurement - Context

**Gathered:** 2026-06-30
**Status:** Ready for planning
**Source:** Transcribed from `docs/research/phase142-redesign-musk5step-audit.md` (Musk 5-step + Renaissance audit, 2026-06-30) + ROADMAP §142A. Design decisions are LOCKED by that audit; this file transcribes them for the planner/checker. Do not re-litigate scope.

<domain>
## Phase Boundary

Phase 142A proves the ensemble OUTPUT has IC before any execution rules are tested. It measures `IC(alpha_score, forward_return_*)` per (symbol, tf, regime, lookahead) using the same BH-FDR + Fisher z-transform 95% CI + 3-fold walk-forward machinery as the feature IC engine. No stops, no targets, no frame assumptions — pure signal measurement.

**Why before 142B:** If `alpha_score` does not predict forward returns, no frame definition will save it. You'd be measuring the frame, not the signal — a silent wrong answer. Signal proof must precede execution proof (Simons: earn promotion through proof).

**OUT OF SCOPE (deleted by Musk audit, do not re-add):**
- Cost model (`alpha.cost.*`) — belongs in v4.0 when real fills exist
- 4-variant calibration grid — deferred to 142C *if* Phase 142 exits positive
- Frame simulation / CounterfactualTracker — that is Phase 142B, gated on EIC-04 passing

**⚠️ P0 URGENT open risk (2026-07-01):** `regime_writer.py` fits the HMM on the full corpus history before its causal decode — regime labels leak future statistical structure into every regime-stratified score. This contaminates the `regime` stratification that EIC-01 reads from `market_regimes`/`feature_vectors.regime`. See `.planning/todos/pending/034-hmm-walk-forward-refit.md`. 142A can proceed (it composes existing IC math, does not touch regime labeling), but any regime-stratified `alpha_ensemble_ic` result inherits this bias until 034 lands — do not treat EIC-04 gate pass/fail on regime-stratified cells as final until the HMM refit fix ships.

</domain>

<decisions>
## Implementation Decisions

### EIC-01 — EnsembleICEngine (KEEP)
Weekly oneshot, `BaseBatch` subclass. Reads `alpha_events` joined to `forward_returns` on (symbol, tf, bar_ts). Computes Spearman `IC(alpha_score, forward_return_fast/mid/slow/extended)` per (symbol, tf, regime). Applies same BH-FDR correction, Fisher z-transform 95% CI, and 3-fold walk-forward as `ICEngine`. Writes to `alpha_ensemble_ic`. Parallelized: one `ProcessPoolExecutor` task per (symbol, tf). CPU-bound IC computation decoupled from async DB reads/writes.

### EIC-02 — IC decay curve → hold_max_bars (KEEP)
For each (symbol, tf, regime), find the first lookahead where IC Sharpe drops below `alpha.ensemble_ic.decay_threshold` (default 0.1 `[initial_estimate]`). Update `alpha.frame.hold_max_bars.<regime>.<tf>` APR keys to match. Replaces initial estimates with data-derived values before 142B runs any frames.

### EIC-03 — Walk-forward stability gate (KEEP)
IC Sharpe max/min fold ratio < 3× across walk-forward folds. Written to `alpha_ensemble_ic.walk_forward_stable` (boolean). Phase 144 OOS validation reads this column. **See D-142A-R1 below for the locked v1 implementation of this metric (fold IC-magnitude ratio, not fold IC-Sharpe ratio) and its justification.**

### EIC-04 — Phase gate (KEEP, threshold is APR-seeded NOT baked in)
`ic_ci_lower > 0` at 95% CI on in-sample data in at least `alpha.ensemble_ic.min_qualifying_fraction` of (symbol, tf, regime) cells before Phase 142B begins. **Renaissance correction:** the 60% is arbitrary and unseeded — `alpha.ensemble_ic.min_qualifying_fraction = 0.60` seeded as `[initial_estimate]`, recalibrate after first run reveals how many cells have sufficient N. Do NOT bake a magic number into the gate logic. If gate fails, run EIC-05 diagnosis before any changes.

### EIC-05 — Gate failure diagnosis script (KEEP)
When EIC-04 fails, emit a structured markdown report before any remediation:
1. N per cell — low N (`< alpha.ic.min_obs_per_regime`) = data starvation, not signal absence
2. Pooled vs per-symbol IC gap — pooled `ic_ci_lower > 0` but per-symbol fails = regime granularity too coarse
3. TF breakdown — 1h passes but 5m fails = TF-specific (fewer independent obs/regime), not global ensemble problem
4. Regime coverage — ≥ 3 regimes with zero qualifying cells = regime label quality issue

Ships in Wave 2. "Diagnose ensemble" without this structure wastes a week chasing the wrong layer.

### Claude's Discretion (implementation detail, not locked)
- Exact ProcessPoolExecutor chunking strategy / worker count — follow `ICEngine` precedent (`infra.ic_engine.workers=12`) and the `BaseBatch` base class
- Whether EnsembleICEngine subclasses `ICEngine` or composes its IC math — researcher decides based on code reuse vs. SoC
- Service unit name / systemd wiring — follow naming system (`indicagent-ensemble-ic-engine`), register in `service_auditor.py` `_DAG_ORDER`

### Decisions added during cross-AI plan review (2026-07-02) — LOCKED

These resolve HIGH review findings against the drafted 142A plans. Recorded here because Phase 142B's frame simulation reads from `alpha_ensemble_ic` and must inherit consistent semantics.

**D-142A-R1 — EIC-03 `walk_forward_stable` uses fold IC-magnitude ratio, not fold IC-Sharpe ratio (deliberate v1 relaxation of the ROADMAP EIC-03 wording).**
ROADMAP.md EIC-03 states "IC Sharpe max/min fold ratio < 3×". The implementation instead computes `max/min` over the per-fold IC *magnitude* (Spearman IC scalar per fold), not per-fold IC Sharpe. This is a conscious, reasoned scope decision, not a silent substitution:
- A reliable per-fold IC *Sharpe* requires `sharpe_min_windows` (30) × `sharpe_window_size` (2000 raw bars) = **60,000 bars inside a single fold's test slice** (live APR values verified 2026-07-02). A 3-fold walk-forward divides `n_valid` into ~`1/(folds+1)` slices, and `ic_engine.py:959` already gates each fold test slice at `min_reliable_n` (100) just to produce a single fold IC scalar. Per (symbol, tf, regime) cell after regime stratification, per-fold N is one-to-three orders of magnitude below the 60k floor, so a per-fold Sharpe would be `None` for the overwhelming majority of cells — making a Sharpe-ratio gate unusable and non-comparable across cells.
- `ic_engine.py`'s own established walk-forward stability check (`fold_ic_arr > 0`, lines 969-973) already operates on fold IC scalars, not fold Sharpe. The proxy therefore matches existing codebase methodology rather than diverging from it.
- The metric is swappable: `alpha.ensemble_ic.wf_stability_metric = 'ic_ratio'` (APR seed). If a future run has cells with N ≥ 240k where a per-fold Sharpe is estimable, the value can be flipped to `'ic_sharpe_ratio'` and the computation switched without a migration.
- **Renaissance guard:** this relaxation is documented in the `walk_forward_stable` code comment and in this decision so no downstream reader mistakes it for the ROADMAP's literal Sharpe gate. Phase 144 OOS validation reading this column inherits the same magnitude-ratio semantics.

**D-142A-R2 — `alpha_ensemble_ic.scored_at` is a per-run vintage timestamp pinned once per invocation; cross-run accumulation is intentional (mirrors `ic_engine.computed_at`).**
- `scored_at` is the hypertable partition column and is part of the composite PK `(event_row_id, scored_at)` (TimescaleDB requires the partition column in the PK). `event_row_id = content_key(symbol, tf, regime, lookahead)` is the stable, data-derived cell key that excludes any run timestamp — analogous to `ic_engine`'s conflict key which uses `training_window_end` (stable) and keeps `computed_at`/`run_ts` OUT of the conflict target.
- **Locked behavior:** a single `run_ts = datetime.now(UTC)` is computed ONCE at the top of `_execute_inner` and reused as `scored_at` for every row written in that invocation (mirrors `ic_engine.py:2009`). A run that fails partway and is retried within the same invocation upserts in place via `ON CONFLICT (event_row_id, scored_at) DO UPDATE`. Separate scheduled/manual invocations get a new `scored_at` and therefore accumulate a real time-series of IC vintages in the hypertable — this is a feature (weekly-oneshot vintage history), not a bug.
- **Consequence for Wave 2 (locked):** the EIC-04 gate and EIC-05 diagnosis MUST select a single completed run via `scored_at = (SELECT max(scored_at) FROM alpha_ensemble_ic)` rather than a rolling `NOW() - INTERVAL '7 days'` window, so gate/diagnosis output is deterministic across manual reruns and never mixes vintages. Phase 142B frame simulation reading `alpha_ensemble_ic` should likewise pin to the latest `scored_at` (or an explicitly chosen vintage).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Locked scope (source of truth)
- `docs/research/phase142-redesign-musk5step-audit.md` — the Musk 5-step + Renaissance audit. EIC-01..05 verdicts, deletions, simplifications. **This is the authority on 142A scope.**
- `.planning/ROADMAP.md` §Phase 142A — formal roadmap entry with EIC-01..05 requirements text

### Schema + APR
- `docs/plans/archive/2026-06-25-v30-alpha-lifecycle-schema.md` — `alpha_ensemble_ic` table DDL (hypertable + unique cell index), `alpha.ensemble_ic.*` APR keys, `alpha.frame.hold_max_bars.*` APR seeds. **WARNING: regime namespace in this doc (`bull/bear/sideways/volatile`) is STALE** — see Open Question OQ-1.

### Methodology + patterns
- `docs/intelligence/intelligence-alphaengine.md` — AlphaEngine concept doc
- `docs/analysis/ic-discovery-report.md` — 4-symbol IC discovery (methodology reference)
- `src/core/agent/base_batch.py` — `BaseBatch` Ring 0 base class (pool lifecycle, D-06, content_key); EnsembleICEngine MUST extend this
- `ic_engine` implementation (feature IC) — the IC math, BH-FDR, Fisher z-transform CI, walk-forward machinery to replicate for the ensemble. Researcher locates exact paths.
- `src/intelligence/register_plugins.py`, `services/service_auditor.py` — service registration (`_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT`)

### CLAUDE.md rules that bind this phase
- Invariant 1 (executable returns): IC queries filter `WHERE return_type = 'executable_open_to_open'`
- APR mandate: every threshold/weight/period lives in `config_state` under `alpha.*`; no hard-coded numerics in `src/`/`services/`
- ProcessPoolExecutor workers are compute-only: serial DB writes from main process only
- Gradient naming for tunable calibration params (`fast`/`mid`/`slow`/`extended`)

</canonical_refs>

<specifics>
## Specific Ideas

- **2 plans, 2 waves** (per ROADMAP):
  - Wave 1: schema migration (`alpha_ensemble_ic` hypertable + `alpha.ensemble_ic.*` APR seeds) + EnsembleICEngine service
  - Wave 2: decay curve analysis + `hold_max_bars` APR calibration + EIC-04 gate evaluation + EIC-05 diagnosis script
- **Data state at plan time (2026-06-30):** Phase B corpus re-run is IN FLIGHT (`feature_ic_scores` at 0 rows mid-rebuild). This blocks EXECUTION of 142A, not planning. `alpha_events` = 12.47M rows, `forward_returns` = 54.26M rows (1:1, executable_open_to_open). OOS boundary `alpha.validation.oos_start = 2025-12-24T05:15:00Z`.
- **IC math parity:** EnsembleICEngine must use the SAME corrected methodology shipped in Phase A (A2: expanding-window WF folds, corpus-level BH-FDR, scale-specific embargo, direct-linkage clustering; A5: gate is `ic_ci_lower > 0 AND passes_fdr = true`). Do not re-derive IC methodology — replicate the feature IC engine's corrected path onto the composite `alpha_score`.
- **Decay threshold is [initial_estimate]:** `alpha.ensemble_ic.decay_threshold = 0.1` — flag for recalibration after first run.

</specifics>

<open_questions>
## Open Questions for Researcher to Resolve

### OQ-1 — Regime namespace mismatch (KNOWN STALENESS, must resolve)
The schema design doc (2026-06-25) keys `alpha.frame.hold_max_bars.<regime>.<tf>` with regime values `bull/bear/sideways/volatile`. But the LIVE regime system (Phase 140.5) is cross-sectional `market_regimes` with 9 labels `{low/mid/high}_{bull/neutral/bear}`, and ic_engine stratifies on those. The `alpha_ensemble_ic.regime` column and the `hold_max_bars.*` APR key namespace MUST be reconciled to the actual labels ic_engine uses, not the schema doc's 4-label set. Researcher determines: which regime label set does the corrected ic_engine actually stratify on, and what should the `hold_max_bars.<regime>.<tf>` key namespace be? This affects the migration DDL and APR seed set.

### OQ-2 — Read source for `alpha_score`
Confirm which column/derivation is `alpha_score` on `alpha_events` (the ensemble output to measure IC against). Researcher locates the exact field and its population path (Phase 139 ensemble + Phase 141 ensemble_trainer weights).

### OQ-3 — `min_qualifying_fraction` gate evaluation surface
EIC-04 evaluates a fraction across (symbol, tf, regime) cells. Decide: is this a SQL query in a gate-evaluation script (Wave 2), or a computed column / view? Researcher recommends the cleanest evaluation surface that Phase 144 can re-read.

</open_questions>

<deferred>
## Deferred Ideas

- **Phase 142B** (AlphaFrameWriter + CounterfactualTracker + state machine + mean-pnl gate + SHADOW-REVIEW.md) — only planned after EIC-04 passes. Not in this phase.
- **Phase 142C** — 4-variant stop_atr_mult calibration grid — only if Phase 142 exits with positive counterfactual P&L.
- **Cost model** (`alpha.cost.*`) — v4.0.

</deferred>

---

*Phase: 142A-ensemble-ic-measurement*
*Context gathered: 2026-06-30 (transcribed from Musk redesign audit; no separate discuss-phase — design was locked by the audit)*
*Amended 2026-07-02: added D-142A-R1 (EIC-03 fold IC-magnitude proxy) and D-142A-R2 (scored_at vintage/idempotency semantics) from cross-AI plan review.*
