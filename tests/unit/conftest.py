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

    async def _noop_acquire() -> float:
        return 0.0  # matches acquire()'s slept-seconds return (todo 485)

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


@pytest.fixture(autouse=True)
def _skip_decompress_headroom_preflight(request, monkeypatch):
    """Todo 426: compressed_hypertable_write_session's disk-headroom pre-flight issues its own
    queries and reads the host filesystem, which the scripted fake connections throughout
    tests/unit/ don't model. It is tested directly in test_batch_utils.py; tests that need the
    real pre-flight mark themselves `real_headroom_check`."""
    if request.node.get_closest_marker("real_headroom_check"):
        return
    try:
        import services._batch_utils as batch_utils
    except ImportError:
        return

    async def _noop_async(conn, hypertable):
        return None

    monkeypatch.setattr(batch_utils, "_assert_decompress_headroom", lambda conn, hypertable: None)
    monkeypatch.setattr(batch_utils, "_assert_decompress_headroom_async", _noop_async)


# --- todo 494: unit tests must not reach the live database --------------------------

# The commands a unit test may never spawn unless the test carries the opt-in marker: the live
# writers the three 185-18 leaks used (test_nightly_lease ran `bar_derivation --stage grid
# --apply` nine times against the live DB). Matched per argv token, not as a joined-line
# substring: `git cat-file <sha>:scripts/ops/...` mentions a writer path without spawning it.
# A writer shape is the script path as its own token, the -m module form, or a scripts/ops
# path token.
_LIVE_WRITER_MODULES = ("bar_derivation", "feature_vector_pipeline")


def _names_live_writer(pieces: list[str]) -> bool:
    for piece in pieces:
        if any(
            piece.endswith(f"{module}.py") or piece == f"services.{module}"
            for module in _LIVE_WRITER_MODULES
        ):
            return True
        if piece == "-m":
            continue
        if piece.startswith("scripts.ops.") or piece.startswith("scripts/ops/"):
            return True
    # "-m services.bar_derivation": the module token follows -m in the same joined line.
    joined = " ".join(pieces)
    return any(f"-m services.{module}" in joined for module in _LIVE_WRITER_MODULES)


@pytest.fixture(autouse=True)
def _refuse_live_writer_spawns(request, monkeypatch):
    """todo 494: subprocess.run/Popen/call/check_* naming a live writer raise, instead of
    deriving real canonical rows into the production database from a unit test. Opt out with
    the `live_writer_subprocess` marker (a deliberate spawn, reviewed in the test's docstring)."""
    if request.node.get_closest_marker("live_writer_subprocess"):
        return
    import subprocess

    real = {
        name: getattr(subprocess, name)
        for name in ("run", "Popen", "call", "check_call", "check_output")
    }

    def _guarded(name, real_fn):
        def wrapper(*args, **kwargs):
            pieces = []
            for arg in args:
                if isinstance(arg, (str, bytes)):
                    pieces.append(arg.decode() if isinstance(arg, bytes) else arg)
                elif isinstance(arg, (list, tuple)):
                    pieces.extend(str(part) for part in arg)
            pieces.extend(str(value) for value in kwargs.values())
            if _names_live_writer(pieces):
                joined = " ".join(pieces)
                raise AssertionError(
                    "todo 494: a unit test is spawning a live writer "
                    f"(subprocess.{name}: {joined[:200]}); the database is not a fixture. "
                    "If the spawn is deliberate, mark the test live_writer_subprocess."
                )
            return real_fn(*args, **kwargs)

        wrapper.__name__ = name
        return wrapper

    for name, real_fn in real.items():
        monkeypatch.setattr(subprocess, name, _guarded(name, real_fn))


@pytest.fixture(autouse=True)
def _live_dsn_connections_are_read_only(request, monkeypatch):
    """todo 494: a connection a unit test opens to the live database is forced read-only, so a
    write statement fails loud instead of appending to production. Read-only unit readers (the
    boundary test's allow-list documents them) keep working: advisory locks and session SETs are
    not writes. A test that genuinely needs a writable live connection is a defect; the
    `live_db` marker exists only for the guard's own tests."""
    if request.node.get_closest_marker("live_db"):
        return

    def _is_live(*args, **kwargs) -> bool:
        """The connect arguments name the live database. Joined strings, so both the DSN form
        and the host/database keyword form are caught."""
        text = " ".join(
            str(part) for part in (*args, *kwargs.values()) if isinstance(part, (str, bytes))
        )
        return "indicagent" in text and "indicagent_test" not in text

    def _force_read_only(conn):
        # In autocommit (the advisory-lock leases connect this way) leave the mode alone: the
        # SET commits session-wide immediately. Otherwise flip to autocommit for the one
        # statement so the SET is not stranded inside the caller's first transaction, then
        # restore the caller's mode; its later transactions begin read-only.
        was = conn.autocommit
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SET default_transaction_read_only = on")
        cur.close()
        conn.autocommit = was
        return conn

    import asyncpg as _asyncpg
    import psycopg as _psycopg

    real_psycopg_connect = _psycopg.connect

    def _psycopg_guarded(*args, **kwargs):
        live = _is_live(*args, **kwargs)
        conn = real_psycopg_connect(*args, **kwargs)
        try:
            if live or _is_live(conn.info.dbname):
                return _force_read_only(conn)
        except Exception:
            conn.close()
            raise
        return conn

    monkeypatch.setattr(_psycopg, "connect", _psycopg_guarded)

    real_asyncpg_connect = _asyncpg.connect

    async def _asyncpg_guarded(*args, **kwargs):
        live = _is_live(*args, **kwargs)
        conn = await real_asyncpg_connect(*args, **kwargs)
        try:
            if live:
                await conn.execute("SET default_transaction_read_only = on")
        except Exception:
            await conn.close()
            raise
        return conn

    monkeypatch.setattr(_asyncpg, "connect", _asyncpg_guarded)

    if hasattr(_asyncpg, "create_pool"):
        real_create_pool = _asyncpg.create_pool

        def _create_pool_guarded(*args, **kwargs):
            if _is_live(*args, **kwargs):
                raise AssertionError(
                    "todo 494: a unit test is opening a live connection pool "
                    "(asyncpg.create_pool); the database is not a fixture."
                )

            return real_create_pool(*args, **kwargs)

        monkeypatch.setattr(_asyncpg, "create_pool", _create_pool_guarded)
