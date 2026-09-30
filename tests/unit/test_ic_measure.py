"""Unit tests of services/ic_measure.py, the fresh IC writer (phase 186 plan 14, D-17, D-20, D-23).

Fakes stand in for psycopg connections; the pure measure jobs run for real on a tiny panel so
the orchestration is exercised end to end without a database.

CI-clean: no DB, no network.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

import services.ic_measure as ic_measure
from services._batch_utils import BulkLoadResult
from src.intelligence.measure import ic as measure_ic
from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.term_structure import TermStructure
from src.intelligence.research.panel import Panel
from tests.unit._responder_fakes import FakeConn, rows_responder

_REPO = Path(__file__).resolve().parents[2]
_OOS = datetime(2026, 3, 1, tzinfo=UTC)

# ---------------------------------------------------------------------------
# A fake APR holding exactly the mapped keys
# ---------------------------------------------------------------------------

_VALUES: dict[str, Any] = {
    "alpha.ic.subsample_min_stride": 5,
    "alpha.ic.bootstrap_block_size.1d": 10,
    "alpha.ic.bootstrap_resamples": 2000,
    "alpha.ic.bootstrap_seed": 42,
    "alpha.ic.fdr_alpha": 0.05,
    "alpha.ic.min_reliable_n": 100,
    "infra.ic_measure.symbol_chunk_size": 50,
    "infra.ic_measure.bootstrap_threads": 2,
    "infra.ic_measure.bootstrap_chunk_resamples": 250,
    "alpha.ic_measure.monitor_window_sessions": 63,
    "alpha.ic.hac_max_lag": 3,
    "alpha.ic_measure.degenerate_std": 1e-8,
    "alpha.ic_measure.monitor_degenerate_std": 1e-10,
}


class TestLoadParams:
    def test_load_params_maps_every_measure_param_field_to_its_apr_key(self) -> None:
        keys = ic_measure.param_keys("1d")
        assert set(keys) == {f.name for f in dataclasses.fields(MeasureParams)}
        apr = {keys[name]: _VALUES[keys[name]] for name in keys}  # only the mapped keys
        params = ic_measure.load_params(apr, "1d")
        for field in dataclasses.fields(MeasureParams):
            assert getattr(params, field.name) == _VALUES[keys[field.name]]

    def test_bootstrap_block_size_is_per_tf(self) -> None:
        apr = {k: v for k, v in _VALUES.items()}
        apr["alpha.ic.bootstrap_block_size.15m"] = 26
        assert ic_measure.load_params(apr, "15m").bootstrap_block_size == 26

    def test_a_missing_key_raises_instead_of_defaulting(self) -> None:
        keys = ic_measure.param_keys("1d")
        for name, key in keys.items():
            apr = {k: v for k, v in _VALUES.items() if k != key}
            with pytest.raises(KeyError, match=re.escape(key)):
                ic_measure.load_params(apr, "1d")

    def test_source_never_reads_the_retired_lookahead_keys(self) -> None:
        source = (_REPO / "services" / "ic_measure.py").read_text()
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        assert "alpha.ic.lookahead" not in code

    def test_seeded_apr_keys_match_load_params(self) -> None:
        migration = "\n".join(
            (_REPO / "production" / "migrations" / name).read_text()
            for name in ("414_ic_measure_apr.sql", "417_ic_measure_bootstrap_apr.sql")
        )
        seeded = set(re.findall(r"^\s*\('([a-z_.0-9]+)', '", migration, flags=re.M))
        read = set(ic_measure.param_keys("1d").values()) | {ic_measure.HORIZONS_KEY}
        must_be_seeded = {k for k in read if "ic_measure" in k}
        assert must_be_seeded <= seeded
        # every other key read exists live already (verified in the plan 14 summary)
        assert {k for k in read if "ic_measure" not in k} == {
            "alpha.ic.subsample_min_stride",
            "alpha.ic.bootstrap_block_size.1d",
            "alpha.ic.bootstrap_resamples",
            "alpha.ic.bootstrap_seed",
            "alpha.ic.fdr_alpha",
            "alpha.ic.min_reliable_n",
            "alpha.ic.hac_max_lag",
        }


class TestOperationalVersusComputational:
    """ic_engine's split (services/ic_engine.py _COMPUTATIONAL_CONFIG_FIELDS and
    _OPERATIONAL_CONFIG_FIELDS): operational keys never enter the identity."""

    _OOS_DT = datetime(2025, 12, 24, 5, 15, tzinfo=UTC)
    _HORIZONS = (1, 2, 5)

    def _apr(self) -> dict[str, Any]:
        apr = dict(_VALUES)
        apr.update(
            {
                "alpha.ic.feature_block_columns": 32,
                "infra.ic_measure.fetch_chunk_rows": 200000,
                "alpha.ic_measure.horizons": {"1d": [1, 2, 5], "15m": [2]},
            }
        )
        return apr

    def test_every_measure_param_field_is_classified_exactly_once(self) -> None:
        from src.intelligence.measure.params import COMPUTATIONAL, OPERATIONAL, fields_of_kind

        names = {f.name for f in dataclasses.fields(MeasureParams)}
        computational = set(fields_of_kind(COMPUTATIONAL))
        operational = set(fields_of_kind(OPERATIONAL))
        assert computational | operational == names
        assert not computational & operational
        assert operational == {
            "symbol_chunk_size",
            "bootstrap_threads",
            "bootstrap_chunk_resamples",
        }

    def test_an_unclassified_field_cannot_be_constructed(self) -> None:
        @dataclasses.dataclass(frozen=True)
        class Half(MeasureParams):
            extra: int = 3

        with pytest.raises(TypeError, match="extra is not classified"):
            Half(**dataclasses.asdict(_params()), extra=3)

    def test_param_types_come_from_the_dataclass_not_a_hand_kept_list(self) -> None:
        params = ic_measure.load_params(self._apr(), "1d")
        for field in dataclasses.fields(MeasureParams):
            assert type(getattr(params, field.name)) is ic_measure.field_type(field.name)
        assert "_INT_FIELDS" not in (_REPO / "services" / "ic_measure.py").read_text()

    def test_operational_keys_are_read_but_never_in_the_identity(self) -> None:
        snapshot = ic_measure.identity_snapshot(self._apr(), "1d", self._HORIZONS, self._OOS_DT)
        read = set(ic_measure.apr_keys_read("1d"))
        for key in ic_measure.operational_keys("1d"):
            assert key in read
            assert key not in snapshot
        assert ic_measure.param_keys("1d")["symbol_chunk_size"] in ic_measure.operational_keys("1d")
        assert "alpha.ic.feature_block_columns" in ic_measure.operational_keys("1d")
        assert "infra.ic_measure.fetch_chunk_rows" in ic_measure.operational_keys("1d")

    def test_changing_an_operational_key_leaves_the_identity_unchanged(self) -> None:
        base = ic_measure.identity_snapshot(self._apr(), "1d", self._HORIZONS, self._OOS_DT)
        for key in ic_measure.operational_keys("1d"):
            apr = self._apr()
            apr[key] = 7
            assert (
                ic_measure.identity_snapshot(apr, "1d", self._HORIZONS, self._OOS_DT) == base
            ), key

    def test_changing_a_computational_key_changes_the_identity(self) -> None:
        base = ic_measure.identity_snapshot(self._apr(), "1d", self._HORIZONS, self._OOS_DT)
        for key in ic_measure.computational_keys("1d"):
            apr = self._apr()
            apr[key] = apr[key] + 1
            changed = ic_measure.identity_snapshot(apr, "1d", self._HORIZONS, self._OOS_DT)
            assert changed != base, key

    def test_another_tfs_horizons_do_not_re_key_this_tf(self) -> None:
        base = ic_measure.identity_snapshot(self._apr(), "1d", self._HORIZONS, self._OOS_DT)
        apr = self._apr()
        apr["alpha.ic_measure.horizons"] = {"1d": [1, 2, 5], "15m": [2, 9]}
        assert ic_measure.identity_snapshot(apr, "1d", self._HORIZONS, self._OOS_DT) == base
        assert ic_measure.identity_snapshot(apr, "1d", (1, 2), self._OOS_DT) != base


class TestHorizons:
    _APR = {
        "alpha.ic_measure.horizons": {"1d": [1, 2], "15m": [2, 26], "1h": [1]},
        "alpha.ic.broadcast_max_bars_per_day.15m": 26,
    }

    def test_returns_the_configured_horizons(self) -> None:
        assert ic_measure.horizons_for(self._APR, "1d") == (1, 2)

    def test_cross_session_intraday_horizon_aborts_before_any_fetch(self) -> None:
        with pytest.raises(ValueError, match="crosses a session"):
            ic_measure.horizons_for(self._APR, "15m")

    def test_tf_without_horizons_raises(self) -> None:
        with pytest.raises(KeyError):
            ic_measure.horizons_for(self._APR, "5m")


class TestFeatureNames:
    def test_schema_types_decide_and_order_follows_featurevector(self) -> None:
        import dataclasses as dc

        from src.intelligence.schemas import FeatureVector

        fv_names = [f.name for f in dc.fields(FeatureVector)]
        present = [fv_names[2], fv_names[0]]  # schema order must not matter
        rows = [(n, "real") for n in present] + [(fv_names[1], "text"), ("not_a_feature", "real")]
        conn = FakeConn(rows_responder(rows))
        names, missing = ic_measure.feature_names(conn, "feature_vectors")
        assert names == [fv_names[0], fv_names[2]]
        assert fv_names[1] in missing and fv_names[3] in missing
        assert "not_a_feature" not in names

    def test_feature_fetch_selects_named_columns_never_star(self) -> None:
        stmt = ic_measure.feature_block_sql("feature_vectors", ["momentum_z_fast", "hurst"])
        text = stmt.as_string(None)
        assert "*" not in text
        assert '"momentum_z_fast"' in text and '"hurst"' in text
        assert '"symbol"' in text and '"bar_ts"' in text
        for needle in ("tf = %s", "symbol = ANY(%s)", "bar_ts >= %s", "bar_ts < %s"):
            assert needle in text


# ---------------------------------------------------------------------------
# A tiny real panel
# ---------------------------------------------------------------------------

_SYMBOLS = ("AAA", "BBB", "CCC")
_N = 40


def _panel() -> Panel:
    rng = np.random.default_rng(3)
    days = np.arange(np.datetime64("2026-01-05"), np.datetime64("2026-01-05") + _N)
    open_ = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (_N, len(_SYMBOLS))), axis=0))
    return Panel(
        tf="1d",
        symbols=_SYMBOLS,
        timestamps=days.astype("datetime64[D]"),
        bars_per_session=1,
        valid=np.ones(_N, dtype=bool),
        open=open_,
        close=open_,
        volume=np.ones_like(open_),
    )


def _params() -> MeasureParams:
    return MeasureParams(
        min_stride=1,
        bootstrap_block_size=2,
        bootstrap_resamples=20,
        rng_seed=1,
        fdr_alpha=0.05,
        min_obs=5,
        symbol_chunk_size=50,
        bootstrap_threads=1,
        bootstrap_chunk_resamples=7,
        monitor_window_sessions=10,
        hac_max_lag=1,
        degenerate_std=1e-8,
        monitor_degenerate_std=1e-10,
    )


def _keys(skip: tuple[int, int] | None = None):
    """Long-form (bar_ts, symbol) rows for every slot, minus one if `skip`."""
    panel = _panel()
    ts, sym = [], []
    for i, day in enumerate(panel.timestamps):
        for j, name in enumerate(_SYMBOLS):
            if skip == (i, j):
                continue
            ts.append(day.astype("datetime64[ns]"))
            sym.append(name)
    return np.array(ts), np.array(sym)


def _context(skip: tuple[int, int] | None = None) -> ic_measure.TfContext:
    ts, sym = _keys(skip)
    return ic_measure.make_tf_context([_panel()], "2026-03-01T00:00:00", ts, sym)


def _features(ctx: ic_measure.TfContext, k: int = 2) -> np.ndarray:
    rng = np.random.default_rng(5)
    return rng.normal(size=(len(ctx.grid.timestamps), len(ctx.grid.symbols), k))


def _source(features: np.ndarray, names: tuple[str, ...], block_size: int):
    """An in-memory FeatureSource: the blocks of `names`, each a column slice of `features`."""
    index = {n: i for i, n in enumerate(names)}
    blocks = tuple(ic_measure.feature_blocks(names, block_size))
    return ic_measure.FeatureSource(blocks, lambda block: features[:, :, [index[n] for n in block]])


def _scan(ctx, source, params, *, labels: np.ndarray | None = None):
    from src.intelligence.measure.regime_disclosure import label_row_masks

    existing = measure_ic.existing_rows(ctx.grid.valid_grid(), ctx.present)
    row_sets = {ic_measure.ALL_ROWS: existing}
    if labels is not None:
        masks, _ = label_row_masks(existing, labels)
        row_sets.update({f"label:{label}": m for label, m in masks.items()})
    return ic_measure.scan_family(source, ctx, params, row_sets)


def _proposer(ctx, features, names, params, horizons, block_size):
    source = _source(features, names, block_size)
    inputs = _scan(ctx, source, params)
    return ic_measure.compute_proposer_rows(ctx, source, inputs, params, horizons)


class TestSlotPresentMask:
    def test_every_job_receives_the_slot_present_mask(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _context(skip=(7, 1))
        n, m = len(ctx.grid.timestamps), len(ctx.grid.symbols)
        expected = ctx.slots.present(n, m)
        assert expected.sum() == n * m - 1 and not expected[7, 1]
        seen: dict[str, np.ndarray] = {}

        def spy(name: str, real):
            def wrapper(*args: Any, **kwargs: Any):
                seen[name] = kwargs["present"]
                return real(*args, **kwargs)

            return wrapper

        for name in (
            "term_structure",
            "regime_volatility_disclosure",
            "member_ic_over_time",
        ):
            monkeypatch.setattr(ic_measure, name, spy(name, getattr(ic_measure, name)))
        features = _features(ctx)
        names = ("f0", "f1")
        labels = np.full((n, m), "low", dtype="<U8")
        params = _params()
        source = _source(features, names, 2)
        inputs = _scan(ctx, source, params, labels=labels)
        ic_measure.compute_proposer_rows(ctx, source, inputs, params, (1, 2))
        ic_measure.compute_disclosure_rows(ctx, source, inputs, labels, params, (1,))
        member = _source(features[:, :, :1], ("f0",), 2)
        ic_measure.compute_monitoring_rows(ctx, member, _scan(ctx, member, params), params, 1)
        assert set(seen) == {
            "term_structure",
            "regime_volatility_disclosure",
            "member_ic_over_time",
        }
        for name, mask in seen.items():
            assert np.array_equal(mask, expected), name


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------


def _term(ic: list[float], p: list[float], cell: measure_ic.IcCell) -> TermStructure:
    return TermStructure(
        features=("f0", "f1"),
        horizons=(1,),
        ic=np.array(ic).reshape(2, 1),
        n_obs=np.array([[30], [30]]),
        p_value=np.array(p).reshape(2, 1),
        peak_horizon=np.array([1, 0]),
        proposer_cell=cell,
    )


class TestRows:
    def test_nan_ic_is_written_as_null_not_nan_and_not_zero(self) -> None:
        from src.intelligence.measure.ic import IcCell

        nan = float("nan")
        cell = IcCell(
            features=("f0", "f1"),
            ic=np.array([0.1, nan]),
            n_obs=np.array([30, 30]),
            n_independent=np.array([30, 30]),
            p_value=np.array([0.02, nan]),
            ci_lower=np.array([0.01, nan]),
            ci_upper=np.array([0.2, nan]),
            reliable=np.array([True, False]),
            n_degenerate=0,
            stride=1,
        )
        end = datetime(2026, 2, 1, tzinfo=UTC)
        rows = ic_measure.proposer_rows(
            "1d",
            _term([0.1, nan], [0.02, nan], cell),
            np.array([0.04, nan]),
            np.array([True, False]),
            {1: end},
        )
        cols = {name: i for i, name in enumerate(ic_measure.COLUMNS)}
        by_feature = {r[cols["feature_name"]]: r for r in rows}
        bad = by_feature["f1"]
        for name in ("ic_value", "p_value", "ic_ci_lower", "ic_ci_upper", "bh_adjusted_p"):
            assert bad[cols[name]] is None, name
        assert bad[cols["reliable"]] is False
        good = by_feature["f0"]
        assert good[cols["ic_value"]] == 0.1 and good[cols["passes_ci_gate"]] is True
        assert good[cols["regime_scope"]] == "unstratified" and good[cols["regime"]] == "_all"
        assert good[cols["symbol"]] == "POOLED" and good[cols["is_pooled"]] is True
        assert good[cols["vector_domain"]] == "quant"
        for row in rows:
            assert not any(isinstance(v, float) and v != v for v in row)

    def test_proposer_rows_cover_every_feature_and_horizon_sorted_by_window_end(self) -> None:
        ctx = _context()
        rows = _proposer(ctx, _features(ctx), ("f0", "f1"), _params(), (1, 2), 2)
        cols = {name: i for i, name in enumerate(ic_measure.COLUMNS)}
        assert len(rows) == 4
        assert {(r[cols["feature_name"]], r[cols["lookahead_bars"]]) for r in rows} == {
            ("f0", 1),
            ("f0", 2),
            ("f1", 1),
            ("f1", 2),
        }
        ends = [r[cols["training_window_end"]] for r in rows]
        assert ends == sorted(ends)
        assert all(e < datetime(2026, 3, 1, tzinfo=UTC) for e in ends)
        # CI and FDR only at the proposer horizon (the first)
        for r in rows:
            if r[cols["lookahead_bars"]] == 2:
                assert r[cols["bh_adjusted_p"]] is None and r[cols["ic_ci_lower"]] is None

    def test_disclosure_rows_one_per_label_feature_horizon(self) -> None:
        ctx = _context()
        n, m = len(ctx.grid.timestamps), len(ctx.grid.symbols)
        labels = np.where(np.arange(n)[:, None] % 2 == 0, "low", "high").astype("<U8")
        labels = np.broadcast_to(labels, (n, m)).copy()
        source = _source(_features(ctx, 1), ("f0",), 2)
        inputs = _scan(ctx, source, _params(), labels=labels)
        rows = ic_measure.compute_disclosure_rows(ctx, source, inputs, labels, _params(), (1,))
        cols = {name: i for i, name in enumerate(ic_measure.COLUMNS)}
        assert {r[cols["regime"]] for r in rows} == {"low", "high"}
        assert {r[cols["regime_scope"]] for r in rows} == {"regime_volatility"}
        assert {r[cols["regime_label_source"]] for r in rows} == {
            "feature_vectors.regime_volatility"
        }

    def test_member_rows_one_per_window(self) -> None:
        ctx = _context()
        source = _source(_features(ctx, 1), ("f0",), 2)
        rows = ic_measure.compute_monitoring_rows(
            ctx, source, _scan(ctx, source, _params()), _params(), 1
        )
        cols = {name: i for i, name in enumerate(ic_measure.COLUMNS)}
        assert len(rows) == 4  # 40 sessions in windows of 10
        assert {r[cols["regime_scope"]] for r in rows} == {"member_window"}
        assert len({r[cols["training_window_end"]] for r in rows}) == 4

    def test_a_unit_reaching_oos_start_raises_before_any_write(self) -> None:
        cols = {name: i for i, name in enumerate(ic_measure.COLUMNS)}
        row = [None] * len(ic_measure.COLUMNS)
        row[cols["training_window_end"]] = _OOS
        with pytest.raises(ValueError, match="oos_start"):
            ic_measure.refuse_reaching_oos([tuple(row)], _OOS)


# ---------------------------------------------------------------------------
# Block digest and alignment
# ---------------------------------------------------------------------------


class TestColumnDigests:
    def test_one_changed_value_moves_the_column_digest_fetch_order_does_not(self) -> None:
        ctx = _context()
        ts, sym = _keys()
        values = np.random.default_rng(1).normal(size=(len(ts), 2))
        grid, _ = measure_ic.scatter_features(ctx.grid, ctx.slots, values)
        base = ic_measure.column_digest("f0", grid[:, :, 0])
        perm = np.random.default_rng(2).permutation(len(ts))
        slots2 = measure_ic.map_slots(ctx.grid, ts[perm], sym[perm])
        grid2, _ = measure_ic.scatter_features(ctx.grid, slots2, values[perm])
        assert ic_measure.column_digest("f0", grid2[:, :, 0]) == base
        values[5, 0] += 1e-9
        grid3, _ = measure_ic.scatter_features(ctx.grid, ctx.slots, values)
        assert ic_measure.column_digest("f0", grid3[:, :, 0]) != base

    def test_the_name_is_part_of_the_column_digest(self) -> None:
        column = _features(_context())[:, :, 0]
        assert ic_measure.column_digest("a", column) != ic_measure.column_digest("b", column)

    def test_features_digest_covers_every_column_and_the_present_mask(self) -> None:
        ctx = _context()
        cols = {"a": "1" * 64, "b": "2" * 64}
        base = ic_measure.features_digest(cols, ctx.present)
        assert ic_measure.features_digest({"b": cols["b"], "a": cols["a"]}, ctx.present) == base
        assert ic_measure.features_digest({**cols, "b": "3" * 64}, ctx.present) != base
        assert ic_measure.features_digest({"a": cols["a"]}, ctx.present) != base
        assert ic_measure.features_digest(cols, _context(skip=(3, 1)).present) != base


class TestPanelsDigest:
    def _panels(self, split: bool) -> tuple[ic_measure.StackGrid, list[Panel]]:
        whole = _panel()
        short = Panel(
            tf="1d",
            symbols=("CCC",),
            timestamps=whole.timestamps[5:],
            bars_per_session=1,
            valid=whole.valid[5:],
            open=np.asarray(whole.open)[5:, 2:3],
            close=np.asarray(whole.close)[5:, 2:3],
            volume=np.asarray(whole.volume)[5:, 2:3],
        )
        head = Panel(
            tf="1d",
            symbols=("AAA", "BBB"),
            timestamps=whole.timestamps,
            bars_per_session=1,
            valid=whole.valid,
            open=np.asarray(whole.open)[:, :2],
            close=np.asarray(whole.close)[:, :2],
            volume=np.asarray(whole.volume)[:, :2],
        )
        panels = [head, short] if split else [head, short]
        return ic_measure.stack_grid(panels, "2026-03-01T00:00:00"), panels

    def test_the_digest_is_independent_of_how_symbols_are_split_into_panels(self) -> None:
        grid, panels = self._panels(True)
        first = ic_measure.panels_digest(grid, panels)
        # the same three series in three one-symbol panels
        whole = _panel()
        singles = [
            Panel(
                tf="1d",
                symbols=(name,),
                timestamps=whole.timestamps[(5 if name == "CCC" else 0) :],
                bars_per_session=1,
                valid=whole.valid[(5 if name == "CCC" else 0) :],
                open=np.asarray(whole.open)[(5 if name == "CCC" else 0) :, j : j + 1],
                close=np.asarray(whole.close)[(5 if name == "CCC" else 0) :, j : j + 1],
                volume=np.asarray(whole.volume)[(5 if name == "CCC" else 0) :, j : j + 1],
            )
            for j, name in enumerate(_SYMBOLS)
        ]
        other = ic_measure.stack_grid(singles, "2026-03-01T00:00:00")
        assert ic_measure.panels_digest(other, singles) == first

    def test_a_changed_price_or_volume_moves_it(self) -> None:
        grid, panels = self._panels(True)
        base = ic_measure.panels_digest(grid, panels)
        for field in ("open", "close", "volume"):
            changed = np.array(getattr(panels[1], field))
            changed[3, 0] *= 1.01
            edited = [panels[0], dataclasses.replace(panels[1], **{field: changed})]
            assert ic_measure.panels_digest(grid, edited) != base, field

    def test_targets_never_request_the_dividend_grid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        from src.intelligence.measure import targets

        seen: list[dict[str, Any]] = []

        async def fake_build_panel(dsn, out_dir, **kwargs):
            seen.append(kwargs)
            return Path(out_dir) / "panel"

        monkeypatch.setattr(targets.snapshot, "build_panel", fake_build_panel)
        asyncio.run(
            targets.build_target_panels(
                "dsn",
                Path("/tmp"),
                ["AAA"],
                "1d",
                "2020-01-01T00:00:00+00:00",
                "2026-03-01T00:00:00+00:00",
                "2026-03-01T00:00:00+00:00",
                _params(),
            )
        )
        assert seen and not any(kwargs.get("dividends") for kwargs in seen)


class TestFeatureBlocks:
    def test_blocks_cover_every_name_in_order(self) -> None:
        names = tuple(f"f{i}" for i in range(10))
        blocks = ic_measure.feature_blocks(names, 4)
        assert [n for b in blocks for n in b] == list(names)
        assert [len(b) for b in blocks] == [4, 4, 2]

    def test_a_trailing_single_column_joins_the_previous_block(self) -> None:
        blocks = ic_measure.feature_blocks(tuple(f"f{i}" for i in range(9)), 4)
        assert [len(b) for b in blocks] == [4, 5]
        assert [len(b) for b in ic_measure.feature_blocks(("a", "b", "c"), 10)] == [3]
        assert [len(b) for b in ic_measure.feature_blocks(("a",), 4)] == [1]

    def test_size_below_one_raises(self) -> None:
        with pytest.raises(ValueError):
            ic_measure.feature_blocks(("a", "b"), 0)


_FAMILY = tuple(f"f{i}" for i in range(11))


def _family_features(ctx: ic_measure.TfContext) -> np.ndarray:
    """11 features with the things that make blocking matter: NaNs in different columns (row
    completeness), ties, a constant column (degenerate) and a fully missing one."""
    n, m = len(ctx.grid.timestamps), len(ctx.grid.symbols)
    rng = np.random.default_rng(17)
    target_like = rng.normal(size=(n, m))
    feats = rng.normal(size=(n, m, len(_FAMILY)))
    feats[:, :, 0] += 0.4 * target_like  # some signal, a spread of p-values
    feats[:, :, 1] = np.round(feats[:, :, 1], 1)
    feats[:, :, 3] = 5.0
    feats[:, :, 4] = np.nan
    feats[rng.random((n, m)) < 0.06, 7] = np.nan
    feats[rng.random((n, m)) < 0.06, 10] = np.nan
    return feats


class TestBlockingNeverReachesAValue:
    """Memory blocking is operational: any block size gives the same rows, bit for bit."""

    def _ctx(self) -> ic_measure.TfContext:
        return _context()

    def test_proposer_rows_are_identical_for_every_block_size(self) -> None:
        ctx = self._ctx()
        features = _family_features(ctx)
        reference = _proposer(ctx, features, _FAMILY, _params(), (1, 2), 32)
        assert reference
        for size in (2, 4, 5, 7):
            assert _proposer(ctx, features, _FAMILY, _params(), (1, 2), size) == reference, size

    def test_bh_columns_match_across_block_sizes_and_are_not_vacuous(self) -> None:
        ctx = self._ctx()
        features = _family_features(ctx)
        cols = {name: i for i, name in enumerate(ic_measure.COLUMNS)}
        rows4 = _proposer(ctx, features, _FAMILY, _params(), (1,), 4)
        rows32 = _proposer(ctx, features, _FAMILY, _params(), (1,), 32)
        adjusted = [r[cols["bh_adjusted_p"]] for r in rows4]
        assert adjusted == [r[cols["bh_adjusted_p"]] for r in rows32]
        assert [r[cols["passes_fdr"]] for r in rows4] == [r[cols["passes_fdr"]] for r in rows32]
        assert any(a is not None for a in adjusted)
        # per-block BH (what a block-local family would do) is a different answer on this data
        from src.intelligence.measure.proposer import propose

        stack = ctx.stack(1)
        per_block = []
        for block in ic_measure.feature_blocks(_FAMILY, 4):
            idx = [_FAMILY.index(n) for n in block]
            per_block.extend(
                propose(
                    features[:, :, idx], block, stack, _params(), present=ctx.present
                ).bh_adjusted_p.tolist()
            )
        family = [a if a is not None else float("nan") for a in adjusted]
        assert not np.allclose(per_block, family, equal_nan=True)

    def test_disclosure_rows_are_identical_for_every_block_size(self) -> None:
        ctx = self._ctx()
        features = _family_features(ctx)
        n, m = len(ctx.grid.timestamps), len(ctx.grid.symbols)
        labels = np.where(np.arange(n)[:, None] % 3 == 0, "high", "low").astype("<U8")
        labels = np.broadcast_to(labels, (n, m)).copy()
        out = []
        for size in (32, 4, 7):
            source = _source(features, _FAMILY, size)
            inputs = _scan(ctx, source, _params(), labels=labels)
            out.append(
                ic_measure.compute_disclosure_rows(ctx, source, inputs, labels, _params(), (1, 2))
            )
        assert out[0] == out[1] == out[2] and out[0]

    def test_monitoring_rows_are_identical_for_every_block_size(self) -> None:
        ctx = self._ctx()
        features = _family_features(ctx)
        members = (_FAMILY[0], _FAMILY[2], _FAMILY[5], _FAMILY[7])
        index = [_FAMILY.index(x) for x in members]
        out = []
        for size in (2, 3, 32):
            source = _source(features[:, :, index], members, size)
            inputs = _scan(ctx, source, _params())
            out.append(ic_measure.compute_monitoring_rows(ctx, source, inputs, _params(), 1))
        assert out[0] == out[1] == out[2] and out[0]

    def test_the_identity_inputs_do_not_depend_on_the_block_size(self) -> None:
        ctx = self._ctx()
        features = _family_features(ctx)
        first = _scan(ctx, _source(features, _FAMILY, 2), _params())
        second = _scan(ctx, _source(features, _FAMILY, 32), _params())
        assert first.column_digests == second.column_digests
        assert first.features_key == second.features_key
        assert np.array_equal(first.complete["all"], second.complete["all"])

    def test_a_changed_column_moves_the_features_key(self) -> None:
        ctx = self._ctx()
        features = _family_features(ctx)
        base = _scan(ctx, _source(features, _FAMILY, 4), _params()).features_key
        features[3, 1, 6] += 1e-6
        assert _scan(ctx, _source(features, _FAMILY, 4), _params()).features_key != base

    def test_a_block_that_changed_between_passes_is_refused(self) -> None:
        ctx = self._ctx()
        features = _family_features(ctx)
        source = _source(features, _FAMILY, 4)
        inputs = _scan(ctx, source, _params())
        features[3, 1, 6] += 1e-6
        with pytest.raises(ValueError, match="changed between fetches"):
            ic_measure.compute_proposer_rows(ctx, source, inputs, _params(), (1,))


class TestSkippedBootstrapsKeepStoredRows:
    """The term structure bootstraps only its first horizon and monitoring bootstraps nothing;
    the stored rows are the rows of cells that were bootstrapped everywhere."""

    def test_proposer_rows_equal_those_built_from_fully_bootstrapped_cells(self) -> None:
        from src.intelligence.measure.proposer import propose

        ctx = _context()
        features = _family_features(ctx)
        horizons = (2, 1, 5)
        params = _params()
        rows = _proposer(ctx, features, _FAMILY, params, horizons, 4)
        full = {
            h: propose(features, _FAMILY, ctx.stack(h), params, present=ctx.present)
            for h in horizons
        }
        first = full[horizons[0]]
        term = TermStructure(
            features=_FAMILY,
            horizons=horizons,
            ic=np.stack([full[h].cell.ic for h in horizons], axis=1),
            n_obs=np.stack([full[h].cell.n_independent for h in horizons], axis=1),
            p_value=np.stack([full[h].cell.p_value for h in horizons], axis=1),
            peak_horizon=np.zeros(len(_FAMILY), dtype=int),
            proposer_cell=first.cell,
        )
        ends = {h: ic_measure._window_end(ctx.stack(h)) for h in horizons}
        reference = ic_measure._sorted_rows(
            ic_measure.proposer_rows("1d", term, first.bh_adjusted_p, first.passes_fdr, ends)
        )
        assert rows == reference and rows

    def test_monitoring_rows_equal_those_built_from_bootstrapped_cells(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.intelligence.measure import monitoring as measure_monitoring

        ctx = _context()
        features = _family_features(ctx)
        members = (_FAMILY[0], _FAMILY[2], _FAMILY[5])
        index = [_FAMILY.index(x) for x in members]
        source = _source(features[:, :, index], members, 2)
        rows = ic_measure.compute_monitoring_rows(
            ctx, source, _scan(ctx, source, _params()), _params(), 1
        )
        real = measure_monitoring.pooled_rank_ic

        def with_bootstrap(*args: Any, **kwargs: Any):
            kwargs["bootstrap"] = True
            return real(*args, **kwargs)

        monkeypatch.setattr(measure_monitoring, "pooled_rank_ic", with_bootstrap)
        reference = ic_measure.compute_monitoring_rows(
            ctx, source, _scan(ctx, source, _params()), _params(), 1
        )
        assert rows == reference and rows


class TestFamilyDigest:
    def test_adding_or_removing_a_feature_changes_it_and_order_does_not(self) -> None:
        params = _params()
        base = ic_measure.family_digest(("a", "b", "c"), params)
        assert ic_measure.family_digest(("c", "b", "a"), params) == base
        assert ic_measure.family_digest(("a", "b", "c", "d"), params) != base
        assert ic_measure.family_digest(("a", "b"), params) != base

    def test_a_computational_param_moves_it_and_an_operational_one_does_not(self) -> None:
        params = _params()
        base = ic_measure.family_digest(("a", "b"), params)
        assert (
            ic_measure.family_digest(("a", "b"), dataclasses.replace(params, symbol_chunk_size=3))
            == base
        )
        assert (
            ic_measure.family_digest(("a", "b"), dataclasses.replace(params, fdr_alpha=0.1)) != base
        )


class TestUnitOwnsItsScope:
    def test_the_unit_names_no_feature_and_no_symbol_and_its_writer_has_no_block_index(
        self,
    ) -> None:
        ctx = _context()
        for job in ic_measure._ALL_JOBS:
            unit = ic_measure.IcMeasure._unit(
                job,
                "1d",
                ctx,
                datetime(2026, 1, 1, tzinfo=UTC),
                _OOS,
                {"k": 1},
                {"job": job},
                lambda: [],
            )
            assert unit.spec.writer == f"ic_measure.{job}"
            assert set(unit.spec.replace_where) == {"tf", "symbol", "regime_scope"}

    def test_the_unit_key_ignores_symbols_and_window_but_not_scope(self) -> None:
        ctx = _context()
        args = (datetime(2026, 1, 1, tzinfo=UTC), _OOS, {"k": 1}, {"job": "proposer"}, lambda: [])
        one = ic_measure.IcMeasure._unit("proposer", "1d", ctx, *args).spec
        other = ic_measure.IcMeasure._unit(
            "proposer", "1d", ctx, datetime(2026, 1, 5, tzinfo=UTC), *args[1:]
        ).spec
        assert one.unit_key == other.unit_key
        scope = ic_measure.IcMeasure._unit("regime_volatility", "1d", ctx, *args).spec
        assert scope.unit_key != one.unit_key


# ---------------------------------------------------------------------------
# Unit execution: skip, replace, dry run
# ---------------------------------------------------------------------------


def _spec() -> Any:
    from services._batch_utils import BulkLoadSpec

    return BulkLoadSpec(
        writer="ic_measure.proposer",
        target_table="feature_ic_scores_v2",
        time_column="training_window_end",
        tf="1d",
        range_start=datetime(2026, 1, 1, tzinfo=UTC),
        range_end=_OOS,
        symbols=_SYMBOLS,
        code_key="a" * 64,
        apr_snapshot={"k": 1},
        input_digest="b" * 64,
        replace_where={
            "tf": "1d",
            "symbol": "POOLED",
            "regime_scope": "unstratified",
            "feature_name": ["f0"],
        },
    )


def _good_row() -> tuple:
    cols = {name: i for i, name in enumerate(ic_measure.COLUMNS)}
    row: list[Any] = [None] * len(ic_measure.COLUMNS)
    row[cols["training_window_end"]] = datetime(2026, 2, 1, tzinfo=UTC)
    return tuple(row)


class _Write:
    def connection(self) -> object:
        return object()


class TestExecuteUnit:
    def _unit(self, compute) -> ic_measure.UnitPlan:
        return ic_measure.UnitPlan(job="proposer", spec=_spec(), compute=compute)

    def test_completed_identity_skips_before_any_ic_is_computed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            ic_measure, "completed_provenance_batch", lambda conn, spec: {"row_count": 7}
        )
        outcome = ic_measure.execute_unit(
            self._unit(lambda: calls.append("compute") or []), FakeConn(), None, _OOS, dry_run=False
        )
        assert outcome.status == "skipped" and calls == []

    def test_changed_identity_with_a_prior_completed_unit_replaces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(ic_measure, "completed_provenance_batch", lambda conn, spec: None)
        monkeypatch.setattr(ic_measure, "prior_completed_unit", lambda conn, spec: True)

        def fake_bulk_load(conn, spec, columns, rows, **kwargs):
            captured.update(kwargs, spec=spec, rows=list(rows))
            return BulkLoadResult(
                spec.batch_key, "loaded", len(captured["rows"]), 0, rows_replaced=3
            )

        monkeypatch.setattr(ic_measure, "bulk_load", fake_bulk_load)
        outcome = ic_measure.execute_unit(
            self._unit(lambda: [_good_row()]), FakeConn(), _Write(), _OOS, dry_run=False
        )
        assert outcome.status == "replaced" and outcome.rows == 1
        assert captured["spec"].replace_where["regime_scope"] == "unstratified"

    def test_a_unit_with_no_prior_batch_is_loaded_through_the_same_replace_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        monkeypatch.setattr(ic_measure, "completed_provenance_batch", lambda conn, spec: None)
        monkeypatch.setattr(ic_measure, "prior_completed_unit", lambda conn, spec: False)

        def fake_bulk_load(conn, spec, columns, rows, **kwargs):
            captured.update(kwargs)
            return BulkLoadResult(spec.batch_key, "loaded", 1, 0)

        monkeypatch.setattr(ic_measure, "bulk_load", fake_bulk_load)
        outcome = ic_measure.execute_unit(
            self._unit(lambda: [_good_row()]), FakeConn(), _Write(), _OOS, dry_run=False
        )
        assert outcome.status == "loaded"
        assert "replace_where" not in captured and "compress_before" not in captured

    def test_dry_run_reports_without_calling_bulk_load(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ic_measure, "completed_provenance_batch", lambda conn, spec: None)
        monkeypatch.setattr(ic_measure, "prior_completed_unit", lambda conn, spec: True)
        monkeypatch.setattr(
            ic_measure, "bulk_load", lambda *a, **k: pytest.fail("bulk_load called in a dry run")
        )
        outcome = ic_measure.execute_unit(
            self._unit(lambda: [_good_row(), _good_row()]), FakeConn(), None, _OOS, dry_run=True
        )
        assert outcome.status == "would_replace" and outcome.rows == 2

    def test_dry_run_skip_and_load_statuses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ic_measure, "completed_provenance_batch", lambda conn, spec: {"row_count": 1}
        )
        assert (
            ic_measure.execute_unit(
                self._unit(lambda: []), FakeConn(), None, _OOS, dry_run=True
            ).status
            == "would_skip"
        )
        monkeypatch.setattr(ic_measure, "completed_provenance_batch", lambda conn, spec: None)
        monkeypatch.setattr(ic_measure, "prior_completed_unit", lambda conn, spec: False)
        assert (
            ic_measure.execute_unit(
                self._unit(lambda: [_good_row()]), FakeConn(), None, _OOS, dry_run=True
            ).status
            == "would_load"
        )

    def test_a_row_reaching_oos_start_writes_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ic_measure, "completed_provenance_batch", lambda conn, spec: None)
        monkeypatch.setattr(ic_measure, "prior_completed_unit", lambda conn, spec: False)
        monkeypatch.setattr(
            ic_measure,
            "bulk_load",
            lambda *a, **k: pytest.fail("bulk_load called for a refused unit"),
        )
        cols = {name: i for i, name in enumerate(ic_measure.COLUMNS)}
        row = list(_good_row())
        row[cols["training_window_end"]] = _OOS
        with pytest.raises(ValueError, match="oos_start"):
            ic_measure.execute_unit(
                self._unit(lambda: [tuple(row)]), FakeConn(), _Write(), _OOS, dry_run=False
            )


class TestBarDigestBracket:
    def test_changed_symbols_refuse_the_tf_naming_them(self) -> None:
        before = {"AAA": "1" * 64, "BBB": "2" * 64}
        after = {"AAA": "1" * 64, "BBB": "3" * 64}
        with pytest.raises(ValueError, match="BBB"):
            ic_measure.check_bar_digests(before, after, allow_absent=False)

    def test_absent_symbols_refuse_a_real_run_but_not_when_allowed(self) -> None:
        same = {"AAA": "absent", "BBB": "2" * 64}
        with pytest.raises(ValueError, match="AAA"):
            ic_measure.check_bar_digests(same, same, allow_absent=False)
        assert ic_measure.check_bar_digests(same, same, allow_absent=True) == ["AAA"]

    def test_unchanged_present_digests_pass(self) -> None:
        same = {"AAA": "1" * 64}
        assert ic_measure.check_bar_digests(same, dict(same), allow_absent=False) == []


class TestMonitoringNeedsMembers:
    def test_monitoring_without_members_has_no_units(self) -> None:
        assert ic_measure.active_jobs(["proposer", "monitoring"], []) == ["proposer"]
        assert ic_measure.active_jobs(["monitoring"], []) == []
        assert ic_measure.active_jobs(["monitoring"], ["f0"]) == ["monitoring"]

    def test_unknown_job_raises(self) -> None:
        with pytest.raises(ValueError, match="nope"):
            ic_measure.active_jobs(["nope"], [])


class TestSourceLints:
    def test_no_direct_writes_or_star_selects(self) -> None:
        source = (_REPO / "services" / "ic_measure.py").read_text()
        assert not re.search(
            r"INSERT INTO feature_ic_scores|UPDATE feature_ic_scores|executemany", source
        )
        assert "bulk_load(" in source
        assert "SELECT *" not in source


# ---------------------------------------------------------------------------
# Code key: the hashed modules equal an independently computed import closure
# ---------------------------------------------------------------------------


def _bytecode_closure(entries: tuple[str, ...], own: tuple[str, ...]) -> set[str]:
    """Slow independent walk: IMPORT_NAME instructions of the compiled code (a different
    mechanism from the ast walk in src.core.code_identity), following modules, hashing a package
    as its __init__ without following it, adding every ancestor package."""
    import dis
    import importlib.util
    import types

    roots = ("src", "services")

    def spec(name: str):
        return importlib.util.find_spec(name)

    def imports_of(name: str) -> set[str]:
        origin = spec(name).origin
        code = compile(Path(origin).read_text(), origin, "exec")
        package = (
            name if spec(name).submodule_search_locations is not None else name.rpartition(".")[0]
        )
        found: set[str] = set()
        stack: list[types.CodeType] = [code]
        while stack:
            current = stack.pop()
            consts: list[Any] = []
            for ins in dis.get_instructions(current):
                if ins.opname in ("LOAD_CONST", "LOAD_SMALL_INT"):  # 3.14 loads small ints apart
                    consts.append(ins.argval)
                    if isinstance(ins.argval, types.CodeType):
                        stack.append(ins.argval)
                elif ins.opname == "IMPORT_NAME":
                    level, fromlist = consts[-2], consts[-1]
                    base = (
                        importlib.util.resolve_name("." * level + ins.argval, package)
                        if level
                        else ins.argval
                    )
                    if base.partition(".")[0] not in roots:
                        continue
                    found.add(base)
                    if spec(base).submodule_search_locations is not None:
                        for item in fromlist or ():
                            try:
                                sub = spec(f"{base}.{item}")
                            except (ModuleNotFoundError, ValueError):
                                sub = None
                            if sub is not None:
                                found.add(f"{base}.{item}")
        return found

    seen: set[str] = set()
    todo = list(entries)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        if spec(name).submodule_search_locations is None:
            todo.extend(imports_of(name))
    out = seen | set(own)
    for name in list(out):
        parts = name.split(".")
        out.update(".".join(parts[:i]) for i in range(1, len(parts)) if parts[0] in roots)
    return {n for n in out if spec(n).origin is not None}  # a namespace package has no file


class TestCodeKeyClosure:
    @pytest.mark.parametrize("job", ic_measure._ALL_JOBS)
    def test_hashed_modules_equal_the_independently_walked_import_closure(self, job: str) -> None:
        entries = (*ic_measure._COMMON_ENTRIES, *ic_measure._JOB_ENTRIES[job])
        expected = _bytecode_closure(entries, ic_measure._OWN_MODULES)
        assert set(ic_measure.job_code_modules(job)) == expected

    def test_the_target_path_modules_the_hand_list_missed_are_hashed(self) -> None:
        for job in ic_measure._ALL_JOBS:
            mods = set(ic_measure.job_code_modules(job))
            assert {
                "src.intelligence.research.store",
                "src.intelligence.research.dividends",
                "src.core.market_calendar",
                "src.intelligence.statistics.ic_math",
            } <= mods, job

    def test_jobs_are_scoped_a_proposer_module_is_not_in_the_monitoring_key(self) -> None:
        assert "src.intelligence.measure.proposer" in ic_measure.job_code_modules("proposer")
        assert "src.intelligence.measure.proposer" not in ic_measure.job_code_modules("monitoring")
        assert "src.intelligence.measure.monitoring" not in ic_measure.job_code_modules("proposer")

    def test_editing_a_closure_module_moves_the_key_and_an_outside_module_does_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.core import code_identity

        real = code_identity.source_path
        edited: dict[str, bytes] = {}

        def patched(name: str) -> Path:
            if name in edited:
                path = Path(__file__).parent / f"_edit_{name}.py"
                path.write_bytes(edited[name])
                created.append(path)
                return path
            return real(name)

        created: list[Path] = []
        monkeypatch.setattr(code_identity, "source_path", patched)
        try:
            base = ic_measure.job_code_key("proposer")
            for name, moves in (
                ("src.intelligence.research.store", True),
                ("src.core.market_calendar", True),
                ("src.intelligence.measure.monitoring", False),  # outside the proposer closure
            ):
                edited.clear()
                edited[name] = real(name).read_bytes() + b"\nEDIT = 1\n"
                assert (ic_measure.job_code_key("proposer") != base) is moves, name
        finally:
            for path in created:
                path.unlink(missing_ok=True)
