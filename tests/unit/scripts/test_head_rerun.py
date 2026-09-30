"""Unit tests for the D-27 step 2 head re-run (scripts/ops/bars/ops_head_rerun.py)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from scripts.ops.bars import ops_head_rerun as mod
from scripts.ops.bars._campaign import CampaignRefused
from scripts.ops.bars.ops_head_rerun import HeadRequest, classify_head, pending_symbols

_VENUES = ("NYSE", "ARCA", "ISLAND", "AMEX", "BATS")
_WS = date(2006, 10, 5)
_WE = date(2016, 2, 2)
_T0 = datetime(2026, 9, 29, tzinfo=UTC)


def _req(route: str, outcome: str, first_bar: date | None = None, day: int = 0) -> HeadRequest:
    return HeadRequest(
        route=route,
        outcome=outcome,
        window_start=_WS,
        window_end=_WE,
        first_bar=first_bar,
        answered_at=_T0.replace(day=1 + day),
    )


def test_moved_when_venue_bars_predate_smart_head() -> None:
    reqs = [_req("SMART", "no_data"), _req("NYSE", "bars", date(2009, 3, 2))]
    reqs += [_req(v, "no_data") for v in _VENUES if v != "NYSE"]
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "moved"


def test_verified_empty_when_smart_and_every_venue_no_data() -> None:
    reqs = [_req("SMART", "no_data")] + [_req(v, "no_data") for v in _VENUES]
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "verified_empty"


def test_venue_timeout_is_unresolved_not_empty() -> None:
    reqs = [_req("SMART", "no_data"), _req("NYSE", "timeout")]
    reqs += [_req(v, "no_data") for v in _VENUES if v != "NYSE"]
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "unresolved"


def test_missing_venue_is_unresolved() -> None:
    reqs = [_req("SMART", "no_data")] + [_req(v, "no_data") for v in _VENUES[:-1]]
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "unresolved"


def test_no_requests_is_unresolved() -> None:
    assert classify_head([], date(2015, 1, 2), _VENUES) == "unresolved"


def test_reached_window_start() -> None:
    reqs = [_req("SMART", "bars", date(2006, 10, 5))]
    assert classify_head(reqs, date(2006, 10, 5), _VENUES) == "reached_window_start"


def test_latest_answer_per_route_wins() -> None:
    reqs = [_req("SMART", "no_data")]
    reqs += [_req(v, "no_data") for v in _VENUES]
    reqs.append(_req("NYSE", "timeout", day=-0))  # same time: ambiguous, ties keep failure
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "unresolved"
    reqs.append(_req("NYSE", "no_data", day=3))  # later clean answer resolves it
    assert classify_head(reqs, date(2015, 1, 2), _VENUES) == "verified_empty"


def test_pending_skips_resolved_unless_force() -> None:
    dispositions = {
        "A": "moved",
        "B": "verified_empty",
        "C": "unresolved",
        "D": "reached_window_start",
    }
    assert pending_symbols(["A", "B", "C", "D", "E"], dispositions, force=False) == ["C", "E"]
    assert pending_symbols(["A", "B", "C"], dispositions, force=True) == ["A", "B", "C"]


def test_refuses_when_preflight_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(**_: Any) -> None:
        raise CampaignRefused("client id outside lanes")

    monkeypatch.setattr(mod, "preflight", _refuse)
    with pytest.raises(SystemExit) as excinfo:
        mod.run_with_refusal(lambda: mod.preflight(client_id=49, apr={}))
    assert excinfo.value.code == 3
