"""ops_refusal_rejudge.py - re-judge each retired-path refused load under the per-source contract.

Second review of plan 191-07 (.planning/phases/191-unified-raw-bar-table/191-07-FIXES-REVIEW.md),
findings 1 and 2; D-191-M (docs/plans/2026-10-12-unified-raw-bar-table-design.md).

The retired fetch path refused a chunk when it restated more than the allowed share of whatever
canonical held, Alpaca rows included. The per-source contract (D-191-K, services/
ohlcv_ingress_contract.py) judges a vendor against its OWN stored values and applies one outcome
to the whole offer: accepted, every offered bar lands last-wins; refused, every offered bar that
differs from the vendor's stored value is held pending, new bars included, and raw keeps the
stored values. The first repair (ops_raw_repair.py) split those loads key by key (new keys taken,
changed keys held) and excused refused values on date-level evidence. This script replaces that
with one decision per load, recorded in its report and on the series' repair load:

1. Offer. The rows the refused load archived (ohlcv_intraday_raw_archive, archived_at = the
   load's loaded_at). A load with no archived rows (n_archived 0) cannot be judged: its offer is
   lost, and the report says so.
2. Complete bars only (src/intelligence/bars/complete_bars.py): an offered bar that straddles its
   request's end, was still forming at the answer, or closed the session before the settle delay
   is not an answer. It is neither judged nor stored nor held; the report lists it.
3. The vendor's own value at the refusal: the canonical row at that instant when it was the
   vendor's (the retired path kept the vendor's history only in canonical: every IBKR archive row
   of these series belongs to a refused load), reconstructed backward from the current canonical
   (before the first repair, from its reports) through the retired path's revision rows logged
   after the refusal; or the offer of an earlier load of the series this script accepts. A stored
   value that a request edge truncated (a request of the series ended inside the bar and a
   complete offer holds more volume) is not an answer either and counts as not stored.
4. Judgment: write_contract.should_refuse over (changed, stored) with the APR thresholds.
5. The vendor's latest answer at each offered key, which raw must hold: the latest of the
   accepted offers and the later applied serves that answered the exact key (a raw or revision
   row of that load at the key, or its request window holding the whole bar; GE 2e726390), each
   only when complete; else the stored value of step 3; else nothing (no raw row).
6. Pending holds (D-191-I): every complete offered value of a refused load that differs from the
   vendor's stored value, unless the vendor answered the key again after the refusal.
7. Re-serve list: keys where raw holds less volume than a held offer (an incomplete bar kept, ADM
   2026-10-12 19:55), and keys left with no raw row although the vendor offered a bar.

Apply, per series in one transaction (the raw series lock, then the selection lock, re-planned
under them): raw is set to the target through services/ohlcv_raw_writer.py (repair mode, served_at
the serve time of the answer or NULL when unknown; a key with no target is withdrawn, its old
value logged), pending rows are added under their refused load or released where the decision no
longer holds them, then services/bar_selection.py re-selects the series and retracts canonical
rows at withdrawn keys no vendor holds. Nothing else is written. Dry run by default.

Exit codes: 0 applied or planned with nothing left; 1 a series stopped; 3 re-serve keys remain.
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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from scripts.ops.bars import ops_selection_gate as gate  # noqa: E402
from services.bar_selection import retract_unselected_slots, select_and_write  # noqa: E402
from services.ohlcv_ingress_contract import read_raw_params  # noqa: E402
from services.ohlcv_raw_writer import (  # noqa: E402
    RawRow,
    hold_legacy_refusal,
    release_legacy_pending,
    withdraw_raw_rows,
    write_raw,
)
from src.config.config_service import ConfigService  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.intelligence.bars.complete_bars import split_complete  # noqa: E402
from src.intelligence.bars.vendor_kind import LABEL_TO_VENDOR_KIND  # noqa: E402
from src.intelligence.bars.write_contract import (  # noqa: E402
    WriteDelta,
    revision_ratio,
    should_refuse,
)

CALLER = "refusal-rejudge-191"
FIRST_REPAIR_CALLER = "raw-repair-191"
TIMEFRAME = "5m"
OWN: tuple[str, str] = ("ibkr", "named")
SETTLE_KEY = "threshold.bar_integrity.session_close_settle_s"
ACCEPTED, HELD, UNJUDGEABLE = "accepted", "held", "unjudgeable"
_BAR = timedelta(minutes=5)
_FAR_PAST = datetime(1990, 1, 1, tzinfo=UTC)
_FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
_FIRST_REPAIR_REPORTS = (
    "raw_repair_191_apply_HD.json",
    "raw_repair_191_apply.json",
    "raw_repair_191_apply_pass2.json",
)

Values = tuple  # (open, high, low, close, volume)


# --------------------------------------------------------------------------------------
# Pure core
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Event:
    """A complete answer of the vendor at one key: when it was served and its value."""

    at: datetime
    values: Values
    source: str  # "offer <load>" or "serve <load>"
    served_at: datetime | None


@dataclass
class Judgement:
    load_id: str
    loaded_at: datetime
    n_offered: int = 0
    n_partial: int = 0
    n_stored: int = 0
    n_changed: int = 0
    n_new: int = 0
    ratio: float = 0.0
    outcome: str = UNJUDGEABLE
    retired_detail: str = ""
    request: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "load_id": self.load_id,
            "loaded_at": self.loaded_at.isoformat(),
            "n_offered": self.n_offered,
            "n_partial": self.n_partial,
            "n_stored": self.n_stored,
            "n_changed": self.n_changed,
            "n_new": self.n_new,
            "ratio": round(self.ratio, 6),
            "outcome": self.outcome,
            "retired_detail": self.retired_detail,
            "request": self.request,
        }


@dataclass
class SeriesInputs:
    """Everything the decision reads for one (symbol, 5m) series, the vendor's (ibkr, named)."""

    symbol: str
    loads: list[gate.LoadFact]
    requests: dict[Any, gate.RequestFact]  # load_id -> matched request
    details: dict[Any, str]  # load_id -> retired detail text
    offers: dict[Any, dict[datetime, Values]]  # refused load_id -> archived offer
    # timestamp -> [(loaded_at, (vendor, kind), old values)] of retired-path canonical revisions
    canon_revisions: dict[datetime, list[tuple[datetime, tuple[str, str], Values]]]
    canon_before_repair: dict[datetime, tuple[tuple[str, str], Values] | None]
    slot_loads: dict[datetime, set[Any]]
    request_ends: list[datetime]
    # load_id -> [first served stamp, last served stamp + bar] (gate.served_ranges): the exact
    # keys an applied serve answered, never its request window (third review, finding 1)
    ranges: dict[Any, tuple[datetime, datetime]] = field(default_factory=dict)
    # timestamp -> when a later load first wrote the key (a load whose every bar was new): the
    # key holds no value of the vendor's before that instant
    first_written: dict[datetime, datetime] = field(default_factory=dict)


@dataclass
class SeriesDecision:
    symbol: str
    judgements: list[Judgement] = field(default_factory=list)
    target: dict[datetime, Event | None] = field(default_factory=dict)
    pending: dict[Any, dict[datetime, Values]] = field(default_factory=dict)
    partial: dict[Any, list[datetime]] = field(default_factory=dict)
    reserve: list[dict[str, Any]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def _own(row: tuple[tuple[str, str], Values] | None) -> Values | None:
    return row[1] if row is not None and row[0] == OWN else None


def canon_at(inputs: SeriesInputs, ts: datetime, t: datetime) -> tuple[Any, datetime | None]:
    """(canonical row at `ts` just before `t`, the time the retired path last wrote it before
    `t` or None): the old value of the earliest revision logged after `t`, else the canonical
    row before the first repair. A key a later load first wrote (`first_written` after `t`) and
    no revision put on record at or before `t` held nothing at `t` (third review of plan
    191-07, finding 1: ADM 2026-10-12 16:00 to 19:55 arrived at 04:27, after the 23:23
    refusal, and read as stored at it)."""
    revs = inputs.canon_revisions.get(ts, [])
    after = [r for r in revs if r[0] > t]
    before = [r[0] for r in revs if r[0] <= t]
    written = max(before) if before else None
    born = inputs.first_written.get(ts)
    if born is not None and born > t and written is None:
        return None, None
    if after:
        first = min(after, key=lambda r: r[0])
        return (first[1], first[2]), written
    return inputs.canon_before_repair.get(ts), written


def _edge(ts: datetime, ends: Sequence[datetime]) -> bool:
    i = bisect.bisect_right(ends, ts)
    return i < len(ends) and ends[i] < ts + timedelta(minutes=5)


def _complete(
    ts: datetime, request: gate.RequestFact | None, settle: timedelta, fallback: datetime
) -> bool:
    """One bar of `ts` served by `request` (answered_at, window_end) is a complete answer; with
    no matched request the load time stands in for the answer (flagged by the caller)."""
    answered = request.answered_at if request is not None else fallback
    end = request.window_end if request is not None else None
    kept, _ = split_complete(
        [{"timestamp": ts}], TIMEFRAME, answered_at=answered, request_end=end, settle=settle
    )
    return bool(kept)


def decide_series(
    inputs: SeriesInputs, *, max_ratio: float, min_stored: int, settle: timedelta
) -> SeriesDecision:
    """The one-outcome-per-load decision and the vendor's latest answer at every offered key."""
    decision = SeriesDecision(inputs.symbol)
    refused = sorted(
        (load for load in inputs.loads if load.outcome == "refused"), key=lambda x: x.loaded_at
    )
    if not refused:
        return decision
    serves = sorted(
        (
            load
            for load in inputs.loads
            if load.outcome == "applied" and load.is_serve and load.vendor == OWN[0]
        ),
        key=lambda x: x.loaded_at,
    )
    by_id = {load.load_id: load for load in inputs.loads}
    accepted_offers: dict[datetime, list[Event]] = defaultdict(list)
    complete_offers: dict[Any, dict[datetime, Values]] = {}
    own_at_refusal: dict[Any, dict[datetime, Values | None]] = {}

    def base_value(ts: datetime, t: datetime) -> tuple[Values | None, datetime | None]:
        row, written = canon_at(inputs, ts, t)
        value = _own(row)
        if value is not None and _edge(ts, inputs.request_ends):
            # a request edge cut a bar here: the stored value is the truncated one when a
            # complete offer at the key carries more volume
            fuller = [
                v[4]
                for offers in complete_offers.values()
                for k, v in offers.items()
                if k == ts and v[4] is not None
            ]
            if value[4] is not None and fuller and max(fuller) > value[4]:
                return None, written
        return value, written

    def own_value(ts: datetime, t: datetime) -> Values | None:
        value, written = base_value(ts, t)
        earlier = [e for e in accepted_offers.get(ts, []) if e.at < t]
        if earlier:
            last = max(earlier, key=lambda e: e.at)
            if written is None or written < last.at:
                return last.values
        return value

    for load in refused:
        judgement = Judgement(
            str(load.load_id),
            load.loaded_at,
            retired_detail=inputs.details.get(load.load_id, ""),
        )
        decision.judgements.append(judgement)
        offer = inputs.offers.get(load.load_id, {})
        if not offer:
            continue
        request = inputs.requests.get(load.load_id)
        if request is None:
            decision.flags.append(f"{load.load_id}: no request matched; load time as answer")
        else:
            judgement.request = (
                f"{request.window_start.isoformat()}..{request.window_end.isoformat()} "
                f"answered {request.answered_at.isoformat()}"
            )
        complete = {
            ts: v for ts, v in offer.items() if _complete(ts, request, settle, load.loaded_at)
        }
        decision.partial[load.load_id] = sorted(set(offer) - set(complete))
        complete_offers[load.load_id] = complete
        own = {ts: own_value(ts, load.loaded_at) for ts in complete}
        own_at_refusal[load.load_id] = own
        stored = [ts for ts, v in own.items() if v is not None]
        changed = {ts: (own[ts], complete[ts]) for ts in stored if own[ts] != complete[ts]}
        delta = WriteDelta(changed=changed)  # type: ignore[arg-type]
        judgement.n_offered = len(offer)
        judgement.n_partial = len(offer) - len(complete)
        judgement.n_stored = len(stored)
        judgement.n_changed = len(changed)
        judgement.n_new = len(complete) - len(stored)
        judgement.ratio = revision_ratio(delta, len(stored))
        refuse = should_refuse(delta, len(stored), max_ratio, min_stored=min_stored, waived=False)
        judgement.outcome = HELD if refuse else ACCEPTED
        if not refuse:
            served = request.answered_at if request is not None else load.loaded_at
            for ts, values in complete.items():
                accepted_offers[ts].append(
                    Event(load.loaded_at, values, f"offer {load.load_id}", served)
                )

    first = refused[0].loaded_at
    keys = sorted({ts for offer in inputs.offers.values() for ts in offer})
    for ts in keys:
        events = list(accepted_offers.get(ts, []))
        for serve in serves:
            if serve.loaded_at <= first:
                continue
            request = inputs.requests.get(serve.load_id)
            wrote = serve.load_id in inputs.slot_loads.get(ts, ())
            served = inputs.ranges.get(serve.load_id)
            covered = served is not None and served[0] <= ts and ts + _BAR <= served[1]
            if not (wrote or covered):
                continue
            if not _complete(ts, request, settle, serve.loaded_at):
                continue
            row, _ = canon_at(inputs, ts, serve.loaded_at + timedelta(microseconds=1))
            value = _own(row)
            if value is None:
                decision.flags.append(
                    f"{ts.isoformat()}: {serve.load_id} served the key but canonical kept "
                    f"{row[0] if row else None}; its value is not on record"
                )
                continue
            served = request.answered_at if request is not None else None
            events.append(Event(serve.loaded_at, value, f"serve {serve.load_id}", served))
        if events:
            decision.target[ts] = max(events, key=lambda e: e.at)
        else:
            value, _ = base_value(ts, first)
            decision.target[ts] = None if value is None else Event(_FAR_PAST, value, "stored", None)
    for load in refused:
        judgement = next(j for j in decision.judgements if j.load_id == str(load.load_id))
        if judgement.outcome != HELD:
            continue
        held: dict[datetime, Values] = {}
        for ts, values in complete_offers[load.load_id].items():
            target = decision.target.get(ts)
            answered_later = target is not None and target.at > load.loaded_at
            if values == own_at_refusal[load.load_id][ts] or answered_later:
                continue
            if target is not None and target.values == values:
                continue
            held[ts] = values
        if held:
            decision.pending[load.load_id] = held
    for load_id, held in decision.pending.items():
        for ts, values in held.items():
            target = decision.target.get(ts)
            if target is None:
                reason = "no raw row: the vendor's offer is held"
            elif (
                values[4] is not None
                and target.values[4] is not None
                and values[4] > target.values[4]
            ):
                reason = "raw holds less volume than the held offer (incomplete bar)"
            else:
                continue
            decision.reserve.append(
                {
                    "symbol": inputs.symbol,
                    "timeframe": TIMEFRAME,
                    "timestamp": ts.isoformat(),
                    "vendor": OWN[0],
                    "kind": OWN[1],
                    "held_load_id": str(load_id),
                    "raw": None if target is None else list(target.values),
                    "held": list(values),
                    "reason": reason,
                }
            )
    for load_id, stamps in decision.partial.items():
        for ts in stamps:
            if int(ts.timestamp()) % 300:
                continue  # an off-grid partial is no slot of the grid; the grid bars stand
            if decision.target.get(ts) is None and ts.isoformat() not in {
                r["timestamp"] for r in decision.reserve
            }:
                decision.reserve.append(
                    {
                        "symbol": inputs.symbol,
                        "timeframe": TIMEFRAME,
                        "timestamp": ts.isoformat(),
                        "vendor": OWN[0],
                        "kind": OWN[1],
                        "held_load_id": None,
                        "raw": None,
                        "held": None,
                        "reason": f"only a partial bar was offered ({load_id})",
                    }
                )
    del by_id
    return decision


# --------------------------------------------------------------------------------------
# Database edges
# --------------------------------------------------------------------------------------

_ARCHIVE_SQL = (
    'SELECT "timestamp", source, open, high, low, close, volume, archived_at '
    "FROM ohlcv_intraday_raw_archive WHERE symbol = %s AND timeframe = %s "
    "AND archived_at = ANY(%s)"
)
_DETAIL_SQL = "SELECT load_id, detail FROM ohlcv_load WHERE load_id = ANY(%s)"
_REVISIONS_SQL = (
    'SELECT v."timestamp", v.vendor, v.kind, v.old_open, v.old_high, v.old_low, v.old_close, '
    "v.old_volume, v.origin, l.loaded_at, l.load_id, l.caller, l.outcome, l.destination "
    "FROM ohlcv_load l JOIN ohlcv_revision v "
    "ON v.load_id = l.load_id AND v.symbol = l.symbol AND v.timeframe = l.timeframe "
    'WHERE l.symbol = %s AND l.timeframe = %s AND v."timestamp" = ANY(%s)'
)
_RAW_AT_SQL = (
    'SELECT "timestamp", open, high, low, close, volume, served_at, load_id, request_id FROM ohlcv_raw '
    'WHERE symbol = %s AND timeframe = %s AND vendor = %s AND kind = %s AND "timestamp" = ANY(%s)'
)
_CANON_AT_SQL = (
    'SELECT "timestamp", source, open, high, low, close, volume FROM market_data_ohlcv '
    'WHERE symbol = %s AND timeframe = %s AND "timestamp" = ANY(%s)'
)
_VENDOR_KEYS_SQL = (
    'SELECT DISTINCT "timestamp" FROM ohlcv_raw WHERE symbol = %s AND timeframe = %s '
    "AND vendor = %s ORDER BY 1"
)
_REVISION_LOADS_SQL = (
    'SELECT "timestamp", load_id FROM ohlcv_revision WHERE symbol = %s AND timeframe = %s '
    "AND origin <> 'pending'"
)
_REQUEST_ENDS_SQL = (
    "SELECT DISTINCT window_end FROM ohlcv_request WHERE symbol = %s AND timeframe = %s "
    "AND source = %s"
)


def first_repair_canonical(log_dir: Path) -> dict[str, dict[datetime, Any]]:
    """symbol -> timestamp -> the canonical row before the first repair (ops_raw_repair.py
    reports, in run order; the earliest 'old' of a slot wins). None: no canonical row then."""
    out: dict[str, dict[datetime, Any]] = defaultdict(dict)
    for name in _FIRST_REPAIR_REPORTS:
        path = log_dir / name
        if not path.exists():
            raise SystemExit(f"first repair report missing: {path}")
        report = json.loads(path.read_text())
        for series in report.get("series", []):
            if series.get("timeframe") != TIMEFRAME:
                continue
            seen = out[series["symbol"]]
            for change in series.get("canonical_changes", []):
                ts = datetime.fromisoformat(change["timestamp"])
                if ts in seen:
                    continue
                old = change["old"]
                seen[ts] = None if old is None else (tuple(old["vk"]), tuple(old["values"]))
    return out


def _labels() -> dict[str, tuple[str, str]]:
    return dict(LABEL_TO_VENDOR_KIND)


def read_inputs(
    cur: Any, symbol: str, match_s: float, before_repair: Mapping[datetime, Any]
) -> tuple[SeriesInputs, dict[datetime, tuple[Any, ...]], dict[Any, set[datetime]]]:
    """(inputs, current raw (values, served_at, load_id) of the vendor at the offered keys,
    existing pending stamps per refused load)."""
    loads = gate.read_loads(cur, symbol, TIMEFRAME)
    cur.execute(gate._REQUESTS_SQL, (symbol, TIMEFRAME))
    requests = gate.match_requests(loads, [gate.RequestFact(*r) for r in cur.fetchall()], match_s)
    refused = [load for load in loads if load.outcome == "refused"]
    cur.execute(_DETAIL_SQL, ([load.load_id for load in refused],))
    details = {r[0]: r[1] or "" for r in cur.fetchall()}
    by_time = {load.loaded_at: load.load_id for load in refused}
    offers: dict[Any, dict[datetime, Values]] = defaultdict(dict)
    labels = _labels()
    cur.execute(_ARCHIVE_SQL, (symbol, TIMEFRAME, list(by_time)))
    for ts, source, o, h, lo, c, v, archived_at in cur.fetchall():
        if labels.get(source) != OWN:
            raise RuntimeError(f"{symbol}: refused archive row with label {source!r}")
        offers[by_time[archived_at]][ts] = (o, h, lo, c, v)
    stamps = sorted({ts for offer in offers.values() for ts in offer})
    canon_revisions: dict[datetime, list] = defaultdict(list)
    slot_loads: dict[datetime, set[Any]] = defaultdict(set)
    pending: dict[Any, set[datetime]] = defaultdict(set)
    cur.execute(_REVISIONS_SQL, (symbol, TIMEFRAME, stamps))
    for row in cur.fetchall():
        ts, vendor, kind, o, h, lo, c, v, origin, loaded_at, load_id, caller, outcome, dest = row
        if origin == "pending":
            if (vendor, kind) == OWN:
                pending[load_id].add(ts)
            continue
        slot_loads[ts].add(load_id)
        if (
            dest == "market_data_ohlcv"
            and outcome == "applied"
            and caller not in gate.NON_SERVE_CALLERS
        ):
            canon_revisions[ts].append((loaded_at, (vendor, kind), (o, h, lo, c, v)))
    raw: dict[datetime, tuple[Any, ...]] = {}
    cur.execute(_RAW_AT_SQL, (symbol, TIMEFRAME, *OWN, stamps))
    for ts, o, h, lo, c, v, served_at, load_id, request_id in cur.fetchall():
        raw[ts] = ((o, h, lo, c, v), served_at, load_id, request_id)
        if load_id is not None:
            slot_loads[ts].add(load_id)
    cur.execute(_CANON_AT_SQL, (symbol, TIMEFRAME, stamps))
    canon_now: dict[datetime, Any] = {}
    for ts, source, o, h, lo, c, v in cur.fetchall():
        vk = labels.get(source)
        canon_now[ts] = None if vk is None else (vk, (o, h, lo, c, v))
    canon_before = {
        ts: before_repair[ts] if ts in before_repair else canon_now.get(ts) for ts in stamps
    }
    cur.execute(_REQUEST_ENDS_SQL, (symbol, TIMEFRAME, OWN[0]))
    ends = sorted(r[0] for r in cur.fetchall())
    ranges, first_written = served_evidence(cur, symbol, loads, match_s)
    inputs = SeriesInputs(
        symbol,
        loads,
        requests,
        details,
        dict(offers),
        dict(canon_revisions),
        canon_before,
        dict(slot_loads),
        ends,
        ranges,
        {ts: first_written[ts] for ts in stamps if ts in first_written},
    )
    return inputs, raw, dict(pending)


def served_evidence(
    cur: Any, symbol: str, loads: Sequence[gate.LoadFact], match_s: float
) -> tuple[dict[Any, tuple[datetime, datetime]], dict[datetime, datetime]]:
    """(load_id -> served range, timestamp -> first write) of the vendor's applied serves over
    the whole series (gate.served_ranges). A serve whose every bar was new (n_new = n_bars) first
    wrote each vendor key in its range."""
    cur.execute(_VENDOR_KEYS_SQL, (symbol, TIMEFRAME, OWN[0]))
    keys = [r[0] for r in cur.fetchall()]
    rows: dict[datetime, set[Any]] = defaultdict(set)
    cur.execute(gate._RAW_LOADS_SQL, (symbol, TIMEFRAME))
    for ts, load_id in cur.fetchall():
        rows[ts].add(load_id)
    cur.execute(_REVISION_LOADS_SQL, (symbol, TIMEFRAME))
    for ts, load_id in cur.fetchall():
        rows[ts].add(load_id)
    cur.execute(gate._REQUESTS_SQL, (symbol, TIMEFRAME))
    requests = [gate.RequestFact(*r) for r in cur.fetchall()]
    cur.execute(gate._RAW_REQUESTS_SQL, (symbol, TIMEFRAME))
    request_rows = cur.fetchall()
    ranges = gate.served_ranges(
        loads,
        requests,
        {OWN[0]: keys},
        match_s,
        row_stamps=gate.load_row_stamps(rows, loads, requests, request_rows, match_s),
        bar=_BAR,
    )
    first_written: dict[datetime, datetime] = {}
    by_id = {load.load_id: load for load in loads}
    for load_id, (start, end) in ranges.items():
        load = by_id[load_id]
        if load.vendor != OWN[0] or not load.n_bars or load.n_new != load.n_bars:
            continue
        lo, hi = bisect.bisect_left(keys, start), bisect.bisect_left(keys, end)
        for ts in keys[lo:hi]:
            if ts not in first_written or load.loaded_at < first_written[ts]:
                first_written[ts] = load.loaded_at
    return ranges, first_written


@dataclass
class SeriesPlan:
    write: dict[datetime, Event] = field(default_factory=dict)  # raw <- target
    restamp: dict[datetime, datetime | None] = field(default_factory=dict)  # served_at only
    withdraw: dict[datetime, Values] = field(default_factory=dict)  # raw row removed
    hold: dict[Any, dict[datetime, Values]] = field(default_factory=dict)
    release: dict[Any, list[datetime]] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        return {
            "raw_write": len(self.write),
            "raw_restamp": len(self.restamp),
            "raw_withdraw": len(self.withdraw),
            "pending_add": sum(len(v) for v in self.hold.values()),
            "pending_release": sum(len(v) for v in self.release.values()),
        }


def linked_refused(
    raw: Mapping[datetime, tuple[Any, ...]], refused: Sequence[gate.LoadFact]
) -> dict[datetime, Any]:
    """timestamp -> the refused load a raw row names (its load_id, or for a backfill copy with no
    load_id its served_at equal to the refused load's loaded_at)."""
    by_id = {load.load_id for load in refused}
    by_time = {load.loaded_at: load.load_id for load in refused}
    out: dict[datetime, Any] = {}
    for ts, row in raw.items():
        served_at, load_id = row[1], row[2]
        if load_id is not None and load_id in by_id:
            out[ts] = load_id
        elif load_id is None and served_at in by_time:
            out[ts] = by_time[served_at]
    return out


def plan_writes(
    decision: SeriesDecision,
    raw: Mapping[datetime, tuple[Any, ...]],
    pending: Mapping[Any, set[datetime]],
    repair_loads: set[Any],
    linked: Mapping[datetime, Any] | None = None,
) -> SeriesPlan:
    """The writes that make raw and the pending holds equal the decision. A raw row that already
    holds the target value is restamped (served_at, lineage) when the first repair wrote it with
    its own write time, or when it still names a refused load: the decision is now the record
    of why the value is current, and a row naming a refused load would read as held."""
    linked = linked or {}
    plan = SeriesPlan()
    for ts, target in decision.target.items():
        current = raw.get(ts)
        if target is None:
            if current is not None:
                plan.withdraw[ts] = current[0]
            continue
        if current is None or current[0] != target.values:
            plan.write[ts] = target
        elif ts in linked or (current[2] in repair_loads and current[1] != target.served_at):
            # the first repair stamped served_at with its own write time (review 2, low item)
            plan.restamp[ts] = target.served_at
    for load_id, held in decision.pending.items():
        missing = {ts: v for ts, v in held.items() if ts not in pending.get(load_id, set())}
        if missing:
            plan.hold[load_id] = missing
    for load_id, stamps in pending.items():
        extra = sorted(stamps - set(decision.pending.get(load_id, {})))
        if extra:
            plan.release[load_id] = extra
    return plan


def _apr(key: str, default: float) -> float:
    async def read() -> float:
        cfg = ConfigService(get_settings().database_url)
        await cfg.initialize()
        try:
            return float(await cfg.get(key, default))
        finally:
            await cfg.close()

    return asyncio.run(read())


def _row(symbol: str, ts: datetime, values: Values) -> RawRow:
    return RawRow(ts, symbol, TIMEFRAME, *OWN, *values)


def apply_series(
    conn: Any, symbol: str, inputs_args: tuple, params: Any, thresholds: dict[str, Any]
) -> dict[str, Any]:
    """Lock, re-read, re-decide and write one series (module docstring); the caller commits."""
    match_s, before_repair = inputs_args
    with conn.cursor() as cur:
        cur.execute(_LOCK_SQL, ("|".join((symbol, TIMEFRAME, *OWN)),))
        cur.execute(_LOCK_SQL, (f"bar_selection|{symbol}|{TIMEFRAME}",))
        inputs, raw, pending = read_inputs(cur, symbol, match_s, before_repair)
    decision = decide_series(inputs, **thresholds)
    repair_loads = {x.load_id for x in inputs.loads if x.caller in (CALLER, FIRST_REPAIR_CALLER)}
    refused = [x for x in inputs.loads if x.outcome == "refused"]
    plan = plan_writes(decision, raw, pending, repair_loads, linked_refused(raw, refused))
    load_id = uuid.uuid4()
    outcomes = "; ".join(
        f"{j.load_id} {j.outcome} (changed {j.n_changed} / stored {j.n_stored} = {j.ratio:.4f}, "
        f"new {j.n_new}, partial {j.n_partial})"
        for j in decision.judgements
    )
    stamps = sorted({*plan.write, *plan.withdraw, *plan.restamp}) or sorted(decision.target)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, "
            "requested_end, outcome, n_bars, n_new, n_changed, first_bar, last_bar, detail, "
            "caller, destination, n_unchanged, n_removed, n_archived) VALUES "
            "(%s, %s, %s, %s, %s, %s, 'applied', %s, %s, %s, %s, %s, %s, %s, 'raw', 0, %s, 0)",
            (
                load_id,
                symbol,
                TIMEFRAME,
                OWN[0],
                gate.utc_date(stamps[0]),
                gate.utc_date(stamps[-1]),
                len(plan.write) + len(plan.withdraw),
                sum(1 for ts in plan.write if ts not in raw),
                sum(1 for ts in plan.write if ts in raw),
                gate.utc_date(stamps[0]),
                gate.utc_date(stamps[-1]),
                "refusal re-judge (191-07 second review, finding 2): " + outcomes,
                CALLER,
                len(plan.withdraw),
            ),
        )
    if plan.write:
        rows = [_row(symbol, ts, e.values) for ts, e in sorted(plan.write.items())]
        (delta,) = write_raw(
            conn,
            rows,
            load_id=load_id,
            request_id=None,
            vendor_codes=params.vendor_codes,
            kind_codes=params.kind_codes,
            batch_rows=params.write.batch_rows,
            future_tolerance_s=params.write.future_tolerance_s,
            repair=True,
            served_at={ts: e.served_at for ts, e in plan.write.items()},
        )
        if delta.new + delta.changed != len(rows):
            raise RuntimeError(f"{symbol}: raw write {delta.new}+{delta.changed} != {len(rows)}")
    if plan.restamp:
        write_raw(
            conn,
            [_row(symbol, ts, raw[ts][0]) for ts in sorted(plan.restamp)],
            load_id=load_id,
            request_id=None,
            vendor_codes=params.vendor_codes,
            kind_codes=params.kind_codes,
            batch_rows=params.write.batch_rows,
            future_tolerance_s=params.write.future_tolerance_s,
            repair=True,
            served_at=plan.restamp,
            restamp=True,
        )
    if plan.withdraw:
        n = withdraw_raw_rows(
            conn,
            [_row(symbol, ts, v) for ts, v in sorted(plan.withdraw.items())],
            load_id=load_id,
        )
        if n != len(plan.withdraw):
            raise RuntimeError(f"{symbol}: withdrew {n}, planned {len(plan.withdraw)}")
    n_held = 0
    for refused_id, held in sorted(plan.hold.items(), key=lambda kv: str(kv[0])):
        n_held += hold_legacy_refusal(
            conn,
            [_row(symbol, ts, v) for ts, v in sorted(held.items())],
            load_id=refused_id,
            vendor_codes=params.vendor_codes,
            kind_codes=params.kind_codes,
            future_tolerance_s=params.write.future_tolerance_s,
        )
    n_released = 0
    for refused_id, stamps_ in sorted(plan.release.items(), key=lambda kv: str(kv[0])):
        n_released += release_legacy_pending(
            conn, symbol, TIMEFRAME, *OWN, load_id=refused_id, timestamps=stamps_
        )
    selection = select_and_write(
        conn,
        symbols=[symbol],
        timeframe=TIMEFRAME,
        start=_FAR_PAST,
        end=_FAR_FUTURE,
        policy_rows=params.policy_rows,
        kind_order=params.kind_order,
        batch_rows=params.write.batch_rows,
    )
    retracted = retract_unselected_slots(
        conn,
        symbol=symbol,
        timeframe=TIMEFRAME,
        timestamps=sorted(plan.withdraw),
        policy_rows=params.policy_rows,
        kind_order=params.kind_order,
    )
    return {
        "symbol": symbol,
        "repair_load": str(load_id),
        "plan": plan.counts(),
        "pending_written": n_held,
        "pending_released": n_released,
        "canonical_new": selection.new,
        "canonical_replaced": selection.changed,
        "canonical_retracted": retracted,
        "selection_held": selection.held,
        "judgements": [j.to_json() for j in decision.judgements],
        "reserve": decision.reserve,
        "flags": decision.flags,
        "writes": [
            {
                "timestamp": ts.isoformat(),
                "old": None if ts not in raw else list(raw[ts][0]),
                "new": list(e.values),
                "source": e.source,
            }
            for ts, e in sorted(plan.write.items())
        ],
        "withdrawn": [
            {"timestamp": ts.isoformat(), "old": list(v)} for ts, v in sorted(plan.withdraw.items())
        ],
        # third review, low item: every released hold and every restamp with the lineage it
        # replaced (a restamp overwrites served_at, load_id and request_id without a revision)
        "released": {
            str(k): [t.isoformat() for t in v]
            for k, v in sorted(plan.release.items(), key=lambda kv: str(kv[0]))
        },
        "restamped": [
            {
                "timestamp": ts.isoformat(),
                "old_served_at": None if raw[ts][1] is None else raw[ts][1].isoformat(),
                "old_load_id": None if raw[ts][2] is None else str(raw[ts][2]),
                "old_request_id": (
                    None if len(raw[ts]) < 4 or raw[ts][3] is None else str(raw[ts][3])
                ),
                "new_served_at": None if new is None else new.isoformat(),
                "new_load_id": str(load_id),
            }
            for ts, new in sorted(plan.restamp.items())
        ],
    }


def refused_symbols(cur: Any) -> list[str]:
    cur.execute(
        "SELECT DISTINCT symbol FROM ohlcv_load WHERE timeframe = %s AND outcome = 'refused' "
        "ORDER BY symbol",
        (TIMEFRAME,),
    )
    return [r[0] for r in cur.fetchall()]


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run(args: argparse.Namespace) -> int:
    _batch, timeout_s, match_s = asyncio.run(gate._read_apr())
    settle = timedelta(seconds=_apr(SETTLE_KEY, 1800))
    before = first_repair_canonical(gate._LOG_DIR)
    conn = gate.open_connection(timeout_s)
    out = Path(args.out) if args.out else gate._LOG_DIR / f"refusal_rejudge_191_{_stamp()}.json"
    series_out: list[dict[str, Any]] = []
    stopped: list[str] = []
    try:
        with conn.cursor() as cur:
            params = read_raw_params(cur)
            symbols = args.symbols or refused_symbols(cur)
        conn.rollback()
        thresholds = {
            "max_ratio": params.thresholds.max_ratio,
            "min_stored": params.thresholds.min_stored,
            "settle": settle,
        }
        for symbol in symbols:
            with conn.cursor() as cur:
                inputs, raw, pending = read_inputs(cur, symbol, match_s, before.get(symbol, {}))
            conn.rollback()
            decision = decide_series(inputs, **thresholds)
            repair_loads = {
                x.load_id for x in inputs.loads if x.caller in (CALLER, FIRST_REPAIR_CALLER)
            }
            refused = [x for x in inputs.loads if x.outcome == "refused"]
            plan = plan_writes(decision, raw, pending, repair_loads, linked_refused(raw, refused))
            counts = plan.counts()
            outcomes = Counter(j.outcome for j in decision.judgements)
            print(
                f"{symbol}: {dict(outcomes)} {counts} reserve {len(decision.reserve)}", flush=True
            )
            if not args.apply:
                series_out.append(
                    {
                        "symbol": symbol,
                        "plan": counts,
                        "judgements": [j.to_json() for j in decision.judgements],
                        "reserve": decision.reserve,
                        "flags": decision.flags,
                        "partial": {
                            str(k): [t.isoformat() for t in v]
                            for k, v in decision.partial.items()
                            if v
                        },
                        "writes": [
                            {
                                "timestamp": ts.isoformat(),
                                "old": None if ts not in raw else list(raw[ts][0]),
                                "new": list(e.values),
                                "source": e.source,
                            }
                            for ts, e in sorted(plan.write.items())
                        ],
                        "withdraw": [ts.isoformat() for ts in sorted(plan.withdraw)],
                        "release": {
                            str(k): [t.isoformat() for t in v] for k, v in plan.release.items()
                        },
                    }
                )
                continue
            if not any(counts.values()):
                series_out.append(
                    {
                        "symbol": symbol,
                        "plan": counts,
                        "judgements": [j.to_json() for j in decision.judgements],
                        "reserve": decision.reserve,
                        "flags": decision.flags,
                    }
                )
                continue
            try:
                done = apply_series(
                    conn, symbol, (match_s, before.get(symbol, {})), params, thresholds
                )
                conn.commit()
            except Exception as error:
                conn.rollback()
                stopped.append(f"{symbol}: {type(error).__name__}: {error}")
                print(f"  STOPPED: {error}", flush=True)
                continue
            series_out.append(done)
    finally:
        conn.close()
    judgements = [j for s in series_out for j in s.get("judgements", [])]
    reserve = [r for s in series_out for r in s.get("reserve", [])]
    totals: Counter = Counter()
    for s in series_out:
        totals.update(s.get("plan", {}))
    report = {
        "meta": {"mode": "apply" if args.apply else "dry-run", "generated": _stamp()},
        "totals": {
            "series": len(series_out),
            "loads": dict(Counter(j["outcome"] for j in judgements)),
            "plan": dict(totals),
            "reserve_keys": len(reserve),
            "stopped": stopped,
        },
        "judgements": [
            {"symbol": s["symbol"], **j} for s in series_out for j in s.get("judgements", [])
        ],
        "reserve_keys": reserve,
        "series": series_out,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps(report["totals"], indent=1, default=str))
    print(f"report: {out}")
    if stopped:
        return 1
    return 3 if reserve else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--out", default=None)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
