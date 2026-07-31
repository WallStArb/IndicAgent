"""Shared helpers for "scan -> diff against a reasoned allow-list" CI guards.

Several unit tests enforce an invariant across many files/entries (e.g. "no new
prometheus_client import", "no duplicate migration number") by scanning for
violations and checking them against a documented allow-list of accepted
exceptions. Both directions of that check -- "no new violation outside the
allow-list" and "no stale allow-list entry that no longer matches anything" --
are a plain two-set diff regardless of what's being scanned; this factors that
diff out so each guard only has to supply its scan function, its allow-list, and
its own context-specific assertion message.
"""

from __future__ import annotations

from collections.abc import Iterable


def unexpected_violations(found: Iterable[str], allow_list: Iterable[str]) -> list[str]:
    """Violations present in `found` but not accounted for by `allow_list`, sorted."""
    return sorted(set(found) - set(allow_list))


def stale_allow_list_entries(found: Iterable[str], allow_list: Iterable[str]) -> list[str]:
    """Allow-list entries that no longer correspond to any actual violation, sorted."""
    return sorted(set(allow_list) - set(found))
