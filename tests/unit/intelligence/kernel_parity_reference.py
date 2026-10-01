"""Reference compute path for the kernel parity fixture (186-08).

`compute_reference(case)` is the one entry point the parity test and the capture script call.
It runs today's compute path (`FeatureFactory.compute_batch`, and for real cases
`services.backfill_feature_factory._compute_symbol_tf` over a fake connection serving the
stored bars) and returns float32 columns in `_ALL_COLUMN_NAMES` order.

186-12 and 186-15 repoint `compute_reference` at the registry path. The golden files never
change in those plans: a behavior change is a separate commit that regenerates them with the
reason recorded (D-25).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "kernel_parity"

# Columns holding strings, UUIDs or datetimes; every other column must be None or a number.
# bar_ts is carried separately as `bar_ts`.
TEXT_COLUMNS = frozenset(
    {
        "feature_vector_id",
        "symbol",
        "tf",
        "pipeline_version",
        "feature_factory_version",
        "regime",
        "regime_label_source",
        "bar_close_ts",
    }
)
CROSS_ASSET_SYMBOLS = ("SPY", "TLT", "SHY", "TIP", "HYG", "LQD")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_NAN = np.float32("nan")


@dataclass
class ReferenceOutput:
    bar_ts: np.ndarray  # int64 UTC ns
    columns: dict[str, np.ndarray]  # float32
    text_columns: dict[str, list[str]]


def case_id(case: dict) -> str:
    return f"{case['kind']}|{case['symbol']}|{case['tf']}"


@lru_cache(maxsize=1)
def load_manifest(fixture_dir: Path = FIXTURE_DIR) -> dict:
    return json.loads((Path(fixture_dir) / "manifest.json").read_text())


def build_config(snapshot: dict):
    from src.intelligence.feature_factory import FeatureFactoryConfig

    return FeatureFactoryConfig(**snapshot)


def ns_to_dt(ns: int) -> datetime:
    return _EPOCH + timedelta(microseconds=int(ns) // 1000)


def dt_to_ns(value: datetime) -> int:
    return (value - _EPOCH) // timedelta(microseconds=1) * 1000


def _bars_from_arrays(ts, o, h, low, c, v) -> list[dict]:
    return [
        {
            "ts": ns_to_dt(ts[i]),
            "open": float(o[i]),
            "high": float(h[i]),
            "low": float(low[i]),
            "close": float(c[i]),
            "volume": float(v[i]),
        }
        for i in range(len(ts))
    ]


def _series_bars(npz: Any, prefix: str) -> list[dict]:
    g = lambda f: npz[f"{prefix}/{f}"]  # noqa: E731
    return _bars_from_arrays(g("ts"), g("open"), g("high"), g("low"), g("close"), g("volume"))


@lru_cache(maxsize=2)
def _load_npz(name: str, fixture_dir: Path = FIXTURE_DIR):
    return np.load(Path(fixture_dir) / name)


def synthetic_inputs(fixture_dir: Path = FIXTURE_DIR) -> tuple[dict[str, np.ndarray], Any]:
    """Synthetic bar arrays (ts int64 ns, ohlcv float64) and the synthetic config."""
    npz = _load_npz("synthetic_golden.npz", fixture_dir)
    inputs = {f: npz[f"in/{f}"] for f in ("ts", "open", "high", "low", "close", "volume")}
    return inputs, build_config(load_manifest(fixture_dir)["synthetic_config"])


def _to_output(columns: tuple[str, ...], rows: list[tuple]) -> ReferenceOutput:
    n = len(rows)
    bar_ts = np.array([dt_to_ns(r[columns.index("bar_ts")]) for r in rows], dtype=np.int64)
    numeric: dict[str, np.ndarray] = {}
    text: dict[str, list[str]] = {}
    for j, name in enumerate(columns):
        if name == "bar_ts":
            continue
        if name in TEXT_COLUMNS:
            text[name] = [str(r[j]) for r in rows]
            continue
        arr = np.full(n, _NAN, dtype=np.float32)
        for i, r in enumerate(rows):
            value = r[j]
            if value is None:
                continue
            if isinstance(value, (str, bytes, datetime)):
                raise TypeError(f"column {name!r} holds non-numeric {type(value).__name__}")
            with np.errstate(over="ignore"):
                arr[i] = np.float32(value)
        numeric[name] = arr
    return ReferenceOutput(bar_ts=bar_ts, columns=numeric, text_columns=text)


class _FakeCursor:
    def __init__(self, series: dict[tuple[str, str], list[dict]]):
        self._series = series
        self._result: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        if "market_data_ohlcv_tradeable" not in sql or len(params) != 2:
            raise AssertionError(f"unexpected SQL or params: {sql!r} {params!r}")
        key = (params[0], params[1])
        if key not in self._series:
            raise AssertionError(f"fixture holds no bars for {key}")
        self._result = [
            (b["ts"], b["open"], b["high"], b["low"], b["close"], b["volume"])
            for b in self._series[key]
        ]

    def fetchall(self):
        return self._result


class _FakeConnection:
    def __init__(self, series):
        self._series = series

    def cursor(self):
        return _FakeCursor(self._series)


def _compute_synthetic(case: dict, manifest: dict, fixture_dir: Path) -> ReferenceOutput:
    from src.intelligence.feature_factory import FEATURE_FACTORY_VERSION, FeatureFactory
    from src.intelligence.features.feature_vector_persistence import (
        _ALL_COLUMN_NAMES,
        feature_vector_to_insert_params,
    )
    from src.intelligence.features.kernels._cache_state import FeatureCache

    inputs, config = synthetic_inputs(fixture_dir)
    bars = _bars_from_arrays(*(inputs[f] for f in ("ts", "open", "high", "low", "close", "volume")))
    results = FeatureFactory.compute_batch(
        bars, case["symbol"], case["tf"], FeatureCache(), config, warm_up_bars=0
    )
    rows = [
        feature_vector_to_insert_params(
            symbol=case["symbol"],
            tf=case["tf"],
            bar_ts=ts,
            pipeline_version=manifest["pipeline_version"],
            feature_factory_version=FEATURE_FACTORY_VERSION,
            regime=None,
            regime_label_source="filtered",
            vector=fv,
        )
        for ts, fv in results
    ]
    return _to_output(_ALL_COLUMN_NAMES, rows)


def _compute_real(case: dict, manifest: dict, fixture_dir: Path) -> ReferenceOutput:
    from services.backfill_feature_factory import _compute_symbol_tf
    from src.intelligence.features.feature_vector_persistence import _ALL_COLUMN_NAMES
    from src.intelligence.features.kernels.macro import (
        build_cross_asset_series,
        build_symbol_beta_series,
    )

    npz = _load_npz("real_inputs.npz", fixture_dir)
    config = build_config(manifest["real_config"])
    symbol, tf = case["symbol"], case["tf"]
    d1 = {s: _series_bars(npz, f"d1/{s}") for s in {symbol, *CROSS_ASSET_SYMBOLS}}
    cross_asset_by_date = build_cross_asset_series(*(d1[s] for s in CROSS_ASSET_SYMBOLS), config)
    beta_by_date = build_symbol_beta_series(d1[symbol], d1["SPY"], d1["TLT"], symbol, config)
    series: dict[tuple[str, str], list[dict]] = {(symbol, "1d"): d1[symbol]}
    prefix = f"case/{symbol}/{tf}"
    if tf != "1d":
        series[(symbol, tf)] = _series_bars(npz, f"{prefix}/main")
    if f"{prefix}/htf/ts" in npz.files:
        series[(symbol, case["htf_tf"])] = _series_bars(npz, f"{prefix}/htf")
    if f"{prefix}/ltf/ts" in npz.files:
        series[(symbol, "1m")] = _series_bars(npz, f"{prefix}/ltf")
    rows = _compute_symbol_tf(
        conn=_FakeConnection(series),
        symbol=symbol,
        tf=tf,
        config=config,
        pipeline_version=manifest["pipeline_version"],
        warm_up_bars=manifest["warm_up_bars"],
        cross_asset_by_date=cross_asset_by_date,
        beta_by_date=beta_by_date,
        symbol_1d_bars=d1[symbol],
    )
    return _to_output(_ALL_COLUMN_NAMES, rows)


def compute_reference(case: dict, fixture_dir: Path = FIXTURE_DIR) -> ReferenceOutput:
    manifest = load_manifest(fixture_dir)
    if case["kind"] == "synthetic":
        return _compute_synthetic(case, manifest, fixture_dir)
    if case["kind"] == "real":
        return _compute_real(case, manifest, fixture_dir)
    raise ValueError(f"unknown case kind {case['kind']!r}")


def canonical_float32(values: np.ndarray) -> np.ndarray:
    """NaN to one bit pattern and -0.0 to 0.0, so equal digests mean array_equal(equal_nan)."""
    arr = np.asarray(values, dtype=np.float32)
    arr = np.where(np.isnan(arr), _NAN, arr).astype(np.float32)
    return (arr + np.float32(0.0)).astype("<f4")


def digest_column(values: np.ndarray) -> str:
    return hashlib.sha256(canonical_float32(values).tobytes()).hexdigest()


def digest_text(values: list[str]) -> str:
    return hashlib.sha256("\n".join(values).encode()).hexdigest()


def digest_output(out: ReferenceOutput) -> dict:
    return {
        "rows": int(len(out.bar_ts)),
        "bar_ts_sha256": hashlib.sha256(out.bar_ts.astype("<i8").tobytes()).hexdigest(),
        "columns": {k: digest_column(v) for k, v in out.columns.items()},
        "text_columns": {k: digest_text(v) for k, v in out.text_columns.items()},
    }
