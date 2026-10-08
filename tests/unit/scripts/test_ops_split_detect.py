"""Plan 185-22 (D-21): ops_split_detect records, re-fetches and re-derives, in that order.

Against a fake connection and injected collaborators; nothing touches IBKR or the database.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date

import pytest

from scripts.ops.bars import ops_split_detect as ops
from services.split_detection import DetectedSplit
from src.intelligence.bars.corporate_actions import SplitRatioRule

_RULE = SplitRatioRule(max_numerator=50, max_denominator=4, rel_tol=0.002)

_EVIDENCE = ("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")


def _split(symbol="XYZ", factor=3.0, day=date(2026, 9, 30), unexplained=False, ids=_EVIDENCE):
    return DetectedSplit(symbol, day, factor, ids, unexplained)


def _ca(action_id, factor, day=date(2026, 9, 30), inferred_by="nightly_overlap"):
    return {
        "action_id": action_id,
        "factor": factor,
        "effective_date": day,
        "inferred_by": inferred_by,
    }


class FakeConn:
    def __init__(self, existing=()):
        self.existing = list(existing)  # corporate_action_current rows (_ca)
        self.executed: list[tuple[str, tuple]] = []
        self.fetched: list[tuple[str, tuple]] = []

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, *args):
        self.executed.append((" ".join(sql.split()), args))

    async def fetch(self, sql, *args):
        self.fetched.append((" ".join(sql.split()), args))
        return self.existing


def _record(conn, split):
    return asyncio.run(ops.record_split(conn, split))


def test_a_new_split_is_inserted_under_the_writer_role_with_its_evidence():
    conn = FakeConn()
    assert _record(conn, _split()) is True
    role, insert = conn.executed
    assert role[0] == "SET LOCAL ROLE bar_derivation_writer"
    sql, args = insert
    assert "INSERT INTO corporate_action" in sql and "'nightly_overlap'" in sql
    assert args[:4] == ("XYZ", "split", date(2026, 9, 30), 3.0)
    assert args[4] == list(_EVIDENCE) and args[6] is None
    # One JSON encoding: a pooled connection with a jsonb codec double-encoded the dumped
    # string (CTVA's and ETHA's 2026-10-08 rows hold a JSON string, not an object).
    assert "$6::text::jsonb" in sql and json.loads(args[5])["detected_by"] == "overlap"


def test_a_reverse_split_is_typed_as_one():
    conn = FakeConn()
    _record(conn, _split(factor=0.125))
    assert conn.executed[1][1][1] == "reverse_split"


def test_the_same_factor_is_not_recorded_twice():
    conn = FakeConn(existing=[_ca("aaaa", 3.0)])
    assert _record(conn, _split()) is False
    assert [sql for sql, _ in conn.executed if sql.startswith("INSERT")] == []


def test_a_different_factor_on_the_same_date_supersedes_the_earlier_row():
    conn = FakeConn(existing=[_ca("aaaa", 2.0)])
    assert _record(conn, _split(factor=3.0)) is True
    assert conn.executed[1][1][6] == "aaaa"


def test_a_correction_at_a_later_date_is_the_same_event_and_is_not_recorded_again():
    """Plan 185-51: ETHA's one current row is an operator correction at 2026-10-05. Re-judging
    the 2026-10-08 fetch run detects the same 1-for-3 with its last old-scale overlap date
    2026-09-30; recording it again would bring back the row the correction voided."""
    conn = FakeConn(existing=[_ca("cccc", 1 / 3, date(2026, 10, 5), "operator")])
    assert _record(conn, _split(factor=1 / 3)) is False
    sql, args = conn.fetched[0]
    assert "effective_date >= $2" in sql and "inferred_by" not in sql.split("WHERE")[1]


def test_a_different_factor_at_a_later_date_is_recorded_without_superseding_it():
    conn = FakeConn(existing=[_ca("cccc", 1 / 3, date(2026, 10, 5), "operator")])
    assert _record(conn, _split(factor=2.0)) is True
    assert conn.executed[1][1][6] is None


def test_a_split_without_evidence_is_refused():
    with pytest.raises(ValueError, match="evidence"):
        _record(FakeConn(), _split(ids=()))


def _process(conn, detected, **calls):
    async def fake_detect(c, **kw):
        return detected

    original = ops.detect_overlap_splits
    ops.detect_overlap_splits = fake_detect
    try:
        return asyncio.run(
            ops.process(
                conn,
                ["run-1"],
                rel_tol=0.002,
                min_run=5,
                ratio_snap_tol=0.01,
                split_rule=_RULE,
                refetch=calls.get("refetch", lambda s: 0),
                derive=calls.get("derive", lambda s: 0),
                report_unexplained=calls.get("report", lambda s: None),
                report_rescale=calls.get("report_rescale", lambda s: None),
            )
        )
    finally:
        ops.detect_overlap_splits = original


def test_recorded_symbols_are_refetched_then_rederived_in_that_order():
    order: list[tuple[str, list[str]]] = []
    report = _process(
        FakeConn(),
        [_split("BBB"), _split("AAA")],
        refetch=lambda s: order.append(("refetch", s)) or 0,
        derive=lambda s: order.append(("derive", s)) or 0,
    )
    assert order == [("refetch", ["AAA", "BBB"]), ("derive", ["AAA", "BBB"])]
    assert report == {
        "recorded": ["AAA", "BBB"],
        "unexplained": [],
        "held": [],
        "returncode": 0,
    }


def test_an_already_recorded_split_is_not_refetched_again():
    order: list = []
    report = _process(
        FakeConn(existing=[_ca("aaaa", 3.0)]),
        [_split()],
        refetch=lambda s: order.append(s) or 0,
    )
    assert order == [] and report["recorded"] == []


def test_unexplained_differences_are_reported_and_never_recorded():
    seen: list[str] = []
    conn = FakeConn()
    report = _process(
        conn, [_split("NOISY", unexplained=True)], report=lambda s: seen.append(s.symbol)
    )
    assert seen == ["NOISY"] and report["unexplained"] == ["NOISY"]
    assert conn.executed == [] and report["recorded"] == []


def test_a_failed_refetch_skips_the_derivation_and_returns_its_code():
    derived: list = []
    report = _process(
        FakeConn(), [_split()], refetch=lambda s: 3, derive=lambda s: derived.append(s) or 0
    )
    assert report["returncode"] == 3 and derived == []


def test_the_refetch_command_asks_the_full_depth_through_the_fetcher_on_the_given_client():
    command = ops.refetch_command(["AAA", "BBB"], years=20, client_id=45)
    assert command[:2] == [sys.executable, str(ops._FETCHER)]
    assert command[1].endswith("scripts/infrastructure/backfill/ibkr_history_fetcher.py")
    assert "--full-scan" in command
    rest = [part for part in command[2:] if part != "--full-scan"]
    pairs = dict(zip(rest[::2], rest[1::2], strict=False))
    assert pairs["--symbols"] == "AAA,BBB" and pairs["--timeframes"] == "1d"
    assert pairs["--dimension"] == "backfill" and pairs["--client-id"] == "45"
    assert pairs["--overlap-sessions"] == str(20 * 260)
    assert not any("lease" in part for part in command)


class _FakeProc:
    def __init__(self, lines: list[str], rc: int) -> None:
        self.stdout = iter(lines)
        self._rc = rc

    def wait(self) -> int:
        return self._rc


def test_a_refetch_refused_by_the_fetcher_lock_is_a_failure_not_a_success():
    """Plan 189-08: the fetcher exits 0 and prints LOCK_HELD_MESSAGE when its lock is held
    (always so when this script runs as the fetcher's own run-end stage). That must read as
    a failed re-fetch, so the derivation is skipped and the split stays quarantined."""
    from scripts.infrastructure.backfill._fetcher_lock import LOCK_HELD_MESSAGE

    refused = ops.run_refetch(["x"], popen=lambda *a, **k: _FakeProc([LOCK_HELD_MESSAGE + "\n"], 0))
    assert refused == ops.LOCK_HELD_EXIT != 0
    assert ops.run_refetch(["x"], popen=lambda *a, **k: _FakeProc(["ok\n"], 0)) == 0
    assert ops.run_refetch(["x"], popen=lambda *a, **k: _FakeProc([], 1)) == 1


def test_the_derive_command_forces_the_daily_stage_for_exactly_those_symbols():
    command = ops._derive_command(["AAA"])
    assert command[-5:] == ["--stage", "daily", "--symbols", "AAA", "--apply"]


# --- plan 185-51 (todo 515): unclassified rescales, holds and sanctioned corrections ---------

_A = "ed939e61-6fcb-4ac7-a5a3-00594cc7a005"  # ETHA 2026-10-02 tradier_refetch
_B = "276f406f-5a03-473c-95eb-c8dff378abb2"  # ETHA 2026-09-30 nightly_overlap
_C = "90c2dc47-d184-48b6-8e50-932fc2f60109"  # CTVA 2026-09-30 nightly_overlap
_R1 = "31ea6768-af6c-417a-a458-908861655752"
_R2 = "3886fb26-3f6f-4ddd-a040-e868d00e3157"

_ROWS = {
    _A: {
        "action_id": _A,
        "symbol": "ETHA",
        "action_type": "reverse_split",
        "effective_date": date(2026, 10, 2),
        "factor": 1 / 3,
    },
    _B: {
        "action_id": _B,
        "symbol": "ETHA",
        "action_type": "reverse_split",
        "effective_date": date(2026, 9, 30),
        "factor": 1 / 3,
    },
    _C: {
        "action_id": _C,
        "symbol": "CTVA",
        "action_type": "split",
        "effective_date": date(2026, 9, 30),
        "factor": 39 / 7,
    },
}


class OpsConn:
    """Answers the correction paths' reads: current actions, evidence requests, holds and the
    vendor ratio read; records every statement."""

    def __init__(self, current=_ROWS, requests=(_R1, _R2), holds=(), ratios=()):
        self.current = dict(current)
        self.requests = set(requests)
        self.holds = list(holds)
        self.ratios = list(ratios)
        self.executed: list[tuple[str, tuple]] = []
        self.existing: list = []

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, *args):
        self.executed.append((" ".join(sql.split()), args))
        return "INSERT 0 1"

    async def fetch(self, sql, *args):
        flat = " ".join(sql.split())
        if "FROM corporate_action_current" in flat and "action_id = ANY" in flat:
            return [self.current[i] for i in args[0] if i in self.current]
        if "FROM corporate_action_current" in flat:
            return self.existing  # record_split's same-date read
        if "FROM ohlcv_request" in flat:
            return [{"request_id": r} for r in args[1] if r in self.requests]
        if "FROM bar_hold_current" in flat:
            return [h for h in self.holds if h["symbol"] == args[0]]
        if "ohlcv_observation" in flat:
            return self.ratios
        raise AssertionError(flat)

    def inserts(self, table):
        return [(s, a) for s, a in self.executed if s.startswith(f"INSERT INTO {table} ")]


def _detected(symbol="CTVA", factor=39 / 7, unclassified=True, unexplained=False):
    return DetectedSplit(
        symbol,
        date(2026, 9, 30),
        factor,
        _EVIDENCE,
        unexplained,
        first_date=date(2026, 9, 3),
        unclassified=unclassified,
    )


def _act(conn, detected, **calls):
    return asyncio.run(
        ops.act_on_detections(
            conn,
            detected,
            split_rule=_RULE,
            report_unexplained=calls.get("report", lambda s: None),
            report_rescale=calls.get("report_rescale", lambda s: None),
            recorded_by="ibkr-history-fetcher",
            fetch_run_id="run-1",
        )
    )


def test_an_unclassified_rescale_is_held_and_reported_never_a_corporate_action():
    seen: list[str] = []
    conn = OpsConn()
    reasons = _act(conn, [_detected()], report_rescale=lambda s: seen.append(s.symbol))
    assert reasons == {"CTVA": "unclassified_rescale"} and seen == ["CTVA"]
    assert conn.inserts("corporate_action") == []
    ((sql, args),) = conn.inserts("bar_hold")
    assert args[1:4] == ("CTVA", "1d", "unclassified_rescale")
    assert args[5:7] == (date(2026, 9, 3), date(2026, 9, 30))
    detail = json.loads(args[8])
    assert detail["fetch_run_id"] == "run-1" and detail["evidence_request_ids"] == list(_EVIDENCE)
    assert "vendor_ratios" in detail


def test_the_same_rescale_seen_again_is_neither_held_again_nor_reported():
    seen: list[str] = []
    held = {"symbol": "CTVA", "factor": 39 / 7, "reason": "unclassified_rescale"}
    conn = OpsConn(holds=[held])
    reasons = _act(conn, [_detected()], report_rescale=lambda s: seen.append(s.symbol))
    assert reasons == {} and seen == [] and conn.inserts("bar_hold") == []


def test_a_recognised_split_and_an_unexplained_difference_keep_their_paths():
    seen: list[str] = []
    conn = OpsConn()
    reasons = _act(
        conn,
        [
            _detected("AAA", 3.0, unclassified=False),
            _detected("NOISY", 1.04, unclassified=False, unexplained=True),
        ],
        report=lambda s: seen.append(s.symbol),
    )
    assert reasons == {"AAA": "split_recorded", "NOISY": "unexplained_difference"}
    assert seen == ["NOISY"] and len(conn.inserts("corporate_action")) == 1
    assert conn.inserts("bar_hold") == []


def test_process_holds_an_unclassified_rescale_and_does_not_refetch_it_by_hand():
    order: list = []
    report = _process(OpsConn(), [_detected()], refetch=lambda s: order.append(s) or 0)
    assert report["held"] == ["CTVA"] and report["recorded"] == [] and order == []


def test_the_split_rule_comes_from_the_three_apr_keys():
    rule = ops.split_rule_from_apr(
        {
            "infra.backfill.split_ratio_max_numerator": "50",
            "infra.backfill.split_ratio_max_denominator": "4",
            "infra.backfill.split_ratio_rel_tol": "0.002",
        }
    )
    assert rule == _RULE
    assert set(ops.SPLIT_RULE_KEYS) <= set(ops._APR_KEYS)
    with pytest.raises(KeyError):
        ops.split_rule_from_apr({})


def _supersede(conn, apply, **over):
    kw = {
        "action_ids": [_A, _B],
        "effective_date": date(2026, 10, 5),
        "factor": 1 / 3,
        "evidence_request_ids": [_R1, _R2],
        "reason": "Nasdaq ECA2026-713: effective 2026-10-06",
        "split_rule": _RULE,
        "apply": apply,
    }
    kw.update(over)
    return asyncio.run(ops.supersede(conn, **kw))


def test_supersede_dry_run_plans_one_correct_row_and_voids_the_rest_writing_nothing():
    conn = OpsConn()
    plan = _supersede(conn, apply=False)
    assert conn.executed == []
    correct, void = plan["insert"]
    assert (correct["supersedes"], correct["action_type"]) == (_A, "reverse_split")
    assert (correct["effective_date"], correct["factor"]) == ("2026-10-05", 1 / 3)
    assert (void["supersedes"], void["action_type"]) == (_B, "void")
    assert plan["current_after"] == [correct["action_id"]]


def test_supersede_apply_inserts_both_rows_in_one_transaction_under_the_writer_role():
    conn = OpsConn()
    plan = _supersede(conn, apply=True)
    assert conn.executed[0][0] == "SET LOCAL ROLE bar_derivation_writer"
    (c_sql, c_args), (v_sql, v_args) = conn.inserts("corporate_action")
    assert "'operator'" in c_sql and "$7::text::jsonb" in c_sql
    assert c_args[0] == plan["insert"][0]["action_id"]
    assert c_args[1:6] == ("ETHA", "reverse_split", date(2026, 10, 5), 1 / 3, [_R1, _R2])
    assert c_args[7] == _A
    assert v_args[1:6] == ("ETHA", "void", date(2026, 9, 30), 1 / 3, [])
    assert v_args[7] == _B
    assert json.loads(v_args[6])["superseded_by"] == c_args[0]
    assert json.loads(c_args[6])["voids"] == [_B]


@pytest.mark.parametrize(
    ("over", "error", "match"),
    [
        ({"action_ids": [_A, "00000000-0000-0000-0000-000000000000"]}, LookupError, "current"),
        ({"action_ids": [_A, _C]}, ValueError, "one symbol"),
        ({"factor": 39 / 7}, ValueError, "recognised"),
        (
            {"evidence_request_ids": [_R1, "deadbeef-0000-0000-0000-000000000000"]},
            ValueError,
            "evidence",
        ),
        ({"evidence_request_ids": []}, ValueError, "evidence"),
        ({"reason": " "}, ValueError, "reason"),
    ],
)
def test_supersede_refuses_what_it_cannot_justify(over, error, match):
    conn = OpsConn()
    with pytest.raises(error, match=match):
        _supersede(conn, apply=True, **over)
    assert conn.executed == []


def test_hold_rescale_voids_the_wrong_split_and_holds_the_name_in_one_transaction():
    ratios = [
        {
            "route": "SMART",
            "n_dates": 1848,
            "median_ratio": 5.5711,
            "first_date": date(2019, 5, 24),
            "last_date": date(2026, 9, 30),
        }
    ]
    conn = OpsConn(ratios=ratios)
    plan = asyncio.run(
        ops.hold_rescale(
            conn,
            action_id=_C,
            reason="Corteva 2026-09-14: Vylor spin-off",
            split_rule=_RULE,
            apply=False,
        )
    )
    assert conn.executed == [] and plan["void"]["supersedes"] == _C
    assert plan["hold"]["first_affected_date"] == "2019-05-24"
    asyncio.run(
        ops.hold_rescale(
            conn,
            action_id=_C,
            reason="Corteva 2026-09-14: Vylor spin-off",
            split_rule=_RULE,
            apply=True,
        )
    )
    ((_, v_args),) = conn.inserts("corporate_action")
    assert v_args[1:3] == ("CTVA", "void") and v_args[7] == _C
    ((_, h_args),) = conn.inserts("bar_hold")
    assert h_args[1:4] == ("CTVA", "1d", "unclassified_rescale")
    assert h_args[4] == 39 / 7 and h_args[7] == _C
    assert h_args[5:7] == (date(2019, 5, 24), date(2026, 9, 30))


def test_void_alone_inserts_one_void_row():
    conn = OpsConn()
    asyncio.run(ops.void(conn, action_id=_B, reason="duplicate", apply=True))
    ((_, args),) = conn.inserts("corporate_action")
    assert args[2] == "void" and args[7] == _B
