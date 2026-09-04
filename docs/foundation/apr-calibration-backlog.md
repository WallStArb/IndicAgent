# APR Calibration Backlog

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-09-04

## What this is

Every APR key's `config_schema.description` carries a provenance tag (`[initial_estimate]`,
`[conventional]`, `[rca_analysis]`, `[user_preference]` — see
`docs/foundation/adaptive-parameter-registry.md`'s description-field convention). Until this
doc existed, finding out which gate-shaped thresholds are still unvalidated guesses meant
grepping all ~670 `config_schema` rows and reading each migration by hand. This is that list,
built once (2026-07-27, prompted by a user rigor check after tracing
`alpha.validation.regime_gate_min_clusters=20` back to an explicit "no empirical calibration
performed yet" admission) and meant to be updated whenever a key gets a real
`[rca_analysis]`/`ml_learned` `config_history` entry — not re-derived from scratch each time.

**Scope note:** this covers keys that function as a **statistical pass/fail gate or ceiling** —
code somewhere compares a measured value against the threshold to decide pass/fail,
include/exclude, or crash/continue. It does not cover APR-exempt categories (service identity,
schema names, statistical concept definitions, DAG topology) — see the parent doc's exempt list.

## Section 1 — Genuinely guessed, gate-shaped, needs real calibration

Ordered by consequence: live `services/*.py` production path first, analysis-script-only last.
**None of these should be casually changed** — several are frozen under a "no post-hoc gate
renegotiation" discipline (same as `alpha.scoring.bootstrap_random_state`, WR-01) precisely
because they gate already-recorded verdicts. Recalibrating any of them requires a dedicated
empirical study committed *before* looking at whether it changes a pending decision, not a
quick guess-swap.

| Key | Value | Gates | Why it's a guess |
|---|---|---|---|
| `alpha.scoring.max_drawdown_ratio` | 0.25 | Gate 2 execution-proof ceiling (`alpha_scorer.py`, `counterfactual_tracker.py`) — the exact number Phase 148/166 failed against (9.6x-26.2x over) | Tagged `[conventional]` but migration 248 cites no external source, only "frozen, PRE-REGISTERED." Same epistemic status as `[initial_estimate]`, mistagged. |
| `alpha.scoring.min_sharpe` | 0.5 | Same Gate 2 tables | Same pattern — pre-registered discipline is real, the number's origin isn't cited. |
| `alpha.construction.attribution_max_static_r2` | 0.50 | Phase 167 Validation Gate 2 (`cross_sectional_spread_tracker.py`) — Phase 167's headline `gate2_passes_overall=true` rests on this number | `[initial_estimate]`, migration 260's own text: "No prior empirical basis exists in this codebase for this specific ceiling; treat as a starting point pending live measurement, not a settled statistical result." |
| `alpha.ensemble.effective_n_gate` | 3.0 | Emission gate on every `alpha_events` row (`alpha_publisher.py`, `ensemble_trainer.py`) | `[initial_estimate]`: "ensures at least 3 effective independent predictors" — asserted, not measured. |
| `alpha.ensemble.max_cluster_correlation` / `max_cluster_weight` | 0.80 / 0.40 | Cluster deflation before ensemble weighting (`ensemble_trainer.py`) | `[initial_estimate]`; migration says "recalibrate by examining the LW correlation matrix post corpus run" — never done. |
| `alpha.ic.cluster_max_corr` | 0.70 | BH-FDR feature clustering (`ic_engine.py`) | `[initial_estimate]`, "candidate ML learning target" — no data behind 0.70 specifically. |
| `alpha.ic.hac_max_lag` | 3 | Newey-West HAC correction on IC Sharpe (`ic_engine.py`) | `[initial_estimate]`: "revise upward if IC series autocorrelation extends beyond lag 3" — this corpus's actual autocorrelation has never been checked. |
| `alpha.ensemble.mv_condition_max` / `alpha.ic.partial_control_condition_max` | 1000 (both) | Ill-conditioning guard on mean-variance/partial-IC solves | Both `[initial_estimate]`; the second migration admits it copied the first ("matching the E2 mean-variance path's precedent") — a guess citing a guess. |
| `alpha.tag_calibrator.*` (`min_sample_n`=60, `half_life_min/max`=30/365d, `expiry_consecutive_fails`=3, `discovery_oos_days`=63) | — | `services/tag_calibrator.py` — governs when an empirical instrument tag is trusted/expired | All `[initial_estimate]`, no measurement cited in any of the seeding migrations. |
| `alpha.concept_registry.ensemble_strategy_min_observations` / `ensemble_strategy_min_promotion_consecutive` | 1000 / 2 | Concept promotion gate | `[initial_estimate]` — the *shape* of the reasoning is documented (non-overlapping CIs are strict), the specific number isn't. |
| `alpha.ensemble_ic.min_obs_per_regime` / `wf_stability_ratio` / `stop_target_min_qualifying_symbols` | 3000 / 3.0 / 3 | Data-sufficiency and fold-stability diagnostics (`ensemble_ic_engine.py`) | All `[initial_estimate]`, no empirical basis cited. |
| `alpha.validation.regime_gate_min_clusters` | 20 | Day-cluster coverage floor — the key that started this audit | `[initial_estimate]`: "no empirical calibration performed yet." Lower blast radius than the rest of this table — consumed only by `scripts/analysis/*.py` one-off eval scripts, not a live daemon. |
| `threshold.signal_audit.verifiable_population_floor` / `partial_population_floor` | 0.90 / 0.50 | Signal audit verdict tiers | `[initial_estimate]`, no data cited — consuming pipeline (I1-I7 signal audit) is part of the archived v2.x tier, not confirmed live; lower priority to recalibrate for that reason. |
| `alpha.decay.demotion_min_consecutive` | 2 | `active → shadow_only` demotion hysteresis for the `feature` domain's sync (`ic_engine.py`) lifecycle path (migration 321, todo 323) — gates `ConceptRegistryService.is_demotion_eligible()` | `[initial_estimate]`: migration's own text picks 2 "as the most directly defensible symmetric starting point" by matching `alpha.concept_registry.ensemble_strategy_min_promotion_consecutive`'s value — a borrowed number, not a measurement against this project's own demotion history. |

**Retired since the last pass:** `alpha.feature_registry.min_ic_sharpe_default` (seeded in
migration 169, the old `feature_registry` system) no longer exists in `config_schema` —
Phase 170 (migration 311) dropped `feature_registry`/`feature_transition_log` and deleted
`FeatureRegistryService`; `concept_registry` is the sole feature-lifecycle system now. Removed
from this table rather than left as a dangling reference to a deleted key.

## Section 2 — Tagged conservatively but actually has real empirical backing

Don't recalibrate these — the number is fine, only the tag undersells it.

- **`feature.zone_engine.min_zone_width_atr.futures`** (1.5): moved here 2026-09-04 — this doc
  previously listed it in Section 1 as `[initial_estimate]` with "no live futures zone data,"
  but `config_schema.description` now reads `[rca_analysis] Phase 126 zone entry width gate for
  futures instruments. Noise-band analysis." The recalibration happened directly via migration
  (no `config_history` `rca_analysis` row — this is a schema-description edit, not a runtime
  `ConfigService.set()` write), so it wouldn't show up in a `config_history` grep. Live consumer
  confirmed: `src/intelligence/trading/trade_framer.py:164` (`_min_zone_width_atr`).
- **`feature.zone_engine.min_zone_width_atr.fx`** (1.0): tagged `[initial_estimate]`, but the
  description cites a real measurement (forex zones' p50 ~1.41-1.43x ATR on EURUSD/USDCHF).
- **`feature.hmm.n_components`** (5): **fixed 2026-07-27, migration 265.** Migration 172 ran a
  real BIC study (SPY/TLT/GLD/EWT 5m, 467k+ obs each, K=5 minimizes BIC unanimously across all
  4 symbols) but `config_schema.description` still described the pre-study K=3 model and
  `[conventional]` tag for months afterward — pure documentation drift, now corrected to
  `[rca_analysis]` with the real citation. Worth checking for other keys with this same
  "migration fixed the value, description never caught up" pattern.
- **`alpha.decay.guard_fail_rate_min/max`** (0.85/0.995): correctly tagged `[rca_analysis]`
  already — the positive-contrast example the rest of this doc should look like ("grounded in
  the 2026-07-19 RCA against EIC-04's established 96-98% normal failure-rate base").

**Checked and confirmed NOT a gap despite superficially matching the pattern:**
`alpha.equity_regime.vix_low_pct`/`vix_high_pct` (0.33/0.67) — an initial audit pass flagged
this as "same bug shape as todo 092's `breadth_frac` fix" (a raw-value cut never
rank-transformed). Verified directly against `src/intelligence/regime_signals/breadth_vol.py`:
`_compute_vix_pct_rank()` already calls `_causal_expanding_rank(vix_z)` before the 0.33/0.67
cut — it's rank-transformed exactly like `breadth_pct` now is post-todo-092, not a raw cut.
No bug here. Kept as a record of a false lead that got caught by verification, not silently
dropped.

## Section 3 — Gate-shaped keys with no provenance tag at all

A documentation gap distinct from the calibration gap above — these predate the tagging
convention (migration 103, Phase 109 era) and were never backfilled.

- `regime.dur_min`, `regime.prob_min`, `swarm.min_confidence` — all three still exist in
  `config_schema` untagged, but their only consumer (`src/intelligence/pipeline/signal_processor.py`)
  is under the archived v2.x I1-I7 pipeline (no live daemon). Low priority — dead-path, not a
  live risk.
- `roll.threshold_default` — no current code reference found; likely dead, unclear.
- The 23 `alert.lag.*` consumer-lag ceilings — infra alerting thresholds, not statistical
  gates; lower priority for this specific backlog.
- `ui.signals.min_confidence` — carries an informal `[data-derived]` tag (not one of the four
  canonical provenance tags) describing 0.40 as an empirically-derived breakeven threshold,
  with no cited study to check it against.

## How to use this doc

When picking up calibration work: prioritize Section 1 top-to-bottom (live production impact
first). When a key gets a real empirical study, move it to Section 2 with a one-line citation,
same as `feature.hmm.n_components` above. Don't let this doc silently go stale — if you
recalibrate something here, update this file in the same change, not later.
