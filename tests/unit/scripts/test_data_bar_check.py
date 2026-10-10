"""Unit tests for the D-28 data bar check CLI (plan 185-16).

Every condition is a pure predicate over query results (T-185-16-01: no
hard-coded pass, every verdict carries evidence counts). The database is never
touched: the CLI's gather step is exercised through a fake cursor that records
SQL and replays canned rows.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from scripts.ops.bars import ops_data_bar_check as mod

_FIXTURE = (
    __file__.rsplit("/tests/", 1)[0] + "/tests/fixtures/bars/corrupt_1d_dry_run_2026_09_26.txt"
)


# --- fixture parsing ---------------------------------------------------------------


def test_parse_dry_run_keys_takes_confirmed_and_market_event_1d_rows_only() -> None:
    text = """# header

## CONFIRMED_CORRUPT (2)

| symbol | tf | timestamp | open |
|---|---|---|---|
| AMAT | 1d | 2007-01-16T00:00:00Z | 19.5 |
| XY | 5m | 2007-01-16T14:30:00Z | 1.0 |

## AMBIGUOUS (1)

| symbol | tf | timestamp |
|---|---|---|
| NOPE | 1d | 2008-01-02T00:00:00Z |

## MARKET_EVENT (1)

| symbol | tf | timestamp |
|---|---|---|
| LEH | 1d | 2008-09-15T00:00:00Z |
"""
    keys = mod.parse_dry_run_keys(text)
    assert keys == (
        ("AMAT", "2007-01-16T00:00:00Z"),
        ("LEH", "2008-09-15T00:00:00Z"),
    )


def test_parse_dry_run_keys_on_the_recorded_fixture_finds_72_1d_keys() -> None:
    keys = mod.parse_dry_run_keys(open(_FIXTURE).read())
    assert len(keys) == 72
    assert ("AMAT", "2007-01-16T00:00:00Z") in keys
    assert all(len(symbol) > 0 for symbol, _ in keys)


# --- pure conditions ----------------------------------------------------------------


def _scrub(**overrides: object) -> mod.CheckResult:
    kwargs: dict[str, object] = {
        "fact_passed": True,
        "fixture_total": 72,
        "fixture_quarantined": 28,
        "fixture_replaced": 44,
        "legacy_total": 15,
        "legacy_quarantined": 5,
        "legacy_replaced": 10,
    }
    kwargs.update(overrides)
    return mod.scrub_condition(**kwargs)  # type: ignore[arg-type]


def test_scrub_condition_passes_when_every_key_is_quarantined_or_replaced() -> None:
    """185-34: a known answer is resolved when quarantined, or replaced by a scrubbed bar of a
    different source with the judged IBKR value kept in ohlcv_revision."""
    ok = _scrub()
    assert ok.ok
    for part in ("quarantined 28", "replaced 44", "open 0", "quarantined 5", "replaced 10"):
        assert part in ok.evidence
    assert _scrub(fixture_quarantined=72, fixture_replaced=0).ok


def test_scrub_condition_fails_naming_the_open_count() -> None:
    no_fact = _scrub(fact_passed=False)
    assert not no_fact.ok

    short = _scrub(fixture_replaced=43)
    assert not short.ok
    assert "open 1" in short.evidence

    legacy_open = _scrub(legacy_replaced=9)
    assert not legacy_open.ok
    assert "open 1" in legacy_open.evidence

    assert not _scrub(fixture_total=0, fixture_quarantined=0, fixture_replaced=0).ok


def test_scrub_condition_holds_the_d28_contract_of_15_legacy_keys() -> None:
    """72/15 are the D-28 contract, not tunables: a short legacy key set fails."""
    assert not _scrub(legacy_total=14, legacy_quarantined=4, legacy_replaced=10).ok


def test_legacy_keys_are_the_15_migration_381_keys_fixed_independent_of_the_flags() -> None:
    """The 15 1d keys migration 381 copied from price_sanity_status = 'confirmed_corrupt'.
    185-30 retired 12 of their flags, so the set is a constant, never read back from flags."""
    keys = mod.LEGACY_1D_KEYS
    assert len(keys) == 15
    assert len(set(keys)) == 15
    assert ("SPY", "2007-04-02T00:00:00Z") in keys
    assert ("DIA", "2009-06-02T00:00:00Z") in keys


_SCRUB_AT = datetime(2026, 10, 3, 20, 59, tzinfo=UTC)
_LOADED = datetime(2026, 10, 3, 20, 55, tzinfo=UTC)


def _status(**overrides: object) -> str:
    kwargs: dict[str, object] = {
        "quarantined": False,
        "stored_source": "tradier",
        "has_ibkr_revision": True,
        "last_revision_at": _LOADED,
        "scrub_at": _SCRUB_AT,
    }
    kwargs.update(overrides)
    return mod.known_answer_status(**kwargs)  # type: ignore[arg-type]


def test_known_answer_replaced_needs_a_different_source_an_ibkr_revision_and_a_later_scrub() -> (
    None
):
    assert _status() == "replaced"


def test_known_answer_quarantine_wins_over_replaced() -> None:
    """A replaced key whose new bar carries a D2a quarantine flag counts as quarantined."""
    assert _status(quarantined=True) == "quarantined"
    assert _status(quarantined=True, stored_source=None, has_ibkr_revision=False) == ("quarantined")


def test_known_answer_without_a_revision_row_is_open() -> None:
    """No ohlcv_revision row: no evidence of what was replaced (T-185-34-01)."""
    assert _status(has_ibkr_revision=False, last_revision_at=None) == "open"


@pytest.mark.parametrize("source", ["ibkr_named", "ibkr_venue", None])
def test_known_answer_still_on_an_ibkr_source_or_hidden_is_open(source: str | None) -> None:
    assert _status(stored_source=source) == "open"


def test_known_answer_revised_after_the_scrub_is_open() -> None:
    """The scrub has not judged the current bar: a revision at or after the last scrub fact."""
    assert _status(last_revision_at=_SCRUB_AT) == "open"
    assert _status(scrub_at=None) == "open"


def test_seam_condition_missing_fact_fails_and_actions_need_split_seam_coverage() -> None:
    assert not mod.seam_condition(
        fact_passed=False, actions=(), split_seam_bars={}, daily_batches=()
    ).ok

    ok_empty = mod.seam_condition(
        fact_passed=True, actions=(), split_seam_bars={}, daily_batches=()
    )
    assert ok_empty.ok

    action = ("FRHC", date(2012, 10, 31), datetime(2026, 9, 30, tzinfo=UTC))
    flagged = mod.seam_condition(
        fact_passed=True,
        actions=(action,),
        split_seam_bars={"FRHC": [date(2012, 10, 1), date(2012, 11, 1)]},
        daily_batches=(),
    )
    assert flagged.ok

    unflagged = mod.seam_condition(
        fact_passed=True, actions=(action,), split_seam_bars={}, daily_batches=()
    )
    assert not unflagged.ok

    rederived = mod.seam_condition(
        fact_passed=True,
        actions=(action,),
        split_seam_bars={},
        daily_batches=(datetime(2026, 10, 1, tzinfo=UTC),),
    )
    assert rederived.ok


def test_dispositions_condition_fails_on_any_unresolved_late_name() -> None:
    ok = mod.dispositions_condition({"AA": "reached_window_start", "AMD": "moved"})
    assert ok.ok
    bad = mod.dispositions_condition({"AA": "reached_window_start", "HOOD": "unresolved"})
    assert not bad.ok
    assert "HOOD" in bad.evidence


def test_dispositions_condition_excludes_tradier_history_late_names_and_reports_them() -> None:
    """185-34: a late name with Tradier history has its history from Tradier, not the truncated
    IBKR route, so it is out of scope (orchestrator call 2026-10-06, pending owner review). The
    excluded count and the excluded unresolved names are on the evidence line."""
    dispositions = {
        "AA": "reached_window_start",
        "DAL": "unresolved",
        "ODFL": "unresolved",
        "XOM": "reached_window_start",
    }
    result = mod.dispositions_condition(dispositions, tradier_history={"DAL", "ODFL", "XOM"})
    assert result.ok
    assert "Tradier-history excluded 3" in result.evidence
    assert "DAL" in result.evidence and "ODFL" in result.evidence
    assert "IBKR-sourced late names 1" in result.evidence


def test_dispositions_condition_unresolved_ibkr_name_still_fails_and_is_named_in_full() -> None:
    names = [f"N{i:02d}" for i in range(12)]
    dispositions = {name: "unresolved" for name in names} | {"DAL": "unresolved"}
    result = mod.dispositions_condition(dispositions, tradier_history={"DAL"})
    assert not result.ok
    assert "unresolved 12" in result.evidence
    for name in names:  # every residue name, not a sample
        assert name in result.evidence


def test_premove_condition_fails_on_pre_move_bar_unless_venue_bars_allowed() -> None:
    assert mod.premove_condition(n_pre_move_bars=0, venue_bars_1d=False).ok
    assert not mod.premove_condition(n_pre_move_bars=3, venue_bars_1d=False).ok
    allowed = mod.premove_condition(n_pre_move_bars=3, venue_bars_1d=True)
    assert allowed.ok
    assert "venue_bars_1d" in allowed.evidence
    assert "IBKR-source" in allowed.evidence


def test_premove_sql_counts_ibkr_sources_only() -> None:
    """185-34: Tradier consolidated history before an IBKR venue move is real history, not
    truncation; only IBKR-source bars before the SMART head are a defect."""
    assert "m.source = ANY(%s)" in mod._PREMOVE_SQL
    assert set(mod.IBKR_1D_SOURCES) == {"ibkr_named", "ibkr_venue"}
    assert "ohlcv_venue_head" in mod._PREMOVE_SQL


def test_docstring_describes_the_source_aware_conditions() -> None:
    doc = " ".join((mod.__doc__ or "").split())
    assert "ohlcv_revision" in doc
    assert "Late names with Tradier history" in doc
    assert "IBKR-source" in doc


def test_dividend_condition_requires_share_and_total_return_symbol() -> None:
    assert mod.dividend_condition(covered=925, eligible=931, total_return_importable=True).ok
    short = mod.dividend_condition(covered=900, eligible=931, total_return_importable=True)
    assert not short.ok
    no_fn = mod.dividend_condition(covered=925, eligible=931, total_return_importable=False)
    assert not no_fn.ok


# test_survivorship_condition_requires_all_six_apr_keys retired 2026-10-09 with
# condition 6 itself (todo 514; owner: survivorship bias is not an issue).


def test_is_active_condition_fails_on_any_soft_deleted_inventory_name() -> None:
    assert mod.is_active_condition(deactivated=0).ok
    failed = mod.is_active_condition(deactivated=1)
    assert not failed.ok


def test_summarize_exits_zero_only_when_every_condition_passes() -> None:
    ok_result = mod.CheckResult(condition="c", ok=True, evidence="e")
    fail_result = mod.CheckResult(condition="c", ok=False, evidence="e")
    assert mod.summarize([ok_result, ok_result]) == 0
    assert mod.summarize([ok_result, fail_result]) == 1


# --- CLI over a fake connection ------------------------------------------------------


class FakeCursor:
    """Replies are per-marker queues: consecutive queries on the same tables
    (the venue flag and the survivorship keys both read config_state) get
    consecutive replies in execution order."""

    def __init__(self, queues: dict[str, list[object]], executed: list) -> None:
        self._queues = queues
        self._next: object = None
        self._executed = executed

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def execute(self, sql: str, params: tuple | dict = ()) -> None:
        marker = _marker(sql)
        self._executed.append((marker, params))
        self._next = self._queues[marker].pop(0)

    def fetchall(self):
        return self._next if isinstance(self._next, list) else []

    def fetchone(self):
        if isinstance(self._next, list):
            return self._next[0] if self._next else None
        return self._next


def _marker(sql: str) -> str:
    # The late names with Tradier history (plan 185-48: stored canonical bars, not the policy).
    if "/* tradier_history */" in sql:
        return "tradier_history"
    for key in (
        "ohlcv_revision",  # known-answer status (fixture keys, then legacy keys)
        "ohlcv_venue_head",  # pre-move count
        "integrity_monitor",
        "corporate_action",
        "split_seam",
        "bar_derivation_batch",
        "market_data_ohlcv_tradeable",
        "instruments",
        "config_state",
        "ohlcv_request",
        "dividend_event_coverage",
    ):
        if key in sql:
            return key
    raise AssertionError(f"unexpected SQL in fake: {sql}")


_SIX_KEYS = [
    ("alpha.survivorship.delisting_return.nasdaq",),
    ("alpha.survivorship.delisting_return.nyse_amex",),
    ("alpha.survivorship.hazard.nasdaq_annual",),
    ("alpha.survivorship.hazard.nyse_amex_annual",),
    ("alpha.survivorship.haircut.small_cap_annual",),
    ("alpha.survivorship.trading_days_per_year",),
]


_FIXTURE_KEYS = mod.parse_dry_run_keys(open(_FIXTURE).read())


def _known_rows(keys, quarantined: bool = False, hidden: bool = False) -> list[tuple]:
    """(symbol, ts, quarantined, stored_source, has_ibkr_revision, last_revision_at,
    stale_status): stale_status is a stored row still carrying the pre-381
    price_sanity_status = 'confirmed_corrupt' the tradeable view filters on."""
    if quarantined:
        return [(s, t, True, None, False, None, False) for s, t in keys]
    return [(s, t, False, "tradier", True, _LOADED, hidden) for s, t in keys]


def _replies() -> dict[str, list[object]]:
    return {
        "integrity_monitor": [(True, _SCRUB_AT), (True, _SCRUB_AT)],  # scrub, then seam fact
        # all fixture keys quarantined, then every legacy key replaced
        "ohlcv_revision": [_known_rows(_FIXTURE_KEYS, True), _known_rows(mod.LEGACY_1D_KEYS)],
        "tradier_history": [[]],  # no late name with Tradier history
        "corporate_action": [[]],  # no seam-audit splits
        "split_seam": [[]],
        "bar_derivation_batch": [[]],  # no daily batches
        "ohlcv_venue_head": [(0,)],  # no pre-move bars visible
        "config_state": [("false",), list(_SIX_KEYS)],  # venue flag, then keys
        "instruments": [(925, 931, 0)],  # covered, eligible, deactivated
        "ohlcv_request": [[]],  # no stored requests
    }


class FakeConn:
    def __init__(self, replies: dict[str, list[object]]) -> None:
        self._queues = {marker: list(items) for marker, items in replies.items()}
        self.executed: list[tuple[str, object]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._queues, self.executed)


def test_main_prints_one_line_per_condition_and_exits_1_on_fail(monkeypatch, capsys) -> None:
    conn = FakeConn(_replies())
    monkeypatch.setattr(mod, "_connect", lambda: _fake_ctx(conn))
    monkeypatch.setattr(mod, "_late_names", lambda conn: {"AMD": date(2015, 10, 1)})
    monkeypatch.setattr(mod, "_load_apr", lambda conn: {})
    monkeypatch.setattr(mod, "_total_return_importable", lambda: True)
    monkeypatch.setattr(mod, "_FIXTURE_PATH", Path(_FIXTURE))

    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    assert excinfo.value.code == 1
    lines = [line for line in capsys.readouterr().out.splitlines() if line[:4] in ("PASS", "FAIL")]
    assert (
        len(lines) == 6
    )  # six conditions since 2026-10-09 (condition 6 retired, todo 514; numbering keeps its gap)
    fails = [line for line in lines if line.startswith("FAIL")]
    # The only failing condition: no stored requests, so AMD stays unresolved.
    assert len(fails) == 1
    assert "unresolved" in fails[0]


def test_main_exits_0_when_every_condition_holds(monkeypatch, capsys) -> None:
    conn = FakeConn(_replies())
    monkeypatch.setattr(mod, "_connect", lambda: _fake_ctx(conn))
    monkeypatch.setattr(mod, "_late_names", lambda conn: {})
    monkeypatch.setattr(mod, "_load_apr", lambda conn: {})
    monkeypatch.setattr(mod, "_total_return_importable", lambda: True)
    monkeypatch.setattr(mod, "_FIXTURE_PATH", Path(_FIXTURE))

    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out


class _FakeCtx:
    def __init__(self, conn) -> None:
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc) -> None:
        return None


def _fake_ctx(conn) -> _FakeCtx:
    return _FakeCtx(conn)


def _patch(monkeypatch, conn, late: dict) -> None:
    monkeypatch.setattr(mod, "_connect", lambda: _fake_ctx(conn))
    monkeypatch.setattr(mod, "_late_names", lambda conn: late)
    monkeypatch.setattr(mod, "_load_apr", lambda conn: {})
    monkeypatch.setattr(mod, "_total_return_importable", lambda: True)
    monkeypatch.setattr(mod, "_FIXTURE_PATH", Path(_FIXTURE))


def test_run_checks_counts_known_answers_by_status_and_passes_ibkr_sources(monkeypatch) -> None:
    replies = _replies()
    fixture_rows = _known_rows(_FIXTURE_KEYS)
    fixture_rows[0] = (
        *fixture_rows[0][:4],
        False,
        None,
        False,
    )  # replaced without a revision: open
    replies["ohlcv_revision"] = [fixture_rows, _known_rows(mod.LEGACY_1D_KEYS)]
    conn = FakeConn(replies)
    _patch(monkeypatch, conn, {})

    results = {r.condition: r for r in mod.run_checks(conn)}
    scrub = results["scrub_pass_complete"]
    assert not scrub.ok
    assert "replaced 71" in scrub.evidence and "open 1" in scrub.evidence

    params = {marker: p for marker, p in conn.executed}
    assert list(params["ohlcv_venue_head"][0]) == list(mod.IBKR_1D_SOURCES)
    revision_params = params["ohlcv_revision"]
    assert list(revision_params[0]) == list(mod.IBKR_1D_SOURCES)
    assert "tradier" not in revision_params[0]


def test_run_checks_excludes_tradier_history_late_names(monkeypatch) -> None:
    """DAL is late and has Tradier history: out of condition 3. AMD (IBKR-sourced, no stored
    requests) stays unresolved and fails the condition."""
    replies = _replies()
    replies["tradier_history"] = [[("DAL",)]]
    conn = FakeConn(replies)
    _patch(monkeypatch, conn, {"AMD": date(2015, 10, 1), "DAL": date(2008, 1, 2)})

    results = {r.condition: r for r in mod.run_checks(conn)}
    late = results["late_name_dispositions"]
    assert not late.ok
    assert "unresolved 1 (AMD)" in late.evidence
    assert "Tradier-history excluded 1" in late.evidence and "DAL" in late.evidence
    params = dict(conn.executed)["tradier_history"]
    assert sorted(params[0]) == ["AMD", "DAL"]
    assert params[1] == "tradier"


def test_tradier_history_predicate_reads_stored_canonical_bars_not_the_open_policy() -> None:
    """Plan 185-48: since 185-47 the open 1d default names IBKR, so a policy predicate would
    exclude nobody and silently widen condition 3 to every name the swap made late. A name
    with any canonical Tradier 1d bar has Tradier history before D; that is the exclusion."""
    sql = " ".join(mod._TRADIER_HISTORY_LATE_SQL.split())
    assert "market_data_ohlcv_tradeable" in sql
    assert "m.timeframe = '1d'" in sql and "m.source = %s" in sql
    assert "bar_source_policy" not in sql and "valid_to" not in sql
    source = Path(mod.__file__).read_text()
    assert "from scripts.infrastructure.backfill" not in source  # the deleted loader
    assert "TRADIER_OWNED_SQL" not in source


def test_known_answer_sql_judges_the_stored_row_not_the_tradeable_view() -> None:
    """185-34 live run: the tradeable view still filters price_sanity_status, which the
    Tradier load left on 10 replaced legacy bars. The stored row decides the status, so a
    replaced bar the view hides is not misread as open."""
    sql = mod._KNOWN_ANSWER_SQL
    assert re.search(r"\bJOIN\s+market_data_ohlcv\s+m\b", sql)
    assert "market_data_ohlcv_tradeable" not in sql
    assert "price_sanity_status" in sql


def test_replaced_keys_hidden_by_a_stale_status_pass_and_are_reported(monkeypatch) -> None:
    replies = _replies()
    replies["ohlcv_revision"] = [
        _known_rows(_FIXTURE_KEYS, True),
        _known_rows(mod.LEGACY_1D_KEYS, hidden=True),
    ]
    conn = FakeConn(replies)
    _patch(monkeypatch, conn, {})

    scrub = {r.condition: r for r in mod.run_checks(conn)}["scrub_pass_complete"]
    assert scrub.ok
    assert "replaced 15" in scrub.evidence
    assert "hidden by a stale price_sanity_status 15" in scrub.evidence


def test_scrub_condition_hidden_count_is_evidence_not_a_failure() -> None:
    result = _scrub(replaced_hidden=10)
    assert result.ok
    assert "hidden by a stale price_sanity_status 10" in result.evidence
