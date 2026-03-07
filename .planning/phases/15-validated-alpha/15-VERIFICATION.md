---
phase: 15-validated-alpha
verified: 2026-03-07T14:00:00Z
status: gaps_found
score: 2/5 success criteria verified
re_verification: false
gaps:
  - truth: "Derivative Oscillator has passed the ALPHA-01 validation gate before being wired to the live pipeline"
    status: failed
    reason: "Gate returned FAIL with n_total_bars=0 (no live data — plugin not yet registered so intelligence_features has no i2.deriv_osc_cross_bullish rows). Plugin exists and is tested but is NOT in TIER_I2. Both the gate and the live wiring are deferred."
    artifacts:
      - path: "src/intelligence/composites/derivative_oscillator.py"
        issue: "Implemented correctly but not registered in TIER_I2. cmp_DerivativeOscillator absent from register_plugins.py TIER_I2 list."
      - path: "docs/validation/2026-03-07-cmp_DerivativeOscillator-deriv_osc_cross_bullish.json"
        issue: "Verdict: FAIL. n_total_bars=0. Gate cannot pass without live data from a registered plugin."
    missing:
      - "Plugin must accumulate live data (requires registering to TIER_I2 first, then re-running validate_alpha.py --promote after 30+ bars exist)"
      - "This is a chicken-and-egg problem: the gate requires data, but data requires registration, and the plan forbids manual registration without passing the gate. Needs a resolution strategy."

  - truth: "CandlestickPatternsPlugin (I5) and CandlestickPatternSetupPlugin (I7) include all 10 new Tier 1 patterns each having passed the ALPHA-01 gate"
    status: failed
    reason: "Only 2 of 9 new patterns had validate_alpha.py runs (three_white_soldiers, three_black_crows). Both returned FAIL (n=0). No pattern has passed the gate. No new pattern was promoted to I7 (candlestick_pattern_setup.py is unchanged). 8 patterns were not even validated."
    artifacts:
      - path: "docs/validation/2026-03-07-patt_CandlestickPatterns-three_white_soldiers.json"
        issue: "Verdict: FAIL. n_total_bars=0."
      - path: "docs/validation/2026-03-07-patt_CandlestickPatterns-three_black_crows.json"
        issue: "Verdict: FAIL. n_total_bars=0."
    missing:
      - "7 validation runs not executed: morning_star, evening_star, three_inside_up, three_inside_down, harami_cross, dark_cloud_cover, piercing_line"
      - "All 9 new patterns blocked from ALPHA-01 gate pass due to empty intelligence_features (same chicken-and-egg: patt_CandlestickPatterns already in TIER_I5, so new fields will appear in live data as pipeline runs, then gate can be re-run)"
      - "I7 CandlestickPatternSetupPlugin has zero new pattern reads — correct isolation until gates pass, but this means the SC is unmet"

  - truth: "AC Oscillator validated via ALPHA-01 before live wiring"
    status: failed
    reason: "AC Oscillator was registered in TIER_I1 (commit ad9af58) BEFORE the validation gate was attempted. The validation report shows FAIL (n=0). The plugin fired production data before passing any statistical validation, violating the phase goal 'live in production after each passes historical validation'."
    artifacts:
      - path: "src/intelligence/register_plugins.py"
        issue: "ac_osc_plugin.name is in TIER_I1 (24 total). Plugin was promoted despite gate FAIL."
      - path: "docs/validation/2026-03-07-ind_ACOscillator-ac.json"
        issue: "Verdict: FAIL. n_total_bars=0. Promoted=false in report. But register_plugins.py was manually patched in commit ad9af58 without gate passing."
    missing:
      - "Either: (a) the TIER_I1 registration should be reverted until the gate passes, or (b) a gate exception policy needs to be formally declared for data-absence vs signal-quality failures"
      - "The plan itself allows deferral, but does not permit pre-emptive registration before gate pass"

  - truth: "MACD hist_accel validated via ALPHA-01 before live promotion"
    status: partial
    reason: "MACDEventsPlugin is already registered in TIER_I2 — the new fields (macd_hist_accel, macd_hist_contracting) are automatically live in the pipeline. Validation report shows FAIL (n=0) because the fields were just added and have no data yet. This is a borderline case: the plugin was already live, and the new fields are additive. The gate cannot logically precede live data for fields on an already-registered plugin."
    artifacts:
      - path: "docs/validation/2026-03-07-evt_MACDEvents-macd_hist_accel.json"
        issue: "Verdict: FAIL. n_total_bars=0. Fields newly added — data will self-populate as pipeline runs."
    missing:
      - "Gate must be re-run after 30+ days of pipeline data accumulates. No action needed to unblock live pipeline (fields are already computing correctly)."
---

# Phase 15: Validated Alpha Verification Report

**Phase Goal:** Four new alpha sources (Derivative Oscillator, 10 Candlestick Tier 1 patterns, MACD histogram acceleration, AC Oscillator) are live in production after each passes historical validation — no unvalidated signals fire

**Verified:** 2026-03-07T14:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| #  | Truth                                                                  | Status      | Evidence                                                              |
|----|------------------------------------------------------------------------|-------------|-----------------------------------------------------------------------|
| 1  | Validation script exists (validate_alpha.py) with gate logic           | VERIFIED    | 790-line script, 8 tests pass, Pearson r>0/p<0.05/N>=30 gates correct |
| 2  | Derivative Oscillator passed gate before being wired to live pipeline  | FAILED      | Gate FAIL (n=0), NOT in TIER_I2                                       |
| 3  | 10 Candlestick Tier 1 patterns: each passed gate, wired to I5 and I7  | FAILED      | 2/9 runs executed (both FAIL n=0), 0 promoted to I7                   |
| 4  | MACDEventsPlugin emits macd_hist_accel/contracting, validated          | PARTIAL     | Fields live (already-registered plugin), gate FAIL n=0 (data pending) |
| 5  | AC Oscillator validated before live wiring                             | FAILED      | Wired to TIER_I1 in commit ad9af58 BEFORE gate pass (gate: FAIL n=0)  |

**Score: 2/5 success criteria verified** (SC1 fully, SC4 partially — live production but gate not yet cleared)

### Required Artifacts

| Artifact                                                       | Expected                                        | Status      | Details                                                        |
|----------------------------------------------------------------|-------------------------------------------------|-------------|----------------------------------------------------------------|
| `production/scripts/validate_alpha.py`                         | CLI gate with Pearson+ADF+FPR+--promote         | VERIFIED    | 790 lines, all features implemented, 8 tests pass             |
| `tests/unit/scripts/test_validate_alpha.py`                    | 8 unit tests covering all gate logic            | VERIFIED    | 8 tests, 501 lines, all pass                                   |
| `docs/validation/.gitkeep`                                     | Audit trail directory git-tracked               | VERIFIED    | Directory exists, 5 JSON reports present                       |
| `src/intelligence/composites/derivative_oscillator.py`         | DerivativeOscillatorPlugin + plugin singleton   | VERIFIED    | 103 lines, correct EMA5→EMA3→SMA9 formula, 8 tests pass       |
| `tests/unit/intelligence/composites/test_derivative_oscillator.py` | 8 unit tests                               | VERIFIED    | 144 lines, 8 tests pass                                        |
| `src/intelligence/patterns/candlestick_patterns.py`            | 18-output plugin (9 existing + 9 new), min_lookback=3 | VERIFIED | 307 lines, 18 outputs, min_lookback=3, 18 tests pass    |
| `tests/unit/intelligence/test_candlestick_tier1.py`            | 12 tests for new patterns                       | VERIFIED    | 322 lines, 18 tests pass (6 extra added beyond plan)          |
| `src/intelligence/composites/macd_events.py`                   | MACDEventsPlugin + 2 new fields (8 total)       | VERIFIED    | 8 outputs including macd_hist_accel, macd_hist_contracting     |
| `src/intelligence/indicators/ac_oscillator.py`                 | ACOscillatorPlugin + plugin singleton           | VERIFIED    | 51 lines, formula correct, 8 tests pass                        |
| `tests/unit/intelligence/test_ac_oscillator.py`                | 8 unit tests                                    | VERIFIED    | 8 tests pass, formula correctness verified to 1e-6             |

### Key Link Verification

| From                            | To                              | Via                                   | Status      | Details                                                              |
|---------------------------------|---------------------------------|---------------------------------------|-------------|----------------------------------------------------------------------|
| validate_alpha.py gate logic    | register_plugins.py             | --promote sentinel patch (3 points)   | VERIFIED    | Sentinel fallback logic present; backup/restore on failure           |
| validate_alpha.py (candlestick) | candlestick_pattern_setup.py    | secondary_patch on --promote          | VERIFIED    | _patch_candlestick_setup() implemented; not yet invoked (no passes) |
| validate_alpha.py data check    | historical_backfill.py          | subprocess.run --replay-only line 593 | VERIFIED    | Wired and tested (test_auto_backfill_triggered passes)              |
| derivative_oscillator.py        | TIER_I2 in register_plugins.py  | import + register_pattern + tier list | NOT WIRED   | cmp_DerivativeOscillator absent from TIER_I2; plugin not live       |
| ac_oscillator.py                | TIER_I1 in register_plugins.py  | import + register_indicator + tier    | WIRED*      | Live in TIER_I1 (commit ad9af58) but wired BEFORE gate pass         |
| new candlestick fields          | candlestick_pattern_setup.py    | explicit named reads (whitelist)      | ISOLATED    | No new fields in I7 reads — correct until gates pass                |
| macd_hist_accel                 | live pipeline (TIER_I2)         | already-registered evt_MACDEvents     | WIRED       | Fields live as additive extension to existing registered plugin      |

*ac_oscillator TIER_I1 wiring predates gate pass — violates plan constraint.

### Requirements Coverage

| Requirement | Source Plan | Description                                      | Status   | Evidence                                                        |
|-------------|-------------|--------------------------------------------------|----------|-----------------------------------------------------------------|
| ALPHA-01    | 15-01       | Validation gate script with Pearson+ADF+promote  | SATISFIED | validate_alpha.py implemented, tested, correct                  |
| ALPHA-02    | 15-02       | DerivativeOscillator implemented + validated     | PARTIAL   | Plugin implemented+tested; gate FAIL; not in TIER_I2            |
| ALPHA-03    | 15-03       | Candlestick Tier 1 x9 implemented + validated    | PARTIAL   | 9 patterns implemented+tested; 2/9 gates run (both FAIL); 0 promoted to I7 |
| ALPHA-04    | 15-04       | MACD accel fields added + validated              | PARTIAL   | Fields live (existing plugin); gate FAIL n=0 (data pending)     |
| ALPHA-05    | 15-05       | AC Oscillator implemented + validated            | PARTIAL   | Plugin live in TIER_I1; gate FAIL; violates "validate before wire" |

### Anti-Patterns Found

| File                                   | Pattern                                      | Severity | Impact                                                              |
|----------------------------------------|----------------------------------------------|----------|---------------------------------------------------------------------|
| `src/intelligence/register_plugins.py` | ac_osc_plugin registered before gate pass    | BLOCKER  | Violates phase contract "no unvalidated signals fire"              |
| All validation JSON reports            | All verdicts: FAIL (n=0)                     | BLOCKER  | No alpha source has cleared the statistical validation gate        |
| `src/intelligence/composites/derivative_oscillator.py` | Plugin not in TIER_I2      | WARNING  | Chicken-and-egg: gate needs data, data needs registration          |

### Human Verification Required

None. The gaps are programmatically verifiable and clearly documented.

---

## Gaps Summary

### Root Cause: Data-Chicken-Egg Problem

All validation gate failures share the same root cause: `intelligence_features` has zero rows for the newly-added fields because the validation gate is designed to run on accumulated historical data. For a brand-new plugin that has never been registered, there can be no historical data.

The plans acknowledge this and allow "deferral" as an acceptable outcome. However, the **phase goal as stated** requires that gates pass before live wiring. Three of the four alpha sources ended the phase in a state that does not satisfy the success criteria.

### Gap 1: DerivativeOscillator Not Live (Correctly Blocked)

The DerivativeOscillatorPlugin exists and is tested but is not in TIER_I2. The gate correctly blocked promotion due to no data. This creates a deadlock: the plugin cannot accumulate data without being registered, but cannot be registered without passing the gate. Resolution: the team needs to either (a) accept that brand-new I2 composites need a bootstrap period (register first, validate after N days), or (b) run the gate using historical OHLCV replay. This deadlock is not resolved by this phase.

### Gap 2: Candlestick Patterns Not Promoted to I7

Nine new patterns are detected in I5 but zero have been promoted to I7 via `--promote`. The isolation is correct and working (CandlestickPatternSetupPlugin has no reads for any new field). However, the Success Criterion requires that they "include all 10 new Tier 1 patterns" in I7 — this is not met. Seven patterns had no validation run at all; two were run with FAIL results. The gate re-runs must happen after live data accumulates for `patt_CandlestickPatterns` (which IS registered in TIER_I5, so fields will self-populate in `intelligence_features.i5` as the pipeline runs).

### Gap 3: AC Oscillator Pre-emptively Registered (Violates Plan Constraint)

The plan explicitly states: "Do NOT manually patch register_plugins.py — only validate_alpha.py --promote may do this." Commit `ad9af58` manually registered `ac_osc_plugin` in TIER_I1 before the validation gate passed. The 15-05 SUMMARY notes this was a deliberate decision ("TIER_I1 promotion despite gate FAIL — data availability issue not signal quality"). This decision bypasses the protection that the gate is designed to provide. Whether this is acceptable requires a policy decision.

### Gap 4: MACD Accel Gate Pending (Acceptable Path Forward)

The `macd_hist_accel` and `macd_hist_contracting` fields are live on an already-registered plugin (`evt_MACDEvents` is in TIER_I2). The gate cannot logically block a field on an already-live plugin — the only lever is whether the I7 setups read those fields (they don't yet). This is the most defensible of the four gaps: the pipeline is computing the values, and the gate will be re-runnable once 30+ days of data accumulates.

---

### What "Live in Production" Actually Means for Phase 15

| Alpha Source           | Computes in Pipeline? | In Tier List? | Gate Passed? | I7 Reads Field? | Phase Goal Met? |
|------------------------|-----------------------|---------------|--------------|-----------------|-----------------|
| Derivative Oscillator  | No                    | No            | No (n=0)     | No              | No              |
| Candlestick Tier 1 x9  | Yes (I5 only)         | Yes (I5)      | No (n=0)     | No              | No              |
| MACD Accel             | Yes (TIER_I2)         | Yes (I2)      | No (n=0)     | No (pending)    | Partial         |
| AC Oscillator          | Yes                   | Yes (I1)      | No (n=0)     | N/A (I1 only)   | No (order wrong)|

---

_Verified: 2026-03-07T14:00:00Z_
_Verifier: Claude (gsd-verifier)_
