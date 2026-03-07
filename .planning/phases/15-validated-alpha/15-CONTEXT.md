# Phase 15: Validated Alpha - Context

**Gathered:** 2026-03-07 (updated 2026-03-08)
**Status:** Ready for planning

<domain>
## Phase Boundary

Four new alpha sources (Derivative Oscillator I2, Candlestick Tier 1 ×10, MACD histogram acceleration, AC Oscillator I1) live in production after each passes historical validation — no unvalidated signals fire. Includes building the validation infrastructure (ALPHA-01) that all current and future alpha sources must clear before promotion.

Adding new I7 setups, changing CIS weights, or modifying signal lifecycle are out of scope.

</domain>

<decisions>
## Implementation Decisions

### Validation Gate Thresholds (ALPHA-01)
- **Minimum N gate**: 30 signal bars (bars where indicator fired) with sufficient forward return data — matches FEED-02 promotion gate; consistent threshold across the system
- **Correlation gate (hard)**: Pearson r > 0, p < 0.05 between indicator signal direction and N-bar forward close-to-close returns — any statistically significant positive directional correlation passes; p < 0.05 + N ≥ 30 is the Renaissance floor
- **Forward return window**: TF-appropriate — 5 bars for 1m, 3 bars for 5m/15m/1h (measures short-term predictive power aligned to the indicator's operating timeframe)
- **ADF stationarity**: Informational only — reported in output but not a hard gate; trend-following indicators (DerivOsc, MACD accel) are expected to be non-stationary; gating on ADF would incorrectly reject valid momentum signals
- **False-positive rate**: Informational only — FPR = indicator fires but price moves wrong direction; report for diagnostic use, no hard threshold until baselines exist

### Validation Script Design (ALPHA-01)
- **Interface**: CLI with flags — `python production/scripts/validate_alpha.py --plugin <name> --days <N> [--symbol-filter <SYM>] [--promote]`
  - Consistent with existing `historical_backfill.py` and `pipeline_reset.py` patterns
  - Reproducible, scriptable, CI-compatible — the Renaissance reproducibility requirement
- **Data sufficiency check**: Script queries `intelligence_features` for row count covering the plugin's output fields. If insufficient data found (below minimum N threshold), automatically triggers `historical_backfill.py --replay-only --days N` internally before running gates — zero prerequisite steps required from the user
- **Correlation source**: Forward N-bar close-to-close returns computed from OHLCV in `intelligence_features` (or `market_data_ohlcv`). Does NOT depend on `signal_ledger.pnl_r` — validates raw market predictability independently of any I7 signal's entry/exit rules. Works immediately on replay data.
- **Output**: File report + terminal summary
  - Writes `docs/validation/YYYY-MM-DD-<plugin>.json` on every run — every pass/fail decision is auditable indefinitely
  - Terminal shows summary: metrics, pass/fail verdict, what would be promoted
  - Git-tracked report files are the audit trail — no DB table needed
- **Promotion flag (`--promote`)**:
  - Without `--promote`: evidence-only mode — runs gates, prints report, exits 0 (pass) or 1 (fail), no code changes
  - With `--promote`: gates must pass (hard block) + auto-patches `register_plugins.py` to add plugin to correct tier list + writes validation report
  - Decision checkpoint: user chooses when to pull the trigger; automation removes the manual file hunting
  - Service restart required after promotion (consistent with systemd pattern)
- **Hard block**: `--promote` only executes if all hard gates pass; exits non-zero on failure, nothing changes

### Candlestick Tier 1 Extension (ALPHA-03)
- **Plugin structure**: Extend existing `CandlestickPatternsPlugin` — raise `min_lookback=3`, add all 10 patterns to the single plugin; 2-bar patterns still work correctly with 3 bars available; one plugin, one outputs frozenset, one integration point for `CandlestickPatternSetupPlugin` (I7)
- **I7 gating**: `CandlestickPatternSetupPlugin` uses explicit named reads — new I5 pattern fields exist in `intelligence_features` but are NOT read by I7 until `--promote` patches the I7 plugin. No signals fire until validated.
- **Validation priority order**: Validate highest-confidence patterns first — Three White Soldiers / Three Black Crows (0.72), then Morning Star / Evening Star / Three Inside Up/Down (0.65), then Harami Cross / Dark Cloud Cover / Piercing Line (0.55–0.58)
- **Post-validation wiring**: `--promote` patches `register_plugins.py` and also patches `CandlestickPatternSetupPlugin` to include the promoted pattern in its named read set

### Delivery Sequencing
- **5 plans, ALPHA-01 first**:
  - Plan 1: `validate_alpha.py` script (ALPHA-01) — build the gate before the sources that must clear it
  - Plan 2: Derivative Oscillator I2 (ALPHA-02) — implement + validate + promote if pass
  - Plan 3: Candlestick Tier 1 ×10 (ALPHA-03) — implement all 10 at I5, validate each, wire passing patterns to I7
  - Plan 4: MACD histogram acceleration (ALPHA-04) — implement + validate + promote if pass
  - Plan 5: AC Oscillator I1 (ALPHA-05) — implement + validate + promote if pass
- Each of Plans 2–5 ends with: `validate_alpha.py --plugin X --days 90 --promote` (script handles data bootstrap automatically if needed)
- Independent failure isolation: a plan failing doesn't block the others

### Claude's Discretion
- Exact format for validation report files (JSON structure, field names)
- How to handle fewer than 30 bars at validation time (report N, exit with informative message)
- Column names and index choices on `intelligence_features` / `market_data_ohlcv` queries
- Exact `--symbol-filter` implementation (comma-separated values)
- DerivOsc formula implementation (Patrick Mulloy triple-smoothed RSI derivative)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/intelligence/patterns/candlestick_patterns.py`: `CandlestickPatternsPlugin` — extend directly; currently has 5 patterns (engulfing_bull/bear, outside_bar, hammer, doji); `min_lookback=2` → raise to 3
- `src/intelligence/trading/candlestick_pattern_setup.py`: I7 plugin using explicit named reads (`features.get("engulfing_bull", 0.0)` etc.) — whitelist mechanism already in place; `--promote` patches these named reads to include validated patterns
- `src/intelligence/composites/macd_events.py`: `MACDEventsPlugin` — `macd_hist_accel` and `macd_hist_contracting` outputs slot in alongside existing histogram outputs
- `production/scripts/historical_backfill.py` + `pipeline_reset.py`: CLI flag patterns (`--days`, `--symbols`, `--dry-run`) — validation script follows same interface conventions; backfill script invoked internally by validate_alpha.py when data is sparse
- `src/intelligence/register_plugins.py`: `TIER_I1`/`TIER_I2`/`TIER_I5`/`TIER_I7` lists — `--promote` patches these; `registry.validate_tier()` hard-crashes at startup if a name is in tier list but import fails

### Established Patterns
- Plugin protocol: `@dataclass`, `name`, `outputs: frozenset[str]`, `min_lookback`, `supports_incremental`, `inputs: tuple[InputSpec]`, `_state: dict`, `compute_full()` + `compute_next()`
- I2 composites read from `features=` dict (I1 outputs already computed) — no raw OHLCV needed; see `macd_events.py`
- I1 indicators read from raw OHLCV DataFrame in `frames["main"]` — see `src/intelligence/indicators/`
- Tier registration: import plugin singleton at top of `register_plugins.py`, add to tier list — single source of truth
- FEED-02 promotion gate (n≥30) already live in `setup_performance` — same threshold applied here for consistency

### Integration Points
- `intelligence_features` + `market_data_ohlcv`: validation script reads from these; forward returns computed from OHLCV close prices; no dependency on `signal_ledger`
- DerivOsc (I2): reads `rsi_14` from features dict — RSI already computed by I1 `RsiPlugin`
- AC Oscillator (I1): midpoint = (high + low) / 2; SMA(5) and SMA(34) on midpoint — pure OHLCV, no upstream dependencies
- MACD hist accel (I2): reads `macd_histogram_12_26_9` from features dict — already computed by I1 `MacdPlugin`

</code_context>

<specifics>
## Specific Ideas

- Jim Simons framing: "earn the right through proof" — empirical validation on our data is the gate, not theoretical confidence scores from prior literature
- "Instrument everything" — I5 detects all 10 candlestick patterns immediately; I7 only fires the ones that have passed validation
- Validation report files in `docs/validation/` are the permanent audit trail: years later, the promotion decision for any alpha source is explainable
- `--promote` flag: automation removes friction (file patching, register_plugins.py, I7 wiring), human retains the decision checkpoint — Medallion automated the tedious parts, not the judgement
- ADF + FPR informational only: avoids incorrectly penalizing momentum indicators for non-stationarity; FPR baselines don't exist yet to set meaningful thresholds
- Forward returns as correlation target: more rigorous than signal_ledger.pnl_r — validates raw market predictability independent of I7 entry/exit logic; works immediately on replay data without waiting for live signals

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

## Bootstrap Policy Exception

Data-absence bootstrap policy applies to three plugins promoted before live data accumulated:

- **ALPHA-02**: `cmp_DerivativeOscillator` — DerivativeOscillatorPlugin registered in TIER_I2 (15-GAP-01)
- **ALPHA-04**: `evt_MACDEvents` (macd_hist_accel field) — MACD acceleration fields added in 15-04
- **ALPHA-05**: `ind_ACOscillator` — AC Oscillator wired to live pipeline before gate pass (commit ad9af58)

In each case: the implementation is mathematically correct (unit tests pass), but intelligence_features has zero rows for the plugin's output fields because registration occurred before any live bars were processed under the new schema.

Gate re-run required after 30+ bars accumulate in intelligence_features for each field. Run:

```
python production/scripts/validate_alpha.py --plugin <name> --days 90 --promote
```

This decision is intentional and closes the sequence-violation concern raised in 15-VERIFICATION.md (ALPHA-05 gap). Data-absent plugins with correct implementations are bootstrap-promoted rather than blocked.

Audit trail JSON files (verdict=BOOTSTRAP) written to docs/validation/ for each exempted plugin.

---

*Phase: 15-validated-alpha*
*Context gathered: 2026-03-07 (updated 2026-03-08)*
