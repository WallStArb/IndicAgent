---
phase: 28-dashboard-completion
verified: 2026-03-12T00:00:00Z
status: human_needed
score: 5/5 must-haves verified
human_verification:
  - test: "Open a drill panel on a live symbol; hover any tier label (I1, I3, I4, I5, SMC, I6, I7)"
    expected: "Tooltip appears with the tier's description text (dotted underline trigger)"
    why_human: "Tooltip rendering requires live browser interaction"
  - test: "Open drill panel on a symbol with recent signals; observe Signal Scorecard section"
    expected: "Shows winner (filled dot), suppressed signals (amber x + label), direction arrows, confidence percentages, and summary header (N fired · M regime-gated · winner: XYZ)"
    why_human: "Requires live intelligence_i7 SSE stream events flowing to dashboard"
  - test: "Open drill panel on fresh browser load (no SSE history yet)"
    expected: "Signal history list shows signals from DB immediately — not empty — with summary line showing resolved count, win rate, avg pnl_r"
    why_human: "Requires DB with signal_ledger data; tests the DB fetch on mount path"
  - test: "Observe I4 Context section in drill panel"
    expected: "GARCH regime, GARCH sigma, GARCH ratio, GARCH shock, Kalman slope, Kalman pos, K-uncertainty rows appear when non-null; GARCH regime row amber when pipeline classifies it as high (2)"
    why_human: "Requires live GARCH/Kalman data flowing through I4 pipeline"
  - test: "Observe Smart Money section in drill panel"
    expected: "BSL touches, BSL sig, SSL touches, SSL sig, In premium (yes/no), Equilibrium rows appear when non-null"
    why_human: "Requires live SMC data with these fields populated"
---

# Phase 28: Dashboard Completion Verification Report

**Phase Goal:** The dashboard fully surfaces the intelligence pipeline — Signal Scorecard with all ranked signals, drill panel signal history from DB, GARCH/Kalman I4 fields, SMC detail fields, and tier tooltips.
**Verified:** 2026-03-12
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Drill panel Signal Scorecard shows all ranked signals for the current bar with confidence, direction, composite rank, regime eligibility, and suppression reason | VERIFIED | `signal-scorecard.tsx` renders winner dot, direction arrow, confidence%, eligibility check/x; wired at `drill-panel.tsx:434` via `data.scorecardByTf?.[timeframe]` |
| 2 | Suppressed signals display human-readable suppression labels (`< 60% conf` / `< 5 bars` / `wrong regime`) | VERIFIED | `SUPPRESSION_LABELS` map at `signal-scorecard.tsx:6-10`; `suppressionLabel()` function at line 12 |
| 3 | `GET /api/signals/recent` returns paginated recent signals from signal_ledger; drill panel merges with live SSE history deduplicated by signal_id | VERIFIED | Route at `signals.py:117` with LEFT JOIN setup_performance; `drill-panel.tsx:327` fetches on mount; `mergedSignalsHistory` useMemo deduplicates by signal_id with SSE wins |
| 4 | Drill panel shows GARCH/Kalman I4 fields and SMC detail fields (BSL/SSL dist_atr/touches/significance, premium/discount fields) | VERIFIED | All 6 GARCH/Kalman fields in `ContextData` types.ts:110-116; mapped in `use-market-stream.ts:136-141`; rendered in `drill-panel.tsx:502-527`; BSL/SSL touches+significance at lines 600-615; price_in_premium+equilibrium_level at lines 633-637 |
| 5 | Tier labels (I1–I8) show hover tooltips | VERIFIED | `tier-tooltip.tsx` with full TIER_COPY map (all 9 tiers: I1-I8, SMC); wired in drill-panel.tsx to I1, I3, I4, I5, SMC, I6, I7 sections; I2 not present in drill panel (no I2 section exists there); I8 not present (no narrative section in drill panel) — both absences match plan's "if present" qualifier |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/api/routes/sse.py` | intelligence_i7 in stream list; signal_scorecard event name | VERIFIED | `sk_intelligence_i7` imported line 15; appended in stream loop line 119; `known_domains` includes `intelligence_i7` line 137; startswith check at line 145-146 returns `"signal_scorecard"` |
| `tests/unit/test_sse_snapshot_filter.py` | Tests for intelligence_i7 routing | VERIFIED | 16 tests pass including new I7 routing tests |
| `dashboard/src/lib/types.ts` | RankedSignal, SignalScorecardData, scorecardByTf in SymbolData | VERIFIED | `RankedSignal` at line 285; `SignalScorecardData` at line 298; `scorecardByTf` at line 389 |
| `dashboard/src/hooks/use-market-stream.ts` | signal_scorecard handler; scorecardByTf state | VERIFIED | `emptySymbolData` has `scorecardByTf: {}` at line 53; event listener at line 818; updates `scorecardByTf[tf]` at line 842 |
| `dashboard/src/components/signal-scorecard.tsx` | SignalScorecard component with all layout | VERIFIED | Exports `SignalScorecard`; SUPPRESSION_LABELS map; empty state; winner/suppressed rows; summary header |
| `dashboard/src/components/drill-panel.tsx` | All wiring: SignalScorecard, DB fetch, summary, GARCH/Kalman, SMC, TierTooltip | VERIFIED | All 7 items wired and substantive |
| `src/api/routes/signals.py` | GET /api/signals/recent with setup_performance JOIN | VERIFIED | Route at line 117; LEFT JOIN setup_performance; summary aggregate query; setup_win_rate + setup_avg_pnl_r per signal |
| `tests/unit/api_tests/test_signals_routes.py` | Tests for /api/signals/recent | VERIFIED | 14 tests pass including TestGetRecentSignals class |
| `dashboard/src/components/tier-tooltip.tsx` | TierTooltip with TIER_COPY for all 9 tiers | VERIFIED | All 9 entries present (I1, I2, I3, I4, I5, SMC, I6, I7, I8); dotted underline styling |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `sse.py _build_stream_list()` | `stream_keys.intelligence_i7()` | import + loop append | WIRED | `sk_intelligence_i7(env_prefix, contract, tf)` appended after sk_intelligence line 119 |
| `sse.py _event_name_for_stream()` | SSE event type `"signal_scorecard"` | `startswith("intelligence_i7:")` | WIRED | Check at line 145-146; before `intelligence:` check to avoid shadowing |
| `use-market-stream.ts signal_scorecard handler` | `SymbolData.scorecardByTf[tf]` | `setSymbolData` updater | WIRED | `setSymbolData` updates `scorecardByTf[tf]` at line 842 |
| `signal_scorecard payload.data` | `RankedSignal[]` | `JSON.parse(payload.data)` | WIRED | `JSON.parse(String(payload.data \|\| "[]"))` at line 825 |
| `drill-panel.tsx` | `signal-scorecard.tsx SignalScorecard` | `<SignalScorecard data={data.scorecardByTf?.[timeframe]} />` | WIRED | Line 434; optional chain handles undefined gracefully |
| `DrillPanel useEffect` | `GET /api/signals/recent` | fetch on mount, `[symbol, timeframe]` deps | WIRED | Line 327; deps array at line 338 |
| `GET /api/signals/recent` | `signal_ledger LEFT JOIN setup_performance` | `db_manager.fetch()` | WIRED | Main query at signals.py:143-176; `setup_performance` JOIN at line 150 |
| `summary block` | summary line render | `n_resolved, win_rate, avg_pnl_r, n_suppressed` | WIRED | Summary displayed at drill-panel.tsx:395-412 |
| `parseIntelligence context` | drill-panel I4 section | `ContextData.garch_sigma, kalman_slope, etc.` | WIRED | Mapped in use-market-stream.ts:136-141; rendered conditionally in drill-panel.tsx:502-527 |
| `drill-panel.tsx Section labels` | `TierTooltip` | `<TierTooltip tier="XX">label</TierTooltip>` | WIRED | 7 tier sections wired (I1, I3, I4, I5, SMC, I6, I7); I2 and I8 absent from drill panel per plan's "if present" qualifier |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| DASH-01 | 28-01 | SSE subscribes to intelligence_i7 stream, emits signal_scorecard event | SATISFIED | `sse.py` wires stream + event name; 16 tests pass |
| DASH-02 | 28-02, 28-03 | Drill panel Signal Scorecard with all ranked signal fields | SATISFIED | `signal-scorecard.tsx` renders complete scorecard; wired to drill panel |
| DASH-03 | 28-02, 28-03 | Suppressed signals show human-readable labels | SATISFIED | SUPPRESSION_LABELS map in signal-scorecard.tsx; all 3 reason codes mapped |
| DASH-04 | 28-04 | GET /api/signals/recent endpoint | SATISFIED | Route at signals.py:117; 14 unit tests pass |
| DASH-05 | 28-05 | Drill panel loads DB history on open, merges with SSE by signal_id | SATISFIED | useEffect fetch + mergedSignalsHistory dedup in drill-panel.tsx |
| DASH-06 | 28-06 | GARCH/Kalman I4 fields surfaced in drill panel | SATISFIED | 6 fields in ContextData; mapped; conditionally rendered |
| DASH-07 | 28-06 | SMC detail fields: BSL/SSL touches/significance, premium/discount | SATISFIED | All fields rendered in Smart Money section |
| DASH-08 | 28-07 | Tier labels (I1–I8) show hover tooltips | SATISFIED | TierTooltip with TIER_COPY for all 9 tiers; wired to all present tier sections |

### Anti-Patterns Found

No blockers or warnings found. All files scanned — no TODO/FIXME/placeholder comments, no empty implementations, no stub returns.

### Human Verification Required

#### 1. Signal Scorecard Live Rendering

**Test:** Open drill panel on a live symbol after the signal generator has fired at least one bar (requires ~50 min warmup after service restart). Observe the "Signal Scorecard" section.
**Expected:** Shows summary header "N fired · M regime-gated · winner: SetupName"; each ranked signal shows filled/open dot, stripped name, direction arrow, confidence %, and eligibility checkmark or amber suppression label.
**Why human:** Requires live intelligence_i7 SSE stream events; browser DOM rendering cannot be verified statically.

#### 2. Tier Tooltip Interaction

**Test:** Hover over any tier label in the drill panel: I1, I3, I4, I5, Smart Money, I6, I7.
**Expected:** Tooltip popup appears with the tier's description text (e.g., hovering I4 shows "Statistical Context — GARCH volatility, Kalman trend, HMM regime, BOCPD change detection. Adaptive statistical models."). The label has a dotted underline and cursor changes to help.
**Why human:** Tooltip hover interaction requires a browser; Radix UI portal rendering cannot be verified statically.

#### 3. DB Signal History on Fresh Load

**Test:** Open a drill panel on a symbol immediately after a fresh browser load (before any SSE signals arrive). Check the Recent Signals section.
**Expected:** Signals appear immediately from DB (not empty), with the summary line showing resolved count, win rate, avg pnl_r. SSE signals arriving later merge without duplication.
**Why human:** Requires a live database with signal_ledger rows for that symbol; tests the DB-backed seeding path.

#### 4. GARCH/Kalman and SMC Fields With Live Data

**Test:** Open drill panel and scroll to I4 Context section and Smart Money section.
**Expected:** GARCH regime label (amber when high), GARCH sigma/ratio/shock, Kalman slope/pos/uncertainty appear. BSL/SSL touches and significance appear. "In premium" and Equilibrium level appear.
**Why human:** Requires live I4 pipeline data flowing; fields are conditionally rendered only when non-null, so empty live data would correctly show nothing.

#### 5. GARCH Regime Amber Styling

**Test:** Observe the "GARCH regime" row during a high-volatility bar (garch_vol_regime === 2 from pipeline).
**Expected:** The value "high" renders in amber (#f59e0b / text-amber-400). During low/normal regimes, no amber styling.
**Why human:** Requires a high-volatility market period to trigger the regime=2 classification from the pipeline.

### Gaps Summary

No gaps found. All 5 observable truths are verified with substantive implementations and working wiring. All 8 requirements (DASH-01 through DASH-08) are satisfied by evidence in the codebase. All 1553 unit tests pass. TypeScript compilation succeeds with no errors.

The only remaining items are visual/interactive human verifications that require a live running system — the code infrastructure is complete and correctly wired.

---

_Verified: 2026-03-12_
_Verifier: Claude (gsd-verifier)_
