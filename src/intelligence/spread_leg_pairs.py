"""The spread_leg pair check (todo 678): every current `instrument_tags` row tagged `spread_leg`
names, in its evidence `pair` key (a symbol or a list of symbols), instruments that exist, other
than itself, and every pair is reciprocal. Pure; the nightly reconciliation audit
(services/bar_reconciliation_audit.py) reads the rows and reports the problems as the
`spread_leg_pairs` check.

One row per symbol is structural: the `instrument_tags` primary key is (symbol, tag).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def pair_symbols(evidence: Mapping | None) -> list[str] | None:
    """The evidence `pair` value as a list of symbols; [] when it is missing, None when it is
    neither a symbol nor a list of symbols, or the evidence is not an object (a malformed value
    is a problem, never coerced)."""
    if evidence is not None and not isinstance(evidence, Mapping):
        return None
    pair = (evidence or {}).get("pair")
    if pair is None:
        return []
    pairs = pair if isinstance(pair, list) else [pair]
    return pairs if all(isinstance(p, str) for p in pairs) else None


def spread_leg_problems(
    rows: Sequence[tuple[str, Mapping | None]], symbols: frozenset[str]
) -> list[str]:
    """Every missing or malformed pair, self pair, pair naming an unknown symbol and
    non-reciprocal pair among the current (symbol, evidence) rows, sorted."""
    problems: list[str] = []
    partners: dict[str, list[str]] = {}
    for symbol, evidence in rows:
        pair_list = pair_symbols(evidence)
        if pair_list is None:
            problems.append(f"{symbol}: pair is not a symbol or a list of symbols")
            pair_list = []
        elif not pair_list:
            problems.append(f"{symbol}: no evidence pair")
        partners[symbol] = pair_list
    for symbol, pair_list in partners.items():
        for partner in pair_list:
            if partner == symbol:
                problems.append(f"{symbol}: pairs with itself")
                continue
            if partner not in symbols:
                problems.append(f"{symbol}->{partner}: no such instrument")
            if partner not in partners:
                problems.append(f"{symbol}->{partner}: partner has no spread_leg row")
            elif symbol not in partners[partner]:
                problems.append(f"{symbol}->{partner}: {partner} does not name {symbol} back")
    return sorted(problems)
