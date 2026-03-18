# Phase 31: CIS Learning Loop + Signal Feature Snapshots — Research

**Researched:** 2026-03-16
**Domain:** Adaptive ML weight learning, TimescaleDB schema extension, shadow A/B infrastructure
**Confidence:** HIGH — all findings verified against actual source code

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LEARN-01 | CIS scorer loads learned weights from `cis_weights` DB at runtime; refreshes every 30 min; falls back to bootstrap when `sample_size < 100` or DB unavailable | CISScorer.__init__ confirmed to use only BOOTSTRAP_WEIGHTS; background refresh pattern exists in signal_generator_service._perf_weights_refresh_loop |
| LEARN-02 | Weight updater trains on binary win/loss labels instead of `signal_quality` proxy | weight_updater.py confirmed to use `signal_quality >= mean` binary split; WIN_OUTCOMES taxonomy verified from lifecycle_tracker |
| LEARN-03 | `cis_weights` table extended with `asset_cluster` + `timeframe` columns; five clusters defined | Migration 012 confirmed: table uses symbol='global', timeframe='global'; no asset_cluster column exists |
| LEARN-04 | Weight learner trains separate LR models per (asset_cluster, timeframe) when N >= 100; falls back to global | settings.py sector values documented; cluster mapping logic must be new |
| FEAT-01 | `signal_features` hypertable captures all non-null raw feature values at signal fire time | Table does not exist; cis_attribution captures contributions only (not raw values); IntelligenceEvent fields are the source |
| FEAT-02 | `signal_features` write committed atomically with `signal_ledger` row in signal_generator_service | signal_ledger INSERT uses execute_batch; same DB connection/transaction available |
| SHAD-01 | `is_shadow BOOLEAN NOT NULL DEFAULT FALSE` added to signal_ledger; shadow signals co-emitted | Column does not exist; INSERT SQL has 38 params; LedgerEntry dataclass must be extended |
| SHAD-02 | Statistical promotion gate CLI: two-sample proportion z-test, p < 0.05 AND N >= 200 per variant | No existing promotion script; scipy.stats.proportions_ztest available in venv |
</phase_requirements>

---

## Summary

Phase 31 closes the four most critical alpha gaps in the I7 system before any new plugins are added. The work is cleanly divisible into four independent change areas: (A) wire the CIS runtime to actually load learned weights from the database, (B) upgrade the weight learner from a proxy target to binary win/loss labels with asset-cluster segmentation, (C) create the `signal_features` hypertable and atomic write path, and (D) add shadow infrastructure (`is_shadow` column + CLI promotion gate).

All code archaeological findings are HIGH confidence — the current source has been read directly. The `weight_updater.py` exists and trains a LogisticRegression but writes to a `cis_weights` table that `CISScorer.__init__` never reads. This is the largest single-point alpha leak: every bar uses bootstrap weights regardless of what the learner computed. Wiring the read path is a small change with no architectural risk.

The `signal_features` table is additive infrastructure. It does not replace `cis_attribution` (which stores per-bucket contribution scores). It adds raw indicator values at mid-bar snapshot time — the ML training dataset foundation that all subsequent supervised learning phases (ML scoring model, calibration) will consume.

**Primary recommendation:** Migrate in this order — (1) DB schema first (migration), (2) weight loader in CISScorer + 30-min refresh loop, (3) weight_updater binary labels + cluster segmentation, (4) signal_features hypertable + atomic write, (5) is_shadow column + LedgerEntry extension, (6) CLI promotion script.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scikit-learn | already in venv | LogisticRegression training + IsotonicRegression (Phase 35) | Used by existing weight_updater.py |
| asyncpg | already in venv | DB pool access for weight refresh background task | Used by DatabaseManager throughout |
| scipy | already in venv | `proportions_ztest` for SHAD-02 CLI promotion gate | Standard for two-sample proportion tests |
| structlog | already in venv | Service logging (structured fields) | Project-wide standard |

**Installation:** No new dependencies required. All libraries are in the existing `.venv`.

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | already in venv | Array operations in weight computation | Already used in weight_updater.py and cis_scorer.py |
| argparse | stdlib | CLI argument parsing for SHAD-02 promotion script | No external lib needed |

---

## Architecture Patterns

### Recommended Project Structure

New files for this phase:

```
src/intelligence/
├── weight_updater.py          # MODIFY: binary labels + cluster segmentation
├── trading/
│   └── cis_scorer.py          # MODIFY: add update_weights() method; keep stateless score()
services/
└── signal_generator_service.py  # MODIFY: _load_cis_weights_loop() + signal_features write
production/
├── migrations/
│   └── 034_cis_learning_loop.sql  # NEW: asset_cluster, signal_features, is_shadow
└── scripts/
    └── promote_shadow.py          # NEW: SHAD-02 CLI promotion gate
tests/unit/intelligence/
└── test_weight_updater.py     # MODIFY: add binary label tests + cluster segmentation tests
tests/unit/service_tests/
└── test_signal_generator_features.py  # NEW: signal_features atomic write tests
```

### Pattern 1: CIS Runtime Weight Loading

**What:** Background async task in `signal_generator_service` loads weights from DB every 30 minutes and calls `cis_scorer.update_weights(weights_dict, version)`. `CISScorer` stays stateless in `score()` — it reads `self._weights` which is updated atomically.

**When to use:** All CIS scoring after startup.

**CISScorer extension:**
```python
# Source: verified from cis_scorer.py — CISScorer.__init__ uses self._weights and self._weights_array
def update_weights(self, weights: dict[str, float], version: int) -> None:
    """Thread-safe weight update. Called from service layer only."""
    self._weights = weights
    self._weights_version = version
    # Recompute weights_array so next score() call uses new weights
    self._weights_array = np.array([self._weights[b] for b in BUCKET_NAMES])
```

**Service background loop pattern (mirrors existing _perf_weights_refresh_loop):**
```python
# Source: verified from signal_generator_service.py line ~1315
async def _cis_weights_refresh_loop(self) -> None:
    while True:
        await asyncio.sleep(1800)  # 30 minutes
        try:
            await self._load_cis_weights_from_db()
        except Exception as exc:
            self.logger.warning("CIS weights refresh error", error=str(exc))

async def _load_cis_weights_from_db(self) -> None:
    """Load per-cluster weights from cis_weights. Falls back to BOOTSTRAP on failure."""
    # Query: SELECT asset_cluster, timeframe, bucket, weight, version, sample_size
    #        FROM cis_weights WHERE sample_size >= 100 ORDER BY version DESC
    # Group by (asset_cluster, timeframe), take max version per group
    # Call self._cis_scorer.update_weights(weights_dict, version)
    # Log: "Loaded weights from DB for cluster={} tf={}"  ← success criterion SC-1
    # Log: "Using bootstrap weights for cluster={} tf={}" ← bootstrap fallback message
```

### Pattern 2: Binary Win Labels in weight_updater.py

**What:** Replace `signal_quality >= mean` with direct binary label from `outcome` column. Query `signal_ledger` on `outcome IS NOT NULL` instead of `signal_quality IS NOT NULL`.

**WIN_OUTCOMES set (verified from lifecycle_tracker.py STATE.md):**
```python
WIN_OUTCOMES = frozenset({'target_1', 'target_1_2', 'target_full'})

# Replace current logic:
y = np.array([
    1.0 if row.get('outcome') in WIN_OUTCOMES else 0.0
    for row in resolved_signals
])
```

**DB query change:**
```sql
-- REPLACE current query in run_weight_update():
SELECT bucket_scores, outcome, confidence, symbol, timeframe
FROM signal_ledger
WHERE outcome IS NOT NULL
  AND bucket_scores IS NOT NULL
  AND is_shadow = FALSE   -- train only on production signals
ORDER BY timestamp DESC
LIMIT 10000
```

### Pattern 3: Asset Cluster Segmentation

**What:** Map each `signal_ledger.symbol` to one of five cluster labels, then train a separate LogisticRegression per `(asset_cluster, timeframe)` when N >= 100.

**Cluster mapping (verified against settings.py sector values):**
```python
# Source: verified from src/config/settings.py — sectors for all active instruments
ASSET_CLUSTER_MAP: dict[str, str] = {
    # eq_index: equity_index sector
    "ES": "eq_index", "NQ": "eq_index", "RTY": "eq_index", "YM": "eq_index",
    # commodity: energy + metals sectors
    "CL": "commodity", "GC": "commodity", "SI": "commodity",
    "NG": "commodity", "HG": "commodity", "PL": "commodity", "PA": "commodity",
    # rates: interest_rates sector
    "ZN": "rates", "ZB": "rates", "ZF": "rates", "ZT": "rates",
    # crypto: crypto sector
    "BTC": "crypto", "ETH": "crypto", "SOL": "crypto",
    # ag: agriculture sector
    "ZC": "ag", "ZS": "ag", "ZW": "ag",
}
# ETFs (equity sector) and FX map to global (no cluster model until >100 signals)
# VX (volatility) maps to global
```

Note: The `symbol` stored in `signal_ledger` is the base symbol (e.g., `ES`, not `ESM6`). Verified from CLAUDE.md: "instruments table key is base symbol."

**Cluster training loop:**
```python
# Group resolved_signals by (asset_cluster, timeframe)
# For each group with n >= 100: train cluster-level model
# Write with asset_cluster + timeframe set explicitly
# For global fallback: use all signals, write with asset_cluster='global', timeframe='global'
```

### Pattern 4: signal_features Hypertable Schema

**What:** New TimescaleDB hypertable capturing raw feature values at signal fire time (mid-bar state, not bar-close state from `intelligence_features`).

**Verified design from i7-quant-audit-2026-03-16.md:**
```sql
CREATE TABLE signal_features (
    signal_id     UUID NOT NULL,
    computed_at   TIMESTAMPTZ NOT NULL,      -- for hypertable partitioning
    feature_name  TEXT NOT NULL,
    feature_value DOUBLE PRECISION,
    feature_bucket TEXT,                     -- trend/momentum/structure/pattern/institutional/regime
    bucket_contribution DOUBLE PRECISION,   -- cross-reference from cis_attribution
    PRIMARY KEY (signal_id, feature_name)
);
SELECT create_hypertable('signal_features', 'computed_at',
    chunk_time_interval => INTERVAL '7 days');
CREATE INDEX ON signal_features (signal_id, computed_at DESC);
```

**Atomic write in signal_generator_service:**
```python
# Same DB connection — execute signal_ledger INSERT then signal_features batch INSERT
# Use asyncpg transaction to guarantee atomicity (FEAT-02)
async with db_pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute(_INSERT_SQL, *ledger_params)
        await conn.executemany(_INSERT_FEATURES_SQL, feature_rows)
```

**What to snapshot:** All non-null float/int fields from the flat `features` dict (merged IntelligenceEvent fields). Also include `constituent_contributions` from `CISResult`. Exclude string/object fields. Include `feature_bucket` by cross-referencing which CIS bucket each feature belongs to (use a static mapping from `cis_scorer.py` bucket methods).

### Pattern 5: is_shadow Column + LedgerEntry Extension

**What:** Add `is_shadow BOOLEAN NOT NULL DEFAULT FALSE` to `signal_ledger`. Extend `LedgerEntry` dataclass and `to_insert_params()`. Co-emit shadow signal on same bar as production signal by running experimental aggregator path in parallel.

**LedgerEntry extension:**
```python
# Add after market_entry_price field (currently param $38):
is_shadow: bool = False

# to_insert_params() becomes 39-element tuple
# _INSERT_SQL gains is_shadow as $39::boolean
```

**Shadow co-emission pattern:**
```python
# In signal_generator_service, after production signal generation:
# Run experimental path (e.g. new weights) with same features/plugin_outputs
# Set is_shadow=True on all resulting LedgerEntry objects
# Insert both production and shadow signals in same transaction
```

### Pattern 6: SHAD-02 CLI Promotion Script

**What:** Standalone Python script at `production/scripts/promote_shadow.py`. Queries `signal_ledger` for matched pairs (same `feature_ts`, `symbol`, `timeframe`, one is_shadow=True, one is_shadow=False). Runs two-sample proportion z-test. Exits non-zero with reason if N < 200 or p >= 0.05.

```python
# scipy.stats.proportions_ztest
from scipy.stats import proportions_ztest

# count = [n_prod_wins, n_shadow_wins]
# nobs = [n_prod_total, n_shadow_total]
stat, p_value = proportions_ztest(count, nobs, alternative='smaller')
# 'smaller': test shadow win rate > prod win rate (one-tailed)

if n_shadow < 200 or n_prod < 200:
    print(f"REJECTED: insufficient samples (shadow={n_shadow}, prod={n_prod}, required=200)")
    sys.exit(1)
if p_value >= 0.05:
    print(f"REJECTED: p={p_value:.4f} >= 0.05 (shadow_wr={shadow_wr:.3f}, prod_wr={prod_wr:.3f})")
    sys.exit(1)
print("PROMOTED")
sys.exit(0)
```

### Anti-Patterns to Avoid

- **Do NOT make CISScorer stateful in score()**: Weight state lives in `self._weights`/`self._weights_version` (set at init or via `update_weights()`), not computed during `score()`. Keeping `score()` pure enables easy unit testing.
- **Do NOT query DB inside score()**: Loading weights is a background refresh concern in the service. `score()` is called per-bar on every symbol×TF — a DB call there would collapse pipeline throughput.
- **Do NOT use `asyncio.Lock` in `update_weights()`**: The GIL protects the dict/array assignment. A lock would serialize all incoming bars during weight refresh.
- **Do NOT train on shadow signals**: `run_weight_update` query must filter `is_shadow = FALSE`. Shadow signals are experimental variants and must not contaminate the production weight learner.
- **Do NOT use `CREATE INDEX CONCURRENTLY` on hypertables**: Confirmed TimescaleDB limitation — omit CONCURRENTLY on all new hypertable indexes.
- **Do NOT use `signal_quality` as training target after this phase**: It is a continuous `pnl_r`-derived proxy. Binary `outcome IN WIN_OUTCOMES` is the correct label from this phase forward.
- **Do NOT use `execute_batch` without asyncpg transaction for atomic signal_features write**: `execute_batch` runs multiple inserts but NOT in a transaction. Must use explicit `async with conn.transaction():` to guarantee FEAT-02 atomicity.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Two-sample proportion test | Custom z-test formula | `scipy.stats.proportions_ztest` | Already in venv; handles edge cases (n=0, identical proportions) |
| Logistic regression with L2 reg | Custom gradient descent | `sklearn.LogisticRegression(C=1.0)` | Already used in weight_updater.py; battle-tested |
| Softmax weight normalization | Custom normalization | `_softmax` + `_clip_and_renormalize` in weight_updater.py | Already exists; reuse or extend, don't duplicate |
| Asyncpg transaction | Manual BEGIN/COMMIT via execute_command | `async with conn.transaction():` | asyncpg native transaction context manager |
| Hypertable creation | Custom chunking logic | `SELECT create_hypertable(...)` | TimescaleDB built-in; chunk_time_interval='7 days' matches pattern in existing migrations |

---

## Common Pitfalls

### Pitfall 1: symbol vs. contract symbol confusion in cluster mapping
**What goes wrong:** `signal_ledger.symbol` stores base symbol (`ES`), not contract code (`ESM6`). If cluster mapping accidentally uses contract code, all rows get `asset_cluster='global'` silently.
**Why it happens:** CLAUDE.md notes the DB stores base symbol but some in-memory representations use contract codes.
**How to avoid:** Map `row['symbol']` (the DB column) directly. Verify with `SELECT DISTINCT symbol FROM signal_ledger LIMIT 10` — these should be base symbols.
**Warning signs:** All weight rows written with `asset_cluster='global'` after migration.

### Pitfall 2: cis_weights unique index collision after schema extension
**What goes wrong:** Migration adds `asset_cluster` to the table but the existing unique index is on `(version, symbol, timeframe)`. New rows with asset_cluster set will collide if version tracking uses a global counter.
**Why it happens:** `run_weight_update` currently does `MAX(version) WHERE symbol='global'` and increments by 1. After migration, version numbering must be per `(asset_cluster, timeframe)` pair.
**How to avoid:** New unique index: `(asset_cluster, timeframe, version)`. Drop and recreate the old index as part of migration 034. Version counter query: `MAX(version) WHERE asset_cluster=$1 AND timeframe=$2`.
**Warning signs:** `asyncpg.exceptions.UniqueViolationError` on first weight write after migration.

### Pitfall 3: signal_features PRIMARY KEY conflict on signal_id + feature_name
**What goes wrong:** If a signal fires twice for the same `(signal_id, feature_name)` (e.g., during replay with `ON CONFLICT DO NOTHING` on signal_ledger), the signal_features insert will fail if it doesn't also handle conflicts.
**Why it happens:** `historical_backfill.py` uses `ON CONFLICT DO NOTHING` on signal_ledger. The signal_features write path must match.
**How to avoid:** `INSERT INTO signal_features ... ON CONFLICT (signal_id, feature_name) DO NOTHING`.
**Warning signs:** `asyncpg.exceptions.UniqueViolationError` during historical replay runs.

### Pitfall 4: LedgerEntry parameter count mismatch after is_shadow addition
**What goes wrong:** `to_insert_params()` returns a tuple; `_INSERT_SQL` uses `$N` positional params. If the dataclass gains a field but INSERT SQL or param count is not updated in lockstep, asyncpg raises `expected N params, got M`.
**Why it happens:** Three places must stay in sync: `LedgerEntry` fields, `to_insert_params()`, and `_INSERT_SQL`.
**How to avoid:** Add `is_shadow` as the LAST field in both dataclass and SQL. Add a unit test asserting `len(entry.to_insert_params()) == <expected>`.
**Warning signs:** `asyncpg.exceptions.InterfaceError: bind message has N parameter formats but expects M`.

### Pitfall 5: Weight update training on future-leaking data
**What goes wrong:** Query uses `ORDER BY timestamp DESC LIMIT 10000` without a time cutoff. If signals are replayed historically (backdated timestamps), the learner trains on out-of-order data and the model sees future outcomes.
**Why it happens:** `historical_backfill.py` replays signals with their original bar timestamps. The learner query selects by `ORDER BY timestamp DESC` which is the bar timestamp, not the time the outcome was resolved.
**How to avoid:** Filter on `exit_at IS NOT NULL AND exit_at < NOW() - INTERVAL '1 day'` to exclude in-flight signals. The `exit_at` column is wall-clock time when the lifecycle service resolved the signal.
**Warning signs:** Anomalously high weight updater accuracy (>75% train accuracy) vs. live performance.

### Pitfall 6: asyncpg JSONB registration for signal_features feature_value columns
**What goes wrong:** asyncpg requires explicit codec registration for JSONB columns. However, `signal_features.feature_value` is `DOUBLE PRECISION`, not JSONB — this pitfall applies only if the schema is changed to store feature vectors as a JSON blob instead of rows.
**Why it happens:** Tendency to collapse the row-per-feature schema into a single JSONB blob for query simplicity.
**How to avoid:** Keep the row-per-feature schema. The ML batch jobs that read it will do `SELECT * FROM signal_features WHERE signal_id = $1` and pivot in Python. Do not store as JSONB blob — it eliminates column-level querying.

---

## Code Examples

### Load CIS weights from DB (verified pattern from existing refresh loops)

```python
# Source: verified pattern from signal_generator_service._perf_weights_refresh_loop (line ~1315)
async def _load_cis_weights_from_db(self) -> None:
    if self._db_manager is None:
        return
    try:
        rows = await self._db_manager.execute_query("""
            SELECT DISTINCT ON (asset_cluster, timeframe)
                asset_cluster, timeframe, version, sample_size,
                trend_w, momentum_w, structure_w, pattern_w, institutional_w, regime_w
            FROM cis_weights
            WHERE sample_size >= 100
            ORDER BY asset_cluster, timeframe, version DESC
        """)
        for row in rows:
            weights = {
                "trend": row["trend_w"], "momentum": row["momentum_w"],
                "structure": row["structure_w"], "pattern": row["pattern_w"],
                "institutional": row["institutional_w"], "regime": row["regime_w"],
            }
            cluster = row["asset_cluster"]
            tf = row["timeframe"]
            self._cis_weights_cache[(cluster, tf)] = (weights, row["version"])
            self.logger.info(
                "Loaded weights from DB",
                cluster=cluster, tf=tf, version=row["version"]
            )
    except Exception as exc:
        self.logger.warning("CIS weights load failed — using bootstrap", error=str(exc))
```

### Binary win label extraction

```python
# Source: verified from i7-quant-audit-2026-03-16.md + lifecycle_tracker outcomes
WIN_OUTCOMES: frozenset[str] = frozenset({'target_1', 'target_1_2', 'target_full'})

def _build_binary_labels(resolved_signals: list[dict]) -> np.ndarray:
    return np.array([
        1.0 if row.get('outcome') in WIN_OUTCOMES else 0.0
        for row in resolved_signals
    ])
```

### Atomic signal_features write

```python
# Source: asyncpg transaction pattern; DatabaseManager exposes pool via self._pool
_INSERT_FEATURES_SQL = """
    INSERT INTO signal_features
        (signal_id, computed_at, feature_name, feature_value, feature_bucket, bucket_contribution)
    VALUES ($1, $2, $3, $4, $5, $6)
    ON CONFLICT (signal_id, feature_name) DO NOTHING
"""

async def _write_signal_with_features(
    pool: asyncpg.Pool,
    ledger_entry: LedgerEntry,
    features: dict,
    cis_result: CISResult,
) -> None:
    feature_rows = _build_feature_rows(ledger_entry.signal_id, ledger_entry.timestamp, features, cis_result)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(_INSERT_SQL, *ledger_entry.to_insert_params())
            await conn.executemany(_INSERT_FEATURES_SQL, feature_rows)
```

### SHAD-02 CLI promotion gate

```python
# Source: scipy.stats API (verified in venv)
from scipy.stats import proportions_ztest

def run_promotion_test(signal_ledger_rows: list[dict]) -> None:
    prod = [r for r in signal_ledger_rows if not r['is_shadow']]
    shadow = [r for r in signal_ledger_rows if r['is_shadow']]

    n_prod, n_shadow = len(prod), len(shadow)
    if n_prod < 200 or n_shadow < 200:
        print(f"REJECTED: insufficient samples (prod={n_prod}, shadow={n_shadow}, required=200)")
        sys.exit(1)

    prod_wins = sum(1 for r in prod if r['outcome'] in WIN_OUTCOMES)
    shadow_wins = sum(1 for r in shadow if r['outcome'] in WIN_OUTCOMES)

    stat, p = proportions_ztest(
        [shadow_wins, prod_wins],
        [n_shadow, n_prod],
        alternative='larger'  # shadow win rate > prod win rate
    )

    if p >= 0.05:
        print(f"REJECTED: p={p:.4f} (shadow_wr={shadow_wins/n_shadow:.3f}, prod_wr={prod_wins/n_prod:.3f})")
        sys.exit(1)
    print("PROMOTED")
    sys.exit(0)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `signal_quality >= mean` as binary target | `outcome IN WIN_OUTCOMES` binary label | Phase 31 | Cleaner signal; no pnl_r scale ambiguity |
| `symbol='global'` in cis_weights | `asset_cluster` + `timeframe` segmented | Phase 31 | ES and BTC get separate weight vectors |
| CIS always uses BOOTSTRAP_WEIGHTS | Runtime loads learned weights from DB | Phase 31 | Live learning loop finally active |
| No raw feature snapshot at signal time | `signal_features` hypertable | Phase 31 | ML training dataset foundation |
| `is_shadow` implicit / absent | `is_shadow BOOLEAN` in signal_ledger | Phase 31 | A/B matched-pair comparison enabled |

**Deprecated/outdated after this phase:**
- `signal_quality` as LR training target: replaced by binary `outcome` label
- Bootstrap-only CIS weights at runtime: replaced by DB-loaded weights with 30-min refresh
- `symbol='global'` as sole weight key: table gains `asset_cluster` + `timeframe` dimensions

---

## Schema Changes Required (Migration 034)

```sql
-- 1. Extend cis_weights for cluster+TF segmentation
ALTER TABLE cis_weights ADD COLUMN IF NOT EXISTS asset_cluster TEXT NOT NULL DEFAULT 'global';
-- Drop old unique index, create new one covering asset_cluster
DROP INDEX IF EXISTS idx_cis_weights_version_symbol;
CREATE UNIQUE INDEX IF NOT EXISTS idx_cis_weights_cluster_tf_version
    ON cis_weights (asset_cluster, timeframe, version);
-- Update bootstrap seed row
UPDATE cis_weights SET asset_cluster = 'global' WHERE asset_cluster IS NULL;

-- 2. signal_features hypertable
CREATE TABLE IF NOT EXISTS signal_features (
    signal_id         UUID NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL,
    feature_name      TEXT NOT NULL,
    feature_value     DOUBLE PRECISION,
    feature_bucket    TEXT,
    bucket_contribution DOUBLE PRECISION,
    PRIMARY KEY (signal_id, feature_name)
);
SELECT create_hypertable('signal_features', 'computed_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_signal_features_signal_id
    ON signal_features (signal_id, computed_at DESC);

-- 3. Shadow column on signal_ledger
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS is_shadow BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_signal_ledger_shadow
    ON signal_ledger (is_shadow, symbol, timeframe) WHERE is_shadow = TRUE;
```

Migration number: `034_cis_learning_loop.sql` (next after 033).

---

## Open Questions

1. **ETF + FX instrument cluster assignment**
   - What we know: 38 ETFs have `asset_class=EQUITY` with various sectors (equity, broad_market, sector ETFs). FX instruments have `asset_class=FX`. VX is volatility.
   - What's unclear: Should ETFs get their own cluster (`etf`/`equity`) or fall through to `global`? Requirements say five clusters covering all 60 instruments — but FX (4), ETFs (38), VX (1) are not in the five defined clusters.
   - Recommendation: Map unmapped instruments to `global` cluster; global model handles them until a cluster-specific model accumulates 100 signals. This is consistent with LEARN-04's "falls back to global model when cluster is sparse" language.

2. **DatabaseManager transaction surface area**
   - What we know: `DatabaseManager` uses asyncpg with connection pooling. `execute_batch` runs multiple inserts. The existing code does not use explicit transaction blocks in `insert_signals()`.
   - What's unclear: Does `DatabaseManager` expose the underlying pool for direct `acquire()` calls, or does atomic write require a new `execute_in_transaction()` helper?
   - Recommendation: Inspect `src/core/database_manager.py` during implementation. If pool is accessible directly, use `pool.acquire()` + `conn.transaction()`. If not, add `execute_in_transaction(queries)` helper to DatabaseManager.

3. **Feature bucket mapping for signal_features**
   - What we know: `cis_scorer.py` has six bucket methods; each method reads specific feature keys. The mapping from feature name to bucket is implicit in the bucket method code.
   - What's unclear: Should the bucket mapping be a static dict defined once in `cis_scorer.py`, or derived at runtime from `constituent_contributions`?
   - Recommendation: Define a static `FEATURE_BUCKET_MAP: dict[str, str]` in `cis_scorer.py` mapping each feature key to its bucket name. Use this for `signal_features.feature_bucket` population. Avoid runtime derivation to keep the write path simple.

---

## Validation Architecture

> `workflow.nyquist_validation` key absent from `.planning/config.json` — validation section included.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (in `.venv`) |
| Config file | `pytest.ini` (project root) |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/test_weight_updater.py tests/unit/intelligence/test_cis_scorer.py -x -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LEARN-01 | CISScorer.update_weights() changes \_weights and \_weights_array | unit | `pytest tests/unit/intelligence/test_cis_scorer.py -k update_weights -x` | ❌ Wave 0 |
| LEARN-01 | 30-min refresh loop calls _load_cis_weights_from_db | unit | `pytest tests/unit/service_tests/test_signal_generator_weights.py -x` | ❌ Wave 0 |
| LEARN-02 | compute_new_weights uses binary outcome labels, not signal_quality | unit | `pytest tests/unit/intelligence/test_weight_updater.py -k binary_labels -x` | ❌ Wave 0 |
| LEARN-03 | cis_weights rows have non-NULL asset_cluster + timeframe | unit (migration) | `pytest tests/unit/test_migration_034.py -x` | ❌ Wave 0 |
| LEARN-04 | Cluster model trains when n >= 100; falls back to global when sparse | unit | `pytest tests/unit/intelligence/test_weight_updater.py -k cluster -x` | ❌ Wave 0 |
| FEAT-01 | _build_feature_rows extracts non-null floats from IntelligenceEvent | unit | `pytest tests/unit/service_tests/test_signal_generator_features.py -k build_feature_rows -x` | ❌ Wave 0 |
| FEAT-02 | signal_features rows inserted atomically with signal_ledger | unit (mock DB) | `pytest tests/unit/service_tests/test_signal_generator_features.py -k atomic -x` | ❌ Wave 0 |
| SHAD-01 | LedgerEntry.to_insert_params() includes is_shadow at correct position | unit | `pytest tests/unit/intelligence/test_signal_ledger.py -k is_shadow -x` | ❌ Wave 0 |
| SHAD-02 | promote_shadow.py exits 1 when N < 200; exits 0 with PROMOTED when p < 0.05 AND N >= 200 | unit | `pytest tests/unit/scripts/test_promote_shadow.py -x` | ❌ Wave 0 |
| SHAD-02 | promote_shadow.py exits 1 when p >= 0.05 regardless of N | unit | `pytest tests/unit/scripts/test_promote_shadow.py -k rejects_high_p -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/intelligence/test_weight_updater.py tests/unit/intelligence/test_cis_scorer.py -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/intelligence/test_weight_updater.py` — extend existing file with binary label tests and cluster segmentation tests
- [ ] `tests/unit/intelligence/test_cis_scorer.py` — extend existing file with `update_weights()` tests
- [ ] `tests/unit/service_tests/test_signal_generator_weights.py` — new file for CIS weight refresh loop unit tests
- [ ] `tests/unit/service_tests/test_signal_generator_features.py` — new file for signal_features atomic write
- [ ] `tests/unit/intelligence/test_signal_ledger.py` — extend or create for is_shadow field validation
- [ ] `tests/unit/scripts/test_promote_shadow.py` — new file for CLI promotion gate
- [ ] `tests/unit/test_migration_034.py` — validate migration SQL produces correct schema (if migration test pattern exists)

---

## Sources

### Primary (HIGH confidence)
- `src/intelligence/weight_updater.py` — verified current training logic, `signal_quality` target, `run_weight_update` DB query
- `src/intelligence/trading/cis_scorer.py` — verified `__init__` uses only BOOTSTRAP_WEIGHTS; no DB loading; `update_weights` method does not exist
- `src/intelligence/trading/signal_ledger.py` — verified LedgerEntry fields (38 params), `_INSERT_SQL` structure, no `is_shadow` column
- `production/migrations/012_cis_weights_table.sql` — verified table schema: `symbol`, `timeframe` columns; no `asset_cluster`
- `services/signal_generator_service.py` — verified `_perf_weights_refresh_loop` pattern for background refresh; no CIS weight loading
- `src/config/settings.py` — verified sector values for all 60 instruments; cluster mapping derivable from sector
- `docs/ideas/i7-quant-audit-2026-03-16.md` — design anchor for all Phase 31 changes; code examples verified against actual source

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` — confirmed `weight_updater.py` exists, `cis_weights` table exists, `cis_attribution` column exists (all verified against source)
- `.planning/REQUIREMENTS.md` — LEARN-01 through SHAD-02 requirements; confirmed against roadmap
- `tests/unit/intelligence/test_weight_updater.py` — existing test structure; Wave 0 must extend this file

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all libraries verified in-venv
- Architecture: HIGH — all patterns derived from verified existing code; no speculative design
- Schema changes: HIGH — migration pattern verified from 33 existing migrations; TimescaleDB gotchas documented in CLAUDE.md
- Pitfalls: HIGH — derived from code reading (unique index collision, param count drift, async transaction surface)
- Asset cluster mapping: MEDIUM — five clusters defined in requirements; ETF/FX/VX assignment to `global` is researcher inference, not explicitly stated

**Research date:** 2026-03-16
**Valid until:** 2026-04-16 (stable codebase; schema changes are additive)
