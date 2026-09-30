"""Capture and verify the walk-forward HMM regime golden (186-13).

Read-only: the capture mode SELECTs from `market_data_ohlcv_tradeable` and `config_state` and
writes only under `--out`. Freezes what the walk-forward regime compute produces so the move of
the HMM from services/regime_writer.py into the registry kernels can be proved byte-identical
(D-25). The fixture is regenerated only in a commit of its own that states the reason.

Sample (fixed before capture): SPY, TLT and LQD at 1d over full history (LQD is degenerate at
every timeframe per the writer docstring, so it exercises the skip path) and SPY at 1h over full
history. Both families (trend `regime`, `regime_volatility`) run on each case. A synthetic case
(`make_synthetic_regime_bars(3000, 42)` under SMALL_HMM_APR at the 1d schedule) is written to
`synthetic_golden.npz`.

BLAS is limited to one thread (as production's worker pool does); several threads are not run
to run reproducible.

Modes:
  (default)      capture from the database through the compute path named by --source and
                 write the fixture. `--source writer` runs the unchanged writer functions
                 through a fake connection that serves only the two bar SELECT shapes;
                 `--source kernel` runs the registry kernels. Each case runs twice and the
                 capture refuses on nondeterminism.
  --verify       recompute every stored case through the kernels from `real_inputs.npz` and
                 the manifest's APR snapshot (no database read) and compare digests.
  --regenerate   like --verify, but writes the recomputed digests and arrays (the golden
                 regeneration commit); needs --reason.
  --dry-run      capture without writing.

Usage: python scripts/infrastructure/features_capture_regime_kernel_golden.py [--out DIR]
"""

from __future__ import annotations

import os

# Production runs the HMM in pool workers capped to one BLAS thread (limit_blas_threads). The
# thread count changes the low bits of the fit and, with several threads, differs run to run
# (measured: SPY 1d trend probabilities), so the golden is defined at one thread. The variables
# must be set before numpy and scipy load their BLAS.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_var] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tests.unit.intelligence.regime_kernel_fixtures import (  # noqa: E402
    FAMILY_LABELS,
    N_NUMERIC_COLUMNS,
    SMALL_HMM_APR,
    digest_case,
    make_synthetic_regime_bars,
)

DEFAULT_OUT = REPO_ROOT / "tests" / "fixtures" / "regime_kernel"
SAMPLE: tuple[tuple[str, str], ...] = (
    ("SPY", "1d"),
    ("TLT", "1d"),
    ("LQD", "1d"),
    ("SPY", "1h"),
)
FAMILIES = ("trend", "volatility")

# The writer's own APR fallbacks (main() in services/regime_writer.py), key -> fallback.
_WRITER_FALLBACKS: dict[str, Any] = {
    "feature.hmm.n_components": 3,
    "feature.hmm.vol_window": 20,
    "feature.hmm.n_iter": 200,
    "alpha.hmm.random_state": 42,
    "feature.hmm.obs_momentum_window": 20,
    "feature.hmm.obs_vol_of_vol_window": 20,
    "feature.hmm.covariance_type": "full",
    "feature.hmm.min_hold_bars": 3,
    "feature.hmm.full_cov_min_obs": 500,
    "feature.hmm.min_state_occupation": 0.05,
    "feature.hmm.churn_window": 10,
    "feature.hmm.min_obs_factor": 50,
    "alpha.hmm_volatility.n_components": 3,
    "alpha.hmm_volatility.vol_window": 20,
    "alpha.hmm_volatility.vol_of_vol_window": 60,
    "alpha.hmm_volatility.covariance_type": "full",
    "alpha.hmm.walk_forward.refit_every_bars.5m": 19800,
    "alpha.hmm.walk_forward.initial_warmup_bars.5m": 39600,
    "alpha.hmm.walk_forward.refit_every_bars.15m": 6600,
    "alpha.hmm.walk_forward.initial_warmup_bars.15m": 13200,
    "alpha.hmm.walk_forward.refit_every_bars.1h": 1650,
    "alpha.hmm.walk_forward.initial_warmup_bars.1h": 3300,
    "alpha.hmm.walk_forward.refit_every_bars.1d": 252,
    "alpha.hmm.walk_forward.initial_warmup_bars.1d": 504,
}

_SQL_SPAN = "SELECT timestamp, close, volume FROM market_data_ohlcv_tradeable WHERE symbol = %s AND timeframe = %s ORDER BY timestamp ASC"


def snapshot_apr(cfg: Any) -> dict[str, Any]:
    """Every HMM APR key through ConfigService, with the writer's fallbacks."""
    return {key: cfg.get_sync(key, fallback) for key, fallback in _WRITER_FALLBACKS.items()}


def _ns_to_dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns // 1_000_000_000, tz=UTC)


class _FakeCursor:
    """Serves the writer's two bar SELECT shapes from stored arrays; anything else raises."""

    def __init__(self, bars: dict[str, np.ndarray]):
        self._bars = bars
        self._rows: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: tuple):
        text = " ".join(sql.split())
        if not text.startswith("SELECT timestamp, close"):
            raise AssertionError(f"fake connection got an unexpected statement: {text!r}")
        ts, close, volume = self._bars["ts"], self._bars["close"], self._bars["volume"]
        if "volume" in text:
            self._rows = [
                (_ns_to_dt(int(t)), float(c), float(v)) for t, c, v in zip(ts, close, volume)
            ]
        else:
            self._rows = [(_ns_to_dt(int(t)), float(c)) for t, c in zip(ts, close)]

    def fetchmany(self, n: int):
        out, self._rows = self._rows[:n], self._rows[n:]
        return out


class _FakeConnection:
    def __init__(self, bars: dict[str, np.ndarray]):
        self._bars = bars

    def commit(self):
        return None

    def cursor(self, name: str | None = None):
        return _FakeCursor(self._bars)


def _schedule(apr: dict[str, Any], tf: str) -> tuple[int, int]:
    return (
        int(apr[f"alpha.hmm.walk_forward.refit_every_bars.{tf}"]),
        int(apr[f"alpha.hmm.walk_forward.initial_warmup_bars.{tf}"]),
    )


def run_writer_case(
    apr: dict[str, Any], bars: dict[str, np.ndarray], family: str, tf: str
) -> list[tuple] | None:
    """The unchanged writer's walk-forward function for one family, through a fake connection."""
    from services import regime_writer as rw

    refit, warmup = _schedule(apr, tf)
    conn = _FakeConnection(bars)
    common = dict(
        conn=conn,
        symbol="CASE",
        tf=tf,
        n_iter=int(apr["feature.hmm.n_iter"]),
        hmm_random_state=int(apr["alpha.hmm.random_state"]),
        refit_every_bars=refit,
        initial_warmup_bars=warmup,
        min_hold_bars=int(apr["feature.hmm.min_hold_bars"]),
        full_cov_min_obs=int(apr["feature.hmm.full_cov_min_obs"]),
        min_state_occupation=float(apr["feature.hmm.min_state_occupation"]),
        churn_window=int(apr["feature.hmm.churn_window"]),
        min_obs_factor=int(apr["feature.hmm.min_obs_factor"]),
    )
    if family == "trend":
        result = rw._compute_symbol_tf_walk_forward(
            n_components=int(apr["feature.hmm.n_components"]),
            vol_window=int(apr["feature.hmm.vol_window"]),
            momentum_window=int(apr["feature.hmm.obs_momentum_window"]),
            vol_of_vol_window=int(apr["feature.hmm.obs_vol_of_vol_window"]),
            covariance_type=str(apr["feature.hmm.covariance_type"]),
            **common,
        )
    else:
        result = rw._compute_symbol_tf_volatility_walk_forward(
            n_components=int(apr["alpha.hmm_volatility.n_components"]),
            vol_window=int(apr["alpha.hmm_volatility.vol_window"]),
            vol_of_vol_window=int(apr["alpha.hmm_volatility.vol_of_vol_window"]),
            covariance_type=str(apr["alpha.hmm_volatility.covariance_type"]),
            **common,
        )
    return None if result is None else result[0]


def rows_to_grid(
    update_rows: list[tuple] | None, ts_ns: np.ndarray, family: str
) -> tuple[np.ndarray, np.ndarray]:
    """Label indices (int8, -1 unwritten) and the 7 numeric columns (float32, NaN unwritten)
    on the bar grid, from the writer's update rows."""
    labels_order = FAMILY_LABELS[family]
    n = len(ts_ns)
    labels = np.full(n, -1, dtype=np.int8)
    columns = np.full((N_NUMERIC_COLUMNS, n), np.nan, dtype=np.float32)
    if not update_rows:
        return labels, columns
    position = {int(t): i for i, t in enumerate(ts_ns)}
    for row in update_rows:
        i = position[int(row[-1].timestamp()) * 1_000_000_000]
        labels[i] = labels_order.index(row[0])
        for c in range(N_NUMERIC_COLUMNS):
            columns[c, i] = np.float32(row[1 + c])
    return labels, columns


def run_kernel_case(
    apr: dict[str, Any], bars: dict[str, np.ndarray], family: str, tf: str
) -> tuple[np.ndarray, np.ndarray]:
    """Label indices and numeric columns from the registry kernels, on the same grid."""
    from src.intelligence.features.contract.registry import compute_kernels, default_registry
    from src.intelligence.features.kernels import regime as regime_kernels

    fields = regime_kernels.hmm_config_fields_from_values(
        lambda key, default: apr.get(key, default)
    )
    config = SimpleNamespace(**fields)
    spec = regime_kernels.FAMILY_KERNELS[family]
    n = len(bars["ts"])
    inputs = {
        "ts": bars["ts"],
        "close": bars["close"],
        "volume": bars["volume"],
        "tf": np.array([tf] * n, dtype=object),
    }
    out = compute_kernels(
        default_registry(), inputs, config, outputs=[spec.code_output, *spec.numeric_outputs]
    )
    code = np.asarray(out[spec.code_output], dtype=np.float64)
    labels = np.where(np.isnan(code), -1.0, code).astype(np.int8)
    columns = np.stack([np.asarray(out[name], dtype=np.float32) for name in spec.numeric_outputs])
    return labels, columns


def _run_twice(fn, *args) -> tuple[np.ndarray, np.ndarray, float]:
    t0 = time.monotonic()
    first = fn(*args)
    elapsed = time.monotonic() - t0
    second = fn(*args)
    return first, second, elapsed


def _same(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray]) -> list[str]:
    bad = []
    if not np.array_equal(a[0], b[0]):
        bad.append("labels")
    for c in range(N_NUMERIC_COLUMNS):
        x = np.ascontiguousarray(a[1][c]).view(np.uint32)
        y = np.ascontiguousarray(b[1][c]).view(np.uint32)
        nan_a, nan_b = np.isnan(a[1][c]), np.isnan(b[1][c])
        if not (np.array_equal(nan_a, nan_b) and np.array_equal(x[~nan_a], y[~nan_b])):
            bad.append(f"column_{c}")
    return bad


def _grid_from(source: str, apr, bars, family, tf) -> tuple[np.ndarray, np.ndarray]:
    if source == "writer":
        return rows_to_grid(run_writer_case(apr, bars, family, tf), bars["ts"], family)
    return run_kernel_case(apr, bars, family, tf)


def _fetch_real_bars(dsn: str) -> dict[str, dict[str, np.ndarray]]:
    import psycopg

    out: dict[str, dict[str, np.ndarray]] = {}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for symbol, tf in SAMPLE:
            cur.execute(_SQL_SPAN, (symbol, tf))
            rows = cur.fetchall()
            out[f"{symbol}/{tf}"] = {
                "ts": np.array(
                    [int(r[0].timestamp()) * 1_000_000_000 for r in rows], dtype=np.int64
                ),
                "close": np.array([float(r[1]) for r in rows], dtype=np.float64),
                "volume": np.array([float(r[2]) for r in rows], dtype=np.float64),
            }
    return out


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO_ROOT, check=True
    ).stdout.strip()


def _case_digests(source, apr, bars_by_case, synthetic, *, twice: bool):
    """(digests per case/family, grids, runtimes)."""
    digests: dict[str, Any] = {}
    grids: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    runtimes: dict[str, float] = {}
    problems: list[str] = []
    cases = [(name, bars, name.split("/")[1]) for name, bars in bars_by_case.items()]
    cases.append(("synthetic", synthetic, "1d"))
    for name, bars, tf in cases:
        case_apr = SMALL_HMM_APR if name == "synthetic" else apr
        for family in FAMILIES:
            key = f"{name}/{family}"
            t0 = time.monotonic()
            grid = _grid_from(source, case_apr, bars, family, tf)
            runtimes[key] = round(time.monotonic() - t0, 2)
            if twice:
                bad = _same(grid, _grid_from(source, case_apr, bars, family, tf))
                if bad:
                    problems.append(f"{key}: nondeterministic in {bad}")
            grids[key] = grid
            digests[key] = digest_case(*grid)
            print(f"{key}: {digests[key]['rows_written']} rows, {runtimes[key]} s", flush=True)
    if problems:
        raise SystemExit("nondeterministic capture, refusing to write:\n" + "\n".join(problems))
    return digests, grids, runtimes


def _write_fixture(out: Path, manifest: dict, digests: dict, bars_by_case, synthetic, grids):
    out.mkdir(parents=True, exist_ok=True)
    inputs: dict[str, np.ndarray] = {}
    for name, bars in bars_by_case.items():
        for field, arr in bars.items():
            inputs[f"{name}/{field}"] = arr
    np.savez_compressed(out / "real_inputs.npz", **inputs)
    (out / "real_golden.json").write_text(
        json.dumps(
            {
                k: v
                for k, v in digests.items()
                if k != "synthetic/trend" and k != "synthetic/volatility"
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    synth: dict[str, np.ndarray] = {f"input/{k}": v for k, v in synthetic.items()}
    for family in FAMILIES:
        labels, columns = grids[f"synthetic/{family}"]
        synth[f"{family}/labels"] = labels
        synth[f"{family}/columns"] = columns
    np.savez_compressed(out / "synthetic_golden.npz", **synth)
    manifest["synthetic_digests"] = {
        f"synthetic/{family}": digests[f"synthetic/{family}"] for family in FAMILIES
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def load_real_inputs(out: Path) -> dict[str, dict[str, np.ndarray]]:
    data = np.load(out / "real_inputs.npz")
    cases: dict[str, dict[str, np.ndarray]] = {}
    for key in data.files:
        name, field = key.rsplit("/", 1)
        cases.setdefault(name, {})[field] = data[key]
    return cases


def load_synthetic(out: Path) -> dict[str, np.ndarray]:
    data = np.load(out / "synthetic_golden.npz")
    return {k[len("input/") :]: data[k] for k in data.files if k.startswith("input/")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--source", choices=["writer", "kernel"], default="writer")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--regenerate", action="store_true")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    out: Path = args.out
    # Production runs the HMM in pool workers capped to one BLAS thread (limit_blas_threads).
    # The thread count changes the low bits of the fit and, with several threads, differs run
    # to run, so the golden is defined at one thread.
    import threadpoolctl

    threadpoolctl.threadpool_limits(1)

    if args.verify or args.regenerate:
        manifest = json.loads((out / "manifest.json").read_text())
        apr = manifest["apr_snapshot"]
        bars_by_case = load_real_inputs(out)
        synthetic = load_synthetic(out)
        digests, grids, runtimes = _case_digests(
            "kernel", apr, bars_by_case, synthetic, twice=False
        )
        stored = json.loads((out / "real_golden.json").read_text())
        stored.update(manifest["synthetic_digests"])
        if args.verify:
            bad = [k for k in digests if digests[k] != stored.get(k)]
            if bad:
                raise SystemExit("VERIFY FAILED: digests differ for " + ", ".join(bad))
            print(f"VERIFY OK: {len(digests)} case/family digests match the stored golden")
            return
        if not args.reason:
            raise SystemExit("--regenerate needs --reason")
        changed = {k: digests[k]["rows_written"] for k in digests if digests[k] != stored.get(k)}
        manifest["regenerated_from"] = _git_head()
        manifest["regeneration_reason"] = args.reason
        manifest["changed_cases"] = changed
        manifest["runtime_seconds"] = runtimes
        _write_fixture(out, manifest, digests, bars_by_case, synthetic, grids)
        print("regenerated; changed cases:", sorted(changed))
        return

    import psycopg

    from services._batch_utils import load_config_service_sync
    from src.config.settings import Settings

    dsn = Settings().database_url
    with psycopg.connect(dsn) as conn:
        apr = snapshot_apr(load_config_service_sync(conn))
    bars_by_case = _fetch_real_bars(dsn)
    synthetic = make_synthetic_regime_bars(3000, 42)
    digests, grids, runtimes = _case_digests(args.source, apr, bars_by_case, synthetic, twice=True)
    manifest = {
        "capture_commit": _git_head(),
        "captured_utc": datetime.now(UTC).isoformat(),
        "source": args.source,
        "apr_snapshot": apr,
        "synthetic_apr": SMALL_HMM_APR,
        "sample": [list(s) for s in SAMPLE],
        "family_labels": {k: list(v) for k, v in FAMILY_LABELS.items()},
        "bar_counts": {k: int(len(v["ts"])) for k, v in bars_by_case.items()},
        "runtime_seconds": runtimes,
    }
    if args.dry_run:
        print("dry run, nothing written")
        return
    _write_fixture(out, manifest, digests, bars_by_case, synthetic, grids)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
