"""Unit tests for ic_engine ProcessPoolExecutor worker contract + cross-sectional
bootstrap thread configuration.

Tests validate the worker function signature and ICEngineConfig's per-tf thread
dict without a live DB connection. `_derive_worker_rng_seed` is live (2026-07-29
correction: an earlier version of this docstring claimed it was removed -- it
was not; it's the per-cell seed for the circular block bootstrap CI at both the
per-symbol path (`_compute_one_regime_cell`, keyed by symbol) and the
cross-sectional path (`_compute_one_cross_sectional_cell`, keyed by
`f"{tf}:{regime_label}"`), and also backs the canary negative controls in
`src/intelligence/feature_factory.py` via the shared `src/core/rng.py` primitive
it was extracted onto during todo 203's /simplify pass).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import (
    ICEngineConfig,
    _compute_one_cross_sectional_cell,
    _compute_one_regime_cell,
    _derive_worker_rng_seed,
    _run_ic_worker,
)


def test_worker_accepts_single_tuple_arg():
    """_run_ic_worker must accept a single 'args' tuple parameter."""
    sig = inspect.signature(_run_ic_worker)
    params = list(sig.parameters.keys())
    assert params == ["args"], f"Expected single 'args' param, got {params}"


class _StubConfigService:
    """Minimal cfg stub for ICEngineConfig.from_apr() -- get_sync(key, default)
    returns a per-key override if present, else the caller's default (matching
    ConfigService's real get_sync() contract on a cold/unwarmed key)."""

    def __init__(self, overrides: dict[str, object]):
        self._overrides = overrides

    def get_sync(self, key: str, default):
        return self._overrides.get(key, default)


def test_from_apr_assembles_cross_sectional_bootstrap_threads_as_per_tf_dict():
    """ICEngineConfig.from_apr() must assemble cross_sectional_bootstrap_threads
    from 4 flat alpha.ic.cross_sectional_bootstrap_threads.{tf} APR keys into a
    {5m,15m,1h,1d} dict -- not read a single scalar key (todo 133, migration 250).
    """
    cfg = _StubConfigService(
        {
            "alpha.ic.cross_sectional_bootstrap_threads.5m": "8",
            "alpha.ic.cross_sectional_bootstrap_threads.15m": "2",
            "alpha.ic.cross_sectional_bootstrap_threads.1h": "3",
            "alpha.ic.cross_sectional_bootstrap_threads.1d": "4",
        }
    )
    config = ICEngineConfig.from_apr(cfg)

    assert config.cross_sectional_bootstrap_threads == {
        "5m": 8,
        "15m": 2,
        "1h": 3,
        "1d": 4,
    }


def test_from_apr_defaults_cross_sectional_bootstrap_threads_when_keys_absent():
    """Absent per-tf keys fall back to defaults (5m threaded, 15m/1h/1d serial)
    so behavior is safe pre-migration -- matches the dataclass field default."""
    cfg = _StubConfigService({})
    config = ICEngineConfig.from_apr(cfg)

    assert config.cross_sectional_bootstrap_threads == {
        "5m": 6,
        "15m": 1,
        "1h": 1,
        "1d": 1,
    }


def test_cross_sectional_cell_indexes_bootstrap_threads_by_tf():
    """_compute_one_cross_sectional_cell's _circular_block_bootstrap_ic call site
    must index the per-tf thread dict by tf, matching bootstrap_block_size[tf]
    one arg over (todo 133, 162-02 Task 2)."""
    source = inspect.getsource(_compute_one_cross_sectional_cell)
    assert "cross_sectional_bootstrap_threads[tf]" in source


def test_per_symbol_cell_never_indexes_cross_sectional_bootstrap_threads():
    """The per-symbol path (_compute_one_regime_cell) must never reference
    cross_sectional_bootstrap_threads at all -- it hardcodes max_workers=1
    (todo 131) because it already runs inside an n_workers-way
    ProcessPoolExecutor pool; threading on top would oversubscribe cores."""
    source = inspect.getsource(_compute_one_regime_cell)
    assert "cross_sectional_bootstrap_threads" not in source


def test_derive_worker_rng_seed_pinned_to_known_values():
    """Regression pin for the 2026-07-29 /simplify extraction (todo 203): this
    function's hash-to-int step moved to src/core/rng.py's hash_key_to_int, but
    its own combination formula (bootstrap_seed + hash % 2**31) must produce
    byte-identical output to before the extraction for every existing caller --
    a silent change here would reseed every live bootstrap CI and canary value
    corpus-wide. Values below were computed against the pre-extraction formula
    (bootstrap_seed + int(hashlib.md5(cell_key.encode()).hexdigest()[:8], 16) %
    2**31) and must never change."""
    assert _derive_worker_rng_seed("SPY", 42) == 1769859002
    assert _derive_worker_rng_seed("QQQ", 90042) == 1900974734
    assert _derive_worker_rng_seed("1h:trending_up", 12345) == 848047474
    assert _derive_worker_rng_seed("cross_sectional", 42) == 1716234523
