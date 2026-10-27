"""E17 fitted-book admission (plan 187-08 Task 3)."""

import pytest

from scripts.research.certify_fitted_books import book_cells, record_sessions
from src.intelligence.research import certificate as cert


def _holds(*cells):
    level = {"rejected": 50, "bound": 67, "holds": True}
    return {c: {"0.05": level, "0.01": {**level, "bound": 18, "rejected": 10}} for c in cells}


FP = {"x.py:f": "abc"}
RIDGE = {"window_sessions": 252, "refit_sessions": 21, "penalty": 1.0, "min_obs": 10_000}
GOOD = {
    "schema": cert.SCHEMA,
    "sessions": cert.REAL_SESSIONS,
    "code": FP,
    "ridge": RIDGE,
    "cells": _holds("ridge", "ridge_static", "kappa_0.2", "kappa_0.2_static"),
}


def test_required_cells():
    assert cert.required_cells("equal_weight", None) == ()
    assert cert.required_cells("ridge", None) == ("ridge", "ridge_static")
    assert cert.required_cells("equal_weight", 0.2) == ("kappa_0.2", "kappa_0.2_static")
    assert cert.required_cells("ridge", 0.5) == ("ridge_kappa",)  # nothing certifies it


def test_unfitted_books_and_synthetic_mode_are_always_open():
    assert cert.fitted_book_refusal("equal_weight", None, "real", None, FP) is None
    assert cert.fitted_book_refusal("ridge", 0.5, "synthetic", None, FP) is None


def test_a_certified_combination_is_admitted():
    assert cert.fitted_book_refusal("ridge", None, "real", GOOD, FP, RIDGE) is None
    assert cert.fitted_book_refusal("equal_weight", 0.2, "exploration", GOOD, FP) is None


@pytest.mark.parametrize(
    "certificate, kappa, word",
    [
        (None, None, "no E17 fitted-book certificate"),
        ({**GOOD, "schema": "old"}, None, "schema"),
        ({**GOOD, "sessions": 1500}, None, "1500 sessions"),
        ({**GOOD, "code": {"x.py:f": "changed"}}, None, "changed since the battery ran"),
        (GOOD, 0.5, "no certified battery cell kappa_0.5"),
        (
            {**GOOD, "cells": {**GOOD["cells"], "ridge_static": {"0.05": {"holds": False}}}},
            None,
            "ridge_static exceeds size at 0.05, 0.01",
        ),
    ],
)
def test_refusals(certificate, kappa, word):
    kind = "ridge" if kappa is None else "equal_weight"
    assert word in cert.fitted_book_refusal(kind, kappa, "real", certificate, FP, RIDGE)


def test_a_ridge_book_off_the_certified_configuration_is_refused():
    other = {**RIDGE, "window_sessions": 5}
    assert "not the certified" in cert.fitted_book_refusal("ridge", None, "real", GOOD, FP, other)


def test_fingerprint_hashes_named_code_only():
    src = "import os\n\n\ndef f():\n    return 1\n\n\ndef g():\n    return 2\n"
    edited_g = src.replace("return 2", "return 3")
    edited_f = src.replace("return 1", "return 4")
    entries = (("m.py", "f"),)
    orig = cert.CERTIFIED_CODE

    try:
        cert.CERTIFIED_CODE = entries
        a = cert.code_fingerprint(lambda p: src)
        assert cert.code_fingerprint(lambda p: edited_g) == a  # an unrelated edit
        assert cert.code_fingerprint(lambda p: edited_f) != a  # an edit to the certified code
    finally:
        cert.CERTIFIED_CODE = orig


def test_segments_include_decorators_and_constants():
    src = "import dataclasses\n\nCUT = 1e-3\n\n\n@dataclasses.dataclass(frozen=True)\nclass R:\n    k: float = 1.0\n"
    assert cert._segment(src, "CUT") == "CUT = 1e-3"
    assert cert._segment(src, "R").startswith("@dataclasses.dataclass(frozen=True)")
    with pytest.raises(LookupError):
        cert._segment(src, "missing")


def test_the_running_code_fingerprints():
    fp = cert.working_tree_fingerprint()
    assert set(fp) == {f"{p}:{n or '*'}" for p, n in cert.CERTIFIED_CODE}


def test_certificate_cells_come_from_book_arms():
    record = {
        "scenarios": [{"sessions": 4000}, {"sessions": 4000}],
        "report": [
            {"cell": "ridge", "arm": "mean1", "levels": {"0.05": {"rejected": 90, "bound": 67}}},
            {
                "cell": "ridge",
                "arm": "book_ridge_k1",
                "levels": {"0.05": {"rejected": 68, "bound": 67}},
            },
        ],
    }
    assert book_cells(record) == {"ridge": {"0.05": {"rejected": 68, "bound": 67, "holds": False}}}
    assert record_sessions(record) == 4000
