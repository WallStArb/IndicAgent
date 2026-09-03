# Phase 151: Feature Primitives Expansion + Theory-Motivated Interaction Layer - Pattern Map

**Mapped:** 2026-07-24
**Files analyzed:** 8 (5 modified, 1 new migration for Wave 1, 1 new migration for Wave 2/3/4 each, plus test files)
**Analogs found:** 8 / 8 (all files have a direct, currently-live analog — this phase is an extension of a 3x-proven pattern, not greenfield)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/intelligence/schemas.py` (FeatureVector, +28 Wave1 / +~50 Wave2 fields) | model | transform | same file, `FeatureVector` dataclass (Phase 163 Plan 01 17-field addition) | exact (self-analog, additive edit) |
| `src/intelligence/feature_factory.py` (28 new atomic compute fns + FEATURE_VECTOR_DOMAIN entries + `_cold_start_vector` fallbacks) | service (pure-function compute library) | transform | same file — `_dist_from_high`/`_dist_from_high_series_full` (Phase 142.5 Plan 05), `_ret_autocorr_series_full`, `_vol_velocity_z_series_full` (Phase 142.5 Plan 04), `_dow_encoding`/`_quarter_position`/`_days_to_month_end_fraction` (calendar family) | exact |
| `src/intelligence/feature_cache.py` (`update_cross_asset()` extended for TIP/HYG/LQD; new `equity_beta_z`/`rate_beta_z`/`sb_corr` state fields) | model (stateful cache) | event-driven (cross-bar accumulation) | same file — `update_cross_asset()`'s `yield_slope_z` block (TLT/SHY ratio + `_zscore_from_deque`) | exact |
| `services/backfill_feature_factory.py` (wire TIP/HYG/LQD bar fetches alongside SPY/TLT/SHY) | service (batch compute daemon) | batch | same file — `_SPY`/`_TLT`/`_SHY` constants + `update_cross_asset()` call site | exact |
| `services/feature_vector_pipeline.py` (same wiring, live path) | service (streaming compute daemon) | streaming | same file — `self._cache_mgr.update_cross_asset(tf, payload)` call site (line 862) | exact |
| `production/migrations/259_<wave1_name>.sql` (28 `feature_vectors` columns + `feature_registry` rows tier=0_atomic + 5 APR keys) | migration | batch (DDL + seed rows) | `production/migrations/255_vp_structural_primitives.sql` (Phase 163, 2026-07-24, same-day precedent) | exact |
| `production/migrations/<N+1>_<wave2_name>.sql` (feature_registry rows tier=1_interaction, parent_features=[atomic1,atomic2]) | migration | batch | `production/migrations/206_partial_ic_interaction_primitives.sql` (APR key pattern) + live `tier=1_interaction` rows (e.g. `vol_body_product`) for the row-shape template | exact |
| `scripts/ops/alpha/ops_interaction_primitives_pilot.py` (generalize from 8 → ~50 features, Wave 3) | script (batch measurement) | batch | same file — `_load_interaction_features()` already queries `WHERE tier = '1_interaction'` with no feature-count assumption baked into the query itself | exact |
| `services/ic_engine.py::_cluster_features` call sites (Wave 4: add `symbol_hmm_regime` as a second stratification axis) | service (batch measurement) | batch | same file — the **already-live** `dual_write_symbol_hmm` dual-pass mechanism at lines 2133-2159 (`regime_passes` list-of-passes pattern) is the direct template, not a from-scratch design | exact |
| `tests/unit/intelligence/test_feature_factory_batch.py` (extend for 28 new atomics) | test | transform | same file (existing `_series_full` test pattern per feature family) | exact |
| `tests/unit/intelligence/test_feature_registry_service.py` (alignment-gate coverage after each wave's migration) | test | transform | same file (existing row-count == dataclass-field-count assertion) | exact |
| `tests/unit/test_ic_engine_clustering.py` (Wave 4 regime-conditioned clustering) | test | transform | same file (existing `_cluster_features` unit coverage) | exact |

## Pattern Assignments

### `src/intelligence/schemas.py` (model, transform)

**Analog:** same file, `FeatureVector` frozen dataclass — self-extend, follow the exact field-block convention used for the Phase 163 Plan 01 addition.

**Field declaration pattern** (`src/intelligence/schemas.py:1264-1291`, Session-level VP/SR block — the most recent addition, model every Wave 1/2 field group on this exact shape):
```python
# Session-level (21: 4 original + 12 VP + 5 S/R, Phase 163) — session
# volume-profile + support/resistance structural features, computed from
# OHLCV in both live and batch (D-05: no I3/tick-data dependency exists;
# the prior comment claiming batch-unavailability was an inherited,
# never-verified assumption).
poc_dist_atr: float | None
va_position: float | None
...
# Session-level — Volume Profile (12, Phase 163 Plan 01, D-13/D-16/D-17/D-18)
nearest_hvn_above_dist_atr: float | None
nearest_hvn_below_dist_atr: float | None
...
```
Rules to copy exactly: (1) group comment states `(N: breakdown, Phase X)` with the phase/plan provenance; (2) new nullable fields use `float | None` only when cold-start genuinely has no defined value (VP/SR-style); Wave 1's 28 atomics are almost all non-optional `float` with a real cold-start default (calendar/momentum/beta-style), matching the non-VP majority of the dataclass — do not default them to `| None` unless the feature genuinely has no valid cold-start value; (3) the docstring's field-count tally (`Total: 172 (...)`) at the top of the class (`schemas.py:1240`) MUST be updated in the same edit — this is a common miss since it's 60+ lines above the actual field additions.

**Field ordering is binding** (schema column order == migration `ADD COLUMN` order == `feature_registry` insert order) — see the class docstring's own warning (`schemas.py:1215`, "Groups and field order are binding").

---

### `src/intelligence/feature_factory.py` (service/pure-function library, transform)

**Analog A — bounded rolling-window recency primitive** (`bars_since_high_fast/slow`, `bars_since_low_fast/slow`, `bars_since_52w_high/low`, `bars_since_extreme_move_fast/slow`, `bars_since_vol_spike_fast/slow`):

**Source:** `src/intelligence/feature_factory.py:1210-1220` (`_dist_from_high`, magnitude sibling) and `:2249-2256` (`_dist_from_high_series_full`):
```python
def _dist_from_high(close: float, highs: np.ndarray, atr: float, eps: float = 1e-10) -> float:
    """Distance from the rolling high, ATR-normalized: (rolling_high_N - C) / ATR."""
    if atr < eps:
        return 0.0
    rolling_high = float(np.max(highs))
    return (rolling_high - close) / atr


def _dist_from_high_series_full(
    closes: np.ndarray, highs: np.ndarray, atr_padded: np.ndarray, window: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _dist_from_high at bar i."""
    rolling_high = _sliding_rolling_max(highs, window)
    safe_atr = np.where(atr_padded > eps, atr_padded, 1.0)
    raw = (rolling_high - closes.astype(float)) / safe_atr
    return np.where(atr_padded > eps, raw, 0.0)
```
`bars_since_high_fast/slow` needs the "argmax over the window" variant of this exact rolling-max mechanism — use `_sliding_rolling_max`'s window machinery but track *position* of the max via `np.argmax` on each window slice (or an O(n) monotonic-deque "bars since window max" algorithm) instead of the max value itself. **Design constraint from todo 180's Fable review (RESEARCH.md Pattern 1):** must stay bounded `[0, N-1]` (rolling window), NOT an expanding lookback — do not reuse `_ret_autocorr_series_full`'s expanding-window shape for this family.

**Analog B — expanding-window incremental-sum statistic** (`abs_ret_autocorr_1`):

**Source:** `src/intelligence/feature_factory.py:2358-2393` (`_ret_autocorr_series_full`), full text:
```python
def _ret_autocorr_series_full(closes: np.ndarray, lag: int) -> np.ndarray:
    """Expanding-window lag-k Pearson autocorrelation of log returns, computed
    over ALL available history up to each bar. result[i] == streaming
    _ret_autocorr(closes[:i+1], lag). O(n) total via incremental running sums
    (one new pair added per bar, no window to re-sum)."""
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    m = len(log_rets)
    if m < lag + 2:
        return result
    sum_x = sum_y = sum_x2 = sum_y2 = sum_xy = 0.0
    count = 0
    for j in range(m):
        if j >= lag:
            x = float(log_rets[j - lag])
            y = float(log_rets[j])
            sum_x += x; sum_y += y
            sum_x2 += x * x; sum_y2 += y * y; sum_xy += x * y
            count += 1
        if count >= 2:
            mean_x = sum_x / count; mean_y = sum_y / count
            var_x = sum_x2 / count - mean_x * mean_x
            var_y = sum_y2 / count - mean_y * mean_y
            denom = math.sqrt(max(var_x, 0.0) * max(var_y, 0.0))
            if denom > 1e-10:
                cov = sum_xy / count - mean_x * mean_y
                result[j + 1] = cov / denom
    return result
```
`abs_ret_autocorr_1` is the identical incremental-sum construction applied to `np.abs(log_rets)` instead of raw `log_rets` — copy the function body, change the input array, keep `lag=1` fixed (not an APR key — `1` defines the statistic per naming-system.md §7, matching `ret_autocorr_1`'s own precedent).

**Analog C — velocity/delta-of-a-z-score primitive** (`momentum_z_velocity_fast/mid/slow`, `vwap_dev_sigma_velocity`):

**Source:** `src/intelligence/feature_factory.py:2748-2758` (`_vol_velocity_z_series_full`), full text:
```python
def _vol_velocity_z_series_full(atr_z: np.ndarray, window: int) -> np.ndarray:
    """z-score of the rolling velocity (first difference) of atr_z over
    `window`. result[i] == streaming vol_velocity_z at bar i. Fully
    vectorized O(n)."""
    n = len(atr_z)
    if n < 2:
        return np.zeros(n, dtype=float)
    velocity = np.diff(atr_z.astype(float))
    padded = np.concatenate([[0.0], velocity])
    return _fixed_window_zscore_series(padded, window)
```
Apply identically to `momentum_z_fast`/`mid`/`slow` series (→ `momentum_z_velocity_fast/mid/slow`) and to `vwap_dev_sigma` (→ `vwap_dev_sigma_velocity`). Each new family needs its own APR window key per naming-system.md's gradient rule — do NOT reuse `vol_velocity_window` (semantically distinct family).

**Analog D — simple calendar coordinate, no history needed** (`quarter_cycle_sin/cos`, `tdom_sin/cos`, `minute_of_hour_sin/cos`):

**Source:** `src/intelligence/feature_factory.py:1623-1630` (`_dow_encoding`) and `:2842-2856` (`_quarter_position`, `_days_to_month_end_fraction`):
```python
def _dow_encoding(bar_ts: datetime) -> tuple[float, float]:
    """Cyclic weekday encoding: (sin(2*pi*weekday/5), cos(2*pi*weekday/5)).
    weekday() returns 0=Monday, 4=Friday. Weekends treated as Friday."""
    weekday = min(bar_ts.weekday(), 4)
    angle = 2.0 * math.pi * weekday / 5.0
    return math.sin(angle), math.cos(angle)


def _quarter_position(bar_ts: datetime) -> float:
    """Position within the quarter: 0.0 at quarter start, approaching 1.0 at end.
    Formula: (month_in_quarter * 30 + day) / QUARTER_LENGTH_DAYS"""
    month_in_q = (bar_ts.month - 1) % 3
    day_in_q = month_in_q * 30 + bar_ts.day
    return min(1.0, day_in_q / _QUARTER_LENGTH_DAYS)
```
`quarter_cycle_sin/cos` = first circular harmonic of the existing `_quarter_position()` value (`sin/cos(2*pi*quarter_position)`) — reuse `_quarter_position()` directly, don't recompute. `minute_of_hour_sin/cos` and `tdom_sin/cos` follow `_dow_encoding`'s `sin/cos(2*pi*x/period)` shape with `x=bar_ts.minute, period=60` and `x=trading_day_of_month, period=~21` respectively. These are pure functions of `bar_ts`/`config` — no `bars` array, no `_series_full` variant needed (per RESEARCH.md Pattern 1's explicit simpler-pattern carve-out).

**Registry pattern** (`FEATURE_VECTOR_DOMAIN`, `src/intelligence/feature_factory.py:62-145`): every field in `FeatureVector` has exactly one entry here (`"quant"`, `"structural"`, `"regime"`, `"macro"`, `"calendar"`). All 28 Wave 1 atomics need an entry — calendar features → `"calendar"`, momentum-velocity/beta/autocorr → `"quant"`, macro spreads (`tip_tlt_ret_z`/`hyg_lqd_ret_z`) → `"macro"` (matching `vix_z`/`flight_quality`/`yield_slope_z`'s existing 3-entry block at lines 126-128). IC engine reads this dict at startup — a missing entry is a silent gap, not a crash (verify no field is skipped).

**`compute()` call-site wiring** (`src/intelligence/feature_factory.py:3785-3830` signature, `:3980-4048` field-assignment block): every new field must appear exactly once in the giant `FeatureVector(...)` constructor call inside `compute()`, using either a direct helper call (calendar family) or `_series_last(s.<field>, <cold_start_default>)` (series-computed family, where `s` is the `_PrecomputedSeries` bundle built by `_precompute_series()`).

**Cold-start fallback** (`src/intelligence/feature_factory.py:3812-3813` dispatch + `:4727-4819` `_cold_start_vector` body): `if len(bars) < 2: return _cold_start_vector(cache, tf)`. Every new field needs a matching entry in `_cold_start_vector()`'s `FeatureVector(...)` call — the function will hard-crash (missing required constructor arg) if any new non-Optional field is omitted, which is the intended fail-loud behavior; do not add a default to the dataclass field to paper over a missed cold-start entry.

---

### `src/intelligence/feature_cache.py` (model/stateful cache, event-driven)

**Analog:** `update_cross_asset()`'s `yield_slope_z` block — direct template for `tip_tlt_ret_z`/`hyg_lqd_ret_z`.

**Source:** `src/intelligence/feature_cache.py:304-357`, full method (signature + `yield_slope_z` block reproduced):
```python
def update_cross_asset(
    self,
    spy_bars: list[dict],
    tlt_bars: list[dict],
    shy_bars: list[dict],
    config: FeatureFactoryConfig,
) -> None:
    """Populate cross-asset proxy fields from available ETF OHLCV bars."""
    window = config.vix_zscore_window
    # vix_z: SPY trailing realized volatility z-score (proxy for VIX)
    if len(spy_bars) >= 2:
        ...
    # yield_slope_z: TLT/SHY return ratio z-score (2Y-10Y proxy)
    yzw = config.yield_curve_zscore_window
    if len(tlt_bars) >= 2 and len(shy_bars) >= 2:
        n = min(len(tlt_bars), len(shy_bars))
        tlt_closes = np.array([b["close"] for b in tlt_bars[-n:]], dtype=float)
        shy_closes = np.array([b["close"] for b in shy_bars[-n:]], dtype=float)
        tlt_rets = np.diff(np.log(np.maximum(tlt_closes, 1e-10)))
        shy_rets = np.diff(np.log(np.maximum(shy_closes, 1e-10)))
        min_len = min(len(tlt_rets), len(shy_rets))
        if min_len > 0:
            ratio = float(tlt_rets[-1]) - float(shy_rets[-1])
            self._yield_ratio_history.append(ratio)
        self.yield_slope_z = _zscore_from_deque(self._yield_ratio_history, yzw)
```
`tip_tlt_ret_z`/`hyg_lqd_ret_z`: same shape, `tip_bars`/`hyg_bars`/`lqd_bars` replacing `tlt_bars`/`shy_bars`, each with its own `deque(maxlen=500)` history field (mirror `_yield_ratio_history` at `feature_cache.py:74`) and its own APR z-score-window key (do NOT reuse `yield_curve_zscore_window` — semantically distinct spread per naming-system.md).

**Signature change wiring:** `update_cross_asset()`'s signature must grow to accept `tip_bars, hyg_bars, lqd_bars` — both call sites need updating: `services/backfill_feature_factory.py` (constants block `_SPY`/`_TLT`/`_SHY` at lines 122-125, plus wherever `update_cross_asset(` is invoked) and `services/feature_vector_pipeline.py:862` (`await self._cache_mgr.update_cross_asset(tf, payload)`).

**Cache dataclass field declaration pattern** (`src/intelligence/feature_cache.py:52-55, 72-74`):
```python
# Cross-asset cached from cross-asset ETF bars (updated via update_cross_asset())
vix_z: float = 0.0  # SPY realized-vol proxy (VXX/VIXY absent from universe)
flight_quality: float = 0.0  # TLT/SPY divergence
yield_slope_z: float = 0.0  # TLT/SHY ratio z-score
...
_yield_ratio_history: deque = field(default_factory=lambda: deque(maxlen=500), repr=False)
```
New public state field (e.g. `tip_tlt_ret_z: float = 0.0`) plus a matching private `_<name>_history: deque = field(default_factory=..., repr=False)` accumulator, exactly this pair pattern.

---

### `production/migrations/259_<wave1>.sql` (migration, batch DDL+seed)

**Analog:** `production/migrations/255_vp_structural_primitives.sql` (Phase 163, executed same day as RESEARCH.md — the most current template).

**Structure to copy exactly** (full file read; key sections):
1. **Header comment block** documenting migration-numbering collision risk (255's own header names the exact same failure mode twice: "this plan's own text names the file `243_...`, but 243 was already claimed... 255 is the verified next-free number") — Wave 1's migration MUST include an equivalent note and MUST re-verify the actual next-free number at execution time via `ls production/migrations/ | sort -t_ -k1 -n | tail -5` (confirmed 258 is latest as of 2026-07-24; provisional target 259).
2. **Column DDL**, `production/migrations/255_vp_structural_primitives.sql:56-72`:
```sql
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS nearest_hvn_above_dist_atr DOUBLE PRECISION;
...
COMMENT ON COLUMN feature_vectors.nearest_hvn_above_dist_atr IS
    '(nearest HVN bucket price above close - close) / ATR. NULL when no HVN above exists in the session profile. Phase 163.';
```
Type is `DOUBLE PRECISION` for every column (verified live: no `feature_vectors` column uses `real`/float32 despite some plan drafts claiming otherwise — see 255's own header note #3). `ADD COLUMN IF NOT EXISTS` with no default is metadata-only against the compressed hypertable (no decompress step needed).
3. **`feature_registry` INSERT**, `:116-153`:
```sql
INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready, requires_htf, status, added_phase)
VALUES
    ('nearest_hvn_above_dist_atr', 'session', '2_theory',
     '(nearest HVN price above close - close) / ATR', 'z_scored', false, false, 'active', '163'),
    ...
ON CONFLICT (feature_name) DO NOTHING;
```
Wave 1's rows use `tier='0_atomic'` (not `'2_theory'` — that value is specific to migration 255's structural features); `group_name` per family (`'calendar'`, `'quant'`, `'macro'`); `added_phase='151'`.
4. **APR triplet** (`config_schema`/`config_state`/`config_history`), `:159-249` — one `INSERT INTO config_schema` block per key with `[conventional]`/`[initial_estimate]` provenance tag, mirrored `config_state` seed, mirrored `config_history` audit row with `changed_by='migration_259'` (match the file's own migration number, not a stale reference — 255's `config_history` rows correctly say `'migration_255'`, but note 206's `config_history` rows say `'migration_214'`, a **known drift bug** in that older migration; do not copy that mistake).
5. `BEGIN;` / `COMMIT;` wrapping the whole file.

---

### `production/migrations/<N+1>_<wave2>.sql` (migration, batch DDL+seed, Wave 2/3)

**Analog:** `production/migrations/206_partial_ic_interaction_primitives.sql` for the APR-key pattern; live `tier=1_interaction` rows (queried directly, RESEARCH.md Pattern 3) for the `feature_registry` row shape.

**Live row shape to copy exactly** (RESEARCH.md, direct DB query 2026-07-24):
```
feature_name          | parent_features                  | formula_short
vol_body_product       | {body_ratio,volume_z}            | body_ratio * volume_z
ret_vol_product_fast   | {ret_lag_fast,volume_z}          | ret_lag_fast / atr_z
```
**Critical correction (do not follow ROADMAP.md verbatim):** ROADMAP.md's design-rules text says `parent_features=[]` — this contradicts every live row and breaks `ops_interaction_primitives_pilot.py::_load_interaction_features()`'s hard 2-parent unpack (see that function's `ValueError` guard, `scripts/ops/alpha/ops_interaction_primitives_pilot.py:132-139`). Every Wave 2 interaction registration MUST use `parent_features=[atomic1, atomic2]`, exactly 2 elements.

**APR-key migration shape** (`production/migrations/206_partial_ic_interaction_primitives.sql`, full file) — copy the `config_schema`/`config_state`/`config_history` triplet pattern verbatim if Wave 3 mints any new key; otherwise Wave 3 needs no migration at all if it extends the existing `alpha.ic.partial_fdr_alpha` (RESEARCH.md Open Question 1 recommends extending, not minting).

---

### `scripts/ops/alpha/ops_interaction_primitives_pilot.py` (script, batch — Wave 3)

**Analog:** same file — no new script needed, generalize the existing one.

**Source:** `scripts/ops/alpha/ops_interaction_primitives_pilot.py:115-141`, full function:
```python
async def _load_interaction_features(conn: asyncpg.Connection) -> list[dict]:
    """tier='1_interaction' rows from feature_registry with their parent atomics.
    Validated here, once, before any per-tf work starts: every Renaissance
    interaction primitive has exactly 2 parent atomics..."""
    rows = await conn.fetch(
        "SELECT feature_name, parent_features FROM feature_registry "
        "WHERE tier = '1_interaction' AND status = 'active' "
        "ORDER BY feature_name"
    )
    features = []
    for r in rows:
        parents = list(r["parent_features"])
        if len(parents) != 2:
            raise ValueError(
                f"feature_registry row {r['feature_name']!r} has {len(parents)} "
                f"parent_features ({parents!r}) -- partial_spearman_ic's 2-control shape "
                "assumes exactly 2 parent atomics per interaction primitive. ..."
            )
        features.append({"feature_name": r["feature_name"], "parents": parents})
    return features
```
The query itself (`WHERE tier = '1_interaction' AND status = 'active'`) needs **zero code change** — it automatically picks up Wave 2's new rows once they land with `status='active'`. The hard 2-parent `ValueError` guard is exactly why Wave 2 must not use `parent_features=[]`. Config loading (`_load_config`, lines 74-81) and lookahead-scale mapping (`_build_lookahead_map`, lines 84-103) are reusable as-is.

---

### `services/ic_engine.py::_cluster_features` (service, batch — Wave 4)

**Analog:** the file's **own already-live dual-pass mechanism** for `symbol_hmm` regime scope — this is a closer/better template than treating Wave 4 as a from-scratch design.

**Source:** `services/ic_engine.py:2121-2159` (the `regime_passes` list-of-passes loop, full text):
```python
regime_passes: list[tuple[np.ndarray, list, str]] = [
    (regime_aligned_market, distinct_regimes, _resolve_regime_scope(False, cross_sectional))
]
if cross_sectional and dual_write_symbol_hmm:
    distinct_symbol_hmm_regimes = [r for r in set(regime_aligned) if r is not None]
    regime_passes.append((regime_aligned, distinct_symbol_hmm_regimes, "symbol_hmm"))

for label_array, labels_this_pass, resolved_scope in regime_passes:
    for regime_label in labels_this_pass:
        pass_rows, pass_skipped = _compute_one_regime_cell(
            regime_label, False, label_array == regime_label, resolved_scope,
            X_aligned=X_aligned, returns_mat=returns_mat, complete_mat=complete_mat,
            config=config, symbol=symbol, tf=tf, rng=rng,
            training_window_end=training_window_end,
            feature_status_map=feature_status_map, run_ts=run_ts,
        )
        all_results.extend(pass_rows)
        n_skipped += pass_skipped
```
`_cluster_features()` itself (`services/ic_engine.py:1264-1281`, full text):
```python
def _cluster_features(X_nd: np.ndarray, cluster_max_corr: float) -> np.ndarray:
    """Distance-threshold dendrogram clustering of non-degenerate feature columns.
    Returns a 1-based int cluster label per column. Single linkage: two clusters
    merge only when the CLOSEST pair across clusters meets the distance threshold."""
    n_nd = X_nd.shape[1]
    if n_nd < 2:
        return np.ones(n_nd, dtype=int)
    corr = np.corrcoef(X_nd.T)
    corr = np.nan_to_num(corr, nan=0.0)
    dist = np.sqrt(0.5 * (1.0 - np.clip(corr, -1.0, 1.0)))
    np.fill_diagonal(dist, 0.0)
    Z = linkage(squareform(dist, checks=False), method="single")
    dist_threshold = np.sqrt(0.5 * (1.0 - cluster_max_corr))
    return fcluster(Z, t=dist_threshold, criterion="distance")
```
`_cluster_features()` itself is called once per cell inside `_compute_one_regime_cell()` (`services/ic_engine.py:1660`) — it is ALREADY per-(symbol, tf, regime_label) since `_compute_one_regime_cell` is invoked once per label in `regime_passes`' inner loop. **RESEARCH.md's State-of-the-Art correction applies here:** Phase 140 P2 clustering is NOT global — it is already per-(symbol, tf, cross_sectional_regime); the `dual_write_symbol_hmm` mechanism above is the existing precedent for adding a second regime axis (`symbol_hmm`) as an *additional pass*, not a replacement. Wave 4's lightest-weight implementation (RESEARCH.md Open Question 3's recommended default) is to make the `dual_write_symbol_hmm`-style extra pass run unconditionally (or gated by the new `alpha.ensemble.cluster_regime_conditioned` APR key) rather than only for regime-group-routed symbols, and to persist `cluster_id` per pass the same way `feature_ic_scores` already tags rows by `regime_scope` — no new table, per RESEARCH.md's recommended default.

---

## Shared Patterns

### APR key registration (every new tunable)
**Source:** `production/migrations/255_vp_structural_primitives.sql:159-229` (schema/state/history triplet) and `production/migrations/206_partial_ic_interaction_primitives.sql:44-91` (a second live example with the `[initial_estimate]` provenance tag)
**Apply to:** every one of the 5 new APR keys in Wave 1 (`feature.momentum_velocity.window`, a VWAP delta-window key, `macro.sb_corr.window_fast/slow`, `feature.bars_since_extreme_move.sigma_threshold`, `feature.bars_since_vol_spike.threshold`) and any Wave 3/4 key (`alpha.ensemble.cluster_regime_conditioned`).
```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES ('feature.momentum_velocity.window', 'int', '20', 5, 200,
    '[conventional] ... Phase 151. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('feature.momentum_velocity.window', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'feature.momentum_velocity.window', 1, '20', 'migration_259', 'Seed ... [conventional]');
```

### `FeatureVector` alignment gate (every wave's migration)
**Source:** `src/intelligence/feature_registry_service.py:44` (`_REGISTRY_ROW_COUNT = len(dataclasses.fields(FeatureVector))`) and `:110-114`/`:148-152` (the hard `RuntimeError` on mismatch)
**Apply to:** every migration that adds `feature_vectors` columns — the corresponding `feature_registry` INSERT count MUST exactly match the new `schemas.py` field count in the SAME migration/PR, or every `ic_engine.py`/`ensemble_trainer.py` startup hard-crashes.

### `FEATURE_VECTOR_DOMAIN` registry (every new atomic/interaction field)
**Source:** `src/intelligence/feature_factory.py:62-145`
**Apply to:** every new `FeatureVector` field needs exactly one entry (`"quant"`/`"structural"`/`"regime"`/`"macro"`/`"calendar"`) — read by IC engine at startup; a missing entry is a silent gap.

### Cold-start fallback contract (every new atomic field)
**Source:** `src/intelligence/feature_factory.py:3812-3813` dispatch, `:4727-4819` `_cold_start_vector` body
**Apply to:** every new non-Optional field must appear in `_cold_start_vector()`'s constructor call — the dataclass being frozen with no defaults on non-Optional fields means this fails loudly (constructor TypeError) rather than silently, by design; do not paper over a miss by adding a dataclass default.

### DAG Invariant 3 — compute never writes its own output
**Source:** root `CLAUDE.md` DAG Invariants section; enforced structurally by `FeatureFactory.compute()`'s stateless/no-IO contract (`src/intelligence/feature_factory.py:1-25` module docstring: "PURITY CONTRACT: compute() performs zero IO")
**Apply to:** all 28+ new atomics and ~50 interaction features — persistence flows through the existing `FeatureVectorWriter`, never inline in `FeatureFactory.compute()` or `FeatureCache`.

## No Analog Found

None. Every file/pattern this phase touches has a direct, currently-live analog in the codebase (this phase is explicitly framed by RESEARCH.md as "an extension of a fully live, already-proven pipeline... done this exact job three times already").

## Metadata

**Analog search scope:** `src/intelligence/` (feature_factory.py, feature_cache.py, feature_registry_service.py, schemas.py), `services/` (ic_engine.py, backfill_feature_factory.py, feature_vector_pipeline.py), `scripts/ops/alpha/`, `production/migrations/` (169, 206, 255)
**Files scanned:** 8 source files fully or targeted-range read (feature_factory.py 4,916 lines — 6 non-overlapping targeted ranges; feature_cache.py 776 lines — 2 ranges; ic_engine.py 4,878 lines — 3 targeted ranges; schemas.py, feature_registry_service.py, ops_interaction_primitives_pilot.py, migrations 206/255 — read in full)
**Pattern extraction date:** 2026-07-24
