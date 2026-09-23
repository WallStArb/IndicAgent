"""The compute-readiness predicate derives its required count from the bound timeframe list.

174 review WR-07: the timeframe stack was a module literal in four places and the
predicate hard-coded `= 4`, so reconfiguring `feature.factory.target_timeframes` would
silently leave promotion testing a different stack than the factory computes.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from scripts.analysis.instrument_compute_eligibility_audit import (
    COMPUTE_READY_PREDICATE_SQL,
    load_compute_timeframes,
)


def test_predicate_has_no_literal_timeframe_count():
    assert not re.search(r"=\s*\d+\s*$", COMPUTE_READY_PREDICATE_SQL, re.MULTILINE)
    assert COMPUTE_READY_PREDICATE_SQL.count("cardinality(%(timeframes)s::text[])") == 2


def _conn_returning(row):
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_load_compute_timeframes_reads_the_factory_key():
    conn, cursor = _conn_returning(('["1h", "1d"]',))
    assert load_compute_timeframes(conn) == ["1h", "1d"]
    assert cursor.execute.call_args.args[1] == ("feature.factory.target_timeframes",)


def test_load_compute_timeframes_fails_loudly_when_unset():
    conn, _ = _conn_returning(None)
    with pytest.raises(RuntimeError, match="not set"):
        load_compute_timeframes(conn)


def test_promote_compute_dimension_binds_apr_timeframes():
    from scripts.infrastructure import universe_expansion_promote_compute_eligible as mod

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    with patch.object(mod, "load_compute_timeframes", return_value=["1h", "1d"]):
        mod._fetch_candidates(conn, mod._DIMENSION_CONFIG["compute"])
    assert cursor.execute.call_args.args[1] == {"timeframes": ["1h", "1d"]}


def test_promote_compute_1d_dimension_binds_nothing():
    from scripts.infrastructure import universe_expansion_promote_compute_eligible as mod

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    with patch.object(mod, "load_compute_timeframes") as mock_load:
        mod._fetch_candidates(conn, mod._DIMENSION_CONFIG["compute_1d"])
    mock_load.assert_not_called()
    assert cursor.execute.call_args.args[1] == {}
