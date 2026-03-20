# Phase 42: Candlestick Pattern Expansion - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Expand I5 candlestick pattern library from 19 existing patterns to 28 total patterns by adding:
- Directional Harami variants: `harami_bull`, `harami_bear` (2 patterns)
- High-reliability reversal patterns: `abandoned_baby_bull`, `abandoned_baby_bear` (2 patterns)
- Market extreme patterns: `tweezer_top`, `tweezer_bottom` (2 patterns)
- Momentum continuation patterns: `belt_hold_bull`, `belt_hold_bear` (2 patterns)
- Gap reversal patterns: `kicker_bull`, `kicker_bear` (2 patterns)

Then calibrate `CandlestickPatternSetup` I7 plugin with database-learned pattern confidence weights, enabling adaptive reliability tier assignment based on live market outcomes.

**Scope constraint:** Pattern detection only — no changes to I7 signal generation logic beyond weight lookup. New patterns flow through existing `CandlestickPatternSetup` gates (trend regime, volume confirmation, S/R proximity).

</domain>

<decisions>
## Implementation Decisions

### Pattern Directionality Architecture

- **Separate directional fields** for Harami patterns: `harami_bull` and `harami_bear` (matching existing `engulfing_bull`/`engulfing_bear` pattern)
- **Rationale:** ML feature engineering best practice — explicit directional features eliminate conditional logic in training pipeline, enable per-direction statistical validation, and simplify ML integration
- **Storage cost:** Negligible — ~265 KB/day uncompressed, < 50 KB/day compressed (TimescaleDB Gorilla compression)
- **Reversibility:** If Phase 46 ML analysis shows no statistical difference between directions, can consolidate to single field (cheaper than splitting later)

### 7 New Pattern Definitions

All patterns follow existing `candlestick_patterns.py` structure (3-bar lookback, boolean outputs):

1. **Harami Bull/Bear** (2 patterns)
   - pp = large body (> 50% of range), p = small body entirely inside pp (bullish harami) OR bearish harami
   - Unlike `harami_cross` (which requires doji), harami allows small body
   - Direction matches p candle: `harami_bull` (p bullish), `harami_bear` (p bearish)

2. **Abandoned Baby Bull/Bear** (2 patterns)
   - pp = large body, p = doji with gap up (bullish) or gap down (bearish), c = large body reversing direction
   - Gap requirement: p body does not overlap pp body (gap up/down)
   - Higher reliability than standard doji patterns due to gap confirmation

3. **Tweezer Top/Bottom** (2 patterns)
   - Two consecutive bars with identical (or near-identical) highs (top) or lows (bottom)
   - Near-identical: abs(high1 - high2) ≤ 0.1 × ATR or abs(low1 - low2) ≤ 0.1 × ATR
   - Indicates market indecision at extreme levels

4. **Belt Hold Bull/Bear** (2 patterns)
   - Long white candle (bullish) or long black candle (bearish) with no upper wick (bull) or no lower wick (bear)
   - Body > 70% of range, wick on opposite side < 10% of range
   - Strong momentum continuation signal

5. **Kicker Bull/Bear** (2 patterns)
   - Gap up from prior black candle (bullish kicker) or gap down from prior white candle (bearish kicker)
   - Gap requirement: current bar open does not overlap prior bar body
   - No wick on gapped side (clean breakout)
   - High-reliability reversal but rare pattern

### Reliability Tier Classification (Literature-Based Priors)

Conservative priors from technical analysis literature (Nison 2001, Bulkowski 2021), discounted by 10% for futures market adjustment:

**Tier 1 — High Reliability** (base_confidence 0.70–0.75):
- `abandoned_baby_bull`: 0.70 (68% literature → discounted 10%)
- `abandoned_baby_bear`: 0.70
- `kicker_bull`: 0.70 (rare but high win rate when fires at key levels)
- `kicker_bear`: 0.70

**Tier 2 — Moderate Reliability** (base_confidence 0.55–0.65):
- `harami_bull`: 0.60 (55% literature → conservative rounding)
- `harami_bear`: 0.60
- `tweezer_top`: 0.60 (52% literature)
- `tweezer_bottom`: 0.60
- `belt_hold_bull`: 0.55 (49% literature → discounted)
- `belt_hold_bear`: 0.55

**Note:** These are bootstrap priors only. Phase 46 ML analysis will re-calibrate based on actual market outcomes (p < 0.05, N ≥ 30). Patterns may be promoted/demoted tiers based on statistical evidence.

### Confidence Weight Architecture — Database-Driven Learning

**Renaissance principle:** "Earn the right through proof" — pattern weights learned from live data, not hardcoded constants.

**Phase 42 implementation:**

1. **Create `pattern_reliability` table** (new migration):
   ```sql
   CREATE TABLE pattern_reliability (
       pattern_name TEXT NOT NULL,
       timeframe TEXT NOT NULL,
       base_confidence FLOAT NOT NULL,
       sample_size INTEGER DEFAULT 0,
       win_rate FLOAT,
       p_value FLOAT,
       ic_score FLOAT,
       is_bootstrap BOOLEAN DEFAULT true,
       last_updated TIMESTAMP DEFAULT NOW(),
       PRIMARY KEY (pattern_name, timeframe)
   );

   CREATE INDEX idx_pattern_reliability_bootstrap
       ON pattern_reliability(is_bootstrap)
       WHERE is_bootstrap = true;
   ```

2. **Seed with literature-based priors** (migration inserts):
   ```sql
   INSERT INTO pattern_reliability (pattern_name, timeframe, base_confidence, is_bootstrap) VALUES
       ('abandoned_baby_bull', '1m', 0.70, true),
       ('abandoned_baby_bear', '1m', 0.70, true),
       ('harami_bull', '1m', 0.60, true),
       -- ... all 7 new patterns
       ('belt_hold_bear', '1m', 0.55, true);
   ```

3. **CandlestickPatternSetup queries DB** with 15-min in-memory cache:
   ```python
   # In CandlestickPatternSetupPlugin.__init__
   self._pattern_weights_cache: dict[str, float] | None = None
   self._cache_ts: datetime | None = None
   self._cache_ttl_sec = 900  # 15 minutes

   def _load_pattern_weights(self, db: asyncpg.Connection) -> dict[str, float]:
       now = datetime.now(UTC)
       if self._cache_ts and (now - self._cache_ts).total_seconds() < self._cache_ttl_sec:
           return self._pattern_weights_cache

       rows = await db.fetch("""
           SELECT pattern_name, base_confidence
           FROM pattern_reliability
           WHERE is_bootstrap = true OR sample_size >= 30
       """)

       self._pattern_weights_cache = {r['pattern_name']: r['base_confidence'] for r in rows}
       self._cache_ts = now
       return self._pattern_weights_cache
   ```

4. **`weight_updater` extends to calibrate patterns** (Phase 42.3):
   - Query: `SELECT pattern_name, COUNT(*), AVG(outcome_binary) FROM signal_ledger WHERE setup_plugin = 'trad_CandlestickPatternSetup' AND outcome IN ('target_1', 'target_1_2', 'target_full', 'stopped_at_entry', 'stopped_in_trade') GROUP BY pattern_name`
   - Compute win_rate, p_value (proportions z-test), IC score
   - Update `pattern_reliability` where `sample_size >= 30` and `p < 0.05`
   - Set `is_bootstrap = false` when data-driven confidence replaces prior

**Benefits:**
- **Adaptive from day one:** System improves itself as evidence accumulates
- **Full audit trail:** Every weight change queryable via dashboard
- **Single source of truth:** No code-DB drift
- **Renaissance-grade:** Let the data speak, not hardcoded assumptions

### Pattern Detection Validation Strategy

**Renaissance principle:** "Don't debate test tiers — measure what matters."

**Phase 42 validation approach:**

1. **Unit tests** (fast, cheap, verify pattern structure):
   - Test file: `tests/unit/test_candlestick_patterns.py`
   - Fixture sets: malformed patterns return `False`
   - Example: Three White Soldiers requires 3 consecutive bullish bars with specific body/wick ratios
   - Example: Abandoned Baby requires gap + doji + reversal
   - Coverage: All 7 new patterns have at least 2 fixtures (valid, invalid)

2. **Single 7-day historical backtest** (validate viability, one-time):
   - Run after implementing all 7 patterns: `.venv/bin/python production/scripts/historical_backfill.py --symbols ES --days 7 --replay-only`
   - Query: `SELECT pattern_name, COUNT(*) FROM signal_ledger WHERE setup_plugin = 'trad_CandlestickPatternSetup' AND computed_at > NOW() - INTERVAL '7 days' GROUP BY pattern_name`
   - **Success criteria:** ≥ 6 of 7 patterns fire at least once in 7-day ES 1m window
   - **Investigation if failure:** Pattern too restrictive? Too rare for ES only? Market conditions?
   - **No ongoing integration tests** — live monitoring is the real test

3. **Live observability** (Renaissance continuous validation):
   - `setup_performance` table tracks per-pattern win rates, refreshed every 15 min
   - Dashboard shows: pattern frequency (fires/month), win rate (last 30 days), IC score
   - **Investigation triggers:**
     - Win rate < 40% → demote to lower confidence tier
     - Fires < 5 times/month → is pattern viable for our symbols?
     - IC score < 0.05 or p > 0.05 → no statistical edge, remove pattern
   - **No separate integration test suite** — live data IS the integration test

**Why this approach:**
- Compute-efficient: Unit tests (fast) + one backtest (negligible) + live monitoring (free)
- Renaissance-grade: Let the market tell us which patterns work, not test suites
- Avoids over-engineering: No ongoing synthetic data pipelines

### Claude's Discretion

- Exact gap tolerance for Abandoned Baby and Kicker patterns (0.1% of bar range or 0.2%?)
- Exact ATR multiplier for Tweezer wick tolerance (0.1× or 0.15×?)
- Whether Belt Hold requires zero wick or < 10% body wick (clean signal vs noise allowance)
- Exact cache TTL for pattern weights (15 min or align with weight_updater frequency?)
- SQL query optimization for pattern_reliability (materialized view for hot paths?)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Pattern detection logic
- `src/intelligence/patterns/candlestick_patterns.py` — Existing 19 pattern implementations (9 base + 10 Tier 1)
- `src/intelligence/trading/candlestick_pattern_setup.py` — I7 plugin consuming I5 outputs with trend regime + volume + S/R gates

### Schema registration
- `src/intelligence/schemas.py:391-511` — I5Patterns schema (75 fields total, candlestick fields at lines 489-509)
- `src/intelligence/register_plugins.py` — TIER_I5 constant (must add new pattern outputs to plugin.outputs frozenset)

### Database tables (extended in Phase 42)
- `pattern_reliability` table (new) — Pattern confidence weights with bootstrap tracking and live calibration
- `setup_performance` table (existing, Phase 14) — Per-setup rolling 30d stats (win_rate, avg_pnl_r, sharpe)
- `signal_ledger` table (existing) — Signal outcomes for pattern calibration (outcome field: target_1/target_1_2/target_full/stopped_at_entry/stopped_in_trade)

### Weight updater architecture
- `src/intelligence/ml/weight_updater.py` — Daily CIS weight training (Phase 14), extend to include pattern calibration
- `production/migrations/042_pattern_reliability.sql` — New table creation + bootstrap seed data

### Test patterns
- `tests/unit/test_candlestick_patterns.py` — Existing pattern unit tests (extend for 7 new patterns)
- `tests/unit/service_tests/test_signal_generator_service.py` — Signal generator test patterns (plugin state, compute_full invocation)

### Requirements
- `.planning/REQUIREMENTS.md` §CANDLE — CANDLE-01 (18 new I5 patterns), CANDLE-02 (confidence tier weights)

### Technical references (pattern definitions)
- Nison, Steve. "Japanese Candlestick Charting Techniques" (2001) — Pattern definitions, reliability statistics
- Bulkowski, Thomas. "Encyclopedia of Candlestick Charts" (2021) — Win rate data, pattern recognition rules
- PROJECT.md §Renaissance Decision Framework — "Instrument everything", "Earn the right through proof", "Let the system run"

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `candlestick_patterns.py` structure (3-bar lookback: pp, p, c) — all new patterns follow this pattern
- Existing pattern field naming: `{pattern_name}_{direction}` for directional variants (engulfing_bull/bear, pin_bar_bull/bear)
- `CandlestickPatternSetupPlugin` candidate collection pattern (priority_rank, direction, pattern_name, base_confidence, sr_auto_satisfied) — extend to 7 new patterns
- `trend_regime` gate logic (abs(trend_regime) >= 0.5) — already enforced for all candlestick patterns
- `volume_confirms` logic (vol[-1] > vol_sma20 * 1.3) — volume confirmation boost already implemented
- `sr_proximity_atr` logic (nearest_support/resistance within 0.3×ATR) — S/R confirmation already implemented

### Established Patterns
- Pattern outputs are `float` (0.0 or 1.0), not boolean — maintains consistency with existing I5 patterns
- Pattern detection uses `df.iloc[-1]`, `df.iloc[-2]`, `df.iloc[-3]` (c, p, pp) indexing — all new patterns follow this
- Body/wick calculations: `c_body = abs(c_c - c_o)`, `c_upper_wick = c_h - max(c_o, c_c)`, `c_lower_wick = min(c_o, c_c) - c_l`
- Range calculations: `c_range = c_h - c_l`, body ratio: `c_body / c_range` (with guards for `c_range > 0`)
- I5 schema uses `extra="forbid"` — all pattern fields must be declared or validation fails

### Integration Points
- `src/intelligence/patterns/candlestick_patterns.py` — Add 7 new pattern detection functions + outputs frozenset
- `src/intelligence/schemas.py:391-511` — Add 7-9 new fields to I5Patterns class (harami_bull, harami_bear + 7 new patterns)
- `src/intelligence/register_plugins.py` — No changes needed (CandlestickPatternsPlugin already registered)
- `src/intelligence/trading/candlestick_pattern_setup.py` — Extend candidate collection to include 7 new patterns with weights from DB
- `services/market_analysis_service.py` — No changes needed (I5 patterns computed automatically by plugin loop)
- `production/migrations/042_pattern_reliability.sql` — New migration for pattern_reliability table + seed data
- `src/intelligence/ml/weight_updater.py` — Extend run_weight_update() to calibrate pattern_reliability from signal_ledger
- `tests/unit/test_candlestick_patterns.py` — Add unit tests for 7 new patterns (2 fixtures each)

</canonical_refs>

<specifics>
## Specific Ideas

- **Renaissance principle applied:** Pattern weights are hypotheses, not constants. Database table `pattern_reliability` tracks priors (is_bootstrap=true) and promotes to data-driven weights (is_bootstrap=false) once statistical significance achieved.
- **Adaptive learning from day one:** No artificial 4-month delay to Phase 46. System starts learning immediately, conservatively (literature priors), and self-improves as evidence accumulates.
- **Full observability:** Dashboard can query `SELECT * FROM pattern_reliability ORDER BY win_rate DESC` to see which patterns actually work. Audit trail shows when/why weights changed.
- **Separate directional fields (harami_bull/bear):** ML feature engineering best practice. Enables per-direction win rate tracking (e.g., harami_bull = 62%, harami_bear = 38% would be signal we'd lose with single field).
- **Conservative priors:** Literature-based win rates discounted 10% for futures market adjustment. Better to underestimate pattern reliability and let system promote winners than overpromise and deliver weak signals.
- **Test strategy tied to observability:** Unit tests verify logic, one 7-day backtest validates viability, live monitoring is the real test. No ongoing synthetic data pipelines — let the market tell us which patterns work.

</specifics>

<deferred>
## Deferred Ideas

- **Per-(symbol, tf, regime) pattern reliability:** Current design aggregates across all symbols/timeframes/regimes. Renaissance segmentation (REL-04) could discover that abandoned_baby works better on ES 1m in ranging regime than NQ 15m in trending regime. Deferred to Phase 46 ML analysis.
- **Pattern interaction effects:** Some patterns may reinforce each other (e.g., harami_bull + tweezer_bottom at same level = higher win rate than either alone). Deferred to Phase 46 confluence analysis.
- **Multi-timeframe pattern confluence:** Abandoned baby on 1m + morning star on 5m at same timestamp = stronger signal. Requires cross-TF pattern detection, currently out of scope.

</deferred>

---

*Phase: 42-candlestick-pattern-expansion*
*Context gathered: 2026-03-20*
