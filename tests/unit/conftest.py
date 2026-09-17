"""Shared fixtures for tests/unit/ only (not tests/integration/)."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_ibkr_hist_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """todo 122: src/providers/ibkr.py's `_hist_rate_limiter` is a process-wide
    module-level singleton (real time.monotonic() timestamps, real asyncio.sleep()),
    never reset between tests. Any unit test exercising fetch_historical_bars() --
    even fully mocked at the ib_async layer -- still pays the real 55-req/10-min
    throttle. Once cumulative calls across the pytest session cross that limit, the
    next acquire() blocks for real, up to ~601s, with the event loop idle and zero
    CPU (confirmed via py-spy: reproducible full-suite hang at the same point in
    collection order). No unit test asserts on the limiter's own behavior, so a
    session-wide no-op is a pure test-isolation fix -- production behavior
    (ibkr.py itself) is untouched.
    """
    try:
        from src.providers import ibkr
    except ImportError:
        return

    async def _noop_acquire() -> None:
        return None

    monkeypatch.setattr(ibkr._hist_rate_limiter, "acquire", _noop_acquire)


@pytest.fixture(autouse=True)
def _prewarm_compressed_hypertable_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Todo 308: services/_batch_utils.py's `_known_compressed_hypertables` cache is
    process-lifetime, shared module state -- pre-warm it to today's real-world value
    before every unit test so (a) a mocked DB response in one test can't leak into
    another's assertions via this shared state, and (b) every pre-existing test across the
    suite that calls `bulk_update_by_key`/`compressed_hypertable_write_session` (directly
    or via a service under test) without any conn scripting for the new live query keeps
    working exactly as before -- those conn mocks were written before this cache existed
    and were never meant to answer it. Repo-wide (not just tests/unit/test_batch_utils.py)
    because several other test files exercise this machinery indirectly through the
    services they test (ic_engine, ops_regime_null_out_and_verify, regime_writer,
    ic_shrinkage_step). Tests exercising the cache-population mechanism itself
    (TestKnownCompressedHypertablesCache in test_batch_utils.py) explicitly reset to None
    first.

    This is a test-default convenience, not a drift-detection mechanism: no unit test here
    (mocked connections, no real DB) could verify the live query's result matches actual
    production schema either before or after todo 308 -- that guarantee now lives entirely
    in production code (the live query itself can't go stale the way a hardcoded literal
    could), the same way it always has for every other mocked-response default in this
    file (e.g. the sibling fixture above). Deliberately kept autouse/repo-wide rather than
    opt-in per file (an alternative code review raised): scoping it to only the ~7 files
    that need it is real, valid follow-up work, but out of scope for todo 308's own "Where"
    (this file + its tests only).
    """
    try:
        import services._batch_utils as batch_utils
    except ImportError:
        return
    monkeypatch.setattr(
        batch_utils,
        "_compressed_hypertable_names_cache",
        frozenset({"feature_vectors", "feature_ic_scores"}),
    )
