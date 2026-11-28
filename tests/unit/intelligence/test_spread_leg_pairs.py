"""The spread_leg pair check (todo 678) and its wiring into the nightly reconciliation audit."""

import asyncio
from datetime import UTC, datetime

from services.bar_reconciliation_audit import BarReconciliationAudit
from src.intelligence.spread_leg_pairs import pair_symbols, spread_leg_problems

SYMBOLS = frozenset({"SPY", "IPO", "EZU", "FXE", "UUP"})


def test_pairs_accept_a_symbol_a_list_or_nothing():
    assert pair_symbols({"pair": "UUP"}) == ["UUP"]
    assert pair_symbols({"pair": ["IPO", "EZU"]}) == ["IPO", "EZU"]
    assert pair_symbols({}) == [] and pair_symbols(None) == []


def test_a_malformed_pair_is_none_not_coerced():
    assert pair_symbols({"pair": {"leg": "SPY"}}) is None
    assert pair_symbols({"pair": ["SPY", ["IPO"]]}) is None
    assert pair_symbols({"pair": 5}) is None
    assert pair_symbols("UUP") is None and pair_symbols(["UUP"]) is None  # jsonb not an object


def test_a_clean_set_with_a_hub_has_no_problems():
    rows = {
        "SPY": {"pair": ["IPO", "EZU"]},
        "IPO": {"pair": "SPY"},
        "EZU": {"pair": "SPY"},
        "FXE": {"pair": "UUP"},
        "UUP": {"pair": "FXE"},
    }
    assert spread_leg_problems(list(rows.items()), SYMBOLS) == []


def test_each_defect_is_named():
    rows = {
        "FXE": {"pair": "UUP"},  # UUP has no row
        "SPY": {"pair": ["IPO", "ZZZ"]},  # IPO does not name SPY back; ZZZ is not an instrument
        "IPO": {"pair": "EZU"},
        "EZU": {"note": "no pair"},
    }
    problems = spread_leg_problems(list(rows.items()), SYMBOLS)
    assert "FXE->UUP: partner has no spread_leg row" in problems
    assert "SPY->IPO: IPO does not name SPY back" in problems
    assert "SPY->ZZZ: no such instrument" in problems
    assert "EZU: no evidence pair" in problems


def test_a_non_string_pair_is_a_problem_not_a_type_error():
    rows = [("FXE", {"pair": {"leg": "UUP"}}), ("UUP", {"pair": ["FXE", ["SPY"]]})]
    problems = spread_leg_problems(rows, SYMBOLS)
    assert "FXE: pair is not a symbol or a list of symbols" in problems
    assert "UUP: pair is not a symbol or a list of symbols" in problems


def test_a_self_pair_is_a_problem():
    assert spread_leg_problems([("SPY", {"pair": "SPY"})], SYMBOLS) == ["SPY: pairs with itself"]


class _Conn:
    """Answers the two reads the check makes: the current spread_leg rows, then instruments."""

    def __init__(self, tags: list[tuple[str, dict]], symbols: frozenset[str]):
        self._tags = [{"symbol": s, "evidence": e} for s, e in tags]
        self._symbols = [{"symbol": s} for s in sorted(symbols)]

    async def fetch(self, sql: str):
        return self._tags if "instrument_tags" in sql else self._symbols


def test_the_nightly_audit_judges_every_current_row_and_reports_each_problem():
    conn = _Conn([("FXE", {"pair": "UUP"}), ("UUP", {"pair": "SPY"})], SYMBOLS)
    judged = asyncio.run(BarReconciliationAudit._spread_leg_pairs(conn))
    assert judged.n_judged == 2
    assert judged.result.samples == (
        "FXE->UUP: UUP does not name FXE back",
        "UUP->SPY: partner has no spread_leg row",
    )
    assert judged.result.n_findings == 2


def test_a_finding_is_logged_and_counted_even_when_no_fact_row_lands(monkeypatch):
    """The standalone script's only record was a fact row whose write failure was swallowed
    (exit 0, nothing recorded). In the nightly audit a finding is an error log line and a
    counter increment before any fact is written, so a fact write that lands nothing loses
    neither."""
    from types import SimpleNamespace

    from services import bar_reconciliation_audit as audit

    errors, counts = [], []
    monkeypatch.setattr(audit.logger, "error", lambda event, **kw: errors.append((event, kw)))
    monkeypatch.setattr(audit.logger, "info", lambda *a, **kw: None)
    monkeypatch.setattr(audit.FINDINGS_TOTAL, "add", lambda n, labels: counts.append((n, labels)))

    async def no_fact_lands(*a, **kw):
        return None

    monkeypatch.setattr(audit.BarReconciliationAudit, "_emit_facts", no_fact_lands)
    monkeypatch.setattr(audit.BarReconciliationAudit, "_print_report", lambda *a, **kw: None)

    class _Conn:
        async def fetchval(self, *a):
            return None

        def transaction(self):
            return _Ctx(None)

    class _Ctx:
        def __init__(self, value):
            self._value = value

        async def __aenter__(self):
            return self._value

        async def __aexit__(self, *exc):
            return False

    pool = SimpleNamespace(acquire=lambda: _Ctx(_Conn()))
    grid = SimpleNamespace(
        pooled_share={}, masked_by_tf={}, masked_derived_by_tf={}, partial_by_tf={}
    )
    window = SimpleNamespace(training_window_end=datetime(2026, 11, 27, tzinfo=UTC))
    finding = audit._Judged(audit.CheckResult(1, ("SPY: pairs with itself",)), 1)
    asyncio.run(
        audit.BarReconciliationAudit._report(
            object.__new__(audit.BarReconciliationAudit),
            pool,
            window,
            None,
            {"spread_leg_pairs": finding},
            grid,
        )
    )
    assert (1, {"check": "spread_leg_pairs"}) in counts
    assert errors == [
        (
            "bar_reconciliation.findings",
            {
                "check": "spread_leg_pairs",
                "n_findings": 1,
                "n_judged": 1,
                "subjects": ["SPY: pairs with itself"],
            },
        )
    ]
