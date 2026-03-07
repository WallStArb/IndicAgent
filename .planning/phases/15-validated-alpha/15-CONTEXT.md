# Phase 15: Validated Alpha - Context

**Gathered:** 2026-03-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Four new alpha sources (Derivative Oscillator I2, Candlestick Tier 1 ×10, MACD histogram acceleration, AC Oscillator I1) live in production after each passes historical validation — no unvalidated signals fire. Includes building the validation infrastructure (ALPHA-01) that all current and future alpha sources must clear before promotion.

Adding new I7 setups, changing CIS weights, or modifying signal lifecycle are out of scope.

</domain>

<decisions>
## Implementation Decisions

### Validation Gate Thresholds (ALPHA-01)
- **Minimum N gate**: 30 resolved signals with non-null `pnl_r` — matches FEED-02 promotion gate; consistent threshold across the system
- **Correlation gate (hard)**: Pearson r > 0, p < 0.05 — any statistically significant positive correlation with pnl_r passes; p < 0.05 + N ≥ 30 is the Renaissance floor
- **ADF stationarity**: Informational only — reported in output but not a hard gate; trend-following indicators (DerivOsc, MACD accel) are expected to be non-stationary; gating on ADF would incorrectly reject valid momentum signals
- **False-positive rate**: Informational only — FPR = signals fired but never meaningfully activated; threshold is signal-type dependent; report for diagnostic use, set gates per-plugin in a future phase once baselines exist

### Validation Script Design (ALPHA-01)
- **Interface**: CLI with flags — `python production/scripts/validate_alpha.py --plugin <name> --days <N> [--symbol-filter <SYM>] [--promote]`
  - Consistent with existing `historical_backfill.py` and `pipeline_reset.py` patterns
  - Reproducible, scriptable, CI-compatible — the Renaissance reproducibility requirement
- **Output**: File report + terminal summary
  - Writes `docs/validation/YYYY-MM-DD-<plugin>.json` on every run — every pass/fail decision is auditable indefinitely
  - Terminal shows summary: metrics, pass/fail verdict, what would be promoted
  - Git-tracked report files are the audit trail — no DB table needed
- **Promotion flag (`--promote`)**:
  - Without `--promote`: evidence-only mode — runs gates, prints report, exits 0 (pass) or 1 (fail), no code changes
  - With `--promote`: gates must pass (hard block) + auto-patches `register_plugins.py` to add plugin to correct tier list + writes validation report
  - Decision checkpoint: user chooses when to pull the trigger; automation removes the manual hunting through register_plugins.py
  - Service restart required after promotion (consistent with systemd pattern)
- **Hard block**: `--promote` only executes if all hard gates pass; exits non-zero on failure, nothing changes

### Candlestick Tier 1 Extension (ALPHA-03)
- **Plugin structure**: Extend existing `CandlestickPatternsPlugin` — raise `min_lookback=3`, add all 10 patterns to the single plugin; 2-bar patterns still work correctly with 3 bars available; one plugin, one outputs frozenset, one integration point for `CandlestickPatternSetupPlugin` (I7)
- **I7 gating**: All 10 patterns detected at I5 (instruments everything), but **none fire at I7** until the pattern passes ALPHA-01 validation; confidence scores from REQUIREMENTS (0.55–0.72) are prior beliefs, not production gates — empirical validation on our data is the gate
- **Validation priority order**: Validate highest-confidence patterns first — Three White Soldiers / Three Black Crows (0.72), then Morning Star / Evening Star / Three Inside Up/Down (0.65), then Harami Cross / Dark Cloud Cover / Piercing Line (0.55–0.58)
- **Post-validation wiring**: `--promote` patches `register_plugins.py`; for I7, also patches `CandlestickPatternSetupPlugin` to include the promoted pattern in its detection set

### Delivery Sequencing
- **5 plans, ALPHA-01 first**:
  - Plan 1: `validate_alpha.py` script (ALPHA-01) — build the gate before the sources that must clear it
  - Plan 2: Derivative Oscillator I2 (ALPHA-02) — implement + validate + promote if pass
  - Plan 3: Candlestick Tier 1 ×10 (ALPHA-03) — implement all 10 at I5, validate each, wire passing patterns to I7
  - Plan 4: MACD histogram acceleration (ALPHA-04) — implement + validate + promote if pass
  - Plan 5: AC Oscillator I1 (ALPHA-05) — implement + validate + promote if pass
- Each of Plans 2–5 ends with: `validate_alpha.py --plugin X --days 90 --promote`
- Independent failure isolation: a plan failing doesn't block the others

### Claude's Discretion
- Exact format for validation report files (JSON structure, field names)
- How to handle fewer than 30 signals at validation time (report N, exit with informative message)
- Column names and index choices on `signal_ledger` / `intelligence_features` queries
- Exact `--symbol-filter` implementation (comma-separated values)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/intelligence/patterns/candlestick_patterns.py`: `CandlestickPatternsPlugin` — extend directly; `outputs` frozenset, `min_lookback`, `compute_full()` follow established plugin protocol
- `src/intelligence/trading/candlestick_pattern_setup.py`: I7 plugin reading from `CandlestickPatternsPlugin` — promotion wires new patterns into this setup's detection logic
- `src/intelligence/composites/macd_events.py`: `MACDEventsPlugin` — `macd_hist_accel` and `macd_hist_contracting` outputs slot in alongside existing histogram outputs
- `production/scripts/historical_backfill.py` + `pipeline_reset.py`: CLI flag patterns (`--days`, `--symbols`, `--dry-run`) — validation script follows same interface conventions
- `src/intelligence/register_plugins.py`: `TIER_I1`/`TIER_I2`/`TIER_I5`/`TIER_I7` lists — `--promote` patches these; `registry.validate_tier()` hard-crashes on startup if a name is in tier list but import fails

### Established Patterns
- Plugin protocol: `@dataclass`, `name`, `outputs: frozenset[str]`, `min_lookback`, `supports_incremental`, `inputs: tuple[InputSpec]`, `_state: dict`, `compute_full()` + `compute_next()`
- I2 composites read from `features=` dict (I1 outputs already computed) — no raw OHLCV needed; see `macd_events.py`
- I1 indicators read from raw OHLCV DataFrame in `frames["main"]` — see `src/intelligence/indicators/`
- Tier registration: import plugin singleton at top of `register_plugins.py`, add to tier list — single source of truth

### Integration Points
- `intelligence_features` + `signal_ledger`: validation script reads from these via `DatabaseManager`; join on `(symbol, feature_ts, feature_tf)` for pnl_r correlation
- DerivOsc (I2): reads `rsi_14` from features dict — RSI already computed by I1 `RsiPlugin`
- AC Oscillator (I1): midpoint = (high + low) / 2; SMA(5) and SMA(34) on midpoint — pure OHLCV, no upstream dependencies
- MACD hist accel (I2): reads `macd_histogram_12_26_9` from features dict — already computed by I1 `MacdPlugin`

</code_context>

<specifics>
## Specific Ideas

- Jim Simons framing: "earn the right through proof" — empirical validation on our data is the gate, not theoretical confidence scores from prior literature
- "Instrument everything" — I5 detects all 10 candlestick patterns immediately; I7 only fires the ones that have passed validation
- Validation report files in `docs/validation/` are the permanent audit trail: years later, the promotion decision for any alpha source is explainable
- `--promote` flag: automation removes friction, human retains the decision checkpoint — Medallion automated the tedious parts, not the judgement
- ADF + FPR informational only: avoids incorrectly penalizing momentum indicators for non-stationarity; FPR baselines don't exist yet to set meaningful thresholds

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 15-validated-alpha*
*Context gathered: 2026-03-07*
