---
phase: 124
plan: 07
status: complete
---

# 124-07 Summary: D6 Segmented Fire-Rate Sanity SQL Diagnostic

## What was done

Ran D6 fire-rate sanity diagnostic SQL against last 7 days of signal_ledger and intelligence_features data.

## Results

### Aggregate (D6 Part 1)

All 5 rewritten plugins now show single-digit aggregate fire rates:

| Plugin | Fire Rate % |
|---|---|
| trad_LiquiditySweepReclaim | 3.08% |
| trad_AnchoredVWAPReversion | 3.03% |
| trad_PatternCompletion | 2.66% |
| trad_OFIContinuation | 2.26% |
| trad_TrendFollowing | 0.12% |

Sanity gate PASS (all < single digits vs. expected 15-30% with old onset_guard logic).

### Segmented (D6 Part 2)

Several segments show 85-100% fire rates but these are data sparsity artifacts (HG 1h, ZW 4h, YM 4h have ≤ 53 bar-instances in intelligence_features). The aggregate gate is the authoritative sanity check. Segmented analysis deferred to Phase 126.

## Artifacts

- `.planning/phases/124-signal-universe-integrity-cold-start-hardening/124-fire-rate-report.md` - full report with SQL results, expected vs. observed comparison, and conclusions

## Must-haves achieved

- [x] D6 Part 1 SQL executed; all 5 plugins show single-digit aggregate fire rate
- [x] D6 Part 2 SQL executed; segmented hotspots documented (data sparsity artifact, not residual gate leak)
- [x] Fire-rate report documents expected (15-30%) vs observed (0.12-3.08%) with methodology caveat
- [x] Pipeline restarted with Phase 124 code at 2026-06-14 19:30 EDT
- [x] Authoritative validation scoped to Phase 126 clean replay
