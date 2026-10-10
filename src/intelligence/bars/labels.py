"""D0 data-quality labels for a research attempt (D-04).

Every attempt carries three typed labels describing the data it read, recorded
with the attempt in the S0 manifest and the S6 evidence: venue truncation
share (cells on names whose history starts at a venue move), the dividend
label (total-return flag plus the share of cells without dividend coverage),
and the scrub-flag share (cells on D2a-flagged bars). The survivorship bound
was retired 2026-10-09 (owner: survivorship bias is not an issue; todo 514).

These labels describe exposure. They never gate a verdict by themselves:
D-04 fixes them as a bound reported beside the statistic, so a bad label is a
disclosed limitation, not a rejected run. Old verdicts are not re-run; labels
are computed for new attempts only.

Inputs arrive as arrays from the DB read helper (plan 16, which needs D1 and
the re-run inventory first). ``d2_rule_version`` is the D2 rule version the
attempt read (D-07), carried unchanged into the manifest.

Pure: arrays in, labels out; no database, no config service, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def venue_truncation_share(cell_symbols: np.ndarray, moved_symbols: frozenset[str]) -> float:
    """Share of an attempt's cells on names whose history starts at a venue move.

    ``cell_symbols`` holds one symbol per (name, session) cell, any shape; the
    share is moved cells over all cells. An attempt with no cells has no
    measured exposure and reports 0.0.
    """
    arr = np.asarray(cell_symbols)
    if arr.size == 0:
        return 0.0
    mask = np.fromiter(
        (symbol in moved_symbols for symbol in arr.ravel()),
        dtype=bool,
        count=arr.size,
    ).reshape(arr.shape)
    return float(mask.mean())


@dataclass(frozen=True)
class DividendLabel:
    """Dividend exposure of the attempt (todo 428, todo 449 coverage).

    ``total_return`` is the spec's panel.total_return flag; outside dividend
    coverage a name's dividends are unknown, never zero, so
    ``uncovered_share`` sizes that unknown.
    """

    total_return: bool
    uncovered_share: float


def dividend_label(total_return: bool, div_covered: np.ndarray) -> DividendLabel:
    """Label from the spec's total-return flag and a per-cell coverage mask.

    ``div_covered`` is boolean per cell (the session lies inside the symbol's
    dividend coverage). Non-boolean input is refused: a silently coerced
    integer mask would mislabel coverage.
    """
    arr = np.asarray(div_covered)
    if arr.dtype != np.dtype(bool):
        raise TypeError(f"div_covered must be boolean, got dtype {arr.dtype}")
    if arr.size == 0:
        return DividendLabel(total_return=bool(total_return), uncovered_share=0.0)
    return DividendLabel(
        total_return=bool(total_return),
        uncovered_share=float(np.logical_not(arr).mean()),
    )


def scrub_flag_share(cell_keys: np.ndarray, flagged_keys: frozenset) -> float:
    """Share of the attempt's cells sitting on D2a-flagged bars (D-09).

    ``cell_keys`` is a 1-D array of (symbol, ts_seconds) pairs, either a
    structured array or an object array of tuples; ``flagged_keys`` holds the
    (symbol, ts_seconds) pairs the scrub stage flagged. Flagged keys outside
    the attempt's cells do not count: the label sizes this attempt's exposure,
    not the flag table.
    """
    arr = np.asarray(cell_keys)
    if arr.ndim != 1:
        raise ValueError(f"cell_keys must be 1-D, got shape {arr.shape}")
    if arr.size == 0 or not flagged_keys:
        return 0.0
    hits = 0
    for row in arr:
        key = tuple(row.tolist()) if isinstance(row, np.void) else tuple(row)
        if key in flagged_keys:
            hits += 1
    return hits / arr.size


@dataclass(frozen=True)
class DataQualityLabels:
    """The three D0 labels plus the D2 rule version the attempt read (D-07).

    The manifest block is carried unchanged by the S0 manifest and the S6
    evidence (D-04); ``d2_rule_version`` is the hook that makes every recorded
    attempt name the derivation rule behind its bars.
    """

    d2_rule_version: str | None
    venue_truncation_share: float
    dividends: DividendLabel
    scrub_flag_share: float

    def to_manifest(self) -> dict:
        """A JSON-able manifest block (plain scalars only)."""
        return {
            "d2_rule_version": self.d2_rule_version,
            "venue_truncation_share": float(self.venue_truncation_share),
            "dividends": {
                "total_return": bool(self.dividends.total_return),
                "uncovered_share": float(self.dividends.uncovered_share),
            },
            "scrub_flag_share": float(self.scrub_flag_share),
        }


def build_labels(
    *,
    d2_rule_version: str | None,
    cell_symbols: np.ndarray,
    moved_symbols: frozenset[str],
    total_return: bool,
    div_covered: np.ndarray,
    cell_keys: np.ndarray,
    flagged_keys: frozenset,
) -> DataQualityLabels:
    """Compute all three labels for one attempt from its inputs (pure).

    One call site for the attempt manifest: every input is a keyword argument,
    so the plan 16 read helper forwards exactly what it loaded.
    """
    return DataQualityLabels(
        d2_rule_version=d2_rule_version,
        venue_truncation_share=venue_truncation_share(cell_symbols, moved_symbols),
        dividends=dividend_label(total_return, div_covered),
        scrub_flag_share=scrub_flag_share(cell_keys, flagged_keys),
    )
