# Phase 132: Stop-Zone Geometry + APR Migration — Context

**Gathered:** 2026-06-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix stop placement geometry (A2/A3) so stops are measured from actual entry price, not zone edge. Migrate all hardcoded numeric constants in `trade_framer.py` to APR (the todo table has ~16 named rows; count actual APR keys by reading the adaptive buffer function before writing SQL). Verify `stopped_at_entry` outcome rate is <5% on a 1-month sample replay + lifecycle_replay.

**Verification gate:** 1-month sample replay followed by `lifecycle_replay.py` on the same date range shows `stopped_at_entry` exit_reason <5% of all stop exits in `trade_executions`; all APR keys visible in `/config/parameters` dashboard with correct seed values; APR-backed code produces identical signals to prior constants at seed values (regression test). Note: `stopped_at_entry` is written by lifecycle_replay.py as the exit_reason — it does not appear in trade_executions until lifecycle_replay runs. The verification query is only valid after both scripts complete.

</domain>

<decisions>
## Implementation Decisions

### D-01: A2 stop geometry — measure first, then fix remaining gaps

**Phase 126 (commit 6fe15543) already implemented:** zone width rejection gate in `trade_framer.py` (line 1052-1077) and stop distance floor at `feature.zone_engine.min_stop_distance_atr` = 0.5 ATR (line 1099-1110). The 25% stopped_at_entry rate cited in the todo predates Phase 126.

**First task:** Run a 2-week sample replay + lifecycle_replay and measure the current stopped_at_entry rate. If already <5%, A2 is closed; remaining work is A3 + A5. If still elevated, implement the remaining gaps:

**(a) zone_engine fast-path bypass:** Confirm whether any zone generation path in `zone_engine.py` produces zones narrower than `min_zone_width_atr * atr` without hitting the trade_framer rejection gate. If yes, add a defensive assertion at zone_engine output. This is a defensive hardening, not a missing gate — trade_framer already rejects narrow zones.

**(b) Stop distance floor increase:** Handled by the A5 APR migration of `MIN_STOP_ATR_MULTIPLIER` → `feature.trade_framer.min_stop_atr` at seed value 1.0 ATR. This raises the floor from 0.5 ATR (zone_engine gate) to 1.0 ATR (trade_framer gate). No separate code change needed for this item.

The sample data in `.planning/todos/pending/2026-06-14-review-stop-zone-logic.md` reflects pre-Phase-126 state. Do not re-implement the zone width gate or stop distance floor — they exist at `trade_framer.py:1052-1110`.

### D-02: A3 per-asset-class stop geometry — empirical seed values from intelligence_features

Four per-asset-class APR keys for minimum stop floor. Seed values must be computed empirically, not guessed. **ATR source matters:** use `intelligence_features.technical_indicators->>'atr'` (the I1 indicator ATR, ~14-bar smoothed), not OHLCV bar ranges. trade_framer.py calls `get_atr(features)` which reads the I1 indicator ATR — if seed values are computed from raw OHLCV, they will be inconsistent with runtime ATR values.

**Query:** `SELECT symbol, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY (technical_indicators->>'atr')::float) AS median_atr FROM intelligence_features WHERE technical_indicators->>'atr' IS NOT NULL GROUP BY symbol` — then group symbols by asset class and divide by tick_size per instrument.

Four per-asset-class APR keys for minimum stop floor:

| APR key | Asset class | Instruments |
|---------|-------------|-------------|
| `feature.trade_framer.stop_multiplier_floor.fx` | FX | EURUSD, GBPUSD, USDCHF, USDJPY |
| `feature.trade_framer.stop_multiplier_floor.commodity_small_tick` | Commodities | SI, NG, HG, CL |
| `feature.trade_framer.stop_multiplier_floor.equity_etf` | Equity/ETF | QQQ, SPY, IWM, XLE, SMH, all ETFs |
| `feature.trade_framer.stop_multiplier_floor.futures_large_tick` | Index futures | ES, NQ, YM, RTY |

The 1-tick gate (`stop <= entry + 1 tick`) is correct and must remain — the per-asset-class floor sits above it.

**Planner responsibility:** Query `market_data_ohlcv` to compute median ATR per asset class, then derive the seed values before writing the migration. This is data work, not a judgment call.

### D-03: A5 APR migration — count actual keys before writing SQL

Full constant table is in `.planning/todos/pending/2026-06-14-trade-framer-apr-migration.md`. The table has 16 named rows, but the last row ("Adaptive buffer piecewise coefficients: 0.80, 0.70, 0.20/0.30, 0.35/0.50, 0.16") covers multiple distinct values. Before writing any migration SQL, read the adaptive buffer function in `trade_framer.py` and count the actual number of APR keys required — each distinct configurable value gets its own key. Migrate all of them. Per-constant process:
1. INSERT into `config_schema` + `config_state` in a migration
2. Load via `ConfigService.get()` at init (pattern: `_config_service` field, `get_sync()` wrapper)
3. Remove the module-level constant
4. Add `[initial_estimate]` provenance tag in `config_schema.description`
5. Flag ML learning targets in description

No hardcoded numeric thresholds, weights, or multipliers remain in `trade_framer.py` after this phase.

### D-04: Seed value computation is a first-task prerequisite

Before writing any APR migration SQL, the planner/executor must query the DB to compute actual `median_ATR / tick_size` values per asset class. These become the seed values for A3 keys. Do not use round-number guesses.

### Claude's Discretion

- Whether to combine A2 + A3 fixes in one plan or separate — prefer separate: A2 first (universally applicable stop geometry), A3 second (asset-class extensions); cleaner regression test boundary
- Migration file numbering — use next available after Phase 131 migrations (check `ls production/migrations/` at plan time)
- Regression test design — run 1-month sample replay with seed values and compare signal count + `stopped_at_entry` rate to pre-fix baseline; pass criterion is <5% rate

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary Spec
- `docs/plans/2026-06-17-phases-131-133-signal-corpus-integrity.md` §"Phase 132" — A2 three-part fix, A3 per-asset-class keys, A5 full constant table reference

### Constant Table (read before writing migration)
- `.planning/todos/pending/2026-06-14-trade-framer-apr-migration.md` — A5 full constant table with APR keys and ML-target flags

### Stop Geometry Source Data
- `.planning/todos/pending/2026-06-14-review-stop-zone-logic.md` — A2 sample data (QQQ entry/zone mismatch); confirms current bug

### APR Standards
- `docs/foundation/adaptive-parameter-registry.md` — APR mandate, namespace conventions, migrate-as-you-go rule
- `docs/foundation/parameter-store.md` — parameter lifecycle, provenance tags, ML learning target flags
- `src/config/config_service.py:39` — OPS_PREFIXES (verify `feature.*` is already in list before adding new keys)

### Key Code Files
- `src/intelligence/trading/trade_framer.py` — primary target; all 16 constants + stop geometry logic
- `src/intelligence/trading/zone_engine.py` — min zone width enforcement; fast-path bypass is the A2(a) bug location

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Existing `ConfigService.get_sync()` pattern — already used by other plugins; apply same pattern for `_config_service` field in `trade_framer.py` dataclass
- `_prewarm_threshold_config()` in `intelligence_pipeline.py` — registration point for new `trade_framer` config service injection; follow same pattern as other registered plugins

### Established Patterns
- APR dataclass field pattern: `_config_service: Any = field(default=None, compare=False, repr=False)`, read via `cfg.get_sync(key, fallback) if cfg else fallback`
- Per-constant migration format: one INSERT into `config_schema` (metadata) + one INSERT into `config_state` (value) per APR key

### Integration Points
- `trade_framer.py` loads asset class from `all_features["asset_class"]` — which is fixed by Phase 131 A4. Phase 132 must run AFTER Phase 131 to correctly route per-asset-class stop floors.

</code_context>

<specifics>
## Specific Ideas

- The 1-tick gate must survive — it's a correctness floor, not a tunable preference. Only the ATR multiplier floor goes into APR.
- Regression test: run `SELECT exit_reason, COUNT(*) FROM trade_executions GROUP BY 1` after 1-month sample replay to measure `stopped_at_entry` rate.

</specifics>

<deferred>
## Deferred Ideas

- FX-specific plugin parameter tuning (min_agreeing, session context) — future phase; EURUSD excluded from corpus until then
- ML learning on stop ATR multiplier — v2.11 after corpus is populated with `counterfactual_pnl_r`

</deferred>

---

*Phase: 132-stop-zone-geometry-apr-migration*
*Context gathered: 2026-06-17*
