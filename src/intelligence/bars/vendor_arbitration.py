"""Three-vendor 1d arbitration for D-191-Q (todo 545): where Alpaca SIP and IBKR disagree on a
daily close, Tradier decides which one is right, while Tradier's rows still exist (plan 191-20
deletes them).

Under the D-191-Q policy Alpaca serves 1d from 2016-01-04 and the daily rule never second-guesses
a tradeable Alpaca bar (daily_rule, module docstring). Where Alpaca's level is wrong for the
contract, the policy says so with a dated IBKR symbol row. This module decides which spans those
are, as evidence frozen once, never as a runtime test inside the rule.

Per name over the arbitration window, a session both Alpaca and IBKR answered disagrees when
their closes differ by more than tolerance_bp. A maximal run of disagreeing common sessions is a
span; the sessions of the span Tradier also answered classify it (each session: Alpaca = Tradier
and IBKR off, IBKR = Tradier and Alpaca off, or neither):

- ibkr_defective: Alpaca agrees with Tradier on at least min_class_share of them. Alpaca is
  right and serves under the default; the span is evidence that IBKR's history is wrong there
  (OKE's drift, RJF's 2/3 level), no row;
- alpaca_differs: IBKR agrees with Tradier on at least min_class_share. A spin-off Alpaca's split
  adjustment leaves unadjusted, or a reused ticker splicing a predecessor: an IBKR symbol row,
  no fallback, over [start, end + 1 day). A span still open at the window end is held instead
  (the disagreement may continue past Tradier's last day, where a dated row would end too soon);
- three_way: neither share reaches min_class_share; two_vendor: Tradier answered none of the
  span. Both go to the owner's hold list, no row;
- a span shorter than min_sessions is noise (a bad print), counted, no row, no hold.

Alpaca sessions before IBKR's first bar (pre_ibkr_history) are not disagreements: Alpaca serves
them. When IBKR verified its own 1d head (ohlcv_provider_head) after the span, IBKR asserts the
contract has no earlier history, so the span may be a predecessor under a reused ticker and goes
to the hold list; otherwise IBKR's history is simply not fetched yet and the span is reported.

The plan (build_plan) is the exact shape scripts/ops/bars/ops_source_policy.py --plan takes: both
current 1d defaults retired, IBKR before the seam, Alpaca with IBKR fallback from it, the
alpaca_differs rows, and a disposition for every live 1d symbol row (retired as replaced or
confirmed, or kept when the name has a hold or nothing to arbitrate).

Pure: closes in, spans and the plan dict out. No database, no APR (thresholds are parameters).
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from src.intelligence.bars.vendor_basis import BP

IBKR_DEFECTIVE = "ibkr_defective"
ALPACA_DIFFERS = "alpaca_differs"
THREE_WAY = "three_way"
TWO_VENDOR = "two_vendor"
PRE_IBKR_HISTORY = "pre_ibkr_history"

SEAM = date(2016, 1, 4)  # D-191-Q's policy seam, a decision record, not a tunable
_EPOCH = date(1990, 1, 1)  # the policy table's first default valid_from (migration 446)
_N_EXAMPLES = 3


@dataclass(frozen=True)
class ArbitrationParams:
    """Window (Tradier's span from the seam) and the APR thresholds the script reads:
    fallback_basis_tolerance_bp, vendor_ratio_run_min_sessions, tradier_admission_min_agree_share.
    """

    window_start: date
    window_end: date
    tolerance_bp: float
    min_sessions: int
    min_class_share: float


@dataclass(frozen=True)
class Span:
    symbol: str
    cls: str
    start: date
    end: date
    n_sessions: int
    n_tradier: int = 0
    shares: dict[str, float] = field(default_factory=dict, compare=False, hash=False)
    median_ibkr_over_alpaca: float | None = None
    median_tradier_over_alpaca: float | None = None
    examples: tuple[dict[str, Any], ...] = ()
    touches_window_end: bool = False
    ibkr_head_verified: bool = False

    def record(self) -> dict[str, Any]:
        """JSON-safe evidence of the span."""
        out = asdict(self)
        out["class"] = out.pop("cls")
        out["start"] = self.start.isoformat()
        out["end"] = self.end.isoformat()
        out["examples"] = list(self.examples)
        return out


@dataclass(frozen=True)
class NameArbitration:
    symbol: str
    n_common: int
    spans: tuple[Span, ...]


@dataclass(frozen=True)
class LiveSymbolRow:
    """One live 1d bar_source_policy symbol row the plan must dispose of."""

    policy_id: str
    symbol: str
    valid_from: date
    valid_to: date | None
    primary: str
    fallback: str | None


def _agree(a: float, b: float, tolerance_bp: float) -> bool:
    return b > 0 and abs(a / b - 1.0) * BP <= tolerance_bp


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _span(
    symbol: str,
    run: list[date],
    alpaca: Mapping[date, float],
    ibkr: Mapping[date, float],
    tradier: Mapping[date, float],
    params: ArbitrationParams,
    last_common: date,
) -> Span:
    counts = {IBKR_DEFECTIVE: 0, ALPACA_DIFFERS: 0, THREE_WAY: 0}
    with_tradier = [d for d in run if tradier.get(d, 0.0) > 0]
    for d in with_tradier:
        a_ok = _agree(alpaca[d], tradier[d], params.tolerance_bp)
        i_ok = _agree(ibkr[d], tradier[d], params.tolerance_bp)
        if a_ok and not i_ok:
            counts[IBKR_DEFECTIVE] += 1
        elif i_ok and not a_ok:
            counts[ALPACA_DIFFERS] += 1
        else:
            counts[THREE_WAY] += 1
    n_t = len(with_tradier)
    shares = {k: (v / n_t if n_t else 0.0) for k, v in counts.items()}
    if not n_t:
        cls = TWO_VENDOR
    elif shares[IBKR_DEFECTIVE] >= params.min_class_share:
        cls = IBKR_DEFECTIVE
    elif shares[ALPACA_DIFFERS] >= params.min_class_share:
        cls = ALPACA_DIFFERS
    else:
        cls = THREE_WAY
    picks = sorted({run[0], run[len(run) // 2], run[-1]})[:_N_EXAMPLES]
    return Span(
        symbol=symbol,
        cls=cls,
        start=run[0],
        end=run[-1],
        n_sessions=len(run),
        n_tradier=n_t,
        shares=shares,
        median_ibkr_over_alpaca=_median([ibkr[d] / alpaca[d] for d in run if alpaca[d] > 0]),
        median_tradier_over_alpaca=_median(
            [tradier[d] / alpaca[d] for d in with_tradier if alpaca[d] > 0]
        ),
        examples=tuple(
            {
                "session": d.isoformat(),
                "alpaca": alpaca[d],
                "ibkr": ibkr[d],
                "tradier": tradier.get(d),
            }
            for d in picks
        ),
        touches_window_end=run[-1] == last_common,
    )


def arbitrate(
    symbol: str,
    alpaca: Mapping[date, float],
    ibkr: Mapping[date, float],
    tradier: Mapping[date, float],
    params: ArbitrationParams,
    *,
    ibkr_head_verified: date | None = None,
) -> NameArbitration:
    """The disagreement spans of one name (module docstring). Closes are each vendor's current
    1d close per session date (Alpaca's tradeable bars only)."""

    def in_window(d: date) -> bool:
        return params.window_start <= d <= params.window_end

    common = sorted(
        d for d in alpaca if in_window(d) and d in ibkr and alpaca[d] > 0 and ibkr[d] > 0
    )
    spans: list[Span] = []
    ibkr_head = min(ibkr, default=None)
    pre = sorted(d for d in alpaca if in_window(d) and (ibkr_head is None or d < ibkr_head))
    if pre:
        spans.append(
            Span(
                symbol=symbol,
                cls=PRE_IBKR_HISTORY,
                start=pre[0],
                end=pre[-1],
                n_sessions=len(pre),
                n_tradier=sum(1 for d in pre if tradier.get(d, 0.0) > 0),
                ibkr_head_verified=ibkr_head_verified is not None and ibkr_head_verified > pre[0],
            )
        )
    run: list[date] = []
    for d in common:
        if _agree(ibkr[d], alpaca[d], params.tolerance_bp):
            if run:
                spans.append(_span(symbol, run, alpaca, ibkr, tradier, params, common[-1]))
                run = []
        else:
            run.append(d)
    if run:
        spans.append(_span(symbol, run, alpaca, ibkr, tradier, params, common[-1]))
    return NameArbitration(symbol, len(common), tuple(sorted(spans, key=lambda s: s.start)))


def span_action(span: Span, params: ArbitrationParams) -> str:
    """row, evidence, hold, noise or info (module docstring)."""
    if span.cls == PRE_IBKR_HISTORY:
        return "hold" if span.ibkr_head_verified else "info"
    if span.cls == IBKR_DEFECTIVE:
        return "evidence"
    if span.n_sessions < params.min_sessions:
        return "noise"
    if span.cls == ALPACA_DIFFERS and not span.touches_window_end:
        return "row"
    return "hold"


def build_plan(
    results: Sequence[NameArbitration],
    live_rows: Sequence[LiveSymbolRow],
    params: ArbitrationParams,
    *,
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """The ops_source_policy --plan document for the D-191-Q 1d decision (module docstring)."""
    by_symbol = {r.symbol: r for r in results}
    live_symbols = {r.symbol for r in live_rows}
    actions = {r.symbol: [(s, span_action(s, params)) for s in r.spans] for r in results}
    held_names = {
        sym
        for sym, acts in actions.items()
        if any(a == "hold" for _s, a in acts) and sym in live_symbols
    }
    symbol_rows: list[dict[str, Any]] = []
    hold: list[dict[str, Any]] = []
    defective: list[dict[str, Any]] = []
    counts = {k: 0 for k in ("row", "evidence", "hold", "noise", "info")}
    for sym in sorted(actions):
        for span, action in actions[sym]:
            counts[action] += 1
            if action == "row" and sym in held_names:
                hold.append({**span.record(), "reason": "the name keeps its live row (hold)"})
            elif action == "row":
                symbol_rows.append(
                    {
                        "symbol": sym,
                        "valid_from": span.start.isoformat(),
                        "valid_to": (span.end + timedelta(days=1)).isoformat(),
                        "primary": "ibkr",
                        "fallback": None,
                        "evidence": span.record(),
                    }
                )
            elif action == "hold":
                hold.append(span.record())
            elif action == "evidence":
                defective.append(span.record())
    replaced = {r["symbol"] for r in symbol_rows}
    retire: list[dict[str, Any]] = []
    keep: list[dict[str, Any]] = []
    for row in sorted(live_rows, key=lambda r: (r.symbol, r.valid_from)):
        result = by_symbol.get(row.symbol)
        if row.symbol in held_names:
            keep.append(
                {
                    "policy_id": row.policy_id,
                    "symbol": row.symbol,
                    "reason": "hold: the arbitration left spans for the owner",
                }
            )
        elif result is None or result.n_common == 0:
            keep.append(
                {
                    "policy_id": row.policy_id,
                    "symbol": row.symbol,
                    "reason": "no common Alpaca and IBKR sessions to arbitrate",
                }
            )
        else:
            n_disagree = sum(s.n_sessions for s in result.spans if s.cls != PRE_IBKR_HISTORY)
            retire.append(
                {
                    "policy_id": row.policy_id,
                    "symbol": row.symbol,
                    "disposition": "replaced" if row.symbol in replaced else "confirmed",
                    "evidence": {
                        "old_row": {
                            "valid_from": row.valid_from.isoformat(),
                            "valid_to": row.valid_to.isoformat() if row.valid_to else None,
                            "primary": row.primary,
                            "fallback": row.fallback,
                        },
                        "n_common": result.n_common,
                        "n_disagreeing_sessions": n_disagree,
                        "classes": sorted({s.cls for s in result.spans}),
                    },
                }
            )
    return {
        "timeframe": "1d",
        "seam": SEAM.isoformat(),
        "retire_defaults": True,
        "defaults": [
            {"valid_from": _EPOCH.isoformat(), "valid_to": SEAM.isoformat(), "primary": "ibkr"},
            {"valid_from": SEAM.isoformat(), "primary": "alpaca", "fallback": "ibkr"},
        ],
        "symbol_rows": symbol_rows,
        "retire_symbol_rows": retire,
        "keep_symbol_rows": keep,
        "hold": hold,
        "ibkr_defective": defective,
        "reason": "D-191-Q: canonical 1d Alpaca SIP primary from 2016-01-04, IBKR before "
        "(todo 545 step 4)",
        "evidence": {
            **evidence,
            "decision": "D-191-Q",
            "params": {
                "window_start": params.window_start.isoformat(),
                "window_end": params.window_end.isoformat(),
                "tolerance_bp": params.tolerance_bp,
                "min_sessions": params.min_sessions,
                "min_class_share": params.min_class_share,
            },
            "span_actions": counts,
            "n_names": len(results),
        },
    }
