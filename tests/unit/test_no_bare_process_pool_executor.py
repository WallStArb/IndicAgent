"""CI guard: no new bare `ProcessPoolExecutor(` construction outside services/_batch_utils.py.

Todo 216: every batch service's ProcessPoolExecutor defaulted to letting each worker
process spawn one OpenBLAS thread per logical core -- with N worker processes already
providing process-level parallelism, that's an N x oversubscription of the same core
count (measured: 2.5x slower even in complete isolation, see
services/_batch_utils.py's limit_blas_threads() docstring). The fix consolidated every
construction site into make_worker_pool(), which wires the thread cap in via
initializer=. Nothing structurally prevented a bare ProcessPoolExecutor(...) before this
guard existed -- a future service could reintroduce the exact bug this fix closed with
no test catching it. Same allow-list pattern as
test_market_data_ohlcv_boundary.py (shared scanner: _source_grep_helpers.py).

CI-clean: no DB, no network -- pure filesystem grep.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_CONSTRUCTOR_PATTERN = re.compile(r"\bProcessPoolExecutor\(")
_SEARCH_DIRS = ("services", "scripts", "src")

# (file, reason) -- every direct ProcessPoolExecutor( construction must appear here.
_ALLOW_LIST: dict[str, str] = {
    "services/_batch_utils.py": (
        "PERMANENT: the sole construction site -- make_worker_pool() wraps it with the "
        "BLAS thread cap already wired in via initializer=. Every other service must call "
        "make_worker_pool(), never ProcessPoolExecutor(...) directly."
    ),
    "services/equity_regime_model.py": (
        "PERMANENT: deprecated Phase-144 rollback path, not currently invoked by the "
        "corpus pipeline (same status already documented in "
        "test_market_data_ohlcv_boundary.py's allow-list for this file). Migration 281's "
        "own scope lists only the 5 live services -- not worth maintaining dead code "
        "against this invariant."
    ),
}


@functools.lru_cache(maxsize=1)
def _find_constructor_references() -> dict[str, int]:
    return find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, _CONSTRUCTOR_PATTERN)


def test_every_process_pool_executor_construction_is_on_the_allow_list():
    hits = _find_constructor_references()
    assert_no_unlisted_references(
        hits,
        _ALLOW_LIST,
        what="direct ProcessPoolExecutor( construction",
        remedy=(
            "Use services._batch_utils.make_worker_pool(n_workers, "
            "blas_threads_per_worker) instead -- it wires in the OpenBLAS thread cap "
            "(todo 216) that a bare ProcessPoolExecutor(...) silently omits."
        ),
    )


def test_process_pool_executor_allow_list_has_no_stale_entries():
    hits = _find_constructor_references()
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)
