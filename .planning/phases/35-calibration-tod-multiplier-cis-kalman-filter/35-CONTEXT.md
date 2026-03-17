# Phase 35: Calibration + TOD Multiplier + CIS Kalman Filter - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Make every confidence number a reliable probability estimate: isotonic regression calibration against historical outcomes, time-of-day win rate adjustment applied pre-CIS aggregation, and a Kalman-smoothed CIS score as the new fire condition gate. No new plugins. No new services. Three enhancements to the existing signal confidence pipeline in `signal_generator_service` and `weight_updater`.

Design framing: Renaissance — instrument everything, earn the right through proof, degrade gracefully, adapt automatically.

</domain>

<decisions>
## Implementation Decisions

### Calibration Job — Architecture

- New module `src/intelligence/ml/confidence_calibrator.py` with `run_calibration_update(db_manager)` async function
- Called from `weight_updater.py` after `run_weight_update()` — same 30-min timer tick, same DB connection, no new systemd unit
- Independent failure domain: calibration failure logs and returns; weight update still completes
- Runs every 30 min (same cadence as weight_updater) — continuous adaptation, not batch-on-demand

### Calibration — Data Storage

- `calibrated_confidence = NULL` when N < 100 for a (plugin_name, timeframe) pair — explicit, unambiguous, no data conflation
- Never store raw confidence in `calibrated_confidence` as a passthrough — training pipeline must be able to isolate truly calibrated rows via `WHERE calibrated_confidence IS NOT NULL`
- `raw_cis_score`, `filtered_cis_score`, `calibrated_confidence` all land as **signal_ledger DB columns** (not log-only) — every bar's confidence state is a labeled training sample; logs rotate, DB doesn't
- DB migration adds 3 columns to `signal_ledger`

### Calibration — Aggregator Integration (CAL-03)

- `calibrated_confidence` is the **sort key** in `_build_all_ranked()` when non-NULL; raw confidence is the fallback
- Do NOT mutate the existing `confidence` field in signal dicts — add `calibrated_confidence` as a new field that travels through the pipeline alongside raw
- Applied as the **final step** after all quality multipliers (perf_multiplier, Hurst, KS drift, GARCH)
- Calibration scope: per winning signal's `(plugin_name, timeframe)` — the post-CIS/post-Kalman winner gets calibrated using its setup's isotonic curve

### TOD Multiplier — Granularity + Seeding

- Seeded by **`regime_type`** (3 groups: `trend`, `mean_reversion`, `any`) × timeframe × hour_ET — NOT per individual plugin
- Rationale: 28 plugins × 4 TFs × 24 hours = 2,688 cells; regime_type grouping = ~120 meaningful cells; exits prior-only mode orders of magnitude faster
- **Bayesian smoothing** replaces the hard N=20 switch from requirements:
  ```
  effective_multiplier = (α × prior + N × empirical_win_rate_ratio) / (α + N)
  ```
  where α=20 (prior weight = 20 virtual observations). Prior is continuously overridden by evidence — no discontinuity, no "prior mode" vs "data mode"
- Session priors (used as Bayesian α seed):
  - NY open (09:30–10:00 ET): `trend` +10%, `mean_reversion` neutral, `any` neutral
  - Lunch chop (11:30–13:00 ET): all regime_types −10%
  - London close (14:00–15:00 ET): `mean_reversion` +8% (SMC), `trend` neutral, `any` neutral
  - MOC (15:30–16:00 ET): `any` +10% (session extremes plugins), others neutral
- Multiplier clamped to [0.7, 1.3] as specified in TOD-02
- Cached in-memory dict refreshed every 4h (per TOD-02)

### TOD Multiplier — Application Point

- Applied **pre-CIS aggregation**: each I7 plugin's raw confidence × TOD_multiplier before feeding into CIS scoring
- NOT post-CIS: the multiplier must affect signal *selection* (whether a plugin's confidence contributes enough to push CIS past threshold), not just cosmetic ranking
- Example: MomentumBreakout fires confidence=0.62 during lunch chop (TOD=0.7) → adjusted=0.43 → weaker CIS contribution → may not clear CIS gate. Correct behavior: lunch chop suppresses signals, not just their rank.

### CIS Kalman Filter — Architecture

- Per-(symbol, timeframe) 1D local-level Kalman filter wrapping the CIS score in `signal_generator_service`
- `CISScorer` remains stateless — Kalman state lives in the service layer (per STATE.md constraint)
- Reuses `KalmanTrendPlugin` local-level recursion pattern (predict → update), not the plugin itself — the filter runs on CIS scores, not price

### CIS Kalman Filter — Parameters

- **Per-TF fixed Q/R from config**, NOT GARCH-adaptive
- Rationale: GARCH sigma is in price units; applying it to scale R for a CIS filter in [-1, 1] space is dimensionally incoherent. Real noise driver is timeframe — 1m CIS is inherently noisier than 1h CIS
- Parameters stored in `config/kalman_parameters.json` alongside existing price Kalman parameters, keyed by timeframe:
  - 1m: higher R (more observation noise, fast-moving CIS)
  - 5m/15m: intermediate R
  - 1h: lower R (smoother CIS, more weight on observation)
  - Starting values from requirements: Q=0.01, R=0.05 — tune per TF before shipping
- No hardcoding — config-driven, adjustable without code change

### CIS Kalman Filter — Fire Condition Transition

- **Shadow mode using existing `is_shadow=TRUE` infrastructure** — not a feature flag, not a parallel log
- New fire condition: `filtered_cis > 0.35 AND raw_cis > 0.28 AND buckets_agreeing ≥ 3`
- Signals that pass current condition but fail new condition: written to `signal_ledger` with `is_shadow=TRUE` + suppression reason logged (which sub-condition failed: filtered_cis / raw_cis / buckets_agreeing)
- **Shadow window: N≥30 suppressed signals per regime_type** — not calendar time. Shadow mode continues until all three regime_types reach threshold (same promotion gate as `validate_alpha.py`)
- After threshold met: run outcome analysis on suppressed signals; if suppressed signals have worse outcomes → hard switch; data decides, not intuition
- No FIRE_CONDITION_V2 env var — feature flags are technical debt masquerading as caution

### Dashboard

- Signal card headline: `calibrated_confidence` as the single confidence number (true probability estimate)
- Drill panel: `raw_cis_score`, `filtered_cis_score`, `calibrated_confidence` displayed side by side for full transparency
- No other dashboard changes in this phase

### Claude's Discretion

- Exact Kalman Q/R values per TF (starting from Q=0.01, R=0.05 baseline from requirements; tune per TF)
- `confidence_calibration` table schema details (breakpoints/values array columns per CAL-01)
- Suppression reason field format in signal_ledger
- How the service refreshes calibration curves every 30 min (mirror existing `_cis_scorer` weight refresh pattern)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §CAL-01, CAL-02, CAL-03 — calibration table schema, batch job spec, aggregator integration
- `.planning/REQUIREMENTS.md` §TOD-01, TOD-02 — TOD multiplier spec, session priors, multiplier range
- `.planning/REQUIREMENTS.md` §KAL-01, KAL-02 — Kalman filter spec, fire condition, logging requirements

### Existing Implementation — Reuse Targets
- `src/intelligence/context/kalman_trend.py` — KalmanTrendPlugin local-level state machine to replicate for CIS filter (Q/R recursion pattern, not the plugin itself)
- `src/intelligence/weight_updater.py` — existing timer entry point; calibration job wires in here
- `src/intelligence/trading/cis_scorer.py` — CISScorer (stays stateless); `_build_all_ranked()` gets calibrated_confidence sort key
- `config/kalman_parameters.json` — existing Kalman config file; add per-TF CIS Kalman entries here

### Prior Phase Context
- `.planning/phases/32-stop-architecture-extended-divergence-stack/32-CONTEXT.md` — stop architecture decisions
- `.planning/phases/34-i4-infrastructure-anchored-vwap-volume-profile/34-CONTEXT.md` — plugin architecture decisions; CISScorer stateless constraint

No external specs — requirements fully captured in decisions above and REQUIREMENTS.md.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `KalmanTrendPlugin` (`src/intelligence/context/kalman_trend.py`): local-level 1D Kalman (predict/update recursion, `_state` dict per symbol+TF, `_Q`/`_R` params loaded from config). Replicate this exact pattern for CIS Kalman — don't import the plugin, copy the recursion.
- `weight_updater.py` `run_weight_update(db_manager)`: async function wired to systemd timer. `run_calibration_update(db_manager)` drops in immediately after this call.
- `signal_ledger.py` `is_shadow` column + existing shadow signal write path — ready to use for fire condition shadow mode; just add suppression reason to the write call.
- `validate_alpha.py` N≥30 + p<0.05 promotion gate — reuse same threshold logic for shadow mode graduation decision.

### Established Patterns
- `_cis_scorer` weight refresh in `signal_generator_service`: hot-swap via `update_weights()` every 30 min from DB. CIS calibration curve refresh follows identical pattern — load from `confidence_calibration` table, cache in service layer.
- `setup_performance` perf_multiplier cache: loaded at startup and every 15 min. TOD multiplier cache follows same pattern but refreshes every 4h.
- `KalmanTrendPlugin._state`: `{symbol: {tf: {x_est, P_est}}}` — CIS Kalman state uses identical structure: `{symbol: {tf: {x_est, P_est}}}`.

### Integration Points
- `signal_generator_service._process_signal()` — TOD multiplier applies here (pre-CIS, per I7 plugin confidence)
- `signal_generator_service._build_all_ranked()` — calibrated_confidence sort key added here (final step)
- `signal_generator_service` CIS scoring call — Kalman wraps the `cis_scorer.score()` return value here
- DB migration: `signal_ledger` gets `raw_cis_score DOUBLE PRECISION`, `filtered_cis_score DOUBLE PRECISION`, `calibrated_confidence DOUBLE PRECISION` — zero-padded migration file `038_...` is taken (roll detection); use `039_calibration_fields.sql`

</code_context>

<specifics>
## Specific Ideas

- Bayesian smoothing for TOD (α=20) is a deliberate enhancement beyond the N=20 hard switch in requirements — planner should implement the smooth version, not the step function
- Shadow window uses N≥30 per regime_type as the graduation threshold, not the 1-week calendar time from requirements — same statistical standard as validate_alpha.py
- TOD multiplier applies PRE-CIS (to I7 plugin confidence), not post-CIS — this is a refinement beyond the requirements which say "before aggregation" but don't emphasize the causal significance
- Jim Simons framing applied throughout: segment relentlessly (regime_type not per-plugin), earn the right through proof (N-based not time-based shadow), never drop data (all 3 fields in DB), let the system run (Bayesian smoothing not hard switches)

</specifics>

<deferred>
## Deferred Ideas

- GARCH-adaptive Kalman Q/R for CIS: dimensionally incoherent (GARCH in price units, CIS in [-1,1]). Defer until a proper CIS-space volatility measure exists.
- Per-plugin TOD multiplier (28 plugins × 4 TFs × 24 hours = 2,688 cells): defer until N is sufficient per cell — likely v2.0 when signal volume is 10×.
- Learned Kalman parameters via EM (Expectation-Maximization on Q/R): elegant but complex; note for future ML phase.

</deferred>

---

*Phase: 35-calibration-tod-multiplier-cis-kalman-filter*
*Context gathered: 2026-03-17*
