"""The stage 2 instrument path (todo 609): inactive, provenance on the row, rerun-safe, no takeover."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.config.instrument_onboarding import (
    STAGE2_COHORT,
    OnboardingRejected,
    Stage2Instrument,
    onboard_stage2_instruments,
    stage2_contract_details,
)


class FakeConn:
    def __init__(self, existing: list[dict[str, Any]] | None = None, status: str | None = None):
        self.existing = existing or []
        self.status = status
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append(("fetch", args))
        wanted = set(args[0])
        return [r for r in self.existing if r["symbol"] in wanted]

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append(("execute", args))
        return self.status or f"INSERT 0 {len(args[1])}"


def row(symbol: str, key: str = "BBG000C2V3D6", kind: str = "composite_figi") -> Stage2Instrument:
    return Stage2Instrument(
        symbol, "ACME CORP", "XNYS", kind, key, "0000000001", "2003-09-10", None, ("CS",), "r"
    )


async def test_new_rows_are_inserted_inactive_with_the_provenance_on_the_row():
    conn = FakeConn()
    result = await onboard_stage2_instruments(
        conn, [row("AAA"), row("BBB", "0000000001:BBB", "cik_ticker")]
    )
    assert (result.inserted, result.already_present) == (2, 0)
    _, (cohort, symbols, details) = conn.calls[-1]
    assert cohort == STAGE2_COHORT and symbols == ["AAA", "BBB"]
    body = json.loads(details[1])
    assert body["asset_class"] == "equity" and body["provider_meta"]["key_kind"] == "cik_ticker"
    assert body["provider_meta"]["types"] == ["CS"] and body["session_id"] == "nyse"


async def test_the_insert_sql_sets_every_eligibility_flag_false_and_inactive():
    from src.config.instrument_onboarding import _INSERT_STAGE2_SQL

    assert "false, false, false, false" in _INSERT_STAGE2_SQL
    assert "is_active" in _INSERT_STAGE2_SQL


async def test_a_rerun_accepts_rows_this_path_wrote_for_the_same_key():
    conn = FakeConn(
        [
            {
                "symbol": "AAA",
                "universe_cohort": STAGE2_COHORT,
                "key_kind": "composite_figi",
                "key": "BBG000C2V3D6",
            }
        ]
    )
    result = await onboard_stage2_instruments(conn, [row("AAA"), row("BBB")])
    assert (result.inserted, result.already_present) == (1, 1)


@pytest.mark.parametrize(
    "existing",
    [
        {"symbol": "AAA", "universe_cohort": "spx", "key_kind": None, "key": None},
        {
            "symbol": "AAA",
            "universe_cohort": STAGE2_COHORT,
            "key_kind": "composite_figi",
            "key": "BBG000B9XB24",
        },
    ],
)
async def test_a_symbol_that_names_another_instrument_refuses_before_any_write(existing):
    conn = FakeConn([existing])
    with pytest.raises(OnboardingRejected, match="never overwrites"):
        await onboard_stage2_instruments(conn, [row("AAA")])
    assert all(kind == "fetch" for kind, _ in conn.calls)


async def test_a_duplicate_symbol_in_the_plan_refuses():
    with pytest.raises(OnboardingRejected, match="twice"):
        await onboard_stage2_instruments(FakeConn(), [row("AAA"), row("AAA", "BBG000B9XB24")])


async def test_a_short_insert_refuses():
    with pytest.raises(OnboardingRejected, match="written for 1 rows"):
        await onboard_stage2_instruments(FakeConn(status="INSERT 0 0"), [row("AAA")])


def test_contract_details_use_the_symbol_as_base_and_fall_back_to_it_for_a_missing_name():
    r = Stage2Instrument(
        "ZZZ~7",
        None,
        None,
        "cik_ticker",
        "0000000007:ZZZ",
        None,
        "2003-09-10",
        "2004-01-01",
        (),
        "r",
    )
    d = stage2_contract_details(r)
    assert d["base"] == "ZZZ~7" and d["name"] == "ZZZ~7" and d["exchange"] == ""
