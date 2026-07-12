# Phase 144: Cross-Sectional Regime Model (`regime_group`) - Pattern Map

**Mapped:** 2026-07-12
**Files analyzed:** 17 (1 migration, 4 signal modules, 1 dispatcher service, 2 modified services,
1 modified pipeline script, 1 doc, 6 new test files, 1 modified test)
**Analogs found:** 17 / 17 (all files have a live, exact or near-exact analog — this phase
extends an already-established family of oneshot regime-labeling code, not a new pattern)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `production/migrations/229_regime_group.sql` | migration | schema-change + APR seed | `production/migrations/174_market_regimes.sql` + `182_equity_regime_model_apr.sql` | exact |
| `src/intelligence/regime_signals/__init__.py` | utility (registry) | transform (pure lookup) | `src/core/ai/registry.py` (`_REGISTRY: dict[str, type]`) | role-match (structure only; no prior "pure compute module registry" in this codebase) |
| `src/intelligence/regime_signals/breadth_vol.py` | utility (signal module) | transform (pure function, no DB) | `services/equity_regime_model.py` (`_compute_vix_pct_rank`, `_compute_breadth_fraction`, `_tf_window`) | exact (this **is** the extraction source per CONTEXT.md D-01/plan doc) |
| `src/intelligence/regime_signals/curve_credit.py` | utility (signal module) | transform (pure function, no DB) | `breadth_vol.py` (once written, for structure) — no live curve/credit-spread precedent | role-match (new math, established structural pattern) |
| `src/intelligence/regime_signals/commodity_momentum_ts.py` | utility (signal module) | transform (pure function, no DB) | `breadth_vol.py` (structure); ships `enabled: false` | role-match |
| `src/intelligence/regime_signals/fx_dollar_carry.py` | utility (signal module) | transform (pure function, no DB) | `breadth_vol.py` (structure); ships `enabled: false` | role-match |
| `services/cross_sectional_regime_model.py` | service (oneshot dispatcher) | batch (fetch → compute → write) | `services/equity_regime_model.py` (entire file — this is its generalized replacement) | exact |
| `services/equity_regime_model.py` | service (oneshot, kept as rollback) | batch | itself, unmodified except a deprecation docstring header | exact (no functional change) |
| `services/ic_engine.py` | service (batch compute + routing) | batch, CRUD (writes `feature_ic_scores`) | itself — current `ICEngineConfig`/`_assert_prerequisites`/`_compute_cross_sectional_tf` | exact (modifying in place) |
| `scripts/ops/corpus/ops_corpus_pipeline_run.sh` | orchestration script | batch (sequential steps) | itself — current step-4 slot | exact |
| `docs/foundation/glossary.md` | docs | — | itself — existing glossary entry format | exact |
| `tests/unit/test_regime_signals_breadth_vol.py` | test | — | `tests/unit/services/test_equity_regime_model_causal.py` | exact (mirror causal-rank + `_tf_window` test shapes) |
| `tests/unit/test_regime_signals_curve_credit.py` | test | — | plan doc's own Task 3 test file (complete as written per RESEARCH.md) | role-match |
| `tests/unit/test_regime_signals_commodity_momentum_ts.py` | test | — | plan doc's own Task 6 test file | role-match |
| `tests/unit/test_regime_signals_fx_dollar_carry.py` | test | — | plan doc's own Task 7 test file | role-match |
| `tests/unit/test_cross_sectional_regime_model.py` | test | — | plan doc's own Task 4 Step 1 test file (complete, CI-clean, no DB) | exact |
| `tests/unit/test_ic_engine_routing.py` | test | — | `tests/unit/test_ic_engine_staleness.py` (direct-import pure-function test pattern against `services.ic_engine`) | role-match |

## Pattern Assignments

### `production/migrations/229_regime_group.sql` (migration)

**Analogs:** `production/migrations/174_market_regimes.sql` (original `market_regimes` table +
index + APR-key block that this migration renames/extends) and
`production/migrations/182_equity_regime_model_apr.sql` (adding calibration-window APR keys to
the same `alpha.regime.*` namespace this migration touches).

**Column-rename + index-rename pattern** (live schema confirmed 2026-07-12 via `\d market_regimes`
— `asset_class` still live, PK is `(asset_class, tf, ts)`, named index
`market_regimes_equity_tf_ts`):
```sql
ALTER TABLE market_regimes RENAME COLUMN asset_class TO regime_group;
ALTER INDEX market_regimes_equity_tf_ts RENAME TO market_regimes_regime_group_tf_ts;
-- PK automatically tracks the renamed column; no separate PK rename needed.
```

**APR schema+state INSERT pattern** (`production/migrations/182_equity_regime_model_apr.sql:14-42`,
verbatim structure to copy):
```sql
INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
  ('alpha.regime.realized_vol_window', 'int', '20',
   'Rolling window (daily bars) for SPY realized vol (log-return std). [initial_estimate] '
   'Scaled to TF bars via _tf_window(daily, tf). ML target: No.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('alpha.regime.realized_vol_window', '20', 1)
ON CONFLICT (config_key) DO NOTHING;
```

**CRITICAL — JSON-typed APR key gotcha (not caught in RESEARCH.md, verified live this session):**
`alpha.regime.groups` must be seeded with `value_type='json'` (plan doc's Task 1 does this
correctly, `docs/plans/2026-07-01-cross-sectional-regime-model.md:156-176`). But
`src/config/config_service.py:94-95`'s `_parse_value()` calls `json.loads(value)` **at cache-load
time** for any `value_type='json'` key:
```python
# src/config/config_service.py:85-97
if vt == "json":
    return json.loads(value)
```
`services/_batch_utils.py::load_config_service_sync()` (used by every batch service including
`equity_regime_model.py` and `ic_engine.py`) populates the whole cache this way at startup. This
means **`cfg.get_sync("alpha.regime.groups", ...)` returns an already-parsed `list[dict]`, not a
raw JSON string**, whenever the key exists in `config_state` (i.e. every real run, once this
migration lands) — confirmed by the live precedent
`src/intelligence/trading/ofi_continuation.py:113-116`:
```python
mag_floors: dict = (
    cfg.get_sync("threshold.ofi_continuation.magnitude_floors", _MAGNITUDE_FLOORS_DEFAULT)
    if cfg
    else _MAGNITUDE_FLOORS_DEFAULT
)
```
— no second `json.loads()` call at any real call site for an existing `'json'`-typed key. The
plan doc's `_parse_group_configs(raw: str)` (Task 4 Step 1, tested with
`raw = json.dumps([...])`) and the `ICEngineConfig.regime_groups_json: str` field described in
RESEARCH.md's Pattern 2 both assume `get_sync()` returns a raw string — this is only true for the
**fallback default value** (when the key is missing from `config_state`), not for the live seeded
value. **The planner must decide:** either (a) keep `_parse_group_configs` accepting a raw JSON
string and have the call site do `json.dumps(cfg.get_sync(...))` when the cached value is already
a `list`/`dict` (round-trips cleanly either way), or (b) make `_parse_group_configs` accept
`str | list[dict]` and skip `json.loads()` when already a list. Do not ship the plan doc's
`str(cfg.get_sync(...))` pattern verbatim — `str()` on an already-parsed Python `list[dict]`
produces a Python-repr string (single quotes, `True`/`False`) that is **not valid JSON** and will
raise inside `json.loads()` downstream.

---

### `src/intelligence/regime_signals/__init__.py` (registry)

**Analog:** `src/core/ai/registry.py:32` — `_REGISTRY: dict[str, type[BaseAIWorker]] = {}` module-level
dict-of-implementations pattern (role-match for the "string key → module/class" registry shape;
no prior instance of a *pure compute module* registry specifically, since this codebase's other
registries map to classes/prompts, not stateless modules).

**Pattern to use (plan doc's version is structurally sound, no drift risk since this is a new file
with no live predecessor to diff against):**
```python
from src.intelligence.regime_signals import breadth_vol, curve_credit

REGISTRY: dict[str, object] = {
    "breadth_vol": breadth_vol,
    "curve_credit": curve_credit,
}
```
Commodity/fx modules get added to this dict even though their groups ship `enabled: false`
(CONTEXT.md Claude's Discretion) — registry completeness is independent of `enabled` gating, which
happens in `_parse_group_configs`/`_build_symbol_regime_class`, not here.

---

### `src/intelligence/regime_signals/breadth_vol.py` (signal module — extraction target)

**Analog:** `services/equity_regime_model.py` (full file, 620 lines, read this session) — this is
the literal extraction source per CONTEXT.md D-01 and the plan doc's own File Map.

**DO NOT copy the plan doc's `Task 2 Step 4` code verbatim** — it reintroduces two bugs already
fixed in the live file (confirmed via direct diff this session and in RESEARCH.md Pitfall 1):

**1. Causal bisect-based expanding rank — copy this exact logic**
(`services/equity_regime_model.py:224-251`, fixed Phase 141 P0-T2):
```python
# Causal bisect-based expanding rank (no look-ahead bias).
# Each position's rank is computed against all PRIOR valid values only.
sorted_window: list[float] = []  # sorted; never contains NaN
causal_ranks: list[float] = []

for val in vix_z:
    if math.isnan(val):
        causal_ranks.append(float("nan"))
        continue
    if not sorted_window:
        bisect.insort(sorted_window, val)
        causal_ranks.append(1.0)
        continue
    left = bisect.bisect_left(sorted_window, val)
    right = bisect.bisect_right(sorted_window, val)
    rank = (left + right) / 2 / len(sorted_window)
    bisect.insort(sorted_window, val)
    causal_ranks.append(rank)
```
The plan doc's `breadth_vol.py::_compute_vix_pct_rank` instead uses
`vix_z.rank(pct=True, na_option="keep")` (`docs/plans/2026-07-01-cross-sectional-regime-model.md:564`)
— a non-causal whole-series rank. Confirmed present in the plan doc verbatim this session — must
be replaced, not merely reviewed.

**2. TF-window scaling — copy this exact helper**
(`services/equity_regime_model.py:84-101`):
```python
_BARS_PER_DAY: dict[str, int] = {
    "1d": 1,
    "1h": 7,  # rounded: 6.5 → 7 for conservative warmup
    "15m": 26,
    "5m": 78,
}

def _tf_window(daily_window: int, tf: str) -> int:
    """Convert a daily-bar window count to the equivalent bar count for a given TF."""
    bars_per_day = _BARS_PER_DAY.get(tf, 1)
    return daily_window * bars_per_day
```
**Architectural gap the planner must resolve:** the plan doc's `REGISTRY` interface contract
(`src/intelligence/regime_signals/__init__.py` docstring) declares `compute(ref_bars, params) ->
tuple[pd.Series, pd.Series] | None` with **no `tf` parameter** — `_tf_window()` cannot scale a
window without knowing the TF. Either (a) add `tf: str` to every signal module's `compute()`
signature (breaking the plan doc's spec'd interface, but correctly threading TF through), or (b)
have `cross_sectional_regime_model.py`'s dispatcher pre-scale the window params via `_tf_window()`
*before* calling `compute(ref_bars, params)`, passing already-bar-scaled values in `params`. Option
(b) keeps signal modules TF-agnostic (arguably cleaner — matches "pure function" framing) and
avoids a signature break; recommend (b) unless the planner finds a reason `curve_credit.py` etc.
need TF-awareness for other reasons.

**Breadth fraction (multi-symbol 200MA cross-sectional mean) — pattern to port**
(`services/equity_regime_model.py:298-332`, adjusted to operate on pre-fetched `ref_bars: dict[str,
pd.DataFrame]` instead of a DB fetch, since the new dispatcher fetches once and passes to all
signal modules — DB access moves to `cross_sectional_regime_model.py`, `compute()` stays DB-free
per the `REGISTRY` docstring contract):
```python
above_ma_by_sym: dict[str, pd.Series] = {}
for sym, df in ref_bars.items():
    s = df.set_index("timestamp")["close"].astype(float).sort_index()
    if len(s) < ma_window:
        continue
    ma = s.rolling(window=ma_window, min_periods=ma_window).mean()
    above = (s > ma).where(ma.notna()).astype(float)
    above_ma_by_sym[sym] = above.rename(sym)
if not above_ma_by_sym:
    return pd.Series(dtype=float, name="breadth")
return pd.concat(list(above_ma_by_sym.values()), axis=1).mean(axis=1, skipna=True).rename("breadth")
```

---

### `src/intelligence/regime_signals/curve_credit.py` (signal module — new math)

**Analog:** structural pattern from `breadth_vol.py` (once written) — `compute()` /
`build_tiers()` / `PROB_KEYS` contract, no live curve/credit-spread precedent exists in the
codebase (confirmed — no prior TLT-SHY or HYG-LQD spread computation found in `services/` or
`src/intelligence/`).

**Open question flagged by RESEARCH.md (Assumption A1), still unresolved — planner must decide:**
should `curve_window`/`credit_window` (plan doc default `60`, `[conventional]`-tagged) be
`_tf_window`-scaled like `breadth_vol`'s windows, or intentionally left as literal bar counts
since this is a brand-new signal with no prior bug-fixed precedent to match? Recommend applying
the same `_tf_window()` scaling for consistency across all `regime_signals/` modules (avoids a
second, inconsistent TF-handling convention within the same package) — but this is a genuine
design call, not a verified-bug fix like `breadth_vol`'s two regressions.

No further extraction needed — the plan doc's `Task 3` code
(`docs/plans/2026-07-01-cross-sectional-regime-model.md:750-858`) is new math with no live
predecessor to diff against; RESEARCH.md found no drift issues here.

---

### `src/intelligence/regime_signals/commodity_momentum_ts.py` / `fx_dollar_carry.py` (ship disabled)

**Analog:** same structural pattern as `curve_credit.py` — plan doc's Task 6/7 code
(`docs/plans/2026-07-01-cross-sectional-regime-model.md:2354-2456`, `2561-2641`) has no live
predecessor and RESEARCH.md found no drift issues. Build per plan doc as-is (CONTEXT.md Claude's
Discretion — cheap to build now, groups stay `enabled: false` regardless of todo 041).

---

### `services/cross_sectional_regime_model.py` (new dispatcher — generalizes `equity_regime_model.py`)

**Analog:** `services/equity_regime_model.py` (full file) — this file **is** the direct
predecessor being generalized; CONTEXT.md/RESEARCH.md both confirm it stays live unmodified
(except a deprecation header) as an emergency rollback fallback.

**Imports pattern** (`services/equity_regime_model.py:41-66`, copy verbatim except symbol-specific
imports):
```python
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import load_config_service_sync as _load_config_service
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/cross_sectional_regime_model.log")
_logger = structlog.get_logger(__name__)
```
**Note:** the new dispatcher does NOT need `ProcessPoolExecutor`/`concurrent.futures` (plan doc's
Global Constraints: "No `ProcessPoolExecutor` in the new service — label assignment is vectorized
numpy... DB fetch is the bottleneck and is serial by design") — `equity_regime_model.py` uses
`ProcessPoolExecutor` for its per-TF label assignment; the new dispatcher intentionally drops that
concurrency (a deliberate simplification, not an oversight — confirmed in both CONTEXT.md's
canonical plan doc and RESEARCH.md's Standard Stack section).

**D-06 oneshot `main()` contract — this IS the pattern to copy** (`services/equity_regime_model.py:365-397,
603-617`, argparse + `init_otel_providers` + try/except/finally + `JOB_COMPLETED_TOTAL`):
```python
def main() -> None:
    parser = argparse.ArgumentParser(description="...")
    parser.add_argument("--tf", nargs="*", default=_DEFAULT_TFS, ...)
    parser.add_argument("--dry-run", action="store_true", ...)
    args = parser.parse_args()

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("cross_sectional_regime_model.otel_init_failed", error=str(error))

    t0 = time.monotonic()
    status = "success"
    exit_code = 0
    settings = Settings()
    conn = None
    try:
        conn = _connect_db(settings)
        cfg = _load_config_service(conn)
        # ... fetch, compute, write ...
    except Exception as error:
        _logger.error("cross_sectional_regime_model.run_failed", error=str(error))
        status = "failure"
        exit_code = 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()
    sys.exit(exit_code)
```
`_JOB = "cross-sectional-regime-model"` (RESEARCH.md Assumption A2 — no systemd unit exists to
match, this only affects the observability label string; the pipeline step name should match).

**IMPORTANT — this is NOT a `BaseBatch` subclass.** CLAUDE.md documents `src/core/agent/base_batch.py`
as the Ring 0 base class for "all Phase 138+ batch services," but `equity_regime_model.py` and
`ic_engine.py` (the direct sibling and downstream consumer of this new file) both use the plain
argparse-`main()`-function pattern shown above, **not** `BaseBatch` (confirmed via grep — neither
file references `BaseBatch`). Follow the live sibling's actual pattern, not the general Ring 0
convention that this specific family of psycopg2-based labeling scripts has never used.

**Write/upsert pattern — generalize the `INSERT` to parameterize the group name**
(`services/equity_regime_model.py:555-562`, currently hardcodes `'equity'`):
```python
insert_sql = """
    INSERT INTO market_regimes (regime_group, tf, ts, regime_label, regime_prob_vector)
    VALUES (%(regime_group)s, %(tf)s, %(ts)s, %(regime_label)s, %(regime_prob_vector)s::jsonb)
    ON CONFLICT (regime_group, tf, ts)
    DO UPDATE SET
        regime_label = EXCLUDED.regime_label,
        regime_prob_vector = EXCLUDED.regime_prob_vector
"""
```
(column renamed per migration 229; `batch_dicts` must include `"regime_group": group_name` per row
— `json.dumps()` still required for the JSONB column, per project convention.)

**Fresh-connection-per-fetch pattern** (`services/equity_regime_model.py:286-293, 335-357`) — copy
this exactly for any per-symbol/per-group bar fetch inside the dispatcher: opens a dedicated
`psycopg2.connect(dsn)` with `autocommit = True` for each read query, closed in a `finally` block,
to avoid idle-connection termination during multi-minute ETF-bar fetches (same rationale that
motivated the `_persist_corpus_results` connection-lifetime fix in `ic_engine.py`).

---

### `services/equity_regime_model.py` (modify — deprecation header only)

**No functional change** (CONTEXT.md Claude's Discretion, plan doc Task 6). Add a module
docstring header noting it is superseded by `cross_sectional_regime_model.py` and retained only
as an emergency single-group rollback path. No analog needed — this is the file being deprecated,
not extended.

---

### `services/ic_engine.py` (modify — routing, 4 touch points + new function)

**Analog:** itself — the file's **current** structure (3020 lines, read this session at each
touch point) is the pattern to extend; the plan doc's Task 5 diffs target a pre-Phase-143/143.1
version and must be re-derived against the live shapes below (RESEARCH.md Pitfalls 2/3, confirmed
directly this session).

**1. `ICEngineConfig` dataclass — add a field, don't replace the loading mechanism**
(`services/ic_engine.py:311-372`, frozen dataclass with defaulted new-field convention already
established by Phase 143/143.1's own additions):
```python
@dataclasses.dataclass(frozen=True)
class ICEngineConfig:
    ...
    equity_model_enabled: bool
    ...
    # Phase 144: cross-sectional regime_group routing. Defaulted (not required) for the
    # same reason as every other post-Phase-143 field on this dataclass -- pre-existing
    # direct ICEngineConfig(...) construction sites (test_hac_ic_sharpe.py) must not break
    # on field-count growth.
    regime_groups_json: str = "[]"
```
`from_apr()` binding site (`services/ic_engine.py:385-406`):
```python
@classmethod
def from_apr(cls, cfg: Any) -> ICEngineConfig:
    return cls(
        ...
        equity_model_enabled=str(cfg.get_sync("alpha.regime.equity_model_enabled", "true")).lower() == "true",
        # See the migration's "CRITICAL — JSON-typed APR key gotcha" section above:
        # get_sync() returns an already-parsed list[dict] once the key is seeded, a raw
        # string only for the missing-key fallback. Normalize here, once, at bind time:
        regime_groups_json=json.dumps(cfg.get_sync("alpha.regime.groups", []))
            if not isinstance(cfg.get_sync("alpha.regime.groups", []), str)
            else cfg.get_sync("alpha.regime.groups", "[]"),
    )
```
(Exact normalization helper is a planner implementation detail; the key correctness requirement is
"never call `json.loads()` on something `get_sync()` already parsed, and never call `str()` on a
`list[dict]` expecting valid JSON out" — both documented above.)

**2. `_assert_prerequisites` — extend the existing 3-arg signature, don't replace it**
(`services/ic_engine.py:461-511`, current live signature and the `asset_class='equity'` site to
generalize):
```python
def _assert_prerequisites(
    conn: Any, tfs: list[str] | None = None, equity_model_enabled: bool = True
) -> None:
    ...
    # market_regimes prerequisite: required when equity_model_enabled=True
    if equity_model_enabled and tfs:
        for tf in tfs:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM market_regimes WHERE asset_class='equity' AND tf=%s",
                    (tf,),
                )
```
Generalize to loop over `enabled_groups` and query `regime_group=%s` per group (plan doc's Task 5
Step 5 intent is correct; apply as an *additional* param on top of the current 3-arg signature,
matching RESEARCH.md's explicit guidance — Live `_assert_prerequisites` code confirmed at these
exact lines this session).

**3. `AmbiguousRegimeGroupError` + `_build_symbol_regime_class` — new function, plan doc code is
current and correct as written** (no drift — new code, not a diff against a moving live file):
```python
class AmbiguousRegimeGroupError(ValueError):
    """Raised when a symbol's tags match more than one enabled regime group."""

def _build_symbol_regime_class(
    tags_by_symbol: dict[str, set[str]],
    group_configs: list[dict],
) -> dict[str, str]:
    prefixes_by_group: list[tuple[str, list[str]]] = [
        (g["name"], [p.rstrip("*") for p in g.get("tag_filter", [])])
        for g in group_configs
        if g.get("enabled", True)
    ]
    result: dict[str, str] = {}
    for symbol, tags in tags_by_symbol.items():
        matches = [
            group_name
            for group_name, prefixes in prefixes_by_group
            if any(any(t.startswith(pfx) for t in tags) for pfx in prefixes)
        ]
        if len(matches) > 1:
            raise AmbiguousRegimeGroupError(
                f"Symbol {symbol!r} matches multiple enabled regime groups "
                f"{matches} — tag_filter patterns must be mutually exclusive. "
                f"Tags: {sorted(tags)}"
            )
        if matches:
            result[symbol] = matches[0]
    return result
```
(Source: `docs/plans/2026-07-01-cross-sectional-regime-model.md:1689-1742`, already unit-tested in
the plan doc's own Task 5 test file — this specific block was NOT flagged as drifted by
RESEARCH.md since it's new code with no live analog to diverge from.)

**4. `mr_dict` loading — generalize from single flat dict to per-group dict**
(`services/ic_engine.py:2717-2730`, current live site):
```python
mr_dict_by_tf: dict[str, dict] = {}
if equity_model_enabled:
    for tf in tfs:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ts, regime_label FROM market_regimes WHERE asset_class='equity' AND tf=%s",
                (tf,),
            )
            mr_dict_by_tf[tf] = {r[0]: r[1] for r in cur.fetchall()}
```
Generalize per RESEARCH.md's Architecture Patterns section to
`mr_dicts_by_group: dict[str, dict[str, dict]]` (`{group_name -> {tf -> {ts -> label}}}`), built
once, looped by `enabled_groups`, then threaded into worker args as
`mr_dicts_by_group.get(symbol_regime_class.get(symbol))` (each worker gets only its own symbol's
group dict — the picklability requirement is unchanged from the current single-dict version).

**5. `_compute_cross_sectional_tf` — ADD two params onto the current 10-arg signature, do not
rewrite it** (`services/ic_engine.py:1454-1465`, current live signature — this is Pitfall 2's exact
finding, re-verified this session):
```python
def _compute_cross_sectional_tf(
    conn: Any,
    tf: str,
    regime_label: str,
    training_window_end: Any,
    existing_keys: frozenset[tuple],
    config: ICEngineConfig,
    tracer: Any,
    run_ts: datetime,
    rng: np.random.Generator,
    feature_status_map: dict[str, str] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
```
Add `regime_group: str` and `symbol_list: list[str]` as **additional** params — the plan doc's
version predates both the `config: ICEngineConfig` (Phase 143.1) and `rng: np.random.Generator`
(Component A/todo 091, Phase 143.1-01) threading; a literal patch-apply against the plan doc's
assumed signature will raise `TypeError` immediately.

The actual bug fix — `chunk_sql`'s missing symbol filter (`services/ic_engine.py:1591-1602`, the
independently `[VERIFIED]` contamination bug CONTEXT.md D-01 exists to fix):
```python
chunk_sql = f"""
    SELECT fv.bar_ts, {feature_cols}, {return_cols}, {complete_cols}
    FROM feature_vectors fv
    INNER JOIN forward_returns fr
        ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
        AND fr.return_type = 'executable_open_to_open'
    WHERE fv.tf = %(tf)s
      AND fv.bar_ts = ANY(%(ts_chunk)s)
      AND fv.symbol = ANY(%(symbol_list)s)      -- NEW: the actual contamination fix
    ORDER BY fv.bar_ts
"""
```
Also update the regime-timestamp pre-fetch (`services/ic_engine.py:1555-1571`, currently
`WHERE asset_class = 'equity'`) to `WHERE regime_group = %(regime_group)s`.

**6. Cross-sectional pass loop caller site** (`services/ic_engine.py:2820-2876`, current live call
— must pass the two new params and loop over `enabled_groups × tfs × cs_regimes` instead of just
`tfs × cs_regimes`):
```python
if equity_model_enabled:  # generalize to: if enabled_groups:
    cs_rng = np.random.default_rng(seed=_derive_worker_rng_seed("cross_sectional", config.bootstrap_seed))
    cs_conn = _connect_db(settings)
    try:
        for tf in tfs:
            for regime_label in cs_regimes:   # now: per-group regime label set
                cs_rows, cs_stats = _compute_cross_sectional_tf(
                    conn=cs_conn, tf=tf, regime_label=regime_label,
                    training_window_end=training_window_end,
                    existing_keys=existing_keys_frozen, config=config,
                    tracer=tracer, run_ts=run_ts, rng=cs_rng,
                    feature_status_map=feature_status_map,
                    # NEW:
                    regime_group=group_name, symbol_list=peer_symbols_for_group,
                )
```

**Generalize `equity_model_enabled` bool gates, don't remove them** (RESEARCH.md Anti-Pattern,
confirmed at `services/ic_engine.py:2034` this session):
```python
if equity_model_enabled and corpus_cs_rows:  # -> if bool(enabled_groups) and corpus_cs_rows:
```
Only the boolean semantics need preserving at `_persist_corpus_results`'s gate — full
group-awareness is not required at every one of these sites (RESEARCH.md Anti-Pattern section).

**Open question for the planner (RESEARCH.md Open Question 2, unresolved by this research):**
whether to retire `alpha.regime.equity_model_enabled` (migration 174) in favor of
`alpha.regime.groups[].enabled` entirely — grep `equity_model_enabled` project-wide before
deciding; if `ic_engine.py` is the sole consumer, retiring it avoids two overlapping kill-switches
drifting out of sync.

---

### `scripts/ops/corpus/ops_corpus_pipeline_run.sh` (modify — same-slot script swap)

**Analog:** itself, current live 8-step structure (`scripts/ops/corpus/ops_corpus_pipeline_run.sh:5,
59, 318-324`, confirmed via grep this session — NOT the plan doc's stale 6-step assumption).

**Pattern — literal same-slot swap, no step renumbering:**
```bash
# Before (line 323-324):
run_step 4 "equity_regime_model" \
    "$PYTHON" services/equity_regime_model.py
# After:
run_step 4 "cross_sectional_regime_model" \
    "$PYTHON" services/cross_sectional_regime_model.py
```
No banner/count changes needed — `printf " Step %d/8 — %s\n"` (line 59) is already correct for an
8-step pipeline; the plan doc's Task 6 assumption of a 6→7 step insertion does not apply.

---

### `docs/foundation/glossary.md` (docs)

**Analog:** existing glossary entry format (bolded term + prose definition + "Contrast with"
cross-references) — plan doc's Task 0 text (lines 80-99) already follows this house style; copy
verbatim, no drift risk (docs, not code, no live structural analog needed beyond format
consistency).

---

### `tests/unit/test_regime_signals_breadth_vol.py` (new test — needs ONE test beyond the plan doc)

**Analog:** `tests/unit/services/test_equity_regime_model_causal.py` (full file, read this session)
— mirror its structure directly, since `breadth_vol.py`'s `compute()` now embeds the exact same
causal-rank and `_tf_window` logic this test file was written to guard.

**Required additional test not in the plan doc's Task 2 test file** (RESEARCH.md Wave 0 Gap,
confirmed as a real gap this session — the plan doc's test file only covers warmup-NaN shape, not
the look-ahead property): mirror `test_vix_pct_rank_causal_property`
(`tests/unit/services/test_equity_regime_model_causal.py:70-121`) — append a large future outlier
value and assert all earlier (non-NaN) ranks are unchanged:
```python
def test_vix_pct_rank_causal_property():
    """Appending a large future value must NOT change earlier ranks."""
    n = 50
    ts_base, close_base = _make_spy_data(n, seed=7)
    ranks_n = _compute_vix_pct_rank(ts_base, close_base, tf="1d", rv_window_days=3, z_window_days=5)
    outlier_ts = ts_base[-1] + timedelta(days=1)
    close_ext = close_base + [close_base[-1] * 100.0]
    ranks_n1 = _compute_vix_pct_rank(ts_base + [outlier_ts], close_ext, tf="1d", rv_window_days=3, z_window_days=5)
    common_idx = ranks_n.dropna().index.intersection(ranks_n1.iloc[:len(ts_base)].dropna().index)
    for ts in common_idx:
        assert abs(ranks_n.loc[ts] - ranks_n1.loc[ts]) < 1e-9
```
Also mirror `test_tf_window_5m`/`test_tf_window_1h`/`test_tf_window_1d`/`test_tf_window_15m`
(same file, lines 45-62) against `breadth_vol.py`'s ported `_tf_window` (or the module it's
imported from, if the planner factors it into a shared location — see Shared Patterns below).

---

### `tests/unit/test_regime_signals_curve_credit.py`, `..._commodity_momentum_ts.py`, `..._fx_dollar_carry.py` (new tests)

**Analog:** plan doc's own Task 3/6/7 test files
(`docs/plans/2026-07-01-cross-sectional-regime-model.md:616-750, 2278-2354, 2503-2561`) — RESEARCH.md
found these complete and correct as written (no drift — new signal modules, no live predecessor to
diff against). Use as-is.

---

### `tests/unit/test_cross_sectional_regime_model.py` (new test)

**Analog:** plan doc's own Task 4 Step 1 test file
(`docs/plans/2026-07-01-cross-sectional-regime-model.md:872-1051`, full file read this session) —
CI-clean (no DB, no network), covers `_parse_group_configs`, `_resolve_group_symbols`, `_bucket`,
`_assign_labels` as pure functions. Complete and correct as written **except** it must be extended
to cover the JSON-parsing gotcha documented above (`_parse_group_configs` receiving an
already-parsed `list` vs. a raw `str`, once the call site normalization lands) — add a test case
exercising both input shapes if `_parse_group_configs` is changed to accept `str | list[dict]`.

**Import + sys.path pattern** (line 878-891, matches every other `tests/unit/*.py` in this repo):
```python
sys.path.insert(0, str(Path(__file__).parents[2]))
from services.cross_sectional_regime_model import (
    _assign_labels, _bucket, _parse_group_configs, _resolve_group_symbols,
)
```

---

### `tests/unit/test_ic_engine_routing.py` (new test)

**Analog:** `tests/unit/test_ic_engine_staleness.py` (read this session) — the established pattern
for testing a pure function lifted directly out of `services/ic_engine.py`, including the
project-root `sys.path` insert convention and direct import from `services.ic_engine`:
```python
from __future__ import annotations
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import AmbiguousRegimeGroupError, _build_symbol_regime_class
```
Test cases per the plan doc's Task 5 Step 1 spec (single-group match, ambiguous multi-match raises
`AmbiguousRegimeGroupError`, zero-match omission, disabled-group exclusion) — plan doc's version is
new code with no drift risk (RESEARCH.md found no issues here).

## Shared Patterns

### D-06 oneshot completion contract
**Source:** `services/equity_regime_model.py:365-397, 603-617` (and every other batch oneshot in
`services/`)
**Apply to:** `services/cross_sectional_regime_model.py`
```python
try:
    init_otel_providers(service_name=_JOB)
except OTelInitError as error:
    _logger.warning("<job>.otel_init_failed", error=str(error))
...
finally:
    JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
    flush_and_shutdown_metrics()
sys.exit(exit_code)
```

### APR config loading (sync, batch services)
**Source:** `services/_batch_utils.py:38-51` (`load_config_service_sync`)
**Apply to:** `services/cross_sectional_regime_model.py`, `services/ic_engine.py`
```python
cfg = _load_config_service(conn)  # populates cfg._cache fully from config_state JOIN config_schema
value = cfg.get_sync("alpha.regime.groups", default)  # no DB I/O, cache-only read
```
**Critical caveat (see migration section above for full detail):** for `value_type='json'` keys,
`get_sync()` returns an already-`json.loads()`-parsed Python object once the key exists in
`config_state` — only the literal `default` argument passed to `get_sync()` is returned unparsed
(for the missing-key case). Every new call site touching `alpha.regime.groups` must handle both
shapes; do not assume it is always a raw string (the plan doc's `_parse_group_configs(raw: str)`
design does, silently, and will break the first time it runs against live seeded config).

### Fail-loud config-authoring error
**Source:** `docs/plans/2026-07-01-cross-sectional-regime-model.md:1689-1742` (`AmbiguousRegimeGroupError`)
**Apply to:** `services/ic_engine.py`'s `_build_symbol_regime_class`
```python
class AmbiguousRegimeGroupError(ValueError):
    """Config-authoring error: fail loud, never silently pick by array order."""
```
Matches CLAUDE.md's "silent wrong answers are worse than loud crashes" mandate — no other
exception-class pattern search was needed since this is new code with an already-correct design.

### Frozen config-at-startup binding
**Source:** `services/ic_engine.py:311-406` (`ICEngineConfig`, `from_apr()`)
**Apply to:** any new `ic_engine.py` config field this phase adds (`regime_groups_json`)
```python
@dataclasses.dataclass(frozen=True)
class ICEngineConfig:
    ...
    new_field: str = "<apr-fallback-default>"  # defaulted, not required — see existing
    # Phase 143/143.1 fields for why: pre-existing direct-constructor test call sites
    # (tests/unit/test_hac_ic_sharpe.py) must not break on field-count growth.
```
Bind once in `from_apr()`, never re-read `config_state` mid-run — the whole point of this
dataclass (per its own docstring) is "no mid-run drift if config_state is updated externally."

### Fresh-connection-per-fetch for long-running reads
**Source:** `services/equity_regime_model.py:286-293, 335-357`
**Apply to:** `services/cross_sectional_regime_model.py`'s per-group/per-TF bar fetches
```python
fresh_conn = psycopg2.connect(dsn)
fresh_conn.autocommit = True  # read-only; no transactions needed
try:
    with fresh_conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
finally:
    fresh_conn.close()
```
Avoids idle-connection termination on multi-minute cross-sectional fetches — same rationale that
drove the `_persist_corpus_results` connection-lifetime restructure in `ic_engine.py` (2026-07-08
incident, 819,538 rows lost to a dead idle connection).

### Exception variable name
**Source:** project-wide convention, CLAUDE.md Key Rules — `except X as error:`, never `as exc:`.
Confirmed already followed in every file read this session (`equity_regime_model.py`,
`ic_engine.py`, the plan doc's own code blocks).

## No Analog Found

None. Every file in this phase's File Map has at least a role-match analog — this phase is an
extension/generalization of an already-established oneshot regime-labeling family
(`equity_regime_model.py` → `cross_sectional_regime_model.py`) plus routing changes to an
already-well-understood file (`ic_engine.py`), not new architectural territory. The two genuinely
"new math" files (`curve_credit.py`, and the disabled `commodity_momentum_ts.py`/`fx_dollar_carry.py`)
have no domain-specific precedent but do have a full structural analog once `breadth_vol.py` is
written (same `compute()`/`build_tiers()`/`PROB_KEYS` contract) — not severe enough to list as "no
analog," just flagged inline above as new math within an established shape.

## Metadata

**Analog search scope:** `services/` (all `*regime*`, `*ic_engine*` files), `src/intelligence/`,
`src/core/ai/registry.py`, `src/config/config_service.py`, `src/intelligence/trading/ofi_continuation.py`,
`production/migrations/` (last 15 + migrations 174/182 specifically), `tests/unit/` (all
`test_ic_engine_*` and `test_equity_regime_model_*` files), `scripts/ops/corpus/ops_corpus_pipeline_run.sh`.
**Files scanned:** ~25 (full reads: `equity_regime_model.py`, `_batch_utils.py`,
`test_equity_regime_model_causal.py`, migrations 174/182/228, plan doc File Map + Tasks 0/1/2/4/5
sections; targeted reads: `ic_engine.py` at 6 distinct line ranges, `config_service.py`,
`ofi_continuation.py`, `ops_corpus_pipeline_run.sh`, `test_ic_engine_staleness.py`).
**Pattern extraction date:** 2026-07-12

---

*Phase: 144-Cross-Sectional Regime Model (`regime_group`)*
*Patterns mapped: 2026-07-12*
