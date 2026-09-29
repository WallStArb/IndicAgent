"""Byte-identical float32 parity against the golden fixture (186-08).

The fixture pins the output of the compute path as it stood before the feature_factory split.
186-12 and 186-15 repoint `kernel_parity_reference.compute_reference` at the registry path and
must keep this test green without touching the fixture (D-25).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from tests.unit.intelligence import kernel_parity_reference as ref

MANIFEST = ref.load_manifest()
CASES = MANIFEST["sample"]["cases"]
GOLDEN = json.loads((ref.FIXTURE_DIR / "real_golden.json").read_text())
NUMERIC = MANIFEST["numeric_columns"]
SYNTHETIC = CASES[0]
REAL_CASES = CASES[1:]


def _first_diff(a: np.ndarray, b: np.ndarray):
    a, b = a.astype(np.float32), b.astype(np.float32)
    bad = ~((a == b) | (np.isnan(a) & np.isnan(b)))
    if not bad.any():
        return None
    i = int(np.argmax(bad))
    return i, a[i], b[i]


def _check_text_and_ts(out: ref.ReferenceOutput, golden: dict, cid: str) -> None:
    assert len(out.bar_ts) == golden["rows"], f"{cid}: row count"
    digest = ref.digest_output(out)
    assert digest["bar_ts_sha256"] == golden["bar_ts_sha256"], f"{cid}: bar_ts digest"
    assert digest["text_columns"] == golden["text_columns"], f"{cid}: text columns"


def test_column_set_matches_manifest():
    out = ref.compute_reference(SYNTHETIC)
    assert list(out.columns) == NUMERIC
    assert sorted(out.text_columns) == sorted(c for c in MANIFEST["text_columns"] if c != "bar_ts")
    assert set(out.columns) | set(out.text_columns) | {"bar_ts"} == set(MANIFEST["columns"])


def test_synthetic_matches_golden_float32():
    golden = np.load(ref.FIXTURE_DIR / "synthetic_golden.npz")
    out = ref.compute_reference(SYNTHETIC)
    cid = ref.case_id(SYNTHETIC)
    _check_text_and_ts(out, GOLDEN[cid], cid)
    assert np.array_equal(out.bar_ts, golden["out/bar_ts"])
    matrix = golden["out/matrix"]
    for j, name in enumerate(NUMERIC):
        diff = _first_diff(out.columns[name], matrix[:, j])
        assert diff is None, f"{name}: row {diff[0]} got {diff[1]!r} golden {diff[2]!r}"


@pytest.mark.parametrize("case", REAL_CASES, ids=ref.case_id)
def test_real_sample_matches_golden_digests(case):
    cid = ref.case_id(case)
    out = ref.compute_reference(case)
    _check_text_and_ts(out, GOLDEN[cid], cid)
    assert list(out.columns) == NUMERIC
    sample = np.load(ref.FIXTURE_DIR / "real_golden_sample.npz")
    for j, name in enumerate(NUMERIC):
        if ref.digest_column(out.columns[name]) == GOLDEN[cid]["columns"][name]:
            continue
        rows = sample[f"{cid}/rows"]
        diff = _first_diff(out.columns[name][rows], sample[f"{cid}/matrix"][:, j])
        where = (
            "outside the 200-row sample"
            if diff is None
            else (f"sample row {rows[diff[0]]} got {diff[1]!r} golden {diff[2]!r}")
        )
        pytest.fail(f"{cid} column {name}: digest mismatch, {where}")
