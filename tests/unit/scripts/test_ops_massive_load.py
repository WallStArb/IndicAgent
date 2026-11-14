"""Massive per-year loader: the day accounting and the guards that need no database."""

from __future__ import annotations

import gzip
from datetime import UTC, date, datetime

import numpy as np
import pytest

from scripts.ops.bars import ops_massive_load as loader
from src.intelligence.bars.massive_flat import FlatBars
from src.intelligence.bars.massive_symbol_map import TickerSpan, unaccounted_instruments

DAY = date(2024, 6, 11)
T0 = int(datetime(2024, 6, 11, 13, 30, tzinfo=UTC).timestamp()) * 1_000_000_000
STEP = 300 * 1_000_000_000


def _bars():
    # AAA two bars, BBB one bar, CCC one bar (CCC has no span that day)
    tickers = np.array(["AAA", "BBB", "CCC"])
    z = np.zeros(4)
    return FlatBars(
        tickers=tickers,
        ticker_index=np.array([0, 0, 1, 2], dtype=np.int32),
        t_ns=np.array([T0, T0 + STEP, T0, T0], dtype=np.int64),
        open=z,
        high=z,
        low=z,
        close=z,
        volume=np.zeros(4, dtype=np.int64),
        n_untraded_rows=3,
        traded_minutes=np.array([9, 4, 2]),
    )


def _mapping():
    return {
        "AAA": TickerSpan("e1", "AAA", "AAA", date(2003, 9, 10), None),
        "BBB": TickerSpan("e2", "BBX", "BBB", date(2003, 9, 10), None),
    }


def _held(*pairs: tuple[str, int]) -> loader.DaySlots:
    return loader.DaySlots(
        np.array([p[0] for p in pairs], dtype=object),
        np.array([p[1] // 1000 for p in pairs], dtype=np.int64),
    )


def test_day_balance_counts_mapped_unmapped_and_massive_only_slots():
    report = loader.account_day(DAY, _bars(), _mapping(), _held(("AAA", T0)), "5m")
    assert (report.bars_out, report.bars_unmapped) == (3, 1)
    assert (report.mapped_tickers, report.unmapped_tickers) == (2, 1)
    assert (report.traded_minutes_in, report.traded_minutes_mapped) == (15, 13)
    assert report.untraded_rows == 3
    # AAA's second bar and BBX's bar have no incumbent row: the expected unselected slots
    assert report.massive_only == 2
    assert report.unmapped_sample == ["CCC"]


def test_instrument_symbol_not_the_file_ticker_keys_the_incumbent_slot():
    report = loader.account_day(DAY, _bars(), _mapping(), _held(("BBX", T0)), "5m")
    assert report.massive_only == 2  # AAA x2 unheld; BBX held


def test_an_empty_mapping_excludes_every_bar():
    report = loader.account_day(DAY, _bars(), {}, loader.DaySlots.empty(), "5m")
    assert (report.bars_out, report.bars_unmapped, report.massive_only) == (0, 4, 0)


def test_a_1d_session_is_held_by_any_incumbent_row_of_the_symbol():
    held = loader.DaySlots(np.array(["AAA"], dtype=object), np.zeros(1, dtype=np.int64))
    report = loader.account_day(DAY, _bars(), _mapping(), held, "1d")
    assert report.massive_only == 1  # BBX unheld; both AAA bars share the one session slot


def _reference_account(bars, mapping, incumbent: set, slot_of) -> tuple:
    """The per-row loop account_day replaced (commit 93fdde51c), kept as the parity oracle."""
    names = bars.tickers[bars.ticker_index]
    in_map = np.array([str(t) in mapping for t in bars.tickers], dtype=bool)
    mapped = in_map[bars.ticker_index]
    massive_only = sum(
        (mapping[str(n)].symbol, slot_of(int(t))) not in incumbent
        for n, t in zip(names[mapped], bars.t_ns[mapped], strict=True)
    )
    return (
        len({str(n) for n in names[mapped]}),
        int(mapped.sum()),
        massive_only,
        sorted({str(n) for n in names[~mapped]})[:5],
    )


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("timeframe", ["5m", "1d"])
def test_vectorized_accounting_matches_the_per_row_loop(seed, timeframe):
    rng = np.random.default_rng(seed)
    tickers = np.array([f"T{i:02d}" for i in range(12)])
    n = int(rng.integers(0, 60))
    index = np.sort(rng.integers(0, len(tickers), n)).astype(np.int32)
    t_ns = T0 + rng.integers(0, 78, n).astype(np.int64) * STEP
    bars = FlatBars(tickers, index, t_ns, *(np.zeros(n),) * 4, np.zeros(n, dtype=np.int64))
    symbols = [f"S{i % 5}" for i in range(len(tickers))]  # several tickers share a symbol
    mapping = {
        str(t): TickerSpan(f"e{i}", symbols[i], str(t), date(2003, 1, 1), None)
        for i, t in enumerate(tickers)
        if rng.random() < 0.7
    }
    held_pairs = {
        (f"S{rng.integers(0, 7)}", int(T0 + rng.integers(0, 78) * STEP))
        for _ in range(int(rng.integers(0, 40)))
    }
    if timeframe == "5m":
        incumbent = {(s, datetime.fromtimestamp(t / 1e9, UTC)) for s, t in held_pairs}
        slot_of = lambda t: datetime.fromtimestamp(t / 1e9, UTC)  # noqa: E731
        held = _held(*held_pairs)
    else:
        incumbent = {(s, DAY) for s, _ in held_pairs}
        slot_of = lambda _t: DAY  # noqa: E731
        held = loader.DaySlots(
            np.array([s for s, _ in held_pairs], dtype=object), np.zeros(len(held_pairs), np.int64)
        )
    report = loader.account_day(DAY, bars, mapping, held, timeframe)
    assert (
        report.mapped_tickers,
        report.bars_out,
        report.massive_only,
        report.unmapped_sample,
    ) == _reference_account(bars, mapping, incumbent, slot_of)


def test_years_must_be_newest_first(capsys):
    with pytest.raises(SystemExit):
        loader.main(["--timeframe", "5m", "--years", "2023", "2024"])


class _Cur:
    def __init__(self, rows):
        self.rows, self.params = rows, None

    def execute(self, _sql, params=None):
        self.params = params

    def fetchall(self):
        return self.rows


def _us(ts: datetime) -> int:
    return int(ts.timestamp()) * 1_000_000


def test_incumbent_slots_group_a_month_query_by_session_date():
    a = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
    b = datetime(2024, 6, 4, 13, 30, tzinfo=UTC)
    got = loader.incumbent_slots(
        _Cur([("X", _us(a)), ("Y", _us(a)), ("X", _us(b))]), "5m", DAY, DAY
    )
    assert sorted(got) == [a.date(), b.date()]
    assert list(got[a.date()].symbols) == ["X", "Y"]
    assert list(got[a.date()].keys) == [_us(a), _us(a)]
    assert list(got[b.date()].symbols) == ["X"]
    one_day = loader.incumbent_slots(
        _Cur([("X", date(2024, 6, 2)), ("X", date(2024, 6, 3))]),
        "1d",
        date(2024, 6, 3),
        date(2024, 6, 3),
    )
    assert list(one_day) == [date(2024, 6, 3)]
    assert list(one_day[date(2024, 6, 3)].symbols) == ["X"]
    assert list(one_day[date(2024, 6, 3)].keys) == [0]


def test_never_selected_kinds_hold_no_incumbent_slot():
    """A slot only iex_rth holds is excluded before a Massive load and unselected after it, so it
    counts as Massive-only, as the gate's windowed --compare counts it."""
    for timeframe in ("5m", "1d"):
        cur = _Cur([])
        loader.incumbent_slots(cur, timeframe, DAY, DAY)
        assert sorted(loader.NEVER_SELECTED_KINDS) in cur.params


def test_a_month_without_a_mapped_bar_writes_nothing():
    batch = loader.MonthBatch()
    batch.parts.append(tuple(np.empty(0) for _ in range(8)))
    fresh, total = loader._flush(None, None, batch, loader.LoadResult(n_offered=3))
    assert total == loader.LoadResult(n_offered=3) and fresh.parts == []


def test_pairs_in_never_matches_an_unknown_code_and_packs_exactly():
    codes = np.array([0, 1, -1, 1], dtype=np.int64)
    keys = np.array([5, 5, 5, 6], dtype=np.int64)
    held = loader.pairs_in(codes, keys, np.array([1, 0]), np.array([6, 5]))
    assert held.tolist() == [True, False, False, True]


def _day_file(root, day: date, tickers: list[str]) -> None:
    folder = root / "day_aggs_v1" / f"{day.year}" / f"{day.month:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    body = "ticker,volume,open,close,high,low,window_start,transactions\n" + "".join(
        f"{t},1,1,1,1,1,0,1\n" for t in tickers
    )
    with gzip.open(folder / f"{day.isoformat()}.csv.gz", "wt") as handle:
        handle.write(body)


def test_archive_index_bitsets_answer_like_the_ticker_sets(tmp_path):
    served = {
        date(2024, 6, 3): ["AAA", "BBB"],
        date(2024, 6, 4): ["BBB", "CCC", "DDD"],
        date(2024, 6, 5): [],
    }
    for day, tickers in served.items():
        _day_file(tmp_path, day, tickers)
    index = loader.ArchiveIndex(tmp_path)
    assert index.sessions == sorted(served)
    assert index.present_on(date(2024, 6, 3)) is index.present_on(date(2024, 6, 3))
    for day, tickers in served.items():
        present = index.present_on(day)
        assert set(present) == set(tickers) and len(present) == len(tickers)
        for ticker in ("AAA", "BBB", "CCC", "DDD", "EEE", 7):
            assert (ticker in present) == (ticker in tickers)
    # a session read before later tickers got ids still answers for them
    assert "DDD" not in index.present_on(date(2024, 6, 3))


def test_disk_refusal_names_the_floor():
    assert loader.disk_refusal(20, 100, 0.10) is None
    assert "under the 10%" in loader.disk_refusal(9, 100, 0.10)


def _batch_inputs(rows_per_symbol: dict[str, int], day: int = 0) -> FlatBars:
    tickers = np.array(sorted(rows_per_symbol))
    index = np.repeat(np.arange(len(tickers)), [rows_per_symbol[t] for t in tickers]).astype(
        np.int32
    )
    start = T0 + day * 86_400 * 10**9
    t_ns = np.concatenate([start + np.arange(rows_per_symbol[t]) * STEP for t in tickers])
    n = len(index)
    prices = np.full(n, 10.0)
    return FlatBars(tickers, index, t_ns, prices, prices, prices, prices, np.ones(n, np.int64))


def test_month_batch_builds_one_raw_batch_with_per_file_serve_time(monkeypatch):
    first, second = (datetime(2024, 6, d, 22, tzinfo=UTC) for d in (3, 4))
    served = {"f3": first, "f4": second}
    monkeypatch.setattr(
        loader,
        "manifest_record",
        lambda path: {"etag": "e", "sha256": "s", "last_modified": str(path)},
    )
    monkeypatch.setattr(loader, "massive_answered_at", lambda path, _symbol: served[str(path)])
    mapping = _mapping()
    batch = loader.MonthBatch()
    batch.add(date(2024, 6, 3), "f3", _batch_inputs({"AAA": 3, "BBB": 2, "CCC": 1}), mapping, None)
    batch.add(date(2024, 6, 4), "f4", _batch_inputs({"AAA": 1}, day=1), mapping, "epoch1")

    class _Ingress:
        source, timeframe, kind = "massive", "5m", "sip_flat_agg"

    class _Write:
        future_tolerance_s = 3600
        batch_rows = 50_000

    class _Params:
        vendor_codes, kind_codes, write = {"massive"}, {"sip_flat_agg"}, _Write()

    raw = batch.raw_batch(_Ingress(), _Params())
    assert raw.symbols.tolist() == ["AAA"] * 4 + ["BBX"] * 2  # CCC unmapped, BBB as BBX
    expected_served = [first, first, first, second, first, first]
    assert raw.served_us.tolist() == [loader.datetime_to_us(t) for t in expected_served]
    lineage = batch.lineage()
    assert sorted(lineage) == ["AAA", "BBX"]
    assert [f[0] for f in lineage["AAA"]["files"]] == ["2024-06-03", "2024-06-04"]
    assert lineage["AAA"]["definition_epoch_ids"] == ["None", "epoch1"]
    assert lineage["BBX"]["ticker_events"] == {"e2": "BBB"}


def test_all_tickers_checks_every_instrument_and_loads_1d_only():
    active, every = ["AAPL", "MSFT"], ["AAPL", "MSFT", "DEAD"]
    assert loader.checked_symbols(False, active, every) == ["AAPL", "MSFT"]
    assert loader.checked_symbols(True, active, every) == ["AAPL", "DEAD", "MSFT"]
    with pytest.raises(SystemExit):
        loader.main(["--timeframe", "5m", "--years", "2010", "--all-tickers"])


def test_a_dead_name_without_a_span_or_gap_row_refuses_an_all_tickers_run():
    spans = [TickerSpan("e1", "AAPL", "AAPL", date(2003, 9, 10), None)]
    checked = loader.checked_symbols(True, ["AAPL"], ["AAPL", "DEAD"])
    assert unaccounted_instruments(checked, spans, set()) == ["DEAD"]
    assert unaccounted_instruments(checked, spans, {"DEAD"}) == []


class _FakeCursor:
    """symbol, ticker_event and instruments answers for run(): one active name with a span, one
    inactive name with neither a span nor a gap row (or, when `span_for_dead`, with a span)."""

    def __init__(self, span_for_dead: bool = False):
        self.span_for_dead = span_for_dead
        self.sql = ""

    def execute(self, sql, *args):
        self.sql = sql

    def fetchall(self):
        if "ticker_event" in self.sql:
            rows = [("e1", "AAPL", "AAPL", date(2003, 9, 10), None)]
            if self.span_for_dead:
                rows.append(("e2", "DEAD", "DEAD", date(2003, 9, 10), date(2008, 1, 1)))
            return rows
        if "is_active" in self.sql:
            return [("AAPL",)]
        return [("AAPL",), ("DEAD",)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Reached(Exception):
    """Raised by the stub archive index: the completeness check was passed."""


def _run_loader(monkeypatch, tmp_path, argv, cursor):
    gap = tmp_path / "gap_list.csv"
    gap.write_text("symbol\n")
    conn = type("Conn", (), {"cursor": lambda self: cursor, "close": lambda self: None})()
    monkeypatch.setattr(loader.psycopg, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(loader, "ArchiveIndex", lambda: (_ for _ in ()).throw(_Reached()))
    monkeypatch.setattr(loader, "setup_service_logging", lambda *a, **k: None)
    return loader.main([*argv, "--gap-list", str(gap)])


def test_run_refuses_a_dead_name_with_no_span_or_gap_row_only_under_all_tickers(
    monkeypatch, tmp_path, capsys
):
    base = ["--timeframe", "1d", "--years", "2010"]
    assert _run_loader(monkeypatch, tmp_path, [*base, "--all-tickers"], _FakeCursor()) == 2
    assert "DEAD" in capsys.readouterr().out
    with pytest.raises(_Reached):  # without the flag the check passes and the run goes on
        _run_loader(monkeypatch, tmp_path, base, _FakeCursor())


def test_all_tickers_refuses_when_no_name_outside_the_active_set_has_a_span(
    monkeypatch, tmp_path, capsys
):
    argv = ["--timeframe", "1d", "--years", "2010", "--all-tickers"]
    gap = tmp_path / "gap_list.csv"
    gap.write_text("symbol\nDEAD\n")  # accounted for by a gap row, still no span outside active
    conn = type("Conn", (), {"cursor": lambda self: _FakeCursor(), "close": lambda self: None})()
    monkeypatch.setattr(loader.psycopg, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(loader, "setup_service_logging", lambda *a, **k: None)
    assert loader.main([*argv, "--gap-list", str(gap)]) == 2
    assert "adds nothing" in capsys.readouterr().out
    with pytest.raises(_Reached):  # a span for the dead name lets the run past both checks
        _run_loader(monkeypatch, tmp_path, argv, _FakeCursor(span_for_dead=True))


def test_all_tickers_parses_with_1d(monkeypatch):
    seen = []
    monkeypatch.setattr(loader, "run", lambda args: seen.append(args) or 0)
    assert loader.main(["--timeframe", "1d", "--years", "2010", "--all-tickers"]) == 0
    assert seen[0].all_tickers and seen[0].timeframe == "1d"
