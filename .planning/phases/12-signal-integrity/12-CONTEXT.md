# Phase 12: Signal Integrity - Context

**Gathered:** 2026-03-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Add regime-aware gating to all 17 I7 plugins. Ineligible signals are not discarded — they become shadow signals written to `signal_ledger` with `status='regime_suppressed'` and tracked by `signal_lifecycle_service` for counterfactual MAE/MFE analysis. Gate thresholds: `hmm_regime_prob >= 0.60`, `hmm_regime_duration >= 5`.

</domain>

<decisions>
## Implementation Decisions

### Gating Location
- **Hybrid: class attribute + aggregator enforcement**
- Each I7 plugin declares `regime_type: str = "any" | "trend" | "mean_reversion"` as a class attribute
- The aggregator reads this attribute and applies thresholds centrally (one place to tune prob/duration thresholds)
- Replaces the current `REGIME_ELIGIBILITY` dict — self-documenting at the plugin level, no separate dict to maintain
- Gate thresholds stay in aggregator constants: `_REGIME_PROB_MIN = 0.60`, `_REGIME_DUR_MIN = 5` (raised from 0.55/3)

### Regime Sourcing — Cascade (slow-clock gating)
- Each signal TF gates on the **next-higher TF's HMM** via a `_regime_cache` maintained in signal_generator_service
- Bar data (OHLCV, indicators, entry/stop/target logic) stays in its own TF — no cross-TF price data mixing
- The regime label is a categorical market state (not bar data), sourced one step up

| Signal TF | Regime authority |
|-----------|-----------------|
| 1m        | 5m HMM          |
| 5m        | 15m HMM         |
| 15m       | 1h HMM          |
| 1h        | 4h HMM          |
| 4h        | 1d HMM          |
| 1d        | 1d HMM (own)    |

- Implementation: `_regime_cache: dict[symbol, dict[tf, {hmm_regime, hmm_regime_prob, hmm_regime_duration}]]`
- Updated on every intelligence event arrival (any TF)
- Gate map constant: `{"1m": "5m", "5m": "15m", "15m": "1h", "1h": "4h", "4h": "1d", "1d": "1d"}`
- If cache entry missing (higher TF not yet seen): skip gate (don't suppress on absent data)

### Shadow Signal Mechanics
- Suppressed signals are written to `signal_ledger` with `status='regime_suppressed'`
- Entry/stop/target levels are populated normally — setup logic runs fully before the gate decision
- `signal_lifecycle_service` queries `regime_suppressed` signals alongside `pending` at startup
- Shadow signals are **virtually activated at signal bar close** — no zone-activation check required
- MAE/MFE tracked normally until TTL expiry using the signal's own entry/stop/target levels
- Status never changes from `regime_suppressed` (never becomes `active`)
- At TTL: 8-class outcome written — this is the counterfactual ("what would have happened")
- Only lifecycle code change: extend initial DB query to include `regime_suppressed` status; skip zone-activation logic for those entries

### Regime Map — All 17 I7 Plugins
| Plugin | `regime_type` |
|--------|--------------|
| TrendFollowing | `trend` |
| MomentumBreakout | `trend` |
| LiquidityHunt | `trend` |
| MTFAlignment | `trend` |
| SqueezeExpansion | `trend` (squeeze resolves into sustained moves in trending regimes; ranging = false breakout risk) |
| MeanReversion | `mean_reversion` |
| VWAPDeviation | `mean_reversion` |
| FVGFill | `mean_reversion` (FVGs fill reliably in ranging; in strong trends they stay open) |
| LiquiditySweepReclaim | `mean_reversion` (sweep below support → reclaim is mean-reversion by design) |
| SessionExtremesSetup | `mean_reversion` (fading Asian H/L is mean-reversion) |
| CHoCHReversal | `any` (fires AT regime transitions — gating on current regime would suppress it at the exact moment it should fire) |
| RegimeTransition | `any` (same — regime-transition signal cannot be gated on current regime) |
| DivergenceStack | `any` (signals exhaustion/regime change, works in any regime) |
| PatternCompletion | `any` (reversal patterns fire when current trend is ending) |
| GapAnalysisSetup | `any` (internal fade/continuation sub-type handles regime implicitly) |
| CandlestickPatternSetup | `any` (confluence score is its own quality gate) |
| SupplyDemandSetup | `any` (works in both trending pullback-to-zone and ranging bounce contexts) |

Summary: 5 trend-only · 5 mean-reversion-only · 7 any-regime

### Claude's Discretion
- Exact field name for `regime_type` attribute (could be `regime_type`, `regime_class`, `allowed_regimes`)
- Whether `_regime_cache` is a dict-of-dicts or a flat `(symbol, tf)` keyed dict
- How to handle the edge case where 4h/1d intelligence streams are not yet subscribed

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `aggregator.py:REGIME_ELIGIBILITY` — existing dict covering 6 plugins; will be replaced by `regime_type` class attribute introspection
- `aggregator.py:_REGIME_PROB_MIN / _REGIME_DUR_MIN` — existing constants; update to 0.60 / 5
- `signal_ledger.py:insert_signals()` — already writes to signal_ledger; needs `regime_suppressed` status path
- `signal_lifecycle_service.py` — zone-activation check is the one code path to skip for shadow signals

### Established Patterns
- All I7 plugins are dataclasses with class-level attributes (`name`, `outputs`, `inputs`, `capability_tags`) — `regime_type` follows this exact pattern
- `_run_setup_plugins()` in signal_generator_service runs all plugins and returns directional signals — regime tagging happens here or in aggregator
- signal_generator already subscribes to all 4 TFs via `_stream_map`; cache update fits naturally into `_process_single_message()`

### Integration Points
- `aggregator.aggregate()` — replace REGIME_ELIGIBILITY dict lookup with `plugin.regime_type` attribute read; add `regime_eligible` / `suppression_reason` to signal dict output
- `signal_generator_service._process_single_message()` — add cache update for `_regime_cache[symbol][timeframe]`
- `signal_generator_service._process_bar()` — pass cached higher-TF regime to `aggregate()` instead of same-TF features
- `signal_lifecycle_service` — extend initial pending signal query; add shadow signal virtual-activation path

</code_context>

<specifics>
## Specific Ideas

- "What would Jim Simons do" — don't gate unless there's clear statistical logic. The 7 `any` plugins get shadow data for 90 days, then revisit empirically whether any should be reclassified
- Gate that cannot be validated by its own shadow data has no place in a quant system (direct from SIGINT-05 requirement intent)
- After 90 days: query suppressed signal outcome distribution per gate type — if consistently winning, threshold too tight

</specifics>

<deferred>
## Deferred Ideas

- Whether I7 plugins should run on 4h/1d bars (currently signal_generator subscribes to 1m/5m/15m/1h only) — defer to backlog
- Empirical reclassification of `any` plugins based on shadow signal outcome data — v1.5+
- Regime-adaptive plugin parameters (I1/I4 parameter values adapt to hmm_regime) — already in v2 backlog

</deferred>

---

*Phase: 12-signal-integrity*
*Context gathered: 2026-03-04*
