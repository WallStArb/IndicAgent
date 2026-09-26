# Phase 176: Earnings-Season Calendar Primitive (todo 353) - Pattern Map

**Mapped:** 2026-09-22
**Files analyzed:** 15 (per RESEARCH.md's Site Inventory; test/migration files counted separately below)
**Analogs found:** 15 / 15 (every touched file already has a live `opex_flag`/`quad_witching_flag` or
`regime_volatility` stratification precedent in the exact same file)

Naming correction carried from RESEARCH.md: use `earnings_season_flag` (not CONTEXT.md's
`is_earnings_season`) — matches `opex_flag`/`quad_witching_flag`'s `<event>_flag` doctrine
(`docs/foundation/naming-system.md` §7a). All excerpts below are keyed to this corrected name.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/intelligence/feature_factory.py` (2 new pure functions: `_earnings_season_flag`, `_days_since_quarter_end`) | utility (compute primitive) | transform | `_opex_flag`/`_quad_witching_flag` (same file, lines 3363-3384) | exact |
| `src/intelligence/feature_factory.py` (`FeatureFactoryConfig` — 2 new int fields) | config | transform | `ny_session_start_utc_hour` etc. (same file, lines 605-624) | exact |
| `src/intelligence/feature_factory.py` (field-to-group dict, ~line 236-237) | config | transform | `"opex_flag": "calendar"` entries (same file, lines 236-237) | exact |
| `src/intelligence/feature_factory.py` (`compute()` construction site, ~line 7249) | service (compute orchestration) | transform | `opex_flag=_opex_flag(bar_ts)` call site (same file, lines 7249-7250) | exact |
| `src/intelligence/feature_factory.py` (`compute_batch()` inline + construction, ~lines 7768, 8232) | service (compute orchestration) | batch/transform | `opex_flag_val = _opex_flag(bar_ts)` + `opex_flag=opex_flag_val` (same file, lines 7768-7769, 8232-8233) | exact |
| `src/intelligence/feature_factory.py` (`_cold_start_vector()`, ~line 8527) | utility (fallback construction) | transform | `opex_flag=_opex_flag(bar_ts) if bar_ts is not None else 0.0` (same file, lines 8527-8528) | exact |
| `src/intelligence/schemas.py` (`FeatureVector` dataclass, 2 new fields) | model | CRUD (field definition) | `opex_flag`/`quad_witching_flag` fields (same file, lines 1506-1511) | exact |
| `src/intelligence/features/feature_vector_persistence.py` (new contiguous slice + `_ALL_COLUMN_NAMES` append) | utility (column-order derivation) | transform | `_PHASE151_INTERACTION_NAMED_FIELD_NAMES` slice pattern (same file, lines 282-294, 449-461) | exact |
| `services/feature_vector_pipeline.py` (`_prewarm_threshold_config()`, ~line 779) | service (config wiring) | request-response (config fetch) | `("feature.session.ny_start_utc_hour", 13)` seed-list entries (same file, lines 779-789) | exact |
| `services/backfill_feature_factory.py` (~line 491) | service (config wiring, batch path) | batch | `ny_session_start_utc_hour=int(cfg.get_sync(...))` construction (same file, lines 491-505) | exact |
| Migration `350_earnings_season_calendar_primitive.sql` | migration | batch (DDL) | `production/migrations/316_velocity_primitives_extension.sql` (full file) | exact |
| Migration `350_*` — `feature_ic_scores.regime_scope` CHECK widening | migration | batch (DDL) | `production/migrations/187_feature_ic_scores_regime_scope.sql` (full file) | exact |
| `services/ic_engine.py` (`_build_regime_passes()` extension, per-symbol path) | service (measurement) | batch/transform | `_build_regime_passes()` (same file, lines 3101-3131) + `cluster_regime_conditioned` plumbing (lines 3106-3130) | exact |
| `services/ic_engine.py` (SELECT fetch — add `earnings_season_flag` column) | service (measurement) | request-response (DB fetch) | `fv_sql` SELECT at lines 3313-3318 | exact |
| `services/ic_engine.py` (cross-sectional in-memory masking — new insertion point) | service (measurement) | transform | `_compute_one_cross_sectional_cell()` docstring/no-mask-step design (same file, lines 3762-3801) | role-match (new code, no direct precedent for the mask-and-recall step itself) |
| `tests/unit/intelligence/test_feature_factory_p7.py` (new tests) | test | — | `test_opex_flag_third_friday` etc. (same file, lines 477-513) | exact |
| `tests/unit/services/test_feature_vector_writer_column_mapping.py` (new/updated positional-index test) | test | — | `test_quad_witching_flag_at_index_290` (same file, lines 706-725) | exact |
| `tests/unit/services/test_ic_engine.py` (new `_build_regime_passes` test) | test | — | `test_build_regime_passes_symbol_hmm_pass_carries_volatility_labels` (same file, lines 261-291) | exact |
| `tests/unit/services/test_feature_vector_writer.py`, `tests/unit/services/test_backfill_feature_factory.py` (fixture updates) | test | — | existing `opex_flag=0.0, quad_witching_flag=0.0` kwargs in fixtures | exact |

## Pattern Assignments

### `src/intelligence/feature_factory.py` — pure calendar primitive functions

**Analog:** `_opex_flag` / `_quad_witching_flag` / `_quarter_position` / `_quarter_cycle_encoding` (same file, lines 3303-3384)

**Core pattern — pure `bar_ts`-only function, no APR needed** (lines 3303-3310, `_quarter_position`):
```python
def _quarter_position(bar_ts: datetime) -> float:
    """Position within the quarter: 0.0 at quarter start, approaching 1.0 at end.

    Formula: (month_in_quarter * 30 + day) / QUARTER_LENGTH_DAYS
    """
    month_in_q = (bar_ts.month - 1) % 3
    day_in_q = month_in_q * 30 + bar_ts.day
    return min(1.0, day_in_q / _QUARTER_LENGTH_DAYS)
```
`_days_since_quarter_end(bar_ts)` should follow this exact shape — pure function of `bar_ts`,
docstring states the formula, no config param (per RESEARCH.md, it needs no APR window).

**Reuse-another-primitive precedent** (lines 3320-3328, `_quarter_cycle_encoding`):
```python
def _quarter_cycle_encoding(bar_ts: datetime) -> tuple[float, float]:
    """First circular harmonic of _quarter_position(): (sin(2*pi*qp), cos(2*pi*qp)).

    Reuses _quarter_position() directly rather than recomputing the
    within-quarter position (Phase 151 Plan 01, todo 104).
    """
    qp = _quarter_position(bar_ts)
    angle = 2.0 * math.pi * qp
    return math.sin(angle), math.cos(angle)
```
`_quad_witching_flag` applies the identical discipline by calling `_opex_flag(bar_ts)` directly
(line 3384) rather than restating its condition — a project-enforced pattern (see the dedicated
regression test `test_quad_witching_flag_calls_opex_flag_not_restated`, excerpted below).

**Core pattern — APR-gated function taking `config: FeatureFactoryConfig`** (lines 3363-3374,
`_opex_flag`, is the naming/doc shape; `_in_ny_session` is the config-threading shape):
```python
def _opex_flag(bar_ts: datetime) -> float:
    """1.0 iff bar_ts falls on the monthly options-expiration Friday, else 0.0.

    Formula (Phase 151 Plan 05, todos 066/104): dow == Friday (weekday() == 4)
    AND week_of_month == 3, where week_of_month = (day - 1) // 7 + 1. Matches
    docs/research/signal-temporal-atomic-primitives.md's prescribed formula
    literally. Deliberately no market-holiday table -- the source doc rejects
    one as nonstationary institutional data (same rationale as _tdom_encoding
    above).
    """
    week_of_month = (bar_ts.day - 1) // 7 + 1
    return 1.0 if (bar_ts.weekday() == 4 and week_of_month == 3) else 0.0
```
```python
# Source: src/intelligence/feature_factory.py:1970 (config-threading shape for
# an APR-gated bar_ts-only calendar function — _earnings_season_flag must copy this)
def _in_ny_session(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is within NY RTH, else 0.0."""
    total_minutes = bar_ts.hour * 60 + bar_ts.minute
    start_minutes = config.ny_session_start_utc_hour * 60 + config.ny_session_start_utc_minute
    end_minutes = config.ny_session_end_utc_hour * 60
    return 1.0 if start_minutes <= total_minutes < end_minutes else 0.0
```
`_earnings_season_flag(bar_ts, config)` should combine both: whole-`config`-object param (not
bare ints), and internally call `_days_since_quarter_end(bar_ts)` to test against
`config.earnings_season_start_days`/`config.earnings_season_end_days` (reuse discipline, same as
`_quad_witching_flag` calling `_opex_flag`).

### `src/intelligence/feature_factory.py` — `FeatureFactoryConfig` APR field declaration

**Analog:** session/calendar int fields (same file, lines 605-624)
```python
# Session / calendar (APR-backed so DST/market-hour adjustments are operationally safe)
ny_session_start_utc_hour: int  # feature.session.ny_start_utc_hour
ny_session_start_utc_minute: int  # feature.session.ny_start_utc_minute
ny_session_end_utc_hour: int  # feature.session.ny_end_utc_hour
overlap_start_utc_hour: int  # feature.session.overlap_start_utc_hour
overlap_end_utc_hour: int  # feature.session.overlap_end_utc_hour
```
Add `earnings_season_start_days: int  # feature.earnings_season.start_days` and
`earnings_season_end_days: int  # feature.earnings_season.end_days` in the same style —
inline comment names the exact APR key, matching every other field in this block.

### `src/intelligence/feature_factory.py` — field-to-group dict

**Analog:** lines 236-237
```python
"opex_flag": "calendar",
"quad_witching_flag": "calendar",
```
Add `"earnings_season_flag": "calendar"` and `"days_since_quarter_end": "calendar"` immediately
after, same dict, same group string.

### `src/intelligence/feature_factory.py` — `compute()` construction site

**Analog:** lines 7238-7250
```python
# Named Interaction Primitives (Phase 151 Plan 05). The 3 cross-TF
# divergences have NO live-path plumbing today (batch is the
# corpus/IC-measurement path; the LTF/HTF merge-walk builders live
# only in backfill_feature_factory.py) -- always None here, same
# asymmetry already documented for the Plan 04 cross-asset gap
# (todo filed at that plan's Task 4). opex_flag/quad_witching_flag
# need only bar_ts, which IS in scope on both paths, so they
# compute real values here too.
ret_div_1m_5m=None,
ret_div_5m_1h=None,
ret_div_1h_1d=None,
opex_flag=_opex_flag(bar_ts),
quad_witching_flag=_quad_witching_flag(bar_ts),
```
New fields follow the `opex_flag=_opex_flag(bar_ts)` shape exactly:
`earnings_season_flag=_earnings_season_flag(bar_ts, config)`,
`days_since_quarter_end=_days_since_quarter_end(bar_ts)`.

### `src/intelligence/feature_factory.py` — `compute_batch()` inline + construction

**Analog:** lines 7768-7769 (inline compute) and 8232-8233 (construction)
```python
opex_flag_val = _opex_flag(bar_ts)
quad_witching_flag_val = _quad_witching_flag(bar_ts)
```
```python
opex_flag=opex_flag_val,
quad_witching_flag=quad_witching_flag_val,
```
Two separate touch points within the same function, exact same `<field>_val = <fn>(bar_ts)`
then `<field>=<field>_val` two-step — copy verbatim shape for the 2 new fields.

### `src/intelligence/feature_factory.py` — `_cold_start_vector()`

**Analog:** lines 8517-8528
```python
# Phase 151 Plan 05: cold start (len(bars) < 2) has no bar history, so
# the 3 cross-TF divergences (which need a prior/HTF return) are
# always None here -- "not measured" is correct with zero bars. The 2
# calendar event flags need only bar_ts (no history), so they compute
# real values when bar_ts is available (len(bars) == 1); with zero
# bars there is no timestamp at all, so they fall back to 0.0 (the
# same neutral convention already used above for dow_sin/cos etc).
ret_div_1m_5m=None,
ret_div_5m_1h=None,
ret_div_1h_1d=None,
opex_flag=_opex_flag(bar_ts) if bar_ts is not None else 0.0,
quad_witching_flag=_quad_witching_flag(bar_ts) if bar_ts is not None else 0.0,
```
Note: `_cold_start_vector()` has no `config` parameter today — planning must check whether
`_earnings_season_flag` needs `config` threaded into this function's signature too, or whether a
neutral 0.0 fallback (matching `opex_flag`'s pattern) is acceptable without it since `bar_ts is
None` already short-circuits to 0.0 in the common case.

### `src/intelligence/schemas.py` — `FeatureVector` dataclass fields

**Analog:** lines 1506-1511
```python
opex_flag: (
    float  # 1.0 iff dow==Friday AND week_of_month==3 (monthly options expiration), else 0.0
)
quad_witching_flag: (
    float  # 1.0 iff opex_flag==1.0 AND month % 3 == 0 (quarterly quad-witching), else 0.0
)
```
No defaults (Pitfall 4) — every construction site listed above must supply these as required
kwargs in the same commit. Append immediately after `volume_z_velocity` (current last field,
298 fields total per RESEARCH.md).

### `src/intelligence/features/feature_vector_persistence.py` — contiguous column-name slice

**Analog:** `_PHASE151_INTERACTION_NAMED_FIELD_NAMES` (lines 282-294) and its inclusion in
`_ALL_COLUMN_NAMES` (lines 449-461)
```python
# The 5 new Phase 151 Plan 05 fields (migration 290) are a ninth contiguous,
# same-order slice -- 3 cross-TF return divergences (ret_div_1m_5m/5m_1h/1h_1d)
# immediately followed by 2 calendar event flags (opex_flag,
# quad_witching_flag), declared as ONE contiguous run in schemas.py
# immediately after Plan 04's rate_beta_z field. Same derive-don't-hand-type
# discipline as the eight slices above; appended at the end of the column
# list below.
_PHASE151_INTERACTION_NAMED_FIELD_NAMES: tuple[str, ...] = _ALL_FEATURE_VECTOR_FIELD_NAMES[
    _ALL_FEATURE_VECTOR_FIELD_NAMES.index("ret_div_1m_5m") : _ALL_FEATURE_VECTOR_FIELD_NAMES.index(
        "quad_witching_flag"
    )
    + 1
]
```
```python
_ALL_COLUMN_NAMES: tuple[str, ...] = (
    _STRUCTURAL_PREFIX_COLUMN_NAMES
    + _RENAISSANCE_PRIMITIVE_FIELD_NAMES
    + ...
    + _VELOCITY_EXTENSION_FIELD_NAMES
    # NEW: + _EARNINGS_SEASON_FIELD_NAMES
)
```
Add a new `_EARNINGS_SEASON_FIELD_NAMES` slice (bounded by `.index("earnings_season_flag")` and
`.index("days_since_quarter_end")`) using the identical `.index(...) : .index(...) + 1` slice
idiom, append to the `_ALL_COLUMN_NAMES` concatenation, and update the module docstring's column
count comment (line ~357-372, currently documents "307 columns ... $302-$307 migration-316" — new
fields become $308-$309).

### `services/feature_vector_pipeline.py` / `services/backfill_feature_factory.py` — APR seed wiring

**Analog:** `services/feature_vector_pipeline.py` lines 779-789 (seed list) +
`services/backfill_feature_factory.py` lines 491-505 (construction)
```python
# services/feature_vector_pipeline.py:779-789 -- seed-list entries, one tuple per APR key
("feature.session.ny_start_utc_hour", 13),
("feature.session.ny_start_utc_minute", 30),
("feature.session.ny_end_utc_hour", 20),
```
```python
# services/backfill_feature_factory.py:491-495 -- FeatureFactoryConfig construction, mirrors the same keys
ny_session_start_utc_hour=int(cfg.get_sync("feature.session.ny_start_utc_hour", 13)),
ny_session_start_utc_minute=int(cfg.get_sync("feature.session.ny_start_utc_minute", 30)),
ny_session_end_utc_hour=int(cfg.get_sync("feature.session.ny_end_utc_hour", 20)),
```
Add `("feature.earnings_season.start_days", 14)` / `("feature.earnings_season.end_days", 42)` to
the pipeline's seed list (~line 779) and
`earnings_season_start_days=int(cfg.get_sync("feature.earnings_season.start_days", 14))` /
`earnings_season_end_days=int(cfg.get_sync("feature.earnings_season.end_days", 42))` to both
`_prewarm_threshold_config()` construction sites — **both files must be updated together**
(production path + batch/backfill path), same as every other APR-backed calendar boundary in
this codebase.

---

## `services/ic_engine.py` — regime-conditioning integration

### Pattern: `_build_regime_passes()` extension (per-symbol path)

**Analog:** `_build_regime_passes()` itself (lines 3101-3131)
```python
def _build_regime_passes(
    regime_aligned_market: np.ndarray,
    distinct_regimes: list,
    regime_aligned: np.ndarray,
    cross_sectional: bool,
    dual_write_symbol_hmm: bool,
    cluster_regime_conditioned: bool,
    primary_resolved_scope: str,
) -> list[tuple[np.ndarray, list, str]]:
    """Build the list of (label_array, distinct_labels, resolved_scope) passes
    _compute_symbol_tf's per-label-array loop iterates over.
    ...
    """
    regime_passes: list[tuple[np.ndarray, list, str]] = [
        (regime_aligned_market, distinct_regimes, primary_resolved_scope)
    ]
    if cross_sectional and (dual_write_symbol_hmm or cluster_regime_conditioned):
        distinct_symbol_hmm_regimes = [r for r in set(regime_aligned) if r is not None]
        regime_passes.append((regime_aligned, distinct_symbol_hmm_regimes, "symbol_hmm"))
    return regime_passes
```
Extend with a new APR-gated `earnings_season_conditioned` param following the exact
`cluster_regime_conditioned` shape:
```python
if earnings_season_conditioned:
    distinct_earnings_season = [r for r in set(earnings_season_aligned) if r is not None]
    regime_passes.append((earnings_season_aligned, distinct_earnings_season, "earnings_season"))
```
`earnings_season_aligned` must be a `"in_season"`/`"off_season"` string-label array, mapped from
the fetched 0.0/1.0 `earnings_season_flag` column — matches every other regime axis's string-label
convention (see the SELECT pattern below).

### Pattern: fetch site — add `earnings_season_flag` to the existing SELECT

**Analog:** lines 3313-3318
```python
feature_cols = ", ".join(f'"{f}"' for f in _FEATURE_NAMES)
fv_sql = f"""
    SELECT bar_ts, regime_volatility, {feature_cols}
    FROM feature_vectors
    WHERE symbol = %s AND tf = %s AND bar_ts <= %s
    ORDER BY bar_ts
"""
```
Add `earnings_season_flag` as a third selected column (`SELECT bar_ts, regime_volatility,
earnings_season_flag, {feature_cols}`) — read the already-persisted column, never recompute
calendar math here (D-03 mandate, explicit anti-pattern in RESEARCH.md).

### Pattern: `_build_regime_passes()`'s pure-function unit test shape (no live DB)

**Analog:** `tests/unit/services/test_ic_engine.py` lines 261-291
```python
def test_build_regime_passes_symbol_hmm_pass_carries_volatility_labels() -> None:
    regime_aligned_market = np.array(["breadth_vol_high", "breadth_vol_low", "breadth_vol_high"])
    distinct_regimes = ["breadth_vol_high", "breadth_vol_low"]
    regime_aligned = np.array(["calm", "elevated", "turbulent"])

    passes = _build_regime_passes(
        regime_aligned_market,
        distinct_regimes,
        regime_aligned,
        cross_sectional=True,
        dual_write_symbol_hmm=True,
        cluster_regime_conditioned=False,
        primary_resolved_scope="cross_sectional",
    )

    assert len(passes) == 2
    primary_label_array, primary_labels, primary_scope = passes[0]
    assert primary_scope == "cross_sectional"
    assert set(primary_labels) == set(distinct_regimes)

    symbol_hmm_label_array, symbol_hmm_labels, symbol_hmm_scope = passes[1]
    assert symbol_hmm_scope == "symbol_hmm"
    assert set(symbol_hmm_labels) == {"calm", "elevated", "turbulent"}
    assert list(symbol_hmm_label_array) == list(regime_aligned)
```
New test mirrors this exactly, driving the extended `_build_regime_passes()` with a fake
`earnings_season_aligned` array and asserting a 3rd pass with `resolved_scope="earnings_season"`
and labels `{"in_season", "off_season"}`.

### Pattern: cross-sectional path — reuse `_compute_one_cross_sectional_cell`, mask don't re-fetch

**Analog:** `_compute_one_cross_sectional_cell()` docstring (lines 3779-3793) — states the
explicit no-internal-mask design this phase's caller-side masking must respect:
```python
"""Compute clustering + per-scale IC/CI/walk-forward/Sharpe for ONE cross-sectional cell.

Extracted from _compute_cross_sectional_tf's inline per-scale loop (162-01 Task 3,
todos 139/140), mirroring _compute_one_regime_cell's shape on the per-symbol side.
Unlike _compute_one_regime_cell, X_raw/returns_mat/complete_mat here are ALREADY the
full cell's pooled cross-symbol data -- the caller's chunked fetch scopes to exactly
this (tf, regime_label) cell, so there is no additional `mask` selection step (cross-
sectional cells are fetched one at a time, not sliced out of a larger per-symbol array).
...
"""
```
No existing caller performs an in-memory row-slice-then-recall of this function — this is new
code, not a copy-paste site (Open Question 2 in RESEARCH.md flags the exact insertion point as
needing dedicated investigation in `_compute_cross_sectional_tf`/`main()`, services/ic_engine.py
~line 4466 onward / ~6260-7000). Do **not** add a third DB-fetch dimension; call
`_compute_one_cross_sectional_cell` a second time per season-state with row-sliced (not
re-fetched) `X_raw`/`returns_mat`/`complete_mat` arrays, reusing 100% of its existing bootstrap/
CI/FDR/walk-forward internals.

### Pattern: `cluster_regime_conditioned`-style run-level APR switch (precedent for
`earnings_season_conditioned`)

**Analog:** lines 627, 862-863, 978
```python
cluster_regime_conditioned: bool = True
```
```python
cluster_regime_conditioned=bool(
    cfg.get_sync("alpha.ensemble.cluster_regime_conditioned", True)
),
```
Add an `earnings_season_conditioned: bool = True` field to `ICEngineConfig` and load it the same
way — RESEARCH.md's Open Question 1 recommends defaulting `true` (unconditional, matches D-01).

---

## Migration `350_earnings_season_calendar_primitive.sql`

### Pattern: `ALTER TABLE ADD COLUMN` + APR seed + `concept_registry`/`concept_gate` genesis seed

**Analog:** `production/migrations/316_velocity_primitives_extension.sql` (full file, 162 lines)
```sql
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS rsi_velocity_fast real;
...
COMMENT ON COLUMN feature_vectors.rsi_velocity_fast IS
    'z-score of the rolling velocity (first difference) of rsi_fast over feature.rsi_velocity.window bars. Todo 320.';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'feature.rsi_velocity.window', 'int', '14', 2, 200,
    '[conventional] Bar-lag window for the first-difference-then-z-score construction ...'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('feature.rsi_velocity.window', '14', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'feature.rsi_velocity.window', 1, '14', 'migration_316',
    'Seed RSI-velocity z-score window, todo 320 [conventional]')
ON CONFLICT DO NOTHING;

INSERT INTO concept_registry
    (domain, name, description, status, enabled, group_name, is_control, added_phase, metadata)
VALUES
    ('feature', 'rsi_velocity_fast', 'zscore(diff(rsi_fast))', 'active', true, 'momentum', false, 'todo320',
     jsonb_build_object('tier', '0_atomic', 'formula_short', 'zscore(diff(rsi_fast))',
         'normalization', 'z_scored', 'linear_ready', true, 'requires_htf', false,
         'apr_namespace', 'feature.'))
ON CONFLICT (domain, name) DO NOTHING;

INSERT INTO concept_gate
    (concept_id, gate_metric_name, gate_eval_method, min_gate_n, fdr_required, fdr_alpha)
SELECT cr.concept_id, 'ic_sharpe_hac', 'bootstrap_ci', 100, true, 0.05
FROM concept_registry cr
WHERE cr.domain = 'feature' AND cr.name IN ('rsi_velocity_fast', ...)
ON CONFLICT (concept_id) DO NOTHING;
```
Key differences from this template for migration 350: (1) `tier` in `metadata` must be
`'1_interaction'` (not `'0_atomic'`) with a non-empty `parent_features` array (Pattern 1 in
RESEARCH.md — see the exact `concept_registry` INSERT already drafted there, reproduced below);
(2) column type `real`, no `DEFAULT`, no VACUUM step needed (plain `ADD COLUMN IF NOT EXISTS`
against a compressed hypertable, per migration 316's own comment block, lines 16-25).

**Exact `concept_registry`/`concept_gate` INSERT already drafted (RESEARCH.md Code Examples,
adapted from migration 316's current-generation pattern):**
```sql
INSERT INTO concept_registry
    (domain, name, description, status, enabled, group_name, is_control, added_phase, metadata)
VALUES
    ('feature', 'earnings_season_flag',
     '1.0 iff bar_ts falls feature.earnings_season.start_days-feature.earnings_season.end_days '
     'after the most recent calendar quarter end, else 0.0', 'active', true, 'calendar', false,
     '176',
     jsonb_build_object('tier', '1_interaction', 'formula_short',
         'days_since_quarter_end BETWEEN start_days AND end_days',
         'normalization', 'bounded_unsigned', 'linear_ready', false, 'requires_htf', false,
         'apr_namespace', 'feature.earnings_season.',
         'parent_features', jsonb_build_array('quarter_position', 'quarter_cycle_sin'))),
    ('feature', 'days_since_quarter_end',
     'Raw calendar days since the most recent quarter end (Mar 31/Jun 30/Sep 30/Dec 31)',
     'active', true, 'calendar', false, '176',
     jsonb_build_object('tier', '1_interaction', 'formula_short',
         'bar_ts.date() - last_quarter_end.date()',
         'normalization', 'unbounded_unsigned', 'linear_ready', true, 'requires_htf', false,
         'apr_namespace', 'feature.',
         'parent_features', jsonb_build_array('quarter_position', 'quarter_cycle_cos')))
ON CONFLICT (domain, name) DO NOTHING;

INSERT INTO concept_gate
    (concept_id, gate_metric_name, gate_eval_method, min_gate_n, fdr_required, fdr_alpha)
SELECT cr.concept_id, 'ic_sharpe_hac', 'bootstrap_ci', 100, true, 0.05
FROM concept_registry cr
WHERE cr.domain = 'feature'
  AND cr.name IN ('earnings_season_flag', 'days_since_quarter_end')
ON CONFLICT (concept_id) DO NOTHING;
```

### Pattern: `feature_ic_scores.regime_scope` CHECK constraint widening

**Analog:** `production/migrations/187_feature_ic_scores_regime_scope.sql` (full file)
```sql
ALTER TABLE feature_ic_scores DROP CONSTRAINT IF EXISTS feature_ic_scores_regime_scope_chk;

ALTER TABLE feature_ic_scores ADD CONSTRAINT feature_ic_scores_regime_scope_chk
    CHECK (regime_scope IN ('cross_sectional', 'symbol_hmm', 'pooled'));
```
Migration 350 (or a same-phase follow-up) must re-run this exact `DROP CONSTRAINT IF EXISTS` /
`ADD CONSTRAINT` shape, widening the `IN (...)` list to add `'earnings_season'`. Per Pitfall 2 in
RESEARCH.md, also `grep -rn "regime_scope" services/ scripts/` before finalizing to confirm
`ensemble_trainer.py`/`alpha_publisher.py`/any dashboard route either allow-lists the new value
or is provably scope-agnostic.

---

## Test Patterns

### `tests/unit/intelligence/test_feature_factory_p7.py` — pure-function boundary tests

**Analog:** lines 470-513
```python
# ---------------------------------------------------------------------------
# opex_flag / quad_witching_flag (Phase 151 Plan 05, todo 104)
# ---------------------------------------------------------------------------


def test_opex_flag_third_friday():
    """2026-03-20 is the third Friday of March 2026 -- the monthly OPEX date."""
    assert _opex_flag(datetime(2026, 3, 20, 15, 0, tzinfo=UTC)) == 1.0


def test_opex_flag_second_friday_not_flagged():
    assert _opex_flag(datetime(2026, 3, 13, 15, 0, tzinfo=UTC)) == 0.0

...

def test_quad_witching_flag_calls_opex_flag_not_restated():
    """Guards Pitfall correction: quad_witching_flag must call _opex_flag(), not
    restate its dow/week_of_month condition inline."""
    import inspect

    src = inspect.getsource(_quad_witching_flag)
    assert "_opex_flag(" in src
```
New tests need: window-boundary cases (day 13/14 and 42/43 relative to quarter end — off-by-one
at both edges), cold-start `bar_ts=None` handling, and a `test_earnings_season_flag_calls_days_since_quarter_end_not_restated`-style
`inspect.getsource()` regression test mirroring the reuse-discipline guard above.

### `tests/unit/services/test_feature_vector_writer_column_mapping.py` — positional-index test

**Analog:** lines 706-725 (`test_quad_witching_flag_at_index_290`)
```python
def test_quad_witching_flag_at_index_290():
    """params[290] ($291) must be quad_witching_flag sentinel value 63.05 --
    the final column of the pre-Phase-151-Plan-06 contract, appended after
    the cross-asset spread/beta fields by migration 290's 5 Named
    Interaction Primitives columns (Phase 151 Plan 05). No longer the true
    last element as of migration 291 (Phase 151 Plan 06) -- 10
    Theory-Motivated Interaction columns are appended after it; see
    test_volume_z_velocity_at_index_306_is_last_element below for
    the current tail."""
    from services.feature_vector_writer import _record_to_insert_params

    record = _make_sentinel_record()
    params = _record_to_insert_params(record)

    assert len(params) == 307
    assert params[286] == pytest.approx(63.01), f"$287 (ret_div_1m_5m) wrong: {params[286]}"
    ...
    assert params[289] == pytest.approx(63.04), f"$290 (opex_flag) wrong: {params[289]}"
    assert params[290] == pytest.approx(63.05), f"$291 (quad_witching_flag) wrong: {params[290]}"
```
Find the current `test_volume_z_velocity_at_index_306_is_last_element`-equivalent test (the
existing "is last element" test the docstring above forward-references), update its
"no longer the true last element" docstring to point at the new fields, and add a new
`test_days_since_quarter_end_at_index_308_is_last_element`-style test with fresh sentinel values
(len(params) becomes 309, not 307).

---

## Shared Patterns

### Component reuse / no-parallel-mechanism discipline (D-03)
**Source:** `_quarter_cycle_encoding` calling `_quarter_position` directly (feature_factory.py:3326);
`_quad_witching_flag` calling `_opex_flag` directly (feature_factory.py:3384); enforced by a
dedicated regression test (`test_quad_witching_flag_calls_opex_flag_not_restated`).
**Apply to:** `_earnings_season_flag` calling `_days_since_quarter_end` internally, never
restating the quarter-end arithmetic; `_build_regime_passes()`'s `earnings_season` pass reusing
`_compute_one_regime_cell`/`_compute_one_cross_sectional_cell` verbatim, never a parallel
mechanism.

### APR-backed numeric threshold, threaded through a frozen config object
**Source:** `FeatureFactoryConfig`'s session/calendar int fields (feature_factory.py:605-624) +
both `_prewarm_threshold_config()` call sites (feature_vector_pipeline.py:779-789,
backfill_feature_factory.py:491-505).
**Apply to:** `earnings_season_start_days`/`earnings_season_end_days` — both files, both the seed
list and the construction call, in the same commit.

### Derive-by-name, don't-hand-type column order
**Source:** `feature_vector_persistence.py`'s entire `_ALL_COLUMN_NAMES` contiguous-slice design
(module docstring cites the "91/152 fields silently unpersisted" incident this pattern exists to
prevent).
**Apply to:** the new `_EARNINGS_SEASON_FIELD_NAMES` slice — never hand-type a column list.

### No-defaults dataclass construction-site parity (Pitfall 4)
**Source:** `opex_flag: float` / `quad_witching_flag: float` fields with no `= 0.0` default
(schemas.py:1506-1511), forcing every construction site to supply them as kwargs.
**Apply to:** every `FeatureVector(...)` construction site listed in the File Classification
table above must land in the same atomic commit as the schema change — `compute()`,
`compute_batch()` (2 sites), `_cold_start_vector()`, and both test fixture files.

## No Analog Found

None — every file in RESEARCH.md's Site Inventory has a live, same-file precedent from the
`opex_flag`/`quad_witching_flag` (migration 290) or `regime_volatility` stratification
(Phase 172 plan 06) construction. The one partial-match noted above
(`_compute_one_cross_sectional_cell`'s caller-side masking) is new code by design — RESEARCH.md's
Open Question 2 already flags it as needing a dedicated investigation task before the plan is
written, not a missing-pattern gap.

## Metadata

**Analog search scope:** `src/intelligence/feature_factory.py`, `src/intelligence/schemas.py`,
`src/intelligence/features/feature_vector_persistence.py`, `services/ic_engine.py`,
`services/feature_vector_pipeline.py`, `services/backfill_feature_factory.py`,
`production/migrations/{187,290,316}_*.sql`, `tests/unit/intelligence/test_feature_factory_p7.py`,
`tests/unit/services/{test_feature_vector_writer_column_mapping,test_ic_engine}.py`
**Files scanned:** 12 source/test files + 3 migration files (all pre-identified by RESEARCH.md's
Site Inventory; this pass verified live line numbers and extracted exact excerpts rather than
searching blind)
**Pattern extraction date:** 2026-09-22
