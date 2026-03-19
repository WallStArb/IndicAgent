# Intelligence Layer Workflow Audit

**Purpose:** Single source of truth for intelligence layer conventions, gotchas, and enforcement gaps.
**Last updated:** 2026-03-19 (Phase 39.1)
**Status:** Updated to reflect Phase 39.1 enforcement additions

---

## Executive Summary

The intelligence layer follows consistent naming conventions with **121 plugins** across tiers I1–I7. Conventions are well-documented in `CLAUDE.md` but required mechanical enforcement. Phase 39.1 adds pre-commit hooks and Protocol/enum enforcement.

**Status after Phase 39.1:**
- Naming conventions: 100% compliant across codebase (verified audit)
- `regime_type` enforcement: Protocol + runtime validation + pre-commit hook (Phase 39.1)
- Signal status strings: `SignalStatus` enum migration complete (Phase 39.1)
- Pre-commit hooks: 4 checks active — class naming, file naming, regime_type, dead imports

---

## Naming Conventions

### Plugin Classes
**Pattern:** `PascalCasePlugin` suffix — e.g., `MACDPlugin`, `BollingerBandsPlugin`, `CHoCHReversalPlugin`
**Why it matters:** Distinguishes plugins from regular classes; pre-commit hook enforces suffix.
**Examples:**
- Correct: `RSIPlugin`, `TrendFollowingPlugin`, `CrossAssetDivergencePlugin`
- Wrong: `RSI`, `TrendFollowing`, `CrossAssetDivergence` (missing `Plugin` suffix)

**Enforcement:** Pre-commit hook blocks commits on classes not ending in `Plugin` (excludes Test/Data/Protocol/Enum classes).

### Plugin Files
**Pattern:** `snake_case.py` — e.g., `bollinger_bands.py`, `rsi.py`, `choch_reversal.py`
**Why it matters:** Consistent module naming; avoids case-sensitivity issues across OS.
**Examples:**
- Correct: `momentum_acceleration.py`, `candlestick_pattern_setup.py`
- Wrong: `MomentumAcceleration.py`, `CandlestickPatternSetup.py`

**Enforcement:** Pre-commit hook blocks commits on files not matching `^[a-z][a-z0-9_]*\.py$`.

### Service Files
**Pattern:** `snake_case_service.py` — e.g., `signal_generator_service.py`, `market_analysis_service.py`

### Constants
**Pattern:** `UPPER_SNAKE_CASE` — e.g., `TIER_I7`, `WIN_OUTCOMES`, `TREND_SETUPS`

### Database Tables/Columns
**Pattern:** `snake_case` — e.g., `signal_ledger`, `cis_score`, `regime_suppressed`

### Redpanda Topics
**Pattern:** Dots not colons — `development.indicators`, `development.cross_asset`
**Gotcha:** Legacy `dev.*` prefix exists; use `development.*` for new topics. Always via `stream_keys.py`.

### Tier Distribution (v1.9)

```
TIER_I1:  27 indicators
TIER_I2:  11 composites
TIER_I3:   7 structure
TIER_I4:  11 context
TIER_I5:  15 patterns
TIER_I6:  14 SMC (13) + confluence (1)
TIER_I7:  36 trading setups
Total:   121 plugins + 2 aggregation = 123
```

**Naming compliance:** All 121 plugin files use `snake_case.py`; all plugin classes use `PascalCasePlugin`.

---

## Gotchas Catalog

All gotchas from CLAUDE.md consolidated here with remediation steps.

### TimescaleDB Gotchas

**1. Column naming: `ts` not `feature_ts`**
- **Issue:** `intelligence_features` uses `ts` as timestamp column, not `feature_ts`
- **Impact:** Queries using `feature_ts` return NULL or wrong data
- **Fix:** Always use `ts` in queries against `intelligence_features`; `feature_ts` is a JOIN key in `signal_ledger`

**2. Topic prefixes: `development.*` vs `dev.*`**
- **Issue:** Legacy topics use `dev.*`; current code uses `development.*`
- **Impact:** Subscribing to wrong prefix = no messages
- **Fix:** Always use `topic_*()` helpers from `src/core/stream_keys.py`

**3. Hypertable parent `pg_class` size is near-zero**
- **Issue:** `SELECT pg_size_pretty(pg_relation_size('intelligence_features'))` returns ~0 bytes
- **Reason:** Size is distributed across chunks, not parent table
- **Fix:** Use `hypertable_size('table_name')` or query `timescaledb_information.chunks`

**4. `pg_stat_user_indexes.idx_scan` is always 0 for hypertable parents**
- **Issue:** Index usage stats tracked at chunk level, not parent
- **Reason:** Hypertables are chunk partitioned
- **Fix:** Use `pg_stat_statements` and `EXPLAIN ANALYZE` instead

**5. Autovacuum on hypertables**
- **Issue:** `ALTER TABLE hypertable SET (autovacuum_...)` only applies to new chunks
- **Reason:** Existing chunks already have their own settings
- **Fix:** Iterate `timescaledb_information.chunks` and apply to each chunk:
  ```sql
  DO $$
  DECLARE r record;
  BEGIN
    FOR r IN SELECT chunk_schema, chunk_name FROM timescaledb_information.chunks
    WHERE hypertable_name = 'intelligence_features'
    LOOP
      EXECUTE format('ALTER TABLE %I.%I SET (autovacuum_vacuum_scale_factor = 0.1)',
                     r.chunk_schema, r.chunk_name);
    END LOOP;
  END $$;
  ```

**6. `docker exec ... -f /dev/stdin` does NOT work**
- **Issue:** Heredoc SQL via `docker exec` fails silently
- **Reason:** `/dev/stdin` redirection doesn't work across Docker exec boundary
- **Fix:** Copy file to container, then execute:
  ```bash
  docker cp file.sql timescaledb:/tmp/file.sql
  docker exec timescaledb psql -U postgres -d indicagent -f /tmp/file.sql
  ```

**7. `instruments.symbol` is base symbol**
- **Issue:** DB `symbol` column stores base (e.g., `PL`, `SOL`, `ES`)
- **Gotcha:** Contract code is in `contract_details->>'symbol'` JSONB field
- **Fix:** Query `symbol` for base, `json.loads(contract_details)['symbol']` for contract code

**8. `instruments.contract_details` is stored as JSON string**
- **Issue:** Column is `jsonb` type but stores a serialized string value
- **Symptom:** `contract_details->>'field'` returns NULL
- **Fix:** Use `(contract_details #>> '{}')::jsonb->>'field'` or Python `json.loads()`

**9. Boolean serialization changed with Redpanda migration**
- **Issue:** Redis streams serialized as `"1"`/`"0"`, Redpanda may use `true`/`false`
- **Impact:** Dashboard boolean parsing breaks
- **Fix:** Verify current format in `use-market-stream.ts` — may need `Number(payload.field) > 0` or `payload.field === true`

**10. Service test `__new__` pattern**
- **Issue:** Tests use `ServiceClass.__new__(ServiceClass)` to bypass `__init__`
- **Gotcha:** New instance attrs in `__init__` must also be manually set in test
- **Example:** `svc._regime_cache = defaultdict(dict)` after `__new__` call
- **Reason:** `__init__` is bypassed, attrs are not initialized

### Signal Ledger Gotchas

**11. `signal_id` UUID threading through pipeline**
- **Issue:** Signal UUID must be passed from generator → lifecycle → DB
- **Impact:** Wrong UUID joins to wrong signal_features rows
- **Fix:** Always thread `signal_id` through all pipeline stages

**12. `aggregator active` must come from `all_ranked`**
- **Issue:** Deriving `active` from raw `signals` bypasses `perf_weights`
- **Impact:** Performance multipliers have zero effect on winner selection
- **Fix:** Always derive `active = [s for s in all_ranked if s.get("regime_eligible", True)]`

**13. `Chandelier trailing stop` monotonic tightening**
- **Issue:** Stop only tightens, never widens
- **Logic:** Long: `max(highest_high_since_entry - 3×ATR, current_stop)`
- **State:** Tracked in `_chandelier_state[sid]` dict per signal

**14. `regime_type` on I7 plugins (FIXED in Phase 39.1)**
- **Issue:** Missing `regime_type` causes silent misfire
- **Impact:** Trend plugins suppressed in ranging, mean-reversion suppressed in trending
- **Fix:** Phase 39.1 adds Protocol enforcement + runtime validation + pre-commit hook

**15. Signal status strings (FIXED in Phase 39.1)**
- **Issue:** Raw strings across multiple files = typo risk
- **Fix:** Phase 39.1 replaces with `SignalStatus` enum in `signal_ledger.py`

### Plugin Pipeline Gotchas

**16. Plugin state write-back is load-bearing**
- **Issue:** GARCH/HMM plugins fully reassign `_state` dict
- **Gotcha:** Forgetting to write back causes stale results
- **Fix:** Always `plugin._state = new_state` after `compute_full()`

**17. `market_data_ohlcv` is backfill-only**
- **Issue:** Live data never touches this table
- **Reason:** Redpanda streams are the real-time pipeline
- **Fix:** Use `intelligence_features` for live data queries; consume from Redpanda for real-time

**18. Mock `isinstance()` gotcha in tests**
- **Issue:** `isinstance(val, (int, float))` fails for MagicMock (truthy but not numeric)
- **Impact:** Tests that check `if val` pass but `isinstance` checks fail silently
- **Fix:** Use `isinstance(val, (int, float))` not `if val` — MagicMock is truthy, `float(MagicMock())` returns 1.0

---

## Enforcement Status

### What's Enforced After Phase 39.1

| Check | Mechanism | What it catches |
|-------|-----------|-----------------|
| Plugin registration | `registry.validate_tier()` | Missing/unregistered plugins in tier lists |
| Protocol compliance | `IndicatorPlugin` / `PatternPlugin` Protocol | Missing required ClassVar attributes |
| `regime_type` existence | `PatternPlugin` Protocol field | Missing `regime_type` on any plugin |
| `regime_type` values | `validate_tier()` I7 runtime check | Invalid values (not trend/mean_reversion/any) |
| Signal status | `SignalStatus` enum | Typos in status strings, missing statuses |
| Schema coverage | `validate_schema_coverage()` | Plugin outputs not declared in tier schemas |
| Asset class filters | `valid_asset_classes` ClassVar | Wrong asset class combinations |
| Plugin class naming | Pre-commit hook (Check 1) | Classes not ending with `Plugin` suffix |
| Plugin file naming | Pre-commit hook (Check 2) | Files not using `snake_case.py` |
| I7 regime_type | Pre-commit hook (Check 3) | Missing `regime_type` in commit |
| Dead imports | Pre-commit hook (Check 4) | Unused imports via ruff F401 |
| Code formatting | Ruff + Black | Style violations |

### What's NOT Enforced (Future Work)

| Convention | Gap | Risk | Phase |
|------------|-----|------|-------|
| Type safety | No mypy/pyright | Type drift at runtime | Phase 40+ |
| Test coverage | No coverage gate | New code without tests | Phase 40+ |
| Secret scanning | No credential detection | API keys in commits | Phase 40+ |
| Complexity limits | No cyclomatic threshold | Unmaintainable functions | Phase 40+ |
| Plugin documentation | No docstring gate | Missing public API docs | Phase 40+ |

---

## Plugin Checklist

For new I7 plugins, use this checklist before committing:

### Declaration
- [ ] Class extends `PatternPlugin` Protocol
- [ ] `name: ClassVar[str]` declared
- [ ] `regime_type: ClassVar[str]` with value in `["trend", "mean_reversion", "any"]`
- [ ] `outputs: ClassVar[set[str]]` declared
- [ ] `inputs: ClassVar[list[InputSpec]]` declared
- [ ] `valid_asset_classes: ClassVar[frozenset[AssetClass]]` declared

### File Structure
- [ ] File uses `snake_case.py` naming (e.g., `my_new_setup.py`)
- [ ] Class uses `PascalCasePlugin` naming (e.g., `MyNewSetupPlugin`)
- [ ] File in correct directory: `src/intelligence/trading/` (I7)

### Registration
- [ ] Added to `TIER_I7` in `src/intelligence/register_plugins.py`
- [ ] Added to appropriate setup list (`TREND_SETUPS`, `MEAN_REVERSION_SETUPS`, or both)

### Testing
- [ ] Unit test covers `compute_full()` returns expected output
- [ ] Unit test verifies `regime_type` is correct
- [ ] Integration test: plugin fires in replay over 1-week window on ES/NQ 1m

### Documentation
- [ ] Class docstring explains setup logic, parameters, edge cases

---

## Pre-commit Hook Reference

**Location:** `.git/hooks/pre-commit`
**Scope:** All commits to this repository
**Execution time:** < 2 seconds typical (3-5 files changed)
**Log:** `.git/hooks/pre-commit.log` (all runs with timestamps)

### Check 1: Plugin Class Naming
- **Scope:** `src/intelligence/**/*.py`
- **Rule:** All classes starting with uppercase must end in `Plugin` suffix
- **Exclusions:** `Test`, `Data`, `Protocol`, `Enum`, `Error`, `Exception`, `Config`, `Result`, `State`, `Score`, `Frame`, `Entry`, `Event`, `Spec`, `Type`, `Info`, `Registry`, `Manager`, `Builder`, `Handler`, `Tracker`, `Scorer`, `Aggregat`
- **Remediation:** Rename class to `MyThingPlugin`

### Check 2: Plugin File Naming
- **Scope:** `src/intelligence/**/*.py` new/modified files
- **Rule:** Filenames must match `^[a-z][a-z0-9_]*\.py$`
- **Exclusions:** `__init__.py`, `conftest.py`
- **Remediation:** Rename file to `my_thing.py`

### Check 3: I7 regime_type
- **Scope:** `src/intelligence/trading/*.py` new/modified files (plugin files only)
- **Rule:** Any file defining a `*Plugin` class must contain `regime_type` declaration
- **Exclusions:** Infrastructure files: `signal_ledger.py`, `lifecycle_tracker.py`, `trade_framer.py`, `signal_aggregator.py`, `cis_scorer.py`, `weight_updater.py`, `confidence_calibrator.py`
- **Remediation:** Add `regime_type: ClassVar[str] = "trend"` (or `"mean_reversion"` or `"any"`)

### Check 4: Dead Imports
- **Scope:** All Python files in commit
- **Tool:** `ruff check --select F401`
- **Remediation:** Remove unused imports or add `# noqa: F401` for intentional re-exports

---

## Compliance Metrics

Hook pass/fail tracked in `.git/hooks/pre-commit.log`. Each run includes timestamp, all check results, and pass/fail status.

### Hook Execution Time
- **Target:** All hooks complete in < 2 seconds on typical commit (3-5 files changed)
- **Verified:** Execution in < 1 second on typical commits (grep-based checks)

### Most Common Violations (Historical)
1. Missing `Plugin` suffix on class names
2. Dead imports from refactoring
3. Missing `regime_type` on new I7 plugins

---

## Exception Log

**Policy:** Strict blocking means no exceptions. This section exists for future transparency if policy changes.

*Initial state: No exceptions recorded.*

---

## Technical Debt Ledger

**Policy:** Renaissance-grade enforcement means no shortcuts. This section exists for future tracking if needed.

*Initial state: No technical debt recorded.*

---

## Live Data Architecture Clarification

### `market_data_ohlcv` is Backfill-Only

```
IBKR TWS → Redpanda Streams → Services              (sub-ms, hot)
           → indicator/analysis/signal pipeline      (<10ms, warm)
           → feature_writer_service → TimescaleDB   (batch, cold)

market_data_ohlcv: BACKFILL ONLY (historical seed data, never live)
intelligence_features: ML training dataset (feature vectors per bar)
signal_ledger: Trading signals + lifecycle outcomes
```

Live data query pattern:
- Wrong: `SELECT * FROM market_data_ohlcv WHERE timestamp > NOW() - INTERVAL '1 hour'`
- Correct: Consume from `development.market.bars` Redpanda topic

---

## Appendix: Enforcement Toolchain

| Tool | Purpose | Scope | Status |
|------|---------|-------|--------|
| `registry.validate_tier()` | Plugin registration | Startup | Active |
| `validate_schema_coverage()` | Schema field validation | Startup | Active |
| `PatternPlugin` Protocol | ClassVar attribute enforcement | Import | Active (Phase 39.1) |
| `SignalStatus` enum | Status string safety | Runtime | Active (Phase 39.1) |
| Pre-commit hook (4 checks) | Git workflow enforcement | Pre-commit | Active (Phase 39.1) |
| Ruff + Black | Code formatting | All Python | Active |
| pytest | Unit tests | `tests/unit/` | Active |

---

## Related Documentation

- `CLAUDE.md` — Development standards, naming conventions, all system gotchas
- `src/intelligence/CLAUDE.md` — Intelligence layer tier reference, plugin protocol, troubleshooting
- `src/intelligence/plugins.py` — `PatternPlugin` Protocol definition

---

**Document version:** 2.0
**Last updated:** 2026-03-19 (Phase 39.1 — enforcement added)
**Next review:** After Phase 40 (type safety + test coverage gates)
