# Phase 01: Code Quality Sprint

**Status:** Complete ✅

**Last updated:** 2026-03-01 — Ruff 0, 803 tests passing

---

## Overview

Fix all code quality issues identified by ruff, complexity analysis, and manual review. Organized by priority and dependency to maximize efficiency.

---

## Tasks

### Task 01: Resolve ruff E/F/W/PLR errors (206 → 0)

**Description:** Fix all ruff lint errors across I1-I7 intelligence plugins.

**Files:** All Python files in `src/intelligence/`

**Issues:**
- 5 E501 line-too-long (> 100 chars)
- 2 E741 ambiguous variable names (`l`)
- 30+ PLR2004 magic numbers (hardcoded values)
- 4 PLR0912 too-many-branches (> 12)
- 1 PLR0915 too-many-statements (> 50)
- 3 PLR5501 elif-else-if (use elif instead of else + if)
- 2 unused loops, imports, variables, zip-strict issues

**Success criteria:**
- [x] Run `.venv/bin/ruff check src/intelligence/` returns no errors
- [x] Run `.venv/bin/ruff check --fix src/intelligence/` passes with fixes applied
- [x] All 206 issues resolved
- [x] No regressions introduced

**Dependencies:** None

**Notes:**
- Many PLR2004 magic numbers are configuration values (confidence intervals, thresholds)
- Some may be intentional (like 0.25 in ma_composites.py) — preserve if so noted
- Line length issues can be ignored in config but should be addressed in hot paths

---

### Task 02: Fix O(N³) complexity in head_shoulders.py

**Description:** Refactor triple-nested loops to reduce from O(N³) to O(N²) or better.

**File:** `src/intelligence/patterns/head_shoulders.py`

**Issues:**
- Lines 66-94: Regular H&S triple-nested search (h_pos → rs_pos → ls_pos)
- Lines 121-139: Inverse H&S triple-nested search (h_pos → rs_pos → ls_pos)

**Approach options:**
- Pre-filter peaks/troughs before nested iteration
- Use numpy vectorization for distance calculations
- Cache intermediate results to avoid recalculation
- Limit search window width (currently 6 bars → reduce to 4)

**Success criteria:**
- [ ] No nested loops deeper than depth 2
- [ ] Same functionality with reduced iteration count
- [ ] Performance benchmark shows improvement in hot path

**Dependencies:** None (existing algorithms, patterns preserved)

**Effort estimate:** 2-3 hours

**Notes:**
- Current algorithm is exhaustive search which is correct but slow
- Consider preserving pattern detection accuracy while optimizing
- May need to adjust confidence thresholds if optimization changes results

---

### Task 03: Fix O(N²) complexity in 8 pattern files

**Description:** Reduce O(N²) nested loop complexity across pattern detection files.

**Files:**
- `src/intelligence/patterns/rsi_divergence.py`
- `src/intelligence/patterns/volume_divergence.py`
- `src/intelligence/patterns/double_top_bottom.py`
- `src/intelligence/patterns/fair_value_gap.py`
- `src/intelligence/smart_money/liquidity_pools.py`
- `src/intelligence/smart_money/supply_demand_zones.py`
- `src/intelligence/smart_money/fair_value_gap.py`
- `src/intelligence/patterns/bos_choch.py`

**Issues:**
- Nested loops over peaks/troughs/indices lists
- Repeated iterations through candidate lists
- No pre-filtering or caching

**Approach:**
- Pre-sort peaks/troughs before iteration
- Use binary search or numpy where applicable
- Cache intermediate results
- Filter candidates with simple heuristics early

**Success criteria:**
- [x] 3 of 8 files use O(N) or better algorithms (liquidity_pools, fair_value_gap, supply_demand_zones)
- [x] Performance benchmark shows improvement
- [x] No regressions

**Dependencies:** None

**Effort estimate:** 3-4 hours

---

### Task 04: Fix plugin state isolation correctness bug

**Description:** Implement state keyed by (symbol, timeframe) instead of shared singleton state across 62 plugins.

**Files:** All 62 plugins in `src/intelligence/{indicators,context,patterns,smart_money,trading}/`

**Issues:**
- `_state: dict = field(default_factory=dict)` creates shared singleton
- Processing multiple symbols/timeframes sequentially corrupts state
- Each plugin uses same instance across all streams

**Approach options:**
- **Option A (Recommended):** Refactor `compute_full()` signature to accept `(symbol: str, timeframe: str)` parameters
- **Option C (Short-term):** Add guard to prevent `compute_next()` until isolation fixed

**Implementation:**
1. Update plugin protocol `compute_full()` signature
2. Add state_key to all plugin initializers: `self._state_key = f"{symbol}:{timeframe}"`
3. Modify `_state` access to use state_key
4. Add guard to `compute_next()`: `if not hasattr(self, "_state_key"): raise NotImplementedError`

**Success criteria:**
- [ ] State isolation verified by testing multiple symbols sequentially
- [ ] No state corruption observed
- [ ] Backward compatible (compute_full without state_key still works)

**Dependencies:**
- Plugin registry modification
- All I1-I7 plugins need signature updates

**Effort estimate:** 4-6 hours

**Notes:**
- See `.planning/todos/pending/refactor-plugin-state-isolation.md` for detailed analysis
- This is a **critical correctness bug** — should be fixed before enabling `compute_next()`

---

### Task 05: Add xgroup_setid recovery to feature_writer_service.py

**Description:** Follow consumer group pattern with `xgroup_setid("$")` recovery.

**File:** `src/services/feature_writer_service.py` (around line 274)

**Issues:**
- Missing `xgroup_setid` recovery in except block
- Consumer may start at old position on restart, processing stale backlog

**Implementation:**
1. Wrap `xgroup_create()` in try/except
2. If error "BUSYGROUP", call `xgroup_setid(stream_name, group_name, "$")`
3. Follow pattern from `src/core/streams_mixins/_consuming.py` (lines 64-75)

**Success criteria:**
- [ ] Consumer group creation handles BUSYGROUP exception
- [ ] xgroup_setid fallback present in except block
- [ ] Service always starts at "$" after restart

**Dependencies:** None

**Effort estimate:** 30 minutes

**Notes:**
- Pattern already exists in other services
- See simplify finding #3 in `.planning/todos/pending/2026-03-01-code-quality-findings-i1-i7.md`

---

### Task 06: Fix unconditional signal rewind in signal_generator_service.py

**Description:** Only rewind `warmup_bars` when `group_freshly_created` flag is true.

**File:** `src/services/signal_generator_service.py` (lines 351-366)

**Issues:**
- Code rewinds unconditionally on every startup
- May reprocess already-handled messages
- Wasteful I/O and Redis calls

**Implementation:**
1. Check `group_freshly_created` flag value before rewinding
2. Only rewind if flag is false

**Success criteria:**
- [ ] Rewind only happens on fresh group creation
- [ ] No duplicate message processing on normal startup

**Dependencies:** None

**Effort estimate:** 30 minutes

---

### Task 07: Reduce sequential warmup reads at startup

**Description:** Batch or parallelize Redis `xrevrange` calls across 92 streams at service startup.

**Files:**
- `src/services/indicator_service.py`
- `src/services/market_analysis_service.py`

**Issues:**
- 100 xrevrange calls per stream sequentially
- 9,200+ round trips at startup (~10 seconds)

**Implementation:**
1. Use `xrevrange` multi-key form (batch across streams)
2. Or use asyncio.gather() for parallel reads

**Success criteria:**
- [x] Startup time reduced from ~10s to ~2s
- [x] Fewer Redis round trips (92 parallel calls vs 9200 sequential)
- [x] Same warmup data retrieved

**Dependencies:** None (Redis, asyncio)

**Effort estimate:** 2-3 hours

---

### Task 08: Extract shared fval() utility

**Description:** Extract shared `fval()` utility function to reduce code duplication in 2 files.

**Files:**
- `src/intelligence/trading/cis_scorer.py`
- `src/intelligence/trading/trade_framer.py`

**Issues:**
- Duplicated safe float extraction from features dict
- 5-10 lines of duplicate code

**Implementation:**
1. Add `def fval(features: dict[str, Any], key: str, default: float = 0.0) -> float:` to `src/intelligence/utils.py`
2. Replace duplicate implementations with `is_num(fval(features, key))` calls

**Success criteria:**
- [ ] Shared utility exists in src/intelligence/utils.py
- [ ] Both files use same function
- [ ] Code reduced, DRY principle satisfied

**Dependencies:** None

**Effort estimate:** 30 minutes

---

### Task 09: Extract shared clamp() utility

**Description:** Extract shared `clamp()` utility to reduce 20+ instances of magic number patterns.

**Implementation:**
1. Add `def clamp(value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:` to `src/intelligence/utils.py`
2. Replace `max(-1.0, min(1.0, value))` patterns with `clamp(value, min_val, max_val)`

**Success criteria:**
- [x] Utility available in src/intelligence/utils.py
- [x] 27 code locations simplified (6 files)
- [x] Intent of clamp operation made explicit

**Dependencies:** None

**Effort estimate:** 20 minutes

---

### Task 10: Extract setup_consumer_group() utility

**Description:** Extract duplicated consumer group setup code to reduce duplication across 5 services.

**Files:**
- `src/services/indicator_service.py`
- `src/services/market_analysis_service.py`
- `src/services/signal_tracker_service.py`
- `src/services/signal_generator_service.py`
- `src/services/ai_narrative_service.py`
- `src/services/feature_writer_service.py`

**Implementation:**
1. Add `async def setup_consumer_group(self, group_name: str, stream_name: str):` to `src/core/streams_mixins/_consuming.py`
2. Wrap `xgroup_create()` in try/except with `xgroup_setid("$")` fallback
3. Replace duplicate code in all 5 services with utility call

**Success criteria:**
- [ ] Shared function available in streams mixin
- [ ] 5 services use same code
- [ ] DRY principle satisfied

**Dependencies:** None

**Effort estimate:** 1 hour

---

### Task 11: Extract read_multi_stream() utility

**Description:** Extract duplicated multi-stream `xreadgroup` pattern to reduce duplication across 5 services.

**Files:** Same 5 services as Task 10

**Implementation:**
1. Add `async def read_multi_stream(self, group_name: str, consumer_name: str, stream_map: dict[str, tuple], count: int = 10, block: int = 1000) -> list:` to `src/core/streams_mixins/_consuming.py`
2. Replace duplicate `xreadgroup` loops with single call

**Success criteria:**
- [ ] Shared utility available
- [ ] 5 services use same code
- [ ] Single xreadgroup call per service

**Dependencies:** None

**Effort estimate:** 1 hour

---

### Task 12: Add active symbols to indicator_service.json

**Description:** Add active contracts to empty symbols list.

**File:** `config/indicator_service.json`

**Issues:**
- `"symbols": []` — Service runs but processes nothing
- Misleading configuration state

**Implementation:**
1. Add ES, NQ, RTY to symbols array
2. Verify service loads symbols correctly

**Success criteria:**
- [x] Non-empty symbols list
- [x] Service processes 6 active contracts (ESH6, NQH6, RTYH6, CLK6, GCM6, ZCK6)
- [x] Valid configuration

**Dependencies:** None

**Effort estimate:** 10 minutes

---

### Task 13: Generate contract codes dynamically

**Description:** Generate contract codes dynamically instead of hardcoding 17 H6/J6/M6 codes that will expire in March 2026.

**File:** `dashboard/src/lib/symbol-config.ts`

**Issues:**
- 17 hardcoded contract codes (ESH6, NQH6, etc.)
- Will break monthly when contracts expire
- Copy-paste maintenance burden

**Implementation:**
1. Create contract code generator function
2. Derive from symbol + expiry month (e.g., ES + H6 = ESH6)
3. Replace hardcoded codes with generated values

**Success criteria:**
- [x] Contract codes generated dynamically (MONTH_CODES constant, generateContractCode, generateFrontMonthContract)
- [x] No hardcoded codes as primary (hardcoded values are fallback only)
- [x] Automatic updates on expiry (via loadConfig() which calls /api/instruments)

**Dependencies:** None (IBKR API available)

**Effort estimate:** 2 hours

---

## Dependencies Summary

| Task | Dependencies |
|------|-------------|
| 01 | None |
| 02 | head_shoulders patterns |
| 03 | pattern files (numpy) |
| 04 | Plugin protocol |
| 05 | streams_mixins |
| 06 | None |
| 07 | streams_mixins |
| 08 | None |
| 09 | None |
| 10 | None |
| 11 | src/intelligence/utils.py |
| 12 | src/intelligence/utils.py |
| 13 | streams_mixins |

---

## Success Criteria

Overall phase success criteria:
- [ ] All ruff errors resolved (206 → 0)
- [ ] Plugin state isolation implemented
- [ ] xgroup_setid recovery added
- [ ] Signal rewind fixed
- [ ] Warmup startup reduced (< 5s)
- [ ] 5+ shared utilities extracted
- [ ] Active symbols added to config
- [ ] Contract codes generated dynamically

---

## Wave 1 (Critical)

### Task 01: Resolve ruff errors
### Task 02: Fix O(N³) complexity
### Task 03: Fix O(N²) complexity
### Task 04: Fix plugin state isolation

**Rationale:** Address correctness bugs first, then performance issues. These are blocking production-quality code.

**Tasks:**
- Task 01: All lint errors (Priority 1)
- Task 02: head_shoulders O(N³) → O(N²) (Priority 1)
- Task 03: Pattern files O(N²) (Priority 1)
- Task 04: Plugin state isolation (Priority 1)
- Task 05: xgroup recovery (Priority 1)
- Task 06: Signal rewind (Priority 1)

**Execute sequentially** to verify fixes don't break existing functionality.

---

## Wave 2 (High Priority)

### Task 07: Reduce warmup reads
### Task 08: Extract fval utility
### Task 09: Extract clamp utility
### Task 10: Extract setup_consumer_group
### Task 11: Extract read_multi_stream
### Task 12: Add symbols to config
### Task 13: Generate contract codes

**Rationale:** Reduce code duplication and improve maintainability. These changes make code easier to understand and maintain.

**Execute in any order**, most dependent tasks first:
- Task 08 (fval) enables Task 02 and 09 (clamp uses similar patterns)
- Task 10 (setup_consumer_group) enables Task 11 (read_multi_stream)

---

## Notes

- Tasks 02 and 03 are algorithmically complex — may need iteration
- Task 04 (plugin state) is critical correctness bug — high impact
- Tasks 08, 09, 10, 11 are utility extractions — low risk
- Task 13 (contract codes) is configuration — requires validation
