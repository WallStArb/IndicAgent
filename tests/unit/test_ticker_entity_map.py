"""The stage 1 ticker-entity map (src/intelligence/bars/ticker_entity_map.py, todo 600 step 3b).

Fixtures copy the shape of the served bodies (Massive overview and events, IBKR contract
details, OpenFIGI mapping); the FIGIs and ISINs of AAPL, Agilent, Meta and Berkshire are the
real served values.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.intelligence.bars import ticker_entity_map as tem
from src.intelligence.bars.ticker_entity_map import (
    Answer,
    DelistedTicker,
    MapInputs,
    propose_ticker_entity_map,
)

_SERVED = datetime(2026, 11, 10, 15, 49, tzinfo=UTC)


def _ans(rid: str, body) -> Answer:
    return Answer(rid, _SERVED, body)


class _World:
    """Builds MapInputs one name at a time."""

    def __init__(self):
        self.instruments: dict[str, str] = {}
        self.overview: dict[str, Answer] = {}
        self.events: dict[str, Answer] = {}
        self.delisted: list[DelistedTicker] = []
        self.ibkr: dict[str, Answer] = {}
        self.figi: dict[str, Answer] = {}

    def name(
        self,
        symbol,
        *,
        isin,
        composite,
        share,
        events,
        list_date="1980-12-12",
        figi_composite=None,
        figi_share=None,
        massive_share=True,
        ticker_root=None,
    ):
        self.instruments[symbol] = "equity"
        results = {
            "ticker": symbol,
            "composite_figi": composite,
            "cik": "0000320193",
            "list_date": list_date,
            "ticker_root": ticker_root or symbol.split(".")[0],
        }
        if massive_share:
            results["share_class_figi"] = share
        self.overview[f"{symbol}@active"] = _ans(
            f"ov-{symbol}", {"status": "OK", "results": results}
        )
        self.events[f"{symbol}@active"] = _ans(
            f"ev-{symbol}",
            {
                "status": "OK",
                "results": {
                    "composite_figi": composite,
                    "events": [
                        {"date": d, "type": "ticker_change", "ticker_change": {"ticker": t}}
                        for d, t in events
                    ],
                },
            },
        )
        self.ibkr[symbol] = _ans(
            f"ib-{symbol}",
            {"status": "OK", "results": [{"secIdList": [["ISIN", isin]]}], "errors": []},
        )
        self.figi[isin] = _ans(
            f"of-{isin}",
            [
                {
                    "data": [
                        {
                            "compositeFIGI": figi_composite or composite,
                            "shareClassFIGI": figi_share or share,
                        }
                    ]
                }
            ],
        )

    def inputs(self) -> MapInputs:
        return MapInputs(
            self.instruments, self.overview, self.events, tuple(self.delisted), self.ibkr, self.figi
        )


def _aapl(world: _World) -> None:
    world.name(
        "AAPL",
        isin="US0378331005",
        composite="BBG000B9XRY4",
        share="BBG001S5N8V8",
        events=[("2003-09-10", "AAPL")],
    )


def _spans(proposal, symbol):
    return [(s.ticker, s.valid_from, s.valid_to) for s in proposal.spans if s.symbol == symbol]


def _gaps(proposal, symbol):
    return [(g.reason, g.valid_from, g.valid_to) for g in proposal.gaps if g.symbol == symbol]


def test_aapl_one_open_span_and_three_identifiers():
    world = _World()
    _aapl(world)
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "AAPL") == [("AAPL", date(2003, 9, 10), None)]
    assert _gaps(proposal, "AAPL") == []
    by_scheme = {i.scheme: i for i in proposal.identifiers}
    assert by_scheme["share_class_figi"].value == "BBG001S5N8V8"
    # Each identifier comes from its own outside source: FIGIs from OpenFIGI, ISIN from IBKR.
    assert by_scheme["share_class_figi"].reference_raw_id == "of-US0378331005"
    assert by_scheme["composite_figi"].reference_raw_id == "of-US0378331005"
    assert by_scheme["isin"].reference_raw_id == "ib-AAPL"
    assert by_scheme["composite_figi"].valid_from == date(2003, 9, 10)
    assert by_scheme["share_class_figi"].valid_from == date(2026, 11, 10)
    assert by_scheme["isin"].valid_from == date(2026, 11, 10)  # IBKR answers for today only
    span = proposal.spans[0]
    assert span.evidence["match"]["basis"] == "share_class_figi"
    assert span.evidence["match"]["cik_used"] is False
    assert proposal.partition() == {"mapped": 1}


def test_rename_chain_gives_consecutive_spans():
    world = _World()
    world.name(
        "META",
        isin="US30303M1027",
        composite="BBG000MM2P62",
        share="BBG001SQCQB0",
        events=[("2022-06-09", "META"), ("2012-05-18", "FB")],
        list_date="2012-05-18",
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "META") == [
        ("FB", date(2012, 5, 18), date(2022, 6, 9)),
        ("META", date(2022, 6, 9), None),
    ]
    assert _gaps(proposal, "META") == []  # listed on its first event: no coverage gap


def test_agilent_chain_naming_awd_is_refused_whole():
    # Massive's A chain is A from 2003-09-10, then AWD from 2005-11-23; the day files serve A
    # throughout, so the newest event contradicts today's ticker and no span is evidenced.
    world = _World()
    world.name(
        "A",
        isin="US00846U1016",
        composite="BBG000C2V3D6",
        share="BBG001SCTQY4",
        events=[("2005-11-23", "AWD"), ("2003-09-10", "A")],
        list_date="1999-11-18",
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "A") == []
    assert _gaps(proposal, "A") == [(tem.EVENT_CHAIN_HEAD_MISMATCH, None, None)]
    assert proposal.gaps[0].detail["head"] == "AWD"
    # Identity is still anchored: the ISIN and both FIGIs are recorded, dated to the answers.
    assert {(i.scheme, i.valid_from, i.reference_raw_id) for i in proposal.identifiers} == {
        ("isin", date(2026, 11, 10), "ib-A"),
        ("composite_figi", date(2026, 11, 10), "of-US00846U1016"),
        ("share_class_figi", date(2026, 11, 10), "of-US00846U1016"),
    }
    assert proposal.partition() == {"mapped": 0, tem.EVENT_CHAIN_HEAD_MISMATCH: 1}


def test_class_share_chain_on_the_root_ticker_is_held():
    # BRK.B's chain names the root BRK, a string the day files never serve; HEI.A's root HEI is
    # a different share class. The class name is held, never mapped to the root.
    world = _World()
    world.name(
        "BRK.B",
        isin="US0846707026",
        composite="BBG000DWG505",
        share="BBG001S90346",
        events=[("2010-01-22", "BRK")],
        ticker_root="BRK",
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "BRK.B") == []
    assert _gaps(proposal, "BRK.B") == [(tem.EVENT_CHAIN_HEAD_MISMATCH, None, None)]


def test_cik_never_decides_a_figi_disagreement():
    world = _World()
    world.name(
        "BF.B",
        isin="US1156372096",
        composite="BBG000BD2NY8",
        share="BBG001S5S5Q6",
        events=[("2003-09-10", "BF.B")],
        figi_share="BBG001S5S5Q7",  # the ISIN's share class is another one: refused
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _gaps(proposal, "BF.B") == [(tem.FIGI_DISAGREES_WITH_ISIN, None, None)]
    assert proposal.gaps[0].detail["disagree"] == {
        "share_class_figi": ["BBG001S5S5Q6", "BBG001S5S5Q7"]
    }
    # The identifiers are the ISIN's own (IBKR, OpenFIGI); Massive's disagreement gates spans.
    assert {(i.scheme, i.value) for i in proposal.identifiers} == {
        ("isin", "US1156372096"),
        ("composite_figi", "BBG000BD2NY8"),
        ("share_class_figi", "BBG001S5S5Q7"),
    }


def test_reused_ticker_span_cut_where_another_security_gave_the_string_up():
    # CRH's chain claims CRHC from 2021-09-23; the delisted universe shows a different security
    # giving CRHC up on 2022-11-11, inside that span: the span is dropped and listed, the later
    # CRH span stands.
    world = _World()
    world.name(
        "CRH",
        isin="IE0001827041",
        composite="BBG000BGGMZ3",
        share=None,
        massive_share=False,
        figi_share="BBG001S5RS10",
        events=[("2023-09-25", "CRH"), ("2021-09-23", "CRHC")],
        list_date="2021-09-23",
    )
    world.delisted.append(DelistedTicker("CRHC", "2022-11-11T05:00:00Z", "dl-page-3"))
    # The old holder of CRH gave the string up before our first CRH session: no clash.
    world.delisted.append(DelistedTicker("CRH", "2023-09-25T04:00:00Z", "dl-page-3"))
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "CRH") == [("CRH", date(2023, 9, 25), None)]
    assert _gaps(proposal, "CRH") == [
        (tem.TICKER_HELD_BY_DELISTED_SECURITY, date(2021, 9, 23), date(2023, 9, 25))
    ]
    span = proposal.spans[0]
    # No share class from Massive: matched on the composite, share class served by OpenFIGI.
    assert span.evidence["match"]["basis"] == "composite_figi"
    share = [i for i in proposal.identifiers if i.scheme == "share_class_figi"][0]
    assert (share.value, share.reference_raw_id) == ("BBG001S5RS10", "of-IE0001827041")


def test_reused_ticker_starts_at_the_new_securitys_first_event():
    # AKTS today is a different company from the AKTS delisted in 2024; its chain starts at
    # 2026-01-09, so the earlier holder's files never fall inside the span.
    world = _World()
    world.name(
        "AKTS",
        isin="US00973N1028",
        composite="BBG00ZQS8KZ1",
        share="BBG00ZQS8LP3",
        events=[("2026-01-09", "AKTS")],
        list_date="2026-01-09",
    )
    world.delisted.append(DelistedTicker("AKTS", "2024-12-20T05:00:00Z", "dl-page-1"))
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "AKTS") == [("AKTS", date(2026, 1, 9), None)]
    assert _gaps(proposal, "AKTS") == []


def test_delisted_massive_ticker_without_identifiers_is_a_gap():
    # Massive knows WBD only as a delisted query, whose answers carry no FIGI or CIK. IBKR and
    # OpenFIGI still anchor the instrument, so its identifiers are recorded as of today.
    world = _World()
    world.name(
        "WBD",
        isin="US9344231041",
        composite="BBG013V3WRQ1",
        share="BBG013V3WRR0",
        events=[("2022-04-11", "WBD")],
    )
    del world.overview["WBD@active"], world.events["WBD@active"]
    world.overview["WBD@2026-10-01"] = _ans(
        "ov-wbd", {"status": "OK", "results": {"ticker": "WBD"}}
    )
    world.events["WBD@2026-10-01"] = _ans(
        "ev-wbd", {"status": "NOT_FOUND", "message": "Ticker not found."}
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _gaps(proposal, "WBD") == [(tem.MASSIVE_TICKER_NOT_ACTIVE, None, None)]
    assert proposal.gaps[0].detail == {"massive_requests": ["WBD@2026-10-01"]}
    assert {i.scheme for i in proposal.identifiers} == {
        "isin",
        "composite_figi",
        "share_class_figi",
    }


def test_identity_is_judged_before_massive():
    world = _World()
    _aapl(world)
    world.ibkr["AAPL"] = _ans(
        "ib-x", {"status": "NOT_FOUND", "results": [], "errors": [{"code": 200}]}
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _gaps(proposal, "AAPL") == [(tem.IBKR_NOT_FOUND, None, None)]
    assert proposal.identifiers == ()


def test_undated_delisted_row_is_cited_and_judges_nothing():
    # Block's former SQ appears in the delisted universe without a date: it cannot place
    # another holder inside the span, so the span stands and cites the row.
    world = _World()
    world.name(
        "XYZ",
        isin="US8522341036",
        composite="BBG0018SLC07",
        share="BBG0018SLC16",
        events=[("2025-01-21", "XYZ"), ("2015-11-19", "SQ")],
        list_date="2015-11-19",
    )
    world.delisted.append(DelistedTicker("SQ", None, "dl-page-9"))
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "XYZ") == [
        ("SQ", date(2015, 11, 19), date(2025, 1, 21)),
        ("XYZ", date(2025, 1, 21), None),
    ]
    assert proposal.spans[0].evidence["undated_delisted"] == ["dl-page-9"]


def test_asset_class_outside_the_vendor_is_a_gap_even_when_the_string_is_a_stock_ticker():
    world = _World()
    _aapl(world)
    world.instruments["AAPL"] = "futures"
    proposal = propose_ticker_entity_map(world.inputs())
    assert _gaps(proposal, "AAPL") == [(tem.ASSET_CLASS_OUTSIDE_VENDOR, None, None)]
    assert proposal.spans == ()


def test_listing_before_the_first_event_is_a_coverage_gap_not_a_span():
    # QQQ's chain starts 2018-06-04; it listed in 1999 (QQQ, then QQQQ): no evidence before.
    world = _World()
    world.name(
        "QQQ",
        isin="US46090E1038",
        composite="BBG000BSWKH7",
        share="BBG001S7S0R1",
        events=[("2018-06-04", "QQQ")],
        list_date="1999-03-10",
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "QQQ") == [("QQQ", date(2018, 6, 4), None)]
    assert _gaps(proposal, "QQQ") == [(tem.BEFORE_FIRST_EVENT, date(2003, 9, 10), date(2018, 6, 4))]
    assert proposal.partition() == {"mapped": 1}


def test_unusable_event_ticker_leaves_a_hole():
    world = _World()
    world.name(
        "AUGO",
        isin="CA05150X1042",
        composite="BBG00Y1Z3T49",
        share="BBG00Y1Z3TZ6",
        events=[
            ("2025-07-16", "AUGO"),
            ("2024-06-01", "S974"),
            ("2023-11-18", ""),
            ("2022-10-12", "ORAA"),
        ],
        list_date="2022-10-12",
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "AUGO") == [
        ("ORAA", date(2022, 10, 12), date(2023, 11, 18)),
        ("AUGO", date(2025, 7, 16), None),
    ]
    assert _gaps(proposal, "AUGO") == [
        (tem.EVENT_TICKER_UNUSABLE, date(2023, 11, 18), date(2024, 6, 1)),
        (tem.EVENT_TICKER_UNUSABLE, date(2024, 6, 1), date(2025, 7, 16)),
    ]


def test_two_instruments_claiming_one_ticker_lose_both_spans():
    world = _World()
    _aapl(world)
    world.name(
        "APLX",
        isin="US0000000001",
        composite="BBG000000001",
        share="BBG000000011",
        events=[("2020-01-02", "APLX"), ("2010-01-04", "AAPL")],
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "AAPL") == []
    assert _gaps(proposal, "AAPL") == [
        (tem.NO_SPAN_SURVIVED, None, None),
        (tem.TICKER_CLAIMED_BY_OTHER_SECURITY, date(2003, 9, 10), None),
    ]
    assert _spans(proposal, "APLX") == [("APLX", date(2020, 1, 2), None)]
    assert proposal.partition() == {"mapped": 1, tem.NO_SPAN_SURVIVED: 1}
    # AAPL's FIGIs are dated after the drop: no span survived, so from OpenFIGI's answer.
    aapl_figis = {i.valid_from for i in proposal.identifiers if i.symbol == "AAPL"}
    assert aapl_figis == {date(2026, 11, 10)}


def test_one_isin_on_two_instruments_refuses_both_whole():
    world = _World()
    _aapl(world)
    world.name(
        "AAPL.X",
        isin="US0378331005",
        composite="BBG000000002",
        share="BBG000000022",
        events=[("2003-09-10", "AAPL.X")],
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert proposal.identifiers == () and proposal.spans == ()
    assert proposal.partition() == {"mapped": 0, tem.IDENTIFIER_CLAIMED_TWICE: 2}


def test_events_group_conflict_refuses():
    world = _World()
    _aapl(world)
    world.events["AAPL@2001-01-01"] = _ans(
        "ev-other",
        {"status": "OK", "results": {"composite_figi": "BBG000B9XRY4", "events": []}},
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _gaps(proposal, "AAPL") == [(tem.EVENTS_GROUP_CONFLICT, None, None)]


@pytest.mark.parametrize(
    ("status", "reason"),
    [("NOT_FOUND", tem.IBKR_NOT_FOUND), ("ERROR", tem.IBKR_ERROR)],
)
def test_ibkr_body_status_is_judged(status, reason):
    world = _World()
    _aapl(world)
    world.ibkr["AAPL"] = _ans("ib-AAPL", {"status": status, "results": [], "errors": []})
    proposal = propose_ticker_entity_map(world.inputs())
    assert _gaps(proposal, "AAPL") == [(reason, None, None)]


def test_openfigi_no_match_is_a_gap():
    world = _World()
    _aapl(world)
    world.figi["US0378331005"] = _ans("of-x", [{"warning": "No identifier found."}])
    proposal = propose_ticker_entity_map(world.inputs())
    assert _gaps(proposal, "AAPL") == [(tem.OPENFIGI_NO_MATCH, None, None)]


def test_same_answers_same_digest_whatever_the_input_order():
    world = _World()
    _aapl(world)
    world.name(
        "META",
        isin="US30303M1027",
        composite="BBG000MM2P62",
        share="BBG001SQCQB0",
        events=[("2022-06-09", "META"), ("2012-05-18", "FB")],
    )
    first = propose_ticker_entity_map(world.inputs())
    shuffled = MapInputs(
        dict(reversed(world.instruments.items())),
        dict(reversed(world.overview.items())),
        dict(reversed(world.events.items())),
        tuple(reversed(world.delisted)),
        dict(reversed(world.ibkr.items())),
        dict(reversed(world.figi.items())),
    )
    second = propose_ticker_entity_map(shuffled)
    assert first == second and first.digest == second.digest
    world.overview["META@active"].body["results"]["list_date"] = "2010-01-01"
    assert propose_ticker_entity_map(world.inputs()).digest != first.digest


def test_openfigi_job_error_is_not_a_no_match():
    world = _World()
    _aapl(world)
    world.figi["US0378331005"] = _ans("of-x", [{"error": "Invalid idValue format."}])
    proposal = propose_ticker_entity_map(world.inputs())
    assert _gaps(proposal, "AAPL") == [(tem.OPENFIGI_ERROR, None, None)]


def test_a_chain_outside_our_names_claiming_the_ticker_drops_the_span():
    # The old Crane (CXT today, composite BBG017BXPZ85) held CR until 2023-04-04; the new
    # Crane's chain starts CR on 2023-03-29. One day file row must never load under two
    # securities, so the new Crane's span is dropped, not trusted.
    world = _World()
    world.name(
        "CR",
        isin="US2244081046",
        composite="BBG016G0L0Q5",
        share="BBG016G0L1H3",
        events=[("2023-03-29", "CR")],
        list_date="2023-03-29",
    )
    world.events["CXT@active"] = _ans(
        "ev-cxt",
        {
            "status": "OK",
            "results": {
                "composite_figi": "BBG017BXPZ85",
                "events": [
                    {
                        "date": "2023-04-04",
                        "type": "ticker_change",
                        "ticker_change": {"ticker": "CXT"},
                    },
                    {
                        "date": "2022-05-17",
                        "type": "ticker_change",
                        "ticker_change": {"ticker": "CR"},
                    },
                ],
            },
        },
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "CR") == []
    assert _gaps(proposal, "CR") == [
        (tem.NO_SPAN_SURVIVED, None, None),
        (tem.TICKER_CLAIMED_BY_OTHER_SECURITY, date(2023, 3, 29), None),
    ]
    assert proposal.gaps[1].detail["claimed_by"] == [
        ["BBG017BXPZ85", "2022-05-17", "2023-04-04", "ev-cxt"]
    ]


def test_share_class_figi_keeps_its_answer_date_and_the_composite_moves_to_the_first_span():
    world = _World()
    _aapl(world)
    proposal = propose_ticker_entity_map(world.inputs())
    dated = {i.scheme: i.valid_from for i in proposal.identifiers}
    assert dated == {
        "composite_figi": date(2003, 9, 10),
        "share_class_figi": date(2026, 11, 10),
        "isin": date(2026, 11, 10),
    }


def test_failed_overview_ask_is_not_a_delisting():
    world = _World()
    _aapl(world)
    world.overview["AAPL@active"] = _ans("ov-x", {"status": "ERROR", "error": "upstream"})
    proposal = propose_ticker_entity_map(world.inputs())
    assert _gaps(proposal, "AAPL") == [(tem.MASSIVE_OVERVIEW_ERROR, None, None)]


def test_naive_delisted_timestamp_is_refused():
    with pytest.raises(ValueError, match="without a zone"):
        _ = DelistedTicker("FB", "2022-06-09T20:00:00", "dl").delisted_on


def test_root_labelled_sibling_chain_cites_but_does_not_refuse():
    # GEF.B's chain names the root GEF (as BRK.B's names BRK); the files serve GEF for the class
    # A share, so that claim judges nothing and the GEF span stands, citing it.
    world = _World()
    world.name(
        "GEF",
        isin="US3976241071",
        composite="BBG000BLG477",
        share="BBG001S5PXG8",
        events=[("2003-09-10", "GEF")],
    )
    world.events["GEF.B@active"] = _ans(
        "ev-gefb",
        {
            "status": "OK",
            "results": {
                "composite_figi": "BBG000BLG4F7",
                "events": [
                    {
                        "date": "2003-09-10",
                        "type": "ticker_change",
                        "ticker_change": {"ticker": "GEF"},
                    }
                ],
            },
        },
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "GEF") == [("GEF", date(2003, 9, 10), None)]
    assert proposal.spans[0].evidence["root_labelled_claims_not_judged"] == [
        ["BBG000BLG4F7", "2003-09-10", None, "ev-gefb"]
    ]


def _rival(world, key, composite, links):
    world.events[key] = _ans(
        f"ev-{key}",
        {
            "status": "OK",
            "results": {
                "composite_figi": composite,
                "events": [
                    {"date": d, "type": "ticker_change", "ticker_change": {"ticker": t}}
                    for d, t in links
                ],
            },
        },
    )


@pytest.mark.parametrize(
    ("key", "composite", "links"),
    [
        # A rival whose newest event is blank is not root-labelled: every string starts with "".
        ("XYZ@2015-03-02", "BBG000000099", [("2015-01-02", ""), ("2008-01-02", "AAPL")]),
        # A rival served without a FIGI judges as an unknown security.
        ("XYZ@2015-03-02", None, [("2015-01-02", "XYZ"), ("2008-01-02", "AAPL")]),
        # A shorter rename (FISV to FI) exempts only the root label FI; the real AAPL link of
        # the chain still judges. Served oldest-first: the head is the newest link by date.
        ("AAPLX@active", "BBG000000099", [("2008-01-02", "AAPL"), ("2015-01-02", "AAPLX")][::-1]),
    ],
)
def test_rival_claims_that_must_judge(key, composite, links):
    world = _World()
    _aapl(world)
    _rival(world, key, composite, links)
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "AAPL") == []
    assert (tem.TICKER_CLAIMED_BY_OTHER_SECURITY, date(2003, 9, 10), None) in _gaps(
        proposal, "AAPL"
    )


def test_only_the_root_label_string_is_exempt():
    # FISV's chain asked under FISV names FI newest; FI is the root label, exempt, so a span of
    # ours on FI stands, citing it.
    world = _World()
    world.name(
        "FI",
        isin="US0000000003",
        composite="BBG000000003",
        share="BBG000000033",
        events=[("2003-09-10", "FI")],
    )
    _rival(world, "FISV@2025-01-02", "BBG000BK2F42", [("2023-06-06", "FI"), ("2003-09-10", "FISV")])
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "FI") == [("FI", date(2003, 9, 10), None)]
    assert "root_labelled_claims_not_judged" in proposal.spans[0].evidence


def test_listed_ticker_refuses_a_trailing_newline():
    world = _World()
    world.name(
        "AAPL",
        isin="US0378331005",
        composite="BBG000B9XRY4",
        share="BBG001S5N8V8",
        events=[("2010-01-04", "AAPL"), ("2003-09-10", "AAP\n")],
    )
    proposal = propose_ticker_entity_map(world.inputs())
    assert _spans(proposal, "AAPL") == [("AAPL", date(2010, 1, 4), None)]
    assert _gaps(proposal, "AAPL")[0][0] == tem.EVENT_TICKER_UNUSABLE
