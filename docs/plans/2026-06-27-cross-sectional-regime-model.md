# Cross-Sectional Regime Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Supersedes:** `docs/plans/2026-06-27-rates-regime-model.md` (rates-specific — discarded in favor of this generic framework).

**Goal:** Replace `equity_regime_model.py` with a single generic `cross_sectional_regime_model.py` that dispatches to pluggable signal modules, where each module defines a peer group (by instrument tag filter) and a regime signal (by computation type), so adding a new group (rates, commodities, FX) requires one signal module and one APR config update — no service code changes.

**Architecture:** Groups are defined as JSON in APR (`alpha.regime.groups`): each entry declares a `tag_filter` (resolves peer members from `instrument_tags` at startup), a `signal_type` (maps to a signal module in `src/intelligence/regime_signals/`), and a `params_prefix` (APR namespace for that signal's thresholds). Signal modules are pure functions: they receive pre-fetched peer bars and return two aligned signal series. A generic `_assign_labels` function in the service applies threshold-based bucketing to produce `{tier1}_{tier2}` labels. Results are written to `market_regimes` (column renamed from `asset_class` to `regime_group`). `ic_engine` routing is updated to map symbols to their group name using the same groups JSON.

**Tech Stack:** Python, psycopg2, pandas, numpy, structlog, APR (config_state/config_schema), TimescaleDB

## Global Constraints

- Exception variable name is `error` — `except X as error:`
- All timestamps UTC — `datetime.now(UTC)` only
- No hardcoded numeric constants — all thresholds via APR
- D-06 oneshot: emit `job_completed_total{job, status}` at exit; `job` matches systemd unit `%n` suffix (kebab-case)
- psycopg2 JSONB requires `json.dumps()` before passing
- All DB queries use `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent`
- Unit tests: `tests/unit/`, CI-clean (no live DB, no network), run via `.venv/bin/pytest tests/unit/ -q`
- No `ProcessPoolExecutor` in the new service — label assignment is vectorized numpy and needs no subprocess overhead; the DB fetch is the bottleneck and is serial by design

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `production/migrations/179_regime_group.sql` | Create | Rename `market_regimes.asset_class` → `regime_group`; add `alpha.regime.groups` APR key; add `alpha.rates_regime.*` APR keys |
| `src/intelligence/regime_signals/__init__.py` | Create | Signal module registry: `REGISTRY: dict[str, module]` |
| `src/intelligence/regime_signals/breadth_vol.py` | Create | Equity signal: SPY realized-vol pct-rank × cross-sectional 200MA breadth. Logic extracted from `equity_regime_model.py`. |
| `src/intelligence/regime_signals/curve_credit.py` | Create | Rates signal: TLT-SHY curve spread z-score × HYG-LQD credit spread z-score |
| `services/cross_sectional_regime_model.py` | Create | Generic dispatcher: loads group config from APR, fetches bars, calls signal modules, assigns labels, writes `market_regimes` |
| `services/equity_regime_model.py` | Modify | Add deprecation header; no functional changes (kept for emergency rollback) |
| `services/ic_engine.py` | Modify | Rename all `asset_class='equity'` → `regime_group=%(regime_group)s`; add `_build_symbol_regime_class(tags_by_symbol, group_configs)`; update `_assert_prerequisites`, `mr_dict` loading, `_compute_cross_sectional_tf`, cross-sectional pass loop |
| `scripts/ops/corpus/ops_corpus_pipeline_run.sh` | Modify | Replace `equity_regime_model` step with `cross_sectional_regime_model`; update 6→7 step count |
| `src/intelligence/regime_signals/commodity_momentum_ts.py` | Create | Commodity signal: cross-sectional momentum z-score × term structure proxy (contango/backwardation). Used by commodity_energy, commodity_metals, commodity_agri groups. |
| `src/intelligence/regime_signals/fx_dollar_carry.py` | Create | FX signal: dollar trend z-score (UUP momentum) × carry environment (risk-on/off proxy via HYG momentum). |
| `tests/unit/test_regime_signals_breadth_vol.py` | Create | Unit tests for breadth_vol signal module (no DB) |
| `tests/unit/test_regime_signals_curve_credit.py` | Create | Unit tests for curve_credit signal module (no DB) |
| `tests/unit/test_regime_signals_commodity_momentum_ts.py` | Create | Unit tests for commodity_momentum_ts signal module (no DB) |
| `tests/unit/test_regime_signals_fx_dollar_carry.py` | Create | Unit tests for fx_dollar_carry signal module (no DB) |
| `tests/unit/test_cross_sectional_regime_model.py` | Create | Unit tests for group config loading, label assignment worker, tier bucketing |
| `tests/unit/test_ic_engine_routing.py` | Create | Unit tests for `_build_symbol_regime_class` routing function |

---

## Task 0: Glossary — Add `regime_group`

**Files:**
- Modify: `docs/foundation/glossary.md`

- [ ] **Step 1: Add glossary entry**

In `docs/foundation/glossary.md`, under the appropriate section (regime / market structure), add:

```
**regime_group** — A named peer group whose regime signal is computed cross-sectionally.
Each group declares a tag_filter (resolves peer symbols), a signal_type (breadth_vol,
curve_credit, etc.), and a params_prefix (APR namespace). Results are written to
market_regimes.regime_group. Defined in APR key alpha.regime.groups.
Examples: "equity" (SPY-like ETFs), "rates" (duration ETFs + credit).
Contrast: feature_vectors.regime stores per-symbol HMM labels; regime_group is market-wide.
```

- [ ] **Step 2: Commit**

```bash
git add docs/foundation/glossary.md
git commit -m "docs(glossary): add regime_group definition"
```

---

## Task 1: Migration 179 — Schema Rename + APR Keys

**Files:**
- Create: `production/migrations/179_regime_group.sql`

**Interfaces:**
- Produces: `market_regimes.regime_group` column (renamed from `asset_class`); APR keys `alpha.regime.groups`, `alpha.rates_regime.*`
- Consumed by: all subsequent tasks

**Note:** After this migration, `equity_regime_model.py` and `ic_engine.py` will fail with column-not-found errors on `asset_class`. This is expected — Task 4 and Task 5 fix them. Work on a feature branch.

- [ ] **Step 1: Write the migration**

```sql
-- production/migrations/179_regime_group.sql
-- Migration 179: Rename market_regimes.asset_class → regime_group.
--
-- Rationale: 'asset_class' was an implementation assumption encoding a specific taxonomy.
-- 'regime_group' is the correct abstraction: any named peer group with a shared regime signal.
-- Adds APR key alpha.regime.groups (JSON array) and alpha.rates_regime.* keys for rates signal.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Rename column
-- ---------------------------------------------------------------------------

ALTER TABLE market_regimes RENAME COLUMN asset_class TO regime_group;

ALTER INDEX market_regimes_equity_tf_ts RENAME TO market_regimes_regime_group_tf_ts;

COMMENT ON TABLE market_regimes IS
    'Cross-sectional regime label per (regime_group, tf, ts). '
    'One row per (regime_group, tf, bar_timestamp) — not per symbol. '
    'IC engine joins here for regime segmentation when the group is enabled in alpha.regime.groups. '
    'Per-symbol HMM labels remain in feature_vectors.regime for per-symbol IC.';

COMMENT ON COLUMN market_regimes.regime_group IS
    'Named peer group whose regime is being labeled. '
    'Examples: equity, rates, commodities. '
    'Matches the "name" field in the alpha.regime.groups APR JSON config.';

-- ---------------------------------------------------------------------------
-- 2. alpha.regime.groups JSON config
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, description)
VALUES (
    'alpha.regime.groups',
    'json',
    '[initial_estimate] JSON array of regime group configs. Each entry: '
    '{"name": str, "tag_filter": [str], "signal_type": str, "params_prefix": str, "enabled": bool}. '
    'tag_filter patterns match instrument_tags.tag values (prefix match, trailing * stripped). '
    'signal_type maps to a module in src/intelligence/regime_signals/. '
    'params_prefix is the APR namespace for that signal''s thresholds. '
    'Groups are checked in order; first matching group wins for symbol routing. '
    'Symbols with no matching group default to the first enabled group named "equity".'
) ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES (
    'alpha.regime.groups',
    '[{"name":"equity","tag_filter":["eq_*","intl_*"],"signal_type":"breadth_vol","params_prefix":"alpha.equity_regime","enabled":true},{"name":"rates","tag_filter":["fi_*"],"signal_type":"curve_credit","params_prefix":"alpha.rates_regime","enabled":true},{"name":"commodity_energy","tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_energy_regime","enabled":false},{"name":"commodity_metals","tag_filter":["commodity_metals_precious","commodity_metals_industrial"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_metals_regime","enabled":false},{"name":"commodity_agri","tag_filter":["commodity_agri"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_agri_regime","enabled":false},{"name":"fx","tag_filter":["fx_*"],"signal_type":"fx_dollar_carry","params_prefix":"alpha.fx_regime","enabled":false}]',
    1
) ON CONFLICT (config_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. alpha.rates_regime.* APR keys
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, min_value, max_value, description)
VALUES
    ('alpha.rates_regime.curve_window',
     'int', 5, 500,
     '[conventional] Rolling window (bars) for TLT-SHY log-return spread z-score normalization. '
     'Mean and std both computed over this window. Warmup = 2*window bars.'),
    ('alpha.rates_regime.credit_window',
     'int', 5, 500,
     '[conventional] Rolling window (bars) for HYG-LQD log-return spread z-score normalization.'),
    ('alpha.rates_regime.steep_threshold',
     'float', 0.0, 5.0,
     '[conventional] Curve z-score above which regime tier is "steep" (long-end outperforms). '
     'Candidate ML learning target.'),
    ('alpha.rates_regime.inverted_threshold',
     'float', -5.0, 0.0,
     '[conventional] Curve z-score below which regime tier is "inverted" (short-end outperforms). '
     'Candidate ML learning target.'),
    ('alpha.rates_regime.credit_tight_threshold',
     'float', -5.0, 5.0,
     '[conventional] Credit z-score above which regime tier is "tight" (HY outperforms IG). '
     'Candidate ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.rates_regime.curve_window',           '60',   1),
    ('alpha.rates_regime.credit_window',          '60',   1),
    ('alpha.rates_regime.steep_threshold',        '0.5',  1),
    ('alpha.rates_regime.inverted_threshold',     '-0.5', 1),
    ('alpha.rates_regime.credit_tight_threshold', '0.0',  1)
ON CONFLICT (config_key) DO NOTHING;

-- Rename equity_regime APR namespace from alpha.regime.* to alpha.equity_regime.*
-- The old keys (alpha.regime.vix_low_pct etc.) remain for backward compat but are now
-- read via params_prefix='alpha.equity_regime' in the groups config, so we add aliased keys.
INSERT INTO config_schema (config_key, value_type, min_value, max_value, description)
VALUES
    ('alpha.equity_regime.vix_low_pct',
     'float', 0.0, 1.0,
     '[initial_estimate] VIX percentile below which vol regime is "low". '
     'Same calibration as alpha.regime.vix_low_pct. Candidate ML learning target.'),
    ('alpha.equity_regime.vix_high_pct',
     'float', 0.0, 1.0,
     '[initial_estimate] VIX percentile above which vol regime is "high". '
     'Candidate ML learning target.'),
    ('alpha.equity_regime.breadth_bear',
     'float', 0.0, 1.0,
     '[initial_estimate] Fraction of ETFs above 200MA below which breadth is "bear". '
     'Candidate ML learning target.'),
    ('alpha.equity_regime.breadth_bull',
     'float', 0.0, 1.0,
     '[initial_estimate] Fraction of ETFs above 200MA above which breadth is "bull". '
     'Candidate ML learning target.'),
    ('alpha.equity_regime.realized_vol_window',
     'int', 5, 500,
     '[conventional] Rolling window (bars) for SPY realized-vol computation (log-return std). '
     'Warmup requires realized_vol_window + vix_z_window bars before any valid signal.'),
    ('alpha.equity_regime.vix_z_window',
     'int', 20, 1000,
     '[conventional] Rolling window (bars) for VIX-proxy z-score normalization (mean and std). '
     '252 = 1 trading year. Candidate ML learning target.'),
    ('alpha.equity_regime.ma_window',
     'int', 20, 500,
     '[conventional] Moving-average window (bars) for 200MA breadth signal. '
     '200 = conventional long-term MA. Candidate ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.equity_regime.vix_low_pct',            '0.33', 1),
    ('alpha.equity_regime.vix_high_pct',           '0.67', 1),
    ('alpha.equity_regime.breadth_bear',           '0.40', 1),
    ('alpha.equity_regime.breadth_bull',           '0.60', 1),
    ('alpha.equity_regime.realized_vol_window',    '20',   1),
    ('alpha.equity_regime.vix_z_window',           '252',  1),
    ('alpha.equity_regime.ma_window',              '200',  1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Apply the migration**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
    -f production/migrations/179_regime_group.sql
```

Expected: no errors. `ALTER TABLE`, `ALTER INDEX`, `INSERT 0 1`, etc.

- [ ] **Step 3: Verify schema**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "\d market_regimes"
```

Expected: column named `regime_group` (not `asset_class`). Primary key on `(regime_group, tf, ts)`.

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT config_key, config_value FROM config_state
   WHERE config_key LIKE 'alpha.regime.groups' OR config_key LIKE 'alpha.rates_regime.%' OR config_key LIKE 'alpha.equity_regime.%'
   ORDER BY config_key;"
```

Expected: 14 rows — 1 groups key + 5 rates keys + 7 equity keys + 1 placeholder (commodity/FX APR keys added in Tasks 6–7).

- [ ] **Step 4: Verify existing data preserved**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT regime_group, COUNT(*) FROM market_regimes GROUP BY 1;"
```

Expected: `equity | <n>` rows unchanged. Column rename is transparent to data.

- [ ] **Step 5: Commit**

```bash
git add production/migrations/179_regime_group.sql
git commit -m "feat(migrations): rename market_regimes.asset_class to regime_group; add rates_regime + equity_regime APR keys (migration 179)"
```

---

## Task 2: breadth_vol Signal Module

**Files:**
- Create: `src/intelligence/regime_signals/__init__.py`
- Create: `src/intelligence/regime_signals/breadth_vol.py`
- Create: `tests/unit/test_regime_signals_breadth_vol.py`

**Interfaces:**
- Consumes: `ref_bars: dict[str, pd.DataFrame]` (symbol → df with columns `timestamp`, `close`, sorted ascending); `params: dict[str, Any]` (APR values keyed without prefix, e.g. `"vix_low_pct"`, `"vix_high_pct"`, `"breadth_bear"`, `"breadth_bull"`)
- Produces:
  - `compute(ref_bars, params) -> tuple[pd.Series, pd.Series] | None` — (vix_pct_rank_series, breadth_fraction_series), both indexed by timestamp; NaN for warmup bars
  - `build_tiers(params) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]` — ordered threshold lists for generic label worker
  - `PROB_KEYS: tuple[str, str]` — `("vix_pct", "breadth_frac")`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_regime_signals_breadth_vol.py
"""Unit tests for breadth_vol signal module. CI-clean: no DB, no network."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.intelligence.regime_signals.breadth_vol import PROB_KEYS, build_tiers, compute

_UTC = pd.Timestamp("2020-01-01", tz="UTC")


def _make_bars(symbol: str, closes: list[float]) -> pd.DataFrame:
    ts = pd.date_range(_UTC, periods=len(closes), freq="1D")
    return pd.DataFrame({"timestamp": ts, "close": closes})


def _rising_bars(n: int, start: float = 100.0) -> list[float]:
    return [start + i * 0.1 for i in range(n)]


def _flat_bars(n: int, val: float = 100.0) -> list[float]:
    return [val] * n


class TestComputeReturnShape:
    def test_returns_two_series(self):
        n = 600
        ref_bars = {
            "SPY": _make_bars("SPY", _rising_bars(n)),
            "QQQ": _make_bars("QQQ", _rising_bars(n, 50.0)),
        }
        params = {
            "vix_low_pct": 0.33,
            "vix_high_pct": 0.67,
            "breadth_bear": 0.40,
            "breadth_bull": 0.60,
            "realized_vol_window": 20,
            "vix_z_window": 252,
            "ma_window": 200,
        }
        result = compute(ref_bars, params)
        assert result is not None
        s1, s2 = result
        assert isinstance(s1, pd.Series)
        assert isinstance(s2, pd.Series)
        assert len(s1) == n
        assert len(s2) == n

    def test_returns_none_when_spy_missing(self):
        ref_bars = {"QQQ": _make_bars("QQQ", _rising_bars(300))}
        params = {"vix_low_pct": 0.33, "vix_high_pct": 0.67, "breadth_bear": 0.40, "breadth_bull": 0.60, "realized_vol_window": 20, "vix_z_window": 252, "ma_window": 200}
        result = compute(ref_bars, params)
        assert result is None

    def test_warmup_bars_are_nan(self):
        n = 600
        ref_bars = {"SPY": _make_bars("SPY", _rising_bars(n))}
        params = {"vix_low_pct": 0.33, "vix_high_pct": 0.67, "breadth_bear": 0.40, "breadth_bull": 0.60, "realized_vol_window": 20, "vix_z_window": 252, "ma_window": 200}
        s1, s2 = compute(ref_bars, params)
        # VIX series warmup = realized_vol_window (20) + vix_z_window (252) - 1 = 271 bars
        assert s1.iloc[:271].isna().all()
        assert s1.iloc[272:].notna().any()


class TestBreadthSignal:
    def test_all_above_200ma_returns_near_one(self):
        # Strongly rising series: all symbols above their 200MA after warmup
        n = 500
        closes = [100.0 + i for i in range(n)]  # steadily rising
        ref_bars = {
            "SPY": _make_bars("SPY", closes),
            "QQQ": _make_bars("QQQ", closes),
        }
        params = {"vix_low_pct": 0.33, "vix_high_pct": 0.67, "breadth_bear": 0.40, "breadth_bull": 0.60, "realized_vol_window": 20, "vix_z_window": 252, "ma_window": 200}
        _, breadth = compute(ref_bars, params)
        valid = breadth.dropna()
        assert (valid > 0.9).all(), f"Expected breadth near 1.0, got min={valid.min():.2f}"

    def test_all_below_200ma_returns_near_zero(self):
        # Strongly falling series: all symbols below their 200MA after warmup
        n = 500
        closes = [500.0 - i for i in range(n)]  # steadily falling
        ref_bars = {
            "SPY": _make_bars("SPY", closes),
            "QQQ": _make_bars("QQQ", closes),
        }
        params = {"vix_low_pct": 0.33, "vix_high_pct": 0.67, "breadth_bear": 0.40, "breadth_bull": 0.60, "realized_vol_window": 20, "vix_z_window": 252, "ma_window": 200}
        _, breadth = compute(ref_bars, params)
        valid = breadth.dropna()
        assert (valid < 0.1).all(), f"Expected breadth near 0.0, got max={valid.max():.2f}"


class TestBuildTiers:
    def test_returns_two_tier_lists(self):
        params = {"vix_low_pct": 0.33, "vix_high_pct": 0.67, "breadth_bear": 0.40, "breadth_bull": 0.60, "realized_vol_window": 20, "vix_z_window": 252, "ma_window": 200}
        t1, t2 = build_tiers(params)
        assert len(t1) == 3  # low, mid, high
        assert len(t2) == 3  # bear, neutral, bull

    def test_tier_names(self):
        params = {"vix_low_pct": 0.33, "vix_high_pct": 0.67, "breadth_bear": 0.40, "breadth_bull": 0.60, "realized_vol_window": 20, "vix_z_window": 252, "ma_window": 200}
        t1, t2 = build_tiers(params)
        assert [n for n, _ in t1] == ["low", "mid", "high"]
        assert [n for n, _ in t2] == ["bear", "neutral", "bull"]

    def test_last_tier_upper_bound_is_inf(self):
        params = {"vix_low_pct": 0.33, "vix_high_pct": 0.67, "breadth_bear": 0.40, "breadth_bull": 0.60, "realized_vol_window": 20, "vix_z_window": 252, "ma_window": 200}
        t1, t2 = build_tiers(params)
        assert t1[-1][1] == float("inf")
        assert t2[-1][1] == float("inf")


class TestProbKeys:
    def test_prob_keys_are_correct(self):
        assert PROB_KEYS == ("vix_pct", "breadth_frac")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_regime_signals_breadth_vol.py -v 2>&1 | head -15
```

Expected: `ImportError: No module named 'src.intelligence.regime_signals'`

- [ ] **Step 3: Create registry `__init__.py`**

```python
# src/intelligence/regime_signals/__init__.py
"""Regime signal module registry.

Each module in this package must implement:
  - compute(ref_bars, params) -> tuple[pd.Series, pd.Series] | None
  - build_tiers(params) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]
  - PROB_KEYS: tuple[str, str]

ref_bars: dict[str, pd.DataFrame] — symbol -> df with columns [timestamp, close], sorted ascending.
params: dict[str, Any] — APR values for this signal, keyed WITHOUT the params_prefix.
compute() returns (signal1_series, signal2_series) indexed by timestamp, NaN for warmup.
build_tiers() returns (tiers1, tiers2): each list is [(tier_name, upper_bound), ...] sorted
  ascending by upper_bound; the last entry's upper_bound must be float("inf").
"""
from src.intelligence.regime_signals import breadth_vol, curve_credit

REGISTRY: dict[str, object] = {
    "breadth_vol": breadth_vol,
    "curve_credit": curve_credit,
}
```

- [ ] **Step 4: Write `breadth_vol.py`**

```python
# src/intelligence/regime_signals/breadth_vol.py
"""breadth_vol — Equity cross-sectional regime signal.

Signal 1 (vix_pct): SPY realized-vol z-score percentile rank over full history.
  Low vol → "low". High vol → "high". Middle → "mid".

Signal 2 (breadth_frac): Fraction of ref_bars symbols with close > 200MA.
  Majority above → "bull". Majority below → "bear". Mixed → "neutral".

Label format: {vix_tier}_{breadth_tier}  e.g. "low_bull", "high_bear", "mid_neutral".
9 possible labels (3 × 3).

Logic extracted from services/equity_regime_model.py — no DB calls here.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

PROB_KEYS: tuple[str, str] = ("vix_pct", "breadth_frac")


def compute(
    ref_bars: dict[str, pd.DataFrame],
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series] | None:
    """Compute (vix_pct_rank, breadth_fraction) series from pre-fetched peer bars.

    SPY must be present in ref_bars (used for realized-vol VIX proxy).
    All other symbols contribute to the breadth signal.

    Returns None if SPY bars are missing or insufficient for warmup.
    Both returned series are indexed by timestamp and share the same index.
    NaN values indicate warmup bars — caller drops them before dispatch.
    """
    if "SPY" not in ref_bars:
        return None

    realized_vol_window = int(params.get("realized_vol_window", 20))
    vix_z_window = int(params.get("vix_z_window", 252))
    ma_window = int(params.get("ma_window", 200))

    spy_df = ref_bars["SPY"].set_index("timestamp").sort_index()
    spy_close = spy_df["close"].astype(float)

    if len(spy_close) < realized_vol_window + vix_z_window:
        return None

    vix_pct = _compute_vix_pct_rank(spy_close, realized_vol_window, vix_z_window)
    breadth = _compute_breadth(ref_bars, ma_window)

    return vix_pct, breadth.reindex(vix_pct.index)


def build_tiers(params: dict[str, Any]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return threshold tier lists for the generic label worker.

    tiers1: VIX percentile buckets.
    tiers2: breadth fraction buckets.
    Each list: [(tier_name, upper_bound), ...] sorted ascending; last upper_bound = inf.
    """
    vix_low = float(params.get("vix_low_pct", 0.33))
    vix_high = float(params.get("vix_high_pct", 0.67))
    bread_bear = float(params.get("breadth_bear", 0.40))
    bread_bull = float(params.get("breadth_bull", 0.60))
    return (
        [("low", vix_low), ("mid", vix_high), ("high", float("inf"))],
        [("bear", bread_bear), ("neutral", bread_bull), ("bull", float("inf"))],
    )


def _compute_vix_pct_rank(spy_close: pd.Series, realized_vol_window: int, vix_z_window: int) -> pd.Series:
    log_ret = np.log(spy_close / spy_close.shift(1))
    realized_vol = log_ret.rolling(window=realized_vol_window, min_periods=realized_vol_window).std()
    rv_mean = realized_vol.rolling(window=vix_z_window, min_periods=vix_z_window).mean()
    rv_std = realized_vol.rolling(window=vix_z_window, min_periods=vix_z_window).std()
    vix_z = (realized_vol - rv_mean) / rv_std.where(rv_std > 1e-10)
    return vix_z.rank(pct=True, na_option="keep")


def _compute_breadth(ref_bars: dict[str, pd.DataFrame], ma_window: int) -> pd.Series:
    """Fraction of ref_bars symbols with close > MA, per timestamp."""
    above_ma_cols: list[pd.Series] = []
    for sym, df in ref_bars.items():
        s = df.set_index("timestamp")["close"].astype(float).sort_index()
        if len(s) < ma_window:
            continue
        ma = s.rolling(window=ma_window, min_periods=ma_window).mean()
        above = (s > ma).where(ma.notna()).astype(float)
        above_ma_cols.append(above.rename(sym))
    if not above_ma_cols:
        return pd.Series(dtype=float, name="breadth")
    return pd.concat(above_ma_cols, axis=1).mean(axis=1, skipna=True).rename("breadth")
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_regime_signals_breadth_vol.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/regime_signals/__init__.py src/intelligence/regime_signals/breadth_vol.py \
    tests/unit/test_regime_signals_breadth_vol.py
git commit -m "feat(regime-signals): add breadth_vol signal module and registry"
```

---

## Task 3: curve_credit Signal Module

**Files:**
- Create: `src/intelligence/regime_signals/curve_credit.py`
- Create: `tests/unit/test_regime_signals_curve_credit.py`

**Interfaces:**
- Consumes: `ref_bars` must contain TLT, SHY, HYG, LQD; `params` keys: `curve_window`, `credit_window`, `steep_threshold`, `inverted_threshold`, `credit_tight_threshold`
- Produces:
  - `compute(ref_bars, params) -> tuple[pd.Series, pd.Series] | None` — (curve_z_series, credit_z_series)
  - `build_tiers(params) -> tuple[list[tuple], list[tuple]]` — (3-tier curve, 2-tier credit)
  - `PROB_KEYS: tuple[str, str]` — `("curve_z", "credit_z")`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_regime_signals_curve_credit.py
"""Unit tests for curve_credit signal module. CI-clean: no DB, no network."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.intelligence.regime_signals.curve_credit import PROB_KEYS, build_tiers, compute

_UTC = pd.Timestamp("2020-01-01", tz="UTC")

_REQUIRED_SYMBOLS = ["TLT", "SHY", "HYG", "LQD"]


def _make_bars(closes: list[float]) -> pd.DataFrame:
    ts = pd.date_range(_UTC, periods=len(closes), freq="1D")
    return pd.DataFrame({"timestamp": ts, "close": closes})


def _rising(n: int, start: float = 100.0) -> list[float]:
    return [start + i * 0.01 for i in range(n)]


def _falling(n: int, start: float = 100.0) -> list[float]:
    return [start - i * 0.01 for i in range(n)]


def _default_params() -> dict:
    return {
        "curve_window": 20,
        "credit_window": 20,
        "steep_threshold": 0.5,
        "inverted_threshold": -0.5,
        "credit_tight_threshold": 0.0,
    }


class TestComputeBasic:
    def test_returns_none_when_symbol_missing(self):
        ref_bars = {s: _make_bars(_rising(200)) for s in ["TLT", "SHY", "HYG"]}  # LQD missing
        result = compute(ref_bars, _default_params())
        assert result is None

    def test_returns_two_aligned_series(self):
        n = 200
        ref_bars = {s: _make_bars(_rising(n)) for s in _REQUIRED_SYMBOLS}
        result = compute(ref_bars, _default_params())
        assert result is not None
        s1, s2 = result
        assert len(s1) == len(s2)
        assert isinstance(s1, pd.Series)
        assert isinstance(s2, pd.Series)

    def test_warmup_bars_are_nan(self):
        n = 300
        ref_bars = {s: _make_bars(_rising(n)) for s in _REQUIRED_SYMBOLS}
        s1, s2 = compute(ref_bars, _default_params())
        # warmup = 2 * window - 1 = 39 bars (window=20)
        assert s1.iloc[:39].isna().all()


class TestSignalDirection:
    def test_rising_tlt_falling_shy_positive_curve_z(self):
        """TLT rising faster than SHY → positive spread → positive curve_z at end."""
        n = 300
        ref_bars = {
            "TLT": _make_bars(_rising(n, 100.0)),
            "SHY": _make_bars(_falling(n, 100.0)),
            "HYG": _make_bars(_rising(n, 80.0)),
            "LQD": _make_bars(_rising(n, 80.0)),
        }
        s1, _ = compute(ref_bars, _default_params())
        valid = s1.dropna()
        assert valid.iloc[-1] > 0, f"Expected positive curve_z, got {valid.iloc[-1]:.4f}"

    def test_hyg_rising_lqd_falling_positive_credit_z(self):
        """HYG outperforming LQD → positive credit spread → positive credit_z (tight)."""
        n = 300
        ref_bars = {
            "TLT": _make_bars(_rising(n, 100.0)),
            "SHY": _make_bars(_rising(n, 100.0)),
            "HYG": _make_bars(_rising(n, 80.0)),
            "LQD": _make_bars(_falling(n, 80.0)),
        }
        _, s2 = compute(ref_bars, _default_params())
        valid = s2.dropna()
        assert valid.iloc[-1] > 0, f"Expected positive credit_z, got {valid.iloc[-1]:.4f}"


class TestBuildTiers:
    def test_curve_has_three_tiers(self):
        t1, t2 = build_tiers(_default_params())
        assert len(t1) == 3
        assert [n for n, _ in t1] == ["inverted", "flat", "steep"]

    def test_credit_has_two_tiers(self):
        t1, t2 = build_tiers(_default_params())
        assert len(t2) == 2
        assert [n for n, _ in t2] == ["wide", "tight"]

    def test_last_upper_bounds_are_inf(self):
        t1, t2 = build_tiers(_default_params())
        assert t1[-1][1] == float("inf")
        assert t2[-1][1] == float("inf")

    def test_thresholds_from_params(self):
        params = {**_default_params(), "steep_threshold": 1.0, "inverted_threshold": -1.0}
        t1, _ = build_tiers(params)
        assert t1[0][1] == -1.0   # inverted upper bound
        assert t1[1][1] == 1.0    # flat upper bound


class TestProbKeys:
    def test_prob_keys(self):
        assert PROB_KEYS == ("curve_z", "credit_z")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_regime_signals_curve_credit.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'compute' from 'src.intelligence.regime_signals.curve_credit'`

- [ ] **Step 3: Write `curve_credit.py`**

```python
# src/intelligence/regime_signals/curve_credit.py
"""curve_credit — Rates cross-sectional regime signal.

Signal 1 (curve_z): TLT log-return minus SHY log-return, rolling z-score.
  Positive → long-end outperforms (curve steepening / rates falling) → "steep".
  Negative → short-end outperforms (curve inverted / rates rising) → "inverted".
  Neither → "flat".

Signal 2 (credit_z): HYG log-return minus LQD log-return, rolling z-score.
  Positive → HY outperforms IG (spreads tightening, risk-on) → "tight".
  Negative → IG outperforms HY (spreads widening, risk-off) → "wide".

Label format: {curve_tier}_{credit_tier}  e.g. "steep_tight", "inverted_wide".
6 possible labels (3 × 2).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

PROB_KEYS: tuple[str, str] = ("curve_z", "credit_z")

_REQUIRED_SYMBOLS = ("TLT", "SHY", "HYG", "LQD")


def compute(
    ref_bars: dict[str, pd.DataFrame],
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series] | None:
    """Compute (curve_z, credit_z) series from pre-fetched peer bars.

    TLT, SHY, HYG, LQD must all be present in ref_bars.
    Returns None if any required symbol is missing.
    Both returned series indexed by timestamp. NaN for warmup bars.
    """
    for sym in _REQUIRED_SYMBOLS:
        if sym not in ref_bars:
            return None

    curve_window = int(params.get("curve_window", 60))
    credit_window = int(params.get("credit_window", 60))

    curve_spread = _log_return_spread(ref_bars["TLT"], ref_bars["SHY"])
    credit_spread = _log_return_spread(ref_bars["HYG"], ref_bars["LQD"])

    curve_z = _rolling_z(curve_spread, curve_window)
    credit_z = _rolling_z(credit_spread, credit_window)

    combined_index = curve_z.index.intersection(credit_z.index)
    return curve_z.reindex(combined_index), credit_z.reindex(combined_index)


def build_tiers(params: dict[str, Any]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return threshold tier lists for the generic label worker.

    tiers1: curve z-score buckets (3 tiers: inverted, flat, steep).
    tiers2: credit z-score buckets (2 tiers: wide, tight).
    """
    inverted = float(params.get("inverted_threshold", -0.5))
    steep = float(params.get("steep_threshold", 0.5))
    tight = float(params.get("credit_tight_threshold", 0.0))
    return (
        [("inverted", inverted), ("flat", steep), ("steep", float("inf"))],
        [("wide", tight), ("tight", float("inf"))],
    )


def _log_return_spread(df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.Series:
    s_a = df_a.set_index("timestamp")["close"].astype(float).sort_index()
    s_b = df_b.set_index("timestamp")["close"].astype(float).sort_index()
    lr_a = np.log(s_a / s_a.shift(1))
    lr_b = np.log(s_b / s_b.shift(1))
    aligned = pd.concat([lr_a.rename("a"), lr_b.rename("b")], axis=1).dropna()
    return (aligned["a"] - aligned["b"]).rename("spread")


def _rolling_z(spread: pd.Series, window: int) -> pd.Series:
    mean = spread.rolling(window=window, min_periods=window).mean()
    std = spread.rolling(window=window, min_periods=window).std()
    return (spread - mean) / std.where(std > 1e-10)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_regime_signals_curve_credit.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/regime_signals/curve_credit.py tests/unit/test_regime_signals_curve_credit.py
git commit -m "feat(regime-signals): add curve_credit signal module for rates regime"
```

---

## Task 4: cross_sectional_regime_model.py

**Files:**
- Create: `services/cross_sectional_regime_model.py`
- Create: `tests/unit/test_cross_sectional_regime_model.py`

**Interfaces:**
- Consumes: `market_data_ohlcv` (bars), `instrument_tags` (peer group membership), `config_state` (group configs + signal params), `src/intelligence/regime_signals/REGISTRY`
- Produces: rows in `market_regimes(regime_group, tf, ts, regime_label, regime_prob_vector)`
- `_assign_labels(group_name, tf, ts_arr, sig1_arr, sig2_arr, tiers1, tiers2, prob_keys) -> list[tuple]` — pure function, exported for tests

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_cross_sectional_regime_model.py
"""Unit tests for cross_sectional_regime_model. CI-clean: no DB, no network."""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from services.cross_sectional_regime_model import (
    _assign_labels,
    _bucket,
    _parse_group_configs,
    _resolve_group_symbols,
)

_UTC = datetime.timezone.utc
_TS = datetime.datetime(2024, 1, 15, tzinfo=_UTC)


class TestParseGroupConfigs:
    def test_parses_valid_json(self):
        raw = json.dumps([
            {"name": "equity", "tag_filter": ["eq_*", "intl_*"], "signal_type": "breadth_vol",
             "params_prefix": "alpha.equity_regime", "enabled": True},
            {"name": "rates", "tag_filter": ["fi_*"], "signal_type": "curve_credit",
             "params_prefix": "alpha.rates_regime", "enabled": True},
        ])
        configs = _parse_group_configs(raw)
        assert len(configs) == 2
        assert configs[0]["name"] == "equity"
        assert configs[1]["name"] == "rates"

    def test_filters_disabled_groups(self):
        raw = json.dumps([
            {"name": "equity", "tag_filter": ["eq_*"], "signal_type": "breadth_vol",
             "params_prefix": "alpha.equity_regime", "enabled": True},
            {"name": "rates", "tag_filter": ["fi_*"], "signal_type": "curve_credit",
             "params_prefix": "alpha.rates_regime", "enabled": False},
        ])
        configs = _parse_group_configs(raw)
        assert len(configs) == 1
        assert configs[0]["name"] == "equity"

    def test_empty_json_returns_empty(self):
        assert _parse_group_configs("[]") == []

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="alpha.regime.groups"):
            _parse_group_configs("not json")


class TestResolveGroupSymbols:
    def test_eq_filter_matches_eq_prefixed_tags(self):
        tags_by_symbol = {
            "SPY": {"eq_large_cap", "eq_blend"},
            "TLT": {"fi_treasury"},
            "EWT": {"intl_em"},
        }
        result = _resolve_group_symbols(tags_by_symbol, ["eq_*", "intl_*"])
        assert "SPY" in result
        assert "EWT" in result
        assert "TLT" not in result

    def test_fi_filter_matches_fi_prefixed_tags(self):
        tags_by_symbol = {
            "TLT": {"fi_treasury"},
            "HYG": {"fi_credit_hy"},
            "SPY": {"eq_large_cap"},
        }
        result = _resolve_group_symbols(tags_by_symbol, ["fi_*"])
        assert "TLT" in result
        assert "HYG" in result
        assert "SPY" not in result

    def test_returns_sorted_list(self):
        tags_by_symbol = {
            "ZZZ": {"eq_x"},
            "AAA": {"eq_x"},
            "MMM": {"eq_x"},
        }
        result = _resolve_group_symbols(tags_by_symbol, ["eq_*"])
        assert result == sorted(result)


class TestBucket:
    def test_value_below_first_upper_bound(self):
        tiers = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
        import numpy as np
        vals = np.array([0.1])
        result = _bucket(vals, tiers)
        assert result[0] == "low"

    def test_value_between_tiers(self):
        tiers = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
        import numpy as np
        vals = np.array([0.5])
        result = _bucket(vals, tiers)
        assert result[0] == "mid"

    def test_value_above_all_thresholds(self):
        tiers = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
        import numpy as np
        vals = np.array([0.9])
        result = _bucket(vals, tiers)
        assert result[0] == "high"

    def test_exactly_at_upper_bound_goes_to_next_tier(self):
        tiers = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
        import numpy as np
        vals = np.array([0.33])
        result = _bucket(vals, tiers)
        # 0.33 is NOT < 0.33, so it falls to "mid"
        assert result[0] == "mid"


class TestAssignLabels:
    def test_basic_label_format(self):
        import numpy as np
        rows = _assign_labels(
            group_name="equity",
            tf="1d",
            ts_arr=[_TS],
            sig1_arr=np.array([0.2]),
            sig2_arr=np.array([0.7]),
            tiers1=[("low", 0.33), ("mid", 0.67), ("high", float("inf"))],
            tiers2=[("bear", 0.40), ("neutral", 0.60), ("bull", float("inf"))],
            prob_keys=("vix_pct", "breadth_frac"),
        )
        assert len(rows) == 1
        group, tf, ts, label, prob = rows[0]
        assert group == "equity"
        assert tf == "1d"
        assert ts == _TS
        assert label == "low_bull"
        assert prob == {"vix_pct": 0.2, "breadth_frac": 0.7}

    def test_all_six_rates_labels_possible(self):
        import numpy as np
        sig1 = np.array([-1.0, -1.0, 0.0, 0.0, 1.0, 1.0])
        sig2 = np.array([-1.0,  1.0, -1.0, 1.0, -1.0,  1.0])
        tiers1 = [("inverted", -0.5), ("flat", 0.5), ("steep", float("inf"))]
        tiers2 = [("wide", 0.0), ("tight", float("inf"))]
        rows = _assign_labels(
            group_name="rates",
            tf="1d",
            ts_arr=[_TS] * 6,
            sig1_arr=sig1,
            sig2_arr=sig2,
            tiers1=tiers1,
            tiers2=tiers2,
            prob_keys=("curve_z", "credit_z"),
        )
        labels = {r[3] for r in rows}
        assert labels == {
            "inverted_wide", "inverted_tight",
            "flat_wide", "flat_tight",
            "steep_wide", "steep_tight",
        }

    def test_output_length_matches_input(self):
        import numpy as np
        n = 50
        rows = _assign_labels(
            group_name="equity",
            tf="5m",
            ts_arr=[_TS] * n,
            sig1_arr=np.random.rand(n),
            sig2_arr=np.random.rand(n),
            tiers1=[("low", 0.33), ("mid", 0.67), ("high", float("inf"))],
            tiers2=[("bear", 0.40), ("neutral", 0.60), ("bull", float("inf"))],
            prob_keys=("vix_pct", "breadth_frac"),
        )
        assert len(rows) == n
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_cross_sectional_regime_model.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name '_assign_labels' from 'services.cross_sectional_regime_model'`

- [ ] **Step 3: Write `cross_sectional_regime_model.py`**

```python
#!/usr/bin/env python3
"""Cross-Sectional Regime Model — generic dispatcher that populates market_regimes.

Groups are defined in APR key alpha.regime.groups (JSON array). Each group:
  - name: string key written to market_regimes.regime_group
  - tag_filter: list of tag patterns (prefix match, * stripped) to resolve peer symbols
  - signal_type: key in src/intelligence/regime_signals/REGISTRY
  - params_prefix: APR namespace for signal thresholds
  - enabled: bool

Signal modules (src/intelligence/regime_signals/) implement:
  - compute(ref_bars, params) -> (pd.Series, pd.Series) | None
  - build_tiers(params) -> (tiers1, tiers2)
  - PROB_KEYS: tuple[str, str]

Data flow per group per TF:
  1. Resolve peer symbols from instrument_tags (startup, once)
  2. Fetch all peer bars for this TF (fresh connection, avoids idle termination)
  3. Call signal_module.compute(ref_bars, params) -> (sig1, sig2)
  4. Align signals, drop NaN warmup rows
  5. Call _assign_labels(...) -> list[tuple]
  6. Batch-insert into market_regimes (ON CONFLICT UPDATE)

Usage:
    python services/cross_sectional_regime_model.py
    python services/cross_sectional_regime_model.py --tf 5m 1h
    python services/cross_sectional_regime_model.py --dry-run
"""
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
from src.intelligence.regime_signals import REGISTRY
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/cross_sectional_regime_model.log")

_logger = structlog.get_logger(__name__)

_JOB = "cross-sectional-regime-model"
_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]

_DEFAULT_GROUPS_JSON = json.dumps([
    {
        "name": "equity",
        "tag_filter": ["eq_*", "intl_*"],
        "signal_type": "breadth_vol",
        "params_prefix": "alpha.equity_regime",
        "enabled": True,
    },
    {
        "name": "rates",
        "tag_filter": ["fi_*"],
        "signal_type": "curve_credit",
        "params_prefix": "alpha.rates_regime",
        "enabled": True,
    },
    # Commodity and FX groups ship disabled — enabled once ETF universe
    # expansion (new instruments + tags) is complete and signal modules pass
    # their unit tests. Enable via APR: alpha.regime.groups update.
    {
        "name": "commodity_energy",
        "tag_filter": ["commodity_energy_crude", "commodity_energy_natgas", "commodity_energy_pipeline"],
        "signal_type": "commodity_momentum_ts",
        "params_prefix": "alpha.commodity_energy_regime",
        "enabled": False,
    },
    {
        "name": "commodity_metals",
        "tag_filter": ["commodity_metals_precious", "commodity_metals_industrial"],
        "signal_type": "commodity_momentum_ts",
        "params_prefix": "alpha.commodity_metals_regime",
        "enabled": False,
    },
    {
        "name": "commodity_agri",
        "tag_filter": ["commodity_agri"],
        "signal_type": "commodity_momentum_ts",
        "params_prefix": "alpha.commodity_agri_regime",
        "enabled": False,
    },
    {
        "name": "fx",
        "tag_filter": ["fx_*"],
        "signal_type": "fx_dollar_carry",
        "params_prefix": "alpha.fx_regime",
        "enabled": False,
    },
])


# ---------------------------------------------------------------------------
# Pure helpers — exported for unit tests
# ---------------------------------------------------------------------------


def _parse_group_configs(raw_json: str) -> list[dict]:
    """Parse and filter group config JSON from APR. Returns only enabled groups."""
    try:
        configs = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError(
            f"alpha.regime.groups contains invalid JSON: {error}"
        ) from error
    return [g for g in configs if g.get("enabled", True)]


def _resolve_group_symbols(
    tags_by_symbol: dict[str, set[str]],
    tag_filter: list[str],
) -> list[str]:
    """Return sorted list of symbols whose tags match any pattern in tag_filter.

    Pattern matching: strip trailing '*' and test if any tag starts with that prefix.
    """
    prefixes = [p.rstrip("*") for p in tag_filter]
    matched = [
        sym
        for sym, tags in tags_by_symbol.items()
        if any(any(t.startswith(pfx) for t in tags) for pfx in prefixes)
    ]
    return sorted(matched)


def _bucket(vals: np.ndarray, tiers: list[tuple[str, float]]) -> np.ndarray:
    """Assign tier names by threshold. tiers sorted ascending by upper_bound; last = inf.

    A value is assigned to the first tier whose upper_bound STRICTLY exceeds the value.
    """
    result = np.full(len(vals), tiers[-1][0], dtype=object)
    for name, upper in reversed(tiers[:-1]):
        result = np.where(vals < upper, name, result)
    return result


def _assign_labels(
    group_name: str,
    tf: str,
    ts_arr: list,
    sig1_arr: np.ndarray,
    sig2_arr: np.ndarray,
    tiers1: list[tuple[str, float]],
    tiers2: list[tuple[str, float]],
    prob_keys: tuple[str, str],
) -> list[tuple]:
    """Vectorized label assignment. No DB, no pandas.

    Returns list of (group_name, tf, ts, regime_label, prob_dict).
    regime_label = "{tier1}_{tier2}".
    """
    labels1 = _bucket(sig1_arr, tiers1)
    labels2 = _bucket(sig2_arr, tiers2)
    return [
        (
            group_name,
            tf,
            ts_arr[i],
            f"{labels1[i]}_{labels2[i]}",
            {prob_keys[0]: float(sig1_arr[i]), prob_keys[1]: float(sig2_arr[i])},
        )
        for i in range(len(ts_arr))
    ]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _connect_db(settings: Settings) -> Any:
    conn = psycopg2.connect(settings.database_url)
    conn.autocommit = False
    return conn


def _load_tags_by_symbol(conn: Any) -> dict[str, set[str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, array_agg(tag) FROM instrument_tags GROUP BY symbol")
        return {row[0]: set(row[1]) for row in cur.fetchall()}


def _fetch_group_bars(dsn: str, tf: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Fetch close prices for all symbols in one query. Returns dict[symbol, DataFrame].

    Uses a fresh connection to avoid idle-connection termination during long fetches.
    """
    sql = """
        SELECT symbol, timestamp, close
        FROM market_data_ohlcv
        WHERE symbol = ANY(%s) AND timeframe = %s
        ORDER BY symbol, timestamp ASC
    """
    fresh_conn = psycopg2.connect(dsn)
    fresh_conn.autocommit = True
    try:
        with fresh_conn.cursor() as cur:
            cur.execute(sql, (symbols, tf))
            rows = cur.fetchall()
    finally:
        fresh_conn.close()

    result: dict[str, list] = {}
    for sym, ts, close in rows:
        result.setdefault(sym, []).append((ts, float(close)))

    return {
        sym: pd.DataFrame(entries, columns=["timestamp", "close"])
        for sym, entries in result.items()
    }


def _write_rows(conn: Any, rows: list[tuple]) -> int:
    """Batch-insert regime rows into market_regimes. Returns count written."""
    insert_sql = """
        INSERT INTO market_regimes (regime_group, tf, ts, regime_label, regime_prob_vector)
        VALUES (%(regime_group)s, %(tf)s, %(ts)s, %(regime_label)s, %(regime_prob_vector)s::jsonb)
        ON CONFLICT (regime_group, tf, ts)
        DO UPDATE SET
            regime_label = EXCLUDED.regime_label,
            regime_prob_vector = EXCLUDED.regime_prob_vector
    """
    batch = [
        {
            "regime_group": r[0],
            "tf": r[1],
            "ts": r[2],
            "regime_label": r[3],
            "regime_prob_vector": json.dumps(r[4]),
        }
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, insert_sql, batch)
    conn.commit()
    return len(batch)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cross-Sectional Regime Model — populate market_regimes for all enabled groups"
    )
    parser.add_argument("--tf", nargs="*", default=_DEFAULT_TFS)
    parser.add_argument("--dry-run", action="store_true")
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
        dsn = settings.database_url
        conn = _connect_db(settings)
        cfg = _load_config_service(conn)

        raw_groups = cfg.get_sync("alpha.regime.groups", _DEFAULT_GROUPS_JSON)
        group_configs = _parse_group_configs(raw_groups)

        if not group_configs:
            _logger.error("cross_sectional_regime_model.no_enabled_groups")
            status = "failure"
            exit_code = 1
            return

        tags_by_symbol = _load_tags_by_symbol(conn)

        for group in group_configs:
            group_name = group["name"]
            signal_type = group["signal_type"]
            params_prefix = group["params_prefix"]

            signal_mod = REGISTRY.get(signal_type)
            if signal_mod is None:
                raise RuntimeError(
                    f"Unknown signal_type '{signal_type}' for group '{group_name}'. "
                    f"Available: {list(REGISTRY.keys())}"
                )

            peer_symbols = _resolve_group_symbols(tags_by_symbol, group["tag_filter"])
            if not peer_symbols:
                _logger.warning(
                    "cross_sectional_regime_model.no_peer_symbols",
                    group=group_name,
                    tag_filter=group["tag_filter"],
                )
                continue

            _logger.info(
                "cross_sectional_regime_model.group_start",
                group=group_name,
                signal_type=signal_type,
                n_symbols=len(peer_symbols),
            )

            # Load APR params for this group's signal
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_key, config_value FROM config_state WHERE config_key LIKE %s",
                    (f"{params_prefix}.%",),
                )
                raw_params = cur.fetchall()
            prefix_len = len(params_prefix) + 1
            params = {row[0][prefix_len:]: row[1] for row in raw_params}

            tiers1, tiers2 = signal_mod.build_tiers(params)

            total_written = 0
            for tf in args.tf:
                _logger.info(
                    "cross_sectional_regime_model.fetching_bars",
                    group=group_name,
                    tf=tf,
                    n_symbols=len(peer_symbols),
                )

                ref_bars = _fetch_group_bars(dsn, tf, peer_symbols)

                if not ref_bars:
                    _logger.warning(
                        "cross_sectional_regime_model.no_bars",
                        group=group_name,
                        tf=tf,
                    )
                    continue

                result = signal_mod.compute(ref_bars, params)
                if result is None:
                    _logger.warning(
                        "cross_sectional_regime_model.signal_returned_none",
                        group=group_name,
                        tf=tf,
                    )
                    continue

                sig1, sig2 = result
                combined = pd.DataFrame({"s1": sig1, "s2": sig2.reindex(sig1.index)}).dropna()

                if combined.empty:
                    _logger.warning(
                        "cross_sectional_regime_model.no_valid_rows",
                        group=group_name,
                        tf=tf,
                    )
                    continue

                rows = _assign_labels(
                    group_name=group_name,
                    tf=tf,
                    ts_arr=combined.index.tolist(),
                    sig1_arr=combined["s1"].to_numpy(),
                    sig2_arr=combined["s2"].to_numpy(),
                    tiers1=tiers1,
                    tiers2=tiers2,
                    prob_keys=signal_mod.PROB_KEYS,
                )

                distinct_labels = {r[3] for r in rows}
                _logger.info(
                    "cross_sectional_regime_model.tf_computed",
                    group=group_name,
                    tf=tf,
                    n_rows=len(rows),
                    distinct_labels=sorted(distinct_labels),
                )

                if args.dry_run:
                    continue

                # Reconnect before write: bar fetch can take minutes for 5m TF
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                conn = _connect_db(settings)

                n_written = _write_rows(conn, rows)
                total_written += n_written
                _logger.info(
                    "cross_sectional_regime_model.tf_written",
                    group=group_name,
                    tf=tf,
                    n_written=n_written,
                )

            _logger.info(
                "cross_sectional_regime_model.group_complete",
                group=group_name,
                total_written=total_written,
            )

        if args.dry_run:
            _logger.info("cross_sectional_regime_model.dry_run_complete")

        elapsed = time.monotonic() - t0
        _logger.info(
            "cross_sectional_regime_model.complete",
            elapsed_s=round(elapsed, 2),
            status=status,
        )

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


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_cross_sectional_regime_model.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Dry-run validate against live DB (equity group)**

```bash
.venv/bin/python services/cross_sectional_regime_model.py --dry-run --tf 1d
```

Expected: log lines show `n_rows > 0` for equity group, `distinct_labels` containing expected 9-label set (`low_bull`, `high_bear`, etc.). No errors.

- [ ] **Step 6: Dry-run validate rates group**

```bash
.venv/bin/python services/cross_sectional_regime_model.py --dry-run --tf 1d 2>&1 | grep -E "group=rates|curve_credit"
```

Expected: rates group shows `n_rows > 0` and `distinct_labels` containing ≤ 6 labels in `{steep|flat|inverted}_{tight|wide}` format.

- [ ] **Step 7: Full run and verify DB**

```bash
.venv/bin/python services/cross_sectional_regime_model.py --tf 5m 15m 1h 1d
```

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT regime_group, tf, regime_label, COUNT(*),
          ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY regime_group, tf), 1) AS pct
   FROM market_regimes
   GROUP BY 1, 2, 3
   ORDER BY 1, 2, 3;"
```

Expected: rows for both equity and rates across all 4 TFs. No single label exceeds 50% for any (group, tf). Equity `regime_group='equity'` rows match previous counts from `equity_regime_model`.

- [ ] **Step 8: Commit**

```bash
git add services/cross_sectional_regime_model.py src/intelligence/regime_signals/ \
    tests/unit/test_cross_sectional_regime_model.py
git commit -m "feat(regime-model): add cross_sectional_regime_model.py generic dispatcher; replaces equity_regime_model"
```

---

## Task 5: ic_engine.py — Routing + regime_group Rename

**Files:**
- Modify: `services/ic_engine.py`
- Create: `tests/unit/test_ic_engine_routing.py`

**Interfaces:**
- Consumes: `_build_symbol_regime_class(tags_by_symbol, group_configs) -> dict[str, str]` (new function in ic_engine.py)
- Modifies: `_assert_prerequisites`, `_load_apr`, `mr_dict` loading block, `_compute_cross_sectional_tf`, cross-sectional pass loop

The 6 touch points in ic_engine.py, in order:

1. New function `_build_symbol_regime_class` (after constants block)
2. `_assert_prerequisites` — parameterize group checks
3. `_load_apr` — add `groups_json` to returned dict
4. `mr_dict` loading block (line ~1854) — load per group
5. Worker args construction (line ~1891) — pass per-symbol mr_dict
6. `_compute_cross_sectional_tf` — add `regime_group` + `symbol_list` params, fix SQL
7. Cross-sectional pass loop (line ~1938) — loop over groups

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_ic_engine_routing.py
"""Unit tests for ic_engine symbol → regime group routing. CI-clean: no DB, no network."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from services.ic_engine import _build_symbol_regime_class

_EQUITY_GROUP = {"name": "equity", "tag_filter": ["eq_*", "intl_*"], "enabled": True}
_RATES_GROUP = {"name": "rates", "tag_filter": ["fi_*"], "enabled": True}
_GROUPS = [_EQUITY_GROUP, _RATES_GROUP]


class TestBuildSymbolRegimeClass:
    def test_fi_symbol_routes_to_rates(self):
        tags = {"TLT": {"fi_treasury"}, "HYG": {"fi_credit_hy"}, "AGG": {"fi_treasury", "fi_credit_ig"}}
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert result["TLT"] == "rates"
        assert result["HYG"] == "rates"
        assert result["AGG"] == "rates"

    def test_equity_symbol_routes_to_equity(self):
        tags = {"SPY": {"eq_large_cap", "eq_blend"}, "EWT": {"intl_em", "eq_sector"}}
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert result["SPY"] == "equity"
        assert result["EWT"] == "equity"

    def test_unmatched_symbol_defaults_to_equity(self):
        tags = {"GLD": {"commodity_metals"}, "BTC": {"crypto"}}
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert result["GLD"] == "equity"
        assert result["BTC"] == "equity"

    def test_disabled_rates_group_routes_fi_to_equity(self):
        disabled_rates = {**_RATES_GROUP, "enabled": False}
        tags = {"TLT": {"fi_treasury"}}
        result = _build_symbol_regime_class(tags, [_EQUITY_GROUP, disabled_rates])
        assert result["TLT"] == "equity"

    def test_first_matching_group_wins(self):
        """Equity group listed first; fi_* matches rates but equity is checked first."""
        # Only rates group — TLT routes to rates
        tags = {"TLT": {"fi_treasury"}}
        result = _build_symbol_regime_class(tags, [_RATES_GROUP])
        assert result["TLT"] == "rates"

    def test_empty_tags_defaults_to_equity(self):
        tags = {"XYZ": set()}
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert result["XYZ"] == "equity"

    def test_preferred_fi_routes_to_rates(self):
        tags = {"PFF": {"fi_preferred"}}
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert result["PFF"] == "rates"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/test_ic_engine_routing.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name '_build_symbol_regime_class' from 'services.ic_engine'`

- [ ] **Step 3: Add `_build_symbol_regime_class` to ic_engine.py**

Find the block after the constants (after `_CROSS_SECTIONAL_SYMBOL` and the `TF_TO_INTERVAL` dict, around line 130). Add immediately after:

```python
# ---------------------------------------------------------------------------
# Symbol → regime group routing
# ---------------------------------------------------------------------------


def _build_symbol_regime_class(
    tags_by_symbol: dict[str, set[str]],
    group_configs: list[dict],
) -> dict[str, str]:
    """Map each symbol to its regime group name from the groups APR config.

    Groups are checked in order; first matching group wins.
    A symbol matches a group if any of its instrument_tags starts with any
    prefix in the group's tag_filter (trailing * stripped).
    Symbols with no matching enabled group default to 'equity'.
    """
    prefixes_by_group: list[tuple[str, list[str]]] = [
        (g["name"], [p.rstrip("*") for p in g.get("tag_filter", [])])
        for g in group_configs
        if g.get("enabled", True)
    ]
    result: dict[str, str] = {}
    for symbol, tags in tags_by_symbol.items():
        assigned = "equity"
        for group_name, prefixes in prefixes_by_group:
            if any(any(t.startswith(pfx) for t in tags) for pfx in prefixes):
                assigned = group_name
                break
        result[symbol] = assigned
    return result
```

- [ ] **Step 4: Run routing tests to confirm they pass**

```bash
.venv/bin/pytest tests/unit/test_ic_engine_routing.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Replace all `asset_class='equity'` references in ic_engine.py**

There are 4 occurrences. Find exact lines:

```bash
grep -n "asset_class" /home/bg/dev/indicagent/services/ic_engine.py
```

For the `_assert_prerequisites` function (line ~326), replace:
```python
                    "SELECT count(*) FROM market_regimes WHERE asset_class='equity' AND tf=%s",
                    (tf,),
```
with:
```python
                    "SELECT count(*) FROM market_regimes WHERE regime_group=%s AND tf=%s",
                    (group_name, tf),
```

Update `_assert_prerequisites` signature and body to loop over enabled groups:

```python
def _assert_prerequisites(
    conn: Any,
    tfs: list[str] | None = None,
    group_configs: list[dict] | None = None,
) -> None:
    """Crash-loud startup gates."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM feature_vectors")
        n_fv = cur.fetchone()[0]
    if n_fv == 0:
        raise RuntimeError(
            "IC Engine startup gate FAILED: feature_vectors is empty. "
            "Run services/backfill_feature_factory.py first."
        )

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM feature_vectors WHERE regime IS NOT NULL")
        n_regime = cur.fetchone()[0]
    if n_regime == 0:
        raise RuntimeError(
            "IC Engine startup gate FAILED: feature_vectors.regime is all-NULL. "
            "Run services/regime_writer.py first."
        )

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM forward_returns")
        n_fr = cur.fetchone()[0]
    if n_fr == 0:
        raise RuntimeError(
            "IC Engine startup gate FAILED: forward_returns is empty. "
            "Run services/forward_return_writer.py first."
        )

    if group_configs and tfs:
        for group in group_configs:
            if not group.get("enabled", True):
                continue
            group_name = group["name"]
            for tf in tfs:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM market_regimes WHERE regime_group=%s AND tf=%s",
                        (group_name, tf),
                    )
                    n_mr = cur.fetchone()[0]
                if n_mr == 0:
                    raise RuntimeError(
                        f"IC Engine startup gate FAILED: market_regimes empty for "
                        f"regime_group={group_name} tf={tf}. "
                        f"Run services/cross_sectional_regime_model.py first."
                    )
```

- [ ] **Step 6: Update main() startup — load group configs and build routing**

After the `equity_model_enabled` load (around line 1739), replace with:

```python
            from services.cross_sectional_regime_model import _parse_group_configs

            raw_groups = _pre_cfg.get_sync("alpha.regime.groups", "[]")
            group_configs: list[dict] = _parse_group_configs(raw_groups)
            enabled_groups = [g for g in group_configs if g.get("enabled", True)]

            _logger.info(
                "ic_engine.groups_loaded",
                n_groups=len(enabled_groups),
                group_names=[g["name"] for g in enabled_groups],
            )

            with conn.cursor() as cur:
                cur.execute("SELECT symbol, array_agg(tag) FROM instrument_tags GROUP BY symbol")
                tags_by_symbol: dict[str, set[str]] = {
                    row[0]: set(row[1]) for row in cur.fetchall()
                }
            symbol_regime_class: dict[str, str] = _build_symbol_regime_class(
                tags_by_symbol, enabled_groups
            )
            _logger.info(
                "ic_engine.routing_built",
                n_symbols=len(symbol_regime_class),
                by_group={
                    g: sum(1 for v in symbol_regime_class.values() if v == g)
                    for g in {v for v in symbol_regime_class.values()}
                },
            )

            equity_model_enabled = any(g["name"] == "equity" for g in enabled_groups)
```

Update the `_assert_prerequisites` call (line ~1748):

```python
            _assert_prerequisites(conn, tfs=args.tf, group_configs=enabled_groups)
```

- [ ] **Step 8: Update `mr_dict` loading to cover all enabled groups**

Replace the `mr_dict_by_tf` loading block (lines ~1854-1866):

```python
            # Load {ts -> regime_label} per (regime_group, tf).
            # mr_dicts_by_group: {group_name -> {tf -> {ts -> label}}}
            mr_dicts_by_group: dict[str, dict[str, dict]] = {}
            for group in enabled_groups:
                group_name = group["name"]
                mr_dicts_by_group[group_name] = {}
                for tf in tfs:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT ts, regime_label FROM market_regimes "
                            "WHERE regime_group=%s AND tf=%s",
                            (group_name, tf),
                        )
                        mr_dicts_by_group[group_name][tf] = {r[0]: r[1] for r in cur.fetchall()}
                    _logger.info(
                        "ic_engine.mr_loaded",
                        regime_group=group_name,
                        tf=tf,
                        n_rows=len(mr_dicts_by_group[group_name][tf]),
                    )
```

- [ ] **Step 9: Update worker args to use per-symbol mr_dict**

Replace the `mr_dict_by_tf if equity_model_enabled else None` worker arg (line ~1891):

```python
                worker_args = [
                    (
                        symbol,
                        tfs,
                        settings.database_url,
                        training_window_end,
                        existing_keys_frozen,
                        apr_cache,
                        run_ts,
                        feature_status_map,
                        mr_dicts_by_group.get(symbol_regime_class.get(symbol, "equity"))
                        if enabled_groups
                        else None,
                    )
                    for symbol in symbols
                ]
```

- [ ] **Step 10: Update `_compute_cross_sectional_tf` signature and SQL**

Change the function signature (line 1262):

```python
def _compute_cross_sectional_tf(
    conn: Any,
    tf: str,
    regime_label: str,
    regime_group: str,
    symbol_list: list[str],
    training_window_end: Any,
    existing_keys: frozenset[tuple],
    apr: dict[str, Any],
    tracer: Any,
    run_ts: datetime,
    feature_status_map: dict[str, str] | None = None,
) -> dict[str, Any]:
```

Replace the `cs_sql` block (lines 1298-1313):

```python
    cs_sql = f"""
        SELECT fv.bar_ts, {feature_cols}, {return_cols}, {complete_cols}
        FROM feature_vectors fv
        INNER JOIN market_regimes mr
            ON mr.regime_group = %(regime_group)s
            AND mr.tf = %(tf)s
            AND mr.ts = time_bucket(%(tf_interval)s::interval, fv.bar_ts)
            AND mr.regime_label = %(regime_label)s
        INNER JOIN forward_returns fr
            ON fr.symbol = fv.symbol
            AND fr.tf = fv.tf
            AND fr.bar_ts = fv.bar_ts
        WHERE fv.tf = %(tf)s
          AND fv.symbol = ANY(%(symbol_list)s)
          AND fv.bar_ts <= %(training_window_end)s
        ORDER BY fv.bar_ts
    """
```

Replace the `cur.execute` call parameters (line ~1316):

```python
        cur.execute(
            cs_sql,
            {
                "tf": tf,
                "tf_interval": tf_interval,
                "regime_label": regime_label,
                "regime_group": regime_group,
                "symbol_list": symbol_list,
                "training_window_end": training_window_end,
            },
        )
```

- [ ] **Step 11: Update cross-sectional pass loop**

Replace the cross-sectional pass block (lines ~1938-1973):

```python
            # Cross-sectional IC pass — one pooled observation per (regime_group, tf, regime_label).
            # Each group's peer symbols are pooled independently.
            if enabled_groups:
                _logger.info("ic_engine.starting_cross_sectional_pass")
                cs_conn = _connect_db(settings)
                try:
                    symbols_by_group: dict[str, list[str]] = {}
                    for sym in symbols:
                        g = symbol_regime_class.get(sym, "equity")
                        symbols_by_group.setdefault(g, []).append(sym)

                    for group in enabled_groups:
                        group_name = group["name"]
                        group_symbols = symbols_by_group.get(group_name, [])
                        if not group_symbols:
                            continue

                        with cs_conn.cursor() as cur:
                            cur.execute(
                                "SELECT DISTINCT regime_label FROM market_regimes "
                                "WHERE regime_group=%s AND tf=%s ORDER BY regime_label",
                                (group_name, tfs[0]),
                            )
                            cs_regimes = [r[0] for r in cur.fetchall()]

                        for tf in tfs:
                            apr = apr_cache[tf]
                            for regime_label in cs_regimes:
                                cs_result = _compute_cross_sectional_tf(
                                    conn=cs_conn,
                                    tf=tf,
                                    regime_label=regime_label,
                                    regime_group=group_name,
                                    symbol_list=group_symbols,
                                    training_window_end=training_window_end,
                                    existing_keys=existing_keys_frozen,
                                    apr=apr,
                                    tracer=tracer,
                                    run_ts=run_ts,
                                    feature_status_map=feature_status_map,
                                )
                                total_committed += cs_result.get("n_committed", 0)
                                total_skipped += cs_result.get("n_skipped", 0)
                                _logger.info(
                                    "ic_engine.cross_sectional_done",
                                    regime_group=group_name,
                                    tf=tf,
                                    regime=regime_label,
                                    n_committed=cs_result.get("n_committed", 0),
                                )
                finally:
                    cs_conn.close()
```

- [ ] **Step 12: Run full unit test suite**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -15
```

Expected: all tests pass including the new routing tests.

- [ ] **Step 13: Verify ic_engine dry-run with routing**

```bash
.venv/bin/python services/ic_engine.py --symbols TLT IEF --tf 1d --dry-run 2>&1 | grep -E "routing_built|mr_loaded|regime_group"
```

Expected: `routing_built` log shows `rates` group with 2 symbols. `mr_loaded` shows `regime_group=rates`.

- [ ] **Step 14: Commit**

```bash
git add services/ic_engine.py tests/unit/test_ic_engine_routing.py
git commit -m "feat(ic-engine): add regime group routing; rename asset_class to regime_group in all SQL"
```

---

## Task 6: Pipeline Update + Deprecate equity_regime_model.py

**Files:**
- Modify: `scripts/ops/corpus/ops_corpus_pipeline_run.sh`
- Modify: `services/equity_regime_model.py`

- [ ] **Step 1: Add deprecation header to equity_regime_model.py**

At the top of the module docstring (after `#!/usr/bin/env python3`), replace the existing docstring opening line with:

```python
"""[DEPRECATED] equity_regime_model.py — superseded by cross_sectional_regime_model.py.

This file is retained for emergency rollback only. Do not run directly.
Use services/cross_sectional_regime_model.py instead.

Original equity regime model — populates market_regimes with cross-sectional labels.
...
```

(Keep the rest of the docstring and all code unchanged.)

- [ ] **Step 2: Update corpus_pipeline_run.sh**

Replace step 4 (ic_engine) block and add regime model steps before it. The current steps 4-6 become steps 5-7, and a new step 4 is inserted:

Replace this section:
```bash
# Step 4 — IC Engine (feature_vectors + forward_returns → feature_ic_scores)
run_step 4 "ic_engine" \
    "$PYTHON" services/ic_engine.py \
    "${SPACE_SYMBOLS[@]}" \
    --training-window-end "$TRAINING_WINDOW_END"

# Step 5 — Ensemble Trainer (feature_ic_scores + feature_vectors → ensemble_weights + ensemble_alpha)
run_step 5 "ensemble_trainer" \
    "$PYTHON" services/ensemble_trainer.py

# Step 6 — Alpha Publisher (ensemble_alpha → alpha_events + Kafka)
run_step 6 "alpha_publisher" \
    "$PYTHON" services/alpha_publisher.py
```

With:
```bash
# Step 4 — Cross-Sectional Regime Model (market_data_ohlcv → market_regimes for all groups)
run_step 4 "cross_sectional_regime_model" \
    "$PYTHON" services/cross_sectional_regime_model.py

# Step 5 — IC Engine (feature_vectors + forward_returns + market_regimes → feature_ic_scores)
run_step 5 "ic_engine" \
    "$PYTHON" services/ic_engine.py \
    "${SPACE_SYMBOLS[@]}" \
    --training-window-end "$TRAINING_WINDOW_END"

# Step 6 — Ensemble Trainer (feature_ic_scores + feature_vectors → ensemble_weights + ensemble_alpha)
run_step 6 "ensemble_trainer" \
    "$PYTHON" services/ensemble_trainer.py

# Step 7 — Alpha Publisher (ensemble_alpha → alpha_events + Kafka)
run_step 7 "alpha_publisher" \
    "$PYTHON" services/alpha_publisher.py
```

Also update the header comment and banner references from `6 steps` to `7 steps`:

```bash
# Full v3.0 corpus pipeline — 7 steps from market_data_ohlcv to alpha_events.
```

```bash
    printf " Step %d/7 — %s\n" "$step" "$name"
```

- [ ] **Step 3: Validate script syntax**

```bash
bash -n scripts/ops/corpus/ops_corpus_pipeline_run.sh && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 4: Test --from-step still works**

```bash
bash scripts/ops/corpus/ops_corpus_pipeline_run.sh --from-step 8 2>&1 | head -10
```

Expected: all steps print `[skipped — --from-step 8]` and reaches summary banner.

- [ ] **Step 5: Run full unit test suite one final time**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/ops/corpus/ops_corpus_pipeline_run.sh services/equity_regime_model.py
git commit -m "feat(pipeline): replace equity_regime_model with cross_sectional_regime_model (step 4, 7-step pipeline)"
```

---

## Verification

After all tasks are committed, run the full validation sequence:

```bash
# 1. Both regime groups populated with reasonable distribution
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT regime_group, tf, regime_label, COUNT(*),
          ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY regime_group, tf), 1) AS pct
   FROM market_regimes
   GROUP BY 1, 2, 3
   ORDER BY 1, 2, 3;"
```

Pass criteria: equity has 9 label types per TF (3 vol × 3 breadth), rates has ≤ 6 (3 curve × 2 credit). Commodity and FX groups show no rows (enabled=false until ETF expansion complete). No label exceeds 50% for any (group, tf).

```bash
# 2. ic_engine routing log confirms correct group assignment
.venv/bin/python services/ic_engine.py --symbols SPY TLT AGG --tf 1d --dry-run 2>&1 | \
    grep -E "routing_built|by_group"
```

Expected: `by_group={"equity": 1, "rates": 2}` (SPY→equity, TLT+AGG→rates).

```bash
# 3. Full unit suite green
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass.

```bash
# 4. Merge to main and push
git checkout main
git merge --ff-only <feature-branch>
git branch -d <feature-branch>
git worktree prune
git push origin main
```

---

## Task 6: commodity_momentum_ts Signal Module

**Dependency:** ETF universe expansion (USO, UNG, DBA, DBB, CPER etc.) must be in `instruments` + tagged before this task runs. Groups remain `enabled=false` until then.

**Design:** Two signal dimensions for each commodity peer group:
- **Momentum z-score** — cross-sectional median of peer group's rolling log-return z-scores (window via APR). Captures whether the group is trending up or down.
- **Term structure proxy** — cross-sectional median of (front_close / back_close - 1) z-score, approximated from price momentum slope acceleration (second derivative of price). True contango/backwardation requires futures data; this ETF proxy captures the same directional signal at lower fidelity.

**Labels (4):** `strong_up`, `up`, `down`, `strong_down` — derived from momentum z-score alone when term structure proxy is unavailable; `{momentum}_{ts}` labels when both signals active.

**Label rationale:** 4 labels (not 9) because peer groups have 4-8 instruments — 9 labels would produce sparse buckets. Simpler is more stable.

**Files:**
- Create: `src/intelligence/regime_signals/commodity_momentum_ts.py`
- Create: `tests/unit/test_regime_signals_commodity_momentum_ts.py`

**APR keys** (add to migration 179 or a follow-on migration):

```sql
INSERT INTO config_schema (config_key, value_type, min_value, max_value, description)
VALUES
    ('alpha.commodity_energy_regime.momentum_window', 'int', 5, 500,
     '[conventional] Rolling window (bars) for per-symbol log-return z-score in energy group.'),
    ('alpha.commodity_energy_regime.strong_threshold', 'float', 0.0, 5.0,
     '[initial_estimate] Median z-score above which momentum is "strong_up". Candidate ML target.'),
    ('alpha.commodity_metals_regime.momentum_window', 'int', 5, 500,
     '[conventional] Rolling window (bars) for metals group momentum z-score.'),
    ('alpha.commodity_metals_regime.strong_threshold', 'float', 0.0, 5.0,
     '[initial_estimate] Metals group strong_up threshold.'),
    ('alpha.commodity_agri_regime.momentum_window', 'int', 5, 500,
     '[conventional] Rolling window (bars) for agri group momentum z-score.'),
    ('alpha.commodity_agri_regime.strong_threshold', 'float', 0.0, 5.0,
     '[initial_estimate] Agri group strong_up threshold.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.commodity_energy_regime.momentum_window', '60', 1),
    ('alpha.commodity_energy_regime.strong_threshold', '0.75', 1),
    ('alpha.commodity_metals_regime.momentum_window', '60', 1),
    ('alpha.commodity_metals_regime.strong_threshold', '0.75', 1),
    ('alpha.commodity_agri_regime.momentum_window', '60', 1),
    ('alpha.commodity_agri_regime.strong_threshold', '0.75', 1)
ON CONFLICT (config_key) DO NOTHING;
```

**Interface:**
- `compute(ref_bars, params) -> tuple[pd.Series, pd.Series] | None` — (momentum_z_median, ts_proxy_median), both indexed by timestamp; NaN for warmup
- `build_tiers(params) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]`
- `PROB_KEYS: tuple[str, str]` — `("momentum_z", "ts_proxy")`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_regime_signals_commodity_momentum_ts.py
"""Unit tests for commodity_momentum_ts signal module. CI-clean: no DB, no network."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
sys.path.insert(0, str(Path(__file__).parents[2]))
from src.intelligence.regime_signals.commodity_momentum_ts import PROB_KEYS, build_tiers, compute

_UTC = pd.Timestamp("2020-01-01", tz="UTC")

def _make_bars(closes: list[float]) -> pd.DataFrame:
    ts = pd.date_range(_UTC, periods=len(closes), freq="5min")
    return pd.DataFrame({"timestamp": ts, "close": closes})

class TestComputeShape:
    def test_returns_two_series_same_length(self):
        n, window = 200, 60
        bars = {"USO": _make_bars([100 + i * 0.1 for i in range(n)]),
                "UNG": _make_bars([50 + i * 0.05 for i in range(n)])}
        params = {"momentum_window": window, "strong_threshold": 0.75}
        s1, s2 = compute(bars, params)
        assert len(s1) == n
        assert len(s2) == n

    def test_warmup_bars_are_nan(self):
        n, window = 200, 60
        bars = {"USO": _make_bars([100.0] * n)}
        params = {"momentum_window": window, "strong_threshold": 0.75}
        s1, _ = compute(bars, params)
        assert s1.iloc[:window].isna().all()

    def test_rising_group_positive_median(self):
        n, window = 200, 60
        bars = {sym: _make_bars([100 + i * 0.5 for i in range(n)])
                for sym in ["USO", "UNG", "XOP"]}
        params = {"momentum_window": window, "strong_threshold": 0.75}
        s1, _ = compute(bars, params)
        assert s1.iloc[window:].median() > 0

class TestBuildTiers:
    def test_returns_two_tier_lists(self):
        tiers1, tiers2 = build_tiers({"strong_threshold": 0.75})
        assert len(tiers1) >= 2
        assert len(tiers2) >= 2

class TestProbKeys:
    def test_prob_keys_are_tuple_of_two(self):
        assert len(PROB_KEYS) == 2
```

- [ ] **Step 2: Run tests (expect ImportError)**

```bash
.venv/bin/pytest tests/unit/test_regime_signals_commodity_momentum_ts.py -v 2>&1 | head -10
```

- [ ] **Step 3: Register in `__init__.py`**

Add to `src/intelligence/regime_signals/__init__.py`:
```python
from src.intelligence.regime_signals import commodity_momentum_ts

REGISTRY = {
    "breadth_vol": breadth_vol,
    "curve_credit": curve_credit,
    "commodity_momentum_ts": commodity_momentum_ts,
    "fx_dollar_carry": fx_dollar_carry,  # added in Task 7
}
```

- [ ] **Step 4: Implement `commodity_momentum_ts.py`**

```python
# src/intelligence/regime_signals/commodity_momentum_ts.py
"""commodity_momentum_ts — Commodity cross-sectional regime signal.

Computes two aligned series from a peer group of commodity ETFs:
  1. momentum_z_median  — cross-sectional median of per-symbol rolling log-return z-scores
  2. ts_proxy_median    — cross-sectional median of momentum slope acceleration (d²price/dt²
                          z-score), an ETF-based proxy for contango/backwardation direction

Labels: strong_up / up / down / strong_down (4 states).
4 labels (not 9) because commodity peer groups have 4-8 instruments — 9 would produce
sparse buckets with unreliable IC stratification.

Shared across commodity_energy, commodity_metals, commodity_agri groups.
params_prefix differs per group; APR key momentum_window and strong_threshold are read
from the group-specific namespace.
"""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd

PROB_KEYS: tuple[str, str] = ("momentum_z", "ts_proxy")


def compute(
    ref_bars: dict[str, pd.DataFrame],
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series] | None:
    """Return (momentum_z_median, ts_proxy_median) series indexed by timestamp.

    Both series have NaN for the first momentum_window bars (warmup).
    Returns None if ref_bars is empty or has fewer than 2 symbols.
    """
    if not ref_bars:
        return None

    window: int = int(params["momentum_window"])

    momentum_cols = []
    ts_proxy_cols = []

    for symbol, df in ref_bars.items():
        closes = df["close"].values.astype(float)
        log_ret = np.log(closes[1:] / closes[:-1])
        log_ret = np.concatenate([[np.nan], log_ret])

        # rolling z-score of log returns
        s = pd.Series(log_ret, index=df["timestamp"])
        roll_mean = s.rolling(window, min_periods=window).mean()
        roll_std = s.rolling(window, min_periods=window).std()
        z = (s - roll_mean) / roll_std.replace(0, np.nan)
        momentum_cols.append(z)

        # term structure proxy: slope acceleration (2nd derivative of price)
        price_s = pd.Series(closes, index=df["timestamp"])
        slope = price_s.diff()
        accel = slope.diff()
        accel_roll_std = accel.rolling(window, min_periods=window).std()
        accel_z = accel / accel_roll_std.replace(0, np.nan)
        ts_proxy_cols.append(accel_z)

    idx = list(ref_bars.values())[0]["timestamp"]
    momentum_df = pd.concat(momentum_cols, axis=1)
    ts_proxy_df = pd.concat(ts_proxy_cols, axis=1)

    return (
        momentum_df.median(axis=1).set_axis(idx),
        ts_proxy_df.median(axis=1).set_axis(idx),
    )


def build_tiers(
    params: dict[str, Any],
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return threshold lists for _assign_labels.

    Tier 1 (momentum): strong_up | up | down | strong_down
    Tier 2 (ts_proxy): contango_signal | neutral | backwardation_signal
    """
    strong = float(params["strong_threshold"])
    tiers1 = [("strong_up", strong), ("up", 0.0), ("down", -strong)]
    tiers2 = [("contango", 0.25), ("neutral", -0.25)]
    return tiers1, tiers2
```

- [ ] **Step 5: Run tests (all pass)**

```bash
.venv/bin/pytest tests/unit/test_regime_signals_commodity_momentum_ts.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/regime_signals/commodity_momentum_ts.py \
    tests/unit/test_regime_signals_commodity_momentum_ts.py
git commit -m "feat(regime-signals): add commodity_momentum_ts signal module"
```

---

## Task 7: fx_dollar_carry Signal Module

**Dependency:** FX ETFs (UUP, FXE, FXY) must be in `instruments` + tagged `fx_*` before enabling. Group ships `enabled=false`.

**Design:** Two signal dimensions:
- **Dollar trend z-score** — UUP rolling log-return z-score (momentum of the dollar index). Positive = dollar strengthening.
- **Carry environment** — HYG momentum z-score as a risk-on/off proxy. Positive = risk-on (carry works), negative = risk-off (carry unwinds). HYG is in the rates group but used here as a reference instrument (not a peer member).

**Labels (4):** `strong_dollar_risk_on`, `strong_dollar_risk_off`, `weak_dollar_risk_on`, `weak_dollar_risk_off`.

**Rationale:** Dollar direction × carry environment are the two orthogonal FX regime drivers. 4 labels fit a 3-6 instrument peer group without sparse bucket risk.

**Files:**
- Create: `src/intelligence/regime_signals/fx_dollar_carry.py`
- Create: `tests/unit/test_regime_signals_fx_dollar_carry.py`

**APR keys:**

```sql
INSERT INTO config_schema (config_key, value_type, min_value, max_value, description)
VALUES
    ('alpha.fx_regime.momentum_window', 'int', 5, 500,
     '[conventional] Rolling window (bars) for UUP and HYG log-return z-score.'),
    ('alpha.fx_regime.dollar_strong_threshold', 'float', 0.0, 5.0,
     '[initial_estimate] UUP z-score above which dollar regime is "strong". Candidate ML target.'),
    ('alpha.fx_regime.carry_risk_on_threshold', 'float', -5.0, 5.0,
     '[initial_estimate] HYG z-score above which carry environment is "risk_on".')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.fx_regime.momentum_window',          '60',   1),
    ('alpha.fx_regime.dollar_strong_threshold',  '0.5',  1),
    ('alpha.fx_regime.carry_risk_on_threshold',  '0.0',  1)
ON CONFLICT (config_key) DO NOTHING;
```

**Interface:**
- `compute(ref_bars, params) -> tuple[pd.Series, pd.Series] | None` — (dollar_z, carry_z)
- `REFERENCE_SYMBOLS: tuple[str, ...]` — `("UUP", "HYG")` — fetched by service as reference bars even if not peer members
- `PROB_KEYS: tuple[str, str]` — `("dollar_z", "carry_z")`

**Note:** `cross_sectional_regime_model.py` must fetch REFERENCE_SYMBOLS bars for any group whose signal module declares them, in addition to peer member bars. Add `_get_reference_symbols(module) -> set[str]` helper that returns `getattr(module, "REFERENCE_SYMBOLS", ())`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_regime_signals_fx_dollar_carry.py
"""Unit tests for fx_dollar_carry signal module. CI-clean: no DB, no network."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
sys.path.insert(0, str(Path(__file__).parents[2]))
from src.intelligence.regime_signals.fx_dollar_carry import (
    PROB_KEYS, REFERENCE_SYMBOLS, build_tiers, compute,
)

_UTC = pd.Timestamp("2020-01-01", tz="UTC")

def _make_bars(closes: list[float]) -> pd.DataFrame:
    ts = pd.date_range(_UTC, periods=len(closes), freq="5min")
    return pd.DataFrame({"timestamp": ts, "close": closes})

class TestComputeShape:
    def test_returns_two_series(self):
        n, window = 200, 60
        bars = {
            "UUP": _make_bars([25 + i * 0.01 for i in range(n)]),
            "HYG": _make_bars([80 + i * 0.05 for i in range(n)]),
            "FXE": _make_bars([105 - i * 0.01 for i in range(n)]),
        }
        params = {"momentum_window": window, "dollar_strong_threshold": 0.5,
                  "carry_risk_on_threshold": 0.0}
        s1, s2 = compute(bars, params)
        assert len(s1) == n
        assert len(s2) == n

    def test_warmup_nan(self):
        n, window = 200, 60
        bars = {"UUP": _make_bars([25.0] * n), "HYG": _make_bars([80.0] * n)}
        params = {"momentum_window": window, "dollar_strong_threshold": 0.5,
                  "carry_risk_on_threshold": 0.0}
        s1, _ = compute(bars, params)
        assert s1.iloc[:window].isna().all()

    def test_missing_uup_returns_none(self):
        bars = {"FXE": _make_bars([105.0] * 200)}
        params = {"momentum_window": 60, "dollar_strong_threshold": 0.5,
                  "carry_risk_on_threshold": 0.0}
        assert compute(bars, params) is None

class TestReferenceSymbols:
    def test_uup_and_hyg_declared(self):
        assert "UUP" in REFERENCE_SYMBOLS
        assert "HYG" in REFERENCE_SYMBOLS
```

- [ ] **Step 2: Run tests (expect ImportError)**

- [ ] **Step 3: Implement `fx_dollar_carry.py`**

```python
# src/intelligence/regime_signals/fx_dollar_carry.py
"""fx_dollar_carry — FX cross-sectional regime signal.

Two signal dimensions:
  1. dollar_z  — UUP rolling log-return z-score (dollar trend strength)
  2. carry_z   — HYG rolling log-return z-score (risk-on/off proxy for carry)

UUP and HYG are REFERENCE_SYMBOLS: fetched by the service even if not peer members
of the fx group. The peer group (FXE, FXY, etc.) is used only to validate the group
has enough members; the signal itself anchors on UUP and HYG.

Labels: strong_dollar_risk_on / strong_dollar_risk_off /
        weak_dollar_risk_on / weak_dollar_risk_off
"""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd

PROB_KEYS: tuple[str, str] = ("dollar_z", "carry_z")
REFERENCE_SYMBOLS: tuple[str, ...] = ("UUP", "HYG")


def compute(
    ref_bars: dict[str, pd.DataFrame],
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series] | None:
    """Return (dollar_z, carry_z) indexed by timestamp. None if UUP missing."""
    if "UUP" not in ref_bars:
        return None

    window = int(params["momentum_window"])

    def _rolling_z(df: pd.DataFrame) -> pd.Series:
        closes = df["close"].values.astype(float)
        log_ret = np.log(closes[1:] / closes[:-1])
        log_ret = np.concatenate([[np.nan], log_ret])
        s = pd.Series(log_ret, index=df["timestamp"])
        roll_mean = s.rolling(window, min_periods=window).mean()
        roll_std = s.rolling(window, min_periods=window).std()
        return (s - roll_mean) / roll_std.replace(0, np.nan)

    dollar_z = _rolling_z(ref_bars["UUP"])
    carry_z = _rolling_z(ref_bars["HYG"]) if "HYG" in ref_bars else pd.Series(
        np.nan, index=dollar_z.index
    )
    return dollar_z, carry_z


def build_tiers(
    params: dict[str, Any],
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Tier 1: dollar strength. Tier 2: carry environment."""
    dollar_thresh = float(params["dollar_strong_threshold"])
    carry_thresh = float(params["carry_risk_on_threshold"])
    tiers1 = [("strong_dollar", dollar_thresh), ("weak_dollar", -dollar_thresh)]
    tiers2 = [("risk_on", carry_thresh)]
    return tiers1, tiers2
```

- [ ] **Step 4: Add `_get_reference_symbols` to `cross_sectional_regime_model.py`**

In the bar-fetch section of `main()`, after resolving peer symbols per group, also fetch reference symbols declared by the signal module:

```python
def _get_reference_symbols(module: Any) -> frozenset[str]:
    return frozenset(getattr(module, "REFERENCE_SYMBOLS", ()))
```

Pass combined `peer_symbols | reference_symbols` to the bar fetch query, then pass `all_bars` (not just peer bars) to `compute()`.

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/unit/test_regime_signals_fx_dollar_carry.py -v
```

- [ ] **Step 6: Update REGISTRY**

```python
# src/intelligence/regime_signals/__init__.py
from src.intelligence.regime_signals import (
    breadth_vol,
    commodity_momentum_ts,
    curve_credit,
    fx_dollar_carry,
)

REGISTRY: dict[str, Any] = {
    "breadth_vol": breadth_vol,
    "curve_credit": curve_credit,
    "commodity_momentum_ts": commodity_momentum_ts,
    "fx_dollar_carry": fx_dollar_carry,
}
```

- [ ] **Step 7: Commit**

```bash
git add src/intelligence/regime_signals/fx_dollar_carry.py \
    src/intelligence/regime_signals/__init__.py \
    tests/unit/test_regime_signals_fx_dollar_carry.py
git commit -m "feat(regime-signals): add fx_dollar_carry signal module + update REGISTRY"
```

---

## Tag Vocabulary Extension (prerequisite for commodity/FX groups)

Before enabling commodity and FX regime groups, the tag vocabulary must be extended with fine-grained sub-tags. This is a migration-level change coordinated with the ETF universe expansion plan.

**New tags required:**

| tag | category | replaces / refines |
|---|---|---|
| `commodity_energy_crude` | exposure | refines `commodity_energy` |
| `commodity_energy_natgas` | exposure | refines `commodity_energy` |
| `commodity_energy_pipeline` | exposure | refines `commodity_energy` |
| `commodity_metals_precious` | exposure | refines `commodity_metals` |
| `commodity_metals_industrial` | exposure | refines `commodity_metals` |
| `commodity_agri` | exposure | new |
| `commodity_broad` | exposure | new |
| `fx_major` | exposure | new — EUR, JPY, GBP |
| `fx_em` | exposure | new — EM FX basket |
| `fx_usd` | exposure | new — dollar index |

**Backward compat:** Keep existing `commodity_energy` and `commodity_metals` tags on instruments that already have them. Add the fine-grained tags alongside. Regime group routing uses fine-grained tags; existing IC scoring uses whatever tags are present. No migration of existing rows needed.
