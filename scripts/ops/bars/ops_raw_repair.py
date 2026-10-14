"""ops_raw_repair.py - repair the raw rows the selection gate explains (phase 191 plan 07 review).

Review of plan 191-07, findings 2 and 4 (.planning/phases/191-unified-raw-bar-table/191-07-REVIEW.md).
The gate (scripts/ops/bars/ops_selection_gate.py) counts the slots where canonical differs from the
selection of raw for a recorded reason. This script decides, per slot, what makes raw the vendor's
own accepted answer, and then lets selection write canonical from raw. It never edits canonical
directly and never deletes a raw row or a revision row.

Per explained slot of a series (the gate's classes, the same evidence):
- refused_self_restatement (raw holds a serve of a refused load, canonical the value the vendor
  served before):
  - not at a chunk edge: `restore_pending` puts the accepted (canonical) value back in raw through
    the raw writer under a repair load (the refused value is logged as the replaced value, origin
    raw) and, where no applied serve of the vendor covered the slot after the refusal, holds the
    refused value as a `pending` revision under the ORIGINAL refused load (D-191-I). Where a later
    applied serve covered it, the vendor already answered again: `restore` only.
  - at a chunk edge (an IBKR request of the series ended inside the bar, review finding 2): one
    of the two values is a truncated bar. The one with the higher volume is the whole bar (a
    truncated bar counts a subset of the trades). Raw truncated: `restore`, no pending (a partial
    bar is not a vendor answer). Raw whole: `reserve`, the slot waits for a re-serve.
- restated_after_copy (raw is stale, canonical the vendor's later accepted serve):
  - not at a chunk edge: `restore`.
  - at a chunk edge: raw whole and canonical truncated: `select` (raw is already right; selection
    takes it). Raw truncated: `reserve` (the whole bar must come from the vendor again, never from
    canonical).
- refused_cross_vendor (a legacy refusal of the vendor against another vendor's canonical row, not
  a refusal under the per-source contract): `select`, the one-time catch-up.
Equal or missing volumes at an edge cannot say which bar is whole: `reserve`. A real difference or
a held refused value already in canonical stops the series (nothing written).

A `reserve` slot's whole session date is left out of the selection this script runs, so canonical
keeps its row there until the vendor serves the slot again through the fetcher (the edge fix in
src/providers/ibkr.py makes that serve whole), and the gate reports the slot until then (exit 3).
Every reserve key is written to the report for that re-serve.

Apply, per series in one transaction: the selection advisory lock of the series
(bar_selection|symbol|timeframe, the same key select_and_write takes) is held from the re-read
through the commit, the plan is recomputed under it, the repair load is recorded, raw is written
through services/ohlcv_raw_writer.py (write_raw repair mode, hold_legacy_refusal), and
services/bar_selection.select_and_write re-selects every date of the series except the reserve
dates. The canonical rows selection changes are computed first with the same pure function and
written to the report; a selection result that disagrees with that count rolls the series back.
Dry run by default; --apply writes.

Exit codes: 0 every series planned or applied with nothing left; 1 a series was stopped (real
difference, held value in canonical, or a write that disagreed with its plan); 3 reserve slots
remain (they need the re-serve).
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import sys
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from scripts.ops.bars import ops_selection_gate as gate  # noqa: E402
from services.bar_selection import select_and_write  # noqa: E402
from services.ohlcv_ingress_contract import read_raw_params  # noqa: E402
from services.ohlcv_raw_writer import RawRow, hold_legacy_refusal, write_raw  # noqa: E402
from src.intelligence.bars.selection import SESSION_TZ, Candidate, session_date  # noqa: E402

CALLER = "raw-repair-191"
DESTINATION_RAW = "raw"
RESTORE = "restore"
RESTORE_PENDING = "restore_pending"
SELECT = "select"
RESERVE = "reserve"
BAR_SECONDS = {"1m": 60, "5m": 300, "4h": 14400}
_FAR_PAST = datetime(1990, 1, 1, tzinfo=UTC)
_FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
_REQUEST_ENDS_SQL = (
    "SELECT DISTINCT window_end FROM ohlcv_request WHERE symbol = %s AND timeframe = %s "
    "AND source = %s"
)
_INSERT_LOAD_SQL = (
    "INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, requested_end, "
    "outcome, n_bars, n_new, n_changed, first_bar, last_bar, detail, caller, destination, "
    "n_unchanged, n_removed, n_archived) "
    "VALUES (%s, %s, %s, %s, %s, %s, 'applied', %s, 0, %s, %s, %s, %s, %s, %s, 0, 0, 0)"
)


# --------------------------------------------------------------------------------------
# Pure core
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotAction:
    """What the repair does at one explained slot."""

    timestamp: datetime
    vendor: str
    kind: str
    cls: str
    action: str
    canonical: gate.Values | None
    raw: gate.Values | None
    edge: bool
    refused_load_id: Any = None
    reason: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.astimezone(UTC).isoformat(),
            "vendor": self.vendor,
            "kind": self.kind,
            "class": self.cls,
            "action": self.action,
            "canonical": None if self.canonical is None else list(self.canonical),
            "raw": None if self.raw is None else list(self.raw),
            "edge": self.edge,
            "refused_load_id": None if self.refused_load_id is None else str(self.refused_load_id),
            "reason": self.reason,
        }


@dataclass
class SeriesPlan:
    symbol: str
    timeframe: str
    actions: list[SlotAction] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def by_action(self) -> Counter:
        return Counter(a.action for a in self.actions)

    def reserve_dates(self) -> list[date]:
        return sorted({session_date(a.timestamp) for a in self.actions if a.action == RESERVE})


def at_edge(ts: datetime, seconds: int, request_ends: Sequence[datetime]) -> bool:
    """True when a request of the series ended strictly inside the bar [ts, ts + seconds):
    that request's answer held the bar truncated at the request end (`request_ends` sorted)."""
    i = bisect.bisect_right(request_ends, ts)
    return i < len(request_ends) and request_ends[i] < ts + timedelta(seconds=seconds)


def _volume(values: gate.Values | None) -> int | None:
    return None if values is None else values[4]


def whole_side(canonical: gate.Values, raw: gate.Values) -> str | None:
    """'canonical' or 'raw', the side holding the whole bar at a chunk edge (more volume), or
    None when the volumes cannot tell (equal or missing)."""
    vc, vr = _volume(canonical), _volume(raw)
    if vc is None or vr is None or vc == vr:
        return None
    return "canonical" if vc > vr else "raw"


def plan_series(
    symbol: str,
    timeframe: str,
    canonical: Mapping[datetime, gate.Row],
    selected: Mapping[datetime, gate.Row],
    evidence: gate.Evidence,
    request_ends: Sequence[datetime],
) -> SeriesPlan:
    """The action of every explained slot of one series (module docstring)."""
    plan = SeriesPlan(symbol, timeframe)
    seconds = BAR_SECONDS[timeframe]
    ends = sorted(request_ends)
    for ts, (kind, cls) in gate.diff_rows(canonical, selected, evidence):
        c, s = canonical.get(ts), selected.get(ts)
        if cls == gate.REAL:
            plan.blockers.append(f"{ts.isoformat()} {kind}: real difference")
            continue
        vk = (s or c)[0]
        if cls == gate.CROSS_VENDOR:
            plan.actions.append(
                SlotAction(ts, *vk, cls, SELECT, c and c[1], s and s[1], False, None, "catch-up")
            )
            continue
        assert c is not None and s is not None  # VALUE classes compare two rows of one key
        edge = at_edge(ts, seconds, ends)
        whole = whole_side(c[1], s[1]) if edge else None
        key = (ts, *vk)
        if cls == gate.SELF_RESTATEMENT:
            load = evidence.refused_serves[key]
            if not edge:
                later = evidence.later().find(ts, vk[0], load.loaded_at)
                action, reason = (
                    (RESTORE, f"re-served by applied load {later.load_id}")
                    if later is not None
                    else (RESTORE_PENDING, "no later serve: refused value held")
                )
            elif whole == "canonical":
                action, reason = RESTORE, "edge: refused serve truncated"
            else:
                action, reason = RESERVE, f"edge: whole bar side {whole or 'unknown'}"
            plan.actions.append(
                SlotAction(ts, *vk, cls, action, c[1], s[1], edge, load.load_id, reason)
            )
            continue
        # restated_after_copy
        if not edge:
            action, reason = RESTORE, "raw stale: canonical is the later serve"
        elif whole == "raw":
            action, reason = SELECT, "edge: canonical truncated, raw whole"
        else:
            action, reason = RESERVE, f"edge: whole bar side {whole or 'unknown'}"
        plan.actions.append(SlotAction(ts, *vk, cls, action, c[1], s[1], edge, None, reason))
    for key in evidence.refused_serves:
        row = canonical.get(key[0])
        if evidence.held(key, row) and row == (key[1:], evidence.raw.get(key)):
            plan.blockers.append(f"{key[0].isoformat()}: a held refused value is in canonical")
    return plan


def selection_windows(reserve_dates: Sequence[date]) -> list[tuple[datetime, datetime]]:
    """[start, end) UTC windows covering every instant except the session dates given (each
    session date is its America/New_York calendar day)."""
    windows: list[tuple[datetime, datetime]] = []
    start = _FAR_PAST
    for day in sorted(set(reserve_dates)):
        day_start = datetime.combine(day, time(), SESSION_TZ).astimezone(UTC)
        day_end = datetime.combine(day + timedelta(days=1), time(), SESSION_TZ).astimezone(UTC)
        if day_start > start:
            windows.append((start, day_start))
        start = max(start, day_end)
    windows.append((start, _FAR_FUTURE))
    return windows


def repaired_candidates(
    candidates: Sequence[Candidate], actions: Sequence[SlotAction]
) -> list[Candidate]:
    """The raw candidates after the restores (the accepted value replaces the raw one)."""
    restore = {
        (a.timestamp, a.vendor, a.kind): a.canonical
        for a in actions
        if a.action in (RESTORE, RESTORE_PENDING)
    }
    out: list[Candidate] = []
    for c in candidates:
        values = restore.get((c.timestamp, c.vendor, c.kind))
        out.append(
            c
            if values is None
            else Candidate(c.timestamp, c.symbol, c.timeframe, c.vendor, c.kind, *values)
        )
    return out


def canonical_changes(
    canonical: Mapping[datetime, gate.Row],
    selected: Mapping[datetime, gate.Row],
    reserve_dates: Sequence[date],
) -> tuple[list[dict[str, Any]], int, int]:
    """(changed slots with old and new rows, new count, replaced count) selection will write
    outside the reserve dates; canonical rows selection does not hold are left alone, as the
    writer leaves them."""
    skip = set(reserve_dates)
    changes: list[dict[str, Any]] = []
    n_new = n_replaced = 0
    for ts in sorted(selected):
        if session_date(ts) in skip:
            continue
        old, new = canonical.get(ts), selected[ts]
        if old == new:
            continue
        n_new += old is None
        n_replaced += old is not None
        changes.append(
            {
                "timestamp": ts.astimezone(UTC).isoformat(),
                "old": None if old is None else {"vk": list(old[0]), "values": list(old[1])},
                "new": {"vk": list(new[0]), "values": list(new[1])},
            }
        )
    return changes, n_new, n_replaced


# --------------------------------------------------------------------------------------
# Database edges
# --------------------------------------------------------------------------------------


def read_series(cur: Any, symbol: str, timeframe: str, policy, kind_order):
    canonical = gate.read_canonical(cur, "market_data_ohlcv", "source", symbol, timeframe)
    candidates = gate.read_candidates(cur, symbol, timeframe)
    evidence = gate.read_evidence(cur, symbol, timeframe, candidates)
    vendors = {k[1] for k in evidence.refused_serves} | {"ibkr"}
    ends: list[datetime] = []
    for vendor in sorted(vendors):
        cur.execute(_REQUEST_ENDS_SQL, (symbol, timeframe, vendor))
        ends += [r[0] for r in cur.fetchall()]
    selected, _ = gate.selected_rows(candidates, policy, kind_order)
    return canonical, candidates, evidence, selected, ends


def _raw_row(symbol: str, timeframe: str, action: SlotAction, values: gate.Values) -> RawRow:
    return RawRow(action.timestamp, symbol, timeframe, action.vendor, action.kind, *values)


def apply_series(conn: Any, plan_in: SeriesPlan, params: Any, policy, kind_order) -> dict[str, Any]:
    """Re-plan under the series lock and write it (module docstring); the caller commits."""
    symbol, timeframe = plan_in.symbol, plan_in.timeframe
    # Lock order as the ingress contract takes it: the raw writer's series locks first, then the
    # selection lock of the series (select_and_write takes it again; advisory locks stack).
    series_locked = sorted({(a.vendor, a.kind) for a in plan_in.actions})
    with conn.cursor() as cur:
        for vendor, kind in series_locked:
            cur.execute(_LOCK_SQL, ("|".join((symbol, timeframe, vendor, kind)),))
        cur.execute(_LOCK_SQL, (f"bar_selection|{symbol}|{timeframe}",))
        canonical, candidates, evidence, selected, ends = read_series(
            cur, symbol, timeframe, policy, kind_order
        )
    plan = plan_series(symbol, timeframe, canonical, selected, evidence, ends)
    if plan.blockers:
        raise RuntimeError(f"{symbol} {timeframe}: blocked under the lock: {plan.blockers[:3]}")
    restores = [a for a in plan.actions if a.action in (RESTORE, RESTORE_PENDING)]
    unlocked = {(a.vendor, a.kind) for a in restores} - set(series_locked)
    if unlocked:
        raise RuntimeError(f"{symbol} {timeframe}: plan changed under the lock: {sorted(unlocked)}")
    loads: list[str] = []
    for vendor in sorted({a.vendor for a in restores}):
        mine = [a for a in restores if a.vendor == vendor]
        stamps = sorted(a.timestamp for a in mine)
        load_id = uuid.uuid4()
        detail = (
            f"raw repair (191-07 review findings 2 and 4): {len(mine)} raw rows put back to the "
            f"value the vendor served and canonical holds; {sum(a.action == RESTORE_PENDING for a in mine)} "
            "refused values held as pending under their refused loads"
        )
        with conn.cursor() as cur:
            cur.execute(
                _INSERT_LOAD_SQL,
                (
                    load_id,
                    symbol,
                    timeframe,
                    vendor,
                    gate.utc_date(stamps[0]),
                    gate.utc_date(stamps[-1]),
                    len(mine),
                    len(mine),
                    gate.utc_date(stamps[0]),
                    gate.utc_date(stamps[-1]),
                    detail,
                    CALLER,
                    DESTINATION_RAW,
                ),
            )
        deltas = write_raw(
            conn,
            [_raw_row(symbol, timeframe, a, a.canonical) for a in mine],
            load_id=load_id,
            request_id=None,
            vendor_codes=params.vendor_codes,
            kind_codes=params.kind_codes,
            batch_rows=params.write.batch_rows,
            future_tolerance_s=params.write.future_tolerance_s,
            repair=True,
        )
        if sum(d.new for d in deltas) or sum(d.changed for d in deltas) != len(mine):
            raise RuntimeError(
                f"{symbol} {timeframe} {vendor}: raw repair wrote "
                f"{[(d.new, d.changed, d.unchanged) for d in deltas]}, planned {len(mine)} changed"
            )
        loads.append(str(load_id))
    by_refused: dict[Any, list[SlotAction]] = defaultdict(list)
    for a in restores:
        if a.action == RESTORE_PENDING:
            by_refused[a.refused_load_id].append(a)
    n_pending = 0
    for refused_load_id, held in sorted(by_refused.items(), key=lambda kv: str(kv[0])):
        n_pending += hold_legacy_refusal(
            conn,
            [_raw_row(symbol, timeframe, a, a.raw) for a in held],
            load_id=refused_load_id,
            vendor_codes=params.vendor_codes,
            kind_codes=params.kind_codes,
            future_tolerance_s=params.write.future_tolerance_s,
        )
    reserve = plan.reserve_dates()
    after, _ = gate.selected_rows(repaired_candidates(candidates, plan.actions), policy, kind_order)
    changes, n_new, n_replaced = canonical_changes(canonical, after, reserve)
    got_new = got_replaced = 0
    for start, end in selection_windows(reserve):
        result = select_and_write(
            conn,
            symbols=[symbol],
            timeframe=timeframe,
            start=start,
            end=end,
            policy_rows=policy,
            kind_order=kind_order,
            batch_rows=params.write.batch_rows,
        )
        got_new += result.new
        got_replaced += result.changed
    if (got_new, got_replaced) != (n_new, n_replaced):
        raise RuntimeError(
            f"{symbol} {timeframe}: selection wrote new {got_new} replaced {got_replaced}, "
            f"planned new {n_new} replaced {n_replaced}"
        )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "actions": dict(plan.by_action()),
        "repair_loads": loads,
        "pending_written": n_pending,
        "canonical_new": n_new,
        "canonical_replaced": n_replaced,
        "canonical_changes": changes,
        "reserve": [a.to_json() for a in plan.actions if a.action == RESERVE],
        "slots": [a.to_json() for a in plan.actions],
    }


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run(args: argparse.Namespace) -> int:
    batch_rows, timeout_s = asyncio.run(gate._read_apr())
    del batch_rows  # the writers take the raw contract's own settings below
    conn = gate.open_connection(timeout_s)
    out = Path(args.out) if args.out else gate._LOG_DIR / f"raw_repair_191_{_stamp()}.json"
    series_out: list[dict[str, Any]] = []
    stopped: list[str] = []
    try:
        with conn.cursor() as cur:
            policy = gate.read_policy(cur)
            kind_order = gate.read_kind_order(cur)
            params = read_raw_params(cur)
            symbols = gate.series_symbols(cur, args.symbols)
        conn.rollback()
        for symbol in symbols:
            for timeframe in args.timeframes:
                with conn.cursor() as cur:
                    canonical, _cands, evidence, selected, ends = read_series(
                        cur, symbol, timeframe, policy, kind_order
                    )
                conn.rollback()
                plan = plan_series(symbol, timeframe, canonical, selected, evidence, ends)
                if not plan.actions and not plan.blockers:
                    continue
                counts = dict(plan.by_action())
                print(f"{symbol} {timeframe}: {counts} blockers {len(plan.blockers)}", flush=True)
                if plan.blockers:
                    stopped.append(f"{symbol} {timeframe}: {plan.blockers[:3]}")
                    series_out.append(
                        {"symbol": symbol, "timeframe": timeframe, "blockers": plan.blockers}
                    )
                    continue
                if not args.apply:
                    series_out.append(
                        {
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "actions": counts,
                            "reserve": [a.to_json() for a in plan.actions if a.action == RESERVE],
                            "slots": [a.to_json() for a in plan.actions],
                        }
                    )
                    continue
                try:
                    done = apply_series(conn, plan, params, policy, kind_order)
                    conn.commit()
                except Exception as error:
                    conn.rollback()
                    stopped.append(f"{symbol} {timeframe}: {type(error).__name__}: {error}")
                    print(f"  STOPPED: {error}", flush=True)
                    continue
                print(
                    f"  applied: pending {done['pending_written']}, canonical new "
                    f"{done['canonical_new']} replaced {done['canonical_replaced']}",
                    flush=True,
                )
                series_out.append(done)
    finally:
        conn.close()
    totals: Counter = Counter()
    for entry in series_out:
        totals.update(entry.get("actions", {}))
    reserve_keys = [
        {"symbol": e["symbol"], "timeframe": e["timeframe"], **r}
        for e in series_out
        for r in e.get("reserve", [])
    ]
    report = {
        "meta": {"mode": "apply" if args.apply else "dry-run", "generated": _stamp()},
        "totals": {
            "series": len(series_out),
            "actions": dict(totals),
            "pending_written": sum(e.get("pending_written", 0) for e in series_out),
            "canonical_new": sum(e.get("canonical_new", 0) for e in series_out),
            "canonical_replaced": sum(e.get("canonical_replaced", 0) for e in series_out),
            "reserve_keys": len(reserve_keys),
            "stopped": stopped,
        },
        "reserve_keys": reserve_keys,
        "series": series_out,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report["totals"], indent=1, default=str))
    print(f"report: {out}")
    if stopped:
        return 1
    return 3 if reserve_keys else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--timeframes", nargs="+", default=["5m"], choices=sorted(BAR_SECONDS))
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--out", default=None)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
