"""Phase 179 harness CLI: one stage per call, artifacts passed by content hash.

    python -m scripts.analysis.sleeve_walk_forward.run --stage s0 --out-dir DIR
    python -m scripts.analysis.sleeve_walk_forward.run --stage s1 --in DIR/snapshot_<h> \
        --out-dir DIR --excluded-file excluded.json [--workers N]
    ... --stage s2 --in s1_<h>.pkl   ... --stage s3 --in s2_<h>.pkl [--workers N]
    ... --stage s4 --in s3_<h>.pkl --fidelity OK|BROKEN
    ... --stage v2|v3 --out-dir DIR [--workers N] [--signal NAME]
    ... --stage s2sig --signal NAME --in DIR/snapshot_<h> --out-dir DIR

s2sig writes an S2-shaped artifact from a parameter-free signal source (signals.SIGNALS) over the
snapshot's sleeve closes, so S3/S4 run on it unchanged; it has no refit and no V4. v2/v3 with
--signal compute that signal from synthetic prices. S3 and S4 carry the signal's name, and s4
takes N_tested from the signal source (its pre-registration's number).

Each stage writes <stage>_<sha256[:16]>.pkl holding its payload, its parent's path and the code
commit, and prints the path. A stage refuses a parent built at a different commit unless
--allow-code-drift is given, so a frozen run can't mix code versions. S1's exclusion list is
required: the pre-registration's section 5 exclusions are never optional. The ledger row and
concept_registry row are written by build step 8, not here.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import pickle
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import structlog

from scripts.analysis.sleeve_walk_forward.config import DEFAULT_CONFIG
from scripts.analysis.sleeve_walk_forward.evaluate import evaluate
from scripts.analysis.sleeve_walk_forward.refit import run_refit
from scripts.analysis.sleeve_walk_forward.results import Snapshot
from scripts.analysis.sleeve_walk_forward.score import forward_returns, score_panel
from scripts.analysis.sleeve_walk_forward.sessions import refit_dates
from scripts.analysis.sleeve_walk_forward.signals import SIGNALS
from scripts.analysis.sleeve_walk_forward.snapshot import (
    build_snapshot,
    load_snapshot,
    verify_snapshot,
)
from scripts.analysis.sleeve_walk_forward.synthetic import run_v2, run_v3
from scripts.analysis.sleeve_walk_forward.verdict import decide, safe_evaluate
from services._batch_utils import make_worker_pool
from services.ic_engine import _checkpoint_content_key
from src.config.settings import Settings

CONFIG = DEFAULT_CONFIG
_JOB = "sleeve-walk-forward"
_logger = structlog.get_logger(__name__)


# Harness code outside src/ and services/, which _checkpoint_content_key does not hash.
_HARNESS_SOURCES: tuple[Path, ...] = (
    *sorted(Path(__file__).parent.glob("*.py")),
    Path(__file__).parents[2] / "ops" / "alpha" / "ops_ic_shrinkage.py",
)


def _code_key() -> str:
    """ic_engine's checkpoint key (AST-normalized hash of the first-party src/ and services/
    modules loaded) plus a hash of the harness's own sources, so a semantic change anywhere on
    the path moves it and an unrelated commit does not."""
    digest = hashlib.sha256(_checkpoint_content_key().encode())
    for path in _HARNESS_SOURCES:
        digest.update(path.name.encode())
        digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def _git() -> tuple[str, bool]:
    """HEAD and whether the tree is dirty, recorded for the section 12 addendum."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    status = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    )
    return head.stdout.strip(), bool(status.stdout.strip())


def _save(out_dir: Path, stage: str, payload: Any, parent: str) -> Path:
    """Artifact named by the hash of its content (stage, parent, code key, payload). The git
    commit and dirty flag are stored for the addendum but kept out of the hash, so the same
    inputs under the same code get the same name whatever the working tree's state."""
    content = {"stage": stage, "parent": parent, "code_key": _code_key(), "payload": payload}
    name = hashlib.sha256(pickle.dumps(content)).hexdigest()[:16]
    commit, dirty = _git()
    path = Path(out_dir) / f"{stage}_{name}.pkl"
    path.write_bytes(pickle.dumps({**content, "git_commit": commit, "git_dirty": dirty}))
    return path


def _load(path: Path, allow_drift: bool) -> dict:
    obj = pickle.loads(Path(path).read_bytes())
    if obj["code_key"] != _code_key() and not allow_drift:
        sys.exit(
            f"{path} was built under code {obj['code_key'][:10]}, current code is "
            f"{_code_key()[:10]}; pass --allow-code-drift to use it anyway"
        )
    return obj


_WORKER_SNAPSHOT: dict[str, Any] = {}


def _refit_worker(
    snapshot_path: str, date: np.datetime64, excluded: frozenset[str], controls: frozenset[str]
):
    """Loads the snapshot once per worker process, not once per refit."""
    if snapshot_path not in _WORKER_SNAPSHOT:
        _WORKER_SNAPSHOT.clear()
        _WORKER_SNAPSHOT[snapshot_path] = load_snapshot(Path(snapshot_path))
    return run_refit(_WORKER_SNAPSHOT[snapshot_path], date, CONFIG, excluded, controls)


def _stage_s1(args: argparse.Namespace) -> Path:
    if args.excluded_file is None:
        sys.exit("--excluded-file is required for s1 (pre-registration section 5)")
    tiers = json.loads(Path(args.excluded_file).read_text())
    if not isinstance(tiers, dict) or set(tiers) != {"exclude", "control"}:
        sys.exit('--excluded-file must be {"exclude": {name: reason}, "control": {name: reason}}')
    excluded, controls = frozenset(tiers["exclude"]), frozenset(tiers["control"])
    verify_snapshot(Path(args.input))
    snap = load_snapshot(Path(args.input))
    unknown = sorted((excluded | controls) - set(snap.feature_names))
    if unknown:
        sys.exit(f"--excluded-file names features that don't exist: {unknown}")
    dates = refit_dates(snap.sessions, CONFIG.refit_years)
    jobs = [(str(args.input), d, excluded, controls) for d in dates]
    if args.workers > 1:
        with make_worker_pool(args.workers, CONFIG.blas_threads_per_worker) as pool:
            refits = list(pool.map(_refit_worker, *zip(*jobs)))
    else:
        refits = [_refit_worker(*j) for j in jobs]
    payload = {
        "snapshot": str(args.input),
        "excluded": sorted(excluded),
        "controls": sorted(controls),
        "refits": refits,
    }
    return _save(args.out_dir, "s1", payload, str(args.input))


def _s2_payload(
    snap: Snapshot, start: int, alpha: np.ndarray, counts: dict, snapshot: str, **extra: Any
) -> dict:
    """The S2-shaped panel S3 reads: every array from the panel's first session on."""
    return {
        "snapshot": snapshot,
        **extra,
        "dates": snap.sessions[start:],
        "alpha": alpha[start:],
        "fwd_ret": forward_returns(np.asarray(snap.sleeve_opens))[start:],
        "closes": np.asarray(snap.sleeve_closes)[start:],
        "no_alpha_counts": counts,
        "apr": snap.apr,
    }


def _stage_s2(args: argparse.Namespace) -> Path:
    s1 = _load(args.input, args.allow_code_drift)["payload"]
    snap = load_snapshot(Path(s1["snapshot"]))
    refits = s1["refits"]
    alpha, counts = score_panel(
        refits,
        snap.sleeve_features,
        snap.sleeve_has_row,
        {f: i for i, f in enumerate(snap.feature_names)},
        snap.equity_labels,
        snap.sessions,
        [r.refit_date for r in refits],
        snap.sessions[-1],
    )
    start = int(np.searchsorted(snap.sessions, refits[0].refit_date))
    payload = _s2_payload(snap, start, alpha, counts, s1["snapshot"])
    return _save(args.out_dir, "s2", payload, str(args.input))


def _stage_s2sig(args: argparse.Namespace) -> Path:
    verify_snapshot(Path(args.input))
    snap = load_snapshot(Path(args.input))
    alpha = SIGNALS[args.signal].compute(np.asarray(snap.sleeve_closes))
    # Same panel start as S2, so the shift set, warmup and trading window match phase 179's.
    start = int(np.searchsorted(snap.sessions, refit_dates(snap.sessions, CONFIG.refit_years)[0]))
    years = snap.sessions[start:].astype("datetime64[Y]").astype(int) + 1970
    missing = ~np.isfinite(alpha[start:])
    counts = {int(y): {"no_signal": int(missing[years == y].sum())} for y in np.unique(years)}
    payload = _s2_payload(snap, start, alpha, counts, str(args.input), signal=args.signal)
    return _save(args.out_dir, "s2sig", payload, str(args.input))


def _stage_s3(args: argparse.Namespace) -> Path:
    s2 = _load(args.input, args.allow_code_drift)["payload"]
    apr = s2["apr"]
    signal = s2.get("signal")  # None: phase 179's calibrated arms
    eval_kw = {} if signal is None else SIGNALS[signal].evaluate_kwargs()
    t0 = time.monotonic()
    res, error = safe_evaluate(
        evaluate,
        s2["alpha"],
        s2["fwd_ret"],
        s2["closes"],
        s2["dates"],
        CONFIG,
        mv_condition_max=float(apr.get(CONFIG.mv_condition_max_key, ("1000", "float"))[0]),
        ic_shrinkage_k=float(apr.get(CONFIG.ic_shrinkage_k_key, ("100", "float"))[0]),
        workers=args.workers,
        **eval_kw,
    )
    seconds = time.monotonic() - t0
    n_shifts = 0 if res is None else len(res.shifts)
    _logger.info(
        "sleeve_walk_forward.s3_done", seconds=round(seconds, 1), n_shifts=n_shifts, error=error
    )
    payload = {"result": res, "error": error, "seconds": seconds}
    if signal is not None:
        payload["signal"] = signal
    return _save(args.out_dir, "s3", payload, str(args.input))


def _stage_s4(args: argparse.Namespace) -> Path:
    s3 = _load(args.input, args.allow_code_drift)["payload"]
    fidelity_ok = args.fidelity == "OK" and s3["error"] is None
    signal = s3.get("signal")
    if s3["result"] is None:
        verdict = {"sleeve_verdict": None, "fidelity": "BROKEN", "reason": s3["error"]}
    else:
        # A signal source's pre-registration pins its own N_tested.
        cfg = (
            CONFIG
            if signal is None
            else dataclasses.replace(CONFIG, n_tested=SIGNALS[signal].n_tested)
        )
        verdict = decide(s3["result"], cfg, fidelity_ok=fidelity_ok)
        verdict["diagnostics"] = s3["result"].diagnostics  # section 11, reported only
    if signal is not None:
        verdict.update(signal=signal, n_tested=SIGNALS[signal].n_tested)
    path = _save(args.out_dir, "s4", verdict, str(args.input))
    path.with_suffix(".json").write_text(json.dumps(verdict, indent=2, default=str))
    return path


def _stage_s0(args: argparse.Namespace) -> Path:
    return asyncio.run(
        build_snapshot(
            args.dsn or Settings().database_url.replace("postgresql+asyncpg://", "postgresql://"),
            Path(args.out_dir),
            sleeve=CONFIG.sleeve,
            start=CONFIG.training_start,
            end_exclusive=args.end_exclusive,
        )
    )


def _stage_v(args: argparse.Namespace) -> Path:
    panel_kw = {} if args.signal is None else {"alpha_kind": args.signal}
    if args.stage == "v2":
        payload = run_v2(range(200), n_shifts=199, workers=args.workers, cfg=CONFIG, **panel_kw)
    else:
        payload = run_v3(
            (0.6, 0.8), range(200), n_shifts=199, workers=args.workers, cfg=CONFIG, **panel_kw
        )
    if args.signal is not None:
        payload = {"signal": args.signal, "result": payload}
    path = _save(args.out_dir, args.stage, payload, "")
    path.with_suffix(".json").write_text(json.dumps(payload, indent=2, default=str))
    return path


_STAGES = {
    "s0": _stage_s0,
    "s1": _stage_s1,
    "s2": _stage_s2,
    "s2sig": _stage_s2sig,
    "s3": _stage_s3,
    "s4": _stage_s4,
    "v2": _stage_v,
    "v3": _stage_v,
}


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--stage", required=True, choices=sorted(_STAGES))
    parser.add_argument("--in", dest="input", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--excluded-file", type=Path)
    parser.add_argument("--fidelity", choices=("OK", "BROKEN"))
    parser.add_argument("--allow-code-drift", action="store_true")
    parser.add_argument("--dsn", default=None, help="default: Settings().database_url")
    parser.add_argument("--signal", choices=sorted(SIGNALS))
    parser.add_argument("--end-exclusive", default="2025-12-24T05:15:00+00:00")
    args = parser.parse_args(argv)
    if args.stage in {"s1", "s2", "s2sig", "s3", "s4"} and args.input is None:
        parser.error(f"--in is required for {args.stage}")
    if args.stage == "s2sig" and args.signal is None:
        parser.error("--signal is required for s2sig")
    if args.stage == "s4" and args.fidelity is None:
        parser.error("--fidelity is required for s4 (V1, V4 and V5 decide it)")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = _STAGES[args.stage](args)
    print(path)
    return path


def _cli() -> int:
    from src.core.service_utils import setup_service_logging
    from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

    setup_service_logging("logs/sleeve_walk_forward.log")
    status = "failure"
    try:
        main()
        status = "success"
        return 0
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    sys.exit(_cli())
