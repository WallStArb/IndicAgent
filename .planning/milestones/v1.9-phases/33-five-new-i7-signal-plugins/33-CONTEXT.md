# Phase 33: Five New I7 Signal Plugins - Context

**Gathered:** 2026-03-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Register six trading setup plugins in TIER_I7 that cover five market conditions previously invisible to I7: failed breakouts, opening range setups (15-min and 30-min as separate plugins), previous-day level tests, second-leg Fibonacci continuations, and intraday volatility contractions. All six plugins must fire in historical replay runs. Design framing: Renaissance — instrument everything, segment relentlessly, earn the right through proof.

Note on scope: ORB is split into two separate plugins (`trad_ORB15` + `trad_ORB30`) for independent statistical tracking. Phase success criteria still hold; six plugins satisfy "five market conditions" with richer segmentation.

</domain>

<decisions>
## Implementation Decisions

### FailedBreakout (trad_FailedBreakout)
- Gate: `bos_detected == 1.0` from SMC tier — trust the existing confirmation, no additional penetration filter
- Reversal window: **3 bars** — tight, high-precision window; breakout only counts as failed if price closes back through the BOS level within 3 bars
- Entry trigger: **close back through the BOS level** (objective, statistically clean — reversal confirmed only when price proves it with a close)
- Entry type: `at_pullback`
- Regime: `mean_reversion` preferred — HMM mean-reversion regime boosts confidence; trend regime reduces confidence ~20% but does not block the signal
- Stop: via `trade_framer.py` — structural snap to BOS level first (within 1.5×ATR), GARCH-adaptive ATR fallback
- Feature logging: `bos_level`, `bars_since_bos`, `reversal_close_delta` logged per signal for training

### Opening Range Breakout — Two Separate Plugins
**Decision: two independently registered plugins for statistical segmentation** — setup performance tracks them separately; if one variant has higher alpha, weight updater promotes it independently.

**trad_ORB15** (15-minute opening range):
- Range defined from 09:30–09:45 ET (first 15 minutes of NY session)
- Fires: first bar closing above/below the 15-min range with volume expansion
- Session gate: 09:30–11:30 ET only (strict — no signals outside this window)

**trad_ORB30** (30-minute opening range):
- Range defined from 09:30–10:00 ET (first 30 minutes of NY session)
- Fires: first bar closing above/below the 30-min range with volume expansion
- Session gate: 09:30–11:30 ET only

**Shared ORB behavior:**
- Overnight gap directional bias: `gap_pct = (open - prior_session_close) / prior_session_close`; gap > 0 → bullish bias boosts long confidence, reduces short confidence (and vice versa); threshold 0.1% to filter micro-gaps
- Volume expansion gate: breakout bar volume > 1.5× session average (proxy via `rel_volume` if available)
- Entry type: `at_pullback` on close of breakout bar
- Stop: `trade_framer.py` — structural snap to opening range boundary first, GARCH ATR fallback
- Regime: trend regime preferred for continuation ORB; any regime allowed

### PrevDayLevelTest (trad_PrevDayLevelTest)
- **Levels triggered:** PDH (`prior_session_high`), PDL (`prior_session_low`), and PDC (`prior_session_close`) — all three are active triggers, not just context
  - Renaissance rationale: PDC is a real institutional reference level; collect all labeled samples and let weight updater determine which level has stronger alpha
- **Two variants in one plugin** — `setup_variant` field in signal output:
  - `"fade"` — price approaches level and reversal momentum detected; fade the level
  - `"continuation"` — price breaks through level, pulls back to re-test, holds; enter continuation
- Regime gate: fade variant → mean-reversion regime preferred; continuation variant → trend regime preferred
- Proximity gate: within 0.5×ATR of the level to qualify as "approaching"
- Entry type: `at_limit` (fade) / `at_pullback` (continuation)
- Stop: `trade_framer.py` structural snap to the level itself (PDH/PDL/PDC as the invalidation point)

### SecondLegContinuation (trad_SecondLegContinuation)
- **Leg 1 detection:** uses I3 `swing_high` / `swing_low` from `IntelligenceEvent` — canonical swing detection, no redundant computation
- **Fib zone:** 38.2%–61.8% of Leg 1 amplitude; entry target at **50% retracement** (most common institutional retracement)
- Entry type: `at_limit` — limit order pre-positioned at the 50% fib level (Renaissance: pre-position at the quantitatively optimal level, no chasing)
- Targets: T1 = 100% measured move, T2 = 127.2%, T3 = 161.8% of Leg 1 amplitude
- Stop: Leg 1 swing low (long) / swing high (short) — structural invalidation via `trade_framer.py`
- Regime gate: trend regime required (HMM); second legs don't form in ranging conditions
- Qualifying condition: Leg 1 amplitude must be ≥ 1.0×ATR to filter micro-swings

### VCP — Volatility Contraction Pattern (trad_VCP)
- **Scope: intraday session only** — contractions measured within the current session's bar history; multi-day VCP would require daily bars and fires far less frequently in 1m/5m replay
- Minimum contractions: **3+ successive range contractions** (each H-L range smaller than the prior) with declining bar volume
- Regime gate: **HMM trend regime required (prob ≥ 0.60)** — VCP is definitionally a continuation/compression pattern; a VCP in ranging/chop is noise, not signal. Regime is definitional, not a filter.
- Entry trigger: first bar closing above (long) / below (short) the most recent contraction's range boundary with volume expansion
- Entry type: `at_pullback` on expansion bar close
- Directional bias: follow HMM trend direction; counter-trend VCP is not a valid setup
- Stop: `trade_framer.py` structural snap to VCP base (lowest contraction low for long), ATR fallback

### Cross-Plugin Architecture
- **All 6 plugins call `trade_framer.py`** for stop/target sizing — inherits GARCH-adaptive multipliers (SIG-01/SIG-02) automatically; no per-plugin stop logic
- **All 6 fire as production signals** and write to `signal_ledger` with complete feature snapshots — statistical promotion gate (`validate_alpha.py`) runs in 30 days when N ≥ 30 per setup
- **Entry types summary:** FailedBreakout = at_pullback; ORB15/30 = at_pullback; PrevDayFade = at_limit; PrevDayContinuation = at_pullback; SecondLeg = at_limit; VCP = at_pullback

### Claude's Discretion
- Exact ATR buffer for BOS stop in FailedBreakout (0.1–0.25× ATR)
- ORB range high/low storage approach (in-memory state dict vs features)
- VCP contraction detection algorithm (rolling window H-L comparison)
- Exact session average volume computation for ORB volume gate
- `swing_high_age_bars` qualifying threshold for SecondLeg (to avoid stale swings)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Plugin Protocol & Tier Conventions
- `src/intelligence/CLAUDE.md` — tier protocol, plugin interface, tier directory conventions, registration patterns
- `src/intelligence/register_plugins.py` — TIER_I7 list (single source of truth); all 6 new plugins must be added here

### Existing Plugin Reference Implementations
- `src/intelligence/trading/choch_reversal.py` — simplest I7 plugin pattern to follow (gate → direction → trade_framer → output)
- `src/intelligence/trading/session_extremes_setup.py` — session-gated plugin with ET timezone handling; reference for ORB session logic
- `src/intelligence/trading/momentum_breakout.py` — BOS-consuming plugin; reference for FailedBreakout BOS feature consumption
- `src/intelligence/trading/trend_following.py` — regime-gated plugin; reference for HMM trend gate pattern

### Feature Schema
- `src/intelligence/schemas.py` — canonical IntelligenceEvent fields; confirm all consumed features exist before planning:
  - BOS/CHoCH: `bos_detected`, `bos_direction`, `bos_level`, `choch_detected`, `choch_direction`
  - Swing: `swing_high`, `swing_low`, `swing_high_type`, `swing_low_type`, `swing_high_age_bars`, `swing_low_age_bars`
  - Session: `session_ny`, `session_london`, `prior_session_high`, `prior_session_low`, `prior_session_close`
  - Regime: `hmm_regime`, `hmm_regime_prob`, `garch_vol_regime`
  - Volume: `rel_volume`

### Stop Architecture
- `src/intelligence/trading/trade_framer.py` — centralized stop/target sizing; all 6 plugins must call this; structural snap logic + GARCH-adaptive ATR fallback

### Session/Timezone Logic
- `src/intelligence/context/session_context.py` — ET timezone handling (`_ET_TZ`, `_in_window`); reference for 09:30–11:30 ORB window gate

### Requirements
- `.planning/REQUIREMENTS.md` PLUG-01 through PLUG-05 — full plugin specs with exact output field names

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `trade_framer.py` (`src/intelligence/trading/trade_framer.py`): All stop/target computation — call directly, don't reimplement
- `session_context.py` `_ET_TZ` + `_in_window()`: ET timezone and session window helpers — import directly for ORB
- `choch_reversal.py`: Cleanest minimal I7 plugin pattern — 60 lines, gate→direction→framer→output
- `session_extremes_setup.py` `_SESSIONS` dict + session flag reading: reference for ORB 09:30–11:30 gate
- `IntelligenceEvent` features: `swing_high`, `swing_low`, `swing_high_age_bars` — I3 swing detection already running; SecondLeg consumes these directly

### Established Patterns
- Plugin class: `@dataclass` with `name`, `outputs`, `min_lookback`, `supports_incremental=False`, `capability_tags`, `inputs`, `regime_type`, `_state`
- All I7 plugins call `self._no_signal()` on gate failure
- HMM gate pattern: `hmm_regime = features.get("hmm_regime"); if hmm_regime not in ("trend", ...): return self._no_signal()`
- Entry type field: `"at_limit"` or `"at_pullback"` — string literal in signal output dict
- `_state` dict keyed by `(symbol, timeframe)` for stateful per-instrument tracking (needed by ORB range storage, VCP contraction tracking, FailedBreakout BOS tracking)

### Integration Points
- `src/intelligence/register_plugins.py` TIER_I7 list — append all 6 new plugin names
- `services/signal_generator_service.py` — no changes needed; auto-discovers registered plugins via registry
- Each plugin file → `src/intelligence/trading/<name>.py`

</code_context>

<specifics>
## Specific Ideas

- Renaissance framing throughout: all 6 plugins fire as production signals immediately (not shadow-first) to maximize labeled training data collection; `validate_alpha.py` runs the promotion gate after N ≥ 30 per setup
- ORB split into two plugins (trad_ORB15, trad_ORB30) specifically to enable independent statistical segmentation — if 15-min ORB outperforms 30-min, weight updater discovers and promotes it automatically
- PDC included as an active PrevDayLevel trigger (not just context) because: cost is zero (field exists), labeled data is valuable, weight updater will suppress it if it has no alpha
- VCP trend regime gate is definitional (not a filter): a VCP in chop is not a VCP by Minervini's definition

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 33-five-new-i7-signal-plugins*
*Context gathered: 2026-03-16*
