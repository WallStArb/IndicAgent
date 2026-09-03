# Phase 165: Swing/Fib/Trend Structure Primitives - Pattern Map

**Mapped:** 2026-07-27
**Files analyzed:** 9 (1 new migration, 1 new test file, 7 modified existing files)
**Analogs found:** 9 / 9 — Phase 163 is the primary analog for every file; the archived
`i3_structure/*.py` plugins are the algorithmic port source (already identified by
RESEARCH.md/CONTEXT.md) but are NOT the wiring-pattern analog — they predate the v3
`FeatureVector`/`FeatureFactoryConfig`/APR/migration conventions entirely.

**How to read this doc:** Phase 163 ("VP/SR Structural Primitives") is the immediately
preceding phase that ported the other two `i3_structure` files (`market_profile.py`,
`support_resistance.py`) into the exact same 7 files this phase touches, using the exact same
port-plus-fix discipline (D-01 nullable-field bug is this phase's version of Phase 163's
D-01/todo-153 cache-stub bug). Every pattern below cites live, currently-committed Phase 163
code — not a template, the actual merged implementation at `main`.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `production/migrations/25X_swing_fib_trend_structure_primitives.sql` | migration | batch (DDL + APR seed) | `production/migrations/255_vp_structural_primitives.sql` | exact |
| `src/intelligence/schemas.py` (`FeatureVector` dataclass) | model | transform | Phase 163's additions at `schemas.py:1264-1291` | exact |
| `src/intelligence/feature_factory.py` (`FEATURE_VECTOR_DOMAIN`) | config/registry | transform | `feature_factory.py:83-106` | exact |
| `src/intelligence/feature_factory.py` (`FeatureFactoryConfig` new fields) | config | transform | `feature_factory.py:487-504` | exact |
| `src/intelligence/feature_factory.py` (new `_compute_swing_*`/`_compute_trend_structure`/`_compute_fib_zones` helpers) | service (pure compute) | transform | `feature_factory.py:3268-3415` (`_compute_sr_dist_atr`/`_cluster_levels`/`_finalize_cluster`) | exact |
| `src/intelligence/feature_factory.py` (`compute()`/`compute_batch()` wiring + `_build_feature_vector` signature) | service (pure compute) | transform | `feature_factory.py:3830-3970` (`compute()`) and the compute_batch() mirror ~4260-4600 | exact |
| `src/intelligence/feature_cache.py` (new session-boundary mutator for `session_levels.py`) | store/mutator | event-driven (per-bar state) | `FeatureCache.update_session_vp()` (`feature_cache.py:191-293`) + `update_wk_vwap()` (`feature_cache.py:166-189`) | exact |
| `src/intelligence/features/feature_vector_persistence.py` | service (persistence) | CRUD (INSERT) | `_STRUCTURAL_VP_SR_FIELD_NAMES` slice (`feature_vector_persistence.py:102-113`) | exact |
| `services/feature_vector_pipeline.py` (config build + `update_*` call site) | service (streaming daemon) | streaming | Phase 163's `session_vp_*` config wiring + `cache.update_session_vp(...)` call (`feature_vector_pipeline.py:594-598,745-751,1036-1037`) | exact |
| `services/backfill_feature_factory.py` (config build) | service (batch daemon) | batch | Phase 163's `session_vp_*`/`sr_*` config wiring (`backfill_feature_factory.py:505-511`) | exact |
| `tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py` (new) | test | transform | `tests/unit/intelligence/test_support_resistance_primitives.py` (full file, 357 lines) | exact |
| `tests/unit/test_feature_factory.py`, `tests/unit/services/test_backfill_feature_factory.py`, `tests/unit/services/test_feature_vector_writer_column_mapping.py`, `tests/unit/test_canary_predictors.py` (blast-radius updates: field count, `FeatureVector(...)` construction, `_build_feature_vector` kwargs) | test | transform | Phase 163 Plan 01 commit `0ff48698` — same 4 files, same blast-radius shape | exact |

## Algorithmic port sources (for the math itself, NOT the wiring pattern)

These are the files CONTEXT.md/RESEARCH.md already identified as the direct port source for
each new primitive's core algorithm. Read them for the computation; read the Phase 163 analogs
above for how to wire that computation into the live v3 files.

- `src/intelligence/features/i3_structure/swing_detector.py` (95 lines, read in full above)
- `src/intelligence/features/i3_structure/swing_momentum.py` (258 lines, read in full above)
- `src/intelligence/features/i3_structure/trend_structure.py` (181 lines, read in full above)
- `src/intelligence/features/i3_structure/fibonacci_zones.py` (108 lines, read in full above)
- `src/intelligence/features/i3_structure/session_levels.py` (435 lines, read in full above —
  Asian-session sub-feature only; `prior_session_*`/`overnight_*`/`weekly_*` need the D-08/D-09
  rewrite, not a literal port)

## Pattern Assignments

### 1. Migration file (`production/migrations/25X_swing_fib_trend_structure_primitives.sql`)

**Analog:** `production/migrations/255_vp_structural_primitives.sql` (full file read)

**Header-note convention** (lines 1-40): document every deviation from the plan's assumed
schema *in the migration file itself* — column type (`double precision`, not `real` — every
column added after migration 201 uses this, confirmed via `information_schema.columns`),
`feature_registry`'s real column set (`feature_name, group_name, tier, formula_short,
normalization, linear_ready, requires_htf, status, added_phase` — no `is_bounded`/
`is_directional` pair), and the "ADD COLUMN on a compressed hypertable is metadata-only, no
decompression" note. Phase 165 will hit the identical migration-numbering collision note
pattern (255 was renumbered from a stale 243) — **verify the next-free migration number
directly** (`ls production/migrations/ | sort -V | tail -5`) rather than trusting any doc's
stated next number.

**Column DDL pattern** (lines 44-61):
```sql
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS nearest_hvn_above_dist_atr DOUBLE PRECISION;
...
COMMENT ON COLUMN feature_vectors.nearest_hvn_above_dist_atr IS
    '(nearest HVN bucket price above close - close) / ATR. NULL when no HVN above exists in the session profile. Phase 163.';
```
Every new Phase 165 column needs both the `ADD COLUMN IF NOT EXISTS ... DOUBLE PRECISION` line
and a `COMMENT ON COLUMN` documenting the exact formula and null condition — copy this 1:1,
substituting Phase 165's 41 field names/formulas (D-01's now-nullable `trend_direction`,
`price_position`, etc. need their null condition spelled out here: "NULL when fewer than 2
confirmed swing highs/lows exist in the lookback window", not the old fake `0.0`/`0.5`).

**`feature_registry` INSERT pattern** (lines 121-149):
```sql
INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready, requires_htf, status, added_phase)
VALUES
    ('nearest_hvn_above_dist_atr', 'session', '2_theory',
     '(nearest HVN price above close - close) / ATR', 'z_scored', false, false, 'active', '163'),
    ...
ON CONFLICT (feature_name) DO NOTHING;
```
Use `group_name='session'`, `tier='2_theory'`, `added_phase='165'` for all 41 rows (per
165-CONTEXT.md's canonical_refs, NOT `group_name='structure'`). `normalization` vocabulary
confirmed from this table: `'z_scored'` (signed ATR-distances), `'unbounded_ratio'`
(non-negative comparable scalars — `resistance_strength`-style; this phase's
`swing_amplitude_ratio`/`swing_volume_confirmation` fit here), `'bounded_signed'` (`{-1,0,1}`
categoricals — `swing_velocity_bias`, `struct_accel_bias`, `trend_direction`),
`'bounded_unsigned'` (`[0,1]`/binary flags — `price_position`, `swing_amplitude_expanding`,
`gap_filled`).

**APR key seed pattern** (lines 154-224) — three-part insert per key (`config_schema` →
`config_state` → `config_history`), each with a `[conventional]` provenance tag in the
description:
```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'feature.sr.window', 'int', '10', 2, 50,
    '[conventional] find_peaks/find_troughs pivot detection window for support/resistance
     clustering (Plan 03). Matches support_resistance.py''s existing default. Phase 163.
     Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('feature.sr.window', '10', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'feature.sr.window', 1, '10', 'migration_255',
        'Seed S/R pivot detection window, Phase 163 [conventional]')
ON CONFLICT DO NOTHING;
```
Apply this 3-insert pattern to every one of D-06 through D-09's ~13 new APR keys
(`feature.swing.pivot_window`, `feature.trend_structure.atr_strength_divisor`,
`feature.trend_structure.range_lookback_bars`, `feature.swing_momentum.confirm_n` +5 more,
`feature.fib.cluster_atr_divisor`, `feature.fib.cluster_fallback_divisor`,
`feature.session_levels.asia_start_et_hour`/`asia_end_et_hour`). JSON-typed keys (none needed
here, unlike Phase 163's `feature.sr.lookback_by_tf`) would use `value_type='json'` per that
same file's `feature.sr.lookback_by_tf` row.

---

### 2. `src/intelligence/schemas.py` — `FeatureVector` dataclass additions

**Analog:** `schemas.py:1264-1291` (Phase 163's own 21-field addition, itself following the
pre-existing `poc_dist_atr: float | None` precedent at line 1269)

```python
# Session-level (21: 4 original + 12 VP + 5 S/R, Phase 163) — session
# volume-profile + support/resistance structural features, computed from
# OHLCV in both live and batch (D-05: no I3/tick-data dependency exists;
# the prior comment claiming batch-unavailability was an inherited,
# never-verified assumption).
poc_dist_atr: float | None
va_position: float | None
sr_support_dist: float | None
sr_resist_dist: float | None
# Session-level — Volume Profile (12, Phase 163 Plan 01, D-13/D-16/D-17/D-18)
nearest_hvn_above_dist_atr: float | None
...
```
Every one of this phase's 41 new fields must be `float | None` — this is D-01's mandatory fix
for `swing_detector`/`trend_structure`'s fields (which the archived plugins emit as fake
numeric defaults) and is the pre-existing convention for every other field in this family
regardless (`fibonacci_zones`/`swing_momentum`/`session_levels` already return `{}`/`None` on
insufficient data in the archived source, so their v3 fields are `float | None` too, no
contested case). Add a comment block per sub-scope (`# Swing Detection (7, Phase 165)`, `#
Swing Momentum (8, Phase 165, D-15)`, `# Trend Structure (6, Phase 165, D-01 nullable-fix)`, `#
Fibonacci Zones (4, Phase 165, D-04/D-05)`, `# Session Levels (16, Phase 165, D-06 through
D-09/D-13)`) matching the `# Session-level — Volume Profile (12, ...)` / `# Session-level —
Support/Resistance (5, ...)` sectioning style — do not interleave with unrelated fields.

**Important field-name collision to check first:** `schemas.py` also contains an *archived*
`I3Structure` Pydantic model (lines 228-341, dead) that happens to define fields with several
of the SAME names this phase is about to add (`swing_high`, `trend_direction`,
`price_position`, etc. — coincidence of both deriving from the same original plugin). Do not
copy field types/defaults from that block — it is not the live `FeatureVector` and several of
its fields are exactly the raw-price/fake-numeric-default shapes this phase must NOT
reproduce. Confirm every new field lands in the live dataclass at (current) lines ~1204-1483,
never near line 228.

---

### 3. `src/intelligence/feature_factory.py` — `FEATURE_VECTOR_DOMAIN` registry

**Analog:** `feature_factory.py:83-106`

```python
# Session-level / market structure
"poc_dist_atr": "structural",
"va_position": "structural",
"sr_support_dist": "structural",
"sr_resist_dist": "structural",
# Session-level — Volume Profile (12, Phase 163 Plan 01)
"nearest_hvn_above_dist_atr": "structural",
...
# Session-level — Support/Resistance (5, Phase 163 Plan 01)
"resistance_strength": "structural",
...
```
All 41 new entries tag `"structural"` (per canonical_refs, matching the existing
`poc_dist_atr`/`va_position`/`sr_support_dist`/`sr_resist_dist` entries) — the IC engine reads
this dict at startup to route fields to their domain bucket; a missing entry means the field is
silently invisible to IC measurement even though it's a real persisted column. Verify via `grep
-c '"structural"' feature_factory.py` before/after (Phase 163 verified 21 → this phase should
land at 62).

---

### 4. `src/intelligence/feature_factory.py` — `FeatureFactoryConfig` new fields

**Analog:** `feature_factory.py:487-504` (Phase 163's `canary_rng_seed`/`session_vp_*`/`sr_*`
defaulted fields, plus the docstring block at lines 360-367 documenting each field's APR key)

```python
# Support/Resistance (Phase 163 Plan 01, consumed by Plan 03). Same
# defaulting rationale as above.
sr_window: int = 10  # feature.sr.window
sr_cluster_atr_mult: float = 0.5  # feature.sr.cluster_atr_mult
sr_lookback_by_tf: dict = field(  # feature.sr.lookback_by_tf
    default_factory=lambda: {"1m": 60, "5m": 60, "15m": 80, "1h": 120, "4h": 90, "1d": 60}
)
```
**Critical convention: give every new field a Python-level default**, not a bare type
annotation (unlike the ~140 pre-existing non-defaulted fields above them in the same
dataclass) — Phase 163's own comment explains why: "avoid updating every pre-existing direct
`FeatureFactoryConfig(...)` construction site across the test suite and services/*.py"; only
the 2 real production entrypoints (`backfill_feature_factory.py`,
`feature_vector_pipeline.py`) need to explicitly wire the real value from `ConfigService`. Add
the docstring `field: APR key` line to the class docstring's parameter list (lines ~360-367
pattern) for every new field — this list is what a future reader greps to find the APR key for
a given config attribute.

Fields needed (from CONTEXT.md D-06/D-07/D-14): `swing_pivot_window` (shared by
swing_detector+trend_structure), `trend_structure_atr_strength_divisor`,
`trend_structure_range_lookback_bars`, `swing_momentum_confirm_n`,
`swing_momentum_max_extremes`, `swing_momentum_reference_bars`,
`swing_momentum_speed_factor_min/max`, `swing_momentum_energy_divisor`,
`swing_momentum_intensity_ramp_lo/hi`, `fib_cluster_atr_divisor`,
`fib_cluster_fallback_divisor`, `session_levels_asia_start_et_hour/asia_end_et_hour`.

---

### 5. `src/intelligence/feature_factory.py` — new pure-compute helper functions

**Analog:** `feature_factory.py:3268-3415` (`_finalize_cluster`, `_cluster_levels`,
`_compute_sr_dist_atr` — the S/R pivot-clustering helpers, since this phase's swing detection
uses the SAME `find_peaks`/`find_troughs` primitive over the SAME kind of bounded-lookback
window)

```python
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
```

This is the closest available shape for `swing_detector.py`/`trend_structure.py`'s port
(both call `find_peaks(high, self.neighbor)`/`find_troughs(low, self.neighbor)` exactly like
`_compute_sr_dist_atr` does): a single stateless function, signature
`(highs, lows, closes, close_, atr_val, volume, config) -> dict[str, float | None]`, module-level
fallback dict constant (`_SWING_FALLBACK`/`_TREND_STRUCTURE_FALLBACK` — **but per D-01, these
fallbacks must be all-`None`, NOT the zero/mirror-of-`_SR_FALLBACK` pattern** — `_SR_FALLBACK`
zeros are fine for S/R because 0.0 is a legitimate "no level found" value there, but
`trend_direction=0.0`/`price_position=0.5` are exactly the fake-plausible-value bug D-01 exists
to kill), `atr_valid` guard at the top, never raises.

**`fibonacci_zones.py` port note:** delete the `i3.get("swing_high")` cross-plugin fallback
entirely (D-05) — compute swing high/low as local numpy values once per bar (shared with the
swing_detector port) and pass them into the fib-zone helper directly; do not reimplement any
fallback branch.

**`swing_momentum.py` port note:** it has its OWN independent `_detect_extremes()`
peak/trough logic (not `find_peaks`/`find_troughs`) — port this as its own private helper
(e.g. `_detect_swing_extremes()`), do not force-unify it with the `find_peaks`/`find_troughs`
call used by swing_detector/trend_structure (CONTEXT.md D-06/Finding B: deliberately separate,
`feature.swing_momentum.confirm_n` is its own APR key).

**`session_levels.py`'s D-08/D-09 rewrite is NOT a `compute()`-time pure function** — see
Pattern 7 below (`FeatureCache` mutator), a fundamentally different shape from the other 4
files.

---

### 6. `src/intelligence/feature_factory.py` — `compute()`/`compute_batch()` wiring +
`_build_feature_vector` signature

**Analog:** `feature_factory.py:3830-3970` (live `compute()`) — S/R call site:

```python
_sr_fields = _compute_sr_dist_atr(highs, lows, close_, atr_val, volumes, tf, config)
sr_support_dist_val: float | None = _sr_fields["sr_support_dist"]
sr_resist_dist_val: float | None = _sr_fields["sr_resist_dist"]
resistance_strength_val: float | None = _sr_fields["resistance_strength"]
...
```
then further down, passed by keyword into `_build_feature_vector(...)`:
```python
sr_support_dist=sr_support_dist_val,
sr_resist_dist=sr_resist_dist_val,
...
resistance_strength=resistance_strength_val,
```

And the VP tf=='1d' neutral-branch precedent (`feature_factory.py:3837-3848`) for any field
that is meaningless on daily bars:
```python
if tf == "1d":
    vp_extra: dict[str, float | None] = dict(_NEUTRAL_VP_EXTRA)
else:
    ...
    vp_extra = _derive_session_vp(cache, close_, atr_val, poc_price_rolling)
```
Note S/R is explicitly NOT gated this way (comment at 3852-3855: "unlike VP... always
computed") — decide per-file whether swing/trend/fib primitives need a tf=='1d' branch (likely
not, since swing detection over daily bars is still meaningful, matching S/R's reasoning) or a
`min_lookback`-driven None (more likely for `session_levels.py`'s weekly rollup on very short
history).

**`_build_feature_vector` signature** (`feature_factory.py:3417-3461`): keyword-only (`*,`),
every new field defaulted to `None` in the same style as the Phase 163 block:
```python
nearest_hvn_above_dist_atr: float | None = None,
nearest_hvn_below_dist_atr: float | None = None,
...
sr_level_count: float | None = None,
```
This is what limits the blast radius of adding 41 new required-in-dataclass-but-optional-here
fields — copy this defaulting discipline exactly for all 41 new kwargs, then thread them
through both `compute()`'s call (~3932-3970) and `compute_batch()`'s mirror call (~4560-4570)
identically — **both paths must be updated in the same commit**, this is the exact live/batch
parity contract `test_sr_live_batch_parity` (Pattern 11 below) exists to guard.

**`_cold_start_vector`** (direct `FeatureVector(...)` construction for `len(bars) < 2`) also
needs all 41 new fields added as `None` args — grep `_cold_start_vector` to find this second
call site; Phase 163's commit `0ff48698` updated it alongside `_build_feature_vector`.

---

### 7. `src/intelligence/feature_cache.py` — new session-boundary mutator (for `session_levels.py`)

**Analog A — session-boundary reset, `update_session_vp()`** (`feature_cache.py:191-232`):
```python
def update_session_vp(
    self,
    bar_ts: datetime,
    high: float,
    low: float,
    close: float,
    volume: float,
    config: FeatureFactoryConfig,
) -> None:
    ts = bar_ts if bar_ts.tzinfo is not None else bar_ts.replace(tzinfo=UTC)
    et = _et_from_utc(ts)
    et_date = et.date()
    session_day = et_date if et.time() >= _RTH_OPEN_ET else et_date - timedelta(days=1)
    if session_day != self._session_day:
        self._sess_bars = []
        self._session_day = session_day
    self._sess_bars.append((float(high), float(low), float(close), float(volume)))
    ...
```
This is the direct template for D-08's rewrite: detect a new session via the ET-calendar-date
transition (using `_et_from_utc` from `src.intelligence.context.session_context`, already
imported at the top of `feature_cache.py`), reset accumulators, recompute from the accumulated
bars. D-08 additionally calls out reusing `_in_ny_session()`-style hour/minute comparison
(`feature_factory.py:1608-1613`) as an alternative/complementary boundary-transition signal —
either the ET-date-change check (this analog) or the `_in_ny_session` 0→1 transition check is
acceptable; `update_session_vp`'s ET-date approach is more directly reusable since it already
lives in `feature_cache.py` next to where the new mutator will live.

**Analog B — ISO-week accumulator extension, `update_wk_vwap()`** (`feature_cache.py:166-189`):
```python
def update_wk_vwap(
    self, bar_ts: datetime, high: float, low: float, close: float, volume: float,
) -> None:
    iso = bar_ts.isocalendar()
    year_week = (iso.year, iso.week)
    if year_week != self._wk_year_week:
        self._wk_tp_vol_sum = 0.0
        self._wk_vol_sum = 0.0
        self._wk_year_week = year_week
    typical = (high + low + close) / 3.0
    self._wk_tp_vol_sum += typical * volume
    self._wk_vol_sum += volume
    ...
```
D-09's mandate: **extend this exact reset block** (`self._wk_year_week` check) with 3 new
`_wk_high`/`_wk_low`/`_wk_close` accumulator fields (sibling to the existing
`_wk_tp_vol_sum`/`_wk_vol_sum`), rather than building a second parallel weekly-boundary
mechanism — do NOT change `update_wk_vwap()`'s existing signature or call sites; either add
the new accumulator lines directly inside `update_wk_vwap()`'s existing `if year_week !=
self._wk_year_week:` reset block, or add a sibling method called from the same per-bar
`advance_bar()` call site (`feature_cache.py:295-310`) — planner's discretion per CONTEXT.md.

**New dataclass fields needed** — follow the existing internal-state field convention
(`feature_cache.py:84-108`, all `field(default=..., repr=False)`, prefixed `_` for
non-`FeatureVector` intermediate state, e.g. `_sess_poc: float | None = field(default=None,
repr=False)`). New fields: `_session_prior_high`/`_session_prior_low`/`_session_prior_close`,
`_session_high`/`_session_low`/`_session_open` (running), `_overnight_high`/`_overnight_low`,
`_wk_high`/`_wk_low`/`_wk_close` (D-09's addition), plus whatever `gap_filled`'s D-13 flag
needs (running session high/low, already covered above — "zero new state needed" per
CONTEXT.md).

**`advance_bar()` call-site pattern** (`feature_cache.py:295-310`):
```python
def advance_bar(
    self, bar_ts: datetime, high: float, low: float, close: float, volume: float,
) -> None:
    self.update_wk_vwap(bar_ts, high, low, close, volume)
    self.hmm_duration += 1.0
```
The new session-boundary mutator does NOT get called from here — Phase 163's `update_session_vp`
is called explicitly by the pipeline/backfill BEFORE `compute()` (Pattern 9 below), not folded
into `advance_bar()` (which runs after). Follow that same explicit-call-site placement, not
`advance_bar()`.

---

### 8. `src/intelligence/features/feature_vector_persistence.py`

**Analog:** `feature_vector_persistence.py:95-113`

```python
_CANARY_FIELD_NAMES: tuple[str, ...] = _ALL_FEATURE_VECTOR_FIELD_NAMES[
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index("canary_noise_gaussian") :
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index("canary_acausal_placebo") + 1
]

# The 17 new structural VP/SR fields (Phase 163 Plan 01, migration 255) are a third
# contiguous, same-order slice -- immediately following the original 4 session-level
# fields (poc_dist_atr/va_position/sr_support_dist/sr_resist_dist) in the dataclass.
_STRUCTURAL_VP_SR_FIELD_NAMES: tuple[str, ...] = _ALL_FEATURE_VECTOR_FIELD_NAMES[
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index("nearest_hvn_above_dist_atr") :
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index("sr_level_count") + 1
]
```
Add a fourth contiguous slice (e.g. `_SWING_FIB_TREND_STRUCTURE_FIELD_NAMES`) derived the same
way — `.index(first_new_field) : .index(last_new_field) + 1` off
`_ALL_FEATURE_VECTOR_FIELD_NAMES` — never hand-type the tuple; this module's whole design goal
(stated at its own docstring lines ~1-11) is making INSERT-column/dataclass-field drift
"structurally impossible." Then append the new slice to the INSERT SQL's column list and the
params tuple, both at the position documented around lines 149-153/236/486 — the running total
column-count comment (`# 181 columns (as of 2026-07-23)`) must be updated to the new total
(181 + 41 = 222, assuming no other phase lands first).

---

### 9. `services/feature_vector_pipeline.py` + `services/backfill_feature_factory.py`

**Analog — config build (both files' `session_vp_*`/`sr_*` block):**
```python
# services/backfill_feature_factory.py:505-511
session_vp_value_area_pct=float(cfg.get_sync("feature.session_vp.value_area_pct", 0.70)),
session_vp_n_buckets=int(cfg.get_sync("feature.session_vp.n_buckets", 50)),
...
sr_window=int(cfg.get_sync("feature.sr.window", 10)),
sr_cluster_atr_mult=float(cfg.get_sync("feature.sr.cluster_atr_mult", 0.5)),
```
```python
# services/feature_vector_pipeline.py:745-751 (mirror, using local _float/_int wrappers)
session_vp_value_area_pct=_float("feature.session_vp.value_area_pct", 0.70),
session_vp_n_buckets=_int("feature.session_vp.n_buckets", 50),
...
```
Both files build a `FeatureFactoryConfig(...)` from `ConfigService`; add one
`get_sync("feature.<new_namespace>.<key>", default)` line per new APR key from Pattern 4,
matching each file's existing wrapper convention (`cfg.get_sync(...)` direct in backfill,
`_float()`/`_int()` local helpers in the live pipeline).

**Analog — per-bar mutator call site** (`services/feature_vector_pipeline.py:1036-1037`):
```python
# VP fields. Mirrors compute_batch()'s per-bar update_session_vp() call.
cache.update_session_vp(bar.ts, bar.high, bar.low, bar.close, float(bar.volume), config)
```
Add the equivalent call for the new `session_levels.py` mutator (Pattern 7) immediately
alongside this line — BOTH the live pipeline's `_process_bar_compute` (this call site) AND
`compute_batch()`'s per-bar loop (backfill) must call it, in the same before-`compute()`
ordering, or live/batch will silently diverge (this is exactly the parity bug class Phase 163's
D-05 fixed).

**Analog — warm-up replay** (`services/feature_vector_pipeline.py:174-202`): on service
restart, `update_wk_vwap()`/`update_session_vp()` are replayed over buffered history so the
mutator doesn't start cold — the new session-boundary mutator needs the same warm-up replay
treatment; read lines 166-210 in full when implementing.

---

### 10. `tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py` (new)

**Analog:** `tests/unit/intelligence/test_support_resistance_primitives.py` (357 lines, full
file read — structure below)

```python
"""Regression: inline S/R FeatureVector fields are non-constant, ATR-unit, live==batch (todo 153)."""
...
N = 140
RNG = np.random.default_rng(16303)

_SR_FIELDS = (
    "sr_support_dist", "sr_resist_dist", "resistance_strength",
    "support_strength", "resistance_age_bars", "support_age_bars", "sr_level_count",
)

def _make_cfg(**overrides: object) -> FeatureFactoryConfig:
    """Small windows so all features warm up well within N bars."""
    defaults = dict(momentum_window_fast=5, ..., sr_window=10, sr_cluster_atr_mult=0.5, ...)
    defaults.update(overrides)
    return FeatureFactoryConfig(**defaults)
```
Test classes/functions to replicate per sub-scope (swing/momentum/trend/fib/session):
- **non-constant regression guard** (`test_sr_non_constant_batch` equivalent) — the direct
  D-01/todo-153-shaped regression test: assert new fields vary across bars, not frozen at a
  fake default.
- **ATR-unit pin** (`test_sr_in_atr_units` equivalent) — hand-constructed constant-true-range
  fixture (Wilder ATR converges to exactly 1.0) pins the raw-price→ATR-distance conversion.
- **live/batch parity** (`test_sr_live_batch_parity` equivalent) — `compute()` vs
  `compute_batch()` agree to 1e-6 on every new field; this is the test that would catch a
  forgotten `compute_batch()` wiring update (Pattern 6's "both paths in the same commit" rule).
- **nullability guard** (new for this phase, no Phase 163 precedent needed since Phase 163
  didn't have D-01's bug) — construct a fixture with `< 2` confirmed swings and assert
  `trend_direction`/`price_position`/etc. are `None`, not `0.0`/`0.5`. This is the single most
  important new test in the phase — it's the direct regression guard for D-01's fix.
- **D-19-style "free field" non-null/non-negative guard** (`test_sr_d19_fields_non_constant`
  equivalent) — for `swing_volume_confirmation` (D-15) and `gap_filled` (D-13).

**Verification discipline** (commit `a748d13d`'s message): "Verified all 4 assertions
actually fail when `_compute_sr_dist_atr` is forced to return its fallback (temporary local
edit, reverted before this commit) — confirms the tests catch the regressions they claim to."
Apply the same mutation-test discipline to Phase 165's new tests before considering them done.

---

## Shared Patterns

### APR migrate-as-you-go (all files)
**Source:** `feature_factory.py:487-504` (defaulted `FeatureFactoryConfig` fields) +
`255_vp_structural_primitives.sql` lines 154-224 (3-part `config_schema`/`config_state`/
`config_history` seed)
**Apply to:** every numeric constant currently hardcoded in the 5 archived plugins (D-06
through D-09's ~13 new keys) — zero inline magic numbers in the ported primitive bodies.

### Nullable FeatureVector fields (D-01's fix, the phase's most important pattern)
**Source:** `schemas.py:1269` (`poc_dist_atr: float | None`, the pre-existing precedent Phase
163 already followed) + `feature_factory.py:3272-3280` (`_SR_FALLBACK` all-zero — the WRONG
model to copy for swing/trend, since 0.0 there is a real "no level" value, not a fake
measurement)
**Apply to:** `trend_structure`'s and `swing_detector`'s new fields specifically — every
early-return/insufficient-data branch must emit `None` per field, never a numeric placeholder.
`swing_momentum`/`fibonacci_zones`/`session_levels` already return `{}`/`None` in the archived
source, so no equivalent fix needed there — but their v3 fields are STILL `float | None` typed
(matching the dataclass convention), they just don't need a behavior change to get there.

### `find_peaks`/`find_troughs` shared pivot-detection utility
**Source:** `src/intelligence/utils.py:15-63` (already imported at
`feature_factory.py:46`) — `find_peaks(data: np.ndarray, n: int) -> list[int]`
**Apply to:** `swing_detector.py`/`trend_structure.py`'s port (both call this with
`n=config.swing_pivot_window`, D-06's shared key). `swing_momentum.py` deliberately does NOT
use this (its own `_detect_extremes()`, D-06's Finding B).

### `get_atr()` → already-computed local `atr_val`, not a fresh cache lookup
**Source:** `feature_factory.py:3832` (`atr_val = float(s.atr_raw[-1]) if len(s.atr_raw) > 0
else 0.0`, computed once near the top of `compute()`) vs. the archived plugins' own
`get_atr(frames.get("i1") or {})` calls (`trend_structure.py:93`, `swing_momentum.py:72`,
`fibonacci_zones.py:48`, `session_levels.py:66`)
**Apply to:** every ported file — do NOT call `get_atr()` inside the new helper functions;
`atr_val` is already a local float in `compute()`/`compute_batch()` by the time any of this
phase's helpers would run — just accept it as a parameter, exactly like `_compute_sr_dist_atr`
does.

### `_build_feature_vector`/`_cold_start_vector`/test-suite blast radius
**Source:** commit `0ff48698` (Phase 163 Plan 01) — touched `services/backfill_feature_factory.py`,
`services/feature_vector_pipeline.py`, `src/intelligence/feature_cache.py`,
`src/intelligence/feature_factory.py`, and 7 test files in one commit for a 17-field addition;
this phase's 41-field addition will touch the same file set (`test_feature_factory_p7.py`,
`test_backfill_feature_factory.py`, `test_feature_vector_writer.py`,
`test_feature_vector_writer_column_mapping.py`, `test_canary_predictors.py`,
`test_feature_factory.py`) plus new dedicated regression tests (Pattern 10).
**Apply to:** budget for this blast radius up front — grep every direct `FeatureVector(...)`
and `_build_feature_vector(...)` construction site (`grep -rn "FeatureVector(" tests/
src/`) before starting, not after CI fails.

### Migration numbering collision — verify, don't trust
**Source:** `255_vp_structural_primitives.sql`'s own header note (renumbered from a stale 243)
**Apply to:** this phase's migration file — run `ls production/migrations/ | sort -V | tail -5`
at implementation time and use the actual next-free number, regardless of what any planning
doc assumes.

## No Analog Found

None — every file in this phase's scope has an exact Phase 163 analog (same phase author, same
week, identical port-from-`i3_structure`-into-v3-`FeatureVector` shape). The one genuinely new
element (D-08/D-09's session-boundary `FeatureCache` mutator for `session_levels.py`) still has
two strong analogs within the same file (`update_session_vp()` for boundary-reset,
`update_wk_vwap()` for the ISO-week accumulator extension) — see Pattern 7.

## Metadata

**Analog search scope:** `src/intelligence/feature_factory.py`, `src/intelligence/schemas.py`,
`src/intelligence/feature_cache.py`, `src/intelligence/features/feature_vector_persistence.py`,
`services/feature_vector_pipeline.py`, `services/backfill_feature_factory.py`,
`production/migrations/255_vp_structural_primitives.sql`,
`tests/unit/intelligence/test_support_resistance_primitives.py`,
`src/intelligence/features/i3_structure/*.py` (port sources), git log of Phase 163's 4 commits
(`4dc708f4`, `0ff48698`, `fde6a2a4`, `bd485e4e`, `a748d13d`).
**Files scanned:** 5 archived plugin files (read in full), 9 live v3 files (targeted reads),
5 Phase 163 commit diffs (stat + targeted content).
**Pattern extraction date:** 2026-07-27
```
