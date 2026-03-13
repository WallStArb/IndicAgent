# Phase 29: Renaissance Signal Quality - Context

**Gathered:** 2026-03-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Close 10 signal quality gaps across 4 tiers — T0 (bug fix), T1 (wire-ins using existing data),
T2 (2 new I4 plugins), T3 (drift detection feedback loops). No new data sources. No new UI.
Everything builds on infrastructure that already exists.

</domain>

<decisions>
## Implementation Decisions

### Design Philosophy (applies to all decisions below)

Every decision was evaluated through three Renaissance lenses:
1. **Information preservation** — express reduced value rather than discard signals. Soft gates
   over hard gates. Continuous functions over step functions.
2. **Instrument everything** — if data exists at computation time and cannot be reconstructed
   later (because scoring functions evolve), capture it now. Storage is cheap; lost labels are
   permanent.
3. **Automate the feedback loop** — detection without automated response is expensive logging.
   Manual tuning is fragile. Build the loop, set principled starting parameters, let empirical
   calibration drive future tuning.

### T0: constituent_contributions — full audit trail, per-feature granularity

**What to capture:** Per-feature contributions within each CIS bucket — not just per-setup
totals. Each bucket method (`_trend`, `_momentum`, etc.) returns `(score, {feature: contribution})`
instead of just `score`. Example:

```json
{
  "momentum": {
    "rsi_14": 0.09,
    "macd_histogram": 0.06,
    "trad_DivergenceStack": 0.07
  },
  "trend": {
    "kalman_slope": 0.11,
    "trend_regime": 0.14,
    "trad_TrendFollowing": 0.08
  }
}
```

**Why per-feature (not just per-setup):** The CIS scoring function will evolve — weights will
be learned, bucket formulas will be tuned. Per-feature contributions cannot be reconstructed
after the function changes. "Cannot discover patterns you didn't know to look for at collection
time." Bucket-level totals are already available as `bucket_scores` — they add nothing new.

**Where it lives:** `intelligence_features.i7` as part of `all_ranked`, via the existing
feature bus write path. NOT in `signal_ledger` (only covers winners — misses all competing
signals that lost), NOT on the IntelligenceEvent bus directly (payload overhead without routing
value). `intelligence_features` has a row per bar per symbol/TF — full competition coverage
including losers.

**Implementation:** Refactor all 6 `CISScorer._bucket()` methods to return
`(float, dict[str, float])`. Assemble contributions in `score()`. `CISResult` field already
exists. Zero external API change.

### T1-A/C: Alpha decay — soft multiplier, per-setup state

**Model:** Soft confidence multiplier only — no hard cooldown. Repeated same-direction signals
from the same setup fire with reduced confidence:

```python
multiplier = 1.0 - (bars_since_last_fire / alpha_half_life)
sig["confidence"] *= max(0.0, multiplier)
```

**Why soft, not hard:** A hard cooldown discards information — the signal exists, its value
just decays. Renaissance: express reduced value, don't throw it away. The signal still competes
in `all_ranked` with lower confidence, which is the correct representation of diminishing alpha.

**State:** New `_setup_last_fire: dict[tuple[str, str, str, int], dict]` keyed by
`(symbol, tf, setup_plugin, direction)`. Separate from the existing `_signal_gate` (which is
per-condition onset). Both coexist — they answer different questions.

**`alpha_half_life` per-TF constants** (hardcoded, same pattern as `MIN_BARS_BETWEEN_SIGNALS`):

```python
ALPHA_HALF_LIFE_BARS: dict[str, int] = {"1m": 10, "5m": 6, "15m": 4, "1h": 3}
```

These are **initial principled values, not calibrated values.** Comment in code: "Replace with
learned values after 90 days of outcome data — regress half-life against Sharpe per TF."
No config infrastructure now. Tune with a code change when data justifies it.

### T1-B: Signal freshness decay — exponential, in lifecycle service

Active signal confidence decays per-bar as it ages:

```python
freshness = exp(-λ * bars_since_fire)
# λ = ln(2) / half_life_bars  (half-life: confidence halves after N bars)
```

Applied in `signal_lifecycle_service` on each bar evaluation for active signals.
Freshness is in-memory only — not written back to `signal_ledger`. It affects lifecycle
evaluation (whether to continue holding) but does not mutate the original confidence record.

### T1-D/E: rel_volume + killzone — CIS momentum/regime bucket wire-ins

`rel_volume` (already in I1) wires into `CISScorer._momentum()`:
- `rel_volume > 1.5` → confidence boost (volume confirms signal)
- `rel_volume < 0.5` → confidence suppression (dead volume = likely false breakout)

Killzone context (already in intelligence bus) wires into `CISScorer._regime()`:
- Active killzone open (London/NY) → regime bucket boost
- Dead session (off-hours, low liquidity) → regime bucket reduction

Both are additive sub-terms within existing bucket methods — zero structural change to CIS.

### T2: Hurst + Shannon — quality multipliers in `_build_all_ranked()`, not CIS buckets

**Architecture decision:** Hurst and Shannon are unsigned quality gates, not directional
signals. They cannot live in CIS buckets (which operate on `[-1, +1]` signed scores) because
their effect is **setup-type-conditional** — high Hurst is good for trend setups, bad for
mean-reversion setups. A universal bucket modifier would be wrong for half the signals.

**Where they apply:** In `_build_all_ranked()`, per-signal, after CIS scoring:

```python
for sig in all_competing:
    setup_class = "trend" if sig["plugin"] in TREND_SETUPS else "mean_reversion"
    hurst_q = features.get(f"hurst_{setup_class}_quality", 1.0)
    entropy_q = features.get("entropy_quality", 1.0)
    sig["confidence"] *= hurst_q * entropy_q
```

**Extensibility:** Future quality signals (volume quality, liquidity quality, session quality)
follow the same pattern — add a named quality field to the appropriate I4 plugin, add one line
in `_build_all_ranked()`. No changes to CIS architecture. Zero maintenance burden.

**`HurstExponentPlugin` (I4) outputs:**
- `hurst_exponent` — raw H value [0, 1]
- `hurst_trend_quality` — quality score for trend setups: high when H > 0.5 (trending market)
- `hurst_mr_quality` — quality score for mean-reversion setups: high when H < 0.5

**`ShannonEntropyPlugin` (I4) outputs:**
- `shannon_entropy` — raw normalized entropy [0, 1]
- `entropy_quality` — universal gate: high when market is structured/predictable

All 5 fields flow through the bus as standard I4 fields → persist to `intelligence_features`
automatically. Renaissance: market quality at signal time is a critical labeled training
feature. Never discard.

### T3: Drift detection — automated feedback loops, not monitoring dashboards

**Architecture:** Standalone `drift_monitor_service` (`services/drift_monitor_service.py`,
port `:9118`, `Restart=always`). Two internal asyncio tasks:
- `KSDriftMonitor.run_forever()` — wakes every 4h
- `CUSUMMonitor.run_forever()` — wakes every 1h

**Philosophy:** Detection without automated response is expensive logging. Response without
detection is thrashing. Both layers required. The cost of a false positive (briefly
under-weighting a healthy setup) is bounded and recoverable. The cost of a missed degradation
is unbounded — continued trading on broken assumptions, compounding losses. Err toward
sensitivity.

**KS → CIS confidence modifier:**
- When KS p-value < 0.05 on key features for a symbol/TF: write drift state to Redis
  (`drift:ks:{symbol}:{tf}`)
- Signal aggregator reads Redis cache per bar: `confidence *= KS_DRIFT_CONFIDENCE_PENALTY`
- `KS_DRIFT_CONFIDENCE_PENALTY = 0.70` — named constant, one place to tune
- Starting value 0.70 is principled, not calibrated. Tune empirically once data accumulates.

**Recovery mechanics:** Gradual, not snap-back. When KS clears, reduce penalty by 50% per
clean check cycle. Full restoration after 2 consecutive clean checks (~8h). Prevents
oscillation when market sits near the KS threshold. Renaissance: stability over speed.

**CUSUM → perf_multiplier:**
- CUSUM detected performance degradation feeds the same `perf_multiplier` knob that
  `setup_performance` already turns — natural extension of the existing feedback loop
- Adjustment is **multiplicative** (composes cleanly with existing `[0.5, 1.5]` range):
  `new_multiplier = current_multiplier * cusum_adjustment_factor`
- Keeps all adjustments within the existing range, no clamping edge cases

**DB table:** `drift_monitor` — records every check result, drift state, KS statistics,
CUSUM values. Prometheus gauges. API endpoint for observability. Full audit trail.

### Claude's Discretion
- Rolling window sizes for Hurst (64 vs 128 vs 256 bars) — choose based on data availability
- Shannon entropy normalization method
- Exact `hurst_trend_quality` / `hurst_mr_quality` mapping functions (linear vs sigmoid)
- `TREND_SETUPS` constant membership (which I7 plugins are "trend" vs "mean-reversion")
- CUSUM threshold starting values (μ₀, σ₀, detection threshold k)
- `drift_monitor` table schema details

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CISScorer._bucket()` methods: refactor to return `(float, dict[str, float])` — clean,
  contained, zero external change
- `_signal_gate[(symbol, tf)]`: existing per-condition onset gate — keep as-is, add separate
  `_setup_last_fire[(symbol, tf, plugin, direction)]` alongside it
- `MIN_BARS_BETWEEN_SIGNALS`: pattern for hardcoded per-TF constants — follow same pattern for
  `ALPHA_HALF_LIFE_BARS`
- `perf_multiplier` in aggregator: CUSUM feeds the same knob — no new ranking infrastructure
- `feature_writer_service`: zero changes needed — contributions flow through existing path

### Established Patterns
- I4 plugins output named fields to IntelligenceEvent → intelligence_features automatically
- `_build_all_ranked()` iterates all competing signals — natural place for quality multipliers
- `drift_monitor_service` follows established service pattern: asyncio, structlog, Prometheus
  gauges on always-on port, `Restart=always` systemd unit

### Integration Points
- `cis_scorer.py` `score()` method: assemble contributions, populate `CISResult`
- `signal_generator_service._build_all_ranked()`: apply Hurst/Shannon quality multipliers
- `signal_generator_service._build_all_ranked()`: apply alpha decay via `_setup_last_fire`
- `signal_lifecycle_service` per-bar evaluation loop: apply freshness decay to active signals
- `src/api/routes/sse.py` (or new route): expose drift state for observability

</code_context>

<specifics>
## Specific Implementation References

**Design docs (use as research input):**
- `docs/ideas/renaissance-gap-analysis.md` — full T0–T3 implementation specs with code sketches
- `docs/plans/2026-03-11-signal-drift-detection-design.md` — drift service architecture,
  KS/CUSUM algorithms, DB schema, Redis cache design

**Key Renaissance framing from CLAUDE.md:**
- KS → CIS penalty (confirmed)
- CUSUM → perf_multiplier auto-adjustment (confirmed)

**Naming conventions to follow:**
- Quality fields: `hurst_trend_quality`, `hurst_mr_quality`, `entropy_quality`
- Drift Redis key: `drift:ks:{symbol}:{tf}`, `drift:cusum:{setup_plugin}`
- Constants: `ALPHA_HALF_LIFE_BARS`, `KS_DRIFT_CONFIDENCE_PENALTY`

</specifics>

<deferred>
## Deferred Ideas

- **Regime suppression virtual outcomes** (Gap 4 in renaissance-gap-analysis.md): track
  simulated outcomes for regime-suppressed shadow signals to measure gate calibration. Requires
  `outcome_virtual` column + lifecycle simulation mode. Separate phase.
- **A/B testing protocol** (Gap 5): shadow mode before CIS weight promotion. Requires
  `experiment_version` column + experiment coordinator. Separate phase.
- **Momentum Exhaustion Entry** (T2-C from gap analysis): RSI second-derivative as I7 plugin
  or I4 feature. Deferred — covered partially by existing MomentumAcceleration infrastructure.
- **Config/DB-driven `alpha_half_life`**: deferred until 90 days of outcome data justifies
  empirical calibration. Revisit in v2.0.
- **Graduated KS penalty** (penalty scales with KS statistic magnitude): theoretically more
  correct but requires calibration data we don't have. Deferred.

</deferred>

---

*Phase: 29-renaissance-signal-quality*
*Context gathered: 2026-03-12*
