"""Unit tests for ic_engine ProcessPoolExecutor worker contract.

Tests validate the worker function signature and RNG derivation without
a live DB connection.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _derive_worker_rng_seed, _run_ic_worker


def test_worker_accepts_single_tuple_arg():
    """_run_ic_worker must accept a single 'args' tuple parameter."""
    sig = inspect.signature(_run_ic_worker)
    params = list(sig.parameters.keys())
    assert params == ["args"], f"Expected single 'args' param, got {params}"


def test_derive_worker_rng_seed_deterministic():
    """Same symbol + bootstrap_seed must always produce the same worker seed."""
    seed1 = _derive_worker_rng_seed("SPY", 42)
    seed2 = _derive_worker_rng_seed("SPY", 42)
    assert seed1 == seed2


def test_derive_worker_rng_seed_differs_by_symbol():
    """Different symbols must produce different worker seeds."""
    seed_spy = _derive_worker_rng_seed("SPY", 42)
    seed_tlt = _derive_worker_rng_seed("TLT", 42)
    assert seed_spy != seed_tlt


def test_derive_worker_rng_seed_valid_range():
    """Derived seed must be a non-negative integer (valid for np.random.default_rng)."""
    seed = _derive_worker_rng_seed("GLD", 42)
    assert isinstance(seed, int)
    assert seed >= 0


def test_rng_from_derived_seed_is_reproducible():
    """Two RNGs from the same derived seed must produce identical sequences."""
    seed = _derive_worker_rng_seed("EWT", 42)
    rng1 = np.random.default_rng(seed)
    rng2 = np.random.default_rng(seed)
    assert np.array_equal(rng1.random(10), rng2.random(10))
