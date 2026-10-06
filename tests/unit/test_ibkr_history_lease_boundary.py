"""CI guard: every IBKR historical fetch holds the one IBKR history stream.

Todo 449 measured that concurrent history streams add no throughput and mostly
time out: one stream per account is the resource. Phase 189 enforces it with the
fetcher's fail-fast advisory lock (FetcherLock, CD-09), taken by the fetcher and
every manual IBKR history tool; until plan 189-08 retires it, the historical
pipeline and the nightly still hold the legacy ResourceLease (D-29). Any module
that calls fetch_historical_bars or fetch_adjusted_daily_closes must therefore
reference one of _HOLDS_STREAM_MARKERS, unless it is on the allow-list below with
a reason and an expiry.

CI-clean: no DB, no network -- pure filesystem grep, same mechanics as
tests/unit/test_market_data_ohlcv_boundary.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._source_grep_helpers import find_pattern_references, read_source

_REPO_ROOT = Path(__file__).parent.parent.parent
# Empty parentheses (prose mentions like `fetch_historical_bars()` in docstrings)
# are not call sites; defs and calls always continue with an argument.
_FETCH_CALL_PATTERN = re.compile(r"\b(?:fetch_historical_bars|fetch_adjusted_daily_closes)\((?!\))")
_SEARCH_DIRS = ("services", "src", "scripts")
# A module referencing any of these holds the stream: the phase 189 fetcher lock, or the
# legacy lease until plan 189-08 retires it.
_HOLDS_STREAM_MARKERS = ("ResourceLease", "FetcherLock")

# (file, reason) -- every fetch call site that does not (yet) hold the stream.
# Entries whose file gains a _HOLDS_STREAM_MARKERS reference must be removed here.
_ALLOW_LIST: dict[str, str] = {
    "src/providers/ibkr.py": (
        "PERMANENT: the provider itself implements the IBKR wire calls; the lease "
        "is the caller's to hold (DAG invariant 3, ibkr.py stays process-ignorant)."
    ),
    "src/providers/base.py": (
        "PERMANENT: abstract provider interface definition, no IBKR process behind it."
    ),
    "src/providers/ibkr_adapter.py": (
        "PERMANENT: dormant v2.x streaming-stack adapter; its only consumer is "
        "services/ibkr_provider.py, inactive since the IBKR live feed went down "
        "(check `systemctl status` before citing it as live)."
    ),
    "services/backfill_feature_factory.py": (
        "TEMPORARY: corpus feature backfill fetches 1d bars lease-free; wiring the "
        "lease through it needs its own change (tracked in the phase 185 deferred "
        "items), not a rider on plan 09."
    ),
    "scripts/infrastructure/backfill/_history_fetch_item.py": (
        "TEMPORARY: library invoked only by ibkr_history_fetcher.py under FetcherLock; "
        "plan 189-08 rewrites this guard around FetcherLock."
    ),
    "scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py": (
        "TEMPORARY: one-off diagnostic probe (measured chunking/rate limits before "
        "todo 449); must hold the lease before its next use, see deferred items."
    ),
}


def _holds_stream(text: str) -> bool:
    return any(marker in text for marker in _HOLDS_STREAM_MARKERS)


def _fetch_callers() -> dict[str, int]:
    return find_pattern_references(
        _REPO_ROOT, _SEARCH_DIRS, _FETCH_CALL_PATTERN, file_globs=("*.py",)
    )


def test_every_fetch_caller_holds_the_lease_or_is_allow_listed():
    for path in _fetch_callers():
        text = read_source(*Path(path).parts)
        if _holds_stream(text):
            continue
        assert path in _ALLOW_LIST, (
            f"{path} calls fetch_historical_bars/fetch_adjusted_daily_closes without "
            "holding the IBKR history stream (CD-09: one stream per account). Take "
            "scripts.infrastructure.backfill._fetcher_lock.FetcherLock before connecting, "
            "or add an allow-list row here with a real reason and an expiry."
        )


def test_lease_allow_list_has_no_stale_entries():
    hits = _fetch_callers()
    for path in _ALLOW_LIST:
        assert path in hits, f"{path} no longer calls fetch directly; remove its allow-list entry."
        text = read_source(*Path(path).parts)
        assert not _holds_stream(
            text
        ), f"{path} now holds the stream ({_HOLDS_STREAM_MARKERS}); its allow-list entry is obsolete."
