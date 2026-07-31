"""CI guard: no live `prometheus_client` import anywhere in src/ or services/.

CLAUDE.md is explicit: "Metrics: src/observability/metrics.py (direct OTel SDK --
prometheus_client fully removed) ... Never import prometheus_client." Until this test,
that rule was convention-only -- no ruff banned-api rule (flake8-tidy-imports/TID251 is not
configured in pyproject.toml today) and no grep-test enforced it (todo 157). A future
regression -- e.g. someone copying a snippet from an older commit or a tutorial that still
uses prometheus_client -- would only be caught by a human reviewer noticing in review.

As of the todo 157 investigation, there are zero real imports: the only 3 hits in the whole
codebase are comments explaining the historical migration away from prometheus_client, not
live import statements. This test only matches actual `import`/`from ... import` statements.

Unlike the other CI guards in this project, there is no allow-list here: prometheus_client
is fully removed per CLAUDE.md, and there is no legitimate exception to grandfather in --
any match is a real regression, full stop.

CI-clean: no DB, no network -- pure filesystem grep.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_BANNED_IMPORT_PATTERN = re.compile(
    r"^\s*(?:import\s+prometheus_client\b|from\s+prometheus_client\b)"
)
_SEARCH_DIRS = ("src", "services")


def test_no_prometheus_client_import_in_src_or_services():
    hits: dict[str, int] = {}
    for search_dir in _SEARCH_DIRS:
        for path in (_REPO_ROOT / search_dir).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            count = sum(1 for line in text.splitlines() if _BANNED_IMPORT_PATTERN.match(line))
            if count:
                hits[str(path.relative_to(_REPO_ROOT))] = count
    assert not hits, (
        f"Live `prometheus_client` import(s) found, banned by CLAUDE.md: {hits}. "
        "Use src/observability/metrics.py's direct OTel SDK instead -- prometheus_client "
        "is fully removed from this codebase, there is no legitimate exception."
    )
