# Production Scripts Audit — Renaissance Validation

**Date:** 2026-03-25
**Purpose:** "Prove value or remove" — audit all production scripts for validity, modernization, and waste
**Status:** 🔍 CRITICAL FINDINGS

---

## Executive Summary

| Category | Count | Scripts |
|----------|-------|---------|
| ✅ **Valid & Modern** | 4 | `historical_backfill`, `pipeline_reset`, `migrate_jsonb_strings_to_objects`, `validate_roll_detection` |
| ⚠️ **Valid but Legacy** | 6 | `compute_ic`, `data_quality_check`, `lifecycle_replay`, `validate_alpha`, `rebuild_ohlcv`, `repair_cis_nulls` |
| ❌ **Outdated/Remove** | 5 | `create_stage_topics`, `kafka_init_topics`, `promote_shadow`, `validate_equity_backfill` |
| ❓ **Unknown/Niche** | 1 | `__init__.py` (empty) |

**Critical Issues:**
1. **11/15 scripts use psycopg2** instead of asyncpg (synchronous DB driver blocks)
2. **2 topic-creation scripts** are obsolete after v2.0 DAG refactor
3. **No comprehensive script reference** in documentation
4. **Mixed database access patterns** (sync vs async)

---

## Detailed Audit

### ✅ Category 1: Valid & Modern (Keep As-Is)

#### 1. `historical_backfill.py` (1841 lines)
**Status:** ✅ Core infrastructure — actively maintained
**Last Updated:** 2026-03-24
**Purpose:** Fetch OHLCV from IBKR + replay through I1-I7 pipeline
**Architecture:** Modern — uses `DatabaseManager`, async patterns, bar normalization
**Dependencies:** ✅ All imports valid
**Verdict:** **KEEP** — critical for data ingestion

#### 2. `pipeline_reset.py` (566 lines)
**Status:** ✅ Core infrastructure — documented in cheatsheet.md
**Last Updated:** 2026-03-23 (fixed critical bugs per `feedback_pipeline_reset_bugs.md`)
**Purpose:** Full pipeline reset (truncate → fetch → replay)
**Architecture:** Modern — async Kafka admin, proper service orchestration
**Dependencies:** ✅ All imports valid
**Known Issues:** Fixed in 2026-03-23 session (register_all_plugins, seed_roll_chain)
**Verdict:** **KEEP** — primary pipeline recovery tool

#### 3. `migrate_jsonb_strings_to_objects.py` (92 lines)
**Status:** ✅ One-time migration tool (can be archived after use)
**Last Updated:** 2026-03-23
**Purpose:** Fix JSONB serialization bug (strings → native objects)
**Architecture:** ✅ Uses `DatabaseManager` (asyncpg)
**Verdict:** **ARCHIVE after migration complete** — not runtime waste

#### 4. `validate_roll_detection.py` (303 lines)
**Status:** ✅ Research/analysis tool for futures roll logic
**Purpose:** Offline validation of calendar + z-score roll detection
**Architecture:** ✅ Uses `DatabaseManager` (asyncpg)
**Verdict:** **KEEP** — niche but valid for roll validation

---

### ⚠️ Category 2: Valid but Legacy (Modernize Recommended)

#### 5. `compute_ic.py` (388 lines)
**Status:** ⚠️ Valid but uses **psycopg2** instead of asyncpg
**Purpose:** Compute Information Coefficient (IC) per plugin/regime
**Current Architecture:**
- ❌ Synchronous DB access (blocks, no async/await)
- ✅ Otherwise correct (writes to `signal_performance_segmented`)
**Issues:**
- `signal_performance_segmented` table dropped in migration 050 (see line 336-337 of `data_quality_check.py`)
- Script still references dropped table
**Verdict:** **REFACTOR** — convert to asyncpg + verify table existence

**Refactor Plan:**
```python
# Replace psycopg2 with asyncpg:
import asyncpg
from src.core.database_manager import DatabaseManager

async def main():
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    # ... use db.pool for queries
```

#### 6. `data_quality_check.py` (573 lines)
**Status:** ⚠️ Production monitoring but uses **psycopg2**
**Purpose:** Data quality audit (NULL rates, staleness, pipeline lag)
**Current Architecture:**
- ❌ Synchronous DB access
- ✅ Prometheus metrics export
- ✅ Critical thresholds enforced
**Issues:**
- Lines 336-337 acknowledge `signal_performance_segmented` dropped
- IC health check returns empty dict when table missing
**Verdict:** **REFACTOR** — convert to asyncpg (monitoring should be async)

**Refactor Plan:**
```python
# Convert all DB queries to async:
async def check_null_rates(db: DatabaseManager, symbols: list[str]):
    async with db.get_connection() as conn:
        rows = await conn.fetch(...)
```

#### 7. `lifecycle_replay.py` (715 lines)
**Status:** ⚠️ Valid but uses **psycopg2** + multiprocessing
**Purpose:** Batch replay of historical signals for lifecycle outcomes
**Current Architecture:**
- ❌ Synchronous DB access
- ❌ Multiprocessing workers (not async)
- ✅ Otherwise correct logic
**Verdict:** **REFACTOR** — convert to asyncio + asyncpg (remove multiprocessing)

**Refactor Plan:**
```python
# Replace multiprocessing with asyncio.gather:
async def process_pair(symbol: str, tf: str):
    async with db.get_connection() as conn:
        # ... fetch bars, process signals

# Process all pairs concurrently:
tasks = [process_pair(sym, tf) for sym, tf in pairs]
await asyncio.gather(*tasks)
```

#### 8. `validate_alpha.py` (848 lines)
**Status:** ⚠️ Valid gate but uses **psycopg2** + hardcoded plugin registry
**Purpose:** Statistical validation gate for new alpha sources
**Current Architecture:**
- ❌ Synchronous DB access
- ⚠️ Hardcoded `PLUGIN_REGISTRY` (lines 57-100) — maintenance burden
- ✅ Pearson r, p-value, ADF tests correct
**Verdict:** **REFACTOR** — convert to asyncpg + auto-discover plugins from registry

**Refactor Plan:**
```python
# Auto-discover plugins instead of hardcoded registry:
from src.intelligence.register_plugins import TIER_I1, TIER_I2, TIER_I5
from src.core.plugin_validator import validate_tier

def discover_plugins():
    """Auto-build plugin registry from TIER_* lists."""
    for tier_list in [TIER_I1, TIER_I2, TIER_I5]:
        for plugin_name in tier_list:
            # ... inspect plugin outputs, build registry
```

#### 9. `rebuild_ohlcv.py` (336 lines)
**Status:** ⚠️ Valid but uses **psycopg2**
**Purpose:** Rebuild `market_data_ohlcv` hypertable (fixes chunk explosion)
**Current Architecture:**
- ❌ Synchronous DB access
- ✅ Correct chunk size logic (7-day chunks)
**Verdict:** **REFACTOR** — convert to asyncpg (rarely used, low priority)

#### 10. `repair_cis_nulls.py` (362 lines)
**Status:** ⚠️ Valid one-time repair but uses **psycopg2**
**Purpose:** Fix NULL CIS scores in signal_ledger
**Current Architecture:**
- ❌ Synchronous DB access
- ✅ Correct backfill logic
**Verdict:** **ARCHIVE after use** — one-time repair tool, not runtime

---

### ❌ Category 3: Outdated/Remove (Dead Code)

#### 11. `create_stage_topics.py` (123 lines)
**Status:** ❌ **OBSOLETE** — v2.0 DAG refactor removed pipeline stages
**Evidence:**
- References `topic_quality_gated`, `topic_regime_gated`, `topic_tod_adjusted`, etc.
- These topics were from Phase 40 DAG stages (6 microservices)
- Phase 44.1-44.3 consolidated stages into `FeaturePipelineService`
**Verdict:** **DELETE** — replaced by unified pipeline topics

**Check if any services still use these topics:**
```bash
docker exec redpanda rpk topic list | grep -E "quality_gated|regime_gated|tod_adjusted"
# If empty -> safe to delete script
```

#### 12. `kafka_init_topics.py` (98 lines)
**Status:** ❓ **DUPLICATE** — similar to `create_stage_topics.py`
**Purpose:** Initialize Kafka topics using aiokafka
**Evidence:**
- Uses `AIOKafkaAdminClient` (correct approach)
- But topic list likely obsolete (same as above)
**Verdict:** **AUDIT** — check if topic list is current, otherwise delete

**Audit Command:**
```bash
# Compare script topics vs actual topics:
docker exec redpanda rpk topic list
# If script creates topics that don't exist -> keep
# If script creates obsolete topics -> delete
```

#### 13. `promote_shadow.py` (115 lines)
**Status:** ❌ **OBSOLETE** — shadow promotion moved to CIS learning loop
**Evidence:**
- References `IS_SHADOW` attribute promotion
- Phase 31 (CIS Learning Loop) implements dynamic weight loading
- Manual promotion script no longer needed
**Verdict:** **DELETE** — replaced by automated CIS feedback loop

#### 14. `validate_equity_backfill.py` (65 lines)
**Status:** ❓ **NICHE** — validates no off-hours bars in equity backfill
**Purpose:** Ensure equity backfill excludes pre/post-market data
**Evidence:**
- Very small (65 lines)
- Checks for bars outside RTH hours
**Verdict:** **KEEP IF** equities are actively traded, **DELETE IF** futures-only

**Check:**
```bash
SELECT DISTINCT symbol FROM market_data_ohlcv WHERE platform = 'equity';
# If empty -> delete script
```

---

### ❓ Category 4: Unknown/Empty

#### 15. `__init__.py` (0 lines)
**Status:** ✅ Package marker (required by Python)
**Verdict:** **KEEP** (empty, but necessary for imports)

---

## Architecture Issues Summary

### Issue 1: psycopg2 vs asyncpg (11 scripts affected)

**Problem:** 11/15 scripts use `psycopg2` (synchronous) instead of `asyncpg` (async)

**Impact:**
- Synchronous DB calls block event loop
- Cannot run concurrently with async services
- Inconsistent with production services (all use asyncpg)

**Solution:**
```python
# OLD (psycopg2):
import psycopg2
conn = psycopg2.connect(url)
rows = conn.fetch(query)

# NEW (asyncpg):
import asyncpg
from src.core.database_manager import DatabaseManager

db = DatabaseManager(url)
await db.initialize()
async with db.get_connection() as conn:
    rows = await conn.fetch(query)
```

**Priority:** HIGH — affects performance and consistency

### Issue 2: Dropped Table References

**Problem:** `compute_ic.py` and `data_quality_check.py` reference `signal_performance_segmented` table dropped in migration 050

**Impact:**
- Scripts will fail with `UndefinedTable` error
- IC computation broken

**Solution:**
1. Check if table should exist (was drop premature?)
2. If yes, restore migration 050
3. If no, remove IC computation code (defer to v2.3 ML phase)

**Priority:** CRITICAL — scripts currently broken

### Issue 3: Hardcoded Plugin Registry

**Problem:** `validate_alpha.py` has hardcoded `PLUGIN_REGISTRY` dict (lines 57-100)

**Impact:**
- Must manually update registry when adding plugins
- Maintenance burden
- Doesn't auto-discover from `TIER_*` lists

**Solution:**
```python
# Auto-build registry from TIER lists:
from src.intelligence.register_plugins import TIER_I1, TIER_I2, TIER_I5

def build_plugin_registry():
    """Auto-discover plugins from TIER lists."""
    registry = {}
    for tier_name, tier_list in [("I1", TIER_I1), ("I2", TIER_I2), ("I5", TIER_I5)]:
        for plugin_name in tier_list:
            # Inspect plugin module, extract metadata
            plugin = registry.get_plugin(plugin_name)
            registry[plugin_name] = {
                "column": tier_name.lower(),
                "field": extract_output_field(plugin),
                # ...
            }
    return registry
```

**Priority:** MEDIUM — works but maintenance burden

---

## Action Plan

### Phase 1: Critical Fixes (Do Now)

1. **Check `signal_performance_segmented` table status:**
   ```bash
   docker exec timescaledb psql -U postgres -d indicagent -c "\d signal_performance_segmented"
   ```
   - If exists: Keep `compute_ic.py`, fix asyncpg migration
   - If dropped: Either restore table or remove IC code

2. **Delete obsolete scripts:**
   - `create_stage_topics.py` (DAG stages removed)
   - `promote_shadow.py` (replaced by CIS learning loop)
   - `validate_equity_backfill.py` if no equity symbols

3. **Audit `kafka_init_topics.py`:**
   - Compare topics in script vs actual Redpanda topics
   - Delete if obsolete, update if current

### Phase 2: Modernize (Next Sprint)

4. **Convert 6 scripts from psycopg2 to asyncpg:**
   - `compute_ic.py`
   - `data_quality_check.py`
   - `lifecycle_replay.py` (also remove multiprocessing)
   - `validate_alpha.py`
   - `rebuild_ohlcv.py`
   - `repair_cis_nulls.py`

5. **Auto-discover plugin registry in `validate_alpha.py`**

### Phase 3: Document

6. **Create `docs/reference/scripts.md`** with:
   - Purpose and when to use each script
   - Required arguments and flags
   - Prerequisites (services stopped, IBKR connected)
   - Example commands
   - Expected output

---

## Recommendations

### Immediate Actions (This Session)

1. **DELETE obsolete scripts:**
   ```bash
   git rm production/scripts/create_stage_topics.py
   git rm production/scripts/promote_shadow.py
   git commit -m "chore(scripts): remove obsolete v2.0 DAG stage scripts"
   ```

2. **CHECK `signal_performance_segmented` existence** (determines `compute_ic.py` fate)

3. **AUDIT `kafka_init_topics.py`** (compare topic list vs actual)

### Next Sprint

4. **Refactor psycopg2 → asyncpg** (6 scripts, ~2-3 days)

5. **Create comprehensive script documentation**

6. **Archive one-time scripts** (`migrate_jsonb_strings_to_objects.py`, `repair_cis_nulls.py` to `docs/archive/`)

---

## Summary

**Keep:** 8 scripts (4 modern + 4 legacy to refactor)
**Delete:** 3-5 scripts (obsolete + unknown)
**Archive:** 2 scripts (one-time migrations)

**Estimated Refactor Effort:** 2-3 days for asyncpg migration across 6 scripts

**Risk:** LOW — legacy scripts still work, just not optimal

**Next Step:** Audit completion → user decision on delete/refactor priorities
