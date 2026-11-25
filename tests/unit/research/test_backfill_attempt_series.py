"""Replay acceptance rules for the pre-515 series backfill (phase 187 plan 03)."""

from datetime import date
from types import SimpleNamespace

import numpy as np

from scripts.research.backfill_attempt_series import (
    compare,
    pre_e17,
    replay_refusal,
    series_differs,
)
from src.intelligence.research.ledger import AttemptSeries

DECISION = {
    "decision": {
        "t": 2.5,
        "p": 0.01,
        "se": 0.1,
        "lag": 8,
        "n_sessions": 3767,
        "mean_session_pnl": 0.001,
        "memory_sessions": 20,
    }
}


def test_equal_decision_has_no_diff():
    assert compare(DECISION, {"decision": dict(DECISION["decision"])}) == {}


def test_any_differing_field_is_reported():
    replayed = {"decision": {**DECISION["decision"], "t": 2.5000000001}}
    assert compare(DECISION, replayed) == {"t": [2.5, 2.5000000001]}


def test_missing_decision_differs():
    assert set(compare(DECISION, {"stage": "S3"})) == set(DECISION["decision"])


def _spec(**panel):
    base = {"transform": None, "total_return": None, "members_universe": None}
    return SimpleNamespace(panel=SimpleNamespace(**{**base, **panel}))


def test_snapshot_only_spec_replays():
    assert replay_refusal(_spec()) is None


def test_spec_reading_beyond_the_snapshot_is_refused():
    assert replay_refusal(_spec(transform="session_legs")) is not None
    assert replay_refusal(_spec(members_universe="us_session_equity")) is not None
    assert replay_refusal(_spec(total_return=object())) is not None


SERIES = AttemptSeries(
    sessions=np.array(["2020-01-02", "2020-01-03"], dtype="datetime64[D]"),
    values=np.array([0.1, -0.2]),
)


def _stored(sessions, d_s):
    return {"sessions": sessions, "d_s": d_s}


def test_no_stored_series_never_differs():
    assert not series_differs(_stored(None, None), SERIES)


def test_bit_identical_stored_series_is_equal():
    stored = _stored([date(2020, 1, 2), date(2020, 1, 3)], [0.1, -0.2])
    assert not series_differs(stored, SERIES)


def test_stored_series_differs_on_one_ulp_a_session_or_a_lost_replay():
    dates = [date(2020, 1, 2), date(2020, 1, 3)]
    assert series_differs(_stored(dates, [0.1, np.nextafter(-0.2, 0)]), SERIES)
    assert series_differs(_stored([date(2020, 1, 2), date(2020, 1, 6)], [0.1, -0.2]), SERIES)
    assert series_differs(_stored(dates, [0.1, -0.2]), None)


def test_a_decision_without_memory_is_pre_e17():
    assert not pre_e17({"evidence": DECISION})
    e16 = {k: v for k, v in DECISION["decision"].items() if k != "memory_sessions"}
    assert pre_e17({"evidence": {"decision": e16}})
    assert pre_e17({"evidence": None})  # nothing recorded is not an E17 record either


def test_the_replay_query_excludes_sweep_attempts_by_spec_path(monkeypatch):
    """A sweep attempt (E21) has a JSON spec and no git blob: the backfill and the parity gate
    never read it, and the exclusion is bound to the one shared path prefix."""
    import asyncio

    from scripts.research import backfill_attempt_series as module
    from src.intelligence.research.ledger import SWEEP_SPEC_PATH_PREFIX

    calls = []

    class _Conn:
        async def fetch(self, sql, *args):
            calls.append((sql, args))
            return []

        async def close(self):
            pass

    async def _connect(dsn):
        return _Conn()

    monkeypatch.setattr(module, "connect_with_codecs", _connect)
    assert asyncio.run(module._rows("dsn", True)) == []
    sql, args = calls[0]
    assert "r.spec_path NOT LIKE $2 || '/%'" in sql
    assert args == (True, SWEEP_SPEC_PATH_PREFIX)
