"""Per-(feature, tf) data quality: the one definition of feature symbol coverage.

A symbol is populated for a feature at a tf when it carries at least one non-NULL value of
that feature over the span. The denominator is the symbols that have any row at that tf in
the span, so a symbol whose bars are not backfilled yet does not count against a feature.

feature_lifecycle (186-09, D-30) decides feature status from these checks, todo 421's
coverage check and todo 435's S0 floor use this function and the APR key
`feature.coverage.min_symbol_fraction`, never a second definition.

Pure functions over counts: no DB, no config loading. The floor is an argument.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolCounts:
    """One symbol's row counts for one feature at one tf over the span."""

    symbol: str
    n_rows: int
    n_non_null: int
    n_non_finite: int


@dataclass(frozen=True)
class FeatureTfQuality:
    feature: str
    tf: str
    n_symbols_with_rows: int
    n_symbols_populated: int
    symbol_coverage: float | None  # None: no symbol has rows, so no claim
    non_null_share: float | None
    n_rows: int
    n_non_finite: int


@dataclass(frozen=True)
class QualityVerdict:
    passed: bool
    failures: tuple[str, ...]
    statistic: float | None  # minimum symbol_coverage over the populated tfs
    per_tf: dict[str, str]  # tf -> ok | coverage | non_finite | not_emitted_at_tf


def feature_tf_quality(feature: str, tf: str, counts: Iterable[SymbolCounts]) -> FeatureTfQuality:
    with_rows = [c for c in counts if c.n_rows > 0]
    n_rows = sum(c.n_rows for c in with_rows)
    n_populated = sum(1 for c in with_rows if c.n_non_null > 0)
    return FeatureTfQuality(
        feature=feature,
        tf=tf,
        n_symbols_with_rows=len(with_rows),
        n_symbols_populated=n_populated,
        symbol_coverage=n_populated / len(with_rows) if with_rows else None,
        non_null_share=sum(c.n_non_null for c in with_rows) / n_rows if n_rows else None,
        n_rows=n_rows,
        n_non_finite=sum(c.n_non_finite for c in with_rows),
    )


def feature_quality_verdict(
    per_tf: Sequence[FeatureTfQuality], coverage_floor: float
) -> QualityVerdict:
    """One feature's verdict over its per-tf results.

    A tf where the feature is NULL on every row while another tf is populated is
    'not_emitted_at_tf' and does not fail the feature (tf-specific columns). A feature
    with no non-NULL value at any tf fails 'not_computed'. Non-finite values at any tf
    fail 'non_finite'. A populated tf below the floor fails 'coverage'.
    """
    populated = [q for q in per_tf if q.symbol_coverage is not None and q.symbol_coverage > 0.0]
    if not populated:
        return QualityVerdict(
            False, ("not_computed",), None, {q.tf: "not_emitted_at_tf" for q in per_tf}
        )
    codes: dict[str, str] = {}
    for q in per_tf:
        if q not in populated:
            codes[q.tf] = "not_emitted_at_tf"
        elif q.n_non_finite > 0:
            codes[q.tf] = "non_finite"
        elif q.symbol_coverage is not None and q.symbol_coverage < coverage_floor:
            codes[q.tf] = "coverage"
        else:
            codes[q.tf] = "ok"
    failures = tuple(f for f in ("non_finite", "coverage") if f in codes.values())
    statistic = min(q.symbol_coverage for q in populated if q.symbol_coverage is not None)
    return QualityVerdict(not failures, failures, statistic, codes)
