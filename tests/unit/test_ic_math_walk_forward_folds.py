"""Unit tests for build_walk_forward_folds (todo 009E, 162-01 Task 2).

Asserts bit-identical fold boundaries against an independent inline
recomputation of the same formula, parametrized over a grid of
(n_valid, n_folds, embargo_bars, min_reliable_n) -- proving the extraction
into src/intelligence/statistics/ic_math.py is faithful to the 4 inline
copies it replaces (services/ic_engine.py x3, services/ensemble_ic_engine.py
x1). DB-free.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.ic_math import build_walk_forward_folds


def _reference_folds(
    n_valid: int, n_folds: int, embargo_bars: int, min_reliable_n: int
) -> list[tuple[int, int]]:
    """Independent inline recomputation of the exact formula the 4 existing
    call sites use -- deliberately re-typed here (not imported) so this test
    actually proves equivalence rather than trivially matching itself."""
    folds = []
    for k in range(n_folds):
        train_end = int(n_valid * (k + 1) / (n_folds + 1))
        test_start = train_end + embargo_bars
        test_end = int(n_valid * (k + 2) / (n_folds + 1))
        if test_start >= test_end or (test_end - test_start) < min_reliable_n:
            continue
        folds.append((test_start, test_end))
    return folds


@pytest.mark.parametrize("n_valid", [50, 100, 500, 2000, 20000, 599999])
@pytest.mark.parametrize("n_folds", [1, 3, 5])
@pytest.mark.parametrize("embargo_bars", [1, 5, 20, 60])
@pytest.mark.parametrize("min_reliable_n", [2, 100])
def test_build_walk_forward_folds_matches_reference(
    n_valid: int, n_folds: int, embargo_bars: int, min_reliable_n: int
) -> None:
    actual = build_walk_forward_folds(n_valid, n_folds, embargo_bars, min_reliable_n)
    expected = _reference_folds(n_valid, n_folds, embargo_bars, min_reliable_n)
    assert actual == expected


def test_build_walk_forward_folds_empty_when_all_folds_too_small() -> None:
    """Every fold skipped -> empty list, not a list of Nones or a raised error."""
    result = build_walk_forward_folds(n_valid=10, n_folds=3, embargo_bars=1, min_reliable_n=100)
    assert result == []


def test_build_walk_forward_folds_returns_test_start_end_pairs() -> None:
    """Sanity: returned pairs are valid (test_start < test_end <= n_valid)."""
    n_valid = 10000
    folds = build_walk_forward_folds(n_valid, n_folds=3, embargo_bars=60, min_reliable_n=100)
    assert len(folds) == 3
    for test_start, test_end in folds:
        assert 0 <= test_start < test_end <= n_valid


def test_build_walk_forward_folds_no_config_import() -> None:
    """Pure-function contract: this module must not import ICEngineConfig or
    EnsembleICConfig (ic_math.py's own stated contract -- no dependency back
    onto either concrete caller's config dataclass)."""
    import inspect

    source = inspect.getsource(build_walk_forward_folds)
    assert "ICEngineConfig" not in source
    assert "EnsembleICConfig" not in source
    assert "ConfigService" not in source
