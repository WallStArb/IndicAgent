# Phase 126: Signal Universe Hardening — Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-06-14-phase-126-signal-universe-hardening.md + docs/plans/2026-06-14-phase-126-pipeline-annotation-layer.md)

<domain>
## Phase Boundary

Fix four mechanical defects that make the clean replay (Phase 127) meaningless as ML training data:

1. **Root Crime 1** — 47.6% of signals stop at entry because zones are sub-ATR (ticket: zone_too_narrow). Zone width gate in `frame_trade()` with APR-backed per-asset-class thresholds.
2. **Root Crime 2** — 8 signal-generation plugins are exempt from confluence annotation (`_I7_I6_EXEMPT`). Delete the exemption; wire all plugins to I6.
3. **Root Crime 3** — `trad_FVGFill` has 8.93% equity win rate (-0.647 avg pnl_r) from a suspected entry-timing defect (fires on approach, not on fill confirmation).
4. **Root Crime 4** — Broken gate conditions: `trad_MeanReversion` dual-gate mutual exclusion (39 signals in 1.44M history); zero-signal time-specific plugins (SessionExtremesSetup, ORB15, ORB30) need diagnosis.

**Also in scope:**
- Pipeline-layer annotation: move `capture_signal_features()` from plugin bodies to `signal_processor._annotate_signal()`, applied uniformly to every signal
- Per-plugin IC validation + detection condition verification audit

**Not in scope:** 3-table migration (Phases 128-130), CounterfactualTracker, calibration retraining, asset-class-specific plugin redesign.

**Wave structure:**
- Wave 0 (P126-00): USDJPY anomaly diagnostic — runs before all code changes
- Wave 1 (P126-01): Universal zone width gate + APR seeds — after Wave 0, blocks replay
- Wave 2 (P126-02/03/04): Plugin completeness (parallel with Wave 1, after Wave 0)
- Wave 3 (P126-06): Pipeline-layer annotation (parallel with Wave 2, after Wave 0)
- Wave 4 (P126-05): IC validation + detection audit (after Wave 2)

</domain>

<decisions>
## Implementation Decisions

### D-01: Zone width gate location
Gate belongs in `frame_trade()` AFTER `_resolve_zone_bounds()` returns, universally applied regardless of zone source path. NOT in `_resolve_zone_bounds()` (that function's contract is geometry resolution only). Returns `_reject_frame("zone_too_narrow:{zone_source}", ...)`. This catches all zone source paths (supply_demand, fvg, ob, structural engine, sweep band, ATR fallback).

### D-02: ATR-derived zones are self-exempt
Sweep band (`entry ± 0.5×ATR` = 1.0×ATR wide) and ATR fallback zone (`entry ± [1.0, 0.5]×ATR` = 1.5×ATR wide) pass the gate trivially by construction. No special-case code needed — they exceed the threshold mathematically.

### D-03: Zone width APR seeds
Initial estimates from noise-band analysis (data-derived in Step 1 of P126-01 before any code changes):
- `feature.zone_engine.min_zone_width_atr` (default) = 1.5
- `feature.zone_engine.min_zone_width_atr.equity_etf` = 1.5
- `feature.zone_engine.min_zone_width_atr.forex` = 1.0
- `feature.zone_engine.min_zone_width_atr.futures` = 1.5
Config_schema descriptions MUST include provenance: `[initial_estimate — noise band analysis: zone_width + buffer (0.25×ATR) ≥ 2.0×ATR → zone_width ≥ 1.75×ATR; rounded to 1.5. ML learning target post Phase 127 replay.]`
Step 1 diagnostic query (zone_width/ATR ratio by plugin and asset class) MUST run before writing gate code; thresholds set from data, not assumed.

### D-04: Stop distance gate (non-zone path only)
APR key `feature.zone_engine.min_stop_distance_atr` = 0.5 with per-asset-class variants.
This gate applies ONLY to the ATR-fallback stop path (non-zone trades). For zone trades, the zone width gate (D-01/D-03) IS the stop distance gate — zone_width + buffer ≈ total stop distance from entry. The two gates are semantically independent: one sets intent (MIN_STOP_ATR_MULTIPLIER, an ML-tunable key), the other is the absolute floor that ML cannot breach. Historical corpus contamination (median equity stop $0.31) is from before MIN_STOP_ATR_MULTIPLIER=1.0 was added — NOT an active code bug; clean replay (Phase 127) regenerates signals through current code.

### D-05: Config service wiring for trade_framer
`trade_framer.py` currently has no config service. Must add `set_config_service()` pattern (matching `zone_engine.py`) and wire at `IntelligencePipeline` startup.

### D-06: Delete _I7_I6_EXEMPT entirely
Delete the `_I7_I6_EXEMPT` frozenset from `register_plugins.py`. For Wave 2 plugin wiring: in Phase 126 Wave 2, each of the 8 plugins gets `requires_i6_confluence = True` and `capture_signal_features()` call. THEN in Wave 3 (pipeline annotation), ALL plugins have `capture_signal_features()` stripped — including the 8 just wired. This means Wave 2 wires them correctly and Wave 3 removes the function call for everyone. After both waves: `_I7_I6_EXEMPT` is gone, all plugins have annotation via the pipeline, `validate_tier()` enforcement is removed (annotation is infrastructure, not per-plugin ClassVar).

### D-07: Pipeline annotation — _annotate_signal() in signal_processor.py
After any I7 plugin fires, before quality gate, `_annotate_signal(sig, flat_features)` runs on every raw signal:
1. `sig["context_features"] = flat_features` — full I1-I6 snapshot (not 30-key curated subset)
2. Derives and surfaces top-level ECL fields: `ctf_score`, `ctf_confirmed`, `zone_friction_score`
Wire immediately after `pre_quality_confidence` stamping and before alpha decay so even regime-suppressed signals carry full context.
`_SURFACED_ECL_FIELDS` tuple documents which fields get promoted to indexed top-level columns.

### D-08: context_features = full flat_features snapshot
After Phase 126, `signal["context_features"]` equals the full `flat_features` dict for every signal. No filtering, no 30-key curated subset. `build_flat_features()` already filters None values. New tier outputs appear in `context_features` automatically — zero code changes needed when a new I6 sub-score is added.

### D-09: zone_friction_score formalization
`zone_friction_score` is currently produced only in `supply_demand_setup.py` plugin body, not in IntelligenceEvent schema. Must be moved to a tier plugin (I3 structure or I6 confluence — decision based on what inputs it requires). After formalization: appears in `flat_features` → automatically in every signal's `context_features`. Remove computation from plugin body.

### D-10: capture_signal_features() deprecation, not deletion
Mark deprecated in Phase 126 with comment: "DEPRECATED (Phase 126): Annotation is now pipeline-layer responsibility. See signal_processor._annotate_signal(). Retained for one release cycle; delete in Phase 128 after confirming no external callers." Do NOT delete the function in Phase 126.

### D-11: SIGNAL_SCHEMA_VERSION bump required
`context_features` changes from 30-key curated subset to full `flat_features` snapshot. Increment `SIGNAL_SCHEMA_VERSION` in `src/intelligence/trading/signal_schema.py`. Add version changelog comment noting schema change and implications for ML training segmentation.

### D-12: Plugin disposition rule — shadow_only=True only, never remove from TIER_I7
Every signal firing is training data. Removal from TIER_I7 is never a valid disposition. Broken/anti-signal plugins → `shadow_only=True` with documented rationale. Plugins stay in TIER_I7 permanently.

### D-13: IC validation thresholds
- `IC > 0.02` AND `hit_rate CI lower > 0.45`: VALIDATED
- `IC between -0.02 and 0.02` OR `hit_rate CI includes 0.5`: NOISE CANDIDATE (document, no action)
- `IC < -0.02` OR `hit_rate CI upper < 0.45`: ANTI-SIGNAL → `shadow_only=True`
Bootstrap 95% CI on hit_rate (10,000 resample). Only plugins with >= 30 outcomes in signal_ledger qualify.

### D-14: trad_MeanReversion — diagnose then decide
Run SQL probe to confirm dual-gate mutual exclusion. If `both_gates_ok / total_bars < 0.01`, lower Gate A threshold (trend_regime_max) to 0.2 and add APR key. If still < 100 fires in 30-day window after fix → `shadow_only=True` with "dual-gate conflict diagnosed; insufficient activation; parked for redesign."

### D-15: trad_FVGFill — diagnostic-first
Do NOT change code until root cause is confirmed. If entry-timing defect (fires on approach, not fill confirmation): fix to require penetration + close inside gap. After any fix: run SQL comparison on signal_ledger. If no clear defect → `shadow_only=True` with "catastrophic equity performance (8.93% win rate), mechanism unknown, parked for redesign."

### D-16: Time-specific plugin verdicts
Each of SessionExtremesSetup, ORB15, ORB30 must have a documented verdict in the plugin docstring: CORRECT-RARE / BROKEN / SCOPE-MISMATCH. Write one targeted unit test for ORB15/ORB30 with synthetic RTH open bar sequence.

### D-17: Wave 0 must complete before code changes
USDJPY diagnostic (P126-00) runs first. Findings written to `docs/plans/2026-06-14-phase-126-usdjpy-diagnostic.md`. Verdict informs whether USDJPY data is fit for replay as training data. If data quality issue found → fix data pipeline in Wave 0 before proceeding.

### D-18: APR dependency on Phase 125
If Phase 125 is not complete when Phase 126 runs, Phase 126 code that reads APR keys must include a hard-coded fallback with a TODO comment noting the APR key. This keeps Phase 126 executable independently.

### Claude's Discretion
- Migration numbering (NNN in migration filename) — use next available
- Exact SQL JOIN syntax for intelligence_features ATR extraction
- Python bootstrap CI implementation (scipy or manual resampling — either acceptable)
- Whether `zone_friction_score` belongs in I3 or I6 — read supply_demand_setup.py to determine inputs; choose tier based on where those inputs live

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 126 Design Docs (full implementation detail, SQL probes, step-by-step)
- `docs/plans/2026-06-14-phase-126-signal-universe-hardening.md` — Root crimes 1-4, wave structure, P126-00 through P126-05, all SQL probes, success criteria
- `docs/plans/2026-06-14-phase-126-pipeline-annotation-layer.md` — Full P126-06 spec: _annotate_signal() implementation, zone_friction_score formalization, strip capture_signal_features(), clean make_signal_from_frame(), delete _I7_I6_EXEMPT, deprecate capture_signal_features(), bump SIGNAL_SCHEMA_VERSION, unit tests

### Core Implementation Files
- `src/intelligence/trading/trade_framer.py` — Zone width gate + stop distance gate insertion point; validate_stop_against_zone; _reject_frame(); _resolve_zone_bounds()
- `src/intelligence/trading/zone_engine.py` — MIN_ZONE_WIDTH_ATR constant; set_config_service pattern to replicate
- `src/intelligence/register_plugins.py` — _I7_I6_EXEMPT frozenset, TIER_I7 list, validate_tier()
- `src/intelligence/signal_processor.py` — _annotate_signal() insertion point (after pre_quality_confidence stamping)
- `src/intelligence/trading/signal_schema.py` — SIGNAL_SCHEMA_VERSION, make_signal_from_frame()
- `src/intelligence/trading/confidence_utils.py` — capture_signal_features() (to be deprecated)
- `src/intelligence/schemas.py` — IntelligenceEvent, tier sub-models; zone_friction_score to be added here
- `src/intelligence/trading/feature_flattening.py` — build_flat_features(); flat_features key set

### Architecture Foundation
- `docs/architecture/setup-confidence-patterns.md` — ECL pattern spec; 6 GOOD patterns
- `docs/foundation/parameter-store.md` — APR key naming, config_schema migration format
- `CLAUDE.md` — Parameter Store section (namespace: `feature.zone_engine.*`, `threshold.*`)

### Signal Quality Audit Output Target
- `docs/plans/2026-06-14-phase-126-signal-quality-audit-results.md` — Produced by P126-05; IC league table + detection verifiability table

</canonical_refs>

<specifics>
## Specific Ideas

### Wave Dependency Map
- P126-00 (USDJPY diagnostic): runs first; SQL-only; no code changes unless data quality issue
- P126-01 (zone width gate): depends on P126-00 verdict; code changes in trade_framer.py + migration
- P126-02 (8 exempt plugins + time-specific + MeanReversion + FVGFill): depends on P126-00; parallel with P126-01 [absorbs P126-03 and P126-04]
- P126-06 (pipeline annotation): depends on P126-00 AND P126-02; Wave 3 [serialized after Wave 2 so strip-sweep runs after Wire-8-plugins completes]
- P126-05 (IC audit + detection correctness): depends on P126-02 completing; Wave 4

### Key SQL Probes (already in design docs)
All diagnostic SQL queries are written in the design doc. Planners should reference these rather than inventing new ones. Wave 0 USDJPY probes, Wave 1 zone_width/ATR ratio query and proxy rejection count query, Wave 2 MeanReversion dual-gate probe, Wave 4 IC league table query.

### Asset Class Detection
`asset_class` field for zone width per-asset-class dispatch: populated by SignalContext or built into `build_flat_features()`. Must verify presence in features dict at `frame_trade()` call time before coding.

### _reject_frame() return type note
`_reject_frame()` returns a `TradeFrame` (not a signal dict). Plugins call `frame_trade()` and check `trade_frame.viable` before emitting. The gate is inside `frame_trade()`, not in a plugin body.

</specifics>

<deferred>
## Deferred Ideas

- Full APR migration of ALL trade_framer.py constants (ATR_STOP_DEMAND_MULTIPLIER, etc.) — tracked in `.planning/todos/pending/` as a separate phase task
- `capture_signal_features()` deletion — Phase 128 (retained one release cycle)
- Asset-class-specific detection logic redesign — v2.11 (requires replay data first)
- Calibration curve retraining — Phase 127 (requires clean replay)
- CounterfactualTracker — Phase 130 (requires trade_frames table)

</deferred>

---

*Phase: 126-signal-universe-hardening*
*Context gathered: 2026-06-14 via PRD Express Path from design docs*
