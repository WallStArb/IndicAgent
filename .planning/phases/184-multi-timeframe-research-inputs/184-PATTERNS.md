# Phase 184: Multi-timeframe research inputs - Pattern map

**Mapped:** 2026-10-27
**Files analyzed:** 31 (13 new source files, 6 modified source files, 12 new or extended test files)
**Analogs found:** 30 / 31 (B8's economic block has only a partial analog)

Line numbers are from the working tree on 2026-10-27. Three files carry uncommitted edits from
another session (the daily_unseen members' universe): `runner.py` (lines 410-411),
`snapshot.py` (lines 223-255) and `spec.py` (line 83). `families/daily_residual.py` and
`tests/unit/research/test_daily_unseen.py` are untracked WIP from the same session. Do not cite
`daily_residual.py` as the member analog until it is committed; the excerpts below use
`overnight_intraday.py` and `common.py`, which are committed. Re-check line numbers at execution.

## File classification

| New/modified file | Role | Data flow | Closest analog | Match quality |
|---|---|---|---|---|
| `src/intelligence/research/clock.py` (+) | utility (pure) | transform | `snapshot.build_grid` intraday branch + `bars/sessions.nyse_sessions` | role-match |
| `src/intelligence/research/align.py` (+) | utility (pure, S2b) | transform | `features/kernels/cross_tf.CtfSeries.asof`, `kernels/macro.daily_asof_indices` | exact (as-of lookup) |
| `src/intelligence/research/smoothing.py` (+) | utility (member transform) | transform | `families/overnight_intraday._prior_window` (own-window sums), `signals.py` memory rule | role-match |
| `src/intelligence/research/kernel_source.py` (+) | service (S2 source) | transform | `registry.compute_kernels` + `backfill_feature_factory.column_warmup_bars` | exact |
| `src/intelligence/research/feature_inputs.py` (+) | utility (S0 pure parts) | transform / validation | `research/data_quality.snapshot_manifest`, `statistics/feature_coverage`, `measure/ic.map_slots` | role-match |
| `src/intelligence/research/families/features.py` (+) | component (family members) | transform | `families/common.py`, `families/overnight_intraday.py` | exact |
| `src/intelligence/research/null_battery_persistent.py` (+) | test harness (H0 battery) | batch | `research/null_battery_overnight_intraday.py`, `research/null_battery.py` | exact |
| `src/intelligence/features/research_kernels/__init__.py` + kernel module(s) (+) | model (Kernel tuples) | transform | `features/kernels/control.py`, `kernels/price.py` `_scaled_series_kernel` | exact (minus discovery) |
| `src/intelligence/statistics/term_structure_lag.py` (+) | utility (pure statistic) | transform | `statistics/ic_math.compute_ic_vectorized`, `statistics/hac.py`, `evaluate.session_shifts` | role-match |
| `src/intelligence/research/panel.py` (mod) | model | file-I/O | itself (`save(extra=...)`, 187-15's optional arrays) | exact |
| `src/intelligence/research/snapshot.py` (mod) | service (S0) | request-response (read-only DB) | itself (dividends block, data-quality pin) | exact |
| `src/intelligence/research/spec.py` (mod) | config (pydantic) | validation | itself (`_OPTIONAL_*_FIELDS`, `_drop_unset`) | exact |
| `src/intelligence/research/runner.py` or `runner/{loading,execution}.py` after 187-18 (mod) | controller | request-response | itself (`_check_spec`, `real_guards`, `_load_panel`) | exact |
| `src/intelligence/research/guards.py` (mod, only if needed) | middleware (S3) | validation | itself (`causality_probe_array`, `memory_check_array`) | exact |
| `src/intelligence/research/families/common.py` (mod, optional) | utility | transform | `declared_memory_rows` | exact |
| `snapshot.py` economic block (B8, after todo 482) | service (S0) | request-response | `snapshot.py` dividends block; `scripts/research/midterm_cycle_looks.py` read | partial |
| `.planning/phases/184-*/184-XX-BATTERY.md` (+, B6) | doc | batch report | `.planning/phases/187-*/187-05-BATTERY.md` | exact |
| `tests/unit/research/conftest.py` or `mtf_fixtures.py` (+) | test fixture | - | `tests/unit/research/test_panel.py::_bars`, `tests/unit/intelligence/daily_grid_fixtures.py` | role-match |
| `tests/unit/research/test_clock.py` (+) | test | - | `tests/unit/research/test_panel.py` | role-match |
| `tests/unit/research/test_align.py` (+) | test | - | `tests/unit/research/test_guards_array.py` | role-match |
| `tests/unit/research/test_smoothing.py` (+) | test | - | `tests/unit/research/test_guards_array.py` | role-match |
| `tests/unit/research/test_kernel_source.py` (+) | test | - | `tests/unit/intelligence/test_causality_probe.py` | exact |
| `tests/unit/research/test_feature_inputs.py` (+) | test | - | `tests/unit/research/test_data_quality.py`, `test_panel.py` | role-match |
| `tests/unit/research/test_term_structure_lag.py` (+) | test | - | `tests/unit/research/test_timing.py` | role-match |
| `tests/unit/research/test_panel_mtf_fields.py` (extend 187-15's `test_panel_optional_fields.py`) | test | - | 187-15 Task 2 test | exact |
| `tests/unit/research/test_runner_feature_members.py` (+) | test | - | `tests/unit/research/test_runner_evidence.py`, `test_guards_array.py` | role-match |
| `tests/unit/intelligence/test_research_kernels.py` (+) | test | - | `tests/unit/intelligence/test_causality_probe.py`, `kernel_parity_reference.py` | exact |
| `tests/unit/test_feature_vectors_read_boundary.py` (+, B1k) | test (CI grep) | - | `tests/unit/test_market_data_ohlcv_boundary.py` | exact |
| `tests/unit/research/test_spec_hashes_pinned.py` (gate, unchanged) | test | - | itself | exact |
| `tests/unit/research/test_economic_block.py` (+, B8) | test | - | `tests/unit/research/test_dividends.py` | role-match |
| `tests/unit/research/test_null_battery_persistent.py` (+) | test | - | `tests/unit/research/test_null_battery_overnight_intraday.py` | exact |

## Sequencing against phase 187 (shared files)

From each 187 plan's `files_modified` (verified 2026-10-27). 187 runs 08 (wave 6) -> 09 (7)
-> 10 (8) -> ... -> 15 (10) -> 18 (13, depends on 14 and 15).

| 184 file | 187-08 | 187-09 | 187-10 | 187-15 | 187-18 | Consequence for 184 |
|---|---|---|---|---|---|---|
| `spec.py` | yes (`horizon_rule`, `_OPTIONAL_BOOK_FIELDS`) | yes (`min_members`, `refit_anchor`, `sign_*` in `_OPTIONAL_COMBINER_FIELDS`) | yes (pod) | yes (`PanelSpec.fields`, `_OPTIONAL_FAMILY_FIELDS` for `generated`) | no | 184's `_OPTIONAL_MEMBER_FIELDS` lands after 187-15 at the earliest; four 187 plans add sibling `_OPTIONAL_*` tuples first |
| `panel.py` | no | no | no | yes (optional high/low/sector_pit arrays) | no | B1a/B1b extend 187-15's optional-array mechanism; after 187-15 Task 2 |
| `snapshot.py` | no | no | no | yes (SELECT high/low on request, as-of SCH read) | no | B1c-B1j wiring after 187-15 Task 2; sector inputs share 187-15's reader |
| `runner.py` | yes (`book_memory`) | yes (`_combiner`) | yes (`run_pod`) | no | yes (split into `runner/` package) | Land 184 wiring before 187-18 so the move carries it, or after 187-18 against `runner/loading.py` and `runner/execution.py` |
| `guards.py` | no | no | no | no | yes (`SignalSource` -> `Predictor` import) | Any guards.py edit before 187-18 rebases across the rename; prefer no edit (array guards already suffice) |
| `signals.py` | no | no | no | no | yes (`git mv` to `predictors.py`) | New 184 code must not import `SignalSource`; B5 belongs on `MemberSpec` |
| `null_battery.py` | yes (`NullScenario.combiner`, `kappa`) | no | no | no | no | `null_battery_persistent.py` is a new module; reuse `listing_mask` and `ALPHAS` by import, after 187-08 if it needs `book_memory` |
| `book.py` | yes (`book_memory`) | yes | no | no | no | 184 feeds member sessions into 187-08's `book_memory`, never computes L by hand |
| `evidence.py` | yes | yes | no | no | no | B4's term-structure record goes in after 187-09 |

187-18's runner split (Task 1 action): `loading` = `_gate, _check_spec, _check_spec_tree,
_prepare_panel, _analysis_panel, _load_panel, _default_build, static_gate`; `execution` =
`compute_residuals, compute_members, real_guards, _vol, _shift_diagnostic, static_precondition,
_power_problem, family_plant, check_family_plant, _combiner`; `recording` =
`family_identities, book_identities`, RunRequest assembly. Any 184 task that names a runner
function names the home it has at execution time.

Wave 1 (new files only, no shared-file edit): clock, align, smoothing, research_kernels,
kernel_source, feature_inputs pure helpers, term_structure_lag, null_battery_persistent,
families/features, the boundary test. Wave 2 (on 5b's go, after 187-09 and 187-15 Task 2):
spec, panel, snapshot, runner wiring. B8: own plan, blocked on todo 482.

## Pattern assignments

### `src/intelligence/research/clock.py` (utility, transform)

**Analogs:** `src/intelligence/bars/sessions.py` lines 22-44; `src/intelligence/research/snapshot.py` lines 102-177.

Calendar source (sessions.py 22-44). Use this, never a fixed 16:00 or `macro._daily_close_ns`:
```python
@lru_cache(maxsize=32)
def nyse_sessions(start: date, end: date) -> dict[date, tuple[datetime, datetime]]:
    """Per-trading-date NYSE session bounds as UTC-aware datetimes.
    ... values are (market_open, market_close) with early closes (13:00 ET)
    on half days and DST-correct 09:30 ET opens. Non-trading days are absent."""
```
The returned dict is shared through the lru cache; treat it as immutable (sessions.py 9-10).

Grid keys `closes_at` must match (snapshot.py 145-148 intraday, 106-114 daily):
```python
local_rows = pd.DatetimeIndex((sessions[:, None] + slots[None, :]).ravel()).tz_localize(
    _EXCHANGE_TZ
)
timestamps = local_rows.tz_convert(UTC).tz_localize(None).values.astype("datetime64[m]")
```
1d `timestamps` are `datetime64[D]` session dates (panel.py line 28). Session date of each
grid row comes from `snapshot.session_dates(panel)` (snapshot.py 171-177), which is the
function to reuse for row -> session date:
```python
def session_dates(panel: Panel) -> np.ndarray:
    first = panel.timestamps[:: panel.bars_per_session]
    if panel.bars_per_session == 1:
        return np.asarray(first).astype("datetime64[D]")
    local = pd.DatetimeIndex(first).tz_localize(UTC).tz_convert(_EXCHANGE_TZ)
    return local.normalize().tz_localize(None).values.astype("datetime64[D]")
```
Rule to implement: `closes_at[row] = min(slot_start + tf_length, session_close)`, NaT where
`panel.valid[row]` is False. The `min` handles the short 15:30-16:00 1h bucket and the 12:30 1h
bucket on half days (RESEARCH Pitfall 3). Do not reuse
`feature_vector_persistence._compute_bar_close_ts` (bar_ts + tf length; wrong on both).

Module header convention (panel.py 1-10): a docstring that states the rule and the no-fill
contract, `from __future__ import annotations`, numpy/pandas only, no I/O.

---

### `src/intelligence/research/align.py` (utility, transform; the only node with two clocks)

**Analogs:** `src/intelligence/features/kernels/cross_tf.py` lines 282-300; `src/intelligence/features/kernels/macro.py` lines 116-128.

As-of lookup with an explicit invalid mask (cross_tf.py 282-300):
```python
def asof(self, row_ns: np.ndarray) -> tuple[...]:
    """A row reads the latest value whose close key is at or before the row's time (a row is
    never given a bar that closes after it starts). Where `valid` is False (no close yet)
    every value is NaN."""
    row_ns = np.asarray(row_ns, dtype=np.int64)
    idx = np.searchsorted(self._close_ns, row_ns, side="right") - 1
    valid = idx >= 0
    ...
    safe = np.where(valid, idx, 0)
    return (np.where(valid, self._momentum[safe], np.nan), ...)
```
Vectorized form (macro.py 127-128):
```python
bar_end = np.asarray(row_ts_ns, dtype=np.int64) + _bar_end_offset_seconds(tf) * _NS_PER_S
return np.searchsorted(np.asarray(available_ns, dtype=np.int64), bar_end, side="right") - 1
```
Differences align must add (design D4, RESEARCH Pattern 3): availability arrays may hold NaT
(drop them before `searchsorted`, map NaT destination rows to NaN output); per-symbol
latest-finite index via a forward max of `np.where(finite, idx, -1)` (an index, never a value
copy); NaN where `cand - last_finite > max_age_rows`; a `[ns, 1]` source broadcasts to every
symbol. Note the contrast: macro.py's fixed 16:00 ET rule is "conservative on half days"; align
uses `clock.closes_at`, which is exact.

Do not import `src.intelligence.features.kernels.*` here (it would pull the rebuild's import
closure into research for no benefit); copy the 3-line `searchsorted` idiom.

---

### `src/intelligence/research/smoothing.py` (utility, member transform)

**Analogs:** `src/intelligence/research/families/overnight_intraday.py` lines 44-56; `src/intelligence/research/signals.py` lines 8-10; `src/intelligence/research/guards.py` lines 42-45.

Trailing-window sums from each window's own rows (overnight_intraday.py 44-56). The FIR
smoother must follow this, not a recursion or a prefix difference, or `memory_check_array`
fails on near-ties:
```python
def _prior_window(x: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """... Each window is summed from its own sessions only, never as a difference of prefix
    sums: a prefix difference carries rounding from every earlier session, which moves the
    centred rank of near-tied names far outside the window and breaks the S3 memory guard."""
    finite = np.isfinite(x)
    xs = np.where(finite, x, 0.0)
    pad = np.zeros((window, x.shape[1]))
    out = []
    for a in (finite.astype(float), xs, xs * xs):
        windows = np.lib.stride_tricks.sliding_window_view(np.concatenate([pad, a]), window, axis=0)
        out.append(windows[: len(x)].sum(axis=-1))
    return tuple(out)
```
Note this window is d-w..d-1; the smoother's window includes row t (`k = 0..k_max`), so the pad
and slice shift by one.

Memory declaration convention (signals.py 8-10): "for a recursive filter, the lag at which its
impulse response falls below 1e-4 of its peak". The 1e-4 constant already exists as
`guards.MEMORY_TOLERANCE` (guards.py 42-45) with its APR-exempt comment; cite it rather than
inventing a second literal. Menu values `Literal[5, 21, 63]` carry an APR-exempt comment in
the style of `families/daily_residual.py` line 27 / `null_battery.py` line 31
(`MEMBER_WINDOWS = (1, 5, 20, 40)  # family 1's slot histories`).

---

### `src/intelligence/features/research_kernels/` (model: Kernel tuples, not auto-discovered)

**Analogs:** `src/intelligence/features/kernels/control.py` lines 1-20; `src/intelligence/features/kernels/price.py` lines 1423-1437, 593-604, 742-755; `src/intelligence/features/kernels/_primitives.py` lines 465-474.

Placement: a sibling package of `kernels/`, so `discover_kernels()` (registry.py 303-328, default
package `src.intelligence.features.kernels`, line 33) never scans it. Expose a `KERNELS` tuple so
`discover_kernels(package="src.intelligence.features.research_kernels")` builds a registry.

Module header and imports (control.py 1-12):
```python
"""Canary control kernels (D-25)."""
from __future__ import annotations
import numpy as np
from src.intelligence.features.contract.registry import Alignment, ExternalInput, Kernel
from src.intelligence.features.kernels._primitives import EPS, unique_datetimes
```
Kernel constructor (_primitives.py 465-474) and the fast/slow scaled pattern (price.py 1423-1437):
```python
def _k(name, outputs, inputs, memory, compute, **kw) -> Kernel:
    return Kernel(name=name, outputs=tuple(outputs), inputs=tuple(inputs),
                  memory=memory, compute=compute, **kw)
```
Research kernels take spec-pinned windows, not `FeatureFactoryConfig` attributes; `memory` is
`lambda c: window - 1` style and must be exact (`memory_atol = 0.0`, registry.py 63-66) or carry
the required comment.

Parity references (bit-equal after warmup, float32):
- `_high_52w_dist_series_full` (price.py 593-604): O(n x window) loop, `result = np.zeros(n)`,
  so pre-warmup rows are 0.0, not NaN. Parity compares rows >= warmup only.
- `_price_percentile_series_full` (price.py 742-755): `np.full(n, 0.5)`; uses
  `_primitives._percentile_rank` (scipy `percentileofscore`, kind "weak", clipped [0, 1]).
- VWAP: the stored `vwap_dev_sigma` is path dependent (volume.py 807-813, `path_dependent=True`,
  cumulative). The research kernel is a bounded rolling-window VWAP with a finite memory; it
  has no parity target, only the truncation probe and memory check.

Import-freeze rule (RESEARCH Pitfall 7): this is a new package; do not edit `kernels/*`,
`registry.py` or `_primitives.py` while 186-26 is live or resumable. Importing `_primitives` is
fine; editing it is not.

---

### `src/intelligence/research/kernel_source.py` (service, transform)

**Analogs:** `src/intelligence/features/contract/registry.py` lines 280-293, 363-420; `services/backfill_feature_factory.py` lines 916-932, 955-965.

Combined registry and memory (registry.py 141, 280-293, 363-368):
```python
KernelRegistry.from_kernels(default.kernels + research.kernels, default.external_inputs)
reg.is_path_dependent(output)                       # refuse (design D7 guard 5)
reg.effective_memory_bars(name, config)             # raises KernelRegistryError if path dependent
feature_memory_bars(output, config, registry=reg)   # D-26: the one source of memory
```
Run (registry.py 371-420): `compute_kernels(registry, inputs, config, outputs=[...])`, inputs keyed
by `BAR_FIELDS = ("ts", "open", "high", "low", "close", "volume")` (registry.py 29), `ts` as int64
UTC ns. Arrays come back in the compute dtype; cast to the kernel's declared dtype (float32).

Warmup mask, copied as the rule the rebuild applies (backfill_feature_factory.py 916-932, 963-965):
```python
def column_warmup_bars(registry, columns, config) -> dict[str, int]:
    warmups: dict[str, int] = {}
    for column in columns:
        kernel = registry.by_output(column)
        if registry.is_path_dependent(column):
            continue
        warmups[column] = registry.effective_memory_bars(kernel.name, config)
    return warmups
...
warmup = warmups.get(name, 0)
if warmup:
    column[: min(warmup, n)] = np.nan
```
Do not import `services.backfill_feature_factory` from research (Ring 2 into Ring 1); reimplement
the 6 lines over the registry API. Per-symbol loop over present rows only (compress each column
to its finite-close rows, compute, scatter back), so a gap never enters a window as a value.

---

### `src/intelligence/research/feature_inputs.py` (utility, S0 pure parts)

**Analogs:** `src/intelligence/research/data_quality.py` lines 57-83; `src/intelligence/statistics/feature_coverage.py` lines 20-63; `src/intelligence/measure/ic.py` lines 383-431; `services/_batch_utils.py` lines 268-295.

Pure manifest builder from fetched rows (data_quality.py 57-83). The provenance pin check
follows this shape: S0 fetches rows, a pure function decides and returns a JSON-able,
deterministically ordered manifest block:
```python
def snapshot_manifest(inputs, *, symbols, tf, digest_rows, verdict_rows) -> dict:
    """The manifest keys S0 pins for one panel (JSON-able, deterministic order)."""
    verdicts: dict[str, dict[str, bool]] = {}
    for subject, metric, passed in sorted(verdict_rows):
        verdicts.setdefault(subject, {})[metric] = bool(passed)
    return {"symbols": sorted(symbols), ..., "bar_content_digests": {tf: symbol_digests(digest_rows)}}
```
Coverage (feature_coverage.py 20-63): build `SymbolCounts(symbol, n_rows, n_non_null,
n_non_finite)` per symbol from the `[t, i]` array, call `feature_tf_quality(feature, tf, counts)`,
refuse when `symbol_coverage is None or symbol_coverage < floor`. Never a second ratio.

Long-form to grid (measure/ic.py 383-431, `map_slots` + `scatter_features`): exact
(timestamp, symbol) match, duplicate raises, count of unmatched rows returned. Research must not
import `measure` (measure imports research); copy the function body into `feature_inputs.py`
(about 30 lines) or move it to a shared Ring 1 module in its own commit. Use float32 output, not
the analog's float64 (RESEARCH Pitfall 6).

Provenance columns available (`_batch_utils.py` 268-286): `batch_key, writer, target_table,
time_column, tf, range_start, range_end, symbols, symbols_hash, code_key, apr_hash,
apr_snapshot, input_digest, unit_key, generation, row_count, status, ...`. Status values include
`superseded` (`_batch_utils.py` 258-262): the pin check selects `status = 'completed'` only.

---

### `src/intelligence/research/families/features.py` (component: family members)

**Analogs:** `src/intelligence/research/families/common.py` lines 1-36; `src/intelligence/research/families/overnight_intraday.py` lines 1-35, 140.

Member contract (common.py 4-7), which the runner calls unchanged:
```python
"""Member contract (the runner calls every member this way, spec params as keywords):
`member(resid_bar_returns, *, bars_per_session, coverage_floor, **params) -> alpha [n, m]`,
NaN where there is no position."""
```
For feature members the first argument becomes the member's declared input (aligned feature
array); keep the keyword signature so `runner._member_fn` (runner.py 153-159) works without change.

Rank helper to reuse (common.py 18-26): `centred_rank(alpha, coverage_floor=...)`.

Module shape (overnight_intraday.py 1-35, 140): docstring with a member table (statistic, window,
sign), imports from `families.common`, and the battery pointer that `runner.static_gate`
requires:
```python
NULL_BATTERY = "src.intelligence.research.null_battery_overnight_intraday"
```
features.py sets `NULL_BATTERY = "src.intelligence.research.null_battery_persistent"`.
`spec.MEMBER_PREFIX` (spec.py 56) already admits any function under `families.`.

---

### `src/intelligence/research/null_battery_persistent.py` (test harness, batch)

**Analogs:** `src/intelligence/research/null_battery_overnight_intraday.py` lines 1-120, 184-236; `src/intelligence/research/null_battery.py` lines 30-50, 168-269.

Interface the driver requires (`scripts/research/e17_null_battery.py` lines 5-10, 38, 53-54):
`scenarios()`, `simulate(scenario, seed) -> {arm: (t, p)}`, `DIAGNOSTIC_CELLS`; plus
`static_gate()` for `runner.static_gate` -> `static_sizes.gate_for(module)`.

Imports and constants (null_battery_overnight_intraday.py 28-65):
```python
from src.intelligence.research import static_sizes
from src.intelligence.research.null_battery import listing_mask
from src.intelligence.research.panel import Panel
from src.intelligence.research.portfolio import rank_vol_neutral_weights, trailing_vol
from src.intelligence.research.timing import timing_test
_WARMUP_SESSIONS = 252
_COVERAGE_FLOOR = 20
_VOL_WINDOW_SESSIONS = 20
```
Scenario dataclass (null_battery.py 37-50): frozen, `name` first, every stress a defaulted field.
Scoring loop (null_battery.py 168-208): `trailing_vol` -> `rank_vol_neutral_weights` ->
`timing_test(weights, target, has, trade, memory_sessions=..., bars_per_session=bps,
warmup_sessions=_WARMUP_SESSIONS)`. For B6, `memory_sessions` must be the same L 187-08's
`book_memory` returns for an aligned or smoothed member (838 + 252 sessions at the long end,
RESEARCH Pitfall 8); report tested-session counts per cell.
`static_gate()` via `static_sizes.gate_from_cells(__name__, ..., scenarios(), DIAGNOSTIC_CELLS,
static=..., time_of_day=...)` (null_battery.py 259-269).
Size levels: `null_battery.ALPHAS = (0.05, 0.01, 0.00167)` (line 30). The statistic is E17
(RESEARCH Pitfall 9), not E16.

---

### `src/intelligence/statistics/term_structure_lag.py` (utility, pure statistic)

**Analogs:** `src/intelligence/statistics/ic_math.py` lines 441-458; `src/intelligence/statistics/hac.py` lines 1-40; `src/intelligence/research/evaluate.py` lines 201-207.

Module style (hac.py 1-30): docstring that pins the exact definition and says why a variant
would be a different, unvalidated statistic; a frozen result dataclass; numpy and scipy only.

Rank IC (ic_math.py 441-458): `compute_ic_vectorized(X, y)` ranks with `rankdata` then
Pearson-on-ranks. For per-row cross-sectional IC at lag k on `[n, m]` arrays, use
`research.portfolio.average_ranks` per row (the same helper `centred_rank` uses,
common.py 15, 25) and average over rows; NaN cells excluded per row.

Shift set (evaluate.py 201-207), the only shift source:
```python
def session_shifts(n: int, bars_per_session: int, min_shift: int, memory: int) -> np.ndarray:
    memory_sessions = -(-memory // bars_per_session)
    return admissible_shifts(n // bars_per_session, min_shift, memory_sessions) * bars_per_session
```
Placement rule: `statistics/` must not import `research/` except for pure helpers it already
uses; if `session_shifts` is needed, the runner computes shifts and passes them in as an array,
so `term_structure_lag.py` stays importable without research. Band level (95%) and K = 60 are
definition constants with an APR-exempt comment.

---

### `src/intelligence/research/panel.py` (model, file-I/O) - wave 2

**Analog:** itself, lines 21, 24-53, 160-190; 187-15 Task 2's optional arrays.

Extra arrays without moving old bytes (panel.py 160-176):
```python
def save(panel: Panel, out_dir: Path, extra: dict[str, np.ndarray] | None = None) -> Path:
    """`extra` arrays (S0's dividend grid) are written into the same content-hashed directory;
    without them the bytes are exactly those of earlier snapshots. load() ignores them."""
    arrays = {"timestamps": panel.timestamps, "valid": panel.valid,
              **{name: getattr(panel, name) for name in _PRICE_FIELDS}, **(extra or {})}
```
`_PRICE_FIELDS = ("open", "close", "volume")` (line 21) drives `__post_init__` shape checks,
`save`, `load` and `runner._sub_panel` (runner.py 169-178) and `select_symbols` (panel.py 210-225).
Do not add `high`/`low`/`closes_at` to `_PRICE_FIELDS`: that changes every saved panel's bytes.
Use 187-15's optional arrays (default None, written only when present) and extend
`select_symbols` and `_sub_panel` to carry them. `closes_at` is `[n]` (per row), not `[n, m]`.
Existing arrays keep float64; new intraday arrays are float32.

---

### `src/intelligence/research/snapshot.py` (service S0, read-only DB) - wave 2

**Analog:** itself, lines 41-52, 92-99, 268-368.

Pinned SQL constants, never built from caller text (snapshot.py 48-52, 85-87):
```python
_BARS_SQL = (
    "SELECT timestamp, open, close, volume FROM market_data_ohlcv_tradeable "
    "WHERE symbol = $1 AND timeframe = $2 AND timestamp >= $3 AND timestamp < $4 "
    "ORDER BY timestamp"
)
UNIVERSE_DIMENSIONS = ("compute_eligible", "compute_eligible_1d", "live_tradeable")
```
Feature reads need dynamic column names: build from an allow-list
(`registry.feature_columns()`, registry.py 298-300) and quote with `asyncpg`-safe identifiers,
following `services/ic_measure.py` 318-324:
```python
def feature_block_sql(table: str, names: Sequence[str]) -> sql.Composed:
    """symbol, bar_ts and exactly the named columns (never a star select), in (bar_ts, symbol) order."""
    columns = [sql.Identifier("symbol"), sql.Identifier("bar_ts"), *map(sql.Identifier, names)]
```
(that analog is psycopg; S0 is asyncpg, so quote identifiers after the allow-list check, for
example `'"' + name + '"'` only for names in the allow-list).

OOS refusal before any fetch (snapshot.py 286-290); the warmup prefix extends `lo` backwards
only, never `hi`:
```python
oos = await pool.fetchval(_OOS_START_SQL)
if oos is None:
    raise ValueError("alpha.validation.oos_start is not set")
if hi > oos:
    raise ValueError(f"end_exclusive {end_exclusive} is past oos_start {oos.isoformat()}")
```
Optional captured block pattern (dividends, snapshot.py 319-338, 356-368): fetch inside the pool
`try`, build arrays with a pure function, record a manifest sub-dict, pass arrays as `extra` to
`panel_mod.save`. B1e feature arrays, B1f provenance, B1d vendor set and B8's economic block
all follow this pattern, each gated by a spec field so a spec without it writes old bytes.
Per-symbol concurrent fetch (snapshot.py 292-306): `asyncio.gather(*(fetch(s) for s in
requested))` on the read-only pool (`read_only_pool`, lines 92-99, `default_transaction_read_only`).
For 5m feature columns read per symbol chunk and keep only the book-clock array (Pitfall 6).

Runner-side check that the snapshot matches the spec (runner.py 396-406), to extend with the new
fields:
```python
expected = {
    "tf": (panel.tf, spec.panel.tf),
    ...
    "dividends": (grid is not None, spec.panel.total_return is not None),
}
wrong = {k: v for k, v in expected.items() if v[0] != v[1]}
if wrong:
    raise ValueError(f"snapshot does not match the spec: {wrong}")
```

---

### `src/intelligence/research/spec.py` (config, validation) - wave 2, after 187-09 and 187-15

**Analog:** itself, lines 58, 71-115, 359-392.

Optional-field registration (spec.py 359-385):
```python
_OPTIONAL_PANEL_FIELDS = ("transform", "members_universe", "total_return")
_OPTIONAL_SCORING_FIELDS = ("timing_statistic",)

def _drop_unset(data: dict, section: str, keys: tuple[str, ...]) -> None:
    for key in keys:
        if data[section][key] is None:
            del data[section][key]

def _family_dump(model: FamilySpec) -> dict:
    data = model.model_dump(mode="json")
    _drop_unset(data, "panel", _OPTIONAL_PANEL_FIELDS)
    _drop_unset(data, "scoring", _OPTIONAL_SCORING_FIELDS)
    return data
```
`_drop_unset` indexes a dict section; members are a list, so add
`_OPTIONAL_MEMBER_FIELDS = ("input", "smoothing_half_life")` and a loop
`for member in data["members"]: for key in ...: if member[key] is None: del member[key]`.
If 187-15 makes `members` optional (`generated` alternative), guard the loop for its absence.

Sub-model style (spec.py 58, 63-69): `model_config = _STRICT` (`extra="forbid", strict=True,
frozen=True`), `Field(...)` bounds, `Literal[...]` menus, `Identifier` pattern for column names.
A `MemberInputSpec` (kind, column, tf, max_age_rows, apr) follows `TotalReturnSpec`;
`smoothing_half_life: Literal[5, 21, 63] | None = None` follows `timing_statistic` (line 172).
`_check_book` (411-428) requires families to agree on `panel`, so the source tf lives on the
member, not the panel.

Gate after every edit: `tests/unit/research/test_spec_hashes_pinned.py` (seven pinned hashes,
lines 20-33; `daily_residual` WIP may add an eighth by then).

---

### `runner.py` (controller) - wave 2; `runner/loading.py` and `runner/execution.py` after 187-18

**Analog:** itself, lines 153-166, 187-240, 267-277, 466-475.

Memory rule to branch (runner.py 267-277): today every member must satisfy
`declared_memory_rows == declared_memory_rows(slot_history, bps, factor_spec)`
(common.py 29-36). Feature members get their own branch computing declared rows from one
function (RESEARCH Pattern 4), fed to 187-08's `book_memory`:
```python
def _check_spec(spec: FamilySpec) -> None:
    bps = spec.panel.analysis_bars_per_session
    factor_spec = FACTOR_SPECS[spec.factor_spec]
    for m in spec.members:
        want = declared_memory_rows(m.slot_history_sessions, bps, factor_spec)
        if m.declared_memory_rows != want:
            raise RunRefused(...)
        resolve_member(m.signal)
```
Member input dispatch (runner.py 162-166): `compute_members` passes `resid_bar` to every member;
generalize to pass each member's declared input (resid_bar, or the aligned feature/kernel array).

S3 over member inputs (runner.py 204-211), which already works on any array:
```python
for m in spec.members:
    fn = _member_fn(spec, m, bps)
    declared = m.slot_history_sessions * bps
    guards.causality_probe_array(fn, residuals.bar, rows, seed=g.seed)
    reach[m.name] = guards.memory_check_array(
        fn, residuals.bar, rows[rows < n - declared - 1], declared=declared
    )
```
For a feature member, probe `fn` composed with `align` (and the smoother) on the source-tf array,
and cite the registry truncation probe (`features.contract.causality_probe.causality_probe`,
causality_probe.py 115-136) by code key for the stored column. Bounded sub-panel for 5m sources,
as `_sub_panel(panel, g.s1_probe_sessions)` does (runner.py 169-178, 213).

Battery gate (runner.py 466-475): `static_gate` refuses a family module without `NULL_BATTERY`;
`families/features.py` must declare it before any real run.

HMM refusal (B1j): registry origin is stamped by `discover_kernels` (`origin=info.name`,
registry.py 326); `hmm_*` columns come from `kernels/regime.py` (origin `regime`). Refuse unless
every covering batch is from the 186-26 rebuild.

---

### `src/intelligence/research/guards.py` (middleware S3) - avoid editing

**Analog:** itself, lines 193-255. `causality_probe_array(fn, x, rows, *, seed, reach=0)` and
`memory_check_array(fn, x, rows, *, declared)` already accept any array function; 184 composes
functions and passes them in, no guards.py edit needed. Kernel members use
`features.contract.causality_probe` (truncation) instead, per its docstring (lines 9-14):
"The research S3 guard adopts this probe in the research lane (D-27), not here."

---

### `snapshot.py` economic block (B8, blocked on todo 482)

**Analogs:** `snapshot.py` dividends block (lines 54-71, 319-338); `scripts/research/midterm_cycle_looks.py` lines 44-54.

Existing economic read (midterm_cycle_looks.py 44-54) reads `economic_series_observation_current`
by `observation_date` with no availability filter; that is the anti-pattern for research. B8 reads
`economic_series_observation` filtered on `available_at <= K`, records K in the manifest, and
refuses an `availability_basis` outside the post-482 set. Reuse the dividends block's structure
(pinned SQL constants with `$n` parameters, a pure grid builder, a manifest sub-dict, `extra`
arrays). Alignment goes through `align.py` with a `[ns, 1]` source and `available_at` as
`src_avail`.

---

### `tests/unit/test_feature_vectors_read_boundary.py` (CI grep, B1k)

**Analog:** `tests/unit/test_market_data_ohlcv_boundary.py` lines 1-30, 117-145.

```python
from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)
_REPO_ROOT = Path(__file__).parent.parent.parent
_RAW_TABLE_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+market_data_ohlcv\b(?!_tradeable)")
_SEARCH_DIRS = ("services", "src", "scripts")
_ALLOW_LIST: dict[str, str] = {"services/bar_selection.py": ("PERMANENT ...: reason"), ...}

@functools.lru_cache(maxsize=1)
def _find_raw_table_references() -> dict[str, int]:
    return find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, _RAW_TABLE_PATTERN, file_globs=("*.py", "*.sh"))

def test_every_raw_market_data_ohlcv_reference_is_on_the_allow_list(): ...
def test_allow_list_has_no_stale_entries(): ...
```
Pattern for 184: `\b(?:FROM|JOIN)\s+feature_vectors(?:_v2)?\b`; note `ic_measure.feature_block_sql`
builds the table name through `sql.Identifier(table)`, which a FROM-literal grep misses. Add a
second pattern for `feature_vectors` string literals in `.py` files, or list ic_measure
explicitly. Seed the allow-list by running the grep first (writer, ic_measure, feature_lifecycle,
snapshot.py).

---

### Tests (shared conventions)

- Array-guard tests (`tests/unit/research/test_guards_array.py` 1-50): module-level helper
  functions (`_rolling_mean`, `_ahead` as the acausal control), a seeded `_x()` generator,
  a fixed `ROWS = np.array([...])`, `pytest.raises(GuardFailure, match="lookahead")`. Use this
  shape for `test_align.py` (planted leak, B3b), `test_smoothing.py` and
  `test_runner_feature_members.py`.
- Kernel tests (`tests/unit/intelligence/test_causality_probe.py` 1-40): `N = 400`,
  `ROWS = np.array([50, 120, 250, 399])`, `CFG = object()`, a seeded close series,
  `pytest.raises(CausalityViolation)` / `MemoryViolation`. Use for
  `test_research_kernels.py` and `test_kernel_source.py`; parity against
  `kernels/price.py` functions imported directly (read-only import is fine).
- Grid tests (`tests/unit/research/test_panel.py` 1-12): `_bars(times_utc, closes)` returns
  `(ts, open, close, volume)` tuples for `build_grid`. The shared MTF fixture extends this with a
  2024-11-29 half day and the 2024-03-11 and 2024-11-04 DST sessions (RESEARCH Wave 0 gaps);
  `tests/unit/intelligence/daily_grid_fixtures.py` is the precedent for a fixture module imported
  by several test files (no `conftest.py` exists in `tests/unit/research/` today).
- Hash gate (`tests/unit/research/test_spec_hashes_pinned.py` 20-43): no new spec file under
  `research/specs/` without adding its pinned hash (`test_every_spec_file_is_pinned`).

## Shared patterns

### No fill, NaN for missing
**Source:** `src/intelligence/research/panel.py` lines 9, 121-130
**Apply to:** clock, align, smoothing, kernel_source, feature_inputs, families/features
```python
fwd = np.full(opens.shape, np.nan)
with np.errstate(invalid="ignore", divide="ignore"):
    fwd[: n - 1 - horizon] = np.log(opens[1 + horizon :] / opens[1 : n - horizon])
```
Allocate NaN, write only computed cells, suppress numpy warnings locally with `np.errstate`.

### Content-hashed snapshot
**Source:** `src/intelligence/research/store.py` lines 31-53
**Apply to:** every new S0 array (feature columns, closes_at, economic block, child dirs)
```python
def write(out_dir: Path, prefix: str, arrays: dict[str, np.ndarray], meta: dict) -> Path:
    """Write to a temporary directory, then rename it to its content hash."""
def verify(path: Path) -> str:
    """Recompute the content hash, compare it with the directory name, and return the full sha256"""
```
Child dirs per source tf: each written with `store.write`, the book-clock manifest lists their
full `verify()` digests so one root hash covers all (RESEARCH Alternatives).

### Optional field leaves every hash unchanged
**Source:** `spec.py` 359-385 (spec), `panel.py` 160-176 (snapshot bytes)
**Apply to:** every spec.py, panel.py, snapshot.py change. Field defaults to None, dropped from
the canonical form while unset; arrays written only when present. Verify with
`test_spec_hashes_pinned.py`, `repro_frozen`, `backfill_attempt_series.py --compare-all`.

### Refusal, not failure
**Source:** `runner.py` 93 (`class RunRefused(Exception)`), 297-305 (`_require_r1`); `guards.py`
52-53 (`GuardFailure`); `snapshot.py` 250-254 (ValueError with the reason and the rule id)
**Apply to:** provenance pin mismatch, coverage floor, path-dependent kernel, HMM column,
non-derived 15m/1h vendor, B8 basis refusal. Spec-time checks raise `RunRefused` before any data
is read; S0 data checks raise `ValueError` naming the rule (e.g. `(B1f)`); S3 raises
`GuardFailure`. Exception variable is `error`.

### Declared memory, one source
**Source:** `registry.feature_memory_bars` (registry.py 363-368), `common.declared_memory_rows`
(common.py 29-36), 187-08 `book.book_memory`
**Apply to:** feature members, kernel_source, smoothing, align `max_age_rows`, S0 warmup prefix,
B6 battery L. Nothing computes L by hand.

### APR-exempt definition constants
**Source:** `guards.py` 39-47, `null_battery.py` 30-34, `kernels/control.py` 14-20
**Apply to:** smoothing menu, 1e-4 memory cut (reuse `MEMORY_TOLERANCE`), B4 band level and K.
Each carries a comment saying it is a definition, not a tunable, and what changing it invalidates.
Spec-pinned values (windows, max_age_rows, coverage floor, APR pins) live in the spec, which is
the one reviewed place (spec.py docstring lines 5-7).

### Ring and import direction
**Apply to:** all new files. Research imports features, statistics, bars; features never import
research (causality_probe.py 9-14); research never imports `measure` or `services`.

## No analog found

| File | Role | Data flow | Reason |
|---|---|---|---|
| `snapshot.py` economic block (B8) | service S0 | request-response | No research read of `economic_series_observation` filters on availability; the only reader (`midterm_cycle_looks.py`) keys on observation date. Use the dividends block for structure and RESEARCH Finding F9 plus `docs/ideas/signal-macro-context-layer.md` for semantics. Blocked on todo 482 regardless. |

## Metadata

**Analog search scope:** `src/intelligence/research/`, `src/intelligence/research/families/`,
`src/intelligence/features/contract/`, `src/intelligence/features/kernels/`,
`src/intelligence/statistics/`, `src/intelligence/bars/`, `src/intelligence/measure/`,
`services/ic_measure.py`, `services/backfill_feature_factory.py`, `services/_batch_utils.py`,
`scripts/research/`, `tests/unit/research/`, `tests/unit/intelligence/`, `tests/unit/`,
`.planning/phases/187-*/187-{08,09,10,15,18}-PLAN.md`
**Files scanned:** about 45
**Pattern extraction date:** 2026-10-27
