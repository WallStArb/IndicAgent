"""S0 data-quality pinning and the D0 labels an attempt carries (D-04, D-07; todo 501).

S0 reads the label inputs once and pins them in the snapshot manifest, so the labels are a pure
function of the snapshot: the runner never reads the database for them, and a replay from the
snapshot hash gives the same block. The pinned facts are the derivation rules behind the bars
(``d2_rule_version``), the policy and verdict state they were read under (``policy_as_of``,
``verdict_as_of`` and the latest ``bar_integrity`` verdict per subject and metric), one content
digest per symbol over the ``bar_content_digest_current`` ranges the span touches, and the raw
label inputs (venue-moved names, quarantined bar keys, dividend coverage windows).

A snapshot captured before todo 501 has no ``data_quality_inputs`` block; its labels are
``None`` and its evidence carries no ``data_quality`` key, so old snapshots run unchanged.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import date, datetime

import numpy as np

from src.intelligence.bars.label_inputs import LabelInputs
from src.intelligence.bars.labels import DataQualityLabels, DividendLabel
from src.intelligence.research.panel import Panel

INPUTS_KEY = "data_quality_inputs"


def _iso(value: datetime | date | None) -> str | None:
    return None if value is None else value.isoformat()


def symbol_digests(rows: Iterable[tuple[str, datetime, str]]) -> dict[str, dict]:
    """``{symbol: {"n_ranges", "digest"}}`` from (symbol, range_start, digest) rows.

    The digest is sha256 over the symbol's ranges in range_start order, one
    ``<range_start iso>:<digest>`` line each, so it changes when any range's content does and
    can be recomputed from ``bar_content_digest_current``. A symbol with no digest row is absent:
    a digest gap is a disclosed fact, not an error.
    """
    ranges: dict[str, list[tuple[datetime, str]]] = {}
    for symbol, range_start, digest in rows:
        ranges.setdefault(symbol, []).append((range_start, digest))
    out = {}
    for symbol in sorted(ranges):
        lines = "\n".join(
            f"{start.isoformat()}:{digest}" for start, digest in sorted(ranges[symbol])
        )
        out[symbol] = {
            "n_ranges": len(ranges[symbol]),
            "digest": hashlib.sha256(lines.encode()).hexdigest(),
        }
    return out


def snapshot_manifest(
    inputs: LabelInputs,
    *,
    symbols: list[str],
    tf: str,
    digest_rows: Iterable[tuple[str, datetime, str]],
    verdict_rows: Iterable[tuple[str, str, bool]],
) -> dict:
    """The manifest keys S0 pins for one panel (JSON-able, deterministic order)."""
    verdicts: dict[str, dict[str, bool]] = {}
    for subject, metric, passed in sorted(verdict_rows):
        verdicts.setdefault(subject, {})[metric] = bool(passed)
    return {
        "symbols": sorted(symbols),
        "d2_rule_version": inputs.d2_rule_version,
        "policy_as_of": _iso(inputs.policy_as_of),
        "verdict_as_of": _iso(inputs.verdict_as_of),
        "bar_integrity": verdicts,
        "bar_content_digests": {tf: symbol_digests(digest_rows)},
        INPUTS_KEY: {
            "moved_symbols": sorted(inputs.moved_symbols),
            "quarantine_keys": [list(k) for k in sorted(inputs.quarantine_keys)],
            "dividend_coverage": {
                s: [_iso(lo), _iso(hi)] for s, (lo, hi) in sorted(inputs.dividend_coverage.items())
            },
        },
    }


def panel_labels(panel: Panel, *, total_return: bool) -> dict | None:
    """The D0 labels block for the panel's cells, or None for a snapshot without pinned inputs.

    A cell is a (bar, symbol) entry with a finite close. Call it on database symbols, before
    total_return splits a name into ``<symbol>~<k>`` segments. The shares are the ones
    ``labels.build_labels`` defines, counted per column so a full intraday universe (about 1e8
    cells) never materializes per-cell keys.
    """
    pinned = panel.manifest.get(INPUTS_KEY)
    if pinned is None:
        return None
    finite = np.isfinite(np.asarray(panel.close))
    per_symbol = finite.sum(axis=0)
    n_cells = int(per_symbol.sum())
    col = {s: j for j, s in enumerate(panel.symbols)}
    seconds = np.asarray(panel.timestamps).astype("datetime64[s]").astype(np.int64)
    # A regular-session bar's UTC date is its New York session date (13:30-21:00 UTC).
    days = np.asarray(panel.timestamps).astype("datetime64[D]")

    moved = sum(int(per_symbol[col[s]]) for s in pinned["moved_symbols"] if s in col)
    flagged = 0
    for symbol, ts in {(s, int(t)) for s, t in pinned["quarantine_keys"]}:
        if symbol not in col:
            continue
        row = np.searchsorted(seconds, ts)
        if row < len(seconds) and seconds[row] == ts and finite[row, col[symbol]]:
            flagged += 1
    covered = 0
    for symbol, (lo, hi) in pinned["dividend_coverage"].items():
        if symbol in col:
            inside = (days >= np.datetime64(lo, "D")) & (days <= np.datetime64(hi, "D"))
            covered += int((finite[:, col[symbol]] & inside).sum())

    def share(k: int) -> float:
        return k / n_cells if n_cells else 0.0

    return DataQualityLabels(
        d2_rule_version=panel.manifest.get("d2_rule_version"),
        venue_truncation_share=share(moved),
        dividends=DividendLabel(
            total_return=bool(total_return), uncovered_share=share(n_cells - covered)
        ),
        scrub_flag_share=share(flagged),
    ).to_manifest()
