"""Bit-identity check: rerun the frozen phase 179 (E14) S3 and phase 181 TSMOM S2/S3 artifacts
through the current research package and compare every recorded output exactly.

Run after any change to src/intelligence/research/ that must keep 1d results unchanged (e.g.
phase 183's R1 construction and R2 session scoring, both default-off):

    python -m scripts.research.determinism.repro_frozen <scratch_out_dir> [--logs DIR]

Reads the frozen artifacts under logs/phase179/rerun_e14 and logs/phase181 (local, not in git);
a worktree without its own logs/ resolves them to the main checkout automatically. Fields a
frozen artifact never recorded are reported and skipped, not compared. Frozen S3 pickles written
before the evaluate move name the pre-move module path and load through load_frozen, which
remaps that one path to the research package.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import hashlib
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.research.determinism.config import DEFAULT_CONFIG as CFG  # noqa: E402
from scripts.research.determinism.sessions import refit_dates  # noqa: E402
from scripts.research.determinism.signals import SIGNALS  # noqa: E402
from scripts.research.determinism.snapshot_io import (  # noqa: E402
    load_snapshot,
    verify_snapshot,
)
from services._batch_utils import make_worker_pool  # noqa: E402
from src.intelligence.research.evaluate import evaluate  # noqa: E402
from src.intelligence.research.panel import daily_panel, forward_returns  # noqa: E402

# The pre-move class path frozen S3 pickles embed (the 4-line shim evaluate.py existed only so
# these still load); load_frozen remaps exactly this module and nothing else.
_RENAMED_MODULES: dict[str, str] = {
    "scripts.analysis.sleeve_walk_forward.evaluate": "src.intelligence.research.evaluate",
}


class _RemappingUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        return super().find_class(_RENAMED_MODULES.get(module, module), name)


def load_frozen(path: Path):
    """Load a frozen artifact, remapping the old evaluate module path."""
    with open(path, "rb") as f:
        return _RemappingUnpickler(f).load()


def frozen_logs_dir(explicit: Path | None) -> Path:
    """The frozen artifacts' logs/ directory: the explicit path if given, else this repo's own
    logs/ when it holds phase181, else the main checkout's logs/ (parent of the common git dir),
    so a worktree needs no --logs."""
    if explicit is not None:
        return Path(explicit)
    own = REPO_ROOT / "logs"
    if (own / "phase181").exists():
        return own
    common_dir = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout.strip()
    return Path(common_dir).parent / "logs"


pool = functools.partial(make_worker_pool, blas_threads_per_worker=CFG.blas_threads_per_worker)


def same(a, b, path="result"):
    """Exact equality, recursing through dataclasses, dicts, sequences and arrays."""
    if b is None and a is not None:
        print(f"  not recorded in frozen artifact, skipped: {path}")
        return True
    if (
        isinstance(b, dict)
        and not b
        and isinstance(a, dict)
        and a
        and path.endswith("observed_weights")
    ):
        print(f"  not recorded in frozen artifact, skipped: {path}")
        return True
    if dataclasses.is_dataclass(a):
        return all(
            same(getattr(a, f.name), getattr(b, f.name, None), f"{path}.{f.name}")
            for f in dataclasses.fields(a)
        )
    if isinstance(a, dict):
        assert set(a) == set(b), (path, set(a) ^ set(b))
        return all(same(a[k], b[k], f"{path}[{k!r}]") for k in a)
    if isinstance(a, (list, tuple)) and not isinstance(a, str):
        assert len(a) == len(b), path
        return all(same(x, y, f"{path}[{i}]") for i, (x, y) in enumerate(zip(a, b)))
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        a, b = np.asarray(a), np.asarray(b)
        assert a.dtype == b.dtype and a.shape == b.shape, (path, a.dtype, b.dtype, a.shape, b.shape)
        assert np.array_equal(a, b, equal_nan=a.dtype.kind in "fc"), (path, "arrays differ")
        return True
    if isinstance(a, float) and np.isnan(a) and np.isnan(b):
        return True
    assert a == b, (path, a, b)
    return True


def evaluate_s2(s2, eval_kw):
    apr = s2["apr"]
    return evaluate(
        s2["alpha"],
        s2["fwd_ret"],
        s2["closes"],
        s2["dates"],
        CFG,
        mv_condition_max=float(apr.get(CFG.mv_condition_max_key, ("1000", "float"))[0]),
        ic_shrinkage_k=float(apr.get(CFG.ic_shrinkage_k_key, ("100", "float"))[0]),
        workers=8,
        pool_factory=pool,
        **eval_kw,
    )


def s2sig_payload(snapshot_dir: Path, signal: str) -> dict:
    """The inline s2sig stage (run.py:191-206 + _s2_payload, run.py:156-169): the S2-shaped
    panel the signal computes from the snapshot, with the same panel start as S2 so the shift
    set, warmup and trading window match phase 179's. No code key: the comparison ignores it."""
    verify_snapshot(snapshot_dir)
    snap = load_snapshot(snapshot_dir)
    panel = daily_panel(
        np.asarray(snap.sleeve_closes),
        dates=snap.sessions,
        opens=np.asarray(snap.sleeve_opens),
    )
    alpha = SIGNALS[signal].compute(panel)
    start = int(np.searchsorted(snap.sessions, refit_dates(snap.sessions, CFG.refit_years)[0]))
    years = snap.sessions[start:].astype("datetime64[Y]").astype(int) + 1970
    missing = ~np.isfinite(alpha[start:])
    counts = {int(y): {"no_signal": int(missing[years == y].sum())} for y in np.unique(years)}
    payload = {
        "snapshot": str(snapshot_dir),
        "signal": signal,
        "dates": snap.sessions[start:],
        "alpha": alpha[start:],
        "fwd_ret": forward_returns(np.asarray(snap.sleeve_opens))[start:],
        "closes": np.asarray(snap.sleeve_closes)[start:],
        "no_alpha_counts": counts,
        "apr": snap.apr,
    }
    # Round-trip through a pickle, matching the original's write-then-read through a file.
    return pickle.loads(pickle.dumps(payload))


def _save_s2sig(out_dir: Path, payload: dict) -> Path:
    data = pickle.dumps(payload)
    name = hashlib.sha256(data).hexdigest()[:16]
    path = Path(out_dir) / f"s2sig_{name}.pkl"
    path.write_bytes(data)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--logs", type=Path, default=None)
    args = parser.parse_args(argv)
    logs = frozen_logs_dir(args.logs)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Phase 179 E14 rerun: frozen S2 -> new evaluate vs frozen S3.
    s2 = load_frozen(logs / "phase179/rerun_e14/s2_3f452732054cd565.pkl")["payload"]
    frozen = load_frozen(logs / "phase179/rerun_e14/s3_4dead18ade3bde16.pkl")["payload"]["result"]
    same(evaluate_s2(s2, {"memory": CFG.shift_memory}), frozen)
    print("phase 179 S3: bit-identical", frozen.excess)

    # Phase 181 TSMOM: frozen snapshot -> new s2sig -> compare S2 payload; new S3 vs frozen S3.
    snap = logs / "phase181/snapshot_dc800360d369f4d5"
    new_payload = s2sig_payload(snap, "tsmom")
    _save_s2sig(args.out_dir, new_payload)
    old_payload = load_frozen(logs / "phase181/s2sig_02b09e153b9d21b4.pkl")["payload"]
    same(
        {k: v for k, v in new_payload.items() if k != "snapshot"},
        {k: v for k, v in old_payload.items() if k != "snapshot"},
        "s2sig",
    )
    print("phase 181 S2 (signal from Panel): bit-identical")
    frozen = load_frozen(logs / "phase181/s3_d3c9294661215c6d.pkl")["payload"]["result"]
    same(evaluate_s2(new_payload, SIGNALS["tsmom"].evaluate_kwargs()), frozen)
    print("phase 181 S3: bit-identical", frozen.excess)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
