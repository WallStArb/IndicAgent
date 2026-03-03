# Phase 10: CandlestickPatternSetup - Context

**Gathered:** 2026-03-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a new I7 trading setup plugin (`CandlestickPatternSetupPlugin`) that reads existing I5 `CandlestickPatterns` outputs and gates on trend/volume confluence to produce a directional trading setup signal. No raw price pattern re-detection — all pattern recognition is delegated to the I5 layer. Register in TIER_I7 (16th plugin, 87 total).

</domain>

<decisions>
## Implementation Decisions

### Pattern eligibility
- Use only the 6 directional I5 outputs: `engulfing_bull`, `engulfing_bear`, `pin_bar_bull`, `pin_bar_bear`, `hammer_detected`, `shooting_star_detected`
- Skip `doji_detected`, `inside_bar`, `outside_bar` — these have no inherent direction and would require an additional gate (trend alignment) that adds complexity for marginal signal quality
- Priority order when multiple patterns fire in the same bar: hammer/shooting_star > engulfing > pin_bar (structure-confirmed patterns rank highest)

### Confluence gating (CNDL-02)
- `trend_regime` (I4) is **mandatory**: `abs(trend_regime) >= 0.5` required (no signal in flat/ranging regime)
- Pattern direction must **agree with trend**: bullish patterns only fire when `trend_regime > 0`, bearish patterns only when `trend_regime < 0`
- At least **one additional factor** must confirm (volume OR S/R proximity):
  - Volume: current bar volume > `volume_sma_20 * 1.3` (1.3× threshold — softer than gap analysis since candlesticks are already structure-based)
  - S/R proximity: `nearest_support`/`nearest_resistance` within `0.3 * atr_14` of current price
  - Exception: `hammer_detected` and `shooting_star_detected` already embed S/R proximity in I5 — they satisfy the S/R factor automatically
- If neither volume nor S/R confirms: return `_no_signal()`

### Signal naming
- Per-pattern signal types: `candlestick_{pattern}_{long|short}`
  - Examples: `candlestick_engulfing_long`, `candlestick_hammer_long`, `candlestick_pin_bar_short`
  - Matches `PatternCompletion`'s naming convention (`pattern_{name}_{long|short}`)
- `regime_context`: `"bullish"` or `"bearish"` (same as PatternCompletion)

### Entry, stop, and targets
- Entry at `close[-1]` — standard for I7 plugins (PatternCompletion does the same)
- Stop: `1.5 × atr_14` beyond entry (consistent with TrendFollowing, PatternCompletion)
- Targets: `[2.0, 3.5, 5.0] × atr_14` extension (same multipliers as PatternCompletion and TrendFollowing)
- ATR fallback: `np.mean(high[-14:] - low[-14:])` if `atr_14` not in features

### Confidence scoring
- Base confidence from pattern type:
  - `hammer_detected` / `shooting_star_detected`: 0.65 (structure-confirmed by I5)
  - `engulfing_bull` / `engulfing_bear`: 0.55 (strong two-bar reversal)
  - `pin_bar_bull` / `pin_bar_bear`: 0.45 (single-bar rejection wick)
- Add `+0.10` if volume confirms, `+0.10` if S/R proximity confirms
- Clamp to `[0.10, 0.90]`

### Claude's Discretion
- Exact volume_sma_20 fallback (inline `np.mean(volume[-20:])` if feature not available — same as SqueezeExpansion)
- How to handle ties when multiple directional patterns fire simultaneously (highest-priority wins per ordering above)
- Whether to include `trend_confidence` in the confidence boost (minor weighting)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CandlestickPatternsPlugin` (`src/intelligence/patterns/candlestick_patterns.py`) — 9 output fields consumed as `features` dict entries; no re-import needed
- `PatternCompletionPlugin` (`src/intelligence/trading/pattern_completion.py`) — closest structural precedent: gates on I5 confidence, enters at `close[-1]`, uses 1.5×/2.0/3.5/5.0 ATR multipliers, per-pattern signal naming
- `TrendFollowingPlugin` — `trend_regime` gate pattern (`abs(trend_regime) >= regime_threshold`)
- `SqueezeExpansionPlugin` — `volume_sma_20` fallback pattern (`np.mean(volume[-20:])` or all-bar mean)
- `_no_signal()` static method — standard across all I7 plugins

### Established Patterns
- I7 dataclass structure: `name`, `outputs` (frozenset), `inputs` (tuple[InputSpec]), `capability_tags` (frozenset), `min_lookback`, `supports_incremental=False`, `_state: dict`
- `compute_full(frames)` receives `frames["main"]` (DataFrame) and `frames["features"]` (aggregated I1–I6 outputs)
- `compute_next` delegates to `compute_full` (all I7 non-incremental plugins)
- Module-level `plugin = CandlestickPatternSetupPlugin()` singleton

### Integration Points
- New file: `src/intelligence/trading/candlestick_pattern_setup.py`
- `src/intelligence/register_plugins.py`: add import + `register_pattern()` call + name in `TIER_I7` (16th entry)
- `tests/unit/intelligence/test_i7_registration.py`: update count assertions to 16 plugins, 87 total
- `tests/unit/intelligence/test_plugin_registry.py`: update `test_tier_i7_has_15_plugins` → 16

### Available Features (from features dict)
- `engulfing_bull`, `engulfing_bear`, `pin_bar_bull`, `pin_bar_bear`, `hammer_detected`, `shooting_star_detected` — from I5 CandlestickPatterns (1.0 or 0.0)
- `trend_regime` — from I4 TrendRegime (-1.0 to +1.0)
- `trend_confidence` — from I4 TrendRegime (0.0 to 1.0)
- `nearest_support`, `nearest_resistance` — from I3 SupportResistance
- `atr_14` — from I1 ATR
- `volume_sma_20` — not a dedicated I1 output; compute inline as fallback

</code_context>

<specifics>
## Specific Ideas

- `hammer_detected` and `shooting_star_detected` already check `nearest_support`/`nearest_resistance` proximity (within 0.5%) inside the I5 plugin — they get the S/R confluence factor for free without a second proximity check in I7
- Signal naming matches `PatternCompletion` convention — CIS bucket scorer will see both patterns under the `"pattern"` capability tag

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 10-candlestickpatternsetup*
*Context gathered: 2026-03-03*
