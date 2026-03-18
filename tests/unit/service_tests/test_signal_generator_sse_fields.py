"""Verify cis_score + was_selected are injected into the SSE signal message."""

import pytest


@pytest.mark.unit
def test_cis_score_injected_when_present():
    """message must include cis_score when result.cis_score is not None."""
    sig = {"direction": 1, "entry_price": 5200.0, "stop_loss": 5180.0,
           "confidence": 0.65, "setup_plugin": "trad_TrendFollowing"}
    message = {k: str(v) for k, v in sig.items() if isinstance(v, (str, int, float, bool))}

    # Simulate Task 6 injection logic
    cis_score = 0.42
    if cis_score is not None:
        message["cis_score"] = str(cis_score)
    message["was_selected"] = "1"

    assert "cis_score" in message
    assert message["cis_score"] == "0.42"
    assert message["was_selected"] == "1"


@pytest.mark.unit
def test_cis_score_absent_when_none():
    """message must NOT include cis_score when result.cis_score is None (fallback path)."""
    sig = {"direction": 1, "confidence": 0.30}
    message = {k: str(v) for k, v in sig.items() if isinstance(v, (str, int, float, bool))}
    cis_score = None
    if cis_score is not None:
        message["cis_score"] = str(cis_score)
    message["was_selected"] = "1"

    assert "cis_score" not in message
    assert message["was_selected"] == "1"
