"""S0's dividend capture with Massive as a coverage source (todo 651): what it reads, what the
manifest records, and that the hash follows the Massive facts while a Yahoo-only name's arrays
stay as they were."""

from __future__ import annotations

import asyncio
from datetime import date

import numpy as np

from src.intelligence.research import dividends, snapshot, store
from tests.unit.research.test_snapshot_mtf import SYMS, FakePool

RULE_ROWS = [
    ("threshold.dividend_event.source_yield_rel_tolerance", "0.1"),
    ("threshold.dividend_event.noise_margin", "1.25"),
]
CAPTURE = "massive/dividends/20261110.jsonl"


class DividendPool(FakePool):
    """AAA is Yahoo-covered with one reconciled event; BBB has only a Massive claim with a gap."""

    def __init__(self, massive_yield: float | None):
        super().__init__("1d")
        self.massive_yield = massive_yield

    async def fetch(self, sql, *args):
        if sql is snapshot._DISPUTE_RULE_SQL:
            return RULE_ROWS
        if sql is snapshot._DIV_COVERAGE_SQL:
            assert args[1] == ["yahoo", "massive"]
            rows = [
                {
                    "symbol": "AAA",
                    "source": "yahoo",
                    "covered_from": date(2024, 1, 1),
                    "covered_to": date(2024, 12, 31),
                    "reference_capture": None,
                    "rule_id": None,
                }
            ]
            if self.massive_yield is not None:
                rows.append(
                    {
                        "symbol": "BBB",
                        "source": "massive",
                        "covered_from": date(2024, 11, 21),
                        "covered_to": date(2024, 12, 5),
                        "reference_capture": CAPTURE,
                        "rule_id": "massive-dividend-coverage-v1",
                    }
                )
            return rows
        if sql is snapshot._DIV_GAPS_SQL:
            if self.massive_yield is None:
                return []
            return [
                {
                    "symbol": "BBB",
                    "source": "massive",
                    "gap_from": date(2024, 11, 27),
                    "gap_to": date(2024, 11, 27),
                }
            ]
        if sql is snapshot._DIV_EVENTS_SQL:
            return [
                {
                    "symbol": "AAA",
                    "ex_date": date(2024, 11, 25),
                    "yahoo_yield": 0.01,
                    "ibkr_yield": 0.01,
                    "ibkr_prev_close": 100.0,
                }
            ]
        if sql is snapshot._MASSIVE_EVENTS_SQL:
            if self.massive_yield is None:
                return []
            return [
                {
                    "symbol": "BBB",
                    "ex_date": date(2024, 12, 2),
                    "dividend_yield": self.massive_yield,
                    "declared_on": date(2024, 11, 1),
                }
            ]
        return await super().fetch(sql, *args)


def _build(monkeypatch, tmp_path, massive_yield):
    pool = DividendPool(massive_yield)

    async def fake_pool(dsn):
        return pool

    async def fake_label_inputs(conn, **_):
        return None

    monkeypatch.setattr(snapshot, "read_only_pool", fake_pool)
    monkeypatch.setattr(snapshot, "load_label_inputs", fake_label_inputs)
    monkeypatch.setattr(snapshot.data_quality, "snapshot_manifest", lambda *a, **k: {})
    out = tmp_path / f"d_{len(list(tmp_path.iterdir()))}"
    return asyncio.run(
        snapshot.build_panel(
            "dsn",
            out,
            symbols=SYMS,
            tf="1d",
            start="2024-11-21",
            end_exclusive="2024-12-06",
            dividends=True,
        )
    )


def test_the_manifest_records_the_source_set_and_the_massive_lineage(monkeypatch, tmp_path):
    path = _build(monkeypatch, tmp_path, 0.02)
    block = store.read_meta(path)["manifest"]["dividends"]
    assert block["coverage_sources"] == ["yahoo", "massive"]
    assert block["massive"] == {
        "source": "dividend_events",
        "symbols_covered": 1,
        "gaps": 1,
        "events": 1,
        "coverage_rules": ["massive-dividend-coverage-v1"],
        "captures": [CAPTURE],
    }
    grid = dividends.load_grid(path)
    bbb = grid.symbols.index("BBB")
    days = [str(d) for d in snapshot.session_dates(snapshot.panel_mod.load(path))]
    covered = [days[k] for k in np.flatnonzero(grid.div_covered[:, bbb])]
    assert "2024-11-27" not in covered and covered[0] == "2024-11-21"
    assert grid.div_yield[days.index("2024-12-02"), bbb] == 0.02


def test_the_hash_follows_the_massive_facts_and_a_yahoo_name_is_unchanged(monkeypatch, tmp_path):
    none, low, high = (_build(monkeypatch, tmp_path, y) for y in (None, 0.02, 0.03))
    assert len({none.name, low.name, high.name}) == 3
    grids = [dividends.load_grid(p) for p in (none, low, high)]
    aaa = grids[0].symbols.index("AAA")
    for name, a in grids[0].arrays().items():
        for other in grids[1:]:
            assert a[:, aaa].tobytes() == other.arrays()[name][:, aaa].tobytes(), name
    assert not grids[0].div_covered[:, grids[0].symbols.index("BBB")].any()
