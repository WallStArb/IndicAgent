"""The bulk raw path's pure parts (bulk raw load path design, build steps 1 and 2): RawBatch
validation, dedup and chunking against the row path, the classified write's statement order and
rowcount check, the contract's deferral and detector shortcut, packing and the status word. No
database; the SQL against real tables is tests/unit/services/test_ohlcv_raw_bulk_live.py and the
month-scale proof is scripts/ops/bars/ops_raw_bulk_equivalence.py."""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

import services.ohlcv_ingress_contract as contract
from services import bar_load
from services.bar_load import LoadResult, load_status, pack_series_chunks
from services.ohlcv_raw_writer import (
    CLS_NEW,
    CLS_REPLACE,
    CLS_SUPERSEDED,
    CLS_UNCHANGED,
    Classified,
    RawRow,
    _group_by_series,
    build_raw_batch,
    datetime_to_us,
    stage_and_classify,
    us_to_datetime,
    write_classified,
)
from src.intelligence.bars.restatement import DetectorParams, Restatement, detect

VENDORS = {"ibkr", "massive", "derived"}
KINDS = {"named", "sip_flat_agg", "fallback", "5m_grid"}
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
T0 = datetime(2024, 6, 3, 13, 30, tzinfo=UTC)
SERVED = datetime(2024, 6, 4, tzinfo=UTC)
LATEST = NOW + timedelta(seconds=3600)
DETECTOR = DetectorParams(0.02, 500, 20, 0.0005, 0.5, 0.8, 0.002, 0.01, 0.01, 0.2)


def _row(symbol="AAA", i=0, close=10.0, volume=100, served=SERVED, **kw) -> RawRow:
    fields = dict(
        timestamp=T0 + timedelta(minutes=5 * i),
        symbol=symbol,
        timeframe="5m",
        vendor="massive",
        kind="sip_flat_agg",
        open=9.0,
        high=11.0,
        low=8.5,
        close=close,
        volume=volume,
        answered_at=served,
    )
    fields.update(kw)
    return RawRow(**fields)


def _bulk(rows: list[RawRow], chunk_rows: int = 10_000, **kw):
    first = rows[0]
    return build_raw_batch(
        timeframe=first.timeframe,
        vendor=first.vendor,
        kind=first.kind,
        symbols=np.array([r.symbol for r in rows], dtype=object),
        ts_us=np.array([datetime_to_us(r.timestamp) for r in rows], dtype=np.int64),
        open=[r.open for r in rows],
        high=[r.high for r in rows],
        low=[r.low for r in rows],
        close=[r.close for r in rows],
        volume=[0 if r.volume is None else r.volume for r in rows],
        volume_null=[r.volume is None for r in rows],
        served_us=[datetime_to_us(r.answered_at) for r in rows],
        vendor_codes=VENDORS,
        kind_codes=KINDS,
        future_tolerance_s=3600,
        chunk_rows=chunk_rows,
        now=NOW,
        **kw,
    )


def _row_path(rows: list[RawRow]):
    return _group_by_series(rows, vendor_codes=VENDORS, kind_codes=KINDS, latest_allowed=LATEST)


def _outcome(fn, rows):
    try:
        return "ok", fn(rows)
    except ValueError as error:
        return "error", str(error)


def _kept_rows_row_path(by_series) -> list[tuple]:
    return [
        (s[0], datetime_to_us(ts), r.open, r.high, r.low, r.close, r.volume, r.answered_at)
        for s, keyed in sorted(by_series.items())
        for ts, r in sorted(keyed.items())
    ]


def _kept_rows_bulk(batch) -> list[tuple]:
    return [
        (
            str(batch.symbols[i]),
            int(batch.ts_us[i]),
            float(batch.open[i]),
            float(batch.high[i]),
            float(batch.low[i]),
            float(batch.close[i]),
            None if batch.volume_null[i] else int(batch.volume[i]),
            us_to_datetime(batch.served_us[i]),
        )
        for i in range(len(batch))
    ]


def _assert_parity(rows: list[RawRow]) -> None:
    row_kind, row_value = _outcome(_row_path, rows)
    bulk_kind, bulk_value = _outcome(_bulk, rows)
    assert bulk_kind == row_kind
    if row_kind == "error":
        assert bulk_value == row_value
    else:
        assert _kept_rows_bulk(bulk_value) == _kept_rows_row_path(row_value)
        assert int(bulk_value.n_offered.sum()) == len(rows)


# --- build_raw_batch: the row path's refusals, dedup and order --------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        dict(vendor="synthetic_fill"),
        dict(kind="synthetic_fill"),
        dict(vendor="derived"),
        dict(kind="fallback"),
        dict(kind="5m_grid"),
        dict(vendor="unknown"),
        dict(kind="unknown"),
    ],
)
def test_every_family_refusal_matches_the_row_path_message(bad):
    """Vendor and kind are one per batch: the row path refuses at its first row, so does the
    bulk path."""
    rows = [_row(i=0, **bad), _row("BBB", i=1, **bad)]
    kind, message = _outcome(_bulk, rows)
    assert kind == "error"
    assert (kind, message) == _outcome(_row_path, rows)


@pytest.mark.parametrize(
    "bad",
    [
        dict(timestamp=LATEST + timedelta(microseconds=1)),
        dict(served=LATEST + timedelta(microseconds=1)),
        dict(open=math.nan),
        dict(high=math.inf),
        dict(low=-math.inf),
        dict(close=math.nan),
        dict(volume=-1),
        dict(open=math.nan, volume=-1),  # the first failing check of the row wins
    ],
)
def test_every_row_refusal_matches_the_row_path_message(bad):
    """The first offending row in input order is reported, by its first failing check."""
    rows = [_row(i=0), _row("BBB", i=1, **bad), _row(i=2, close=math.nan)]
    kind, message = _outcome(_bulk, rows)
    assert kind == "error"
    assert (kind, message) == _outcome(_row_path, rows)


def test_the_future_bound_is_inclusive_on_both_paths():
    _assert_parity([_row(timestamp=LATEST), _row(i=1, served=LATEST)])


def test_identical_repeats_collapse_and_the_last_occurrence_wins():
    later = SERVED + timedelta(hours=1)
    rows = [_row(i=0), _row(i=1), _row(i=0, served=later)]
    batch = _bulk(rows)
    assert len(batch) == 2 and batch.n_offered.tolist() == [3]
    assert us_to_datetime(batch.served_us[0]) == later  # the last occurrence's serve time
    _assert_parity(rows)


def test_a_contradicting_repeat_raises_with_the_row_path_count_and_order():
    rows = [
        _row("BBB", i=1),
        _row(i=0),
        _row("BBB", i=1, close=10.5),
        _row(i=0, close=11.0),
        _row(i=0),  # contradicts the 11.0 that precedes it: counted again, as the row path does
        _row(i=3, volume=None),
        _row(i=3, volume=0),  # None and 0 differ
    ]
    kind, message = _outcome(_bulk, rows)
    assert kind == "error" and message.startswith("chunk offers 4 key(s)")
    assert (kind, message) == _outcome(_row_path, rows)


@pytest.mark.parametrize("seed", range(40))
def test_seeded_random_batches_match_the_row_path(seed):
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(int(rng.integers(1, 40))):
        bad = rng.random() < 0.03
        rows.append(
            _row(
                str(rng.choice(["AAA", "BBB", "CCC"])),
                int(rng.integers(0, 6)),
                close=float(rng.choice([10.0, 10.01, -0.0, 0.0])) if not bad else math.nan,
                volume=None if rng.random() < 0.1 else int(rng.integers(0, 2)),
                served=SERVED + timedelta(seconds=int(rng.integers(0, 3))),
            )
        )
    _assert_parity(rows)


def test_an_empty_offer_is_an_empty_batch():
    batch = build_raw_batch(
        timeframe="5m",
        vendor="massive",
        kind="sip_flat_agg",
        symbols=np.empty(0, dtype=object),
        **{c: [] for c in ("ts_us", "open", "high", "low", "close", "volume", "served_us")},
        vendor_codes=VENDORS,
        kind_codes=KINDS,
        future_tolerance_s=3600,
        chunk_rows=10,
    )
    assert (len(batch), batch.n_keys, pack_series_chunks(np.diff(batch.key_bounds()), 5)) == (
        0,
        0,
        [],
    )


def test_series_chunks_cut_each_symbol_in_stamp_order():
    rows = [_row("BBB", i) for i in range(5)] + [_row("AAA", i) for i in (3, 0, 1, 2)]
    batch = _bulk(rows, chunk_rows=2)
    assert batch.symbols.tolist() == ["AAA"] * 4 + ["BBB"] * 5
    assert batch.load_key.tolist() == [0, 0, 1, 1, 2, 2, 3, 3, 4]
    assert batch.n_offered.tolist() == [2, 2, 2, 2, 1]
    sub = batch.keys(1, 3)
    assert (
        sub.load_key.tolist() == [0, 0, 1, 1] and sub.symbols.tolist() == ["AAA"] * 2 + ["BBB"] * 2
    )
    assert sub.n_offered.tolist() == [2, 2]


def test_the_volume_and_stamp_conversions_refuse_what_the_row_path_would_lose():
    with pytest.raises(ValueError, match="nanosecond"):
        bar_load.ns_to_us(np.array([1_000_000_001]))
    with pytest.raises(ValueError, match="non-finite volume"):
        bar_load.whole_volume(np.array([1.0, math.nan]))
    assert bar_load.whole_volume(np.array([1.9, 2.0])).tolist() == [1, 2]  # int(v) truncation


def _frame(n=3, tz="UTC", **extra):
    stamps = pd.date_range(T0.replace(tzinfo=None), periods=n, freq="5min", tz=tz)
    frame = pd.DataFrame(
        {"t": stamps, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": np.arange(n) * 10}
    )
    return frame.assign(**extra)


class _Params:
    vendor_codes = frozenset(VENDORS)
    kind_codes = frozenset(KINDS)

    class write:  # noqa: N801 - mirrors RawContractParams.write
        future_tolerance_s = 3600
        batch_rows = 50_000


def test_frame_to_raw_batch_is_the_columnar_twin_of_frame_to_raw_rows():
    frames = {"BBB": _frame(2), "AAA": _frame(3, answered_at=pd.Timestamp(SERVED))}
    answered = SERVED + timedelta(days=1)
    frames["BBB"]["answered_at"] = pd.Timestamp(answered)
    batch = bar_load.frame_to_raw_batch(
        frames, vendor="massive", timeframe="5m", params=_Params(), kind="sip_flat_agg", now=NOW
    )
    rows = [
        r
        for s, f in frames.items()
        for r in bar_load.frame_to_raw_rows(
            f, s, vendor="massive", timeframe="5m", kind="sip_flat_agg"
        )
    ]
    assert _kept_rows_bulk(batch) == _kept_rows_row_path(_row_path(rows))
    with pytest.raises(ValueError, match="naive"):
        bar_load.frame_to_raw_batch(
            {"AAA": _frame(tz=None)},
            vendor="massive",
            timeframe="5m",
            params=_Params(),
            answered_at=SERVED,
        )
    partial = {"AAA": _frame(answered_at=pd.Timestamp(SERVED)), "BBB": _frame()}
    with pytest.raises(ValueError, match="some rows have no answered_at"):
        bar_load.frame_to_raw_batch(
            partial, vendor="massive", timeframe="5m", params=_Params(), answered_at=SERVED
        )
    with pytest.raises(ValueError, match="answer time"):
        bar_load.frame_to_raw_batch(
            {"AAA": _frame()}, vendor="massive", timeframe="5m", params=_Params()
        )


# --- stage_and_classify and write_classified on a recording cursor ------------------------------


class RecordingCursor:
    def __init__(self, classes=(), replaced=(), rowcounts=None):
        self.classes, self.replaced = list(classes), list(replaced)
        self.rowcounts = rowcounts or {}
        self.calls: list[tuple] = []
        self.rowcount = 0
        self.copied: list[tuple] = []
        self._one = None
        self._all: list = []

    def execute(self, sql, params=None, **kw):
        self.calls.append(("execute", sql, params, kw))
        self._one = (self.classes,) if sql.startswith("SELECT array_agg") else None
        self._all = self.replaced if "WHERE cls = 2" in sql else []
        self.rowcount = next((n for key, n in self.rowcounts.items() if key in sql), 0)

    def executemany(self, sql, seq):
        self.calls.append(("executemany", sql, list(seq), {}))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all

    def copy(self, sql):
        cursor = self

        class _Copy:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def set_types(self, types):
                cursor.calls.append(("set_types", types))

            def write_row(self, row):
                cursor.copied.append(row)

        self.calls.append(("copy", sql))
        return _Copy()

    def sql(self, start: str) -> list[tuple]:
        return [
            c for c in self.calls if c[0] in ("execute", "executemany") and c[1].startswith(start)
        ]


def _two_series():
    return _bulk([_row("BBB", 0), _row("AAA", 0), _row("AAA", 1, volume=None)])


def test_staging_locks_every_series_in_order_then_classifies_unprepared_in_one_join():
    batch = _two_series()
    cur = RecordingCursor(
        classes=[CLS_NEW, CLS_REPLACE, CLS_UNCHANGED], replaced=[(1, 1, 2, 3, 4, 5)]
    )
    classified = stage_and_classify(cur, batch)
    (lock,) = cur.sql("SELECT pg_advisory_xact_lock")
    assert lock[2] == [("AAA|5m|massive|sip_flat_agg",), ("BBB|5m|massive|sip_flat_agg",)]
    (classify_call,) = cur.sql("INSERT INTO ohlcv_raw_stage_class")
    assert classify_call[3] == {"prepare": False}
    assert classify_call[2]["symbols"] == ["AAA", "BBB"]
    assert classify_call[2]["lo"] == T0 and classify_call[2]["hi"] == T0 + timedelta(minutes=5)
    order = [c[1] for c in cur.calls if c[0] in ("execute", "executemany", "copy")]
    first = {
        p: next(i for i, sql in enumerate(order) if sql.startswith(p))
        for p in ("COPY", "SELECT pg_advisory", "INSERT INTO ohlcv_raw_stage_class")
    }
    assert first["COPY"] < first["SELECT pg_advisory"] < first["INSERT INTO ohlcv_raw_stage_class"]
    # the staged row keeps the missing volume as NULL, never 0
    assert [row[8] for row in cur.copied] == [100, None, 100]
    # key 0 is AAA (new, replace), key 1 is BBB (unchanged)
    assert classified.counts.tolist() == [[1, 0, 1, 0], [0, 1, 0, 0]]
    assert classified.replaced_old == {1: (1, 2, 3, 4, 5)}


def test_a_classification_that_lost_rows_is_loud():
    with pytest.raises(RuntimeError, match="classification returned 2 rows for 3"):
        stage_and_classify(RecordingCursor(classes=[0, 0]), _two_series())


def _classified(classes):
    batch = _two_series()
    counts = np.zeros((batch.n_keys, 4), dtype=np.int64)
    np.add.at(counts, (batch.load_key, np.array(classes)), 1)
    return Classified(batch, np.array(classes), {}, counts)


IDS = dict(load_ids=[uuid.uuid4(), uuid.uuid4()], request_ids=[uuid.uuid4(), uuid.uuid4()])


def test_write_classified_logs_old_values_first_and_skips_empty_classes():
    cur = RecordingCursor(
        rowcounts={"INSERT INTO ohlcv_revision": 2, "WHERE c.cls = 0": 1, "WHERE c.cls = 2": 1}
    )
    write_classified(cur, _classified([CLS_NEW, CLS_REPLACE, CLS_SUPERSEDED]), **IDS)
    written = [c[1].split(" (")[0] for c in cur.calls]
    assert written == [
        "INSERT INTO ohlcv_revision",
        "INSERT INTO ohlcv_raw",
        "INSERT INTO ohlcv_raw",
    ]
    assert "ON CONFLICT" not in cur.calls[1][1]
    assert (
        "ohlcv_raw.served_at IS NULL OR EXCLUDED.served_at >= ohlcv_raw.served_at"
        in cur.calls[2][1]
    )
    quiet = RecordingCursor()
    write_classified(quiet, _classified([CLS_UNCHANGED] * 3), **IDS)
    assert quiet.calls == []


@pytest.mark.parametrize(
    "short", ["INSERT INTO ohlcv_revision", "WHERE c.cls = 0", "WHERE c.cls = 2"]
)
def test_a_rowcount_short_of_the_classification_raises(short):
    counts = {"INSERT INTO ohlcv_revision": 2, "WHERE c.cls = 0": 1, "WHERE c.cls = 2": 1}
    counts[short] -= 1
    with pytest.raises(RuntimeError, match="moved under the series lock"):
        write_classified(
            RecordingCursor(rowcounts=counts),
            _classified([CLS_NEW, CLS_REPLACE, CLS_SUPERSEDED]),
            **IDS,
        )


def test_write_classified_needs_one_id_pair_per_series_chunk():
    with pytest.raises(ValueError, match="one per series-chunk"):
        write_classified(
            RecordingCursor(),
            _classified([0, 0, 0]),
            load_ids=[uuid.uuid4()],
            request_ids=[uuid.uuid4()],
        )


# --- the contract's batch entry point ---------------------------------------------------------


@pytest.mark.parametrize("seed", range(20))
def test_a_chunk_without_a_replaced_row_gets_the_detectors_own_answer(seed):
    """The shortcut constant equals `detect` whenever no stored value changed (superseded
    offers are not offered to the detector), under the APR seeds' shape of parameters."""
    rng = np.random.default_rng(seed)
    n = int(rng.integers(1, 60))
    stamps = [T0 + timedelta(minutes=5 * i) for i in range(n)]
    values = {ts: (float(rng.integers(1, 9)),) * 4 + (int(rng.integers(0, 9)),) for ts in stamps}
    stored = {ts: v for ts, v in values.items() if rng.random() < 0.6}
    expected = detect(values, stored, timedelta(minutes=5), DETECTOR)
    assert expected == Restatement(len(stored), 0, 0.0, (), None, None, None)


class FakeConn:
    def __init__(self, ranked: bool):
        self.ranked = ranked
        self.cur = RecordingCursor()
        self.cur.fetchone = lambda: (self.ranked,)

    def cursor(self):
        return self.cur

    def __enter__(self):
        return self


class _ContractParams:
    detector = DETECTOR
    kind_order = {}

    class write:  # noqa: N801
        batch_rows = 50_000


def _patch_writer(monkeypatch, classes):
    def fake_classify(cur, batch):
        cls = np.array(classes[: len(batch)])
        counts = np.zeros((batch.n_keys, 4), dtype=np.int64)
        np.add.at(counts, (batch.load_key, cls), 1)
        return Classified(batch, cls, {}, counts)

    written = []
    monkeypatch.setattr(contract, "stage_and_classify", fake_classify)
    monkeypatch.setattr(contract, "write_classified", lambda cur, c, **ids: written.append(ids))
    selected = []
    monkeypatch.setattr(
        contract,
        "_select",
        lambda conn, spans, params, horizon: selected.append(spans) or (5, 2, 1),
    )
    return written, selected


def test_an_unranked_vendor_defers_selection_and_claims_no_horizon(monkeypatch):
    written, selected = _patch_writer(monkeypatch, [CLS_NEW, CLS_NEW, CLS_UNCHANGED])
    batch = _two_series()
    lineage = {"AAA": {"file": "a"}, "BBB": {"file": "b"}}
    conn = FakeConn(ranked=False)
    result = contract.apply_raw_contract_batch(
        conn, batch, caller="test", params=_ContractParams(), lineage_by_symbol=lineage
    )
    assert selected == []
    assert result.n_selection_deferred == 2 and result.n_unselected == 0
    _assert_policy_read_under_selection_locks(conn.cur)
    (loads,) = conn.cur.sql("INSERT INTO ohlcv_load")
    notes = [json.loads(row[12].removeprefix("lineage: ")) for row in loads[2]]
    assert notes == [
        {"file": "a", "horizon": None, "selection": "deferred_unranked"},
        {"file": "b", "horizon": None, "selection": "deferred_unranked"},
    ]
    # rows in batch order are AAA, AAA, BBB: the load rows carry AAA new 2, BBB unchanged 1
    assert [(r[1], r[7], r[8], r[15]) for r in loads[2]] == [("AAA", 2, 2, 0), ("BBB", 1, 0, 1)]
    assert len(written) == 1 and len(written[0]["load_ids"]) == 2


def test_a_ranked_vendor_selects_each_symbols_span_and_records_the_horizon(monkeypatch):
    _, selected = _patch_writer(monkeypatch, [CLS_NEW] * 3)
    conn = FakeConn(ranked=True)
    result = contract.apply_raw_contract_batch(
        conn,
        _two_series(),
        caller="test",
        params=_ContractParams(),
        lineage_by_symbol={"AAA": {}, "BBB": {}},
    )
    assert (result.selected_slots, result.n_unselected, result.n_excluded) == (5, 2, 1)
    _assert_policy_read_under_selection_locks(conn.cur)
    assert result.n_selection_deferred == 0
    assert selected == [{("AAA", "5m"): (T0, T0 + timedelta(minutes=5)), ("BBB", "5m"): (T0, T0)}]
    (loads,) = conn.cur.sql("INSERT INTO ohlcv_load")
    note = json.loads(loads[2][0][12].removeprefix("lineage: "))
    assert "selection" not in note and datetime.fromisoformat(note["horizon"]).tzinfo


def _assert_policy_read_under_selection_locks(cur) -> None:
    statements = [c[1] for c in cur.calls if c[0] in ("execute", "executemany")]
    locks = [i for i, c in enumerate(cur.calls) if c[0] == "executemany" and "pg_advisory" in c[1]]
    selection = [i for i in locks if cur.calls[i][2][0][0].startswith("bar_selection|")]
    assert len(selection) == 1
    assert [k[0] for k in cur.calls[selection[0]][2]] == [
        "bar_selection|AAA|5m",
        "bar_selection|BBB|5m",
    ]
    ranked = next(i for i, c in enumerate(cur.calls) if c[0] == "execute" and "EXISTS" in c[1])
    assert selection[0] < ranked and statements


def test_the_vendor_ranking_guard_reads_the_policy_view():
    conn = FakeConn(ranked=True)
    assert contract.vendor_is_ranked(conn.cur, "5m", "alpaca")
    (call,) = conn.cur.sql("SELECT EXISTS")
    assert (
        "bar_source_policy_current" in call[1] and "IN (primary_source, fallback_source)" in call[1]
    )
    assert call[2] == ("5m", "alpaca")


def test_the_shortcut_needs_signature_min_bars_of_at_least_one(monkeypatch):
    _patch_writer(monkeypatch, [0, 0, 0])

    class Params(_ContractParams):
        detector = DetectorParams(0.02, 500, 0, 0.0005, 0.5)

    with pytest.raises(ValueError, match="signature_min_bars >= 1"):
        contract.apply_raw_contract_batch(
            FakeConn(False), _two_series(), caller="t", params=Params()
        )


# --- packing, load_batch and the status word ---------------------------------------------------


@pytest.mark.parametrize("seed", range(20))
def test_packing_never_splits_a_series_chunk_nor_exceeds_the_limit(seed):
    rng = np.random.default_rng(seed)
    sizes = rng.integers(1, 30, int(rng.integers(0, 40)))
    groups = pack_series_chunks(sizes, 50)
    assert [k for first, stop in groups for k in range(first, stop)] == list(range(len(sizes)))
    assert all(0 < sizes[first:stop].sum() <= 50 for first, stop in groups)
    with pytest.raises(ValueError, match="exceeds"):
        pack_series_chunks(np.array([10, 51]), 50)


def test_load_batch_commits_one_transaction_per_group_under_the_bar_role(monkeypatch):
    seen = []

    def fake_apply(conn, group, **kw):
        seen.append((len(group), group.n_keys, kw["request_ids"]))
        return contract.IngressResult(
            len(group), len(group), 0, 0, 0, n_selection_deferred=group.n_keys
        )

    monkeypatch.setattr(bar_load, "apply_raw_contract_batch", fake_apply)

    class Conn:
        class info:  # noqa: N801
            import psycopg

            transaction_status = psycopg.pq.TransactionStatus.IDLE

        def __init__(self):
            self.cur = RecordingCursor()
            self.transactions = 0

        def transaction(self):
            self.transactions += 1
            return self

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return self.cur

    batch = _bulk([_row(s, i) for s in ("AAA", "BBB", "CCC") for i in range(3)], chunk_rows=2)
    conn = Conn()
    result = bar_load.load_batch(
        conn, batch, caller="t", params=_Params(), max_rows=4, request_ids=list("abcdef")
    )
    # keys of 2 and 1 rows per symbol; a third key would pass 4 rows, so each group is a symbol
    assert seen == [(3, 2, list("ab")), (3, 2, list("cd")), (3, 2, list("ef"))]
    assert conn.transactions == 3
    assert [c[1] for c in conn.cur.calls] == ["SET LOCAL ROLE bar_derivation_writer"] * 3
    assert result.n_offered == 9 and result.n_selection_deferred == batch.n_keys


def test_a_deferred_load_is_raw_only_never_applied():
    assert load_status(apply=True, selection_deferred=3).startswith("RAW-ONLY")
    assert load_status(apply=True) == "APPLIED"
    both = load_status(apply=True, basis_flagged=1, selection_deferred=3)
    assert both.startswith("PARTIAL") and "RAW-ONLY" in both
    assert load_status(apply=True, unselected=1, selection_deferred=3).startswith("UNSELECTED")
    total = LoadResult().plus(contract.IngressResult(1, 1, 0, 0, 0, n_selection_deferred=2))
    assert total.n_selection_deferred == 2


def test_a_row_without_a_symbol_is_refused_not_filed_under_another():
    rows = [_row("AAA", 0), _row("BBB", 1)]
    with pytest.raises(ValueError, match="symbol missing on 1"):
        build_raw_batch(
            timeframe="5m",
            vendor="massive",
            kind="sip_flat_agg",
            symbols=np.array(["AAA", None], dtype=object),
            ts_us=[datetime_to_us(r.timestamp) for r in rows],
            open=[1.0, 1.0],
            high=[1.0, 1.0],
            low=[1.0, 1.0],
            close=[1.0, 1.0],
            volume=[1, 1],
            served_us=[datetime_to_us(SERVED)] * 2,
            vendor_codes=VENDORS,
            kind_codes=KINDS,
            future_tolerance_s=3600,
            chunk_rows=10,
            now=NOW,
        )
