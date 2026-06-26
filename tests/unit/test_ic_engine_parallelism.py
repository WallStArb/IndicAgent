"""Unit tests for ic_engine ProcessPoolExecutor worker contract.

Tests validate the worker function signature without a live DB connection.
_derive_worker_rng_seed was removed when the circular block bootstrap was
replaced by Fisher z-transform CI (no RNG needed).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _run_ic_worker


def test_worker_accepts_single_tuple_arg():
    """_run_ic_worker must accept a single 'args' tuple parameter."""
    sig = inspect.signature(_run_ic_worker)
    params = list(sig.parameters.keys())
    assert params == ["args"], f"Expected single 'args' param, got {params}"
