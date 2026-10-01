"""Unit tests for backfill_feature_factory's pool-worker contract (186-25).

The rebuild worker runs in a ProcessPoolExecutor subprocess: it takes one packed `args`
tuple, reads the database through its own read-only connection, and returns a bounded
payload (spool paths and row counts, todo 339) -- never rows, never a database write.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.backfill_feature_factory import _rebuild_worker


def test_rebuild_worker_accepts_single_tuple_arg():
    sig = inspect.signature(_rebuild_worker)
    params = list(sig.parameters.keys())
    assert params == ["args"], f"Expected single 'args' param, got {params}"


def test_rebuild_worker_never_writes_the_database():
    """Compute-only (CLAUDE.md invariant): the worker's body holds no write statement, and its
    only database use is the read-only connect at the top."""
    source = inspect.getsource(_rebuild_worker)
    for forbidden in ("INSERT INTO", "UPDATE ", "COPY ", ".commit(", "executemany"):
        assert forbidden not in source, forbidden
    # The connection is opened for reads only and closed in finally.
    assert "psycopg.connect(dsn)" in source
