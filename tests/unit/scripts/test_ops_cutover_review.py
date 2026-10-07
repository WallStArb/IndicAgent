"""ops_cutover_review.py: the per-name gate before the first d2-v2 apply (plan 185-38). Pure."""

from __future__ import annotations

from scripts.ops.bars import ops_cutover_review as review_module


def _row(
    symbol,
    *,
    stored=1000,
    removed=0,
    refused_interior=0,
    head=0,
    refused_head=0,
    changed=0,
    source_only=0,
    group="tradier_only",
):
    return {
        "symbol": symbol,
        "group": group,
        "changed": str(changed),
        "changed_source_only": str(source_only),
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


def test_removed_share_over_its_limit_fails_and_names_the_symbol():
    findings = _review([_row("W", removed=6), _row("OK", removed=5)])
    assert [(f.symbol, f.measure) for f in findings] == [("W", "removed")]
    assert "W" in str(findings[0])


def test_refused_only_names_pass_and_are_reported_informational():
    # Orchestrator decision 2026-10-07 (SIL, BNO): a refusal that removes nothing stored
    # loses or alters no data; it is reported, not gated.
    rows = [
        _row("BNO", refused_interior=6),
        _row("SIL", head=0, refused_head=300),
    ]
    assert _review(rows) == []
    info = review_module.informational(rows, max_refused=0.005)
    assert [(f.symbol, f.measure) for f in info] == [
        ("BNO", "refused_interior"),
        ("SIL", "refused_head"),
    ]


def test_value_changes_on_a_tradier_or_mixed_series_fail_over_the_limit():
    findings = _review(
        [
            _row("ALTERED", changed=10, source_only=2, group="mixed"),
            _row("RELABEL", changed=400, source_only=400, group="mixed"),
        ]
    )
    assert [(f.symbol, f.measure) for f in findings] == [("ALTERED", "changed")]


def test_an_admitted_ibkr_only_switch_is_not_gated_on_changes():
    # The admission sweep's evidence is the review for an IBKR-only name moving to Tradier.
    assert _review([_row("AA", changed=1000, group="ibkr_only")]) == []
    # Removals still gate it.
    findings = _review([_row("BRBR", changed=1000, removed=594, group="ibkr_only")])
    assert [(f.symbol, f.measure) for f in findings] == [("BRBR", "removed")]


def test_an_exception_row_clears_the_name():
    assert _review([_row("W", removed=900)], exceptions=frozenset({"W"})) == []


def test_no_stored_rows_and_no_heads_measure_zero():
    assert _review([_row("NEW", stored=0)]) == []


def test_a_report_without_the_refused_head_column_is_refused(tmp_path):
    old = tmp_path / "old.tsv"
    old.write_text("symbol\tn_stored\tremoved\nA\t1\t0\n")
    assert review_module.main([str(old)]) == 1
