"""CI guard: one IBKR history stream per account, enforced by the phase 189 fetcher lock.

Todo 449 measured that concurrent history streams add no throughput and mostly time out: one
stream per account is the resource. Phase 189 enforces it with the fetcher's fail-fast advisory
lock (FetcherLock, CD-09), taken by ibkr_history_fetcher.py and by every manual IBKR history tool;
plan 189-08 retired the two-tier ResourceLease that preceded it. Any module that calls
fetch_historical_bars, fetch_adjusted_daily_closes or get_head_timestamp must therefore reference
FetcherLock in code (an import or a name, not prose in a docstring or comment), unless it is on the
allow-list below with a reason.

CI-clean: no DB, no network -- source parsing only, same mechanics as
tests/unit/test_market_data_ohlcv_boundary.py.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.unit._source_grep_helpers import find_pattern_references, read_source

_REPO_ROOT = Path(__file__).parent.parent.parent
# Empty parentheses (prose mentions like `fetch_historical_bars()` in docstrings) are not call
# sites; defs and calls always continue with an argument.
_FETCH_CALL_PATTERN = re.compile(
    r"\b(?:fetch_historical_bars|fetch_adjusted_daily_closes|get_head_timestamp)\((?!\))"
)
_SEARCH_DIRS = ("services", "src", "scripts")
_LOCK_MARKER = "FetcherLock"

# (file, reason) -- every fetch call site that does not take the lock itself. An entry whose
# file gains a FetcherLock reference in code is obsolete and must be removed.
_ALLOW_LIST: dict[str, str] = {
    "src/providers/ibkr.py": (
        "PERMANENT: the provider itself implements the IBKR wire calls; the lock is the "
        "caller's to hold (DAG invariant 3, ibkr.py stays process-ignorant)."
    ),
    "src/providers/base.py": (
        "PERMANENT: abstract provider interface definition, no IBKR process behind it."
    ),
    "src/providers/ibkr_adapter.py": (
        "PERMANENT: dormant v2.x streaming-stack adapter; its only consumer is "
        "services/ibkr_provider.py, inactive since the IBKR live feed went down "
        "(check `systemctl status` before citing it as live)."
    ),
    "scripts/infrastructure/backfill/_history_fetch.py": (
        "PERMANENT: helper library invoked only by ibkr_history_fetcher.py, which holds "
        "FetcherLock for the whole run (no CLI since plan 189-08)."
    ),
    "scripts/infrastructure/backfill/_history_fetch_item.py": (
        "PERMANENT: helper library invoked only by ibkr_history_fetcher.py, which holds "
        "FetcherLock for the whole run."
    ),
    "services/backfill_feature_factory.py": (
        "TEMPORARY (retire: todo 506): the phase 186 rebuild writer's --fetch-only stage "
        "fetches 1d bars without the lock; editing it while 186-26's rebuild is pending can "
        "discard the rebuild's cells, so the lock wiring waits for that rebuild. Not scheduled "
        "today, so it never runs beside the fetcher."
    ),
}


def _references_lock_in_code(text: str) -> bool:
    """True when the module imports or names FetcherLock outside docstrings and comments."""
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Name) and node.id == _LOCK_MARKER:
            return True
        if isinstance(node, ast.Attribute) and node.attr == _LOCK_MARKER:
            return True
        if isinstance(node, ast.alias) and node.name == _LOCK_MARKER:
            return True
    return False


def _fetch_callers() -> dict[str, int]:
    return find_pattern_references(
        _REPO_ROOT, _SEARCH_DIRS, _FETCH_CALL_PATTERN, file_globs=("*.py",)
    )


def test_every_fetch_caller_takes_the_fetcher_lock_or_is_allow_listed():
    for path in _fetch_callers():
        if _references_lock_in_code(read_source(*Path(path).parts)):
            continue
        assert path in _ALLOW_LIST, (
            f"{path} calls an IBKR history fetch without taking the fetcher lock (CD-09: one "
            "stream per account). Take scripts.infrastructure.backfill._fetcher_lock.FetcherLock "
            "before connecting, or add an allow-list row here with a real reason."
        )


def test_lock_allow_list_has_no_stale_entries():
    hits = _fetch_callers()
    for path in _ALLOW_LIST:
        assert (
            path in hits
        ), f"{path} no longer calls a fetch directly; remove its allow-list entry."
        assert not _references_lock_in_code(
            read_source(*Path(path).parts)
        ), f"{path} now takes FetcherLock; its allow-list entry is obsolete."


def test_the_lock_marker_ignores_prose():
    assert not _references_lock_in_code('"""Runs under FetcherLock."""\n# FetcherLock\nx = 1\n')
    assert _references_lock_in_code("from m import FetcherLock\n")
    assert _references_lock_in_code("import m\nlock = m.FetcherLock('dsn')\n")


def test_no_module_takes_the_retired_history_lease():
    """Plan 189-08 retired the ResourceLease on the IBKR history stream; the generic
    src/core/resource_lease.py stays (CD-09) but no IBKR history caller may use it."""
    for path in _fetch_callers():
        assert "ResourceLease" not in read_source(*Path(path).parts), path
