"""ops_cutover_review.py: the per-name gate before the first d2-v2 apply (plan 185-38). Pure."""

from __future__ import annotations

from scripts.ops.bars import ops_cutover_review as review_module


def _row(symbol, *, stored=1000, removed=0, refused_interior=0, head=0, refused_head=0):
    return {
        "symbol": symbol,
        "n_stored": str(stored),
        "removed": str(removed),
        "refused_interior": str(refused_interior),
        "head": str(head),
        "refused_head": str(refused_head),
    }


def _review(rows, exceptions=frozenset()):
    return review_module.review(rows, exceptions, max_removed=0.005, max_refused=0.005)


def test_clean_names_pass():
    assert _review([_row("A"), _row("B", removed=5, refused_interior=5, head=100)]) == []


def test_each_measure_over_its_limit_fails_and_names_the_symbol():
    findings = _review(
        [
            _row("W", removed=6),
            _row("BNO", refused_interior=6),
            _row("XLY", head=0, refused_head=300),
            _row("SIL", head=199, refused_head=1),
        ]
    )
    assert [(f.symbol, f.measure) for f in findings] == [
        ("W", "removed"),
        ("BNO", "refused_interior"),
        ("XLY", "refused_head"),
    ]
    assert "XLY" in str(findings[2])


def test_an_exception_row_clears_the_name():
    assert _review([_row("W", removed=900)], exceptions=frozenset({"W"})) == []


def test_no_stored_rows_and_no_heads_measure_zero():
    assert _review([_row("NEW", stored=0)]) == []


def test_a_report_without_the_refused_head_column_is_refused(tmp_path):
    old = tmp_path / "old.tsv"
    old.write_text("symbol\tn_stored\tremoved\nA\t1\t0\n")
    assert review_module.main([str(old)]) == 1
