# Phase 166: Frame/Execution Recalibration - Pattern Map

**Mapped:** 2026-07-23
**Files analyzed:** 8 (2 extended services, 1 new module, 1 new script, 1 new migration, 3 new test files)
**Analogs found:** 8 / 8

RESEARCH.md's "Recommended Project Structure" and "Code Examples" sections already name the
exact analog for nearly every file in this phase — this map adds concrete line numbers, full
excerpts, and a couple of analogs RESEARCH.md didn't cite in full (test files, migration 243).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/ensemble_ic_engine.py` (extend: `_calibrate_stop_target()`) | service (batch calibration) | CRUD (APR read → compute → APR write) | `services/ensemble_ic_engine.py::_calibrate_hold_max_bars` (same file, sibling function) | exact |
| `services/alpha_frame_writer.py` (extend: per-(regime,tf) stop/target key lookup + structural geometry call) | service (batch writer) | CRUD (read `alpha_events`, write `alpha_frames`) | `services/alpha_frame_writer.py::_process_partition` (same file, existing `hold_key` lookup) | exact |
| `src/intelligence/trading/structural_confluence.py` (new) | utility (pure functions, confluence scoring) | transform | `src/intelligence/trading/zone_engine.py` | exact (port, new spec table) |
| `scripts/analysis/gate166_frame_recalibration_eval.py` (new) | service (oneshot gate script) | batch (read OOS rows → compute → write `gate_evaluations`) | `scripts/analysis/score03_gate2_execution_eval.py` | exact |
| `production/migrations/253_alpha_frame_stop_target_calibration.sql` (new) | migration | batch (schema/APR seed) | `production/migrations/243_frame_min_stop_price_fraction.sql` + `205_alpha_frames_schema.sql` (APR seed block) | exact |
| `tests/unit/test_ensemble_ic_stop_target_calibration.py` (new) | test | — | `tests/unit/test_ensemble_ic_decay.py` | exact |
| `tests/unit/test_structural_confluence.py` (new) | test | — | `tests/unit/trading/test_zone_engine.py` | exact |
| `tests/unit/test_gate166_frame_recalibration_eval.py` (new) | test | — | `tests/unit/test_score03_gate2_execution_eval.py` | exact |

`services/counterfactual_tracker.py` is explicitly **unchanged** (already generic over each
frame's snapshotted `stop_price`/`target_price`/`max_hold_bars` columns) — no pattern entry
needed, but `frame_gate_passes`/`evaluate_frame_gate` are reused unmodified by the new gate
script (see Shared Patterns).

## Pattern Assignments

### `services/ensemble_ic_engine.py` — new `_calibrate_stop_target()` (service, CRUD)

**Analog:** `services/ensemble_ic_engine.py::_calibrate_hold_max_bars` / `_select_hold_bars_from_decay` (same file — this is a sibling-function port, not a cross-file port)

**Imports already in scope** (file header, lines 1-60) — no new imports needed for the calibration
function itself; it runs inside the same module as `_calibrate_hold_max_bars`, reusing
`ConfigService`, `np`, `asyncpg`, `_cfg`, `_load_apr_dict` already imported there.

**Qualifying-cells gate to reuse verbatim** (lines 271-275):
```python
# Significance + sufficiency + stability gate (review finding #6, MANDATORY; extended
# 2026-07-09 to add walk_forward_stable — see ensemble_trainer.py's CORRECTNESS
# INVARIANTS docstring for why cross-sectional significance alone is not a sufficient
# bar). Mirrors EIC-04's own phase-gate query (ops_ensemble_ic_gate.py, `_GATE_SQL`).
_QUALIFYING_FLAGS = ("passes_fdr", "reliable", "walk_forward_stable")
```

**Core CR-02 champion-gate dispatch pattern to mirror** (lines 1037-1052 — call the new function
alongside the existing one, same gate):
```python
if weight_version == champion_weight_version:
    n_keys_written = await self._calibrate_hold_max_bars(pool, corpus_all_results, config)
else:
    self.logger.info(
        "ensemble_ic.hold_max_bars_calibration_skipped",
        reason="scoped_weight_version_run",
        weight_version=weight_version,
        champion_weight_version=champion_weight_version,
    )
    n_keys_written = 0
```

**Grouping/median/write structure to mirror exactly** (lines 1063-1126, `_calibrate_hold_max_bars`
full body):
```python
async def _calibrate_hold_max_bars(
    self,
    pool: asyncpg.Pool,
    results: list[dict[str, Any]],
    config: EnsembleICConfig,
) -> int:
    """... median hold_bars across symbols that returned a non-None result ...
    A (regime, tf) pair with zero qualifying symbols is SKIPPED entirely -- no
    config_service.set call, no fallback default -- the prior APR value remains
    authoritative until a future run qualifies.
    Excludes is_pooled=true rows: ... a per-symbol execution parameter ...
    """
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in results:
        if row.get("is_pooled"):
            continue
        key = (row["symbol"], row["tf"], row["regime"])
        groups.setdefault(key, []).append(row)

    per_regime_tf: dict[tuple[str, str], list[int]] = {}
    for (_symbol, tf, regime), cells in groups.items():
        hold_bars = _select_hold_bars_from_decay(
            cells, config.decay_threshold, config.lookaheads
        )
        if hold_bars is None:
            continue
        per_regime_tf.setdefault((regime, tf), []).append(hold_bars)

    if not per_regime_tf:
        return 0

    config_service = ConfigService(database_url=self._db_dsn, pool=pool)
    await config_service.initialize()

    n_written = 0
    for (regime, tf), qualifying_hold_bars in per_regime_tf.items():
        n_qualifying = len(qualifying_hold_bars)
        median_hold_bars = int(np.median(qualifying_hold_bars))
        key = f"alpha.frame.hold_max_bars.{regime}.{tf}"
        qualifying_flags_desc = " AND ".join(f"{flag}=true" for flag in _QUALIFYING_FLAGS)
        await config_service.set(
            key,
            str(median_hold_bars),
            changed_by="ensemble-ic-engine",
            reason=(
                "calibrated from IC decay curve (EIC-02); median across "
                f"{n_qualifying} qualifying ({qualifying_flags_desc}) "
                f"symbols; decay_threshold={config.decay_threshold}"
            ),
        )
        n_written += 1
    return n_written
```

**What NOT to copy (Pitfall 1, RESEARCH.md Finding 1):** `_select_hold_bars_from_decay`'s
decay-threshold-crossing walk over `[fast, mid, slow, extended]` scales has no stop/target
analog. Write a NEW selection function using `counterfactual_mfe`/`counterfactual_mae`
percentile-of-rescaled-ATR-units (open design question — see RESEARCH.md Open Question 2) —
reuse only the STRUCTURE above (grouping by `(symbol, tf, regime)` → per-symbol selection →
group by `(regime, tf)` → median across qualifying symbols → CR-02 gate → skip-if-empty →
`config_service.set` with a descriptive `reason`).

**Config dataclass extension pattern** (`EnsembleICConfig.from_apr`, lines 195-221) — if the new
selection function needs its own APR-driven parameters (e.g. a percentile threshold), add fields
the same way `decay_threshold`/`min_qualifying_fraction` were added to this frozen dataclass, one
`_cfg(cfg, "alpha.ensemble_ic.<key>", <default>)` call per field.

---

### `services/alpha_frame_writer.py` — extend `_process_partition` (service, CRUD)

**Analog:** same file, existing `hold_key` lookup at write time.

**Imports already in scope** (lines 32-55) — `_cfg`, `_load_apr_dict_async as _load_apr` from
`services._batch_utils`; no new imports needed for a per-(regime,tf) stop/target key lookup. If
the structural candidate's geometry call is wired in here too, import
`src.intelligence.trading.structural_confluence` the same way other `src.intelligence.trading.*`
modules are imported elsewhere in the codebase (bare `from src.intelligence.trading.X import Y`).

**Exact pattern to mirror for new stop/target keys** (lines 344-348, live):
```python
hold_key = f"alpha.frame.hold_max_bars.{regime}.{tf}"
if hold_key not in cfg:
    missing_hold_keys.add(hold_key)
max_hold_bars = int(_cfg(cfg, hold_key, _DEFAULT_HOLD_MAX_BARS))
```
Apply identically for `alpha.frame.stop_atr_mult.{regime}.{tf}` and
`alpha.frame.target_r_multiple.{regime}.{tf}`, each falling back to the existing global scalar
(`frame_config.stop_atr_mult`/`frame_config.target_r_multiple`, from `FrameConfig.from_apr`,
lines 156-174) when the per-cell key is absent — additive/backward-compatible, per RESEARCH.md's
Integration Points note.

**Aggregate-not-per-row logging pattern to reuse** (lines 328-329, 390-403 — the
`missing_hold_keys: set[str]` accumulator, warned once per partition, never per row):
```python
missing_hold_keys: set[str] = set()
...
if hold_key not in cfg:
    missing_hold_keys.add(hold_key)
...
if missing_hold_keys:
    self.logger.warning(
        "alpha_frame_writer.hold_max_bars_key_missing",
        symbol=symbol,
        tf=tf,
        hold_keys=sorted(missing_hold_keys),
    )
```
Mirror this exactly for the new `missing_stop_keys`/`missing_target_keys` sets — CLAUDE.md's
"never log per-row inside a full-corpus loop" rule applies directly to `--backfill` runs over
the full `alpha_events` backlog.

**Frame geometry pure function — reuse unmodified, do not duplicate** (lines 64-119,
`compute_frame_geometry`):
```python
def compute_frame_geometry(
    direction: str, entry_price: float, atr: float,
    stop_atr_mult: float, target_r_multiple: float, min_stop_price_fraction: float,
) -> tuple[float, float, float]:
    if atr <= 0:
        raise ValueError(...)
    if direction == "long":
        stop_price = entry_price - stop_atr_mult * atr
        stop_distance = entry_price - stop_price
        target_price = entry_price + target_r_multiple * stop_distance
    elif direction == "short":
        stop_price = entry_price + stop_atr_mult * atr
        stop_distance = stop_price - entry_price
        target_price = entry_price - target_r_multiple * stop_distance
    else:
        raise ValueError(...)
    if stop_distance < min_stop_price_fraction * entry_price:
        raise ValueError(...)  # todo 162 degenerate-ATR skip
    return stop_price, target_price, target_r_multiple
```
This function's `atr<=0` and `min_stop_price_fraction` ValueError-raise-and-skip contract
(todo 162's fix) must be preserved for both candidates — do not widen the floor to avoid the
exception; callers already catch it and skip the frame.

**`FrameConfig` frozen-dataclass-from-APR pattern** (lines 146-174) — the structural candidate's
new APR keys (proximity/cluster-radius/strength-weight thresholds, per CLAUDE.md's
Migrate-as-you-go rule) should be added as new fields here or in a sibling frozen dataclass, read
via `_cfg(cfg_dict, "alpha.frame.<key>", <default>)`, validated eagerly at config-load time (see
the `stop_atr_mult <= 0` raise at lines 159-163) rather than rediscovered per-frame.

---

### `src/intelligence/trading/structural_confluence.py` (new) — utility, transform

**Analog:** `src/intelligence/trading/zone_engine.py` (full file, 499 lines, archived-tier but
architecturally live-quality — see CLAUDE.md's note that this whole file is dead code with
intact, well-tested logic).

**Imports pattern in the analog** (lines 1-24) — do NOT copy `_fval`/metrics imports verbatim if
they pull from the archived plugin tier; check `src/intelligence/trading/plugin_utils.py` and
`src/observability/metrics.py` are still live/importable before reusing. `get_atr_with_floor`
(`src/intelligence/trading/atr_utils.py`) is CLAUDE.md-endorsed ("never recompute ATR in I7") —
reuse if a price-unit ATR accessor is needed, otherwise the new module will receive ATR the same
way `AlphaFrameWriter` already computes it (from `market_data_ohlcv`, per the module's own
docstring line 8-9).

**`ZoneCandidate` dataclass — portable nearly unmodified** (lines 85-91):
```python
@dataclass
class ZoneCandidate:
    price: float
    name: str
    strength: float  # 0.0–1.0 quality weight
    source_tier: str  # "i1", "i3", "i4", "smc" in v2.x → "vp"/"sr" in the v3 port
    source_family: str  # for dedup: "sr", "swing", "smc_ssl", "ma_ema", "ma_sma", "vp", "overnight"
```

**Clustering/scoring core — portable nearly unmodified, generic over `ZoneCandidate`** (lines
344-395):
```python
def _find_clusters(candidates: list[ZoneCandidate], atr: float) -> list[list[ZoneCandidate]]:
    if not candidates:
        return []
    clusters: list[list[ZoneCandidate]] = []
    current = [candidates[0]]
    radius = atr * _cluster_radius_atr()
    for c in candidates[1:]:
        if abs(c.price - current[-1].price) <= radius:
            current.append(c)
        else:
            clusters.append(current)
            current = [c]
    clusters.append(current)
    return [cl for cl in clusters if len(cl) >= 2]

def _source_diversity(cluster: list[ZoneCandidate]) -> int:
    return len({c.source_tier for c in cluster})

def _score_cluster(cluster: list[ZoneCandidate], atr: float) -> float:
    width = max(cluster[-1].price - cluster[0].price, atr * 0.01)
    width_atr = width / atr
    strength_sum = sum(c.strength for c in cluster)
    diversity = _source_diversity(cluster)
    return (strength_sum * diversity) / max(width_atr, 0.1)

def _pick_single_best(candidates, entry, atr) -> ZoneCandidate | None:
    if not candidates:
        return None
    best_score, best = -1.0, None
    sw, pw = _strength_weight(), _proximity_weight()
    for c in candidates:
        dist_atr = abs(c.price - entry) / atr if atr > EPSILON else 2.0
        proximity = max(0.0, 1.0 - dist_atr / 2.0)
        score = c.strength * sw + proximity * pw
        if score > best_score:
            best_score, best = score, c
    return best
```

**3-tier resolution shape to port** (`_resolve_zone`, lines 418-477 — confluence cluster →
single-best → ATR fallback with `tier="atr"`, empty zone; caller applies its own bounds):
```python
clusters = _find_clusters(candidates, atr)
diverse = [cl for cl in clusters if _source_diversity(cl) >= 2]
if diverse:
    best = max(diverse, key=lambda cl: _score_cluster(cl, atr))
    ...  # tier="confluence"
best_single = _pick_single_best(candidates, entry, atr)
if best_single is not None:
    ...  # tier="single"
return ZoneResult(zone_low=0.0, zone_high=0.0, tier="atr", ...)  # caller fallback
```

**Declarative spec-table pattern — v2.x shape, needs a v3-specific replacement table** (lines
111-127, `_SUPPORT_SPECS`):
```python
# (feature_key, display_name, default_strength, source_tier, source_family)
_SUPPORT_SPECS: tuple[tuple[str, str, float, str, str], ...] = (
    ("nearest_support", "support", 0.7, "i3", "sr"),
    ("sr_nearest_support", "sr_support", 0.7, "i3", "sr"),
    ...
)
```
**Do not copy this table's entries.** Per RESEARCH.md Finding 2/Q3 and Pitfall 3, every field
name in the v2.x table is 100% absent from v3's live `feature_vectors` schema except the four
Phase-163-owned columns. The new module's spec table must be populated ONLY with:
`sr_support_dist`/`sr_resist_dist`, `resistance_strength`/`support_strength`,
`resistance_age_bars`/`support_age_bars`, `sr_level_count`, plus POC/VAH/VAL reconstructed from
`poc_dist_atr`/`poc_rolling_dist_atr`/`distance_to_vah_atr`/`distance_to_val_atr` (Phase 163's
D-16 ATR-normalized-distance design — reconstruct a price via
`entry_price ± distance_atr_field * atr`, not a raw price column). Verify live before wiring:
`SELECT count(*) FROM feature_vectors WHERE sr_support_dist IS NOT NULL` must return `>0` (only
true after Phase 163 executes — Pitfall 2).

**`_STRENGTH_FIELD` companion-strength lookup pattern** (lines 146-166, `_resolve_strength`, lines
175-186) — maps a candidate's `name` to a companion "quality" feature key
(`support_strength`/`*_age_bars`), decaying to `default` when absent. Reuse this shape for
Phase 163's `resistance_strength`/`support_strength`/`*_age_bars` fields — they map directly onto
this pattern per RESEARCH.md's Q3 recommendation.

**Extension-point comment required** (per CONTEXT.md D-06 / RESEARCH.md Open Question 4): leave
an explicit comment in the new module's spec table pointing at the follow-on todo that will
extend it with SMC/swing/fib/anchored-VWAP sources once Phases 164/165 land.

**Fresh APR namespace — do not reuse v2.x keys** (RESEARCH.md Finding 5): `zone_engine.py` reads
its thresholds via `feature.zone_engine.*`/`weights.zone_engine.*` (lines 36-69, `_read_config`
+ `_cluster_radius_atr`/`_zone_buffer_atr`/`_strength_weight`/`_proximity_weight`) — this
pattern (a `set_config_service`/`_read_config` module-level pair) is the right SHAPE to copy, but
seed fresh `alpha.frame.*`-namespaced keys in migration 253, not the archived `feature.zone_engine.*`
family.

---

### `scripts/analysis/gate166_frame_recalibration_eval.py` (new) — service, batch

**Analog:** `scripts/analysis/score03_gate2_execution_eval.py` (full file, 531 lines) — RESEARCH.md
already states this should be mirrored "exactly."

**Imports pattern to copy near-verbatim** (lines 38-66):
```python
from __future__ import annotations
import argparse, asyncio, hashlib, json, sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import asyncpg
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.analysis.phase143_1_08_shadow_validation import (
    _annualized_sharpe, _max_drawdown,
)
from services._batch_utils import cfg as _cfg
from services.counterfactual_tracker import (
    _DEFAULT_BOOTSTRAP_RANDOM_STATE, evaluate_frame_gate, frame_gate_passes,
)
from src.config.settings import Settings
from src.core.service_utils import format_iso_ts
```

**Same-`bar_ts` aggregation before any cumulative statistic — mandatory, todo 172** (lines
169-186, `_aggregate_pnl_by_bar_ts`):
```python
def _aggregate_pnl_by_bar_ts(rows: list[dict[str, Any]]) -> np.ndarray:
    """SUM counterfactual_pnl_r across all frames sharing the same bar_ts ... Frames sharing
    an exact bar_ts are genuinely SIMULTANEOUS positions ... Aggregating to one summed value
    per distinct bar_ts BEFORE the cumulative walk fixes this structurally."""
    by_bar_ts: dict[Any, float] = {}
    for row in rows:
        by_bar_ts[row["bar_ts"]] = by_bar_ts.get(row["bar_ts"], 0.0) + row["pnl_r"]
    return np.array([by_bar_ts[bt] for bt in sorted(by_bar_ts)], dtype=float)
```

**Regime-stratified companion — mandatory per D-05, reuse verbatim** (lines 255-282,
`_compute_regime_companion`):
```python
def _compute_regime_companion(rows, bootstrap_max_n, bootstrap_batch, bootstrap_random_state,
                               regime_gate_min_clusters):
    regime_cells = evaluate_frame_gate(
        rows, min_n=1, bootstrap_max_n=bootstrap_max_n, bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
        group_key=lambda row: (row["direction"], row["regime"]),
        min_clusters=regime_gate_min_clusters,
    )
    evaluated_cells = [c for c in regime_cells if c["coverage"] == "evaluated"]
    c2_regime_stratified_passes = (
        all(c["passes"] for c in evaluated_cells) if evaluated_cells else None
    )
    ...
    return regime_cells, c2_regime_stratified_passes, c7_regime_stratified_no_confident_loss
```

**Pure evidence-assembly core — the exact function shape both `--dry-run` and the real write path
call, and what unit tests exercise on synthetic rows** (lines 303-317 signature +
`_compute_pooled_criteria`, lines 189-252): assemble a single `evidence` dict with pooled c1-c5
criteria + regime companion, never raise on a statistical FAIL (`result='fail'` is a normal
value; exceptions reserved for genuine system faults).

**`_json_safe` non-finite-float sanitizer — reuse, do not re-derive** (lines 402-426):
```python
def _json_safe(obj: Any) -> Any:
    """... Python's json.dumps emits bare Infinity/-Infinity/NaN ... PostgreSQL's jsonb parser
    correctly rejects [them] ... c2_ci_upper/c7 short-side CI upper bounds legitimately land
    at +inf ... this evidence payload always contains such values."""
    if isinstance(obj, float):
        if obj == float("inf"): return "Infinity"
        if obj == float("-inf"): return "-Infinity"
        if obj != obj: return "NaN"
        return obj
    if isinstance(obj, dict): return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list): return [_json_safe(v) for v in obj]
    return obj
```

**Atomic dry-run-then-one-shot write pattern — reuse exactly, new `_GATE_ID`** (lines 429-454):
```python
async def _write_gate2_row(pool, evidence, run_ts, look_log_path) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchval(
                "SELECT count(*) FROM gate_evaluations WHERE gate_id = $1", _GATE_ID
            )
            if existing:
                raise RuntimeError(f"'{_GATE_ID}' already has {existing} row(s) ... run-once "
                                    "cadence (D-04) violated.")
            await conn.execute(
                "INSERT INTO gate_evaluations (gate_id, result, evidence, run_ts) "
                "VALUES ($1, $2, $3::jsonb, $4)",
                _GATE_ID, evidence["result"], json.dumps(_json_safe(evidence)), run_ts,
            )
    _append_look_log(look_log_path, run_ts, evidence)
```
Set `_GATE_ID` to a NEW value per CONTEXT.md D-04/RESEARCH.md Assumption A4 (e.g. two rows, one
per candidate — `gate166_scalar`/`gate166_structural`, or a single combined `gate166_frame_recal`
— an explicit planning decision, not locked here) — never reuse `"gate2_execution"`.

**`main()` argparse + dry-run branch to mirror** (lines 457-527) — `--dry-run` flag, full
computation + printed verdict + zero writes; real path calls `_write_gate2_row`. Per Pitfall 5,
finalize each candidate's in-sample calibration BEFORE running this script against OOS data even
once — more than one `--dry-run` invocation per candidate during development is a holdout leak.

---

### `production/migrations/253_alpha_frame_stop_target_calibration.sql` (new) — migration

**Analog 1 (APR key seed with full provenance comment):** `production/migrations/243_frame_min_stop_price_fraction.sql` (full file, 61 lines) — copy this file's shape exactly: a comment block explaining WHY the key exists and citing the specific finding/todo, then `config_schema` INSERT with `min_value`/`max_value` bounds and a `[initial_estimate]`-tagged description, then `config_state` seed, then `config_history` provenance row, all `ON CONFLICT DO NOTHING`, wrapped in `BEGIN`/`COMMIT`:
```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'alpha.frame.min_stop_price_fraction', 'float', '0.001', 0.0, 0.05,
    '[initial_estimate] FRAME-01/counterfactual_tracker: minimum stop_distance as a '
    'fraction of entry_price (todo 162). ...'
) ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.frame.min_stop_price_fraction', '0.001', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'alpha.frame.min_stop_price_fraction', 1, '0.001', 'migration_243',
    'Seed minimum stop-distance-as-fraction-of-price floor, todo 162 ... [initial_estimate]')
ON CONFLICT DO NOTHING;
```

**Analog 2 (per-regime/tf calibrated-key namespace precedent):** `production/migrations/205_alpha_frames_schema.sql` lines 159-257 — the original global-scalar seed for `alpha.frame.stop_atr_mult`/`alpha.frame.target_r_multiple` (`'1.5'`/`'2.0'`, `migration_214`/`214`, `[initial_estimate]`). The new migration's per-(regime,tf) keys (`alpha.frame.stop_atr_mult.<regime>.<tf>`, `alpha.frame.target_r_multiple.<regime>.<tf>`) are NOT seeded with values here (they get written later by `_calibrate_stop_target()`'s first live run, exactly as `alpha.frame.hold_max_bars.<regime>.<tf>` keys are — check `production/migrations/195_*.sql`, the hold_max_bars precedent, for the "schema/key exists, no per-cell value seeded" pattern if the calibration keys need a `config_schema` row without a `config_state` row).

**Next free migration number confirmed:** highest existing is `252_ic_refresh_min_new_fraction.sql` — `253` is correct and free (verified via `ls production/migrations/`).

**Namespace discipline (Finding 5):** seed fresh `alpha.frame.*` keys only. Do not reuse
`feature.trade_framer.*` (migration 141, `structure_snap_proximity_atr`, already migrated —
CONTEXT.md's characterization of this as unmigrated was incorrect per RESEARCH.md) or
`feature.zone_engine.*`/`weights.zone_engine.*` (migrations 126/128).

---

### Test files (new) — mirror existing sibling tests structurally

| New test file | Analog | Analog's structure to copy |
|---|---|---|
| `tests/unit/test_ensemble_ic_stop_target_calibration.py` | `tests/unit/test_ensemble_ic_decay.py` | Pure-function unit tests, no DB/Kafka. `sys.path.insert` boilerplate (lines 24-31), a `_cell(...)` synthetic-row builder helper (lines 38-51), one `test_*` per decay-curve/selection scenario. Import target under test directly: `from services.ensemble_ic_engine import _select_hold_bars_from_decay` → adapt to the new selection function's name. |
| `tests/unit/test_structural_confluence.py` | `tests/unit/trading/test_zone_engine.py` | `import pytest`; import public API only (`ZoneCandidate`, `ZoneResult`, `collect_candidates`, `find_best_level`, `resolve_structural_zone` — adapt names to the new module); synthetic `features: dict` fixtures per test (see `test_collect_candidates_long_gathers_support_levels`, lines 15-33) using ONLY the Phase-163-owned field names (`sr_support_dist`, `sr_resist_dist`, `resistance_strength`, `support_strength`, `poc_dist_atr`, etc.) — do not reuse this analog's v2.x field names (`nearest_support`, `swing_low`, `ema_21`, ...) as fixture keys. |
| `tests/unit/test_gate166_frame_recalibration_eval.py` | `tests/unit/test_score03_gate2_execution_eval.py` | Exercise `assemble_gate2_evidence`-equivalent pure function directly on synthetic row lists (no DB); include a same-`bar_ts` tie-density fixture to assert `_aggregate_pnl_by_bar_ts`-equivalent aggregation fires before any cumulative stat (todo 172 regression guard); assert the regime companion is always present in the evidence dict (D-05); assert the gate writes a NEW `gate_id`, never `"gate2_execution"` (D-04) — mirrors this file's own `test_gate166_uses_new_gate_id`-style assertion named in RESEARCH.md's test map. |

## Shared Patterns

### CR-02 champion-`weight_version` gate (calibration writes)
**Source:** `services/ensemble_ic_engine.py` lines 1043-1052 (dispatch) + module docstring lines
37-38.
**Apply to:** Both the scalar candidate's `_calibrate_stop_target()` and any future calibration
function this phase adds — never fires against a challenger `weight_version` under evaluation.
```python
if weight_version == champion_weight_version:
    n_keys_written = await self._calibrate_X(pool, corpus_all_results, config)
else:
    self.logger.info("ensemble_ic.X_calibration_skipped", reason="scoped_weight_version_run", ...)
    n_keys_written = 0
```

### APR read-with-fallback + eager validation
**Source:** `services/alpha_frame_writer.py` lines 156-174 (`FrameConfig.from_apr`) and lines
344-348 (`hold_key` per-cell lookup).
**Apply to:** All new `alpha.frame.*` key reads in both `ensemble_ic_engine.py` and
`alpha_frame_writer.py` — validate global/fallback values once eagerly at config-load time
(raise `ValueError` on an invalid value, per `stop_atr_mult <= 0` at line 159), read per-cell keys
with a `_cfg(cfg, key, default)` fallback to the global scalar, and accumulate (never per-row log)
any missing per-cell keys.

### Aggregate-not-per-row logging over a full-corpus loop
**Source:** `services/alpha_frame_writer.py` lines 328-329, 390-403 (`missing_hold_keys: set[str]`).
**Apply to:** Any new loop in `alpha_frame_writer.py`'s `--backfill` path or the new gate script's
row-scan — accumulate a counter/set, log once per partition/run, per CLAUDE.md's
"never log per-row inside a loop over the full corpus" rule.

### Dry-run-then-one-shot atomic gate write
**Source:** `scripts/analysis/score03_gate2_execution_eval.py` lines 429-454 (`_write_gate2_row`)
+ lines 457-527 (`main`).
**Apply to:** `scripts/analysis/gate166_frame_recalibration_eval.py` — full computation under
`--dry-run` with zero writes; real path re-checks no prior row exists for the `gate_id` inside the
same transaction as the INSERT.

### `_json_safe` non-finite-float sanitization
**Source:** `scripts/analysis/score03_gate2_execution_eval.py` lines 402-426.
**Apply to:** Any new script writing a `jsonb` evidence payload containing bootstrap CI bounds
(which legitimately hit `+inf`/`nan` for thin cells) — reuse this exact function, do not
re-derive an ad-hoc `try/except` around `json.dumps`.

### Day-clustered bootstrap gate machinery (do not reimplement)
**Source:** `services/counterfactual_tracker.py` lines 172-283 (`frame_gate_passes`,
`evaluate_frame_gate`).
**Apply to:** The new gate script's pooled and regime-stratified verdicts — both already handle
BCa-vs-analytic-CLT method selection, day-clustering, `bootstrap_random_state` reproducibility
(WR-01), and the `min_clusters`/`coverage="insufficient"` distinction (D-05's disclose-don't-gate
requirement).

### Exception variable name and UTC timestamps
**Source:** project-wide (`services/ensemble_ic_engine.py` line 913 `except Exception as error:`;
`services/alpha_frame_writer.py` line 255 `datetime.now(UTC)`).
**Apply to:** All new/modified files in this phase — `except X as error:` never `exc`;
`datetime.now(UTC)` never `datetime.now()`/`datetime.utcnow()`.

## No Analog Found

None — every file in this phase's scope has a strong (exact or near-exact) analog already in the
codebase. This is explicitly called out in RESEARCH.md's "Key insight": the phase's entire
toolkit (calibration-mechanism half + confluence-scoring half) already exists from Phase
142B/143.1/148 and the archived v2.x trading tier; the work is porting/extending, not novel
design.

## Metadata

**Analog search scope:** `services/`, `src/intelligence/trading/`, `scripts/analysis/`,
`production/migrations/`, `tests/unit/` (+ `tests/unit/trading/`) — scope directly dictated by
RESEARCH.md's own exhaustive file-by-file investigation (Q1-Q4, Sources section), not
re-searched from scratch.
**Files scanned/read directly (this pass):** `services/ensemble_ic_engine.py` (imports,
`EnsembleICConfig`, `_QUALIFYING_FLAGS`, `_select_hold_bars_from_decay`, `_calibrate_hold_max_bars`,
CR-02 dispatch), `services/alpha_frame_writer.py` (full file), `src/intelligence/trading/zone_engine.py`
(full file), `src/intelligence/trading/trade_framer.py` (`_classify_stop_basis`, `_select_vp`),
`services/counterfactual_tracker.py` (`frame_gate_passes`, `evaluate_frame_gate`),
`scripts/analysis/score03_gate2_execution_eval.py` (full file), `production/migrations/243_frame_min_stop_price_fraction.sql`
(full file), `production/migrations/205_alpha_frames_schema.sql` (grep + targeted lines),
`tests/unit/test_ensemble_ic_decay.py`, `tests/unit/trading/test_zone_engine.py`,
`tests/unit/test_alpha_frame_writer_geometry.py` (heads of each).
**Pattern extraction date:** 2026-07-23
