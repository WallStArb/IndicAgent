"""Worker pool construction and BLAS thread limits for compute-only process pools."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Any


def limit_blas_threads(n_threads: int) -> None:
    """ProcessPoolExecutor `initializer`: caps this worker's BLAS thread pool.

    Without this, every worker's numpy/scipy/hmmlearn calls default to spawning
    one OpenBLAS thread per logical core (24 on this host) -- with N ProcessPoolExecutor
    workers already providing process-level parallelism, that's an N x oversubscription
    of the same core count. Measured (todo 216): an isolated single-process GaussianHMM
    fit (50k rows, 5D obs, K=5 -- regime_writer's real shape) ran 2.5x slower at the
    default 24 threads than capped to 1 (4.65s vs 1.86s), with zero contention from other
    processes. Small-state HMM/rank-IC workloads operate on tiny per-step matrices; BLAS
    thread coordination overhead exceeds any parallel gain, even before counting the real
    12-worker contention this fixes on top of that.

    Thread count does change the exact floating-point result (not just wall time) --
    verified empirically, not assumed: the same fit at threads=1 vs threads=24 produced
    means_/transmat_/covars_ differing at ~1e-10 absolute, from BLAS reduction-order
    noise. But the discrete Viterbi state assignments -- what actually gets written as
    `regime` -- were byte-identical across all 50,000 observations in that test. This is
    why blas_threads_per_worker is classified OPERATIONAL, not COMPUTATIONAL, in
    ic_engine.py's fingerprint system (see _OPERATIONAL_CONFIG_FIELDS): it moves the
    16th significant digit, not the labels or IC values anything downstream reads.

    Called once per worker at pool startup (fork or spawn, both call the initializer
    before any task runs) -- not a context manager, the limit is meant to persist for
    the worker's whole lifetime.

    threadpoolctl.threadpool_limits() only reaches ALREADY-LOADED BLAS libraries (it
    calls into the runtime library's own thread-count API, it does not set an env var)
    -- if OpenBLAS isn't loaded yet when this runs, the call is a silent no-op and the
    worker's later `import numpy` gets an uncapped pool. The explicit `import numpy`
    below (this module's own top-level import would happen to cover it too, since
    unpickling this function to call it as a ProcessPoolExecutor initializer requires
    importing this module first -- but that's an incidental guarantee a future edit
    could break without any test catching it) makes the load-before-cap ordering
    load-bearing and self-contained instead.
    """
    import numpy  # noqa: F401  -- load-bearing: must be loaded before threadpool_limits()
    import threadpoolctl

    threadpoolctl.threadpool_limits(n_threads)


def _chained_worker_init(blas_threads_per_worker: int, initializer: Any, initargs: tuple) -> None:
    """make_worker_pool's composition: the BLAS cap always runs first, then the caller's
    initializer unchanged. Module-level so it pickles under forkserver/spawn contexts."""
    limit_blas_threads(blas_threads_per_worker)
    initializer(*initargs)


def make_worker_pool(
    n_workers: int,
    blas_threads_per_worker: int,
    initializer: Any | None = None,
    initargs: tuple = (),
    **kwargs: Any,
) -> ProcessPoolExecutor:
    """ProcessPoolExecutor with the BLAS thread cap already wired in (todo 216).

    Every batch service's ProcessPoolExecutor should be constructed through this, not
    directly -- a bare ProcessPoolExecutor(...) silently reintroduces the OpenBLAS
    oversubscription bug limit_blas_threads() fixes, with no test to catch the omission.
    kwargs forward to ProcessPoolExecutor unchanged (e.g. mp_context=).

    A caller initializer (e.g. the rebuild writer installing its shared macro externals
    once per worker instead of pickling them into every task) runs AFTER the BLAS cap,
    never instead of it.
    """
    if initializer is None:
        worker_init: Any = limit_blas_threads
        worker_initargs: tuple = (blas_threads_per_worker,)
    else:
        worker_init = _chained_worker_init
        worker_initargs = (blas_threads_per_worker, initializer, initargs)
    return ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=worker_init,
        initargs=worker_initargs,
        **kwargs,
    )
