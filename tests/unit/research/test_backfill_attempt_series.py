"""Replay acceptance rules for the pre-515 series backfill (phase 187 plan 03)."""

from types import SimpleNamespace

from scripts.research.backfill_attempt_series import compare, replay_refusal

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
