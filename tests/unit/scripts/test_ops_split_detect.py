"""Plan 185-51: the sanctioned split corrections (supersede, void, hold, release) and the split rule.

Against a fake connection; nothing touches the database.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from scripts.ops.bars import ops_split_detect as ops
from src.intelligence.bars.corporate_actions import SplitRatioRule

_RULE = SplitRatioRule(max_numerator=50, max_denominator=4, rel_tol=0.002)


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
        if "_VENDOR_RATIOS" in flat or "market_data_ohlcv_tradeable" in flat:
            return self.ratios
        raise AssertionError(flat)

    def inserts(self, table):
        return [(s, a) for s, a in self.executed if s.startswith(f"INSERT INTO {table} ")]


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


def test_supersede_refuses_a_massive_reference_row():
    # An operator row stales the incumbents; a reference row records a market split they carry
    # adjusted (todo 600), so it is corrected by a void and a new --apply-massive line instead.
    rows = {k: dict(v) for k, v in _ROWS.items()}
    rows[_A]["inferred_by"] = "massive_reference"
    conn = OpsConn(current=rows)
    with pytest.raises(ValueError, match="massive_reference"):
        _supersede(conn, apply=True)
    with pytest.raises(ValueError, match="massive_reference"):
        asyncio.run(ops.hold_rescale(conn, action_id=_A, reason="r", split_rule=_RULE, apply=True))
    assert conn.executed == []
