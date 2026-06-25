"""Unit tests for backfill_feature_factory ProcessPoolExecutor worker contract."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.backfill_feature_factory import _run_compute_worker


def test_feature_factory_worker_accepts_single_tuple_arg():
    sig = inspect.signature(_run_compute_worker)
    params = list(sig.parameters.keys())
    assert params == ["args"], f"Expected single 'args' param, got {params}"
