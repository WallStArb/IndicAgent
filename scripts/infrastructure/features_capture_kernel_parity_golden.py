"""Capture the golden float32 output of the current feature compute path (186-08).

Read-only: SELECTs from `market_data_ohlcv_tradeable` and `config_state`, writes only under
`--out`. Freezes what `FeatureFactory.compute_batch` and `_compute_symbol_tf` produce today so
the feature_factory split (186-12, 186-15) can prove byte-identical parity. The fixture is
regenerated only in a commit of its own that states the reason (D-25).

Sample (fixed before capture): symbols SPY, QQQ, TLT, XLE; timeframes 5m, 15m, 1h, 1d; every
window ends before 2026-06-20. Intraday cases fetch 1,200 output bars plus the warm-up; 1d
fetches the last 1,500 bars; higher-timeframe bars (1h for 5m and 15m) are the last 600 bars
up to the window end; 1m bars for the 5m ret_div feature span the 5m window; 1d bars for the
four symbols and SHY, TIP, HYG, LQD feed the cross-asset and beta series.

Usage: python scripts/infrastructure/features_capture_kernel_parity_golden.py [--dry-run]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.infrastructure._capture_common import git_head  # noqa: E402
from services.backfill_feature_factory import (  # noqa: E402
    _build_feature_factory_config,
    _load_config_service,
)
from src.config.settings import Settings  # noqa: E402
from src.intelligence.features.feature_vector_persistence import _ALL_COLUMN_NAMES  # noqa: E402
from tests.unit.intelligence import kernel_parity_reference as ref  # noqa: E402
from tests.unit.intelligence.test_feature_factory_batch_parity import (  # noqa: E402
    N as SYNTHETIC_N,
)
from tests.unit.intelligence.test_feature_factory_batch_parity import _make_cfg  # noqa: E402

END_BOUND = "2026-06-20"
SYMBOLS = ("SPY", "QQQ", "TLT", "XLE")
TIMEFRAMES = ("5m", "15m", "1h", "1d")
D1_SYMBOLS = (*SYMBOLS, "SHY", "TIP", "HYG", "LQD")
INTRADAY_OUTPUT_BARS = 1200
D1_BARS = 1500
HTF_BARS = 600
PIPELINE_VERSION = "3.0.0"
SAMPLE_ROWS = 200

_SQL_LAST = """
SELECT timestamp, open, high, low, close, volume FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = %s AND timestamp < %s
ORDER BY timestamp DESC LIMIT %s
"""
_SQL_LAST_UPTO = """
SELECT timestamp, open, high, low, close, volume FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = %s AND timestamp <= %s
ORDER BY timestamp DESC LIMIT %s
"""
_SQL_SPAN = """
SELECT timestamp, open, high, low, close, volume FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = %s AND timestamp >= %s AND timestamp <= %s
ORDER BY timestamp ASC
"""


def _arrays(rows: list[tuple], *, reverse: bool) -> dict[str, np.ndarray]:
    if reverse:
        rows = rows[::-1]
    ts = np.array(
        [ref.dt_to_ns(r[0] if r[0].tzinfo else r[0].replace(tzinfo=UTC)) for r in rows],
        dtype=np.int64,
    )
    out = {"ts": ts}
    for i, name in enumerate(("open", "high", "low", "close", "volume"), start=1):
        out[name] = np.array([float(r[i]) for r in rows], dtype=np.float64)
    return out


def _put(store: dict, prefix: str, arrays: dict[str, np.ndarray]) -> None:
    for name, arr in arrays.items():
        store[f"{prefix}/{name}"] = arr


def _fetch_inputs(conn, warm_up_bars: int, htf_map: dict) -> tuple[dict, list[dict]]:
    store: dict[str, np.ndarray] = {}
    cases: list[dict] = []
    with conn.cursor() as cur:
        for symbol in D1_SYMBOLS:
            cur.execute(_SQL_LAST, (symbol, "1d", END_BOUND, D1_BARS))
            _put(store, f"d1/{symbol}", _arrays(cur.fetchall(), reverse=True))
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                case = {"kind": "real", "symbol": symbol, "tf": tf, "htf_tf": htf_map.get(tf)}
                prefix = f"case/{symbol}/{tf}"
                if tf == "1d":
                    main = {
                        k[len(f"d1/{symbol}/") :]: v
                        for k, v in store.items()
                        if k.startswith(f"d1/{symbol}/")
                    }
                else:
                    cur.execute(
                        _SQL_LAST,
                        (symbol, tf, END_BOUND, INTRADAY_OUTPUT_BARS + warm_up_bars),
                    )
                    main = _arrays(cur.fetchall(), reverse=True)
                    _put(store, f"{prefix}/main", main)
                first_ns, last_ns = int(main["ts"][0]), int(main["ts"][-1])
                first_dt, last_dt = ref.ns_to_dt(first_ns), ref.ns_to_dt(last_ns)
                if case["htf_tf"] and case["htf_tf"] != "1d":
                    cur.execute(_SQL_LAST_UPTO, (symbol, case["htf_tf"], last_dt, HTF_BARS))
                    _put(store, f"{prefix}/htf", _arrays(cur.fetchall(), reverse=True))
                if tf == "5m":
                    cur.execute(_SQL_SPAN, (symbol, "1m", first_dt, last_dt))
                    ltf = _arrays(cur.fetchall(), reverse=False)
                    if len(ltf["ts"]):
                        _put(store, f"{prefix}/ltf", ltf)
                case["main_bars"] = int(len(main["ts"]))
                case["window_start_utc"] = first_dt.isoformat()
                case["window_end_utc"] = last_dt.isoformat()
                cases.append(case)
    return store, cases


def _synthetic_inputs() -> dict[str, np.ndarray]:
    """500 bars, seed 42, same generator order as test_feature_factory_batch_parity."""
    rng = np.random.default_rng(42)
    n = SYNTHETIC_N
    closes = np.cumprod(1.0 + rng.normal(0, 0.005, n)) * 100.0
    spread = closes * rng.uniform(0.001, 0.008, n)
    highs = closes + spread
    lows = closes - spread
    opens = closes + rng.normal(0, 0.003, n) * closes
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    volumes = rng.uniform(1e5, 1e7, n)
    base = ref.dt_to_ns(datetime(2023, 1, 3, 14, 30, tzinfo=UTC))
    ts = base + np.arange(n, dtype=np.int64) * 5 * 60 * 1_000_000_000
    return {
        "ts": ts,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }


def _matrix(out: ref.ReferenceOutput, names: list[str]) -> np.ndarray:
    return np.stack([out.columns[n] for n in names], axis=1)


def _clear_caches() -> None:
    ref.load_manifest.cache_clear()
    ref._load_npz.cache_clear()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="tests/fixtures/kernel_parity")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    out_dir = (REPO_ROOT / args.out).resolve()

    with psycopg.connect(Settings().database_url) as conn:
        conn.autocommit = True
        config = _build_feature_factory_config(_load_config_service(conn))
        warm_up_bars = config.momentum_zscore_window
        real_config = dataclasses.asdict(config)
        assert build_equal(real_config, config), "config snapshot does not round-trip"
        store, real_cases = _fetch_inputs(conn, warm_up_bars, config.ctf_higher_tf_map)

    for case in real_cases:
        print(case)
    if args.dry_run:
        print(f"dry run: {len(real_cases)} real cases, warm_up_bars={warm_up_bars}")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    synth_cfg = _make_cfg()
    synthetic = _synthetic_inputs()
    cases = [{"kind": "synthetic", "symbol": "SPY", "tf": "5m"}] + real_cases
    manifest = {
        "capture_commit": git_head(),
        "capture_utc": datetime.now(UTC).isoformat(),
        "pipeline_version": PIPELINE_VERSION,
        "warm_up_bars": warm_up_bars,
        "real_config": json.loads(json.dumps(real_config)),
        "synthetic_config": json.loads(json.dumps(dataclasses.asdict(synth_cfg))),
        "columns": list(_ALL_COLUMN_NAMES),
        "sample": {
            "end_bound_utc": END_BOUND,
            "symbols": list(SYMBOLS),
            "timeframes": list(TIMEFRAMES),
            "d1_symbols": list(D1_SYMBOLS),
            "intraday_output_bars": INTRADAY_OUTPUT_BARS,
            "d1_bars": D1_BARS,
            "htf_bars": HTF_BARS,
            "substitutions": [],
            "cases": cases,
        },
    }
    np.savez_compressed(
        out_dir / "synthetic_golden.npz", **{f"in/{k}": v for k, v in synthetic.items()}
    )
    np.savez_compressed(out_dir / "real_inputs.npz", **store)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    _clear_caches()

    digests: dict[str, dict] = {}
    outputs: dict[str, ref.ReferenceOutput] = {}
    unstable: list[str] = []
    for case in cases:
        cid = ref.case_id(case)
        first = ref.compute_reference(case, out_dir)
        second = ref.compute_reference(case, out_dir)
        d1, d2 = ref.digest_output(first), ref.digest_output(second)
        if d1 != d2:
            unstable.append(cid)
            cols = [c for c in d1["columns"] if d1["columns"][c] != d2["columns"].get(c)]
            print(f"NON-DETERMINISTIC {cid}: {cols}", file=sys.stderr)
        digests[cid] = d1
        outputs[cid] = first
        print(f"{cid}: rows={d1['rows']}")
    if unstable:
        print(f"refusing to freeze: {unstable}", file=sys.stderr)
        return 1

    numeric = [c for c in _ALL_COLUMN_NAMES if c in outputs[ref.case_id(cases[0])].columns]
    manifest["numeric_columns"] = numeric
    manifest["text_columns"] = sorted(ref.TEXT_COLUMNS)
    manifest["row_counts"] = {cid: d["rows"] for cid, d in digests.items()}

    synth_out = outputs[ref.case_id(cases[0])]
    payload = {f"in/{k}": v for k, v in synthetic.items()}
    payload["out/matrix"] = _matrix(synth_out, numeric)
    payload["out/bar_ts"] = synth_out.bar_ts
    np.savez_compressed(out_dir / "synthetic_golden.npz", **payload)

    sample: dict[str, np.ndarray] = {}
    for cid, out in outputs.items():
        if cid == ref.case_id(cases[0]):
            continue
        n = len(out.bar_ts)
        rows = np.unique(np.linspace(0, n - 1, SAMPLE_ROWS).astype(np.int64))
        sample[f"{cid}/rows"] = rows
        sample[f"{cid}/matrix"] = _matrix(out, numeric)[rows]
    np.savez_compressed(out_dir / "real_golden_sample.npz", **sample)
    (out_dir / "real_golden.json").write_text(json.dumps(digests, indent=1, sort_keys=True))

    manifest["fixture_bytes"] = sum(p.stat().st_size for p in out_dir.iterdir() if p.is_file())
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"fixture bytes: {manifest['fixture_bytes']}")
    return 0


def build_equal(snapshot: dict, config) -> bool:
    return type(config)(**json.loads(json.dumps(snapshot))) == config


if __name__ == "__main__":
    raise SystemExit(main())
