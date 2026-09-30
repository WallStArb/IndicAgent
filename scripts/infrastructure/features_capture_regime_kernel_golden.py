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
  (default)      capture from the database through the registry kernels and write the
                 fixture. Each case runs twice and the capture refuses on nondeterminism. (The
                 first capture, at commit ec3d8a814, ran the unchanged writer functions
                 through a fake connection; the manifest's `source` says which path wrote a
                 fixture, and the kernels reproduced it byte for byte before the writer's own
                 compute functions were deleted.)
  --verify       recompute every stored case through the kernels from `real_inputs.npz` and
                 the manifest's APR snapshot (no database read) and compare digests.
  --dump PATH    write the kernels' current per-row state (code, status, columns) to PATH.
  --regenerate   like --verify, but writes the recomputed digests and arrays (the golden
                 regeneration commit); needs --reason and --changed-from, a --dump taken
                 before the change, from which the manifest's flip report is computed.
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


def run_kernel_full(
    apr: dict[str, Any], bars: dict[str, np.ndarray], family: str, tf: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(code, segment status, numeric columns as float32) from the registry kernels."""
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
        default_registry(),
        inputs,
        config,
        outputs=[spec.code_output, spec.status_output, *spec.numeric_outputs],
    )
    columns = np.stack([np.asarray(out[name], dtype=np.float32) for name in spec.numeric_outputs])
    return (
        np.asarray(out[spec.code_output], dtype=np.float64),
        np.asarray(out[spec.status_output], dtype=np.float64),
        columns,
    )


def run_kernel_case(
    apr: dict[str, Any], bars: dict[str, np.ndarray], family: str, tf: str
) -> tuple[np.ndarray, np.ndarray]:
    """Label indices (int8, -1 unwritten) and numeric columns from the registry kernels."""
    code, _status, columns = run_kernel_full(apr, bars, family, tf)
    return np.where(np.isnan(code), -1.0, code).astype(np.int8), columns


def _all_cases(out: Path) -> list[tuple[str, dict[str, np.ndarray], str, dict[str, Any]]]:
    manifest = json.loads((out / "manifest.json").read_text())
    cases = [
        (name, bars, name.split("/")[1], manifest["apr_snapshot"])
        for name, bars in load_real_inputs(out).items()
    ]
    cases.append(("synthetic", load_synthetic(out), "1d", SMALL_HMM_APR))
    return cases


def dump_state(out: Path, path: Path) -> None:
    """Every case and family's code, segment status and numeric columns from the kernels as
    they are now, keyed `<case>|<family>|code|status|c0..c6`. Run it before and after a
    behavior change; `--regenerate --changed-from` compares the two."""
    arrays: dict[str, np.ndarray] = {}
    for name, bars, tf, apr in _all_cases(out):
        for family in FAMILIES:
            code, status, columns = run_kernel_full(apr, bars, family, tf)
            arrays[f"{name}|{family}|code"] = code
            arrays[f"{name}|{family}|status"] = status
            for c in range(N_NUMERIC_COLUMNS):
                arrays[f"{name}|{family}|c{c}"] = columns[c]
    np.savez(path, **arrays)


def change_report(pre_path: Path, post_path: Path, out: Path) -> dict[str, Any]:
    """Per case and family: the refit segments whose gate verdict flipped, rows that gained or
    lost a label, and per-column changed-row counts, in total and outside the flipped segments
    (only the duration column may differ outside them, in the first written run after a flip)."""
    pre, post = np.load(pre_path), np.load(post_path)
    report: dict[str, Any] = {}
    for name, _bars, tf, apr in _all_cases(out):
        refit = int(apr[f"alpha.hmm.walk_forward.refit_every_bars.{tf}"])
        for family in FAMILIES:
            key = f"{name}|{family}"
            s_pre, s_post = pre[f"{key}|status"], post[f"{key}|status"]
            n = len(s_pre)
            written = np.flatnonzero((s_pre > 0) | (s_post > 0))
            first = int(written[0]) if len(written) else None
            flipped: list[list] = []
            flip_rows = np.zeros(n, dtype=bool)
            lost = gained = 0
            lo = first
            while lo is not None and lo < n:
                hi = min(lo + refit, n)
                was, now = s_pre[lo] == 1.0, s_post[lo] == 1.0
                if was != now:
                    flipped.append([lo, hi, "written->skipped" if was else "skipped->written"])
                    flip_rows[lo:hi] = True
                    lost, gained = lost + (hi - lo) * was, gained + (hi - lo) * now
                lo = hi
            changed = []
            for c in range(N_NUMERIC_COLUMNS):
                x, y = pre[f"{key}|c{c}"], post[f"{key}|c{c}"]
                diff = ~((x == y) | (np.isnan(x) & np.isnan(y)))
                changed.append([int(diff.sum()), int((diff & ~flip_rows).sum())])
            report[f"{name}/{family}"] = {
                "flipped_segments": flipped,
                "rows_lost_label": int(lost),
                "rows_gained_label": int(gained),
                "columns_changed_rows_total_and_outside_flipped": changed,
            }
    return report


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


def _case_digests(apr, bars_by_case, synthetic, *, twice: bool):
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
            grid = run_kernel_case(case_apr, bars, family, tf)
            runtimes[key] = round(time.monotonic() - t0, 2)
            if twice:
                bad = _same(grid, run_kernel_case(case_apr, bars, family, tf))
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
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--regenerate", action="store_true")
    parser.add_argument("--reason", default="")
    parser.add_argument("--dump", type=Path, help="write the kernels' current state to this npz")
    parser.add_argument(
        "--changed-from",
        type=Path,
        help="a --dump from before the change; --regenerate records the flip report against it",
    )
    args = parser.parse_args()
    out: Path = args.out
    # Production runs the HMM in pool workers capped to one BLAS thread (limit_blas_threads).
    # The thread count changes the low bits of the fit and, with several threads, differs run
    # to run, so the golden is defined at one thread.
    import threadpoolctl

    threadpoolctl.threadpool_limits(1)

    if args.dump:
        dump_state(out, args.dump)
        print(f"wrote {args.dump}")
        return

    if args.verify or args.regenerate:
        manifest = json.loads((out / "manifest.json").read_text())
        apr = manifest["apr_snapshot"]
        bars_by_case = load_real_inputs(out)
        synthetic = load_synthetic(out)
        digests, grids, runtimes = _case_digests(apr, bars_by_case, synthetic, twice=False)
        stored = json.loads((out / "real_golden.json").read_text())
        stored.update(manifest["synthetic_digests"])
        if args.verify:
            bad = [k for k in digests if digests[k] != stored.get(k)]
            if bad:
                raise SystemExit("VERIFY FAILED: digests differ for " + ", ".join(bad))
            print(f"VERIFY OK: {len(digests)} case/family digests match the stored golden")
            return
        if not args.reason or not args.changed_from:
            raise SystemExit("--regenerate needs --reason and --changed-from")
        post_dump = out.parent / "_regime_post_dump.npz"
        dump_state(out, post_dump)
        try:
            report = change_report(args.changed_from, post_dump, out)
        finally:
            post_dump.unlink(missing_ok=True)
        changed = {k: digests[k]["rows_written"] for k in digests if digests[k] != stored.get(k)}
        manifest["regenerated_from"] = _git_head()
        manifest["regeneration_reason"] = args.reason
        manifest["changed_cases"] = {
            case: {"rows_written_now": rows, **report[case]} for case, rows in changed.items()
        }
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
    digests, grids, runtimes = _case_digests(apr, bars_by_case, synthetic, twice=True)
    manifest = {
        "capture_commit": _git_head(),
        "captured_utc": datetime.now(UTC).isoformat(),
        "source": "kernel",
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
