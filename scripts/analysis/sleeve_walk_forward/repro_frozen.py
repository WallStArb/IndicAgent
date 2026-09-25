"""Bit-identity check: rerun the frozen phase 179 (E14) S3 and phase 181 TSMOM S2/S3 artifacts
through the current research package and compare every recorded output exactly.

Run after any change to src/intelligence/research/ that must keep 1d results unchanged (e.g.
phase 183's R1 construction and R2 session scoring, both default-off):

    python scripts/analysis/sleeve_walk_forward/repro_frozen.py <scratch_out_dir> [--logs DIR]

Reads the frozen artifacts under logs/phase179/rerun_e14 and logs/phase181 (local, not in git).
Fields a frozen artifact never recorded are reported and skipped, not compared.
"""

import dataclasses
import functools
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
from scripts.analysis.sleeve_walk_forward import run
from scripts.analysis.sleeve_walk_forward.config import DEFAULT_CONFIG as CFG
from scripts.analysis.sleeve_walk_forward.signals import SIGNALS
from services._batch_utils import make_worker_pool
from src.intelligence.research.evaluate import evaluate

REPO_LOGS = Path(__file__).resolve().parents[3] / "logs"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else None
# Frozen artifacts live in the main checkout's logs/ (not in git); pass --logs DIR from a worktree.
MAIN = Path(sys.argv[sys.argv.index("--logs") + 1]) if "--logs" in sys.argv else REPO_LOGS
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


def main():
    # Phase 179 E14 rerun: frozen S2 -> new evaluate vs frozen S3.
    s2 = pickle.loads((MAIN / "phase179/rerun_e14/s2_3f452732054cd565.pkl").read_bytes())["payload"]
    frozen = pickle.loads((MAIN / "phase179/rerun_e14/s3_4dead18ade3bde16.pkl").read_bytes())[
        "payload"
    ]["result"]
    same(evaluate_s2(s2, {"memory": CFG.shift_memory}), frozen)
    print("phase 179 S3: bit-identical", frozen.excess)

    # Phase 181 TSMOM: frozen snapshot -> new s2sig -> compare S2 payload; new S3 vs frozen S3.
    snap = MAIN / "phase181/snapshot_dc800360d369f4d5"
    s2_new = run.main(
        ["--stage", "s2sig", "--signal", "tsmom", "--in", str(snap), "--out-dir", str(OUT)]
    )
    new_payload = pickle.loads(s2_new.read_bytes())["payload"]
    old_payload = pickle.loads((MAIN / "phase181/s2sig_02b09e153b9d21b4.pkl").read_bytes())[
        "payload"
    ]
    same(
        {k: v for k, v in new_payload.items() if k != "snapshot"},
        {k: v for k, v in old_payload.items() if k != "snapshot"},
        "s2sig",
    )
    print("phase 181 S2 (signal from Panel): bit-identical")
    frozen = pickle.loads((MAIN / "phase181/s3_d3c9294661215c6d.pkl").read_bytes())["payload"][
        "result"
    ]
    same(evaluate_s2(new_payload, SIGNALS["tsmom"].evaluate_kwargs()), frozen)
    print("phase 181 S3: bit-identical", frozen.excess)


if __name__ == "__main__":
    main()
