# Canary RNG Seed Fix + Broadcast-Feature Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the confirmed canary RNG seeding bug (todo 203 — `canary_noise_gaussian`/`canary_noise_uniform`/`canary_near_constant` are bit-identical across every symbol at a given timestamp, defeating their purpose as cross-sectional negative controls), build a read-only audit that empirically classifies which of the 244 active features share this same "broadcast" (symbol-invariant) exposure, and correctly scope/document a second, independently-discovered anomaly (`canary_acausal_placebo` not clearing its POOLED gate) that must NOT be guess-fixed without its own diagnosis.

**Architecture:** Three independent, non-overlapping changes. (1) A pure-function seed-derivation fix in `src/intelligence/feature_factory.py`, mirroring `ic_engine.py`'s existing `_derive_worker_rng_seed` hashing pattern exactly (DRY — don't invent a second seeding convention). (2) A new, self-contained, read-only diagnostic script (`ops_broadcast_feature_audit.py`), following the exact house style of `ops_canary_integrity_assert.py`/`ops_lookahead_horizon_response.py` (no persistence, no config_state writes, exit 0). (3) Documentation-only changes to `.planning/todos/` correcting a factual error from this session (the "no live canary check" claim was wrong — `ops_canary_integrity_assert.py` already exists and is already firing) and filing a new, separate todo for the undiagnosed anomaly it surfaced.

**Tech Stack:** Python 3.14, PostgreSQL/TimescaleDB (asyncpg), pytest, numpy.

## Global Constraints

- `_canary_sub_seed` must remain PYTHONHASHSEED-independent (no Python built-in `hash()`) — reproducibility across ProcessPoolExecutor workers and interpreter invocations is load-bearing (existing test `test_stable_across_repeated_calls_no_hash_randomization`). Use `hashlib.md5`, mirroring `services/ic_engine.py:1444`'s `_derive_worker_rng_seed`.
- Do NOT trigger a corpus-wide backfill/recompute of `feature_vectors` as part of this plan. The 3 broken canary columns have zero live consumers today (`status='candidate'`, never promoted; only read via `feature_ic_scores`, which is empty of any vintage newer than 2025-12-24 and is already gated on todo 202's rebuild for an unrelated reason). The next scheduled corpus rebuild will produce correct values once this fix lands — a dedicated backfill of 3 unconsumed columns across the full corpus is not justified (YAGNI / Musk mandate: don't accelerate work step 1-3 haven't justified).
- Do NOT attempt to fix the `canary_acausal_placebo` POOLED-detection anomaly in this plan. It has a different, unconfirmed root cause (verified: it does not use `_canary_sub_seed` at all) and fixing it blind would violate systematic-debugging discipline ("diagnose before proposing fixes"). File it as its own todo (Task 3) instead.
- Full `tests/unit/` suite must be green before this is considered done.

---

## Task 1: Fix `_canary_sub_seed` to include `symbol` — the confirmed bug (todo 203)

**Files:**
- Modify: `src/intelligence/feature_factory.py:1778-1811` (`_canary_sub_seed`, `_canary_noise_gaussian`, `_canary_noise_uniform`, `_canary_near_constant`), `:1` region imports (add `hashlib`), `:6337-6339` (`compute()` call site), `:7093-7095` (`compute_batch()` call site)
- Test: `tests/unit/test_canary_predictors.py` (extensive existing coverage of the old signature — every call site needs updating, plus new tests for the actual property that matters)

**Interfaces:**
- Consumes: nothing new.
- Produces: `_canary_sub_seed(bar_ts: datetime, symbol: str, base_seed: int, offset: int) -> int` (symbol inserted as the 2nd positional param), `_canary_noise_gaussian(bar_ts: datetime, symbol: str, base_seed: int) -> float`, `_canary_noise_uniform(bar_ts: datetime, symbol: str, base_seed: int) -> float`, `_canary_near_constant(bar_ts: datetime, symbol: str, base_seed: int) -> float` — all gain `symbol` as their 2nd parameter, same position across all four for consistency.

- [ ] **Step 1: Write the failing tests proving the actual bug is fixed**

Add to `tests/unit/test_canary_predictors.py`, in a new class after `TestNoiseCanaries` (before `TestConstantCanaries`):

```python
class TestCanarySymbolDifferentiation:
    """The actual bug (todo 203): _canary_sub_seed omitted `symbol` entirely, so
    every symbol got the IDENTICAL 'random' draw at a given bar_ts -- confirmed
    live in feature_vectors (bit-identical canary_noise_gaussian/uniform/
    near_constant across every pooled symbol at the same timestamp). This defeats
    their purpose as cross-sectional negative controls: any measurement pooling
    multiple symbols (ic_engine.py's _compute_cross_sectional_tf) saw severe
    pseudo-replication as a result."""

    def test_different_symbols_give_different_sub_seeds(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        s_spy = _canary_sub_seed(bar_ts, "SPY", base_seed=90042, offset=0)
        s_qqq = _canary_sub_seed(bar_ts, "QQQ", base_seed=90042, offset=0)
        assert s_spy != s_qqq

    def test_same_symbol_and_bar_ts_still_deterministic(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        s1 = _canary_sub_seed(bar_ts, "SPY", base_seed=90042, offset=0)
        s2 = _canary_sub_seed(bar_ts, "SPY", base_seed=90042, offset=0)
        assert s1 == s2

    def test_gaussian_canary_differs_across_symbols_at_same_bar_ts(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        v_spy = _canary_noise_gaussian(bar_ts, "SPY", base_seed=90042)
        v_qqq = _canary_noise_gaussian(bar_ts, "QQQ", base_seed=90042)
        assert v_spy != v_qqq

    def test_uniform_canary_differs_across_symbols_at_same_bar_ts(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        v_spy = _canary_noise_uniform(bar_ts, "SPY", base_seed=90042)
        v_qqq = _canary_noise_uniform(bar_ts, "QQQ", base_seed=90042)
        assert v_spy != v_qqq

    def test_near_constant_canary_differs_across_symbols_at_same_bar_ts(self) -> None:
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        v_spy = _canary_near_constant(bar_ts, "SPY", base_seed=90042)
        v_qqq = _canary_near_constant(bar_ts, "QQQ", base_seed=90042)
        assert v_spy != v_qqq
        # Still both tiny deviations from the constant -- symbol differentiation
        # must not break the "near constant" property.
        assert abs(v_spy - _CANARY_CONSTANT_VALUE) < 1e-3
        assert abs(v_qqq - _CANARY_CONSTANT_VALUE) < 1e-3

    def test_many_symbols_produce_a_real_spread_not_a_few_repeated_clusters(self) -> None:
        """A weak fix (e.g. only 2-3 effective buckets due to a poor hash mix)
        would still show up as clustering across a large symbol set -- assert
        real spread, not just pairwise inequality."""
        bar_ts = datetime(2026, 3, 4, 14, 30, tzinfo=UTC)
        symbols = [f"SYM{i}" for i in range(50)]
        values = [_canary_noise_gaussian(bar_ts, s, base_seed=90042) for s in symbols]
        assert len(set(values)) == 50
        assert np.std(values) > 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_canary_predictors.py::TestCanarySymbolDifferentiation -v`
Expected: FAIL with `TypeError: _canary_sub_seed() got an unexpected keyword argument` or positional arg count mismatch (current signature has no `symbol` param).

- [ ] **Step 3: Add `hashlib` import**

In `src/intelligence/feature_factory.py`, the import block currently reads (line 29-36):

```python
import bisect
import calendar
import dataclasses
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
```

Replace with:

```python
import bisect
import calendar
import dataclasses
import hashlib
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
```

- [ ] **Step 4: Fix `_canary_sub_seed` and its 3 callers**

Replace lines 1778-1811:

```python
def _canary_sub_seed(bar_ts: datetime, base_seed: int, offset: int) -> int:
    """Deterministic per-bar sub-seed derived from bar_ts + the APR base seed
    + a per-canary offset. Pure arithmetic (no Python hash()) so the value is
    stable across processes/interpreter versions -- required for
    ProcessPoolExecutor workers and for the "same bar inputs + seed -> same
    value" determinism contract. Different offsets give independently
    seeded, distributionally-distinct draws from one shared APR base seed
    (never reusing one generator/seed for two different canaries).
    """
    ts_int = int(bar_ts.timestamp() * 1000)
    return (base_seed * 1_000_003 + ts_int * 97 + offset) % (2**32)


def _canary_noise_gaussian(bar_ts: datetime, base_seed: int) -> float:
    """Pure Gaussian noise, N(0, 1) (offset=0). Negative control: must never
    carry IC."""
    rng = np.random.default_rng(_canary_sub_seed(bar_ts, base_seed, offset=0))
    return float(rng.standard_normal())


def _canary_noise_uniform(bar_ts: datetime, base_seed: int) -> float:
    """Pure Uniform[0, 1) noise (offset=1), independently seeded from the
    Gaussian canary. Two distributionally-distinct RNG sources both agreeing
    they are null is stronger pipeline-integrity evidence than one alone."""
    rng = np.random.default_rng(_canary_sub_seed(bar_ts, base_seed, offset=1))
    return float(rng.uniform(0.0, 1.0))


def _canary_near_constant(bar_ts: datetime, base_seed: int) -> float:
    """_CANARY_CONSTANT_VALUE plus tiny deterministic epsilon noise
    (offset=2) -- verifies degenerate near-zero-variance input handling
    without being bit-identical to the pure constant canary."""
    rng = np.random.default_rng(_canary_sub_seed(bar_ts, base_seed, offset=2))
    return _CANARY_CONSTANT_VALUE + _CANARY_NEAR_CONSTANT_EPSILON * float(rng.standard_normal())
```

with:

```python
def _canary_sub_seed(bar_ts: datetime, symbol: str, base_seed: int, offset: int) -> int:
    """Deterministic per-(symbol, bar) sub-seed derived from symbol + bar_ts +
    the APR base seed + a per-canary offset.

    2026-07-29 fix (todo 203): previously omitted `symbol` entirely -- every
    symbol received the IDENTICAL "random" draw at a given bar_ts, confirmed
    live in feature_vectors (bit-identical canary_noise_gaussian/uniform/
    near_constant across every pooled symbol at the same timestamp). Any
    cross-sectional measurement pooling multiple symbols (this project's own
    ic_engine.py _compute_cross_sectional_tf, or an ad hoc diagnostic doing the
    same) saw severe pseudo-replication as a result -- the true independent
    draw count per bar_ts was 1, not n_symbols, defeating these negative
    controls' entire purpose.

    Uses hashlib.md5 (not Python's built-in hash()) for the symbol component,
    mirroring ic_engine.py's _derive_worker_rng_seed(cell_key, bootstrap_seed)
    exactly -- stable across processes/interpreter versions
    (PYTHONHASHSEED-independent), required for ProcessPoolExecutor workers and
    the "same bar inputs + seed -> same value" determinism contract. The
    bar_ts/offset arithmetic component is unchanged from the original (still
    pure arithmetic, no hash() there either).
    """
    ts_int = int(bar_ts.timestamp() * 1000)
    symbol_hash = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
    return (base_seed * 1_000_003 + ts_int * 97 + offset + symbol_hash) % (2**32)


def _canary_noise_gaussian(bar_ts: datetime, symbol: str, base_seed: int) -> float:
    """Pure Gaussian noise, N(0, 1) (offset=0). Negative control: must never
    carry IC."""
    rng = np.random.default_rng(_canary_sub_seed(bar_ts, symbol, base_seed, offset=0))
    return float(rng.standard_normal())


def _canary_noise_uniform(bar_ts: datetime, symbol: str, base_seed: int) -> float:
    """Pure Uniform[0, 1) noise (offset=1), independently seeded from the
    Gaussian canary. Two distributionally-distinct RNG sources both agreeing
    they are null is stronger pipeline-integrity evidence than one alone."""
    rng = np.random.default_rng(_canary_sub_seed(bar_ts, symbol, base_seed, offset=1))
    return float(rng.uniform(0.0, 1.0))


def _canary_near_constant(bar_ts: datetime, symbol: str, base_seed: int) -> float:
    """_CANARY_CONSTANT_VALUE plus tiny deterministic epsilon noise
    (offset=2) -- verifies degenerate near-zero-variance input handling
    without being bit-identical to the pure constant canary."""
    rng = np.random.default_rng(_canary_sub_seed(bar_ts, symbol, base_seed, offset=2))
    return _CANARY_CONSTANT_VALUE + _CANARY_NEAR_CONSTANT_EPSILON * float(rng.standard_normal())
```

- [ ] **Step 5: Update the 2 production call sites**

`src/intelligence/feature_factory.py:6337-6339` (inside `compute()`, `symbol` is already the function's own parameter), replace:

```python
        canary_noise_gaussian_val = _canary_noise_gaussian(bar_ts, config.canary_rng_seed)
        canary_noise_uniform_val = _canary_noise_uniform(bar_ts, config.canary_rng_seed)
        canary_near_constant_val = _canary_near_constant(bar_ts, config.canary_rng_seed)
```

with:

```python
        canary_noise_gaussian_val = _canary_noise_gaussian(bar_ts, symbol, config.canary_rng_seed)
        canary_noise_uniform_val = _canary_noise_uniform(bar_ts, symbol, config.canary_rng_seed)
        canary_near_constant_val = _canary_near_constant(bar_ts, symbol, config.canary_rng_seed)
```

`src/intelligence/feature_factory.py:7093-7095` (inside `compute_batch()`, `symbol` is already the function's own parameter), replace:

```python
            canary_noise_gaussian_val = _canary_noise_gaussian(bar_ts, config.canary_rng_seed)
            canary_noise_uniform_val = _canary_noise_uniform(bar_ts, config.canary_rng_seed)
            canary_near_constant_val = _canary_near_constant(bar_ts, config.canary_rng_seed)
```

with:

```python
            canary_noise_gaussian_val = _canary_noise_gaussian(bar_ts, symbol, config.canary_rng_seed)
            canary_noise_uniform_val = _canary_noise_uniform(bar_ts, symbol, config.canary_rng_seed)
            canary_near_constant_val = _canary_near_constant(bar_ts, symbol, config.canary_rng_seed)
```

- [ ] **Step 6: Update every existing call site in the test file to the new signature**

`tests/unit/test_canary_predictors.py` has ~15 pre-existing calls to these 4 functions using the OLD signature (no `symbol`). Every one now breaks (positional arg shift). Fix each by inserting `"SPY"` as the 2nd argument (matching this file's existing convention of using `"SPY"` as its default test symbol in `TestFeatureFactoryIntegration`):

Lines 210-211 (`TestCanarySubSeed.test_deterministic_for_same_inputs`):
```python
        s1 = _canary_sub_seed(bar_ts, "SPY", base_seed=90042, offset=0)
        s2 = _canary_sub_seed(bar_ts, "SPY", base_seed=90042, offset=0)
```

Line 216 (`test_different_offsets_give_different_seeds`):
```python
        seeds = {_canary_sub_seed(bar_ts, "SPY", base_seed=90042, offset=o) for o in range(3)}
```

Lines 220-221 (`test_different_bar_ts_give_different_seeds`):
```python
        s1 = _canary_sub_seed(datetime(2026, 3, 4, 14, 30, tzinfo=UTC), "SPY", 90042, 0)
        s2 = _canary_sub_seed(datetime(2026, 3, 4, 14, 31, tzinfo=UTC), "SPY", 90042, 0)
```

Line 228 (`test_stable_across_repeated_calls_no_hash_randomization`):
```python
        results = [_canary_sub_seed(bar_ts, "SPY", 90042, 1) for _ in range(5)]
```

Lines 240-241 (`TestNoiseCanaries.test_gaussian_deterministic_for_fixed_seed`):
```python
        v1 = _canary_noise_gaussian(bar_ts, "SPY", base_seed=90042)
        v2 = _canary_noise_gaussian(bar_ts, "SPY", base_seed=90042)
```

Lines 246-247 (`test_uniform_deterministic_for_fixed_seed`):
```python
        v1 = _canary_noise_uniform(bar_ts, "SPY", base_seed=90042)
        v2 = _canary_noise_uniform(bar_ts, "SPY", base_seed=90042)
```

Lines 252-253 (`test_different_seed_gives_different_value`):
```python
        v1 = _canary_noise_gaussian(bar_ts, "SPY", base_seed=90042)
        v2 = _canary_noise_gaussian(bar_ts, "SPY", base_seed=1)
```

Lines 261-262 (`test_gaussian_and_uniform_are_independently_seeded`):
```python
        gaussian_val = _canary_noise_gaussian(bar_ts, "SPY", base_seed=90042)
        uniform_val = _canary_noise_uniform(bar_ts, "SPY", base_seed=90042)
```

Line 273 (`test_uniform_is_bounded_zero_to_one_across_many_bars`):
```python
            v = _canary_noise_uniform(base + timedelta(minutes=i), "SPY", base_seed=90042)
```

Line 281 (`test_gaussian_is_not_degenerate_across_many_bars`):
```python
            _canary_noise_gaussian(base + timedelta(minutes=i), "SPY", base_seed=90042) for i in range(200)
```

Line 297 (`TestConstantCanaries.test_near_constant_is_literal_plus_tiny_noise`):
```python
        v = _canary_near_constant(bar_ts, "SPY", base_seed=90042)
```

Lines 303-304 (`test_near_constant_is_deterministic`):
```python
        v1 = _canary_near_constant(bar_ts, "SPY", base_seed=90042)
        v2 = _canary_near_constant(bar_ts, "SPY", base_seed=90042)
```

Lines 309-311 (`test_near_constant_uses_a_different_sub_seed_than_noise_canaries`):
```python
        near_const_seed = _canary_sub_seed(bar_ts, "SPY", 90042, offset=2)
        gaussian_seed = _canary_sub_seed(bar_ts, "SPY", 90042, offset=0)
        uniform_seed = _canary_sub_seed(bar_ts, "SPY", 90042, offset=1)
```

- [ ] **Step 7: Run the full canary test file to verify everything passes**

Run: `.venv/bin/pytest tests/unit/test_canary_predictors.py -v`
Expected: All PASS, including the 6 new `TestCanarySymbolDifferentiation` tests and every pre-existing test with its call sites updated. `TestFeatureFactoryIntegration` tests (which call `FeatureFactory.compute`/`compute_batch` directly, not the canary helpers) require no changes — they already pass `symbol` to the top-level API.

- [ ] **Step 8: Run the full unit suite to catch any other call site**

Run: `grep -rn "_canary_sub_seed(\|_canary_noise_gaussian(\|_canary_noise_uniform(\|_canary_near_constant(" src/ services/ tests/ scripts/`
Expected: every match is either inside `src/intelligence/feature_factory.py` (the definitions/call sites just fixed) or `tests/unit/test_canary_predictors.py` (just fixed) — no other caller exists.

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: 0 failures.

- [ ] **Step 9: Commit**

```bash
git add src/intelligence/feature_factory.py tests/unit/test_canary_predictors.py
git commit -m "fix(feature_factory): seed canary noise predictors per-symbol (todo 203)"
```

---

## Task 2: Broadcast-feature audit — empirically classify which active features share the canaries' exposure

**Files:**
- Create: `scripts/ops/alpha/ops_broadcast_feature_audit.py`
- Test: `tests/unit/scripts/test_ops_broadcast_feature_audit.py`

**Interfaces:**
- Consumes: `services.ic_engine._FEATURE_NAMES`, `src.config.settings.Settings` (same pattern as `ops_lookahead_horizon_response.py`).
- Produces: `_classify_broadcast(values_by_bar_ts: dict[Any, np.ndarray], epsilon: float) -> bool` — pure function, no IO. `main()` — read-only report, no return value consumed elsewhere.

- [ ] **Step 1: Write the failing tests for the pure classification function**

Create `tests/unit/scripts/test_ops_broadcast_feature_audit.py`:

```python
"""Unit tests for ops_broadcast_feature_audit.py's pure classification logic
(2026-07-29, follow-up to todo 203).

vix_z/yield_slope_z were confirmed bit-identical across every symbol at a given
bar_ts -- correctly, since they're legitimately single macro series broadcast to
every row. Any significance test that pools symbols together has the same
pseudo-replication exposure as the (buggy) canaries for any feature with this
structure. This script classifies which active features have it, empirically.
No DB, no asyncio -- pure function tests only.
"""

from __future__ import annotations

import numpy as np

from scripts.ops.alpha.ops_broadcast_feature_audit import _classify_broadcast


class TestClassifyBroadcast:
    def test_identical_values_across_symbols_classified_broadcast(self) -> None:
        values_by_bar_ts = {
            "t1": np.array([1.5, 1.5, 1.5]),
            "t2": np.array([2.0, 2.0, 2.0]),
        }
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is True

    def test_varying_values_classified_not_broadcast(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5, 1.6, 1.4])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is False

    def test_single_bar_ts_with_variance_fails_even_if_others_pass(self) -> None:
        values_by_bar_ts = {
            "t1": np.array([1.5, 1.5, 1.5]),
            "t2": np.array([2.0, 2.1, 2.0]),
        }
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is False

    def test_bar_ts_with_fewer_than_two_symbols_is_skipped(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is True

    def test_nan_values_excluded_before_comparison(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5, 1.5, np.nan])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is True

    def test_epsilon_tolerance_allows_tiny_float_noise(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5, 1.5 + 1e-12])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is True

    def test_epsilon_tolerance_rejects_real_difference(self) -> None:
        values_by_bar_ts = {"t1": np.array([1.5, 1.5001])}
        assert _classify_broadcast(values_by_bar_ts, epsilon=1e-9) is False

    def test_empty_dict_classified_broadcast_vacuously(self) -> None:
        """No bar_ts groups to compare -- nothing contradicts 'broadcast', matching
        the loop's natural behavior (never entered, returns the initial True)."""
        assert _classify_broadcast({}, epsilon=1e-9) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/scripts/test_ops_broadcast_feature_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.ops.alpha.ops_broadcast_feature_audit'`.

- [ ] **Step 3: Write the script**

Create `scripts/ops/alpha/ops_broadcast_feature_audit.py`:

```python
#!/usr/bin/env python3
"""
ops_broadcast_feature_audit.py -- empirical audit of which active features are
"broadcast" (identical across all symbols at a given bar_ts) vs genuinely
idiosyncratic (varies by symbol).

Motivated by todo 203: canary_noise_gaussian/uniform/near_constant were found seeded
by (bar_ts, base_seed) only, no symbol -- bit-identical across every symbol at a
timestamp, confirmed live (fixed by this same session's plan, Task 1). But vix_z/
yield_slope_z were ALSO confirmed bit-identical across symbols -- correctly, since
they're legitimately single macro series broadcast to every row. Any significance
test that pools symbols together (this project's own ic_engine.py
_compute_cross_sectional_tf, or an ad hoc diagnostic doing the same) treats a
broadcast feature's (symbol, bar_ts) pairs as if they were independent observations,
when the true independent draw count per bar_ts is 1, not n_symbols -- severe
pseudo-replication, inflating apparent significance for ANY feature with this
structure, whether or not the underlying relationship is real.

feature_registry.group_name already has a 'macro' category (vix_z, yield_slope_z,
flight_quality) -- but 'session'/'calendar' features (e.g. dow_sin, hour_of_day_cos,
in_ny_session, power_hour) are ALSO derived purely from bar_ts, hence equally
broadcast, and are NOT captured by 'macro'. This script classifies EMPIRICALLY (from
actual feature_vectors data, not by trusting group_name), then cross-references
against group_name to confirm/deny the hypothesis and surface any surprises (a
feature broadcast but NOT in macro/session/calendar, or vice versa).

Read-only, no persistence -- classification is a printed report only. Whether/how to
make this classification durable (a feature_registry column) is deferred to whoever
builds a broadcast-aware significance test (a separate, real methodology decision,
not mechanical) -- building schema/persistence with no current consumer would be
premature (YAGNI).

Usage:
    python scripts/ops/alpha/ops_broadcast_feature_audit.py
    python scripts/ops/alpha/ops_broadcast_feature_audit.py --tf 1h --n-timestamps 20
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np

from services.ic_engine import _FEATURE_NAMES
from src.config.settings import Settings

_TFS = ("5m", "15m", "1h", "1d")
_DEFAULT_N_TIMESTAMPS = 20
_DEFAULT_MIN_SYMBOLS = 10
_BROADCAST_EPSILON = 1e-9
_EXPECTED_BROADCAST_GROUPS = frozenset({"macro", "session", "calendar"})

_SAMPLE_TIMESTAMPS_SQL = """
    SELECT bar_ts FROM feature_vectors
    WHERE tf = $1
    GROUP BY bar_ts
    HAVING count(DISTINCT symbol) >= $2
    ORDER BY bar_ts DESC
    LIMIT $3
"""
_FEATURE_REGISTRY_SQL = "SELECT feature_name, group_name, status FROM feature_registry"


def _classify_broadcast(values_by_bar_ts: dict[Any, np.ndarray], epsilon: float) -> bool:
    """True if EVERY bar_ts group's cross-symbol values are identical within
    `epsilon` (max - min <= epsilon) -- i.e. a 'broadcast' feature, indistinguishable
    from a single value duplicated across every symbol. Groups with fewer than 2
    finite values are skipped (nothing to compare); an empty input is vacuously
    broadcast (no evidence against it)."""
    for values in values_by_bar_ts.values():
        finite = values[np.isfinite(values)]
        if len(finite) < 2:
            continue
        if (np.nanmax(finite) - np.nanmin(finite)) > epsilon:
            return False
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tf", choices=_TFS, default=None, help="Restrict to one timeframe.")
    parser.add_argument("--n-timestamps", type=int, default=_DEFAULT_N_TIMESTAMPS)
    parser.add_argument("--min-symbols", type=int, default=_DEFAULT_MIN_SYMBOLS)
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        registry_rows = await pool.fetch(_FEATURE_REGISTRY_SQL)
        status_by_feature = {r["feature_name"]: r["status"] for r in registry_rows}
        group_by_feature = {r["feature_name"]: r["group_name"] for r in registry_rows}
        active_features = [f for f in _FEATURE_NAMES if status_by_feature.get(f) == "active"]
        feature_cols_sql = ", ".join(f'"{f}"' for f in active_features)

        tfs = (args.tf,) if args.tf else _TFS
        print("# Broadcast-Feature Audit\n")
        print(
            f"Classifying {len(active_features)} active features per tf as 'broadcast' "
            "(identical across every symbol at a bar_ts) or 'idiosyncratic' (varies by "
            f"symbol). epsilon={_BROADCAST_EPSILON}, min_symbols={args.min_symbols}, "
            f"n_timestamps={args.n_timestamps}. A broadcast feature pooled cross-"
            "sectionally has severe pseudo-replication exposure in any significance "
            "test that treats (symbol, bar_ts) pairs as independent -- see todo 203.\n"
        )

        for tf in tfs:
            ts_rows = await pool.fetch(
                _SAMPLE_TIMESTAMPS_SQL, tf, args.min_symbols, args.n_timestamps
            )
            bar_ts_list = [r["bar_ts"] for r in ts_rows]
            if not bar_ts_list:
                print(f"## tf={tf}: no bar_ts with >= {args.min_symbols} symbols -- skipped\n")
                continue

            rows = await pool.fetch(
                f"""
                SELECT bar_ts, symbol, {feature_cols_sql}
                FROM feature_vectors
                WHERE tf = $1 AND bar_ts = ANY($2::timestamptz[])
                """,
                tf,
                bar_ts_list,
            )

            values_by_feature: dict[str, dict[Any, list[float]]] = {
                f: {ts: [] for ts in bar_ts_list} for f in active_features
            }
            for r in rows:
                for f in active_features:
                    values_by_feature[f][r["bar_ts"]].append(r[f])

            broadcast_features = [
                f
                for f in active_features
                if _classify_broadcast(
                    {
                        ts: np.array(v, dtype=np.float64)
                        for ts, v in values_by_feature[f].items()
                    },
                    _BROADCAST_EPSILON,
                )
            ]

            print(f"## tf={tf} ({len(bar_ts_list)} timestamps sampled, {len(rows)} rows)\n")
            print(f"Broadcast features ({len(broadcast_features)}):")
            for f in sorted(broadcast_features):
                group = group_by_feature.get(f, "?")
                flag = "" if group in _EXPECTED_BROADCAST_GROUPS else "  <-- UNEXPECTED GROUP"
                print(f"  {f:<32} group={group}{flag}")
            print()

        print(
            "---\nA feature listed with '<-- UNEXPECTED GROUP' is broadcast in the data but "
            "not tagged macro/session/calendar in feature_registry -- worth checking whether "
            "it's mis-tagged or genuinely should carry this exposure warning. This report is "
            "informational only (no writes) -- see script docstring for why persistence is "
            "deferred."
        )
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scripts/test_ops_broadcast_feature_audit.py -v`
Expected: All 8 PASS.

- [ ] **Step 5: Run the script against live data**

Run: `.venv/bin/python scripts/ops/alpha/ops_broadcast_feature_audit.py --tf 1h`
Expected: exit 0, a report listing broadcast features for tf=1h. Confirm `vix_z`, `yield_slope_z`, `flight_quality` all appear (group=macro, no flag). Confirm session/calendar features (`dow_sin`, `hour_of_day_cos`, `in_ny_session`, `power_hour`, etc.) also appear, correctly unflagged (group=session or calendar, both in `_EXPECTED_BROADCAST_GROUPS`). Note any `<-- UNEXPECTED GROUP` output for the plan's final report to the user.

- [ ] **Step 6: Commit**

```bash
git add scripts/ops/alpha/ops_broadcast_feature_audit.py tests/unit/scripts/test_ops_broadcast_feature_audit.py
git commit -m "feat(ops): add broadcast-feature audit script (todo 203 follow-up)"
```

---

## Task 3: File a new todo for the independently-discovered `canary_acausal_placebo` anomaly

**Files:**
- Create: `.planning/todos/pending/204-canary-acausal-placebo-pooled-not-detected.md`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Confirm the next todo number is unused**

Run: `ls .planning/todos/pending/ | grep "^204"`
Expected: no output (204 is free). If NOT free, use the next actually-free number and adjust this task's filename and all cross-references in Task 4 accordingly.

- [ ] **Step 2: Write the todo**

Create `.planning/todos/pending/204-canary-acausal-placebo-pooled-not-detected.md`:

```markdown
---
status: pending
priority: P0
filed: 2026-07-29
source: re-running ops_canary_integrity_assert.py while fixing todo 203 (canary RNG seed bug)
---

# `canary_acausal_placebo` (positive control, deliberate look-ahead leak) is NOT
# clearing the POOLED significance gate in live feature_ic_scores -- ic_ci_lower=
# ic_ci_upper=0 exactly, a degenerate-computation signature, not a real small-IC
# measurement -- root cause not yet diagnosed

## Problem

Running `scripts/ops/alpha/ops_canary_integrity_assert.py` against the current
`feature_ic_scores` vintage (`training_window_end = 2025-12-24 05:15:00+00`, the only
vintage in the table) fails:

    FATAL: canary integrity violation -- canary_acausal_placebo (positive control) did
    NOT clear the significance gate in the POOLED stratum -- this pipeline failed to
    detect a deliberate look-ahead leak, meaning it cannot be trusted to detect a real
    one either

Every `canary_acausal_placebo` / POOLED row sampled has `ic_ci_lower = 0` AND
`ic_ci_upper = 0` exactly -- a zero-width CI at exactly zero. This is the signature of
a degenerate/fallback computation path (e.g. a zero-variance guard), not a genuinely
small measured IC (a real Fisher-z or bootstrap CI on thousands of observations is not
exactly [0, 0] to floating-point precision by chance).

This is NOT the same root cause as todo 203's canary RNG seeding bug --
`canary_acausal_placebo` does not use `_canary_sub_seed` at all (it reads
`closes[i+1]`/`closes[i+2]` directly, genuinely per-symbol). Confirmed the raw
`feature_vectors.canary_acausal_placebo` column has real, non-degenerate variance
corpus-wide (stddev 0.003-0.015 depending on tf, 250K-1.4M distinct values per tf) --
so the bug, whatever it is, is in how `ic_engine.py`'s cross-sectional POOLED
measurement processes this specific feature, not in the raw feature data itself.

## Hypotheses (none yet confirmed -- do NOT guess-fix)

1. **Stale vintage**: `feature_ic_scores` has never been recomputed since
   2025-12-24 -- possibly predates a code path that's since been fixed, or the
   corpus's forward_returns/feature_vectors alignment was different then. Todo 202
   already gates a full corpus rebuild for an unrelated reason (per-tf lookahead grid)
   -- this todo's finding might simply resolve once that rebuild happens, or might not.
2. **Price-sanity/outlier clipping applied to a feature that looks like a return**:
   `canary_acausal_placebo` is deliberately constructed to have the exact shape of a
   return column (`ln(close[t+2]/close[t+1])`). If `ic_engine.py`'s corrupt-print /
   `max_abs_return` sanity-guard (built for `forward_returns`, todo 148) is also
   touching feature *inputs* that resemble returns, it could be masking/clipping this
   canary's most informative (largest-magnitude) observations specifically.
3. **A genuine bug in `_compute_cross_sectional_tf`'s degenerate-feature masking**
   (`non_degenerate_mask` in `ic_math.py`) incorrectly classifying this feature as
   zero-variance for the POOLED family specifically, even though per-symbol variance
   is real.

## Fix

Not diagnosed yet. Next step: re-run `ops_canary_integrity_assert.py` after todo
202's corpus rebuild lands (cheap, free confirmation/denial of Hypothesis 1). If it
still fails post-rebuild, trace `_compute_cross_sectional_tf`'s handling of
`canary_acausal_placebo` specifically (inspect this one feature's `X_raw` column and
intermediate `non_degenerate_mask`/`ic_vec` values at a breakpoint) before touching
any production code.

## References

- `scripts/ops/alpha/ops_canary_integrity_assert.py` -- the gate that caught this
- `.planning/todos/pending/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md` -- sibling finding, confirmed different root cause
- `.planning/todos/pending/202-per-tf-lookahead-grid-downstream-consumers-stale.md` -- gates the corpus rebuild that would test Hypothesis 1
- `services/ic_engine.py` `_compute_cross_sectional_tf` -- where this would need tracing if Hypothesis 1 is ruled out
```

- [ ] **Step 3: Commit**

```bash
git add .planning/todos/pending/204-canary-acausal-placebo-pooled-not-detected.md
git commit -m "docs(todos): file todo 204 -- canary_acausal_placebo POOLED gate anomaly"
```

---

## Task 4: Correct todo 203 and PRIORITIES.md

**Files:**
- Modify: `.planning/todos/pending/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md`
- Modify: `.planning/todos/PRIORITIES.md`

**Interfaces:** None (documentation only).

- [ ] **Step 1: Correct the factual error in todo 203**

The original filing claimed `ic_engine.py`/`ensemble_ic_engine.py` "never reference
canary at all... not wired into any live check." That was wrong -- it only checked
those two files directly; `scripts/ops/alpha/ops_canary_integrity_assert.py` (todo
068, Phase 143.1-02) already exists, is wired into
`ops_corpus_pipeline_run.sh` after the ic_engine step, and is already firing (for
`canary_acausal_placebo`, now split out as todo 204). In
`.planning/todos/pending/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md`,
find the paragraph starting `production `ic_engine.py`/`ensemble_ic_engine.py`
currently never reference "canary" at all` and replace it with:

```markdown
**Correction (2026-07-29):** the original filing's claim that this control was "not
wired into any live check" was wrong -- it only checked `ic_engine.py`/
`ensemble_ic_engine.py` directly. `scripts/ops/alpha/ops_canary_integrity_assert.py`
(todo 068, Phase 143.1-02) already exists, is wired into
`ops_corpus_pipeline_run.sh` immediately after the ic_engine step, and IS already
firing today -- though for a different, independently-diagnosed reason
(`canary_acausal_placebo` not clearing its POOLED gate, split out to todo 204, NOT
caused by this todo's seeding bug). This todo's Fix item 2 ("wire canaries into a
live check") is therefore already satisfied by existing infrastructure and is
REMOVED below -- nothing new needs to be built there.
```

- [ ] **Step 2: Mark the seeding fix and broadcast audit as done, remove the now-redundant Fix item**

In the same file, find the `## Fix` section's numbered list (items 1-3) and replace
it with:

```markdown
## Fix

1. **Canary seeding -- DONE 2026-07-29** (`docs/superpowers/plans/2026-07-29-canary-seed-and-broadcast-feature-audit.md`
   Task 1): `symbol` added into `_canary_sub_seed`'s hash input, mirroring
   `ic_engine.py`'s own `_derive_worker_rng_seed(cell_key, bootstrap_seed)` pattern.
   No historical backfill triggered -- these 3 columns have zero live consumers today
   (`status='candidate'`, only read via `feature_ic_scores`, which is already gated
   on todo 202's rebuild for an unrelated reason); the next scheduled corpus rebuild
   produces correct values with no dedicated backfill needed.

2. ~~Wire canaries into a live check~~ -- REMOVED, already existed
   (`ops_canary_integrity_assert.py`, todo 068) before this todo was filed; the
   original claim otherwise was a research error, corrected above.

3. **Broadcast-feature significance testing -- AUDITED, not yet fixed** (same plan,
   Task 2): `scripts/ops/alpha/ops_broadcast_feature_audit.py` empirically classifies
   which of the 244 active features are symbol-invariant (broadcast) vs idiosyncratic,
   confirming `vix_z`/`yield_slope_z`/`flight_quality` (group='macro') plus every
   session/calendar-derived feature share this exposure. Building the actual
   broadcast-aware significance test (collapse to one row per bar_ts before
   bootstrapping, or a dedicated time-series-only test for that feature subset) is a
   real methodology decision, not mechanical implementation -- remains open, to be
   scoped as its own todo once someone is ready to design it, not bundled here.
```

- [ ] **Step 3: Update PRIORITIES.md's P0 entry**

In `.planning/todos/PRIORITIES.md`, find the `**Live P0 as of 2026-07-29:**` line
that starts with `[203](pending/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md)`
and its explanatory paragraph. Replace the whole paragraph (from `— 3 of 5 canary
negative-control...` through `...horizon-response diagnostic.`) with:

```markdown
— **seeding fix + broadcast-feature audit DONE 2026-07-29** (see plan
`docs/superpowers/plans/2026-07-29-canary-seed-and-broadcast-feature-audit.md`);
`symbol` now included in `_canary_sub_seed`'s hash, `ops_broadcast_feature_audit.py`
confirms `vix_z`/`yield_slope_z`/`flight_quality` + all session/calendar features
share the same pseudo-replication exposure the canaries had. Building an actual
broadcast-aware significance test remains open (real design question, not filed as
its own todo yet). Full end-to-end confirmation (a green
`ops_canary_integrity_assert.py` run) still waits on todo 202's corpus rebuild.
Sibling finding [204](pending/204-canary-acausal-placebo-pooled-not-detected.md) —
`canary_acausal_placebo` not clearing its POOLED gate for an unrelated, undiagnosed
reason.
```

- [ ] **Step 4: Commit**

```bash
git add .planning/todos/pending/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md .planning/todos/PRIORITIES.md
git commit -m "docs(todos): correct todo 203 scope, mark seeding fix + broadcast audit done"
```

---

## Task 5: Full-suite verification and cleanup

- [ ] **Step 1: Run the complete unit test suite**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: 0 failures.

- [ ] **Step 2: Run `/simplify` on the changed files**

Per this project's Done-Coding SOP, invoke `/simplify` on
`src/intelligence/feature_factory.py`, `scripts/ops/alpha/ops_broadcast_feature_audit.py`
before review.

- [ ] **Step 3: Run `/review`**

Per this project's Done-Coding SOP.

- [ ] **Step 4: Final commit / branch merge**

Follow CLAUDE.md's Done-Coding SOP steps 4-6 (commit on feature branch → `git
checkout main && git merge --ff-only <branch>` → prune worktree). Do NOT push unless
explicitly asked.

---

## Explicitly out of scope — do not implement here

1. **Fixing the `canary_acausal_placebo` POOLED-detection anomaly** (todo 204) — root
   cause not yet diagnosed (3 competing hypotheses, none confirmed). Fixing blind
   would violate systematic-debugging discipline.
2. **Building the broadcast-aware significance test itself** (collapsing to one row
   per bar_ts, or a dedicated time-series bootstrap for macro/session/calendar
   features) — a real methodology decision the broadcast audit (Task 2) informs but
   does not resolve. Scope as its own todo once someone is ready to design it.
3. **Any corpus-wide backfill/recompute** of `feature_vectors` or `feature_ic_scores`
   — already gated on todo 202 for an unrelated reason; this plan's fix produces
   correct values on the next scheduled rebuild with no separate backfill needed.
4. **The walk-forward/held-out validation** of the 4 genuinely-idiosyncratic candidate
   features (`range_pct_slow`, `garch_ratio`, `hmm_regime_prob`, `hmm_entropy`) from
   the prior session's shortlist bootstrap recheck — a separate follow-on to this
   measurement-integrity work, not blocked by it, not bundled into this plan.
