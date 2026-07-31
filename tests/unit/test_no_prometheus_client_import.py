"""CI guard: no live `prometheus_client` import anywhere in src/ or services/.

CLAUDE.md is explicit: "Metrics: src/observability/metrics.py (direct OTel SDK --
prometheus_client fully removed) ... Never import prometheus_client." Until this test,
that rule was convention-only -- no ruff banned-api rule (flake8-tidy-imports/TID251 is not
configured in pyproject.toml today) and no grep-test enforced it (todo 157). A future
regression -- e.g. someone copying a snippet from an older commit or a tutorial that still
uses prometheus_client -- would only be caught by a human reviewer noticing in review.

As of the todo 157 investigation, there are zero real imports: the only 3 hits in the whole
codebase are comments explaining the historical migration away from prometheus_client, not
live import statements. This test only matches actual `import`/`from ... import` statements,
so it starts clean with an empty allow-list and stays that way unless a real regression lands.

CI-clean: no DB, no network -- pure filesystem grep.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_BANNED_IMPORT_PATTERN = re.compile(
    r"^\s*(?:import\s+prometheus_client\b|from\s+prometheus_client\b)"
)
_SEARCH_DIRS = ("src", "services")

# {file: reason} -- deliberately empty. Per CLAUDE.md, prometheus_client is fully removed;
# any new match here is a real regression, not a legitimate exception to grandfather in.
_ALLOW_LIST: dict[str, str] = {}


@functools.lru_cache(maxsize=1)
def _find_prometheus_client_imports() -> dict[str, int]:
    """Returns {relative_path: match_count} for every .py file under _SEARCH_DIRS with a
    live `import prometheus_client` / `from prometheus_client import ...` statement."""
    hits: dict[str, int] = {}
    for search_dir in _SEARCH_DIRS:
        for path in (_REPO_ROOT / search_dir).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            count = sum(1 for line in text.splitlines() if _BANNED_IMPORT_PATTERN.match(line))
            if count:
                hits[str(path.relative_to(_REPO_ROOT))] = count
    return hits


def test_no_prometheus_client_import_in_src_or_services():
    hits = _find_prometheus_client_imports()
    unexpected = set(hits) - set(_ALLOW_LIST)
    assert not unexpected, (
        f"Live `prometheus_client` import(s) found, banned by CLAUDE.md: {unexpected}. "
        "Use src/observability/metrics.py's direct OTel SDK instead. If this is somehow a "
        "genuine, deliberate exception, add it to _ALLOW_LIST in this file with a one-line "
        "reason -- but there should be no legitimate reason, prometheus_client is fully "
        "removed from this codebase."
    )


def test_prometheus_client_allow_list_has_no_stale_entries():
    hits = _find_prometheus_client_imports()
    stale = set(_ALLOW_LIST) - set(hits)
    assert not stale, (
        f"Allow-list entries that no longer match any prometheus_client import: {stale}. "
        "Remove the stale entry."
    )
