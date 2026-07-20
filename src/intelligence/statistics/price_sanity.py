"""Bar-level price-sanity classification and cross-symbol corroboration.

Shared by services/bar_auditor.py's live audit task (todo 149) and
scripts/ops/corpus/ops_known_corrupt_print_cleanup.py's ad hoc cleanup tool (todo 151).
Both consumers classify OHLC bars against their immediate neighbors to distinguish
genuine corrupt prints (an isolated spike-and-immediate-revert with no economic basis)
from real market-wide events (a Flash-Crash-shaped move corroborated across multiple
symbols) -- see docs/superpowers/specs/2026-07-20-bar-ingestion-price-sanity-guard-design.md
for the full design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

_MAGNITUDE_THRESHOLD_DEFAULT = 10.0
_NEIGHBOR_AGREEMENT_THRESHOLD_DEFAULT = 2.0


@dataclass(frozen=True)
class CandidateVerdict:
    verdict: str  # "CONFIRMED_CORRUPT" | "AMBIGUOUS" | "PLAUSIBLE" | "MARKET_EVENT"
    implausible_fields: tuple[str, ...]
    max_ratio: float
    neighbor_ratio: float | None
    reason: str


def classify_candidate_bar(
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    prev_close: float | None,
    next_open: float | None,
    magnitude_threshold: float = _MAGNITUDE_THRESHOLD_DEFAULT,
    neighbor_agreement_threshold: float = _NEIGHBOR_AGREEMENT_THRESHOLD_DEFAULT,
) -> CandidateVerdict:
    """Classify a candidate bar against its immediate neighbors (LAG close / LEAD open).

    Reference price is the average of the previous bar's close and the next bar's
    open. Each of this bar's open/high/low/close is checked independently (a corrupt
    print can taint only SOME OHLC fields -- e.g. the UUP row has a corrupted
    open/high but a plausible low/close) against that reference via a symmetric
    magnitude factor (max(ratio, 1/ratio), so both a 1000x-too-high and a 1000x-too-
    low value are caught the same way).

    CONFIRMED_CORRUPT requires BOTH: at least one field off by
    >= magnitude_threshold, AND the two neighbors agreeing closely with each other
    (<= neighbor_agreement_threshold apart) -- confirming they are a trustworthy
    reference for an isolated spike-and-immediate-revert. If the neighbors
    themselves disagree beyond that threshold, the reference is untrustworthy and
    the verdict is AMBIGUOUS instead of forcing a call. Missing neighbor data (series
    boundary) is always AMBIGUOUS -- there is no reference to check against at all.
    """
    if prev_close is None or next_open is None or prev_close <= 0 or next_open <= 0:
        return CandidateVerdict(
            verdict="AMBIGUOUS",
            implausible_fields=(),
            max_ratio=float("nan"),
            neighbor_ratio=None,
            reason="insufficient_neighbor_data",
        )

    reference_price = (prev_close + next_open) / 2.0
    fields = {"open": open_, "high": high, "low": low, "close": close}
    magnitude_factors: dict[str, float] = {}
    for name, value in fields.items():
        if value is None or value <= 0:
            magnitude_factors[name] = float("inf")
            continue
        ratio = value / reference_price
        magnitude_factors[name] = max(ratio, 1.0 / ratio)

    implausible_fields = tuple(
        name for name, factor in magnitude_factors.items() if factor >= magnitude_threshold
    )
    max_ratio = max(magnitude_factors.values())
    neighbor_ratio = max(prev_close, next_open) / min(prev_close, next_open)

    if not implausible_fields:
        return CandidateVerdict(
            verdict="PLAUSIBLE",
            implausible_fields=(),
            max_ratio=max_ratio,
            neighbor_ratio=neighbor_ratio,
            reason="within_magnitude_threshold",
        )
    if neighbor_ratio <= neighbor_agreement_threshold:
        return CandidateVerdict(
            verdict="CONFIRMED_CORRUPT",
            implausible_fields=implausible_fields,
            max_ratio=max_ratio,
            neighbor_ratio=neighbor_ratio,
            reason="isolated_spike_neighbors_agree",
        )
    return CandidateVerdict(
        verdict="AMBIGUOUS",
        implausible_fields=implausible_fields,
        max_ratio=max_ratio,
        neighbor_ratio=neighbor_ratio,
        reason="implausible_but_neighbors_disagree",
    )


def apply_cross_symbol_downgrade(
    verdict: CandidateVerdict, n_corroborating_symbols: int, min_symbols: int
) -> CandidateVerdict:
    """Downgrade CONFIRMED_CORRUPT -> MARKET_EVENT when the subject symbol plus
    n_corroborating_symbols OTHER symbols (total >= min_symbols) show a similarly
    implausible move at/near the same (tf, timestamp) -- todo 152's cross-symbol
    corroboration signal applied to a single-symbol classification.
    classify_candidate_bar's single-symbol neighbor-agreement check cannot
    distinguish a genuine V-shaped flash-crash recovery from an isolated bad print
    (both show "isolated spike, neighbors agree"); this is the missing signal. Only
    CONFIRMED_CORRUPT is checked -- AMBIGUOUS/PLAUSIBLE verdicts are unaffected by
    corroboration.
    """
    if verdict.verdict != "CONFIRMED_CORRUPT":
        return verdict
    total_symbols = n_corroborating_symbols + 1
    if total_symbols < min_symbols:
        return verdict
    return replace(
        verdict,
        verdict="MARKET_EVENT",
        reason=f"cross_symbol_corroborated_n={total_symbols}",
    )


def build_subject_key(symbol: str, tf: str, timestamp_iso: str) -> str:
    """integrity_monitor.subject shape for price-sanity monitor types (todo 149/151)."""
    return f"symbol={symbol}|tf={tf}|ts={timestamp_iso}"
