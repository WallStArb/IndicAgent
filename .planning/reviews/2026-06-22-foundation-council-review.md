# Foundation Council Review — v3.0 AlphaEngine
**Date:** 2026-06-22
**Scope:** Feature vector persistence layer, live write path, batch compute path, FeatureVector schema, FeatureFactory config
**Context:** Pre-Phase-138 review conducted before IC engine backfill runs. All findings should be resolved or triaged before IC training data is produced at scale.

---

## Files Reviewed

- `src/intelligence/features/feature_vector_persistence.py` — canonical SQL, content-key, serializer
- `services/feature_vector_writer.py` — live Kafka → DB write path
- `services/backfill_feature_factory.py` — batch OHLCV fetch + feature compute
- `src/intelligence/schemas.py` (FeatureVector + FeatureVectorRecord)
- `src/intelligence/feature_factory.py` (FeatureFactoryConfig)
- `src/observability/metrics.py` (counter/gauge/histogram factories)
- `.planning/phases/138-ic-engine-forward-returns/138-P1-PLAN.md`

---

## What the Council Agrees Is Solid

These structural decisions are correct and load-bearing. Do not change them:

- **Content-key UUID on every row.** SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] as UUID. One implementation (`make_feature_vector_id`) in the shared persistence module. Both live and batch paths import from it. Schema drift is structurally impossible.
- **`regime_label_source` validated at the boundary.** `VALID_REGIME_LABEL_SOURCES = {'filtered', 'unknown'}`. `viterbi_batch` values raise `ValueError` before INSERT. Look-ahead bias is structurally prevented.
- **`ON CONFLICT (symbol, tf, bar_ts) DO NOTHING` idempotency.** Replay is safe without DB round-trips.
- **`FEATURE_VECTOR_DOMAIN` registry on `FeatureFactory`.** IC engine knows what it's measuring — domain tagging (quant/structural/regime/macro/calendar) is present from day one.
- **Frozen dataclass for `FeatureVector`.** Compute path is stateless and pure. No hidden mutation.
- **APR-backed `FeatureFactoryConfig`.** Zero inline magic numbers in primitive bodies. All periods, windows, and thresholds are in `config_state`.
- **`_REQUIRED_COLUMNS` schema pre-flight at startup.** Silent schema drift becomes a loud crash before any data is lost.
- **Single shared persistence module.** `feature_vector_persistence.py` is Ring 1. Both write paths import from it. Adding column 62 requires one file change.

---

## Findings

### Finding 1 — CRITICAL: Silent NaN/Inf propagation into IC training corpus

**The problem:** `FeatureVector` declares all fields as `float`. Python's `float` accepts `nan` and `inf`. A z-score computed against a zero-variance window (newly listed ETF, halted symbol, thin market at open) produces `nan` or `inf`. That value flows through the frozen dataclass, through `feature_vector_to_insert_params()`, and into the DB as a structurally valid row. The IC engine then computes Spearman rank correlation on a column containing nulls. PostgreSQL coalesces `nan` to `NULL` in some contexts silently. The IC estimate for that feature on that symbol/TF will be biased, with no error surfaced anywhere in the pipeline.

A single degenerate row that passes silently can corrupt IC estimates for an entire feature column across all its regime strata. The failure mode is: researcher looks at IC results and asks why `hurst` looks non-predictive for XLF — the answer is 47 rows written with `hurst = inf` pulling the Spearman correlation toward zero.

**Two fix options:**

Option A (implement now — no schema change):
Add a validator function to `feature_vector_persistence.py`:
```python
import math, dataclasses

def validate_feature_vector(vector: FeatureVector) -> list[str]:
    """Return list of degenerate field names (empty = clean). Caller decides action."""
    bad = []
    for field in dataclasses.fields(vector):
        v = getattr(vector, field.name)
        if not math.isfinite(v):
            bad.append(field.name)
    return bad
```
Call in `feature_vector_to_insert_params()` before building the tuple:
```python
bad = validate_feature_vector(vector)
if bad:
    raise ValueError(f"Degenerate features (nan/inf): {bad}. Symbol={symbol} tf={tf} bar_ts={bar_ts}")
```
Live path → DLQ. Batch path → skip with counter increment.

Option B (correct long-term — Phase 139 schema migration):
Add `quality_flags: int` to `FeatureVector` — a bitmask where bit `i=1` means feature `i` was computed from degraded data (imputed, clipped, insufficient lookback). IC engine filters `WHERE quality_flags = 0` for primary IC measurement, measures bias with `quality_flags > 0` rows in a separate audit pass.

**Recommendation:** Option A immediately (15 lines, no schema change). Option B in Phase 139 when the frequency and pattern of degraded features is understood from production data.

---

### Finding 2 — CRITICAL: `pipeline_version` conflates algorithm version with software version

**The problem:** `FeatureVectorRecord.pipeline_version` is the IntelligencePipeline software version (e.g. "3.0.0"). If we change the Hurst exponent estimator from R/S analysis to DFA in Phase 139, that changes the feature's statistical meaning permanently — but the pipeline version may not be bumped. The IC engine cannot distinguish rows computed with the old Hurst from rows computed with the new one. It averages their ICs into a meaningless combined estimate. This is a latent form of look-ahead contamination: the model will appear to have a stable IC for `hurst` when it actually has two different series concatenated.

**Concrete fix:**
1. Add `feature_factory_version: str` to `FeatureVectorRecord` (Kafka wire envelope).
2. Add `feature_factory_version VARCHAR NOT NULL DEFAULT '1.0.0'` column to `feature_vectors` schema (migration).
3. Add `FEATURE_FACTORY_VERSION = "1.0.0"` module-level constant to `feature_factory.py`. Bump whenever any feature's computation algorithm changes.
4. Include `feature_factory_version` in the `feature_vector_id` content-key derivation: `SHA-256(symbol|tf|bar_ts_ns|pipeline_version|feature_factory_version)`.
5. IC engine queries include `WHERE feature_factory_version = $current_version` to exclude rows from superseded algorithms.

This maps directly to `BaseBatch.compute_version` that P1 plans to build — wire `feature_factory_version` into that contract now.

**Note:** The content-key formula change (step 4) means all existing rows get new UUIDs on recompute. That is correct behavior — a row computed with a different algorithm is a different row.

---

### Finding 3 — HIGH: No per-symbol/TF write observability — stalled symbols are invisible

**The problem:** `events_consumed_total` and `batch_writes_total` in `FeatureVectorWriter` are aggregate counters. If SPY 5m writes 1000 rows per minute and XLF 5m writes zero (stalled pipeline, bad symbol, deserialization error routing silently to DLQ), Grafana shows healthy aggregate metrics. The XLF stall is invisible until IC training finds the gap — potentially weeks later.

**Concrete fix in `FeatureVectorWriter._parse_payload`:**
Add per-symbol success counter at parse time (we have symbol before it reaches the buffer):
```python
self.rows_parsed_by_symbol.add(1, {"symbol": record.symbol, "tf": record.tf})
```
Add `rows_parsed_by_symbol` counter in `__init__`:
```python
self.rows_parsed_by_symbol = counter(
    "feature_writer_rows_parsed_by_symbol_tf_total",
    "Rows successfully parsed per symbol and timeframe",
)
```

Also add `rows_skipped_total` counter — `ON CONFLICT DO NOTHING` silently discards duplicate rows. asyncpg doesn't report how many rows were skipped. We need a periodic audit query:
```sql
-- Run every 15 min, emit as gauge
SELECT COUNT(*) FROM feature_vectors 
WHERE bar_ts > NOW() - INTERVAL '15 minutes'
  AND symbol = $1 AND tf = $2
```
Or: track expected vs. actual row count per (symbol, tf) from `backfill_status.theoretical_max`.

**Grafana alert:** Alert if `feature_writer_rows_parsed_by_symbol_tf_total{symbol="SPY", tf="5m"}` rate drops to zero for > 10 minutes during market hours.

---

### Finding 4 — HIGH: Lazy import of `FeatureVector` inside hot-path `_parse_payload`

**The problem:**
```python
def _parse_payload(self, payload: dict) -> tuple[list, list]:
    ...
    try:
        ...
        from src.intelligence.schemas import FeatureVector  # ← inside hot loop
        vector = FeatureVector(**vector_data)
```
Python caches module imports after the first call, but `from X import Y` inside a hot loop still performs a `sys.modules` dict lookup + attribute access on every call. At 58 symbols × 1 bar/minute during market hours, this is noise. But it is structurally wrong and the pattern should not propagate to other writers.

**Fix (1 line):** Move `from src.intelligence.schemas import FeatureVector` to the module-level import block at the top of `feature_vector_writer.py`. It is already imported transitively; add the explicit direct import.

---

### Finding 5 — HIGH: `__import__("time")` anti-pattern in flush hot path

**The problem:**
```python
async def _flush_batch(self, batch: list) -> None:
    ...
    _fw_t0 = __import__("time").perf_counter()
    await self.db_manager.execute_batch(...)
    PERSISTENCE_BATCH_LATENCY.record(
        __import__("time").perf_counter() - _fw_t0, ...
    )
```
`__import__` is slower than a pre-imported module reference. Called on every batch flush. Also unreadable.

**Fix:** `import time` at the module level. Replace both occurrences with `time.perf_counter()`.

---

### Finding 6 — HIGH: `FeatureVector` docstring field count is wrong — will cause audit confusion

**The problem:** The `FeatureVector` docstring says "Regime-level (11)" but only 10 fields are present in that group. The Volatility group (2 fields: `atr_z`, `vol_ratio`) is missing entirely from the docstring breakdown. The group sums in the docstring add to 52, not 54. Any future auditor counting docstring groups will get 52, start debugging, and waste time before discovering the docstring is just wrong.

**Fix:** Correct the `FeatureVector` docstring to:
```
Groups and field order are binding (schema column names in feature_vectors):
  Momentum (5): price velocity at two horizons, range, intra-bar close position, gap
  Volume/flow (8): informed flow, volume, OFI, OFI divergence, CVD slope, CMF, rel volume, VWAP dev
  Volatility (2): ATR z-score, short/long vol ratio
  Session-level (4): volume profile POC/VA, S/R proximity
  Regime-level (10): HMM prob/entropy/duration, Hurst, Shannon, GARCH ratio, HMA slope, ADX, Aroon fast/slow
  Oscillators (6): RSI and CCI at fast/mid/slow scales
  Cross-asset (3): VIX z-score, flight-to-quality, yield slope
  Calendar (9): NY/London session, overlap, power hour, opening range, weekly VWAP, dow sin/cos, month position
  Cross-timeframe (3): momentum/VWAP/regime alignment from HTF cache
  Statistical/liquidity (4): Amihud illiquidity, 52w high distance, return skewness, return autocorrelation
  Total: 54
```

---

### Finding 7 — MEDIUM: No `bar_close_ts` — forward return computation has a gap ambiguity

**The problem:** `feature_vectors` has `bar_ts` (open timestamp) but not `bar_close_ts`. The `forward_returns` service (Phase 138 P3) computes `ln(open[T+N+1] / open[T+1])` — entry at next-bar open. For intraday TFs, `T+1` is simply `bar_ts + tf_seconds`. But for daily bars, the "next bar open" is not `bar_ts + 86400s` — it's the next trading day's open, which could be `bar_ts + 86400`, `+ 259200` (Friday→Monday), or longer (holidays). The `forward_returns` service must correctly find the next-bar open; without `bar_close_ts`, it has to query `market_data_ohlcv` for every row to find the next actual bar, which is expensive and adds a join.

**Concrete fix:**
1. Add `bar_close_ts TIMESTAMPTZ NOT NULL` to `feature_vectors` schema.
2. Populate it in `feature_vector_to_insert_params()`:
   - For intraday: `bar_ts + timedelta(seconds=tf_seconds[tf])`
   - For daily: the actual bar close (20:00 ET = 00:00 UTC next day)
3. `forward_returns` service queries: `WHERE bar_ts > prev.bar_close_ts ORDER BY bar_ts LIMIT 1` per symbol/tf — guaranteed to find the correct next bar even across gaps.

This also enables a cheap coverage check: gaps in `feature_vectors` become `MAX(bar_close_ts) - MIN(bar_ts)` vs. `theoretical_max * tf_seconds`.

---

### Finding 8 — MEDIUM: `BaseBatch` plan is missing checkpoint standardization

**The problem:** `backfill_feature_factory.py` implements its own checkpoint pattern via the `backfill_status` table. `BaseBatch` (Phase 138 P1) plans `content_key()`, D-06 emission, and asyncpg pool lifecycle — but not checkpoint/resume. Every future `BaseBatch` subclass will either re-implement its own checkpoint table (introducing drift) or run without checkpointing (meaning a 6-hour IC engine run that fails at hour 5 restarts from zero).

**What to add to `BaseBatch` interface:**
```python
class BaseBatch(ABC):
    # Existing planned interface:
    job_name: str
    compute_version: str

    async def run(self) -> None: ...           # template: setup → execute → teardown + D-06
    async def _setup_pool(self) -> None: ...
    async def _teardown_pool(self) -> None: ...
    def content_key(self, *parts: str) -> str: ...
    def _emit_completion(self, status: str) -> None: ...

    @abstractmethod
    async def execute(self, pool: asyncpg.Pool) -> None: ...

    # ADD: Checkpoint interface (30 lines, eliminates restart bugs for all future subclasses):
    @property
    def _checkpoint_key(self) -> str:
        """Unique key for this run's checkpoint. Default: job_name."""
        return self.job_name

    async def _read_checkpoint(self) -> dict | None:
        """Read last saved checkpoint state. None = start fresh."""

    async def _write_checkpoint(self, state: dict) -> None:
        """Persist checkpoint state atomically for restart recovery."""

    # ADD: Progress gauge (emitted during execute(), not just at D-06 completion):
    def _emit_progress(self, fraction: float, *, items_done: int, items_total: int) -> None:
        """Update job_progress_fraction OTel gauge. Called by subclass during execute()."""
```
Storage: a `batch_job_checkpoints` table (`job_key TEXT PK, state JSONB, updated_at TIMESTAMPTZ`). Migration goes into P1's migration 159.

---

### Finding 9 — MEDIUM: No cross-sectional rank features — major Medallion signal source missing

**The problem:** All 54 features are computed per-symbol independently. A symbol's 5-day return z-score tells you how it moved. It does not tell you how it moved *relative to peers*. Cross-sectional rank features are among the most reliable alpha sources in systematic equity models because they are self-normalizing and regime-invariant. Medallion's documented approach relies heavily on relative measures. Our feature set currently has zero cross-sectional features.

**Three features to add:**
- `momentum_rank_z` — where does this symbol's 5-day return rank among the 58-symbol universe at this bar_ts? Normalized to z-score (0 = bottom quintile, positive = top).
- `volume_rank_z` — cross-sectional relative volume rank.
- `vol_rank_z` — cross-sectional volatility (ATR) rank.

**The architectural challenge:** These require computing across all symbols simultaneously at the same bar_ts, which the current architecture does not support. Each `FeatureVector` is computed independently, symbol by symbol. A "cross-sectional enrichment pass" is needed after all symbols are computed for a given bar_ts.

**Recommended approach:**
1. Add the three columns to `feature_vectors` schema now (nullable, default NULL).
2. Add the three fields to `FeatureVector` with `Optional[float]` (breaking from the "no defaults" contract, but justified — these are computed in a separate pass).
3. Plan the cross-sectional enrichment as a `BaseBatch` subclass in Phase 139: reads all rows for a given bar_ts, computes ranks across symbols, UPDATEs the `_rank_z` columns.
4. IC engine ignores NULLs in Spearman calculation — these features simply have no IC contribution until the enrichment pass runs.

The IC engine will discover whether cross-sectional rank has IC. No researcher judgment required.

---

### Finding 10 — MEDIUM: Block bootstrap block size is TF-agnostic — statistically incorrect

**The problem:** Phase 138 P4 plan uses `alpha.ic.bootstrap_block_size = 10` for all TFs. The purpose of block bootstrap is to preserve the autocorrelation structure of IC over time. The correct block size is `>= 2 × autocorrelation_length_of_IC_series`.

For daily bars: IC autocorrelation length ≈ 5-20 days. Block size 10 is reasonable.
For 5m bars: IC autocorrelation at 5m resolution is much shorter in calendar time, but measured in bar count the autocorrelation could extend 50-100 bars (a trading day = 78 bars at 5m). Block size 10 for 5m massively underestimates the autocorrelation structure, producing falsely narrow bootstrap confidence intervals.

A falsely narrow CI means we accept features as IC-positive that are actually noise. This directly causes ensemble weights to include uninformative features, degrading alpha.

**Fix:** Replace with TF-specific APR keys in migration 160:
```sql
-- alpha.ic.bootstrap_block_size is removed; replaced by TF-specific keys
INSERT INTO config_schema (config_key, value_type, description) VALUES
  ('alpha.ic.bootstrap_block_size.5m',  'int', 'Block bootstrap size for 5m IC estimation [initial_estimate]'),
  ('alpha.ic.bootstrap_block_size.15m', 'int', 'Block bootstrap size for 15m IC estimation [initial_estimate]'),
  ('alpha.ic.bootstrap_block_size.1h',  'int', 'Block bootstrap size for 1h IC estimation [initial_estimate]'),
  ('alpha.ic.bootstrap_block_size.1d',  'int', 'Block bootstrap size for 1d IC estimation [initial_estimate]');

INSERT INTO config_state (config_key, config_value) VALUES
  ('alpha.ic.bootstrap_block_size.5m',  '78'),   -- 1 trading day in 5m bars
  ('alpha.ic.bootstrap_block_size.15m', '26'),   -- 1 trading day in 15m bars
  ('alpha.ic.bootstrap_block_size.1h',  '10'),   -- ~2 trading days in 1h bars
  ('alpha.ic.bootstrap_block_size.1d',  '10');   -- 10 trading days (2 weeks)
```
IC engine reads `cfg.get_sync(f"alpha.ic.bootstrap_block_size.{tf}", 10)` per TF.

---

### Finding 11 — LOW: Two missing momentum horizons weaken the ensemble

**The problem:** We have `momentum_z_5` (short) and `momentum_z_20` (medium). Renaissance and virtually all systematic equity research document momentum persistence across three horizons: 1-month, 3-month, and 12-month. The 12-month-minus-1-month spread (long-term momentum minus short-term reversal) is one of the most empirically robust factors in equity literature (Jegadeesh and Titman, 1993).

**Missing features:**
- `momentum_z_60` — 60-bar return z-score. For daily TF: 3-month momentum. For 1h: 2.5-day.
- `momentum_reversal_z` — negative of `momentum_z_5` conditioned on `momentum_z_60 > 0` (short-term mean reversion within a longer trend). Or simply add the raw `momentum_z_1` (1-bar return z-score) which serves as the reversal signal at short horizons.

These are two additional columns in `FeatureVector`, two additional lines in `FeatureFactory.compute()`, and two entries in the migration. The IC engine will determine whether they have predictive power — no researcher judgment required.

---

### Finding 12 — LOW: Calendar features missing quarterly position and earnings cycle

**What we have:** `dow_sin/cos` (day-of-week encoding), `month_position` (where in the month, 0-1).

**Missing:**
- `quarter_position` — where in the quarter (0-1). Captures earnings seasonality (analysts front-run earnings releases), options expiration clustering (quarterly triple witching), and systematic rebalancing flows.
- `days_to_month_end` (normalized, 0-1) — month-end rebalancing by index funds and pension funds produces predictable price pressure in specific sectors. Highly predictive for ETFs tracking cap-weighted indices.

Both are deterministic calendar computations, zero IO, two lines of Python. No warmup required. Schema adds two float columns.

---

## Prioritization Matrix

| Finding | Severity | Action | Timing |
|---|---|---|---|
| 1 — NaN/Inf in training corpus | CRITICAL | Add validator to persistence module | Before backfill runs |
| 2 — `pipeline_version` ambiguity | CRITICAL | Add `feature_factory_version` field + migration | Phase 138 P1 |
| 3 — No per-symbol observability | HIGH | Add `rows_parsed_by_symbol_tf` counter | Phase 138 or P0 patch |
| 4 — Lazy `FeatureVector` import | HIGH | Move to module-level imports | Before backfill runs |
| 5 — `__import__("time")` in flush | HIGH | `import time` at top | Before backfill runs |
| 6 — Docstring field count wrong | HIGH | Correct docstring breakdown | Before backfill runs |
| 7 — No `bar_close_ts` | MEDIUM | Schema migration, serializer update | Phase 139 |
| 8 — No checkpoint in `BaseBatch` | MEDIUM | Add to P1 plan before building | Phase 138 P1 |
| 9 — No cross-sectional features | MEDIUM | Schema columns now, enrichment later | Phase 139 plan |
| 10 — TF-agnostic bootstrap | MEDIUM | TF-specific APR keys in migration 160 | Phase 138 P1 |
| 11 — Missing momentum horizons | LOW | Add `momentum_z_60`, `momentum_reversal_z` | Phase 138 backfill window |
| 12 — Missing calendar features | LOW | Add `quarter_position`, `days_to_month_end` | Phase 138 backfill window |

---

## Critical Path Before IC Training Data Is Written

The following must be resolved before `backfill_feature_factory.py` runs and before Phase 138 P2-P4 execute. IC rows produced without these fixes cannot be trusted:

1. **Finding 1 (NaN validator)** — without this, degenerate feature rows enter the IC corpus silently.
2. **Finding 2 (`feature_factory_version`)** — without this, algorithm changes produce mixed-version IC estimates.
3. **Finding 10 (TF-specific bootstrap)** — without this, IC confidence intervals for 5m are falsely narrow.

Findings 4, 5, 6 are quick cleanups that should go in the same commit.

Findings 11 and 12 (additional features) should be added to `FeatureVector` and the schema **before** the backfill runs. It is dramatically cheaper to add two columns now and backfill them once than to add them post-backfill and re-run 100M+ rows.

---

## Next Session Starting Point

1. Execute Findings 1, 4, 5, 6 as a single commit (small, clean, no schema changes).
2. Update Phase 138 P1 plan to include: `feature_factory_version` field (Finding 2), checkpoint interface on `BaseBatch` (Finding 8), TF-specific bootstrap APR keys (Finding 10).
3. Decide on Findings 11 and 12 (additional features) — if adding them, do it before the backfill migration runs so we only backfill once.
4. Then execute Phase 138 P1 → P4.

Session command to resume: `/gsd-execute-phase 138`
