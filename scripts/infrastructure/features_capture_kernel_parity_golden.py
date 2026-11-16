"""Capture the production feature path's golden digests (R2 item 1, trimmed in R2 item 2).

Writes `tests/fixtures/kernel_parity/production_golden.json`: the digests of the path the corpus
rerun runs (`_series_kernel_inputs` and `_compute_series_columns`) over the stored real cases of
`real_inputs.npz`. No fetch, no database. The golden is regenerated only in a commit of its own
that states the reason: a refactor never regenerates it (a refactor leaves every digest equal).

The legacy golden (`real_golden.json`, `synthetic_golden.npz`) and the batch path that produced it
(`FeatureFactory.compute_batch`) were deleted in R2 item 2, after the production path was shown
equal to it after each column's declared warmup on every stored case.

Usage: python scripts/infrastructure/features_capture_kernel_parity_golden.py \
           --production --reason "why the golden changes"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.infrastructure._capture_common import git_head  # noqa: E402
from tests.unit.intelligence import kernel_parity_reference as ref  # noqa: E402


def regenerate_production(out_dir: Path, reason: str) -> int:
    """Digest the production path over the stored real cases into `production_golden.json`."""
    manifest = json.loads((out_dir / "manifest.json").read_text())
    cases = [c for c in manifest["sample"]["cases"] if c["kind"] == "real"]
    digests = {ref.case_id(c): ref.digest_output(ref.compute_production(c, out_dir)) for c in cases}
    record = {
        "reason": reason,
        "capture_commit": git_head(),
        "hmm": "SMALL_HMM_APR of tests/unit/intelligence/regime_kernel_fixtures.py",
        "cases": digests,
    }
    (out_dir / "production_golden.json").write_text(json.dumps(record, indent=1) + "\n")
    columns = sum(len(d["columns"]) for d in digests.values())
    print(f"production golden: {len(digests)} cases, {columns} columns")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="tests/fixtures/kernel_parity")
    parser.add_argument("--production", action="store_true", required=True)
    parser.add_argument("--reason", required=True, help="why the golden changes")
    args = parser.parse_args()
    return regenerate_production((REPO_ROOT / args.out).resolve(), args.reason)


if __name__ == "__main__":
    raise SystemExit(main())
