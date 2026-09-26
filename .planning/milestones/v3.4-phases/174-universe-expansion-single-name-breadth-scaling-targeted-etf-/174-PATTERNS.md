# Phase 174: Universe Expansion - Pattern Map

**Mapped:** 2026-09-15
**Files analyzed:** 10 (3 modified source files, 3-4 new migrations, 1 new script, 3 new/extended test files)
**Analogs found:** 9 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `services/_batch_utils.py` (`Float32ChunkAccumulator`, add `disk_backed` mode) | utility | batch/transform | same class, existing in-RAM mode (same file, lines 1029-1074) | exact (extending existing class) |
| `services/ic_engine.py` (`_compute_cross_sectional_tf` pre-flight estimate) | service (batch compute) | batch | `_check_cell_size` + its existing post-materialization call site (same file, lines 1020-1030, 3614) | exact (same guard function, new call site) |
| `services/ic_engine.py` (`_compute_one_cross_sectional_cell` — `X_nd` copy fix) | service (batch compute) | batch | same function's existing `X_sub` slice-not-fancy-index fix, lines 3646-3653 | exact (documented precedent for the identical numpy-copy problem) |
| `src/config/settings.py` (`get_active_contracts`, add `dimension` param) | config/utility | request-response (in-process) | same function, existing signature + sibling `get_all_futures_contracts` (same file, lines 476-620) | exact (extending existing function + established sibling-function convention) |
| `production/migrations/336_instruments_governance_split.sql` (new) | migration | CRUD (DDL) | migration 307 (`regime_volatility_schema_apr_cvr.sql`) — additive DDL block | exact (multi-block additive-migration shape) |
| `production/migrations/337_universe_apr_keys.sql` (new) | migration | CRUD (DDL) | migration 307's Block 2 (APR key INSERT pattern) | exact |
| `production/migrations/338_etf_gap_fill_tags.sql` (new) | migration | CRUD (DDL) | migration 296 (`single_name_equity_sector_orthogonality_expansion.sql`) | exact (instrument + tag onboarding shape) |
| `scripts/infrastructure/universe_expansion_stratified_sourcing.py` (new, one-off) | utility/script | batch (fetch → transform → write) | `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` (bootstrap/argparse/logging shape) + `scripts/analysis/ic_sharpe_stride_bias_check.py` (APR-seeded RNG pattern) | role-match (no direct external-CSV-sourcing analog exists in the codebase) |
| `tests/unit/test_batch_utils.py` (extend `TestFloat32ChunkAccumulator`) | test | batch/transform | same file, `TestFloat32ChunkAccumulator` class, lines 272-312 | exact |
| `tests/unit/services/test_settings_active_contracts_dimension.py` (new, or extend existing) | test | request-response | `tests/unit/services/test_service_contract_resolution.py` (mocking shape for `get_active_contracts`) | exact |

## Pattern Assignments

### `services/_batch_utils.py` — `Float32ChunkAccumulator` disk-backed mode (utility, batch/transform)

**Analog:** same class, in-RAM mode, `services/_batch_utils.py` lines 1029-1074.

**Current shape to extend** (lines 1048-1074):
```python
def __init__(self, flush_at: int | None = None) -> None:
    self._flush_at = flush_at
    self._chunks: list[np.ndarray] = []
    self._buf: list = []

def append_row(self, row: Any) -> None:
    self._buf.append(row)
    if self._flush_at is not None and len(self._buf) >= self._flush_at:
        self._flush_buf()

def append_chunk(self, rows: Any) -> None:
    if len(rows):
        self._chunks.append(np.array(rows, dtype=np.float32))

def _flush_buf(self) -> None:
    if self._buf:
        self._chunks.append(np.array(self._buf, dtype=np.float32))
        self._buf = []

def finalize(self) -> np.ndarray | None:
    """vstack every chunk and free them; None if nothing was ever appended."""
    self._flush_buf()
    if not self._chunks:
        return None
    result = np.vstack(self._chunks)
    self._chunks = []
    return result
```

**Docstring convention to match** (lines 1029-1046): every class-level comment names the specific todo, both call sites (`_compute_symbol_tf` streaming-cursor, `_compute_cross_sectional_tf` chunked-fetch), and why the two callers share this one buffer-bookkeeping class rather than duplicating it. The new `disk_backed` mode's docstring addition should follow this same "name the todo (371), name D-04, explain why additive not a fork" convention — RESEARCH.md's Don't-Hand-Roll table explicitly warns against a parallel/forked accumulator class (the exact mistake migration 249 already fixed once for `_check_cell_size`).

**Constructor extension pattern (additive, existing callers unaffected)** — this is a *design sketch* already validated in RESEARCH.md's Code Examples section; treat it as the concrete pattern to implement, not just inspiration:
```python
def __init__(
    self,
    flush_at: int | None = None,
    *,
    disk_backed: bool = False,
    estimated_rows: int | None = None,
    n_cols: int | None = None,
    scratch_dir: str | None = None,
) -> None:
    self._flush_at = flush_at
    self._chunks: list[np.ndarray] = []
    self._buf: list = []
    self._disk_backed = disk_backed
    self._write_offset = 0
    if disk_backed:
        if not estimated_rows or not n_cols:
            raise ValueError("disk_backed mode requires estimated_rows and n_cols")
        self._tmpfile = tempfile.NamedTemporaryFile(
            dir=scratch_dir, suffix=".memmap", delete=False
        )
        self._memmap = np.memmap(
            self._tmpfile.name, dtype=np.float32, mode="w+",
            shape=(estimated_rows, n_cols),
        )
```
`append_chunk()`/`finalize()` extend with an `if self._disk_backed:` branch — write directly at `self._write_offset` into the memmap, `finalize()` returns `self._memmap[: self._write_offset]` (a view, no vstack/copy) instead of `np.vstack(self._chunks)`. Existing `append_row`/`append_chunk`/`finalize()` public API signatures do not change — the per-symbol streaming caller (`_compute_symbol_tf`) is unaffected by default (`disk_backed=False`).

**Error handling / exception naming (project-wide rule, applies to any new `except` block in the memmap path):** `except X as error:` — not `exc`.

**Cleanup requirement (from RESEARCH.md's DAG diagram):** the memmap scratch file must be deleted in a `finally` block by the caller (`_compute_cross_sectional_tf`) after each cell — do not accumulate scratch files across a multi-day corpus run.

---

### `services/ic_engine.py` — pre-flight cell-size estimate (service, batch compute)

**Analog:** `_check_cell_size` (lines 1020-1030) and its existing post-materialization call site (line 3614, inside `_compute_one_cross_sectional_cell`).

**Existing guard function to reuse unchanged** (lines 1020-1030):
```python
def _check_cell_size(n_rows: int, config: ICEngineConfig, context_label: str) -> None:
    """Crash-loud row-count ceiling (162-01 Task 3, todo 140) -- fails loud rather
    than silently routing an oversized cell to an alternate/degraded algorithm.
    Shared by the per-symbol and cross-sectional cell computes (162 simplify-pass;
    previously this exact check was copy-pasted at both call sites).
    """
    if config.max_cell_rows and n_rows > config.max_cell_rows:
        raise CellTooLargeError(
            f"{context_label} has {n_rows} rows, exceeding "
            f"alpha.ic.max_cell_rows={config.max_cell_rows}."
        )
```

**New call site** — insert immediately after the existing `regime_timestamps` fetch in `_compute_cross_sectional_tf` (current line ~4398, right before the `if not regime_timestamps: return` early-exit at line 4401):
```python
n_estimated = len(regime_timestamps) * len(symbol_list)
_check_cell_size(
    n_estimated, config,
    f"Cross-sectional cell (pre-flight estimate) tf={tf} regime={regime_label}",
)
```
This is a second call to the SAME shared function — do not write a new guard. Matches the existing docstring's own stated intent ("Shared by the per-symbol and cross-sectional cell computes... previously this exact check was copy-pasted at both call sites") — a pre-flight call is a third call site of the same shared function, not a new implementation.

**Context-label convention to match:** every `_check_cell_size` call site's `context_label` embeds `tf=` and `regime=` (see line 3614: `f"Cross-sectional cell tf={tf} regime={regime_label}"`) — the new pre-flight call must follow the identical f-string shape, differentiated only by the `(pre-flight estimate)` marker so log/error output makes clear which of the two guard invocations fired.

---

### `services/ic_engine.py` — `X_nd` boolean-index copy fix (service, batch compute)

**Analog:** the SAME function's existing `X_sub` fix, `_compute_one_cross_sectional_cell` lines 3641-3653 — this is the in-file precedent for exactly this class of numpy-copy problem, already applied once and documented.

**Existing precedent (already-correct fix, read as the pattern to replicate for `X_nd`):**
```python
# Slice, not fancy-index (2026-07-19 OOM fix): regular-stride subsampling
# is exactly expressible as a basic slice, which numpy returns as a VIEW
# sharing memory with X_raw/X_nd -- arr[np.arange(0, n, stride)] would
# instead allocate a full copy. Eliminates 2 more full-cell-sized
# allocations from the peak (alongside the rankdata float32 cast below)
# for the largest cross-sectional cells.
X_sub = X_raw[0:n_raw:scale_stride]
```

**The unfixed defeat point to address (line 3630):**
```python
cluster_input_mask = non_degenerate_mask & ~broadcast_mask
X_nd = X_raw[:, cluster_input_mask]   # boolean column index -- ALWAYS copies, even on a memmap
```

**Recommended fix shape** (per RESEARCH.md Pitfall 1 — block-column-chunking, matching an existing project precedent at `feature_block_columns: int = 32`, line 637, "bounds peak transient memory to O(n_sub x block) instead of O(n_sub x n_features)"): build `X_nd` as a second memmap, written column-block-by-column-block, rather than one boolean-index call. Do NOT declare D-04 complete by fixing `Float32ChunkAccumulator.finalize()` alone — this second copy point must also be addressed or measured-safe at the largest known cell size (`5m/high_bear`, ~64M rows × ~250 features).

**Exception naming:** any new `try/except` in this path uses `except X as error:`.

---

### `src/config/settings.py` — `get_active_contracts()` `dimension` parameter (config/utility, request-response)

**Analog:** the function itself (lines 476-599) plus its documented sibling-function convention (`get_all_futures_contracts`, line 602).

**Current signature and query shape to extend** (lines 476, 524-530):
```python
def get_active_contracts(settings: Settings | None = None) -> list[Instrument]:
    ...
    # 3. Non-futures (equities, FX, crypto) from instruments table
    cur.execute(
        "SELECT symbol, base, contract_details "
        "FROM instruments "
        "WHERE is_active = true AND contract_details->>'asset_class' != 'futures'"
    )
    nf_rows = cur.fetchall()
```

**Extension pattern (from RESEARCH.md, validated against the actual function body read this session):**
```python
def get_active_contracts(
    settings: Settings | None = None,
    dimension: str = "compute",  # NEW -- "backfill" | "compute" | "live"
) -> list[Instrument]:
    ...
    dimension_clause = {
        "backfill": "is_active = true",
        "compute": "is_active = true AND compute_eligible = true",
        "live": "is_active = true AND compute_eligible = true AND live_tradeable = true",
    }[dimension]
```
Critical constraint: the migration (see `336_instruments_governance_split.sql` below) MUST set `compute_eligible=true` for all 231 existing rows so `dimension="compute"` (the new default) is behaviorally IDENTICAL to today's unparameterized call for every existing caller (~25 call sites, per RESEARCH.md's Pattern 1 note and Assumption A5) — this equivalence needs a regression test (see Test Assignment below) before merging, not just an assertion in a comment.

**Error handling pattern already in the function (unchanged, reuse as-is)** (lines 584-599):
```python
except Exception as error:
    import structlog as _structlog

    _structlog.get_logger(__name__).warning(
        "get_active_contracts.db_query_failed",
        error=str(error),
    )
    # Fallback: return last valid cache if warm; never consult s.contracts
    with _settings_lock:
        if _active_contracts_cache is not None:
            return _active_contracts_cache
    _structlog.get_logger(__name__).critical(
        "get_active_contracts.cold_start_db_unavailable",
        error=str(error),
    )
    return []
```
Note the project's `except X as error:` convention is already followed here — matches the mandate.

**Sibling-function convention** (line 602 area) — if the planner chooses a separate function instead of a `dimension=` param for `get_backfill_eligible_contracts()`, `get_all_futures_contracts(settings)` at line 602 is the existing precedent for a "same shape, different filter" sibling function docstring convention ("Same as get_active_contracts() but queries without the is_front_month filter").

---

### `production/migrations/336_instruments_governance_split.sql` (new) — additive schema split (migration, CRUD/DDL)

**Analog:** migration 307 (`production/migrations/307_regime_volatility_schema_apr_cvr.sql`), full file read — chosen because it demonstrates the exact "additive DDL block, idempotent, ON CONFLICT DO NOTHING, explicit backfill UPDATE even where DEFAULT would suffice" pattern D-07 needs, and its header comment style (explain what's NOT being done and why) matches this project's documentation standard.

**DDL block pattern to copy** (migration 307, lines 75-83, adapted shape):
```sql
ALTER TABLE instruments
    ADD COLUMN IF NOT EXISTS compute_eligible boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS live_tradeable   boolean NOT NULL DEFAULT false;

-- Explicit backfill statement (redundant with DEFAULT but explicit per CLAUDE.md's
-- "silent wrong answers are worse than loud crashes" -- makes the semantic mapping
-- decision a visible, reviewable SQL statement, not an implicit column default):
UPDATE instruments SET compute_eligible = true, live_tradeable = false WHERE is_active = true;
```

**Idempotency convention** (migration 307's closing comment, lines 67-69): "All three blocks idempotent: DDL uses ADD COLUMN IF NOT EXISTS (migration 158's pattern); APR uses ON CONFLICT (config_key) DO NOTHING (migration 292's pattern); CVR uses ON CONFLICT (namespace, code) DO NOTHING (migration 233's pattern). Safe to re-run." — every new migration this phase should carry the equivalent statement.

**Header-comment convention to match** (migration 307, lines 1-70): explain the rationale block-by-block, explicitly list what was deliberately NOT created/changed and why (e.g. "Deliberately NOT created: alpha.hmm_volatility.walk_forward.enabled... regime_volatility is a brand-new column with no legacy corpus to protect"). Phase 174's migration should explain, per RESEARCH.md's Pattern 1: why `is_active` is left untouched (25 call sites, already means "backfill-eligible" in practice), and the default semantics chosen for existing rows.

**Instrument onboarding INSERT shape (for the Russell 3000 sample + ETF rows, same migration or a follow-up one)** — analog: migration 296, lines 85-134 (`INSERT INTO instruments (symbol, base, contract_details, is_active) VALUES ...`):
```sql
INSERT INTO instruments (symbol, base, contract_details, is_active) VALUES
    ('URA', 'URA', '{"symbol":"URA","base":"URA","name":"Global X Uranium ETF","asset_class":"equity","exchange":"SMART","sector":"uranium_miners","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true)
ON CONFLICT (symbol) DO NOTHING;
```
`contract_details` JSONB shape is fixed across all 42 rows in migration 296 — reuse this exact key set (`symbol`, `base`, `name`, `asset_class`, `exchange`, `sector`, `tick_size`, `session_id`, `point_value`, `provider_meta`) for every new instrument this phase adds, whether sourced by the stratified-sampling script or hand-written for the 2 gap-fill ETFs.

---

### `production/migrations/337_universe_apr_keys.sql` (new) — APR key registration (migration, CRUD/DDL)

**Analog:** migration 307's Block 2 (lines 85-138) — the canonical `config_schema` + `config_state` paired-INSERT pattern for new (not recalibrated) APR keys.

**Pattern to copy exactly:**
```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.ic_engine.memmap_scratch_dir',
    'str',
    '/tmp/ic_engine_scratch',
    NULL, NULL,
    '[initial_estimate] Phase 174 (D-04): scratch directory for the disk-backed '
    'Float32ChunkAccumulator memmap files used by cross-sectional cell compute at '
    'universe scale. Not an ML learning target.'
),
(
    'alpha.universe.stratified_sample_random_state',
    'int',
    '42',
    NULL, NULL,
    '[user_preference] Phase 174 (D-02): RNG seed for the market-cap-stratified '
    'random sample drawn from the Russell 3000 population. Changing this value '
    'invalidates the sample''s reproducibility -- re-running the sourcing script '
    'with a different seed draws a different, non-comparable sample. Not an ML '
    'learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.ic_engine.memmap_scratch_dir', '/tmp/ic_engine_scratch', 1),
('alpha.universe.stratified_sample_random_state', '42', 1)
ON CONFLICT (config_key) DO NOTHING;
```
**Namespace constraint (RESEARCH.md, hard rule):** there is no `universe.` prefix in `ConfigService.OPS_PREFIXES`. Sampling-methodology keys MUST live under `alpha.*` (e.g. `alpha.universe.*`); OOM-fix keys under `infra.*` (e.g. `infra.ic_engine.*`). Any key drafted outside this allowlist will not load via `ConfigService.get()`.

**Description-provenance tag convention** (CLAUDE.md APR section, already demonstrated in migration 307's `[rca_analysis]` tags): every new key's description must open with one of `[initial_estimate]`, `[conventional]`, `[rca_analysis]`, or `[user_preference]` and state whether it's an ML learning target — the RNG seed is explicitly `[user_preference]`/not-ML-target per CLAUDE.md's "Seeds that affect algorithm output" APR category.

---

### `production/migrations/338_etf_gap_fill_tags.sql` (new) — ETF onboarding + tag registration (migration, CRUD/DDL)

**Analog:** migration 296 in full — same shape as the instrument+tag INSERT pattern above, but scoped to ~2 EM-FX/vol-proxy ETFs instead of 42 single names (per RESEARCH.md's Critical Correction, momentum/quality tickers are NOT needed — MTUM/QUAL/USMV already exist and are backfilled).

**Tag INSERT pattern to copy** (migration 296, lines 143-227):
```sql
INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
    ('EMLC', 'fx_em', 1.0, 'human', '{"reason": "EM local-currency sovereign bond ETF -- proxy for EM-FX exposure, layered with EM sovereign credit + duration risk"}'),
    ('VIXY', 'vol_proxy', 1.0, 'human', '{"reason": "VIX front-month futures ETF -- volatility exposure proxy, no real futures curve infra required"}')
ON CONFLICT (symbol, tag) DO NOTHING;
```
**New `tag_vocabulary` rows first** (if `fx_em`/`vol_proxy` don't already exist as usable tags — confirm live before writing, per RESEARCH.md's Open Question 4) — analog: migration 296 lines 68-70 (`commodity_uranium` addition):
```sql
INSERT INTO tag_vocabulary (tag, category, description) VALUES
    ('fx_em', 'exposure', 'Emerging-market currency exposure -- distinct from developed-market fx_* tags (UUP/FXE/FXY/FXA/FXC), driven by EM rate-differential and capital-flow dynamics rather than developed-market monetary policy.')
ON CONFLICT (tag) DO NOTHING;
```

**`instrument_metadata` stub row (D-08 requirement — every new instrument, no exceptions)** — analog: migration 150 (`production/migrations/150_instrument_metadata.sql`), lines 29-35, the table's original seed-row pattern:
```sql
INSERT INTO instrument_metadata (symbol, listing_date, underlying_index, issuer, description) VALUES
    ('EMLC', '2010-07-22', NULL, 'VanEck', 'VanEck JPM EM Local Currency Bond ETF -- EM-FX + sovereign credit proxy')
ON CONFLICT (symbol) DO UPDATE SET
    listing_date = EXCLUDED.listing_date,
    underlying_index = EXCLUDED.underlying_index,
    issuer = EXCLUDED.issuer,
    description = EXCLUDED.description,
    updated_at = NOW();
```
This is the exact gap todo 282/D-08 exists to close — every migration or script that inserts into `instruments` this phase must pair it with an `instrument_metadata` row (or a visibly logged, explicit skip reason), never a silent omission.

---

### `scripts/infrastructure/universe_expansion_stratified_sourcing.py` (new, one-off) — sourcing/stratification script (utility/script, batch)

**No direct analog exists in the codebase** for "download external constituent file → stratify → write onboarding rows" — flagged below in No Analog Found. Two partial analogs cover distinct sub-patterns:

**Analog 1 (bootstrap/argparse/structlog shape):** `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`, lines 1-60.
```python
# sys.path bootstrap -- count parents carefully (this file's actual depth from repo root)
project_root = Path(__file__).parent.parent.parent.parent  # adjust parent count to actual depth
sys.path.insert(0, str(project_root))

from src.config.settings import Settings, get_active_contracts, get_all_futures_contracts
from src.core.database_manager import DatabaseManager
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
_logger = structlog.get_logger(__name__)
```
Verify the actual parent-count needed for this new script's real path before copying — the analog file's own header comment (lines 28-35) documents a prior off-by-one bug in exactly this bootstrap line, caught only because a sibling script got it right.

**Analog 2 (APR-seeded RNG for reproducible sampling):** `scripts/analysis/ic_sharpe_stride_bias_check.py`, line 146 area — fetches live APR values from `config_state` before running, and seeds `np.random.default_rng(seed)` from an explicit variable, not a bare literal:
```python
rng = np.random.default_rng(seed)
```
Combine with `alpha.universe.stratified_sample_random_state` (migration 337 above) as the seed source — never a hardcoded `42` in the script itself.

**`backfill_status` seed-row pattern (mandatory per CLAUDE.md's Corpus Pipeline Gotcha and D-08)** — analog: `services/backfill_feature_factory.py`, lines 205-212:
```python
_UPSERT_STATUS_SQL = """
INSERT INTO backfill_status (symbol, tf, status, fetch_complete, started_at)
VALUES (%s, %s, %s, %s, NOW())
ON CONFLICT (symbol, tf) DO UPDATE SET
    status = EXCLUDED.status,
    fetch_complete = GREATEST(backfill_status.fetch_complete, EXCLUDED.fetch_complete),
    started_at = COALESCE(backfill_status.started_at, EXCLUDED.started_at)
"""
```
Every newly onboarded symbol (Russell 3000 sample + gap-fill ETFs) MUST get one `backfill_status` row per timeframe via this exact upsert shape — a missing row silently vanishes from `--compute-only` compute runs (CLAUDE.md's named gotcha, D-08's exact failure class one table over).

**No-per-row-logging rule (applies directly — hundreds/thousands of symbols processed):** accumulate a counter, log once per run, matching `ic_engine.py`'s `n_skipped` pattern — do not `logger.info()` per onboarded symbol.

**Parameterized-SQL requirement (Security Domain, V5 in RESEARCH.md):** every symbol string from the downloaded CSV must go through parameterized queries (`%(...)s` placeholders, matching `ic_engine.py`'s `chunk_sql` convention already verified this session) — never f-string-interpolated into raw SQL, and every symbol must be routed through `src/providers/ibkr.py`'s `qualify_instrument()` before any DB write (de facto allowlist against a malformed/unexpected ticker string in the downloaded file).

---

## Shared Patterns

### APR key registration (config_schema + config_state paired INSERT)
**Source:** `production/migrations/307_regime_volatility_schema_apr_cvr.sql`, lines 85-138.
**Apply to:** `337_universe_apr_keys.sql` (new keys) and any config threshold introduced by the `X_nd` block-chunking fix in `ic_engine.py`.
```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(...)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
(...)
ON CONFLICT (config_key) DO NOTHING;
```
Namespace constraint: `alpha.*` or `infra.*` only — there is no `universe.` prefix.

### Instrument + tag onboarding (INSERT ... ON CONFLICT DO NOTHING)
**Source:** `production/migrations/296_single_name_equity_sector_orthogonality_expansion.sql`, full file.
**Apply to:** `338_etf_gap_fill_tags.sql` and the stratified-sourcing script's DB-write step (either as generated SQL or via parameterized `psycopg` execute using the identical column/conflict shape).
```sql
INSERT INTO instruments (symbol, base, contract_details, is_active) VALUES (...)
ON CONFLICT (symbol) DO NOTHING;

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES (...)
ON CONFLICT (symbol, tag) DO NOTHING;
```

### Exception variable naming
**Source:** `src/config/settings.py` line 584, `except Exception as error:` — project-wide rule (CLAUDE.md).
**Apply to:** every new `try/except` in `_batch_utils.py`'s disk-backed accumulator, the sourcing script, and any migration-adjacent Python.

### Crash-loud cell-size guard (never auto-subsample)
**Source:** `services/ic_engine.py`, `_check_cell_size` (lines 1020-1030) + `CellTooLargeError` (line 252).
**Apply to:** both the new pre-flight call site and the existing post-materialization call site — D-04 explicitly forbids a `try/except CellTooLargeError: subsample()` fallback anywhere in this phase's code.

### Never log per-row inside a full-corpus loop
**Source:** `ic_engine.py`'s `n_skipped` accumulate-then-log-once pattern (referenced throughout CLAUDE.md and RESEARCH.md).
**Apply to:** the stratified-sourcing script (hundreds-to-thousands of symbols) and any bulk `backfill_status`/`instrument_metadata` write loop.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `scripts/infrastructure/universe_expansion_stratified_sourcing.py` (external-CSV-download + `pandas.qcut` stratification step specifically) | utility/script | batch (fetch external file) | No existing script in this codebase downloads/parses an external CSV/XLSX constituent file. Bootstrap/logging/RNG-seeding sub-patterns are covered by two partial analogs above (`infrastructure_run_historical_pipeline.py`, `ic_sharpe_stride_bias_check.py`); the `pandas.qcut()`-based decile-bucketing logic itself has no in-repo precedent — implement per RESEARCH.md's Code Examples/Don't-Hand-Roll guidance (use `pandas.qcut` directly, do not hand-roll quantile binning) |

## Metadata

**Analog search scope:** `services/_batch_utils.py`, `services/ic_engine.py`, `src/config/settings.py`, `production/migrations/` (296, 150, 307, 292, 332, 319), `scripts/infrastructure/backfill/`, `scripts/analysis/`, `tests/unit/test_batch_utils.py`, `tests/unit/services/test_service_contract_resolution.py`, `services/backfill_feature_factory.py`.
**Files scanned:** ~25 (direct reads + targeted greps across migrations, scripts, tests).
**Pattern extraction date:** 2026-09-15
