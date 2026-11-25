"""S0 proves the volume basis a volume kernel member reads (todo 588 item e): one basis over the
source bars' (vendor, kind) pairs, never a constant, never mixed."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from src.intelligence.bars import vendor_kind
from src.intelligence.research import snapshot
from src.intelligence.research.panel import Panel
from src.intelligence.research.snapshot import MemberSourceRequest, SourceRequest

ALPACA = ("alpaca", "sip_rth")
MASSIVE = ("massive", vendor_kind.KIND_MASSIVE_CANONICAL)
IBKR = ("ibkr", "smart_trades")
VWAP = MemberSourceRequest("vw", "kernel", "rk_vwap_dev_w20", {"rk_vwap_dev": 20}, 1, 0, None)
HIGH = MemberSourceRequest("hd", "kernel", "rk_high_dist_w126", {"rk_high_dist": 126}, 1, 0, None)
STORED = MemberSourceRequest("st", "feature", "momentum_z_fast", None, 1, None, None)


def _req(*members, tf="1d"):
    return SourceRequest(tf, "h", tuple(members), True)


def test_one_basis_across_vendors_that_agree():
    assert (
        snapshot.volume_basis_of([ALPACA, MASSIVE, ALPACA]) == vendor_kind.VOLUME_BASIS_CONSOLIDATED
    )
    assert snapshot.volume_basis_of([IBKR]) == vendor_kind.VOLUME_BASIS_SMART


def test_a_pair_with_no_volume_carries_no_basis():
    pairs = [ALPACA, ("ibkr", "venue")]
    assert snapshot.volume_basis_of(pairs) == vendor_kind.VOLUME_BASIS_CONSOLIDATED


@pytest.mark.parametrize(
    "pairs, message",
    [
        ([ALPACA, IBKR], "give \\[1, 2\\]"),  # a seam: two bases
        ([], "none"),  # no bars, nothing proves a basis
        ([("ibkr", "venue")], "none"),  # only bars with no volume
    ],
)
def test_mixed_or_absent_basis_refuses(pairs, message):
    with pytest.raises(ValueError, match=message):
        snapshot.volume_basis_of(pairs)


def test_an_unmapped_pair_raises_never_defaults():
    with pytest.raises(ValueError, match="no volume basis"):
        snapshot.volume_basis_of([("nobody", "nothing")])


def test_only_volume_kernels_need_a_basis():
    assert snapshot._needs_volume_basis(_req(VWAP), None)
    assert not snapshot._needs_volume_basis(_req(HIGH), None)
    assert not snapshot._needs_volume_basis(_req(STORED), None)


class FakePool:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def fetch(self, sql, *args):
        self.calls.append(args)
        return [{"vendor": v, "kind": k} for v, k in self.rows]


def _ctx(pool, n_symbols=5, chunk=2):
    return SimpleNamespace(
        pool=pool,
        book=SimpleNamespace(symbols=tuple(f"s{i}" for i in range(n_symbols))),
        scored_lo=datetime(2020, 1, 1, tzinfo=UTC),
        hi=datetime(2021, 1, 1, tzinfo=UTC),
        warmup_sessions=300,
        chunk=chunk,
    )


def _prove(pool, req, **kw):
    return asyncio.run(snapshot._source_volume_basis(_ctx(pool, **kw), req, None))


def test_the_basis_is_read_per_symbol_chunk_and_recorded():
    pool = FakePool([ALPACA, MASSIVE])
    basis, evidence = _prove(pool, _req(VWAP))
    assert basis == vendor_kind.VOLUME_BASIS_CONSOLIDATED
    assert evidence == {
        "basis": 1,
        "bar_tf": "1d",
        "vendor_kinds": (
            [list(ALPACA), list(MASSIVE)] if ALPACA < MASSIVE else [list(MASSIVE), list(ALPACA)]
        ),
    }
    assert [len(c[1]) for c in pool.calls] == [2, 2, 1]  # 5 symbols in chunks of 2
    assert all(c[0] == "1d" for c in pool.calls)


def test_a_derived_intraday_source_reads_its_5m_constituents():
    pool = FakePool([ALPACA])
    _basis, evidence = _prove(pool, _req(VWAP, tf="1h"))
    assert evidence["bar_tf"] == "5m" and all(c[0] == "5m" for c in pool.calls)


def test_no_volume_kernel_reads_nothing_and_adds_no_evidence():
    pool = FakePool([ALPACA])
    assert _prove(pool, _req(HIGH, STORED)) is None
    assert pool.calls == []


def test_a_mixed_source_refuses_naming_the_tf():
    with pytest.raises(ValueError, match="1d source refused.*one volume basis"):
        _prove(FakePool([ALPACA, IBKR]), _req(VWAP))


def _grid(n=120, m=2, seed=3):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, (n, m)), axis=0))
    spread = np.abs(rng.normal(0.0, 0.4, (n, m)))
    return Panel(
        tf="1d",
        symbols=("a", "b"),
        timestamps=np.datetime64("2020-01-01") + np.arange(n).astype("timedelta64[D]"),
        bars_per_session=1,
        valid=np.ones(n, dtype=bool),
        open=close * 0.999,
        close=close,
        volume=rng.integers(1, 5_000, (n, m)).astype(float),
        high=close + spread,
        low=close - spread,
    )


def test_the_kernel_runs_with_the_proven_basis_and_is_refused_without_it():
    grid = _grid()
    out = snapshot._run_kernel(grid, VWAP, None, True, vendor_kind.VOLUME_BASIS_CONSOLIDATED)
    assert np.isfinite(out.values["rk_vwap_dev_w20"][25:]).all()
    with pytest.raises(ValueError, match="volume_basis"):
        snapshot._run_kernel(grid, VWAP, None, True)


def test_a_kernel_that_does_not_read_volume_is_unchanged_by_a_basis_argument():
    grid = _grid(n=300)
    config = SimpleNamespace(high_52w_window=252)
    plain = snapshot._run_kernel(grid, HIGH, config, False)
    with_basis = snapshot._run_kernel(
        grid, HIGH, config, False, vendor_kind.VOLUME_BASIS_CONSOLIDATED
    )
    assert np.array_equal(
        plain.values["rk_high_dist_w126"], with_basis.values["rk_high_dist_w126"], equal_nan=True
    )
