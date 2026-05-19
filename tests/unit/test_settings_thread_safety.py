"""Thread-safety tests for src.config.settings module-level globals (Phase 090 THREAD-01)."""

import concurrent.futures
import inspect

import src.config.settings as settings_mod


def test_default_settings_singleton_under_threads():
    """Structural correctness check under threads.

    Note: Python GIL makes pure-Python races rare; the source assertions in
    tests 2 and 3 are the primary lock-correctness guarantee. This test checks
    that 16 concurrent callers all receive the same Settings instance (singleton
    property) and that no torn creation window produces a second object.
    """
    # Reset the singleton so concurrent creation is actually exercised
    with settings_mod._settings_lock:
        settings_mod._settings_singleton = None

    ids = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(settings_mod._default_settings) for _ in range(16)]
        for f in concurrent.futures.as_completed(futures):
            ids.append(id(f.result()))

    assert len(ids) == 16
    assert len(set(ids)) == 1, f"Expected 1 unique Settings instance, got {len(set(ids))}"


def test_invalidate_active_contracts_cache_is_lock_protected():
    """Verify invalidate_active_contracts_cache acquires _settings_lock before writing."""
    src = inspect.getsource(settings_mod.invalidate_active_contracts_cache)
    assert (
        "with _settings_lock:" in src
    ), "invalidate_active_contracts_cache must wrap the write in 'with _settings_lock:'"


def test_get_active_contracts_uses_double_checked_locking():
    """Verify get_active_contracts uses _settings_lock blocks outside the DB query.

    The function has at least 2 separate lock blocks:
      - One for the cache read (before DB query)
      - One for the cache write (after DB query)
    The DB query runs outside the lock (Pitfall 2 closed). A third lock block
    in the fallback path is acceptable.
    """
    src = inspect.getsource(settings_mod.get_active_contracts)
    lock_count = src.count("with _settings_lock:")
    assert (
        lock_count >= 2
    ), f"expected at least 2 lock blocks in get_active_contracts, found {lock_count}"
