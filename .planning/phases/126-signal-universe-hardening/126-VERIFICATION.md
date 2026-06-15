---
phase: 126-signal-universe-hardening
verified: 2026-06-15T00:00:00Z
status: gaps_found
score: 9/12 must-haves verified
gaps:
  - truth: "REQUIREMENTS.md SIGNAL-QUALITY-01 text specifies gate in _resolve_zone_bounds() returning no_signal(); actual implementation places gate in frame_trade() after _resolve_zone_bounds()"
    status: partial
    reason: "Gate is correctly implemented in frame_trade() per the PLAN must_haves (D-01) and design doc — but REQUIREMENTS.md text is inconsistent with actual implementation. Also REQUIREMENTS.md specifies per-asset-class seeds as equity_etf:0.5 / forex:0.25 / futures:0.35 but migration 134 seeds equity:1.5 / fx:1.0 / futures:1.5 with different key names. Requirements text has stale/incorrect values."
    artifacts:
      - path: "src/intelligence/trading/trade_framer.py"
        issue: "Implementation is architecturally correct (gate in frame_trade, not _resolve_zone_bounds) — but REQUIREMENTS.md says the opposite. No code defect; REQUIREMENTS.md is the stale artifact."
      - path: ".planning/REQUIREMENTS.md"
        issue: "SIGNAL-QUALITY-01 still marked [ ] (Pending in traceability table); gate location, threshold values, and key names differ from implemented state."
    missing:
      - "Update REQUIREMENTS.md SIGNAL-QUALITY-01 to reflect: (a) gate lives in frame_trade() after _resolve_zone_bounds() per D-01; (b) APR key names are feature.zone_engine.min_zone_width_atr.{equity,fx,futures} not equity_etf/forex; (c) threshold values are equity:1.5, fx:1.0, futures:1.5 (data-derived); (d) mark requirement satisfied"

  - truth: "REQUIREMENTS.md SIGNAL-QUALITY-02 states all 8 formerly-exempt plugins have requires_i6_confluence=True and call capture_signal_features() — but Wave 3 (P126-06) removed both attributes from all plugins"
    status: partial
    reason: "REQUIREMENTS.md SIGNAL-QUALITY-02 was written before the pipeline annotation layer (P126-06) was added to Phase 126 scope. The requirement text demands requires_i6_confluence=True and capture_signal_features() calls, but Phase 126 Wave 3 correctly removed both as part of migrating annotation to the pipeline layer. The code is architecturally correct; the requirement text is stale."
    artifacts:
      - path: ".planning/REQUIREMENTS.md"
        issue: "SIGNAL-QUALITY-02 still marked [ ] (Pending); text demands per-plugin capture_signal_features() calls which were intentionally stripped in P126-06; does not mention _annotate_signal() pipeline annotation; frozenset name is _CONFLUENCE_EXEMPT_PLUGINS but actual was _I7_I6_EXEMPT."
    missing:
      - "Update REQUIREMENTS.md SIGNAL-QUALITY-02 to reflect: (a) _I7_I6_EXEMPT deleted (not _CONFLUENCE_EXEMPT_PLUGINS); (b) requires_i6_confluence and capture_signal_features() removed from all plugins — annotation moved to signal_processor._annotate_signal() (P126-06); (c) SIGNAL_SCHEMA_VERSION bumped to v4; (d) mark requirement satisfied"

  - truth: "stopped_at_entry rate < 15% on 10K-signal replay is measurable"
    status: failed
    reason: "SIGNAL-QUALITY-01 includes stopped_at_entry < 15% as a Phase 126 success criterion. This is explicitly deferred to Phase 127 replay — signal_ledger has no outcomes data (shadow_outcome all null). The gate enforces zone_width >= threshold but the downstream pnl_r outcome metric cannot be measured until Phase 127 clean replay runs."
    artifacts:
      - path: ".planning/REQUIREMENTS.md"
        issue: "stopped_at_entry < 15% appears as part of SIGNAL-QUALITY-01 but cannot be verified until Phase 127"
    missing:
      - "Acknowledge in REQUIREMENTS.md that stopped_at_entry rate measurement is Phase 127 (REPLAY-01 deliverable), not Phase 126 — or split SIGNAL-QUALITY-01 into two requirements"
---

# Phase 126: Signal Universe Hardening — Verification Report

**Phase Goal:** Harden the signal universe by eliminating the four root crimes — sub-ATR zones (stop at entry), missing I6 confluence wiring, zero-signal time-specific plugins, and a biased heterogeneous training corpus — so Phase 127 clean replay runs on a defensible signal set.
**Verified:** 2026-06-15
**Status:** gaps_found (3 gaps — all in REQUIREMENTS.md stale text, not code defects)
**Re-verification:** No — initial verification

## Important Finding Up Front

The code is correct. The three gaps are all REQUIREMENTS.md text inconsistencies: the requirements were written before (a) the gate location decision D-01 was finalized, (b) the pipeline annotation layer (Wave 3) was added to Phase 126 scope, and (c) actual APR threshold values were data-derived. No architectural violations exist in the implementation.

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | USDJPY diagnostic exists with verdict backed by data | VERIFIED | `docs/plans/2026-06-14-phase-126-usdjpy-diagnostic.md` has all 4 required sections; verdict = ZONE GEOMETRY, avg_zone_atr_ratio 0.788x vs 1.41-1.43x for EURUSD/USDCHF |
| 2 | Zone width gate in frame_trade() after _resolve_zone_bounds() for all zone source paths | VERIFIED | `trade_framer.py:1059,1068` — `zone_too_narrow:` rejection in frame_trade(); _resolve_zone_bounds() body unchanged |
| 3 | Stop distance floor gate present | VERIFIED | `trade_framer.py:1101` — `stop_too_close:` gate present |
| 4 | Config service wiring: set_config_service + _min_zone_width_atr | VERIFIED | `trade_framer.py:68,166` — both functions present; wired at `services/intelligence_pipeline.py:476` |
| 5 | APR migration 134 with per-asset-class seeds and provenance | VERIFIED | File exists; contains `feature.zone_engine.min_zone_width_atr.{equity,fx,futures}` + `min_stop_distance_atr.*`; "noise band analysis" (4 hits) and "Absolute floor" (4 hits) provenance strings present |
| 6 | Zone width gate unit tests | VERIFIED | `tests/unit/intelligence/test_zone_width_gate.py` exists; 29 occurrences of `zone_too_narrow` / `def test_` |
| 7 | _I7_I6_EXEMPT frozenset deleted with zero remaining references | VERIFIED | `grep -rn "_I7_I6_EXEMPT" src/ tests/` returns empty |
| 8 | requires_i6_confluence fully removed from all plugins and validate_tier() | VERIFIED | `grep -rn "requires_i6_confluence" src/ tests/` returns empty |
| 9 | Time-specific plugin verdicts in docstrings | VERIFIED | session_extremes_setup.py: SCOPE-MISMATCH; orb15.py: CORRECT-RARE; orb30.py: CORRECT-RARE — all at line 3/7/11 respectively |
| 10 | MeanReversion and FVGFill dispositions applied | VERIFIED | mean_reversion.py: `shadow_only = True` (line 50); fvg_fill.py: `shadow_only = True` (line 85); both with rationale strings |
| 11 | Pipeline annotation: _annotate_signal() in signal_processor.py | VERIFIED | `signal_processor.py:73` — `def _annotate_signal`; `_SURFACED_ECL_FIELDS` at line 65; wired at line 347 (before gates, after pre_quality_confidence) |
| 12 | zone_friction_score formalized in tier sub-model (SMCContext) | VERIFIED | `schemas.py:821` — `zone_friction_score: float | None = None` on SMCContext |
| 13 | capture_signal_features() stripped from all plugin bodies and deprecated | VERIFIED | `grep "capture_signal_features" src/intelligence/trading/` returns only `signal_schema.py` changelog comment; `confidence_utils.py:180` has DEPRECATED comment |
| 14 | SIGNAL_SCHEMA_VERSION = "v4" with changelog | VERIFIED | `signal_schema.py:21` — `SIGNAL_SCHEMA_VERSION: str = "v4"`; changelog at lines 17-18 |
| 15 | Pipeline annotation unit tests | VERIFIED | `tests/unit/intelligence/test_pipeline_annotation.py` exists with 12 test functions |
| 16 | IC league table + detection verifiability audit script | VERIFIED | `production/scripts/signal_quality_audit.py` exists; 6 occurrences of "bootstrap"; results doc has IC table, Layer 2 table, Summary, Dispositions Applied sections |
| 17 | Anti-signal plugins demoted shadow_only=True; none removed from TIER_I7 | VERIFIED | 5 new shadow_only demotions (CHoCHReversal, LiquiditySweepReclaim, SupplyDemandSetup, TrendFollowing, FVGFill); TIER_I7 membership count unchanged |
| 18 | REQUIREMENTS.md SIGNAL-QUALITY-01 accurately describes the implementation | FAILED | Requirement text says gate in `_resolve_zone_bounds()` returning `no_signal()`; actual implementation uses `frame_trade()` returning `_reject_frame("zone_too_narrow:...")` per D-01. APR key suffixes and threshold values also differ. |
| 19 | REQUIREMENTS.md SIGNAL-QUALITY-02 accurately describes the implementation | FAILED | Requirement text demands `requires_i6_confluence=True` and `capture_signal_features()` calls — both intentionally removed in P126-06. Frozenset name wrong (`_CONFLUENCE_EXEMPT_PLUGINS` vs actual `_I7_I6_EXEMPT`). |
| 20 | stopped_at_entry < 15% on 10K-signal replay verified | FAILED | Explicitly deferred to Phase 127 replay. signal_ledger has no outcome data for measurement. |

**Score:** 17/20 truths verified (3 gaps — all REQUIREMENTS.md staleness, no code defects)

---

### Required Artifacts

| Artifact | Status | Notes |
|----------|--------|-------|
| `docs/plans/2026-06-14-phase-126-usdjpy-diagnostic.md` | VERIFIED | 4 required sections present |
| `src/intelligence/trading/trade_framer.py` | VERIFIED | zone_too_narrow + stop_too_close + set_config_service + _min_zone_width_atr all present |
| `production/migrations/134_phase126_apr_seeds.sql` | VERIFIED | 8 APR keys; noise band analysis + Absolute floor provenance present |
| `tests/unit/intelligence/test_zone_width_gate.py` | VERIFIED | 29 zone_too_narrow references |
| `src/intelligence/register_plugins.py` | VERIFIED | _I7_I6_EXEMPT deleted; TIER_I7 membership unchanged; all 8 formerly-exempt plugins still registered |
| `src/intelligence/trading/mean_reversion.py` | VERIFIED | shadow_only=True + rationale |
| `src/intelligence/trading/fvg_fill.py` | VERIFIED | shadow_only=True + rationale |
| `tests/unit/intelligence/test_orb_plugins.py` | VERIFIED | exists (created in P126-02) |
| `src/intelligence/pipeline/signal_processor.py` | VERIFIED | _annotate_signal + _SURFACED_ECL_FIELDS + wired at line 347 |
| `src/intelligence/schemas.py` | VERIFIED | zone_friction_score on SMCContext at line 821 |
| `src/intelligence/trading/signal_schema.py` | VERIFIED | SIGNAL_SCHEMA_VERSION="v4" + changelog |
| `src/intelligence/trading/confidence_utils.py` | VERIFIED | DEPRECATED comment at line 180 |
| `tests/unit/intelligence/test_pipeline_annotation.py` | VERIFIED | 12 test functions |
| `production/scripts/signal_quality_audit.py` | VERIFIED | exists; bootstrap present (6 hits) |
| `docs/plans/2026-06-14-phase-126-signal-quality-audit-results.md` | VERIFIED | 4 required section headers present |
| `.planning/REQUIREMENTS.md` | FAILED | SIGNAL-QUALITY-01/02 text stale; both marked Pending in traceability; text inconsistent with actual implementation |

---

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| frame_trade() | zone_too_narrow rejection | After `_resolve_zone_bounds()`, before validate_stop | WIRED — lines 1045, 1048, 1059/1068 |
| trade_framer._min_zone_width_atr() | config_state APR keys | `_cfg("feature.zone_engine.min_zone_width_atr.{asset_class}")` | WIRED — line 172 |
| services/intelligence_pipeline.py | trade_framer.set_config_service | Line 476, same config_service as zone_engine | WIRED |
| signal_processor.process() | _annotate_signal() | Line 347 — after pre_quality_confidence, before gates | WIRED |
| SMCContext.zone_friction_score | flat_features | Tier sub-model field; build_flat_features iterates sub-models | WIRED |
| audit verdicts | plugin shadow_only=True | 5 new demotions applied in source files | WIRED |

---

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| SIGNAL-QUALITY-01 | PARTIAL | Code implementation correct (zone width gate in frame_trade, APR seeds applied, data-derived thresholds). REQUIREMENTS.md text is stale — wrong gate location, wrong key names, wrong seed values. stopped_at_entry measurement deferred to Phase 127. |
| SIGNAL-QUALITY-02 | PARTIAL | Code implementation correct (8 plugins compliant, _I7_I6_EXEMPT deleted, pipeline annotation, anti-signal demotions applied). REQUIREMENTS.md text demands per-plugin capture_signal_features() calls that were intentionally removed. Wrong frozenset name. |

---

### Anti-Patterns Found

None in code. No TODO/FIXME/placeholder patterns in the key implementation files. No empty implementations. The shadow_only=True dispositions are intentional and documented.

---

### Gaps Summary

All three gaps are REQUIREMENTS.md staleness, not code defects. The implementation is architecturally correct and follows the PLAN must_haves and design decisions (D-01 through D-18).

**Gap 1 — SIGNAL-QUALITY-01 text:** Written before D-01 was finalized (gate in frame_trade, not _resolve_zone_bounds). Values in the requirements text (equity_etf:0.5, forex:0.25, futures:0.35) are from an earlier design iteration — the actual data-derived values (equity:1.5, fx:1.0, futures:1.5) are in migration 134. This creates a false impression that Phase 126 is incomplete when the code is correct.

**Gap 2 — SIGNAL-QUALITY-02 text:** Written before Wave 3 pipeline annotation layer was added to Phase 126 scope (see CONTEXT.md NOTE ON WAVE 3 INTERACTION). The requirement text demands `requires_i6_confluence=True` and per-plugin `capture_signal_features()` calls — both intentionally removed as part of the architectural improvement. The frozenset name is also wrong (`_CONFLUENCE_EXEMPT_PLUGINS` vs actual `_I7_I6_EXEMPT`).

**Gap 3 — stopped_at_entry measurement:** Phase 126 code enforces zone_width >= ATR threshold prospectively. Historical signal_ledger has null shadow_outcome. The < 15% rate can only be measured after Phase 127 clean replay generates outcomes — which is correct sequencing. The requirement mixes a Phase 126 gate implementation with a Phase 127 measurement.

**Recommendation:** Update REQUIREMENTS.md to close SIGNAL-QUALITY-01 and SIGNAL-QUALITY-02 with accurate text before running Phase 127. This is a documentation fix, not a code fix.

---

_Verified: 2026-06-15_
_Verifier: Claude (gsd-verifier)_
