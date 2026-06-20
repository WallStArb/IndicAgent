---
phase: 126-signal-universe-hardening
verified: 2026-06-15T12:00:00Z
status: passed
score: 20/20 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 17/20
  gaps_closed:
    - "REQUIREMENTS.md SIGNAL-QUALITY-01 text now correctly describes gate in frame_trade() / _reject_frame, APR key names feature.zone_engine.min_zone_width_atr.{equity,fx,futures} = 1.5/1.0/1.5, and stopped_at_entry measurement deferred to Phase 127 REPLAY-01"
    - "REQUIREMENTS.md SIGNAL-QUALITY-02 text now correctly describes _I7_I6_EXEMPT deleted, pipeline annotation via signal_processor._annotate_signal(), capture_signal_features() DEPRECATED, SIGNAL_SCHEMA_VERSION = v4"
    - "stopped_at_entry < 15% measurement now explicitly documented as Phase 127 REPLAY-01 deliverable in SIGNAL-QUALITY-01 requirement text"
  gaps_remaining: []
  regressions: []
---

# Phase 126: Signal Universe Hardening — Verification Report

**Phase Goal:** Harden the signal universe by eliminating the four root crimes — sub-ATR zones (stop at entry), missing I6 confluence wiring, zero-signal time-specific plugins, and a biased heterogeneous training corpus — so Phase 127 clean replay runs on a defensible signal set.
**Verified:** 2026-06-15
**Status:** passed
**Re-verification:** Yes — after gap closure (Plan 126-07)

## Summary

Initial verification (same session) found 17/20 truths verified. All 3 gaps were REQUIREMENTS.md text inconsistencies — no code defects. Plan 126-07 corrected REQUIREMENTS.md SIGNAL-QUALITY-01 and SIGNAL-QUALITY-02 text and marked both Complete. Re-verification confirms all 20 truths now pass.

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | USDJPY diagnostic exists with verdict backed by data | VERIFIED | `docs/plans/2026-06-14-phase-126-usdjpy-diagnostic.md` has all 4 required sections; verdict = ZONE GEOMETRY, avg_zone_atr_ratio 0.788x vs 1.41-1.43x for EURUSD/USDCHF |
| 2 | Zone width gate in frame_trade() after _resolve_zone_bounds() for all zone source paths | VERIFIED | `trade_framer.py:1059,1068-1070` — `zone_too_narrow:` rejection in frame_trade(); _resolve_zone_bounds() body unchanged |
| 3 | Stop distance floor gate present | VERIFIED | `trade_framer.py:1101` — `stop_too_close:` gate present |
| 4 | Config service wiring: set_config_service + _min_zone_width_atr | VERIFIED | `trade_framer.py:68,166-176` — both functions present; wired at `services/intelligence_pipeline.py:476` |
| 5 | APR migration 134 with per-asset-class seeds and provenance | VERIFIED | File exists; seeds equity:1.5 / fx:1.0 / futures:1.5 with "noise band analysis" provenance; `min_stop_distance_atr.*` also present |
| 6 | Zone width gate unit tests | VERIFIED | `tests/unit/intelligence/test_zone_width_gate.py` exists; 12 test functions |
| 7 | _I7_I6_EXEMPT frozenset deleted with zero remaining references | VERIFIED | `grep -rn "_I7_I6_EXEMPT" src/ tests/` returns empty |
| 8 | requires_i6_confluence fully removed from all plugins and validate_tier() | VERIFIED | `grep -rn "requires_i6_confluence" src/ tests/` returns empty |
| 9 | Time-specific plugin verdicts in docstrings | VERIFIED | session_extremes_setup.py: SCOPE-MISMATCH; orb15.py: CORRECT-RARE; orb30.py: CORRECT-RARE |
| 10 | MeanReversion and FVGFill dispositions applied | VERIFIED | mean_reversion.py: `shadow_only = True` (line 50) with dual-gate rationale; fvg_fill.py: `shadow_only = True` (line 85) |
| 11 | Pipeline annotation: _annotate_signal() in signal_processor.py | VERIFIED | `signal_processor.py:73` — `def _annotate_signal`; `_SURFACED_ECL_FIELDS` at line 65; wired at line 347 |
| 12 | zone_friction_score formalized in tier sub-model (SMCContext) | VERIFIED | `schemas.py:821` — `zone_friction_score: float | None = None` on SMCContext |
| 13 | capture_signal_features() stripped from all plugin bodies and deprecated | VERIFIED | `confidence_utils.py:180` has DEPRECATED comment; only signal_schema.py changelog comment references it in trading/ |
| 14 | SIGNAL_SCHEMA_VERSION = "v4" with changelog | VERIFIED | `signal_schema.py:21` — `SIGNAL_SCHEMA_VERSION: str = "v4"` |
| 15 | Pipeline annotation unit tests | VERIFIED | `tests/unit/intelligence/test_pipeline_annotation.py` exists with 12 test functions |
| 16 | IC league table + detection verifiability audit script | VERIFIED | `production/scripts/signal_quality_audit.py` exists; results doc has IC table, Layer 2 table, Summary, Dispositions Applied sections |
| 17 | Anti-signal plugins demoted shadow_only=True; none removed from TIER_I7 | VERIFIED | 5 new shadow_only demotions (CHoCHReversal, LiquiditySweepReclaim, SupplyDemandSetup, TrendFollowing, FVGFill); TIER_I7 membership count unchanged |
| 18 | REQUIREMENTS.md SIGNAL-QUALITY-01 accurately describes the implementation | VERIFIED | Text now correctly describes: gate in frame_trade() / _reject_frame; APR keys feature.zone_engine.min_zone_width_atr.{equity,fx,futures} = 1.5/1.0/1.5; stopped_at_entry measurement explicitly deferred to Phase 127 REPLAY-01; marked [x] Complete in traceability table |
| 19 | REQUIREMENTS.md SIGNAL-QUALITY-02 accurately describes the implementation | VERIFIED | Text now correctly describes: _I7_I6_EXEMPT deleted from register_plugins.py; annotation moved to signal_processor._annotate_signal() (Wave 3); per-plugin requires_i6_confluence and capture_signal_features() removed; SIGNAL_SCHEMA_VERSION bumped to v4; all 8 formerly-exempt plugins remain in TIER_I7; marked [x] Complete in traceability table |
| 20 | stopped_at_entry < 15% on 10K-signal replay deferred correctly | VERIFIED | SIGNAL-QUALITY-01 requirement text now explicitly states: "stopped_at_entry rate < 15% measurement deferred to Phase 127 (REPLAY-01) — gate enforced prospectively in Phase 126; historical signal_ledger lacks outcome data"; no false claim that this was measured in Phase 126 |

**Score:** 20/20 truths verified

---

### Required Artifacts

| Artifact | Status | Notes |
|----------|--------|-------|
| `docs/plans/2026-06-14-phase-126-usdjpy-diagnostic.md` | VERIFIED | 4 required sections present |
| `src/intelligence/trading/trade_framer.py` | VERIFIED | zone_too_narrow + stop_too_close + set_config_service + _min_zone_width_atr all present |
| `production/migrations/134_phase126_apr_seeds.sql` | VERIFIED | 8 APR keys; noise band analysis provenance; equity:1.5 / fx:1.0 / futures:1.5 |
| `tests/unit/intelligence/test_zone_width_gate.py` | VERIFIED | 12 test functions |
| `src/intelligence/register_plugins.py` | VERIFIED | _I7_I6_EXEMPT deleted; TIER_I7 membership unchanged; all 8 formerly-exempt plugins still registered |
| `src/intelligence/trading/mean_reversion.py` | VERIFIED | shadow_only=True + dual-gate rationale |
| `src/intelligence/trading/fvg_fill.py` | VERIFIED | shadow_only=True + rationale |
| `tests/unit/intelligence/test_orb_plugins.py` | VERIFIED | exists |
| `src/intelligence/pipeline/signal_processor.py` | VERIFIED | _annotate_signal + _SURFACED_ECL_FIELDS + wired at line 347 |
| `src/intelligence/schemas.py` | VERIFIED | zone_friction_score on SMCContext at line 821 |
| `src/intelligence/trading/signal_schema.py` | VERIFIED | SIGNAL_SCHEMA_VERSION="v4" + changelog |
| `src/intelligence/trading/confidence_utils.py` | VERIFIED | DEPRECATED comment at line 180 |
| `tests/unit/intelligence/test_pipeline_annotation.py` | VERIFIED | 12 test functions |
| `production/scripts/signal_quality_audit.py` | VERIFIED | exists; bootstrap CI present |
| `docs/plans/2026-06-14-phase-126-signal-quality-audit-results.md` | VERIFIED | 4 required section headers present |
| `.planning/REQUIREMENTS.md` | VERIFIED | SIGNAL-QUALITY-01/02 text accurate; both marked [x] Complete in body and traceability table; last-updated note records Phase 126 gap closure |

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
| SIGNAL-QUALITY-01 | SATISFIED | Code correct + REQUIREMENTS.md text accurate + traceability marked Complete |
| SIGNAL-QUALITY-02 | SATISFIED | Code correct + REQUIREMENTS.md text accurate + traceability marked Complete |

---

### Anti-Patterns Found

None. No TODO/FIXME/placeholder patterns in key implementation files. No empty implementations. Shadow_only=True dispositions are intentional and documented with rationale strings.

---

### Re-verification Summary

All three gaps from the initial verification are closed:

**Gap 1 (CLOSED) — SIGNAL-QUALITY-01 stale text:** REQUIREMENTS.md now correctly describes the gate location (frame_trade / _reject_frame), APR key names (feature.zone_engine.min_zone_width_atr.{equity,fx,futures}), data-derived threshold values (1.5/1.0/1.5), and explicitly defers stopped_at_entry measurement to Phase 127 REPLAY-01.

**Gap 2 (CLOSED) — SIGNAL-QUALITY-02 stale text:** REQUIREMENTS.md now correctly describes _I7_I6_EXEMPT as the deleted frozenset (not _CONFLUENCE_EXEMPT_PLUGINS), pipeline annotation via signal_processor._annotate_signal() as the replacement mechanism, capture_signal_features() as DEPRECATED (not deleted), and SIGNAL_SCHEMA_VERSION bumped to v4.

**Gap 3 (CLOSED) — stopped_at_entry measurement deferred:** SIGNAL-QUALITY-01 requirement text now explicitly states the < 15% rate measurement is a Phase 127 REPLAY-01 deliverable. The Phase 126 gate enforces zone_width >= ATR threshold prospectively; historical outcome measurement is correctly sequenced after clean replay.

No regressions found in the 17 originally-verified truths.

---

_Verified: 2026-06-15_
_Verifier: Claude (gsd-verifier)_
