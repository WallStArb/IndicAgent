"""S6 attempt series and headline numbers (phase 187 plan 02, migration 515, E18)."""

import numpy as np

from src.intelligence.research.ledger import AttemptSeries, _headline

SESSIONS = np.array(["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07"], dtype="datetime64[D]")


def test_series_keeps_tested_sessions_only():
    series = AttemptSeries.from_timing(SESSIONS, np.array([np.nan, 0.1, np.nan, -0.2]))
    assert series.sessions.tolist() == SESSIONS[[1, 3]].tolist()
    assert series.values.tolist() == [0.1, -0.2]
    assert [d.isoformat() for d in series.sessions_as_dates()] == ["2020-01-03", "2020-01-07"]


def test_no_tested_session_means_no_series():
    assert AttemptSeries.from_timing(SESSIONS, np.full(4, np.nan)) is None


def test_headline_from_decision_and_series():
    series = AttemptSeries.from_timing(SESSIONS, np.array([0.1, 0.2, 0.3, 0.4]))
    payload = {
        "decision": {
            "t": 2.5,
            "p": 0.006,
            "annualized_sharpe": 0.9,
            "mean_session_pnl": 0.001,
            "n_sessions": 4,
        },
        "turnover_per_session": 2.0,
    }
    t, p, sharpe, mean, turnover, n, start, end = _headline(payload, series)
    assert (t, p, sharpe, mean, turnover, n) == (2.5, 0.006, 0.9, 0.001, 2.0, 4)
    assert (start.isoformat(), end.isoformat()) == ("2020-01-02", "2020-01-07")


def test_refusal_evidence_has_no_headline():
    assert _headline({"stage": "S3", "error": "x"}, None) == (None,) * 8
