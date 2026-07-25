# Phase 164: SMC Institutional Footprint Primitives - Pattern Map

**Mapped:** 2026-07-25
**Files analyzed:** 6 (all modified, no new files — this port lands entirely inside files Phase 163 already touched)
**Analogs found:** 6 / 6 (all exact — Phase 163 is a same-repo, same-pattern, 24-hour-old direct precedent)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `production/migrations/259_smc_institutional_footprint.sql` (number TBD — re-verify at execution time, see below) | migration | batch (schema DDL + config seed) | `production/migrations/255_vp_structural_primitives.sql` | exact — same author, same phase-predecessor, same column/registry/APR shape |
| `src/intelligence/schemas.py` (`FeatureVector` dataclass) | model | transform (pure data contract) | same file, `poc_dist_atr`...`sr_level_count` block (lines 1264-1291) added by migration 255 | exact |
| `src/intelligence/feature_cache.py` (`FeatureCache` dataclass + new `update_overnight_range()` mutator) | store/provider (mutable session state) | event-driven (session-boundary-reset accumulation) | `update_wk_vwap()` (lines 165-188) for the boundary-reset shape; `update_session_vp()` (lines 190-272) for the "accumulate raw levels, derive ATR-normalized values later in `compute()`" split | exact |
| `src/intelligence/feature_factory.py` (`compute()`/`compute_batch()` SMC block + 8 new pure helper functions + `FeatureFactoryConfig` fields + `FEATURE_VECTOR_DOMAIN` entries) | service/transform (pure compute) | transform (CRUD-free, deterministic function of bars+cache+config) | `_compute_sr_dist_atr()` (lines 3332-3414) for a fully self-contained stateless window-scan primitive; `_derive_session_vp()` (lines 3180-3265) for a primitive that reads `FeatureCache` raw state + `atr_val` and returns a dict of derived fields | exact |
| `src/intelligence/features/feature_vector_persistence.py` (`_SMC_FIELD_NAMES` slice) | model/utility (persistence contract) | CRUD (INSERT column list derivation) | `_STRUCTURAL_VP_SR_FIELD_NAMES` (lines 102-113) — literally the same append-only slice pattern, append a 4th slice after it | exact |
| `services/feature_vector_pipeline.py` + `services/backfill_feature_factory.py` (APR key wiring into `FeatureFactoryConfig`) | controller/config-loader | request-response (config prewarm) / batch | `_THRESHOLD_KEYS` tuple + `_prewarm_threshold_config()` (feature_vector_pipeline.py:568-734) and the equivalent `cfg.get_sync(...)` block in `backfill_feature_factory.py:498-506` | exact |

No test files listed separately — RESEARCH.md's Wave 0 gap table (`test_smc_order_blocks.py`, `test_smc_fvg.py`, `test_smc_liquidity.py`, `test_smc_zones.py`, `test_smc_structure.py`, `test_smc_amd_cycle.py`) all follow the same analog: `tests/unit/intelligence/test_support_resistance_primitives.py` / `test_volume_profile_primitives.py` (Phase 163's own new-file precedent, cited directly in RESEARCH.md's Test Framework section — not re-read here since RESEARCH.md already confirms the naming/structure convention).

## Pattern Assignments

### `production/migrations/259_smc_institutional_footprint.sql` (migration, batch)

**Analog:** `production/migrations/255_vp_structural_primitives.sql` (full file read, 251 lines)

**Structure to copy exactly** — 3 numbered `BEGIN`/`COMMIT`-wrapped sections in one file:

1. **`ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS <name> DOUBLE PRECISION;`** — one line per new column, followed by one `COMMENT ON COLUMN` per column. Use `DOUBLE PRECISION`, never `real` — migration 255's header explicitly documents that every `feature_vectors` column added after migration 201 (which only converted the 156 columns it listed) is `double precision`, confirmed via live `information_schema.columns` inspection, not the stale `real` assumption from that plan's own text. Apply the same live-schema-check discipline before committing to a type in Phase 164's migration.

```sql
-- Source: production/migrations/255_vp_structural_primitives.sql:56-107 (verified 2026-07-25)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS nearest_hvn_above_dist_atr DOUBLE PRECISION;
...
COMMENT ON COLUMN feature_vectors.nearest_hvn_above_dist_atr IS
    '(nearest HVN bucket price above close - close) / ATR. NULL when no HVN above exists in the session profile. Phase 163.';
```
No `decompress_chunk()` step needed — `ADD COLUMN` with a NULL default against a compressed hypertable is metadata-only (migration 255's header, citing migrations 197/206/216 precedent).

2. **`feature_registry` INSERT** — real columns are `feature_name, group_name, tier, formula_short, normalization, linear_ready, requires_htf, status, added_phase` (NOT an `is_bounded`/`is_directional` pair — migration 255's header explicitly warns this was a stale-draft assumption in its own plan text, corrected against the live `\d feature_registry` schema). `normalization` has no CHECK constraint but follows existing enum-like convention: `z_scored` (ATR-distance fields), `bounded_unsigned` (0/1 flags and [0,1]-clamped strength fields), `unbounded_ratio` (non-negative comparable scalars like counts/ages/cluster-strength — matches `resistance_strength`/`sr_level_count`'s precedent). `ON CONFLICT (feature_name) DO NOTHING`.

```sql
-- Source: production/migrations/255_vp_structural_primitives.sql:116-153
INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready, requires_htf, status, added_phase)
VALUES
    ('resistance_strength', 'session', '2_theory',
     'volume-weighted resistance cluster strength (capped per-member sum)', 'unbounded_ratio', false, false, 'active', '163'),
    ...
ON CONFLICT (feature_name) DO NOTHING;
```
Use `added_phase = '164'`, `group_name` should be a new value distinct from `'session'` (e.g. `'smc'` or `'smart_money'` — matches the `FEATURE_VECTOR_DOMAIN` tag decision below, A5 in RESEARCH.md's Assumptions Log).

3. **APR key seeding** — 3-table pattern: `config_schema` (key, type, default, min, max, description with `[conventional]` provenance tag), `config_state` (seed value, version 1), `config_history` (audit row, `changed_by = 'migration_<N>'`). All three `ON CONFLICT DO NOTHING`.

```sql
-- Source: production/migrations/255_vp_structural_primitives.sql:159-249
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'feature.sr.cluster_atr_mult', 'float', '0.5', 0.05, 5.0,
    '[conventional] ATR multiple defining the pivot-clustering radius for support/resistance (Plan 03). Matches support_resistance.py''s existing default. Phase 163. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('feature.sr.cluster_atr_mult', '0.5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'feature.sr.cluster_atr_mult', 1, '0.5', 'migration_255',
     'Seed S/R clustering ATR multiple, Phase 163 [conventional]')
ON CONFLICT DO NOTHING;
```
Phase 164's APR keys: RESEARCH.md's Migrate-as-you-go list — `impulse_bars`, `impulse_atr_mult` (order blocks), reclaim-bar counts (breaker/mitigation), AMD's 4 UTC session-boundary hours (20/0/10/21), any per-plugin lookback windows hardcoded in the archived source. Every one needs `[conventional]` provenance (copied verbatim from the archived plugin's own hardcoded default — an unvalidated ICT-community convention, not `[rca_analysis]`).

**Migration numbering:** migration 255's own header documents 2 prior numbering collisions (243 vs 255, 221 vs 222/223) from concurrent sessions claiming the "next" number between planning and execution. RESEARCH.md's Open Question 3 flags 259 as next-free as of 2026-07-25 — re-run `ls production/migrations/ | sort -V | tail -3` immediately before writing the file, not just at planning time.

---

### `src/intelligence/schemas.py` — `FeatureVector` dataclass (model, transform)

**Analog:** same file, the Phase 163 session-level block (lines 1264-1291), and the module docstring's "Groups and field order are binding" convention (lines 1215-1241).

**Pattern:** `FeatureVector` is `@dataclasses.dataclass(frozen=True)`, all fields typed `float` (required) or `float | None` (optional, no default — this dataclass has zero defaulted fields; every field must be supplied by `_build_feature_vector`'s keyword-only constructor call). New SMC fields must:
1. Be typed `float | None` (never `str` — RESEARCH.md's Pitfall 4: `amd_phase`/`ob_mitigation_status` are Python `str` in the archived source and MUST be ordinal-encoded before becoming a field here, or the dataclass construction crashes).
2. Be added as a new contiguous, commented block (matching the existing per-family comment-block convention, e.g. `# Session-level — Volume Profile (12, Phase 163 Plan 01, D-13/D-16/D-17/D-18)`), with the block's line count and phase number noted in both the field-level comment and the class docstring's "Groups and field order are binding" summary table.
3. Field placement does not need to match INSERT column order (`feature_vector_persistence.py` derives by name) — but DOES need to be a **contiguous** slice for the `dataclasses.fields(FeatureVector)[start:end]` slicing technique in `feature_vector_persistence.py` to work. Pick one placement (end of file, immediately before the 3 nullable cross-sectional fields, matching where canary fields were appended) and keep all ~15-20 new SMC fields together as one block.

```python
# Source: src/intelligence/schemas.py:1264-1291 (verified 2026-07-25)
    # Session-level — Support/Resistance (5, Phase 163 Plan 01, D-19)
    resistance_strength: float | None
    support_strength: float | None
    resistance_age_bars: float | None
    support_age_bars: float | None
    sr_level_count: float | None
```

Update the class docstring's total field count and the "Total: N" line (currently 172) and the `_build_feature_vector()` function's keyword-arg signature (grep-confirm every new field is also threaded through `_build_feature_vector` at `feature_factory.py:3417+` — this function has zero defaults either, so a missed field is a hard `TypeError` at call time, not a silent drop).

---

### `src/intelligence/feature_cache.py` — new `update_overnight_range()` mutator (store/provider, event-driven)

**Analog:** `update_wk_vwap()` (lines 165-188) for the reset-on-boundary-change shape; `update_session_vp()` (lines 190-272) for the "store raw levels only, let `compute()` do ATR normalization" split.

```python
# Source: src/intelligence/feature_cache.py:165-188 (verified 2026-07-25)
def update_wk_vwap(
    self,
    bar_ts: datetime,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> None:
    """Update weekly VWAP state and set above_wk_vwap from current bar.

    Resets accumulators at ISO week boundary. Called by the pipeline or backfill
    once per bar, after FeatureFactory.compute().
    """
    iso = bar_ts.isocalendar()
    year_week = (iso.year, iso.week)
    if year_week != self._wk_year_week:
        self._wk_tp_vol_sum = 0.0
        self._wk_vol_sum = 0.0
        self._wk_year_week = year_week
    typical = (high + low + close) / 3.0
    self._wk_tp_vol_sum += typical * volume
    self._wk_vol_sum += volume
    wk_vwap = self._wk_tp_vol_sum / self._wk_vol_sum if self._wk_vol_sum > 1e-10 else close
    self.above_wk_vwap = float(close > wk_vwap)
```

**Port target for AMD's `update_overnight_range()`:** replace the ISO-week boundary key with a UTC-hour-rollover key — `(bar_ts.date(), bar_ts.hour >= 20)` transitioning into a new 20:00 UTC accumulation window (RESEARCH.md's exact recommendation). Replace the VWAP running-sum accumulation with `min`/`max` high/low accumulation (mirrors `_state[key_sym] = {"high": max(...), "low": min(...)}` in the archived `AMDCyclePlugin.compute_full`, shown below). New `FeatureCache` fields to add (analogous to `_wk_tp_vol_sum`/`_wk_vol_sum`/`_wk_year_week`): `_overnight_high`, `_overnight_low`, `_overnight_day`.

New `FeatureCache` session-level dataclass fields to expose to `compute()` (matching `above_wk_vwap: float = 0.0` at line 64 and `poc_dist_atr: float = 0.0` at line 67 — plain float attrs, not underscore-prefixed, since these ARE read directly by `compute()`/`_build_feature_vector`): `amd_phase` (ordinal-encoded), `amd_manipulation_detected`, `amd_distribution_direction`, `manip_strength` (clamped [0,1] — see Anti-patterns below).

**Archived source for the accumulation logic to port** (`AMDCyclePlugin.compute_full`, full file read, 134 lines):

```python
# Source: src/intelligence/archive/smc_context/amd_cycle.py:81-122 (verified 2026-07-25)
key_sym = "overnight"
if phase == "accumulation":
    prev = self._state.get(key_sym, {})
    self._state[key_sym] = {
        "high": max(prev.get("high", high), high),
        "low": min(prev.get("low", low), low),
    }
    ...
# Manipulation detection: breach overnight range then reverse
manip_detected = 0.0
manip_strength = 0.0
overnight = self._state.get(key_sym, {})
on_high = overnight.get("high")
on_low = overnight.get("low")
on_range = (on_high - on_low) if (on_high is not None and on_low is not None) else 0.0

if phase == "manipulation" and on_high is not None and on_low is not None:
    if high > on_high and close < on_high:
        manip_detected = 1.0
        manip_strength = (high - on_high) / on_range if on_range > 0 else 0.0
        ...
    elif low < on_low and close > on_low:
        manip_detected = 1.0
        manip_strength = (on_low - low) / on_range if on_range > 0 else 0.0
        ...
```

**Do NOT port the `self._state` dict pattern itself** — this is the exact anti-pattern RESEARCH.md's Anti-patterns section flags. Rewrite as `FeatureCache` typed fields (`self._overnight_high: float | None`, `self._overnight_low: float | None`) mutated by the new `update_overnight_range()` method, called once per bar by the caller (same call-site convention as `update_wk_vwap`/`update_session_vp` below), not a plugin-instance dict.

**Session-boundary reset already-live import to reuse:** `utc_datetime_from_df` (`src/intelligence/utils.py`) for extracting the bar's UTC hour — already imported by the archived `amd_cycle.py` (line 18) and confirmed still live/non-archived per RESEARCH.md's Standard Stack section.

---

### `src/intelligence/feature_factory.py` — SMC compute block (service/transform, transform)

**Analog A — fully self-contained stateless window-scan** (`order_blocks`, `fair_value_gap`, `liquidity_sweeps`, `liquidity_pools`, `bos_choch` all fit this shape): `_compute_sr_dist_atr()`.

```python
# Source: src/intelligence/feature_factory.py:3332-3414 (verified 2026-07-25)
def _compute_sr_dist_atr(
    highs: np.ndarray,
    lows: np.ndarray,
    close_: float,
    atr_val: float,
    volume: np.ndarray,
    tf: str,
    config: FeatureFactoryConfig,
) -> dict[str, float]:
    """Stateless inline support/resistance (D-02/D-04), ATR-normalized (D-19).
    ...
    Falls back to all-zero for any side/field when atr_val <= 0, the window
    has insufficient bars for find_peaks/find_troughs, or no qualifying pivot
    cluster exists on that side -- never raises.
    """
    atr_valid = atr_val is not None and math.isfinite(atr_val) and atr_val > 0
    if not atr_valid:
        return dict(_SR_FALLBACK)

    lookback = config.sr_lookback_by_tf.get(tf, 120)
    h = highs[-lookback:]
    lo = lows[-lookback:]
    ...
    peak_indices = find_peaks(h, n=config.sr_window)
    trough_indices = find_troughs(lo, n=config.sr_window)
    ...
    return {
        "sr_support_dist": sr_support_dist,
        "sr_resist_dist": sr_resist_dist,
        "resistance_strength": resistance_strength,
        ...
    }
```
Key shape to copy: (1) a module-level `_<CONCEPT>_FALLBACK: dict[str, float]` constant for the "insufficient data" early-return — never raise, per V5 in RESEARCH.md's Security Domain section; (2) `atr_valid` guard as the first check; (3) `config.<name>_lookback_by_tf.get(tf, <default>)` for per-timeframe windowing (reuse `sr_lookback_by_tf`'s exact JSON-dict-APR-key shape for any new per-tf lookback, e.g. an equivalent `feature.smc.<concept>.lookback_by_tf` key if a plugin needs different tf-specific windows than S/R's); (4) reuse `find_peaks`/`find_troughs` directly rather than re-deriving pivot detection (already used by `liquidity_sweeps.py`, `liquidity_pools.py`, `bos_choch.py` in the archived source per RESEARCH.md's Don't Hand-Roll table).

**Analog B — reads `FeatureCache` mutable state + derives ATR-normalized output** (`amd_cycle` fits this shape): `_derive_session_vp()`.

```python
# Source: src/intelligence/feature_factory.py:3180-3265 (verified 2026-07-25)
def _derive_session_vp(
    cache: FeatureCache,
    close_: float,
    atr_val: float,
    poc_price_rolling: float | None,
) -> dict[str, float | None]:
    """Derive the 14 ATR-normalized/bounded VP FeatureVector fields.

    Reads FeatureCache's raw session levels (set by update_session_vp(), called
    once per bar by the caller before compute()/inside compute_batch()'s loop)
    plus the compute-path atr_val -- no raw price level is ever returned or
    persisted (D-16). ...
    """
    atr_valid = atr_val is not None and math.isfinite(atr_val) and atr_val > 0
    poc = cache._sess_poc
    ...
    poc_dist_atr = 0.0 if poc is None or not atr_valid else (close_ - poc) / atr_val
    ...
    return {
        "poc_dist_atr": poc_dist_atr,
        ...
    }
```
AMD's equivalent (`_derive_amd_cycle(cache, ...)` or inline) reads `cache._overnight_high`/`cache._overnight_low` (or the non-underscore ordinal fields if state lives directly on the dataclass) and returns the same shape of `{"amd_phase": ..., "manip_strength": ...}` dict — `manip_strength` MUST be wrapped in `linear_ramp`/`clamp` before returning (see Anti-patterns below); the archived source has no clamp at all (`amd_cycle.py:114/120`, `manip_strength = (high - on_high) / on_range`, unbounded).

**`compute()` call-site wiring** — where the new SMC block goes, matching the exact order S/R and VP are threaded into `compute()`:

```python
# Source: src/intelligence/feature_factory.py:3852-3863 (verified 2026-07-25)
        _sr_fields = _compute_sr_dist_atr(highs, lows, close_, atr_val, volumes, tf, config)
        sr_support_dist_val: float | None = _sr_fields["sr_support_dist"]
        sr_resist_dist_val: float | None = _sr_fields["sr_resist_dist"]
        resistance_strength_val: float | None = _sr_fields["resistance_strength"]
        ...
```
Phase 164's block goes in the same section of `compute()` (after `atr_val` is computed, alongside the VP/S-R block), in the RESEARCH.md-mandated order: `order_blocks` -> `breaker_blocks`/`mitigation_blocks` (consume OB's `active_obs` dict directly, NOT `self._state`) -> `fair_value_gap` -> `liquidity_sweeps` -> `liquidity_pools` -> `supply_demand_zones` (consumes FVG + LiquidityPools output) -> `bos_choch` -> `amd_cycle`. Then thread every new field into the final `_build_feature_vector(...)` keyword-arg call (lines 3932+), matching how `poc_dist_atr_val`, `vp_extra["nearest_hvn_above_dist_atr"]`, etc. are passed at lines 3950-3970.

**`compute_batch()` per-bar loop** — where `cache.update_session_vp(...)` is called once per bar inside the vectorized backfill loop; AMD's new `update_overnight_range()` call goes at the same call site:

```python
# Source: src/intelligence/feature_factory.py:4200-4201 (verified 2026-07-25)
            # matches the live pipeline's per-bar update_session_vp() call site.
            cache.update_session_vp(bar_ts, high_, low_, close_, vol_, config)
```
and live pipeline equivalent:
```python
# Source: services/feature_vector_pipeline.py:1012-1015 (verified 2026-07-25)
        # Session-VP accumulator (Phase 163 Plan 02): update BEFORE compute()
        # reads FeatureCache's raw session levels to derive the 14 ATR-normalized
        # VP fields. Mirrors compute_batch()'s per-bar update_session_vp() call.
        cache.update_session_vp(bar.ts, bar.high, bar.low, bar.close, float(bar.volume), config)
```
Add `cache.update_overnight_range(bar.ts, bar.high, bar.low, config)` immediately adjacent to this in BOTH `compute_batch()`'s loop and `feature_vector_pipeline.py`'s per-bar handler (and its warm-up replay block at `feature_vector_pipeline.py:185-202`, which replays `update_wk_vwap()`/`update_session_vp()` over buffered history after a restart — AMD's mutator needs the same warm-up replay treatment or overnight state silently resets to cold-start after every service restart).

**`FeatureFactoryConfig` new fields** — same defaulted-field pattern as `session_vp_*`/`sr_*`:

```python
# Source: src/intelligence/feature_factory.py:488-504 (verified 2026-07-25)
    # Session Volume Profile (Phase 163 Plan 01, D-03/D-13). Defaulted for the
    # same reason as canary_rng_seed above (avoid updating every pre-existing
    # direct FeatureFactoryConfig(...) construction site); the 2 real production
    # entrypoints (backfill_feature_factory.py, feature_vector_pipeline.py)
    # explicitly wire these from ConfigService.
    session_vp_value_area_pct: float = 0.70  # feature.session_vp.value_area_pct
    session_vp_n_buckets: int = 50  # feature.session_vp.n_buckets
    ...
    sr_lookback_by_tf: dict = field(  # feature.sr.lookback_by_tf
        default_factory=lambda: {"1m": 60, "5m": 60, "15m": 80, "1h": 120, "1d": 60}
    )
```
Every new SMC APR field must be `= <default>` (never bare, unlike the majority of `FeatureFactoryConfig`'s ~90 non-defaulted fields) — same comment noting the ~6 pre-existing direct `FeatureFactoryConfig(...)` test construction sites this defaulting rationale protects.

**`FEATURE_VECTOR_DOMAIN` new entries** — one dict entry per new field, tag `"smart_money"` (RESEARCH.md's A5 recommendation, matching the archived plugins' own `capability_tags: frozenset({"smart_money"})`):

```python
# Source: src/intelligence/feature_factory.py:84-106 (verified 2026-07-25)
FEATURE_VECTOR_DOMAIN: dict[str, str] = {
    ...
    "poc_dist_atr": "structural",
    ...
    "resistance_strength": "structural",
    ...
}
```

---

### `src/intelligence/features/feature_vector_persistence.py` — `_SMC_FIELD_NAMES` slice (model/utility, CRUD)

**Analog:** `_STRUCTURAL_VP_SR_FIELD_NAMES` (lines 102-113) — the direct 3rd-slice precedent (after `_RENAISSANCE_PRIMITIVE_FIELD_NAMES` and `_CANARY_FIELD_NAMES`).

```python
# Source: src/intelligence/features/feature_vector_persistence.py:102-113 (verified 2026-07-25)
# The 17 new structural VP/SR fields (Phase 163 Plan 01, migration 255) are a third
# contiguous, same-order slice -- immediately following the original 4 session-level
# fields (poc_dist_atr/va_position/sr_support_dist/sr_resist_dist) in the dataclass.
# Same derive-don't-hand-type discipline as the two slices above; appended at the end
# of the column list (after the canary fields) below, matching this module's
# append-only convention.
_STRUCTURAL_VP_SR_FIELD_NAMES: tuple[str, ...] = _ALL_FEATURE_VECTOR_FIELD_NAMES[
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index(
        "nearest_hvn_above_dist_atr"
    ) : _ALL_FEATURE_VECTOR_FIELD_NAMES.index("sr_level_count")
    + 1
]
```

Add a 4th slice `_SMC_FIELD_NAMES` immediately after it, using the first/last field names of whatever contiguous block was added to `schemas.py`:

```python
_SMC_FIELD_NAMES: tuple[str, ...] = _ALL_FEATURE_VECTOR_FIELD_NAMES[
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index("<first_new_field>") : _ALL_FEATURE_VECTOR_FIELD_NAMES.index("<last_new_field>")
    + 1
]
```

Then thread `_SMC_FIELD_NAMES` through 3 places, exactly matching how `_STRUCTURAL_VP_SR_FIELD_NAMES` was threaded through the same 3 places (`FEATURE_VECTOR_INSERT_SQL` column list at line 179, the `$N` placeholder range generator at lines 210-221, and `_TOTAL_COLUMNS` at line 235, and the final `feature_vector_to_insert_params` return tuple's `*(getattr(vector, name) for name in _SMC_FIELD_NAMES)` unpack at line 438). No hand-typed column list anywhere — this is exactly the discipline that prevents the 2026-07-08 incident (91/152 columns silently NULL) from recurring, and `tests/unit/test_feature_vector_persistence_completeness.py` structurally enforces it (auto-covers new fields with zero new test code, per RESEARCH.md's Requirements table).

Also bump the module docstring's running column-count changelog (`2026-07-23: extended to 181 columns...`) with a new dated entry for Phase 164's column count.

---

### `services/feature_vector_pipeline.py` + `services/backfill_feature_factory.py` — APR key wiring (controller/config-loader)

**Analog (live path):** `_THRESHOLD_KEYS` tuple + `_prewarm_threshold_config()`.

```python
# Source: services/feature_vector_pipeline.py:589-600, 602-621, 723-733 (verified 2026-07-25)
        ("feature.sr.window", 10),
        ("feature.sr.cluster_atr_mult", 0.5),
        (
            "feature.sr.lookback_by_tf",
            {"1m": 60, "5m": 60, "15m": 80, "1h": 120, "1d": 60},
        ),
    )

    async def _prewarm_threshold_config(self) -> None:
        """Prewarm config cache and build FeatureFactoryConfig from feature.* keys."""
        assert self._config_service is not None
        for key, default in self._THRESHOLD_KEYS:
            await self._config_service.get(key, default)

        cs = self._config_service

        def _int(key: str, default: int) -> int:
            v = cs.get_sync(key, default)
            return int(v) if v is not None else default
        ...
        self._feature_factory_config = FeatureFactoryConfig(
            ...
            sr_window=_int("feature.sr.window", 10),
            sr_cluster_atr_mult=_float("feature.sr.cluster_atr_mult", 0.5),
            sr_lookback_by_tf=_dict(
                "feature.sr.lookback_by_tf",
                {"1m": 60, "5m": 60, "15m": 80, "1h": 120, "1d": 60},
            ),
        )
```
Add every new `feature.smc.*` (or per RESEARCH.md's A4, possibly flatter `feature.<concept>.*`) key to `_THRESHOLD_KEYS`, then a matching `_int`/`_float`/`_dict` call inside `_prewarm_threshold_config()`'s `FeatureFactoryConfig(...)` construction.

**Analog (batch path):**

```python
# Source: services/backfill_feature_factory.py:498-506 (verified 2026-07-25)
        session_vp_value_area_pct=float(cfg.get_sync("feature.session_vp.value_area_pct", 0.70)),
        session_vp_n_buckets=int(cfg.get_sync("feature.session_vp.n_buckets", 50)),
        ...
        sr_window=int(cfg.get_sync("feature.sr.window", 10)),
        sr_cluster_atr_mult=float(cfg.get_sync("feature.sr.cluster_atr_mult", 0.5)),
        sr_lookback_by_tf=_get_dict_config(
            cfg, "feature.sr.lookback_by_tf", {"1m": 60, "5m": 60, "15m": 80, "1h": 120, "1d": 60}
        ),
    )
```
Same `cfg.get_sync(key, default)` inline pattern, no separate prewarm step (batch path reads config once at job start, synchronously). `_get_dict_config()` is the existing shared JSON-dict-APR-key parser — reuse directly for any new per-tf/per-concept dict-shaped APR key, don't reimplement.

**Also update** the warm-up replay block (`feature_vector_pipeline.py:174-202`, which replays `update_wk_vwap()`/`update_session_vp()` over buffered history after a service restart) to include `update_overnight_range()` — otherwise AMD's overnight-range state cold-starts on every restart while VP/SR state doesn't, an inconsistency a code reviewer would flag.

---

## Shared Patterns

### ATR-distance normalization (the single load-bearing convention this whole phase exists to enforce)
**Source:** `_compute_sr_dist_atr()` / `_derive_session_vp()` (`feature_factory.py`), migration 255's header note.
**Apply to:** every one of the 8 ported plugins' distance/level output.
Formula shape: `(level - close_) / atr_val` (or `abs(...)` for undirected), guarded by `atr_valid = atr_val is not None and math.isfinite(atr_val) and atr_val > 0`, falling back to `0.0` (required fields) or `None` (brand-new optional fields with no legacy default to preserve) when invalid. Never persist the raw `level`/`top`/`bottom`/`midpoint` itself — RESEARCH.md's Field-by-Field Raw-Price Audit table is the literal per-file checklist.

### Bounded strength/decay scoring
**Source:** `src/intelligence/utils.py` (`linear_ramp`, `clamp`), `src/intelligence/utils/gradient_utils.py` (`freshness_decay`) — already live, already imported.
**Apply to:** `manip_strength` (currently unbounded in the archived `amd_cycle.py`, must be clamped before persisting — RESEARCH.md Pitfall 3), and any other "strength"/"score" field lacking an explicit upper bound in the archived source. `liquidity_sweeps.py`'s `sweep_strength` and `supply_demand_zones.py`'s `demand_freshness` already use these correctly in the archived source — same functions, same call shape, no new bounding abstraction needed.

### Session-boundary-reset accumulation
**Source:** `FeatureCache.update_wk_vwap()` (ISO-week key) / `update_session_vp()` (ET-session-day key), `feature_cache.py:165-272`.
**Apply to:** the new `update_overnight_range()` mutator — same "compare boundary key, reset accumulators on change" shape, different boundary calculation (UTC-hour rollover into 20:00 instead of ISO week or ET session open).

### Append-only field-name-slice persistence contract
**Source:** `feature_vector_persistence.py`'s `_RENAISSANCE_PRIMITIVE_FIELD_NAMES` -> `_CANARY_FIELD_NAMES` -> `_STRUCTURAL_VP_SR_FIELD_NAMES` chain.
**Apply to:** the new `_SMC_FIELD_NAMES` slice — derive by name from `dataclasses.fields(FeatureVector)`, never hand-type a column list. This is the single most consequential pattern in the whole phase (prevents the 2026-07-08 91-column-silently-NULL incident from recurring) and the completeness test structurally enforces it with zero new test code required.

### APR migrate-as-you-go, 3-layer wiring
**Source:** `config_schema`/`config_state`/`config_history` migration inserts + `_THRESHOLD_KEYS`/`_prewarm_threshold_config()` (live) + inline `cfg.get_sync()` (batch) + `FeatureFactoryConfig` defaulted dataclass field.
**Apply to:** every new numeric threshold this phase's archived-plugin port surfaces (impulse-move %, base-body ratio, ATR multipliers, reclaim-bar counts, lookback windows, AMD's 4 UTC session-boundary hours). No hardcoded constant may land in `feature_factory.py`/`feature_cache.py` — every one traces to a `feature.*` (or `feature.smc.*`) config key with `[conventional]` provenance.

### Pure-function purity contract (no IO in `compute()`/`compute_batch()`)
**Source:** `feature_factory.py:3792-3797` docstring — "PURE FUNCTION: no IO... Deterministic: identical inputs -> identical output."
**Apply to:** all 8 ported plugins. The archived `breaker_blocks.py`/`mitigation_blocks.py`'s `self._state` cross-call mutation must NOT be carried into v3 — derive both directly from `order_blocks`' own already-scanned `active_obs` list within the same compute pass (RESEARCH.md's explicit correction to the "stateless full-window recompute" pattern).

## No Analog Found

None — all 6 file-classification rows above have an exact, same-repo, 24-hour-old analog from Phase 163. This is the strongest possible analog coverage this project's pattern-mapper has produced; there is no category of file in this phase's scope that lacks a directly-cited precedent.

## Metadata

**Analog search scope:** `src/intelligence/feature_factory.py`, `src/intelligence/feature_cache.py`, `src/intelligence/schemas.py`, `src/intelligence/features/feature_vector_persistence.py`, `production/migrations/255_vp_structural_primitives.sql`, `services/feature_vector_pipeline.py`, `services/backfill_feature_factory.py`, `src/intelligence/archive/smc_context/order_blocks.py` (full read), `src/intelligence/archive/smc_context/amd_cycle.py` (full read). RESEARCH.md's own Sources section (full reads of all 8 in-scope archived plugin files plus `premium_discount.py`/`swing_utils.py`/`ict_killzones.py`) is treated as already-verified upstream evidence for the plugins not independently re-read here (`fair_value_gap.py`, `liquidity_sweeps.py`, `liquidity_pools.py`, `supply_demand_zones.py`, `breaker_blocks.py`, `mitigation_blocks.py`, `bos_choch.py`) — no re-read needed since RESEARCH.md's Field-by-Field Raw-Price Audit table already extracted every concrete field name from those 6 files at the line level.
**Files scanned:** 9 direct reads (2 full-file archived plugins, migration 255, feature_vector_persistence.py, targeted ranges of feature_factory.py/feature_cache.py/schemas.py/feature_vector_pipeline.py/backfill_feature_factory.py) + RESEARCH.md's 8-plugin audit taken as verified.
**Pattern extraction date:** 2026-07-25
