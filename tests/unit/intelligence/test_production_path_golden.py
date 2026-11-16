"""The production feature path against real-data golden digests (R2 item 1).

The corpus rerun computes `feature_vectors` through `_series_kernel_inputs` and
`_compute_series_columns` (one `compute_kernels` call from the series start, declared-warmup and
none masks, float32 clamp). `production_golden.json` pins that path over the stored real cases;
regenerate it with `features_capture_kernel_parity_golden --production --reason ...` in a commit
of its own, never inside a refactor. The legacy batch path it was once checked against
(`FeatureFactory.compute_batch`, equal after each column's declared warmup except the three
regime-model columns) was deleted in R2 item 2 after that equality held on every stored case.
"""

from __future__ import annotations

import json

import pytest

from tests.unit.intelligence import kernel_parity_reference as ref

MANIFEST = ref.load_manifest()
GOLDEN = json.loads((ref.FIXTURE_DIR / "production_golden.json").read_text())["cases"]
REAL_CASES = [c for c in MANIFEST["sample"]["cases"] if c["kind"] == "real"]


@pytest.mark.parametrize("case", REAL_CASES, ids=ref.case_id)
def test_production_path_matches_its_golden_digests(case):
    cid = ref.case_id(case)
    digest = ref.digest_output(ref.compute_production(case))
    golden = GOLDEN[cid]
    assert digest["rows"] == golden["rows"], f"{cid}: row count"
    assert digest["bar_ts_sha256"] == golden["bar_ts_sha256"], f"{cid}: bar_ts digest"
    assert sorted(digest["columns"]) == sorted(golden["columns"]), f"{cid}: column set"
    changed = [c for c, d in digest["columns"].items() if d != golden["columns"][c]]
    assert not changed, f"{cid}: {len(changed)} column digest(s) moved, first {changed[:5]}"
