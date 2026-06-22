---
phase: 138-ic-engine-forward-returns
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/intelligence/schemas.py
  - src/intelligence/feature_factory.py
  - src/intelligence/features/feature_vector_persistence.py
  - services/feature_vector_writer.py
  - services/backfill_feature_factory.py
  - production/migrations/159_foundation_hardening.sql
autonomous: true

must_haves:
  truths:
    - "validate_feature_vector() exists in feature_vector_persistence.py; raises ValueError listing non-finite field names"
    - "feature_vector_to_insert_params() calls validate_feature_vector() before building the tuple"
    - "FeatureVectorRecord has feature_factory_version: str field on the Kafka wire envelope"
    - "FEATURE_FACTORY_VERSION = '1.0.0' module-level constant in feature_factory.py"
    - "Content-key formula includes feature_factory_version: SHA-256(symbol|tf|bar_ts_ns|pipeline_version|feature_factory_version)"
    - "Both write paths (feature_vector_writer + backfill_feature_factory) pass feature_factory_version into the INSERT tuple"
    - "FeatureVector dataclass has 4 new computed fields: momentum_z_slow, momentum_reversal_z, quarter_position, days_to_month_end"
    - "FeatureVector dataclass has 3 new Optional[float] fields: momentum_rank_z, volume_rank_z, volatility_rank_z (cross-sectional, NULL until Phase 139)"
    - "FeatureFactory.compute() computes all 4 new feature values deterministically for every bar"
    - "FeatureVector docstring field-group breakdown sums to correct total and lists all groups"
    - "feature_vector_writer.py imports FeatureVector at module level, not inside _parse_payload"
    - "feature_vector_writer.py has import time at module level; no __import__() calls"
    - "feature_vector_writer.py has rows_parsed_by_symbol_tf_total counter incremented at parse time"
    - "feature_vectors schema has 9 new columns: feature_factory_version, bar_close_ts, momentum_z_slow, momentum_reversal_z, quarter_position, days_to_month_end, momentum_rank_z, volume_rank_z, volatility_rank_z"
    - "feature_vectors RENAMED columns: momentum_z_5 -> momentum_z_fast, momentum_z_20 -> momentum_z_mid (in same migration 159)"
    - "APR keys renamed: feature.momentum.window_short -> feature.momentum.window_fast, feature.momentum.window_long -> feature.momentum.window_mid (in same migration 159)"
    - "batch_job_checkpoints table exists: job_key TEXT PK, state JSONB, updated_at TIMESTAMPTZ"
    - "feature_vector_to_insert_params() builds 70-element tuple in exact column-definition order"
    - "bar_close_ts populated in INSERT: bar_ts + TF duration for intraday; bar_ts + 1 day for 1d"
  artifacts:
    - path: "production/migrations/159_foundation_hardening.sql"
      provides: "9 new columns on feature_vectors + batch_job_checkpoints table"
      contains: "feature_factory_version"
    - path: "src/intelligence/features/feature_vector_persistence.py"
      provides: "validate_feature_vector(), updated content-key with feature_factory_version, 70-param INSERT tuple"
      contains: "validate_feature_vector"
    - path: "src/intelligence/feature_factory.py"
      provides: "FEATURE_FACTORY_VERSION constant, compute for momentum_z_60/reversal_z/quarter_position/days_to_month_end"
      contains: "FEATURE_FACTORY_VERSION"
    - path: "src/intelligence/schemas.py"
      provides: "FeatureVectorRecord.feature_factory_version, 7 new FeatureVector fields, corrected docstring"
      contains: "feature_factory_version"
    - path: "services/feature_vector_writer.py"
      provides: "module-level imports, rows_parsed_by_symbol_tf_total counter, feature_factory_version wired"
      contains: "rows_parsed_by_symbol_tf_total"
  key_links:
    - from: "feature_factory.py FEATURE_FACTORY_VERSION"
      to: "feature_vector_persistence.py make_feature_vector_id()"
      via: "FeatureVectorRecord.feature_factory_version threaded through both write paths into content-key"
      pattern: "FEATURE_FACTORY_VERSION"
    - from: "validate_feature_vector()"
      to: "feature_vector_to_insert_params() call site"
      via: "raises ValueError on nan/inf; live path raises -> DLQ; batch path catches, logs, increments counter, continues"
      pattern: "validate_feature_vector"
    - from: "FeatureFactory.compute() new fields"
      to: "feature_vectors new schema columns"
      via: "feature_vector_to_insert_params() tuple position must match CREATE TABLE column order in migration 159"
      pattern: "momentum_z_60\|quarter_position"
---

<objective>
Harden the feature vector foundation before backfill runs. The council review (2026-06-22) identified 12 findings across the full write stack — data integrity, algorithm version tracking, observability, compute correctness, and schema completeness. All must be resolved before backfill_feature_factory.py runs because IC rows produced without these fixes cannot be trusted and adding schema columns post-backfill requires a full re-run of 100M+ rows.

The IC engine (P2-P6) depends on every row in feature_vectors being correctly computed, versioned, and complete. This plan is the foundation that makes that true.

Output: hardened write stack with NaN guard, feature_factory_version throughout, 7 new FeatureVector fields computed and persisted, migration 159 applied, feature_vector_to_insert_params() at 70 params, per-symbol observability counter, module-level imports, corrected docstring, batch_job_checkpoints table ready for BaseBatch.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md
@.planning/reviews/2026-06-22-foundation-council-review.md
@CLAUDE.md
@src/intelligence/features/feature_vector_persistence.py
@src/intelligence/schemas.py
@src/intelligence/feature_factory.py
@services/feature_vector_writer.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Code quality fixes — module imports, __import__ anti-pattern, docstring (Findings 4, 5, 6)</name>
  <files>services/feature_vector_writer.py, src/intelligence/schemas.py</files>
  <read_first>
    - services/feature_vector_writer.py (full read — find FeatureVector import inside _parse_payload; find __import__("time") occurrences; understand import block)
    - src/intelligence/schemas.py (find FeatureVector docstring; count fields per group; verify group sums)
  </read_first>
  <action>
    Three targeted fixes — no logic changes:

    1. (Finding 4) In services/feature_vector_writer.py: move `from src.intelligence.schemas import FeatureVector`
       from inside _parse_payload() to the module-level import block at the top of the file.
       The class is already imported transitively; this adds an explicit direct import.

    2. (Finding 5) In services/feature_vector_writer.py: add `import time` to the module-level import block.
       Replace all `__import__("time").perf_counter()` calls in _flush_batch() with `time.perf_counter()`.
       There are exactly 2 occurrences — both must be replaced.

    3. (Finding 6) In src/intelligence/schemas.py: correct the FeatureVector docstring field-group breakdown.
       The current docstring omits the Volatility group and sums to 52 instead of the correct 54.
       Rewrite the breakdown to:
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
       This docstring will need updating again after Task 4 adds 7 new fields — do that in Task 4.
  </action>
  <acceptance_criteria>
    - `grep -n "from src.intelligence.schemas import FeatureVector" services/feature_vector_writer.py` shows the import only at module level (line < 30), not inside any function
    - `grep -c "__import__" services/feature_vector_writer.py` returns 0
    - `grep -c "import time" services/feature_vector_writer.py` returns 1 (module-level)
    - `grep -c "time.perf_counter" services/feature_vector_writer.py` returns 2
    - `.venv/bin/ruff check services/feature_vector_writer.py` passes
    - `grep -c "Total: 54" src/intelligence/schemas.py` returns 1 (docstring updated)
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from services.feature_vector_writer import FeatureVectorWriter; print('ok')"</verify>
  <done>Module-level imports, no __import__, docstring summing to 54 — all three fixes in place.</done>
</task>

<task type="auto">
  <name>Task 2: NaN/Inf validator + per-symbol observability counter (Findings 1, 3)</name>
  <files>src/intelligence/features/feature_vector_persistence.py, services/feature_vector_writer.py</files>
  <read_first>
    - src/intelligence/features/feature_vector_persistence.py (full read — find feature_vector_to_insert_params(); understand how validate would be called; find imports block)
    - services/feature_vector_writer.py (find _parse_payload(); understand where to increment a per-symbol counter; find existing counter definitions)
    - src/observability/metrics.py (counter() factory signature; find a counter definition to mirror)
    - .planning/reviews/2026-06-22-foundation-council-review.md (Finding 1 Option A code; Finding 3 counter name)
  </read_first>
  <action>
    Two additions:

    1. (Finding 1) In src/intelligence/features/feature_vector_persistence.py, add:
       ```python
       import math, dataclasses

       def validate_feature_vector(vector: FeatureVector) -> list[str]:
           """Return list of non-finite field names (empty = clean). Caller decides action."""
           bad = []
           for field in dataclasses.fields(vector):
               v = getattr(vector, field.name)
               if v is not None and not math.isfinite(v):
                   bad.append(field.name)
           return bad
       ```
       (The `v is not None` guard handles Optional[float] fields that will be None for cross-sectional cols.)

       In feature_vector_to_insert_params(), immediately before building the return tuple:
       ```python
       bad = validate_feature_vector(vector)
       if bad:
           raise ValueError(f"Degenerate features (nan/inf): {bad}. symbol={symbol} tf={tf} bar_ts={bar_ts}")
       ```
       This raises ValueError. In the live write path (feature_vector_writer._parse_payload), the existing
       exception handling routes the payload to DLQ — no change needed there. In the batch path
       (backfill_feature_factory), the caller should catch ValueError, log it with symbol/tf/bar_ts,
       increment a skip counter, and continue to the next bar. Check how backfill calls
       feature_vector_to_insert_params() and add the try/except there.

    2. (Finding 3) In services/feature_vector_writer.py, add a per-(symbol, tf) counter:
       In __init__, define:
       ```python
       self._rows_parsed_by_symbol_tf = counter(
           "feature_writer_rows_parsed_by_symbol_tf_total",
           "Rows successfully parsed per symbol and timeframe",
       )
       ```
       (Use the counter() factory from src/observability/metrics.py — find it by reading that file.)
       In _parse_payload(), after successfully constructing the FeatureVectorRecord (before appending
       to the batch), increment:
       ```python
       self._rows_parsed_by_symbol_tf.add(1, {"symbol": record.symbol, "tf": record.tf})
       ```
       Place the increment AFTER successful deserialization so failed parses are not counted.
  </action>
  <acceptance_criteria>
    - `grep -c "validate_feature_vector" src/intelligence/features/feature_vector_persistence.py` returns >= 2 (definition + call)
    - `grep -c "math.isfinite" src/intelligence/features/feature_vector_persistence.py` returns >= 1
    - `.venv/bin/python -c "from src.intelligence.features.feature_vector_persistence import validate_feature_vector; print('ok')"` exits 0
    - `.venv/bin/python -c "
import math, dataclasses
from src.intelligence.features.feature_vector_persistence import validate_feature_vector
from src.intelligence.schemas import FeatureVector
# Build a minimal FeatureVector with one nan field to test validator
import inspect
fields = [f.name for f in dataclasses.fields(FeatureVector)]
vals = {f: 0.0 for f in fields}
vals[fields[0]] = float('nan')
fv = FeatureVector(**vals)
bad = validate_feature_vector(fv)
assert fields[0] in bad, f'expected {fields[0]} in bad fields, got {bad}'
print('validator catches nan: ok')
"` exits 0
    - `grep -c "rows_parsed_by_symbol_tf_total" services/feature_vector_writer.py` returns >= 2 (definition + increment)
    - `.venv/bin/pytest tests/unit/ -q` stays GREEN
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from src.intelligence.features.feature_vector_persistence import validate_feature_vector; print('ok')"</verify>
  <done>validate_feature_vector() raises ValueError on nan/inf before INSERT; per-symbol counter incremented in _parse_payload.</done>
</task>

<task type="auto">
  <name>Task 3: feature_factory_version throughout the full write stack (Finding 2)</name>
  <files>src/intelligence/feature_factory.py, src/intelligence/schemas.py, src/intelligence/features/feature_vector_persistence.py, services/feature_vector_writer.py, services/backfill_feature_factory.py</files>
  <read_first>
    - src/intelligence/feature_factory.py (find existing constants at module level; understand where FeatureVectorRecord is constructed/published)
    - src/intelligence/schemas.py (FeatureVectorRecord dataclass definition; add field here)
    - src/intelligence/features/feature_vector_persistence.py (make_feature_vector_id() — current SHA-256 formula; feature_vector_to_insert_params() signature)
    - services/feature_vector_writer.py (_parse_payload — where FeatureVectorRecord is deserialized from Kafka payload; understand what fields are read)
    - services/backfill_feature_factory.py (_make_feature_vector_id() — the backfill's version of the content key; _serialize_feature_vector() / _vector_to_params())
    - .planning/reviews/2026-06-22-foundation-council-review.md (Finding 2 full spec)
  </read_first>
  <action>
    Thread feature_factory_version through the full stack. Five files, one invariant: every write
    path must include feature_factory_version in both the content-key and the INSERT tuple.

    1. src/intelligence/feature_factory.py — add module-level constant:
       ```python
       FEATURE_FACTORY_VERSION = "1.0.0"
       ```
       Bump this string whenever any feature's computation algorithm changes. Add a comment:
       "Bump on any algorithm change; IC engine filters by version to avoid mixing IC estimates."

    2. src/intelligence/schemas.py — add field to FeatureVectorRecord:
       ```python
       feature_factory_version: str
       ```
       FeatureVectorRecord is the Kafka wire envelope. This field must be set when publishing.
       In feature_factory.py, find where FeatureVectorRecord is constructed and add
       `feature_factory_version=FEATURE_FACTORY_VERSION` to the constructor call.

    3. src/intelligence/features/feature_vector_persistence.py — update make_feature_vector_id():
       Current formula: SHA-256(symbol|tf|bar_ts_ns|pipeline_version)
       New formula: SHA-256(symbol|tf|bar_ts_ns|pipeline_version|feature_factory_version)
       Update the function signature to accept feature_factory_version: str and add it to the
       concatenated key string. Update all call sites in this module.

    4. services/feature_vector_writer.py — in _parse_payload(), extract feature_factory_version
       from the Kafka payload and pass it to make_feature_vector_id() and the INSERT tuple.
       If the field is absent in the payload (old messages), default to "1.0.0".

    5. services/backfill_feature_factory.py — update _make_feature_vector_id() (the local copy
       of the content-key function) to also include feature_factory_version in the SHA-256 input.
       Import FEATURE_FACTORY_VERSION from feature_factory.py and use it.
       Update all call sites in the backfill service.

    Do NOT change what feature_factory_version is set to (it remains "1.0.0") — only wire the
    constant through the infrastructure so future algorithm changes propagate correctly.
  </action>
  <acceptance_criteria>
    - `grep -c "FEATURE_FACTORY_VERSION" src/intelligence/feature_factory.py` returns >= 1
    - `grep -c "feature_factory_version" src/intelligence/schemas.py` returns >= 1 (FeatureVectorRecord field)
    - `grep -c "feature_factory_version" src/intelligence/features/feature_vector_persistence.py` returns >= 3 (function param + key string + any call sites)
    - `grep -c "feature_factory_version" services/feature_vector_writer.py` returns >= 2
    - `grep -c "FEATURE_FACTORY_VERSION\|feature_factory_version" services/backfill_feature_factory.py` returns >= 2
    - Content-key includes version: `.venv/bin/python -c "
from src.intelligence.features.feature_vector_persistence import make_feature_vector_id
import datetime, uuid
ts = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
id1 = make_feature_vector_id('SPY', '5m', ts, '3.0.0', '1.0.0')
id2 = make_feature_vector_id('SPY', '5m', ts, '3.0.0', '2.0.0')
assert id1 != id2, 'different factory versions must produce different content keys'
print('content-key versioning: ok')
"` exits 0
    - `.venv/bin/pytest tests/unit/ -q` stays GREEN
  </acceptance_criteria>
  <verify>.venv/bin/python -c "from src.intelligence.feature_factory import FEATURE_FACTORY_VERSION; print('FEATURE_FACTORY_VERSION =', FEATURE_FACTORY_VERSION)"</verify>
  <done>FEATURE_FACTORY_VERSION constant in feature_factory.py; FeatureVectorRecord carries the field on the wire; content-key formula includes it in both write paths; backfill uses the same constant.</done>
</task>

<task type="auto">
  <name>Task 4: New feature compute + FeatureVector dataclass expansion + naming remediation (Findings 9, 11, 12)</name>
  <files>src/intelligence/feature_factory.py, src/intelligence/schemas.py</files>
  <read_first>
    - src/intelligence/feature_factory.py (full read — find compute() method; find existing momentum_z_5, momentum_z_20 patterns to mirror; find calendar feature section with dow_sin/cos for quarter_position/days_to_month_end)
    - src/intelligence/schemas.py (FeatureVector dataclass — find existing field order; understand frozen=True implications for adding fields; find docstring to update)
    - .planning/reviews/2026-06-22-foundation-council-review.md (Findings 9, 11, 12 full spec)
  </read_first>
  <action>
    Add 7 new fields to FeatureVector and compute 4 of them in FeatureFactory.

    SCHEMAS (src/intelligence/schemas.py):
    NAMING REMEDIATION FIRST (before adding new fields):
    Rename existing momentum_z fields in the FeatureVector dataclass to use scale names,
    consistent with rsi_fast/rsi_mid/rsi_slow and cci_fast/cci_mid/cci_slow patterns:
    - `momentum_z_5` → `momentum_z_fast`  (APR-backed period; fast scale)
    - `momentum_z_20` → `momentum_z_mid`   (APR-backed period; mid scale)

    Add to FeatureVector dataclass — 4 computed float fields (after existing momentum fields):
    ```python
    momentum_z_slow: float      # slow-scale return z-score (APR: feature.momentum.window_slow, default 60)
    momentum_reversal_z: float  # 1-bar return z-score (concept-named: short-term reversal signal)
    ```
    After existing calendar fields (near dow_sin/cos, month_position):
    ```python
    quarter_position: float     # position within the quarter [0, 1]; earnings/rebalancing cycle
    days_to_month_end: float    # (days remaining to month end) / (days in month) [0, 1]
    ```
    3 Optional cross-sectional fields (after all computed fields, at the end of the dataclass):
    ```python
    momentum_rank_z: float | None = None     # cross-sectional rank; populated in Phase 139
    volume_rank_z: float | None = None       # cross-sectional volume rank; populated in Phase 139
    volatility_rank_z: float | None = None   # cross-sectional volatility rank; populated in Phase 139
    ```
    NOTE: frozen=True dataclass does NOT allow default values on non-default fields. The Optional
    fields MUST come after all non-default fields. If the current ordering would cause a TypeError,
    read the existing field order carefully and place the Optional fields last.

    Update the FeatureVector docstring to add the new groups:
    - Extended momentum: momentum_z_60, momentum_reversal_z (add to Momentum group or new subsection)
    - Calendar additions: quarter_position, days_to_month_end (add to Calendar group; update count 9 -> 11)
    - Cross-sectional (3, nullable): momentum_rank_z, volume_rank_z, vol_rank_z
    Update Total accordingly.

    COMPUTE (src/intelligence/feature_factory.py):
    Also rename _FactoryConfig fields and APR key strings:
    - `momentum_window_short` → `momentum_window_fast`  (APR key: feature.momentum.window_fast)
    - `momentum_window_long` → `momentum_window_mid`    (APR key: feature.momentum.window_mid)
    - Add `momentum_window_slow: int  # feature.momentum.window_slow` (default 60)
    Rename all local variables accordingly: `momentum_z_5_val` → `momentum_z_fast_val`, etc.

    Mirror existing momentum z-score pattern for momentum_z_slow:
    - slow-scale log return: ln(close / close_N_bars_ago) where N = config.momentum_window_slow
    - z-score over the same rolling window as momentum_z_fast/momentum_z_mid (APR: feature.momentum.zscore_window)
    - If fewer than momentum_window_slow bars of history available, set to 0.0 (same convention)

    momentum_reversal_z (1-bar return z-score):
    - 1-bar log return: ln(close / close_prev)
    - z-score over rolling 20-bar window (APR: feature.period.momentum.fast, fallback 20)
    - Captures short-term price shock magnitude; sign is direction

    quarter_position (calendar, zero IO):
    - Derive from bar's timestamp: month_in_quarter = (bar_ts.month - 1) % 3  (0, 1, 2)
    - day_in_quarter = month_in_quarter * ~30 + bar_ts.day
    - quarter_position = day_in_quarter / 91.25  (approximate quarter length)
    - Clamp to [0, 1]. Deterministic, no lookback required.

    days_to_month_end (calendar, zero IO):
    - import calendar (stdlib)
    - days_in_month = calendar.monthrange(bar_ts.year, bar_ts.month)[1]
    - days_remaining = days_in_month - bar_ts.day
    - days_to_month_end = days_remaining / days_in_month  (normalized [0, 1])
    - Deterministic, no lookback required.

    Cross-sectional fields (momentum_rank_z, volume_rank_z, vol_rank_z): do NOT compute in
    FeatureFactory.compute(). Leave them as None. They are populated in Phase 139 enrichment pass.
    Ensure FeatureVector construction in compute() passes None for these three fields explicitly.

    Zero hardcoded numerics: any new period or window used for rolling computation must be
    backed by an APR key (cfg.get_sync). Calendar computations (91.25, days_in_month) are
    statistical constants, not tunable parameters — acceptable as module-level constants.
  </action>
  <acceptance_criteria>
    - Old names gone from FeatureVector: `grep -c "momentum_z_5\b\|momentum_z_20\b\|momentum_z_60\|vol_rank_z" src/intelligence/schemas.py` returns 0
    - `grep -c "momentum_z_slow\|momentum_reversal_z\|quarter_position\|days_to_month_end" src/intelligence/schemas.py` returns >= 4
    - `grep -c "momentum_z_fast\|momentum_z_mid" src/intelligence/schemas.py` returns >= 2
    - `grep -c "momentum_rank_z\|volume_rank_z\|volatility_rank_z" src/intelligence/schemas.py` returns >= 3
    - `.venv/bin/python -c "
import dataclasses
from src.intelligence.schemas import FeatureVector
fields = [f.name for f in dataclasses.fields(FeatureVector)]
for name in ['momentum_z_fast', 'momentum_z_mid', 'momentum_z_slow', 'momentum_reversal_z', 'quarter_position', 'days_to_month_end', 'momentum_rank_z', 'volume_rank_z', 'volatility_rank_z']:
    assert name in fields, f'{name} missing from FeatureVector'
for bad in ['momentum_z_5', 'momentum_z_20', 'momentum_z_60', 'vol_rank_z']:
    assert bad not in fields, f'{bad} must be renamed'
print(f'FeatureVector has {len(fields)} fields: ok')
"` exits 0
    - `grep -c "momentum_z_slow\|momentum_reversal_z\|quarter_position\|days_to_month_end" src/intelligence/feature_factory.py` returns >= 4
    - `grep -n "momentum_rank_z\|volume_rank_z\|volatility_rank_z" src/intelligence/feature_factory.py` shows only None assignments (no compute logic)
    - `grep -c "momentum_z_5\b\|momentum_z_20\b\|momentum_window_short\|momentum_window_long" src/intelligence/feature_factory.py` returns 0
    - Optional fields have defaults: `.venv/bin/python -c "
import dataclasses
from src.intelligence.schemas import FeatureVector
opt_fields = [f for f in dataclasses.fields(FeatureVector) if f.name in ('momentum_rank_z','volume_rank_z','volatility_rank_z')]
for f in opt_fields:
    assert f.default is None, f'{f.name} default must be None'
print('optional field defaults: ok')
"` exits 0
    - `.venv/bin/pytest tests/unit/ -q` stays GREEN
  </acceptance_criteria>
  <verify>.venv/bin/python -c "import dataclasses; from src.intelligence.schemas import FeatureVector; print(f'FeatureVector: {len(dataclasses.fields(FeatureVector))} fields')"</verify>
  <done>FeatureVector has 7 new fields; FeatureFactory.compute() computes 4 of them deterministically; 3 cross-sectional fields are None (Phase 139); docstring updated.</done>
</task>

<task type="auto">
  <name>Task 5: Schema migration 159 — feature_vectors DDL hardening + batch_job_checkpoints (Findings 2, 7, 8, 9, 11, 12)</name>
  <files>production/migrations/159_foundation_hardening.sql</files>
  <read_first>
    - production/migrations/158_feature_vector_id.sql (style: comment block, ALTER TABLE pattern, index pattern)
    - production/migrations/156_feature_vectors_expand.sql (column definition style, NOT NULL defaults, nullability conventions)
    - .planning/reviews/2026-06-22-foundation-council-review.md (Findings 2, 7, 8, 9, 11, 12 for exact column specs)
  </read_first>
  <action>
    Create production/migrations/159_foundation_hardening.sql.

    Header comment block (mirror style of 158):
    -- Migration 159: Foundation hardening — feature_vectors naming remediation + schema expansion + batch_job_checkpoints
    -- Covers: momentum_z column renaming (5->fast, 20->mid), APR key renaming,
    --   council review findings: F2 (feature_factory_version), F7 (bar_close_ts),
    --   F8 (batch_job_checkpoints), F9 (cross-sectional nullables), F11 (momentum), F12 (calendar)
    -- Applied before backfill_feature_factory runs so all columns are correct from the first write.

    FIRST — naming remediation (before ADD COLUMN):
    -- Column names must encode scale (concept), not period (tunable parameter).
    -- Pattern: rsi_fast/rsi_mid/rsi_slow; cci_fast/cci_mid/cci_slow. Momentum follows same.
    ALTER TABLE feature_vectors RENAME COLUMN momentum_z_5 TO momentum_z_fast;
    ALTER TABLE feature_vectors RENAME COLUMN momentum_z_20 TO momentum_z_mid;

    -- APR key rename for consistency (period values live in APR, not schema or key names)
    UPDATE config_schema SET config_key = 'feature.momentum.window_fast'
      WHERE config_key = 'feature.momentum.window_short';
    UPDATE config_state  SET config_key = 'feature.momentum.window_fast'
      WHERE config_key = 'feature.momentum.window_short';
    UPDATE config_schema SET config_key = 'feature.momentum.window_mid'
      WHERE config_key = 'feature.momentum.window_long';
    UPDATE config_state  SET config_key = 'feature.momentum.window_mid'
      WHERE config_key = 'feature.momentum.window_long';

    THEN — ADD COLUMN IF NOT EXISTS:
    1. feature_factory_version VARCHAR(32) NOT NULL DEFAULT '1.0.0'
       -- Algorithm version; bump FEATURE_FACTORY_VERSION in feature_factory.py on any compute change.
       -- DEFAULT '1.0.0' applies to any existing rows (pre-migration rows are version 1.0.0 by definition).
    2. bar_close_ts TIMESTAMPTZ
       -- Bar close timestamp for forward return next-bar lookup.
       -- NULL on pre-migration rows; populated on all new writes. Consider NOT NULL constraint in Phase 139.
    3. momentum_z_slow DOUBLE PRECISION
       -- Slow-scale return z-score (APR: feature.momentum.window_slow, default 60 bars). NULL on pre-migration rows.
    4. momentum_reversal_z DOUBLE PRECISION
       -- 1-bar return z-score (short-term reversal, concept-named). NULL on pre-migration rows.
    5. quarter_position DOUBLE PRECISION
       -- Position within calendar quarter [0, 1]. NULL on pre-migration rows.
    6. days_to_month_end DOUBLE PRECISION
       -- Normalized days remaining to month end [0, 1]. NULL on pre-migration rows.
    7. momentum_rank_z DOUBLE PRECISION
       -- Cross-sectional momentum rank z-score. Populated by Phase 139 enrichment pass. NULL = not enriched.
    8. volume_rank_z DOUBLE PRECISION
       -- Cross-sectional volume rank z-score. Populated by Phase 139 enrichment pass.
    9. volatility_rank_z DOUBLE PRECISION
       -- Cross-sectional volatility rank z-score. Populated by Phase 139 enrichment pass.

    CREATE TABLE IF NOT EXISTS batch_job_checkpoints (
        job_key TEXT PRIMARY KEY,
        state JSONB NOT NULL DEFAULT '{}',
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    -- Checkpoint store for BaseBatch subclasses. BaseBatch._write_checkpoint() upserts here.
    -- BaseBatch._read_checkpoint() reads from here at startup; None = start fresh.

    Apply the migration:
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/159_foundation_hardening.sql
  </action>
  <acceptance_criteria>
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d feature_vectors"` shows momentum_z_fast, momentum_z_mid (renamed) and all 9 new columns (momentum_z_slow, volatility_rank_z, etc.)
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM information_schema.columns WHERE table_name='feature_vectors' AND column_name IN ('momentum_z_5','momentum_z_20','vol_rank_z');"` returns 0 (old names gone)
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT column_name FROM information_schema.columns WHERE table_name='feature_vectors' AND column_name='feature_factory_version';"` returns 1 row
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT column_default FROM information_schema.columns WHERE table_name='feature_vectors' AND column_name='feature_factory_version';"` contains '1.0.0'
    - APR keys renamed: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM config_state WHERE config_key IN ('feature.momentum.window_short','feature.momentum.window_long');"` returns 0
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "SELECT count(*) FROM information_schema.tables WHERE table_name='batch_job_checkpoints';"` returns 1
    - `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d batch_job_checkpoints"` shows job_key TEXT PK, state JSONB, updated_at TIMESTAMPTZ
    - migration file exists: `ls production/migrations/159_foundation_hardening.sql`
  </acceptance_criteria>
  <verify>PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name='feature_vectors' ORDER BY ordinal_position;" | tail -15</verify>
  <done>Migration 159 applied; 9 new columns on feature_vectors with correct nullability; batch_job_checkpoints table created.</done>
</task>

<task type="auto">
  <name>Task 6: Wire expanded INSERT tuple + bar_close_ts population + tests green (Findings 7, all)</name>
  <files>src/intelligence/features/feature_vector_persistence.py, services/backfill_feature_factory.py, tests/unit/services/test_feature_vector_writer.py, tests/unit/services/test_feature_vector_writer_column_mapping.py, tests/unit/services/test_backfill_feature_factory.py</files>
  <read_first>
    - src/intelligence/features/feature_vector_persistence.py (feature_vector_to_insert_params() — current 61-element tuple; INSERT SQL string — must be extended to 70 params)
    - services/backfill_feature_factory.py (_serialize_feature_vector() / _vector_to_params() — the batch path equivalent; find bar_ts and tf available at call site for bar_close_ts)
    - tests/unit/services/test_feature_vector_writer_column_mapping.py (pins exact column index per field — must be updated for all new fields)
    - tests/unit/services/test_feature_vector_writer.py (tuple length assertion: currently 61 -> must become 70)
    - tests/unit/services/test_backfill_feature_factory.py (tuple length assertion for batch path)
    - CLAUDE.md (APR rules; timestamp handling; no hardcoded numeric thresholds)
  </read_first>
  <action>
    Expand feature_vector_to_insert_params() and the INSERT SQL to include all 9 new columns.
    Column order in the tuple MUST match the column order in the INSERT SQL which MUST match
    the column definition order in migration 159.

    CANONICAL COLUMN ORDER (total 70 params):
    $1  feature_vector_id      -- content-key UUID (from P0)
    $2  symbol
    $3  tf
    $4  bar_ts
    $5  pipeline_version
    $6  feature_factory_version  -- NEW (Finding 2)
    $7  regime
    $8  regime_label_source
    $9-$62  54 original feature columns (in exact existing order — do not reorder)
    $63 bar_close_ts            -- NEW (Finding 7)
    $64 momentum_z_slow         -- NEW (Finding 11; scale name, APR-backed period)
    $65 momentum_reversal_z     -- NEW (Finding 11; concept-named)
    $66 quarter_position        -- NEW (Finding 12)
    $67 days_to_month_end       -- NEW (Finding 12)
    $68 momentum_rank_z         -- NEW (Finding 9, nullable)
    $69 volume_rank_z           -- NEW (Finding 9, nullable)
    $70 volatility_rank_z       -- NEW (Finding 9, nullable; NOT vol_rank_z)

    bar_close_ts computation (Finding 7):
    Define a module-level mapping in feature_vector_persistence.py:
    ```python
    _TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    ```
    In the INSERT params:
    - For intraday TFs: bar_close_ts = bar_ts + timedelta(seconds=_TF_SECONDS[tf])
    - For "1d": bar_close_ts = bar_ts.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
      (daily bar closes at midnight UTC = 20:00 ET)
    - If tf not in _TF_SECONDS: raise ValueError(f"Unknown tf for bar_close_ts: {tf}")

    UPDATE INSERT SQL: extend the column list and $-placeholders to 70.

    UPDATE the backfill_feature_factory batch path equivalently:
    - _vector_to_params() (or _serialize_feature_vector()) must also produce 70 elements
    - bar_close_ts: same computation using the same _TF_SECONDS mapping (import from persistence module
      or define the same mapping locally — either is acceptable)
    - feature_factory_version: use the imported FEATURE_FACTORY_VERSION constant

    UPDATE TESTS:
    - test_feature_vector_writer.py: change tuple length assertion from 61 to 70
    - test_feature_vector_writer_column_mapping.py: add index assertions for all 9 new columns
      ($6=5 for feature_factory_version, $63=62 for bar_close_ts, $64-70=63-69 for new features)
    - test_backfill_feature_factory.py: update tuple length assertion to 70

    Run: .venv/bin/pytest tests/unit/ -q
    All tests must pass before this task is done.
  </action>
  <acceptance_criteria>
    - `grep -c "feature_factory_version\|bar_close_ts\|momentum_z_slow\|quarter_position\|momentum_rank_z" src/intelligence/features/feature_vector_persistence.py` returns >= 5 (one per new field in params)
    - `grep -c "momentum_z_5\b\|momentum_z_20\b\|vol_rank_z" src/intelligence/features/feature_vector_persistence.py` returns 0 (old names gone)
    - `.venv/bin/python -c "
from src.intelligence.features.feature_vector_persistence import feature_vector_to_insert_params
import inspect
sig = inspect.signature(feature_vector_to_insert_params)
print('params:', list(sig.parameters.keys()))
"` shows feature_factory_version in the parameter list
    - `.venv/bin/python -c "
import dataclasses, datetime
from src.intelligence.schemas import FeatureVector
from src.intelligence.features.feature_vector_persistence import feature_vector_to_insert_params
fields = [f.name for f in dataclasses.fields(FeatureVector)]
vals = {f: 0.0 for f in fields if f not in ('momentum_rank_z','volume_rank_z','vol_rank_z')}
vals.update({'momentum_rank_z': None, 'volume_rank_z': None, 'volatility_rank_z': None})
fv = FeatureVector(**vals)
import uuid
bar_ts = datetime.datetime(2024,1,1,tzinfo=datetime.timezone.utc)
row = feature_vector_to_insert_params(fv, 'SPY', '5m', bar_ts, '3.0.0', '1.0.0')
assert len(row) == 70, f'expected 70, got {len(row)}'
print('70-param tuple: ok')
"` exits 0
    - `grep -c "assert len.*70\|== 70" tests/unit/services/test_feature_vector_writer.py` returns >= 1
    - `grep -c "assert len.*70\|== 70" tests/unit/services/test_backfill_feature_factory.py` returns >= 1
    - `.venv/bin/pytest tests/unit/ -q` GREEN (all passing)
  </acceptance_criteria>
  <verify>.venv/bin/pytest tests/unit/ -q 2>&1 | tail -5</verify>
  <done>70-param INSERT tuple in both write paths; bar_close_ts computed correctly; all 9 new columns wired; unit tests green.</done>
</task>

</tasks>

<verification>
- validate_feature_vector() raises ValueError on nan/inf before any INSERT in both write paths
- FEATURE_FACTORY_VERSION = "1.0.0" in feature_factory.py; in content-key; in FeatureVectorRecord; in INSERT tuple
- momentum_z_5/20 renamed to momentum_z_fast/mid in DB and all code; no old names in src/services/tests/docs
- FeatureVector has 7 new fields (4 computed, 3 Optional[float]); FeatureFactory.compute() produces all 4; all use scale names
- Migration 159 applied: 2 columns renamed, APR keys renamed, 9 new columns added, batch_job_checkpoints table exists
- feature_vector_to_insert_params() produces 70-element tuple; INSERT SQL matches
- bar_close_ts populated correctly for all TFs
- feature_vector_writer.py: module-level imports, no __import__, per-symbol counter
- .venv/bin/pytest tests/unit/ -q GREEN
</verification>

<success_criteria>
- All 6 task acceptance criteria pass
- .venv/bin/pytest tests/unit/ -q GREEN
- .venv/bin/ruff check src/intelligence/features/feature_vector_persistence.py src/intelligence/feature_factory.py src/intelligence/schemas.py services/feature_vector_writer.py passes
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-01-SUMMARY.md` documenting:
- Which council review findings were addressed (1-6, 7, 8-partial, 9, 11, 12)
- Final FeatureVector field count
- Migration 159 columns applied
- Any pre-existing test failures that were out of scope
</output>
