"""Unit tests for services/batch_support/pool.py (BLAS thread cap, worker pool)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.batch_support.pool import limit_blas_threads, make_worker_pool


class TestLimitBlasThreads:
    """Todo 216: real-effect test (not mocked) proving limit_blas_threads() actually
    caps every detected BLAS/OpenMP thread pool, not just that it calls some API.
    Restores the original limits afterward so this test can't leak state into any
    test that runs later in the same pytest session."""

    def test_caps_thread_count_for_every_detected_pool(self) -> None:
        import threadpoolctl

        original = threadpoolctl.threadpool_limits()  # no-op snapshot, for restore below
        try:
            limit_blas_threads(1)
            info = threadpoolctl.threadpool_info()
            assert info, "no BLAS/OpenMP thread pools detected -- can't exercise the cap"
            assert all(entry["num_threads"] == 1 for entry in info)
        finally:
            original.restore_original_limits()


class TestMakeWorkerPool:
    """Todo 216: every ProcessPoolExecutor construction site was converted to this
    wrapper so the BLAS thread cap can never be silently omitted (see the CI guard in
    test_no_bare_process_pool_executor.py, which enforces that batch_support/pool.py stays
    the only file constructing one directly)."""

    def test_wires_limit_blas_threads_as_initializer(self) -> None:
        with patch("services.batch_support.pool.ProcessPoolExecutor") as mock_pool_cls:
            make_worker_pool(4, 2)

            mock_pool_cls.assert_called_once_with(
                max_workers=4,
                initializer=limit_blas_threads,
                initargs=(2,),
            )

    def test_forwards_extra_kwargs_to_process_pool_executor(self) -> None:
        with patch("services.batch_support.pool.ProcessPoolExecutor") as mock_pool_cls:
            make_worker_pool(4, 2, mp_context="fake_ctx")

            mock_pool_cls.assert_called_once_with(
                max_workers=4,
                initializer=limit_blas_threads,
                initargs=(2,),
                mp_context="fake_ctx",
            )
