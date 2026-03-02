# Phase 09: GapAnalysisSetup - Context

**Gathered:** 2026-03-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a new I7 trading setup plugin (`GapAnalysisSetupPlugin`) that detects opening gaps by comparing prior session close to current session open, classifies them as fade or continuation based on gap size relative to ATR and volume context, and outputs a full signal with direction, bias, confidence score, entry type, stop, and target levels. Register in TIER_I7. Focused on ES and NQ at market open (9:30 ET), but plugin protocol uses `symbol=".*"`.

</domain>

<decisions>
## Implementation Decisions

### Prior close data source
- Use `opening_gap_pct` and `prior_session_close` already computed by `SessionLevelsPlugin` (I3) from the `features` dict — do NOT re-derive from raw bars
- This avoids duplicating session-boundary logic that SessionLevels already handles correctly

### Time window gating
- Plugin fires only when `bars_since_session_start` (from I4 SessionContextPlugin) is ≤ 30 bars (first 30 minutes after NY open)
- After 30 bars the gap opportunity has typically resolved — no signal should fire
- If `bars_since_session_start` is unavailable, fall back to `session_ny` flag as coarse check

### Gap thresholds
- Minimum gap size: `0.3 × atr_14` — smaller gaps not worth trading
- Continuation threshold: `1.0 × atr_14` — gaps ≥ this level with confirming volume classify as continuation
- Fade territory: `0.3–1.0 × atr_14` — default bias is fade
- Thresholds are class-level params (`min_gap_atr_mult`, `continuation_atr_mult`) with these defaults — not hardcoded

### Fade vs continuation classification
- **Continuation**: gap size ≥ `continuation_atr_mult × atr_14` AND relative volume ≥ 1.5× recent average (confirming momentum)
- **Fade**: gap in `[min_gap_atr_mult, continuation_atr_mult)` range OR large gap without volume confirmation
- Relative volume from `volume_ratio` feature if available; fallback: compare current bar volume to mean of last 20 bars from df

### Entry type logic
- **`at_limit`**: entered at the current session open price (gap still open, no retrace yet)
- **`at_pullback`**: entered at prior session close level (wait for gap fill attempt, then trade direction)
- Default for fade setups: `at_limit` (fade from current open toward prior close)
- Default for continuation setups: `at_limit` (enter at open, trade away from prior close)
- Claude's discretion: exact pullback offset calculation

### Stop and target levels
- Stop: `1.5 × atr_14` beyond entry in adverse direction (same multiplier as TrendFollowing for consistency)
- Target 1: prior session close level (fade) or `2.0 × atr_14` extension (continuation)
- Target 2: `3.0 × atr_14` extension (continuation) or `0.5 × atr_14` beyond prior close (fade overshoot)
- Claude's discretion: exact target array construction

### Symbol filtering
- InputSpec uses `symbol=".*"` — plugin protocol is always all-symbols; ES/NQ focus is an operational concern
- Claude's discretion: whether to add a configurable `allowed_symbols` set or leave open

### Claude's Discretion
- Exact confidence scoring formula (base suggestion: normalize gap_size/ATR and volume_ratio into 0–1)
- Exact pullback entry offset
- Target array ordering and count
- How to handle `opening_gap_pct = None` (SessionLevels couldn't determine prior close) → return no signal

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SessionLevelsPlugin` outputs `opening_gap_pct`, `prior_session_close`, `overnight_high`, `overnight_low` — consumed as features, no re-implementation needed
- `SessionContextPlugin` outputs `session_ny`, `bars_since_session_start` — use for time gating
- `MeanReversionPlugin` pattern: ATR fallback via `np.mean(high[-14:] - low[-14:])` — reuse for atr_14 guard
- `_no_signal()` pattern used by all I7 plugins — return `{"signal_type": "none", "direction": 0, ...}` or `{}`

### Established Patterns
- I7 plugin dataclass: `name`, `outputs` (frozenset), `inputs` (tuple[InputSpec, ...]), `capability_tags` (frozenset), `min_lookback`, `supports_incremental=False`, `_state: dict`
- `compute_full(frames)` receives `frames["main"]` (DataFrame) and `frames["features"]` (dict of I1–I6 outputs)
- Register via `register_all_plugins()` in `src/intelligence/register_plugins.py`, add to `TIER_I7` constant
- `tests/unit/intelligence/test_i7_registration.py` tracks I7 plugin count — must update count assertion

### Integration Points
- `src/intelligence/trading/gap_analysis_setup.py` — new file (matches path from existing plan)
- `src/intelligence/register_plugins.py` — add `from .trading.gap_analysis_setup import plugin as gap_analysis_setup_plugin`
- `TIER_I7` list: add `"trad_GapAnalysisSetup"`
- Plugin name convention: `trad_GapAnalysisSetup` (matches plan 09-02)

</code_context>

<specifics>
## Specific Ideas

- The `opening_gap_pct` field from SessionLevels is computed at session start — reuse this rather than doing `(open - prior_close) / prior_close` again
- Gap signal should NOT fire if `opening_gap_pct is None` (no prior session history available)
- Roadmap explicitly names ES and NQ but architecture should remain general — the use case focus is documentation/operational, not code-level filtering

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 09-gap-analysis-setup*
*Context gathered: 2026-03-02*
