"""Three-vendor 1d arbitration for D-191-Q (todo 545): where Alpaca SIP and IBKR disagree on a
daily close, Tradier decides which one is right, while Tradier's rows still exist (plan 191-20
deletes them).

Under the D-191-Q policy Alpaca serves 1d from 2016-01-04 and the daily rule never second-guesses
a tradeable Alpaca bar (daily_rule, module docstring). Where Alpaca's level is wrong for the
contract, or nobody can tell, the policy says so with a dated IBKR symbol row (primary ibkr, no
fallback). This module decides which spans those are, as evidence frozen once, never as a
runtime test inside the rule.

Disagreement spans. Per name over the arbitration window, a session both Alpaca and IBKR answered
disagrees when their closes differ by more than tolerance_bp. A maximal run of disagreeing common
sessions is a span; the sessions of the span Tradier also answered classify it (each: Alpaca =
Tradier and IBKR off, IBKR = Tradier and Alpaca off, or neither):

- ibkr_defective: Alpaca agrees with Tradier on at least min_class_share of them. Alpaca is right
  and serves; the span is evidence that IBKR's history is wrong there (OKE, RJF), no row;
- alpaca_differs: IBKR agrees with Tradier on at least min_class_share. A spin-off Alpaca's split
  adjustment leaves unadjusted, or a reused ticker: an IBKR row over [start, end + 1 day). A span
  still open at the window end is held (it may run past Tradier's last day);
- three_way: neither share reaches min_class_share. When IBKR and Tradier both adjusted the
  history with factors a few bp apart (second review): the median log IBKR/Tradier is within
  three_way_max_it_bp, its median absolute deviation is under tolerance_bp, and it is at most
  three_way_log_share of the median log IBKR/Alpaca, the span gets an IBKR row; otherwise held;
- two_vendor: Tradier answered none of the span; held;
- a span shorter than min_sessions (the basis window) is noise: Alpaca serves. Where IBKR agrees
  with Tradier on such a session and Alpaca is more than quarantine_rel off Tradier, the session
  goes to the quarantine list (a bar_quality_flag the policy apply writes through the flag
  writer).

Alpaca before IBKR's first bar (pre_ibkr_history). Alpaca serves it only when its series runs into
IBKR's first bar: the span's last session and IBKR's first bar are consecutive NYSE sessions, and
on IBKR's first session Alpaca's close agrees within tolerance_bp with IBKR's or, where IBKR is the
one off, with Tradier's. Otherwise (a gap, or a level break: a predecessor under a reused ticker)
the span has no bar: an IBKR row from its start to IBKR's first bar. A name IBKR never answered is
held. A span longer than min_sessions needs more than the same-session test, which cannot see a
ticker handover (third review: SW served WestRock's 2016-2024 history): it is admitted only when
Tradier answered inside it and agrees with Alpaca on at least min_class_share of those sessions,
or the close-to-close gap at IBKR's first bar is at most gap_max_moves (APR
threshold.bar_integrity.arbitration_gap_max_daily_moves) times the name's median absolute daily
log move on IBKR's own closes, the gap test applying only where Tradier has no session in the
span (the Tradier veto, data lane 2026-10-28: Tradier's disagreement holds CRH whatever its gap).
Otherwise it is held under an interim IBKR row. Whether IBKR verified its head (ohlcv_provider_head) is recorded as evidence; both cases take
the same test (second review).

A hold means Alpaca does not serve (second review H1): build_plan gives every held span an interim
IBKR row over it, and the hold list is the owner's to turn into final rows. The plan is the exact
document scripts/ops/bars/ops_source_policy.py --plan takes: both 1d defaults retired (their
policy_ids pinned), IBKR before the seam, Alpaca with IBKR fallback from it, the rows, a
disposition for every live 1d symbol row (replaced by new rows, superseded_by_default, or kept
when the arbitration has nothing on the name), the quarantine list and the raw-data fingerprint
the apply checks.

Pure: closes in, spans and the plan dict out. No database, no APR (thresholds are parameters).
"""

from __future__ import annotations

import math
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
QUARANTINE_RULE = "vendor_disagreement"


@dataclass(frozen=True)
class ArbitrationParams:
    """Window (Tradier's span from the seam) and the thresholds the script reads: APR
    fallback_basis_tolerance_bp, fallback_basis_window_sessions (min_sessions: a basis difference
    is a level held over the basis window), tradier_admission_min_agree_share and
    threshold.bar_scrub.view_disagreement_rel (quarantine_rel); the two three-way thresholds are
    the second review's decision values, recorded in the plan's evidence."""

    window_start: date
    window_end: date
    tolerance_bp: float
    min_sessions: int
    min_class_share: float
    quarantine_rel: float = 0.02
    three_way_max_it_bp: float = 50.0
    three_way_log_share: float = 0.1
    gap_max_moves: float = 4.0


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
    median_log_it_bp: float | None = None
    mad_log_it_bp: float | None = None
    median_log_ia_bp: float | None = None
    examples: tuple[dict[str, Any], ...] = ()
    touches_window_end: bool = False
    ibkr_head: date | None = None
    ibkr_head_verified: bool = False
    continuous: bool = False
    continuity: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def record(self) -> dict[str, Any]:
        """JSON-safe evidence of the span."""
        out = asdict(self)
        out["class"] = out.pop("cls")
        for key in ("start", "end", "ibkr_head"):
            out[key] = out[key].isoformat() if out[key] else None
        out["examples"] = list(self.examples)
        return out


@dataclass(frozen=True)
class NameArbitration:
    symbol: str
    n_common: int
    spans: tuple[Span, ...]
    quarantine: tuple[dict[str, Any], ...] = ()


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


def _log_bp(a: float, b: float) -> float:
    return math.log(a / b) * BP


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
    log_it = [_log_bp(ibkr[d], tradier[d]) for d in with_tradier]
    med_it = _median(log_it)
    picks = sorted({run[0], run[len(run) // 2], run[-1]})[:_N_EXAMPLES]
    return Span(
        symbol=symbol,
        cls=cls,
        start=run[0],
        end=run[-1],
        n_sessions=len(run),
        n_tradier=n_t,
        shares=shares,
        median_ibkr_over_alpaca=_median([ibkr[d] / alpaca[d] for d in run]),
        median_tradier_over_alpaca=_median([tradier[d] / alpaca[d] for d in with_tradier]),
        median_log_it_bp=med_it,
        mad_log_it_bp=(None if med_it is None else _median([abs(x - med_it) for x in log_it])),
        median_log_ia_bp=_median([_log_bp(ibkr[d], alpaca[d]) for d in run]),
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


def _quarantine(
    symbol: str,
    span: Span,
    run: list[date],
    alpaca: Mapping[date, float],
    ibkr: Mapping[date, float],
    tradier: Mapping[date, float],
    params: ArbitrationParams,
) -> list[dict[str, Any]]:
    """The sessions of a short span where IBKR = Tradier and Alpaca is quarantine_rel off."""
    if span.n_sessions >= params.min_sessions or span.cls == IBKR_DEFECTIVE:
        return []
    out = []
    for d in run:
        t = tradier.get(d, 0.0)
        if (
            t > 0
            and _agree(ibkr[d], t, params.tolerance_bp)
            and abs(alpaca[d] / t - 1.0) > params.quarantine_rel
        ):
            out.append(
                {
                    "symbol": symbol,
                    "session": d.isoformat(),
                    "alpaca": alpaca[d],
                    "ibkr": ibkr[d],
                    "tradier": t,
                    "alpaca_over_tradier": alpaca[d] / t,
                }
            )
    return out


def _pre_ibkr(
    symbol: str,
    pre: list[date],
    alpaca: Mapping[date, float],
    ibkr: Mapping[date, float],
    tradier: Mapping[date, float],
    params: ArbitrationParams,
    sessions: Sequence[date] | None,
    ibkr_head_verified: date | None,
) -> Span:
    head = min(ibkr, default=None)
    continuity: dict[str, Any] = {}
    continuous = False
    with_tradier = [d for d in pre if tradier.get(d, 0.0) > 0]
    continuity["tradier_agree_share"] = (
        sum(1 for d in with_tradier if _agree(alpaca[d], tradier[d], params.tolerance_bp))
        / len(with_tradier)
        if with_tradier
        else None
    )
    if head is not None:
        index = {d: i for i, d in enumerate(sessions or ())}
        consecutive = pre[-1] in index and head in index and index[head] - index[pre[-1]] == 1
        a_head = alpaca.get(head)
        agrees_ibkr = a_head is not None and _agree(a_head, ibkr[head], params.tolerance_bp)
        t_head = tradier.get(head, 0.0)
        agrees_tradier = (
            a_head is not None and t_head > 0 and _agree(a_head, t_head, params.tolerance_bp)
        )
        continuous = consecutive and (agrees_ibkr or agrees_tradier)
        ibkr_days = sorted(d for d in ibkr if ibkr[d] > 0)
        moves = [abs(_log_bp(ibkr[b], ibkr[a])) for a, b in zip(ibkr_days, ibkr_days[1:])]
        gap = _log_bp(ibkr[head], alpaca[pre[-1]]) if alpaca[pre[-1]] > 0 else None
        median_move = _median(moves)
        continuity |= {
            "consecutive": consecutive,
            "alpaca_at_head": a_head,
            "ibkr_at_head": ibkr[head],
            "tradier_at_head": t_head or None,
            "overnight_gap_bp": gap,
            "median_abs_daily_move_bp": median_move,
            "gap_in_daily_moves": (
                abs(gap) / median_move if gap is not None and median_move else None
            ),
        }
    return Span(
        symbol=symbol,
        cls=PRE_IBKR_HISTORY,
        start=pre[0],
        end=pre[-1],
        n_sessions=len(pre),
        n_tradier=sum(1 for d in pre if tradier.get(d, 0.0) > 0),
        ibkr_head=head,
        ibkr_head_verified=ibkr_head_verified is not None,
        continuous=continuous,
        continuity=continuity,
    )


def arbitrate(
    symbol: str,
    alpaca: Mapping[date, float],
    ibkr: Mapping[date, float],
    tradier: Mapping[date, float],
    params: ArbitrationParams,
    *,
    sessions: Sequence[date] | None = None,
    ibkr_head_verified: date | None = None,
) -> NameArbitration:
    """The disagreement spans of one name (module docstring). Closes are each vendor's current
    1d close per session date (Alpaca's tradeable bars only); sessions is the NYSE session
    calendar the continuity test reads."""

    def in_window(d: date) -> bool:
        return params.window_start <= d <= params.window_end

    common = sorted(
        d for d in alpaca if in_window(d) and d in ibkr and alpaca[d] > 0 and ibkr[d] > 0
    )
    spans: list[Span] = []
    quarantine: list[dict[str, Any]] = []
    head = min(ibkr, default=None)
    pre = sorted(d for d in alpaca if in_window(d) and (head is None or d < head))
    if pre:
        spans.append(
            _pre_ibkr(symbol, pre, alpaca, ibkr, tradier, params, sessions, ibkr_head_verified)
        )

    def close(run: list[date]) -> None:
        span = _span(symbol, run, alpaca, ibkr, tradier, params, common[-1])
        spans.append(span)
        quarantine.extend(_quarantine(symbol, span, run, alpaca, ibkr, tradier, params))

    run: list[date] = []
    for d in common:
        if _agree(ibkr[d], alpaca[d], params.tolerance_bp):
            if run:
                close(run)
                run = []
        else:
            run.append(d)
    if run:
        close(run)
    return NameArbitration(
        symbol, len(common), tuple(sorted(spans, key=lambda s: s.start)), tuple(quarantine)
    )


def _adjusted_three_way(span: Span, params: ArbitrationParams) -> bool:
    """IBKR and Tradier both adjusted the history, a few bp apart (module docstring)."""
    it, mad, ia = span.median_log_it_bp, span.mad_log_it_bp, span.median_log_ia_bp
    if it is None or mad is None or ia is None:
        return False
    return (
        abs(it) <= params.three_way_max_it_bp
        and mad < params.tolerance_bp
        and abs(it) <= params.three_way_log_share * abs(ia)
    )


def span_action(span: Span, params: ArbitrationParams) -> str:
    """row, evidence, hold, noise or info (module docstring)."""
    if span.cls == PRE_IBKR_HISTORY:
        if span.ibkr_head is None:
            return "hold"
        if not span.continuous:
            return "row"
        if span.n_sessions <= params.min_sessions:
            return "info"
        share = span.continuity.get("tradier_agree_share")
        if share is not None:
            # Tradier answered inside the span: its word decides (the Tradier veto, data lane
            # 2026-10-28; CRH).
            return "info" if share >= params.min_class_share else "hold"
        moves = span.continuity.get("gap_in_daily_moves")
        return "info" if moves is not None and moves <= params.gap_max_moves else "hold"
    if span.cls == IBKR_DEFECTIVE:
        return "evidence"
    if span.n_sessions < params.min_sessions:
        return "noise"
    if span.cls == ALPACA_DIFFERS:
        return "hold" if span.touches_window_end else "row"
    if span.cls == THREE_WAY and _adjusted_three_way(span, params):
        return "row"
    return "hold"


def _row_end(span: Span) -> date:
    """valid_to of the IBKR row over a span: IBKR's head for a pre-IBKR span (no bar until it),
    the day after the span otherwise."""
    if span.cls == PRE_IBKR_HISTORY and span.ibkr_head is not None:
        return span.ibkr_head
    return span.end + timedelta(days=1)


def build_plan(
    results: Sequence[NameArbitration],
    live_rows: Sequence[LiveSymbolRow],
    params: ArbitrationParams,
    *,
    evidence: Mapping[str, Any],
    live_default_ids: Sequence[str],
    raw_fingerprint: Mapping[str, Any],
) -> dict[str, Any]:
    """The ops_source_policy --plan document for the D-191-Q 1d decision (module docstring)."""
    by_symbol = {r.symbol: r for r in results}
    symbol_rows: list[dict[str, Any]] = []
    hold: list[dict[str, Any]] = []
    defective: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    counts = dict.fromkeys(("row", "evidence", "hold", "noise", "info"), 0)
    classes: dict[tuple[str, str], dict[str, Any]] = {}
    for result in sorted(results, key=lambda r: r.symbol):
        quarantine.extend(result.quarantine)
        for span in result.spans:
            action = span_action(span, params)
            counts[action] += 1
            entry = classes.setdefault(
                (span.cls, action), {"spans": 0, "sessions": 0, "names": set()}
            )
            entry["spans"] += 1
            entry["sessions"] += span.n_sessions
            entry["names"].add(result.symbol)
            if action in ("row", "hold"):
                symbol_rows.append(
                    {
                        "symbol": result.symbol,
                        "valid_from": span.start.isoformat(),
                        "valid_to": _row_end(span).isoformat(),
                        "primary": "ibkr",
                        "fallback": None,
                        "evidence": {**span.record(), "interim": action == "hold"},
                    }
                )
            if action == "hold":
                hold.append(span.record())
            elif action == "evidence":
                defective.append(span.record())
    new_symbols = {r["symbol"] for r in symbol_rows}
    retire: list[dict[str, Any]] = []
    keep: list[dict[str, Any]] = []
    for row in sorted(live_rows, key=lambda r: (r.symbol, r.valid_from)):
        result = by_symbol.get(row.symbol)
        old = {
            "valid_from": row.valid_from.isoformat(),
            "valid_to": row.valid_to.isoformat() if row.valid_to else None,
            "primary": row.primary,
            "fallback": row.fallback,
        }
        if result is None:
            keep.append(
                {
                    "policy_id": row.policy_id,
                    "symbol": row.symbol,
                    **{k: old[k] for k in ("valid_from", "valid_to")},
                    "reason": "no Alpaca 1d history to arbitrate",
                }
            )
            continue
        retire.append(
            {
                "policy_id": row.policy_id,
                "symbol": row.symbol,
                "disposition": (
                    "replaced" if row.symbol in new_symbols else "superseded_by_default"
                ),
                "evidence": {
                    "old_row": old,
                    "n_common": result.n_common,
                    "classes": sorted({s.cls for s in result.spans}),
                },
            }
        )
    return {
        "timeframe": "1d",
        "seam": SEAM.isoformat(),
        "retire_defaults": True,
        "retire_default_ids": list(live_default_ids),
        "raw_fingerprint": dict(raw_fingerprint),
        "defaults": [
            {"valid_from": _EPOCH.isoformat(), "valid_to": SEAM.isoformat(), "primary": "ibkr"},
            {"valid_from": SEAM.isoformat(), "primary": "alpaca", "fallback": "ibkr"},
        ],
        "symbol_rows": symbol_rows,
        "retire_symbol_rows": retire,
        "keep_symbol_rows": keep,
        "hold": hold,
        "ibkr_defective": defective,
        "quarantine": quarantine,
        "quarantine_rule": QUARANTINE_RULE,
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
                "quarantine_rel": params.quarantine_rel,
                "three_way_max_it_bp": params.three_way_max_it_bp,
                "three_way_log_share": params.three_way_log_share,
                "gap_max_moves": params.gap_max_moves,
            },
            "span_actions": counts,
            "classes": [
                {
                    "class": cls,
                    "action": action,
                    "spans": v["spans"],
                    "sessions": v["sessions"],
                    "names": len(v["names"]),
                }
                for (cls, action), v in sorted(classes.items())
            ],
            "n_names": len(results),
            "n_quarantine": len(quarantine),
        },
    }
