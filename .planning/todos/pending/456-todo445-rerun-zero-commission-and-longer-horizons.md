---
status: pending
priority: P2
filed: 2026-09-29
source: owner review of todo 445's decision (2026-09-29): cost model overstates commission; horizons too short
---

# Rerun the 5m name set with zero commission, then test longer horizons

## What

Todo 445 chose `keep_5m` with a 5m name set of `ret_autocorr_1` and `sweep_detected`. Two inputs
narrowed that set more than the owner intends:

1. Cost model. `scripts/research/todo445_5m_incremental_ic.py` copies the 0b hurdle: 1.4bp per
   side, half spread (0.7bp) plus commission ($0.0035/share at an assumed $50, 0.7bp). The live
   book will likely execute at a zero-commission broker (Alpaca, TastyTrade, Tradier or
   Fidelity), so per-side cost is about half and `ic_min` halves.
2. Horizons. Only about 2.5 hours and half a session were tested. A 5m signal can be held
   longer; incremental information over the 1h and 1d versions at 1 to 5 day holds is untested.

## Steps

1. Part A (no new look): make commission a parameter defaulting to 0, add a small sell-side
   SEC/FINRA fee term (verify current rates first), keep the 1.4bp spread anchor. Rederive the
   cost-clearing step from the recorded p-values in
   `.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-07-todo445-result.json`
   (no DB query, same precedent as the BH-FDR correction). Report the name set at $0 and at
   $0.0035 per share side by side.
2. Part B (a counted look): extend the horizons to multi-day and residualize each 5m feature on
   its 15m, 1h and 1d counterparts. Record it in `.planning/gate_look_log.jsonl`. In-sample only,
   before `oos_start`.
3. Any change to the 5m name set feeds the phase 186 feature_vectors rebuild scope, so land
   this before that rebuild step runs or record it as a follow-up rebuild.

## Constraints

- No hyper-traded candidates: horizons are multi-hour to multi-day, low turnover.
- Statistics stay gross; costs gate only the name set and promotion (E18).
- Research attempts are paused until 185 and 186 land; Part A is a re-derivation and can run
  sooner, Part B waits.
