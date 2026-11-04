"""S0 feature and kernel members on source timeframes (plan 184-08), on a fake pool."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import numpy as np
import pytest

from src.intelligence.features.contract.registry import default_registry, feature_memory_bars
from src.intelligence.research import align, clock, snapshot, store
from src.intelligence.research import panel as panel_mod
from src.intelligence.research.snapshot import MemberSourceRequest, SourceRequest
from tests.unit.research.test_feature_inputs import SNAP, SNAP_HASH, _batch, _real_config
from tests.unit.research.test_snapshot_mtf import OOS, SYMS, FakePool, _rows

REG = default_registry()
COL = "bar_close_pos"  # applicable on every tf, memory 0
WARM_COL = "ret_lag_2"  # memory 3
KERNEL = "rk_price_percentile_w3"
WINDOWS = {"rk_price_percentile": 3}
FAR = (datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))
START, END = "2024-11-21", "2024-12-06"


def fv(ts, sym: str, k: int = 0) -> float:
    minutes = (
        int(np.datetime64(ts, "m").astype(np.int64))
        if not isinstance(ts, datetime)
        else int(ts.timestamp() // 60)
    )
    return float(minutes % 1000) / 10 + 100 * SYMS.index(sym) + k


class FeaturePool(FakePool):
    def __init__(self, tf, *, chunk=100, batches=None, null_at=None):
        super().__init__(tf)
        self.chunk, self.null_at = chunk, null_at
        self.batches = [_batch(start=FAR[0], end=FAR[1])] if batches is None else batches

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        if "snapshot_feature_chunk_symbols" in sql:
            return self.chunk
        return OOS

    async def fetch(self, sql, *args):
        if sql.startswith("SELECT timestamp, open"):
            sym, tf, lo, hi = args
            self.calls.append((sql, args))
            off = 10.0 * SYMS.index(sym)
            return [
                (r[0], r[1] + off, r[2] + off, *r[3:])
                for r in _rows(tf, ", high, low" in sql)
                if lo <= r[0] < hi
            ]
        if sql.startswith("SELECT timestamp, close"):
            self.calls.append((sql, args))
            sym, tf, lo, hi = args
            off = 10.0 * SYMS.index(sym)
            return [(r[0], r[2] + off) for r in _rows(tf, False) if lo <= r[0] < hi]
        if sql.startswith("SELECT batch_key"):
            self.calls.append((sql, args))
            return self.batches
        if sql.startswith("SELECT symbol, bar_ts"):
            self.calls.append((sql, args))
            tf, symbols, lo, hi = args
            ncol = sql.split(" FROM ")[0].count('"') // 2
            out = []
            for i, r in enumerate(x for x in _rows(tf, False) if lo <= x[0] < hi):
                for sym in sorted(symbols):
                    cells = [
                        None if self.null_at == (sym, i) else fv(r[0], sym, k) for k in range(ncol)
                    ]
                    out.append((sym, r[0], *cells))
            return out
        return await super().fetch(sql, *args)


@pytest.fixture
def build(monkeypatch, tmp_path):
    def run(tf, sources, *, pool=None, start=START, end=END, **kw):
        pool = pool or FeaturePool(tf)

        async def fake_pool(dsn):
            return pool

        async def fake_label_inputs(conn, **_):
            return None

        monkeypatch.setattr(snapshot, "read_only_pool", fake_pool)
        monkeypatch.setattr(snapshot, "load_label_inputs", fake_label_inputs)
        monkeypatch.setattr(snapshot.data_quality, "snapshot_manifest", lambda *a, **k: {})
        out = tmp_path / f"{tf}_{len(list(tmp_path.iterdir()))}"
        path = asyncio.run(
            snapshot.build_panel(
                "dsn",
                out,
                symbols=SYMS,
                tf=tf,
                start=start,
                end_exclusive=end,
                sources=sources,
                **kw,
            )
        )
        return path, pool

    return run


def feature_member(name="f", column=COL, floor=None, max_age=1):
    return MemberSourceRequest(name, "feature", column, None, max_age, None, floor)


def kernel_member(name="k", floor=None, max_age=1):
    return MemberSourceRequest(name, "kernel", KERNEL, WINDOWS, max_age, 0, floor)


def req(tf, *members, high_low=False, pin=SNAP_HASH):
    return SourceRequest(tf, pin, tuple(members), high_low)


def queries(pool, prefix):
    return [c for c in pool.calls if c[0].startswith(prefix)]


# --- columns (amendment) ----------------------------------------------------------------------


def test_unknown_column_refused_before_any_sql(build):
    pool = FeaturePool("1d")
    with pytest.raises(ValueError, match="B1e"):
        build("1d", [req("1d", feature_member(column="no_such_column"))], pool=pool)
    assert pool.calls == []


def test_not_applicable_column_refused_at_load(build):
    na = next(c for c in REG.feature_columns() if c in REG.not_applicable_outputs("1d"))
    pool = FeaturePool("1d")
    with pytest.raises(ValueError, match="B1e"):
        build("1d", [req("1d", feature_member(column=na))], pool=pool)
    assert pool.calls == []


# --- config -----------------------------------------------------------------------------------


def _configs(monkeypatch, sources, batches=None, tf="1d"):
    pool = FeaturePool(tf, batches=batches)

    async def fake_pool(dsn):
        return pool

    monkeypatch.setattr(snapshot, "read_only_pool", fake_pool)
    out = asyncio.run(snapshot.source_configs("dsn", sources, START, END, symbols=SYMS))
    return out, pool


def test_config_equals_projection_and_sends_no_bar_query(monkeypatch):
    out, pool = _configs(monkeypatch, [req("1d", feature_member()), req("1h", kernel_member())])
    assert set(out) == {"1d", "1h"}
    assert out["1d"]["config"] == _real_config()
    assert out["1d"]["block"]["projection_hash"] == SNAP_HASH
    assert not queries(pool, "SELECT timestamp") and not queries(pool, "SELECT symbol, bar_ts")


def test_config_hash_mismatch_refused_b1f(monkeypatch):
    with pytest.raises(ValueError, match="B1f"):
        _configs(monkeypatch, [req("1d", feature_member(), pin="0" * 64)])


def test_config_batches_disagreeing_refused_b1f(monkeypatch):
    other = {**SNAP, "momentum_window_fast": SNAP["momentum_window_fast"] + 1}
    batches = [
        _batch("b1", start=FAR[0], end=datetime(2024, 12, 1, tzinfo=UTC)),
        _batch("b2", start=datetime(2024, 12, 1, tzinfo=UTC), end=FAR[1], snapshot=other),
    ]
    with pytest.raises(ValueError, match="B1f"):
        _configs(monkeypatch, [req("1d", feature_member())], batches=batches)


def test_provenance_missing_and_mixed_code_keys_refused_before_feature_rows(build):
    for batches in (
        [],
        [_batch("b1", code_key="a" * 40), _batch("b2", code_key="b" * 40)],
    ):
        pool = FeaturePool("1d", batches=batches)
        with pytest.raises(ValueError, match="B1f"):
            build("1d", [req("1d", feature_member())], pool=pool)
        assert not queries(pool, "SELECT symbol, bar_ts") and not queries(pool, "SELECT timestamp")


def test_hmm_without_rebuild_batches_refused_b1j(build):
    regime = next(c for c in REG.applicable_outputs("1d") if REG.by_output(c).origin == "regime")
    batches = [_batch(writer="other-writer", target_table="feature_vectors")]
    with pytest.raises(ValueError, match="B1j"):
        build(
            "1d",
            [req("1d", feature_member(column=regime))],
            pool=FeaturePool("1d", batches=batches),
        )


def test_coverage_below_floor_refused_b1h(build):
    with pytest.raises(ValueError, match="B1h"):
        build("1d", [req("1d", feature_member(floor=1.5))])


def test_path_dependent_column_refused_b1g(build):
    path_dep = next(
        c
        for c in REG.applicable_outputs("1d")
        if REG.is_path_dependent(c) and REG.by_output(c).origin != "regime"
    )
    with pytest.raises(ValueError, match="B1g"):
        build("1d", [req("1d", feature_member(column=path_dep))])


# --- equal and coarser sources ------------------------------------------------------------------


def test_equal_tf_feature_in_book_dir_with_warmup_mask(build):
    path, _ = build("1d", [req("1d", feature_member(column=WARM_COL))])
    arr = store.read_array(path, f"feature__1d__{WARM_COL}")
    memory = feature_memory_bars(WARM_COL, _real_config(), REG)
    assert memory > 0 and arr.dtype == np.float32
    assert np.isnan(arr[:memory]).all() and np.isfinite(arr[memory:]).all()
    info = store.read_meta(path)["manifest"]["sources"]["1d"]
    assert info["config_hash"] == SNAP_HASH and info["relation"] == "equal"
    assert info["columns"][WARM_COL]["warmup"]["masked_rows"] == memory * len(SYMS)


def test_null_cell_stays_nan_never_zero(build):
    path, _ = build("1d", [req("1d", feature_member())], pool=FeaturePool("1d", null_at=("BBB", 3)))
    arr = store.read_array(path, f"feature__1d__{COL}")
    assert np.isnan(arr[3, 1]) and np.isfinite(arr[3, 0])
    assert not (arr == 0).any()


def test_coarser_source_in_child_dir_verified(build):
    path, _ = build("1h", [req("1d", feature_member())], start="2024-11-22", end="2024-12-04")
    info = store.read_meta(path)["manifest"]["sources"]["1d"]
    assert info["relation"] == "coarser" and info["sha256"] == store.verify(
        path.parent / info["dir"]
    )
    child = panel_mod.load(path.parent / info["dir"])
    assert child.tf == "1d" and child.closes_at is not None
    assert store.has_array(path.parent / info["dir"], f"feature__1d__{COL}")
    assert snapshot.verify_sources(path) == {"1d": path.parent / info["dir"]}
    victim = path.parent / info["dir"] / f"feature__1d__{COL}.npy"
    data = bytearray(victim.read_bytes())
    data[-1] ^= 0xFF
    victim.write_bytes(bytes(data))
    with pytest.raises(ValueError):
        snapshot.verify_sources(path)


def test_no_sources_is_byte_identical(build):
    a, _ = build("1d", None)
    b, _ = build("1d", ())
    assert a.name == b.name


# --- finer sources ------------------------------------------------------------------------------


def _finer(build, chunk=100, **kw):
    members = (feature_member("f", max_age=7), kernel_member("k", max_age=7))
    pool = FeaturePool("1d", chunk=chunk)
    path, pool = build(
        "1d", [req("1h", *members, high_low=True)], pool=pool, fields=("closes_at",), **kw
    )
    return path, pool


def _source_full(path):
    """The full 1h feature array the fake served, rebuilt from the stored source grid."""
    ts = store.read_array(path, "src_ts__1h")
    out = np.full((len(ts), len(SYMS)), np.nan, dtype=np.float32)
    served = {
        np.datetime64(t.replace(tzinfo=None), "ns") for t in (r[0] for r in _rows("1h", False))
    }
    for i, t in enumerate(np.asarray(ts).astype("datetime64[ns]")):
        if t in served:
            for j, s in enumerate(SYMS):
                out[i, j] = fv(t.astype("datetime64[m]"), s)
    return out


def test_finer_index_replays_the_full_alignment(build):
    path, _ = _finer(build)
    book = panel_mod.load(path)
    src_ts = store.read_array(path, "src_ts__1h")
    src_valid = store.read_array(path, "src_valid__1h")
    src_closes = clock.closes_at(src_ts, src_valid, "1h", 7)
    full = _source_full(path)
    expected = align.align_index(np.isfinite(full), src_closes, book.closes_at, 7)
    idx = store.read_array(path, "idx__f")
    assert idx.dtype == np.int32 and np.array_equal(idx, expected) and (idx >= 0).any()
    assert (store.read_array(path, "idx__k") >= 0).any()  # the kernel member has an index too
    rows = store.read_array(path, "ref_rows__f")
    values = store.read_array(path, "ref_values__f")
    assert values.dtype == np.float32 and np.array_equal(rows, np.unique(idx[idx >= 0]))
    pos = np.searchsorted(rows, idx)
    replay = np.where(
        idx >= 0, values[np.clip(pos, 0, len(rows) - 1), np.arange(len(SYMS))], np.nan
    )
    assert np.array_equal(replay, align.gather(full, idx), equal_nan=True)
    names = {p.stem for p in path.glob("*.npy")}
    assert not any(n.startswith(("aligned", "values__")) for n in names)


def test_source_grid_persisted_and_no_availability_stored(build):
    path, _ = _finer(build)
    names = {p.stem for p in path.glob("*.npy")}
    assert {"src_ts__1h", "src_valid__1h"} <= names
    assert not any("avail" in n for n in names)
    ts = store.read_array(path, "src_ts__1h")
    valid = store.read_array(path, "src_valid__1h")
    assert len(ts) == len(valid) and ts.dtype.kind == "M"


def test_kernel_probe_bars_hold_first_symbols_raw_ohlcv(build):
    path, _ = _finer(build)
    probe = store.read_array(path, "probe_bars__1h")
    assert probe.shape == (len(store.read_array(path, "src_ts__1h")), len(SYMS), 5)
    close = probe[:, 0, 3]
    assert np.isfinite(close).sum() == len(_rows("1h", False))
    assert np.isfinite(probe[:, 0, 1]).any() and np.isfinite(probe[:, 0, 2]).any()
    assert store.read_meta(path)["manifest"]["sources"]["1h"]["probe_symbols"] == list(SYMS)


def test_chunking_changes_no_value_and_issues_more_queries(build):
    one, pool_one = _finer(build, chunk=100)
    many, pool_many = _finer(build, chunk=1)
    assert len(queries(pool_one, "SELECT symbol, bar_ts")) == 1
    assert len(queries(pool_many, "SELECT symbol, bar_ts")) == len(SYMS)
    assert {p.stem for p in one.glob("*.npy")} == {p.stem for p in many.glob("*.npy")}
    for p in one.glob("*.npy"):
        assert np.array_equal(
            store.read_array(one, p.stem), store.read_array(many, p.stem), equal_nan=True
        ), p.stem
    a = store.read_meta(one)["manifest"]["sources"]["1h"]["columns"]
    b = store.read_meta(many)["manifest"]["sources"]["1h"]["columns"]
    assert a == b


def test_every_source_array_is_in_the_book_hash(build):
    path, _ = _finer(build)
    assert store.verify(path)
    victim = path / "idx__f.npy"
    data = bytearray(victim.read_bytes())
    data[-1] ^= 0x01
    victim.write_bytes(bytes(data))
    with pytest.raises(ValueError):
        store.verify(path)
