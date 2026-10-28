"""S0's pure feature-read decisions (184-04, todo 435): each refusal names its rule id."""

from __future__ import annotations

import dataclasses
import json
import typing
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.feature_factory import FeatureFactoryConfig
from src.intelligence.features.contract.registry import default_registry, feature_memory_bars
from src.intelligence.features.kernels._hmm import HmmConfig
from src.intelligence.research import feature_inputs as fi
from src.intelligence.research import store
from src.intelligence.research.feature_inputs import FeatureInputRefused

REG = default_registry()
T0 = datetime(2024, 1, 1, tzinfo=UTC)
T1 = datetime(2024, 7, 1, tzinfo=UTC)
T2 = datetime(2025, 1, 1, tzinfo=UTC)
PLAIN = next(c for c in REG.feature_columns() if not REG.is_path_dependent(c))
PATH_DEP = next(c for c in REG.feature_columns() if REG.is_path_dependent(c))


# ---------------------------------------------------------------------------
# fixtures: a real config from a complete value set, never defaults
# ---------------------------------------------------------------------------


def _fixture_value(hint: object, i: int) -> object:
    if hint is int:
        return 7 + i
    if hint is float:
        return 0.25 + i / 64
    if hint is str:
        return "diag"
    raise AssertionError(f"no fixture value for {hint}")


def _hmm() -> HmmConfig:
    hints = typing.get_type_hints(HmmConfig)
    values = {
        f.metadata["apr_key"]: _fixture_value(hints[f.name], i)
        for i, f in enumerate(dataclasses.fields(HmmConfig))
    }
    return HmmConfig.from_values(lambda key, default: values.get(key, default))


def _real_config(*, hmm: bool = True) -> FeatureFactoryConfig:
    hints = typing.get_type_hints(FeatureFactoryConfig)
    values: dict[str, object] = {}
    for i, f in enumerate(dataclasses.fields(FeatureFactoryConfig)):
        if f.name == "hmm":
            continue
        if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            values[f.name] = _fixture_value(hints[f.name], i)
    return FeatureFactoryConfig(**values, hmm=_hmm() if hmm else None)


def _as_stored(config: FeatureFactoryConfig) -> dict:
    """asdict as the database returns jsonb: through JSON."""
    return json.loads(json.dumps(dataclasses.asdict(config)))


SNAP = _as_stored(_real_config())
SNAP_HASH = fi.config_projection_hash(fi.config_projection(SNAP))


def _batch(
    key: str = "b1",
    *,
    symbols: tuple[str, ...] = ("AAA", "BBB"),
    start: datetime = T0,
    end: datetime = T2,
    code_key: str = "c" * 40,
    snapshot: dict | None = None,
    status: str = "completed",
    writer: str = fi.REBUILD_WRITER,
    target_table: str = fi.REBUILD_TARGET_TABLE,
) -> dict:
    return {
        "batch_key": key,
        "writer": writer,
        "target_table": target_table,
        "tf": "1d",
        "range_start": start,
        "range_end": end,
        "symbols": list(symbols),
        "code_key": code_key,
        "apr_hash": "apr-" + key,
        "apr_snapshot": SNAP if snapshot is None else snapshot,
        "input_digest": "dig-" + key,
        "generation": 1,
        "status": status,
    }


def _pin(batches, *, pin: str = SNAP_HASH, symbols=("AAA", "BBB"), start=T0, end=T2) -> dict:
    return fi.provenance_pin(
        batches,
        symbols=list(symbols),
        span_start=start,
        span_end=end,
        pinned_config_projection_hash=pin,
    )


# ---------------------------------------------------------------------------
# columns and SQL (B1e)
# ---------------------------------------------------------------------------


def test_columns_unknown_refuses():
    with pytest.raises(FeatureInputRefused, match="B1e"):
        fi.check_columns(["not_a_feature"], REG)


def test_columns_quote_refuses_before_sql():
    with pytest.raises(FeatureInputRefused, match="B1e"):
        fi.feature_select_sql([PLAIN + '"; DROP TABLE x; --'], REG)


def test_columns_select_sql_text():
    a, b = REG.feature_columns()[:2]
    sql = fi.feature_select_sql([a, b], REG)
    for part in (f'"{a}"', f'"{b}"', "symbol", "bar_ts", "ORDER BY bar_ts, symbol"):
        assert part in sql
    for n in range(1, 5):
        assert f"${n}" in sql
    assert "*" not in sql


# ---------------------------------------------------------------------------
# scatter (B1e)
# ---------------------------------------------------------------------------

GRID_TS = np.array(
    [np.datetime64("2024-01-02T21:00", "ns"), np.datetime64("2024-01-03T21:00", "ns")]
)
DAY0 = datetime(2024, 1, 2, 21, tzinfo=UTC)
DAY1 = datetime(2024, 1, 3, 21, tzinfo=UTC)


def test_scatter_exact_match_float32():
    rows = [("AAA", DAY0, 1.5, None), ("BBB", DAY1, 2.5, 3.0)]
    arrays, unmatched = fi.scatter_rows(rows, GRID_TS, ["AAA", "BBB"], ["x", "y"])
    assert unmatched == 0
    assert arrays["x"].dtype == np.float32
    assert arrays["x"][0, 0] == np.float32(1.5) and arrays["x"][1, 1] == np.float32(2.5)
    assert np.isnan(arrays["x"][0, 1]) and np.isnan(arrays["x"][1, 0])
    assert np.isnan(arrays["y"][0, 0]) and arrays["y"][1, 1] == np.float32(3.0)
    present = fi.present_mask(rows, GRID_TS, ["AAA", "BBB"])
    assert present.tolist() == [[True, False], [False, True]]


def test_scatter_duplicate_raises():
    rows = [("AAA", DAY0, 1.0), ("AAA", DAY0, 2.0)]
    with pytest.raises(FeatureInputRefused, match="duplicate"):
        fi.scatter_rows(rows, GRID_TS, ["AAA"], ["x"])


def test_scatter_unmatched_counted():
    off_grid = DAY0 + timedelta(minutes=1)
    rows = [("AAA", DAY0, 1.0), ("AAA", off_grid, 2.0), ("ZZZ", DAY1, 3.0)]
    arrays, unmatched = fi.scatter_rows(rows, GRID_TS, ["AAA"], ["x"])
    assert unmatched == 2
    assert int(np.isfinite(arrays["x"]).sum()) == 1


# ---------------------------------------------------------------------------
# provenance pin (B1f)
# ---------------------------------------------------------------------------


def test_provenance_uncovered_symbol_refuses():
    with pytest.raises(FeatureInputRefused, match="B1f"):
        _pin([_batch(symbols=("AAA",))])


def test_provenance_gap_in_union_refuses():
    batches = [_batch("b1", end=T1), _batch("b2", start=T1 + timedelta(days=1))]
    with pytest.raises(FeatureInputRefused, match="no completed provenance"):
        _pin(batches)


def test_provenance_union_of_ranges_covers():
    block = _pin([_batch("b2", start=T1), _batch("b1", end=T1)])
    assert block["batch_keys"] == ["b1", "b2"]


def test_provenance_superseded_does_not_cover():
    batches = [_batch("b1", end=T1), _batch("b2", start=T1, status="superseded")]
    with pytest.raises(FeatureInputRefused, match="B1f"):
        _pin(batches)


def test_provenance_hash_pin_mismatch_names_both():
    wrong = "0" * 64
    with pytest.raises(FeatureInputRefused, match="B1f") as caught:
        _pin([_batch()], pin=wrong)
    assert wrong in str(caught.value) and SNAP_HASH in str(caught.value)


def test_provenance_unpinned_field_disagreement_refuses():
    """Two batches agree on every window a spec author would look at but differ on one other
    field; the pin equals one batch's projection hash and the read still refuses."""
    other = dict(SNAP)
    other["canary_rng_seed"] = SNAP["canary_rng_seed"] + 1
    batches = [_batch("b1", end=T1), _batch("b2", start=T1, snapshot=other)]
    with pytest.raises(FeatureInputRefused, match="canary_rng_seed") as caught:
        _pin(batches, pin=SNAP_HASH)
    assert "B1f" in str(caught.value)


def test_provenance_mixed_code_keys_refuse():
    batches = [_batch("b1", end=T1), _batch("b2", start=T1, code_key="d" * 40)]
    with pytest.raises(FeatureInputRefused, match="code keys"):
        _pin(batches)


def test_provenance_missing_config_field_refuses():
    partial = {k: v for k, v in SNAP.items() if k != "hma_period"}
    with pytest.raises(FeatureInputRefused, match="hma_period"):
        _pin([_batch(snapshot=partial)])


def test_provenance_passing_block():
    block = _pin([_batch("b2", start=T1), _batch("b1", end=T1)])
    assert block["batch_keys"] == ["b1", "b2"]
    assert block["code_key"] == "c" * 40
    assert block["apr_hashes"] == ["apr-b1", "apr-b2"]
    assert block["input_digests"] == {"b1": "dig-b1", "b2": "dig-b2"}
    assert block["projection"] == fi.config_projection(SNAP)
    assert block["projection_hash"] == SNAP_HASH
    json.dumps(block)  # JSON-able


def test_provenance_snapshot_as_json_text():
    batch = _batch()
    batch["apr_snapshot"] = json.dumps(SNAP)
    assert _pin([batch])["projection_hash"] == SNAP_HASH


# ---------------------------------------------------------------------------
# the one config (B1f)
# ---------------------------------------------------------------------------


def test_config_from_block_and_memory():
    block = _pin([_batch()])
    config = fi.feature_config(block)
    assert isinstance(config, FeatureFactoryConfig)
    for name, value in block["projection"].items():
        got = getattr(config, name)
        got = dataclasses.asdict(got) if dataclasses.is_dataclass(got) else got
        assert got == value, name
    assert fi.column_memory_bars(PLAIN, config, REG) == feature_memory_bars(PLAIN, config, REG)


def test_config_tampered_block_refuses():
    block = _pin([_batch()])
    block["projection"] = dict(block["projection"], hma_period=999)
    with pytest.raises(FeatureInputRefused, match="B1f"):
        fi.feature_config(block)


def test_round_trip_real_config():
    cfg = _real_config()
    stored = _as_stored(cfg)
    block = _pin([_batch(snapshot=stored)], pin=fi.config_projection_hash(stored))
    rebuilt = fi.feature_config(block)
    assert rebuilt == cfg
    assert isinstance(rebuilt.hmm, HmmConfig)
    assert fi.config_projection_hash(dataclasses.asdict(rebuilt)) == block["projection_hash"]


def test_round_trip_hmm_none():
    cfg = _real_config(hmm=False)
    stored = _as_stored(cfg)
    block = _pin([_batch(snapshot=stored)], pin=fi.config_projection_hash(stored))
    rebuilt = fi.feature_config(block)
    assert rebuilt == cfg and rebuilt.hmm is None
    assert fi.config_projection_hash(dataclasses.asdict(rebuilt)) == block["projection_hash"]


@dataclasses.dataclass(frozen=True)
class _Inner:
    a: int
    b: tuple[int, ...]


@dataclasses.dataclass(frozen=True)
class _Outer:
    inner: _Inner
    pairs: tuple[tuple[int, int], ...]
    fixed: tuple[str, float]
    maybe: _Inner | None
    plain: dict


def test_round_trip_container_coercion():
    obj = _Outer(
        inner=_Inner(1, (2, 3)),
        pairs=((1, 2), (3, 4)),
        fixed=("x", 1.5),
        maybe=_Inner(4, ()),
        plain={"1h": 3},
    )
    stored = json.loads(json.dumps(dataclasses.asdict(obj)))
    assert fi._build(_Outer, stored) == obj


# ---------------------------------------------------------------------------
# warmup (B1g)
# ---------------------------------------------------------------------------


def test_warmup_mask_per_symbol_from_first_present_row():
    values = np.arange(12, dtype=np.float32).reshape(6, 2)
    present = np.ones((6, 2), dtype=bool)
    present[:2, 1] = False  # symbol 1 starts at row 2
    present[3, 0] = False  # a gap: not a present row
    values[~present] = np.nan
    out, counts = fi.warmup_mask(values, 2, present=present)
    assert np.isnan(out[[0, 1], 0]).all() and np.isfinite(out[2:3, 0]).all()
    assert np.isnan(out[[2, 3], 1]).all() and np.isfinite(out[4:, 1]).all()
    assert counts["masked_rows"] == 4 and counts["memory_bars"] == 2
    assert np.isfinite(values[0, 0])  # input not modified


def test_warmup_mask_idempotent():
    values = np.arange(20, dtype=np.float32).reshape(10, 2)
    present = np.ones_like(values, dtype=bool)
    once, _ = fi.warmup_mask(values, 3, present=present)
    twice, counts = fi.warmup_mask(once, 3, present=present)
    np.testing.assert_array_equal(once, twice)
    assert counts["masked_finite"] == 0


def test_warmup_mask_path_dependent_refuses():
    config = fi.feature_config(_pin([_batch()]))
    with pytest.raises(FeatureInputRefused, match="B1g"):
        fi.column_memory_bars(PATH_DEP, config, REG)
    with pytest.raises(FeatureInputRefused, match="B1g"):
        fi.refuse_path_dependent(PATH_DEP, REG)


# ---------------------------------------------------------------------------
# coverage (B1h)
# ---------------------------------------------------------------------------


def _coverage_case():
    values = np.full((4, 4), np.nan, dtype=np.float32)
    values[:, 0] = 1.0
    values[:, 1] = 2.0
    values[2, 2] = 3.0
    present = np.ones_like(values, dtype=bool)
    present[:, 3] = False  # no rows: not in the denominator
    return values, present, ["A", "B", "C", "D"]


def test_coverage_records_block():
    values, present, symbols = _coverage_case()
    block = fi.coverage_check(values, symbols, present=present, feature="f", tf="1d", floor=0.9)
    assert block["symbol_coverage"] == 1.0 and block["floor"] == 0.9
    assert block["n_symbols_with_rows"] == 3


def test_coverage_below_floor_refuses():
    values, present, symbols = _coverage_case()
    values[2, 2] = np.nan
    with pytest.raises(FeatureInputRefused, match="B1h"):
        fi.coverage_check(values, symbols, present=present, feature="f", tf="1d", floor=0.9)


def test_coverage_no_rows_refuses():
    values = np.full((2, 1), np.nan, dtype=np.float32)
    present = np.zeros_like(values, dtype=bool)
    with pytest.raises(FeatureInputRefused, match="B1h"):
        fi.coverage_check(values, ["A"], present=present, feature="f", tf="1d", floor=0.5)


# ---------------------------------------------------------------------------
# HMM regime columns (B1j)
# ---------------------------------------------------------------------------

HMM_COL = next(c for c in REG.feature_columns() if REG.by_output(c).origin == "regime")


def test_hmm_column_refused_on_old_writer():
    batches = [_batch("b1"), _batch("b2", writer="feature-vector-writer")]
    with pytest.raises(FeatureInputRefused, match="B1j"):
        fi.refuse_regime_columns([HMM_COL], REG, batches)


def test_hmm_column_refused_on_wrong_target():
    with pytest.raises(FeatureInputRefused, match="B1j"):
        fi.refuse_regime_columns([HMM_COL], REG, [_batch(target_table="feature_vectors")])


def test_hmm_column_refused_without_batches():
    with pytest.raises(FeatureInputRefused, match="B1j"):
        fi.refuse_regime_columns([HMM_COL], REG, [])


def test_hmm_column_passes_on_rebuild():
    fi.refuse_regime_columns([HMM_COL, PLAIN], REG, [_batch("b1"), _batch("b2")])


def test_hmm_non_regime_columns_ignore_writer():
    fi.refuse_regime_columns([PLAIN], REG, [_batch(writer="feature-vector-writer")])


# ---------------------------------------------------------------------------
# intraday vendors (B1d)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tf", ["15m", "1h"])
def test_vendor_intraday_non_derived_refuses(tf):
    with pytest.raises(FeatureInputRefused, match="B1d"):
        fi.check_intraday_vendors(tf, [("derived", "5m_grid"), ("ibkr", "trades")])


@pytest.mark.parametrize("tf", ["15m", "1h"])
def test_vendor_intraday_derived_passes(tf):
    assert fi.check_intraday_vendors(tf, [("derived", "5m_grid")] * 2) == [["derived", "5m_grid"]]


@pytest.mark.parametrize("tf", ["1d", "5m"])
def test_vendor_other_tfs_return_set(tf):
    pairs = [("ibkr", "trades"), ("alpaca", "sip"), ("ibkr", "trades")]
    assert fi.check_intraday_vendors(tf, pairs) == [["alpaca", "sip"], ["ibkr", "trades"]]


# ---------------------------------------------------------------------------
# content hash
# ---------------------------------------------------------------------------


def test_hash_feature_arrays_verify(tmp_path):
    name = fi.feature_array_name("1h", PLAIN)
    assert name == f"feature__1h__{PLAIN}"
    arrays = {name: np.arange(6, dtype=np.float32).reshape(3, 2)}
    path = store.write(tmp_path, "snap", arrays, {"k": 1})
    assert len(store.verify(path)) == 64
    raw = bytearray((path / f"{name}.npy").read_bytes())
    raw[-1] ^= 0xFF
    (path / f"{name}.npy").write_bytes(bytes(raw))
    with pytest.raises(ValueError, match="hash mismatch"):
        store.verify(path)
