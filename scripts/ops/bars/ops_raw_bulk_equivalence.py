"""Rolled-back equivalence proof of the bulk raw load path (bulk raw load path design, section 10,
build step 3).

Runs the row path (`apply_raw_contract`, one call per series-chunk in the loader's call shape)
and the bulk path (`apply_raw_contract_batch` over packed groups of the same offers) against the
live database, each inside a transaction that is ALWAYS rolled back, and compares what each
wrote, bit for bit:

- ohlcv_raw of the sampled series in the month (every column; floats by their exact hex form,
  stamps as epoch microseconds; a load id by its (symbol, first bar, last bar, bars) label);
- ohlcv_revision and ohlcv_restatement_flag of the loads (same labels);
- ohlcv_load rows (every column but load_id, loaded_at and the note's horizon/selection);
- the LoadResult counts;
- market_data_ohlcv and bar_session_choice of the series in the month, which neither path may
  change.

Allowed difference: the row path's `n_unselected` against the bulk path's `n_selection_deferred`
plus ops_selection_gate's windowed --compare count of unselected slots over the bulk path's
result, which must equal it. A third transaction runs the bulk path twice and asserts the second
run wrote nothing. A contradicting duplicate must raise the same ValueError on both paths.

Then a measurement transaction offers every sampled series' month as new and times each bulk
stage; `EXPLAIN (ANALYZE, BUFFERS)` of the classification and of the new-row INSERT gives the
server insert rate that decides the section 9 fallback ladder.

Sample: 40 mapped symbols with Massive rows in the month, drawn with a recorded seed, AAPL, NVDA
and AXON forced in. The setup (deleting the new group's month inside the transaction) runs as
the login user; both paths run under the bar-writer role. Run it only while no Massive load is
writing the month (it takes the same series locks). Nothing persists.

Usage: .venv/bin/python -m scripts.ops.bars.ops_raw_bulk_equivalence [--month 2024-06]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg

from scripts.ops.bars import ops_selection_gate as gate
from services.bar_load import (
    CHUNK_ROWS,
    LoadResult,
    frame_to_raw_batch,
    frame_to_raw_rows,
    pack_series_chunks,
)

# The measurement EXPLAINs the writer's own statement texts and stages through its own COPY, so
# it names those private symbols; every parameter comes from the writer's public builders.
from services.ohlcv_ingress_contract import (
    _INSERT_LOAD_SQL,
    DESTINATION_RAW,
    OUTCOME_APPLIED,
    RawContractParams,
    SeriesLoad,
    _load_params,
    apply_raw_contract,
    apply_raw_contract_batch,
    read_raw_params,
)
from services.ohlcv_raw_writer import (
    _BULK_NEW_SQL,
    _CLASSIFY_SQL,
    _stage,
    classify_params,
    datetime_to_us,
    lock_series,
    stage_and_classify,
    us_to_datetime,
    write_classified,
    write_params,
)
from src.config.settings import get_settings
from src.core.service_utils import setup_service_logging
from src.intelligence.bars.vendor_ingress import vendor_ingress

SEED = 20261111
# BRK.B (the dotted ticker the design named) is on the identity gap list and has no Massive
# rows; AXON (served as AAXN before its rename) stands in as the mapped-name case.
FORCED = ("AAPL", "NVDA", "AXON")
GROUPS = (
    ("new", 10),
    ("unchanged", 10),
    ("replace", 8),
    ("superseded", 8),
    ("mixed", 2),
    ("duplicates", 2),
)
CALLER = "raw-bulk-equivalence"
_ROLE = "bar_derivation_writer"
_DAY = timedelta(days=1)
_TICK = 0.01
_REPLACE_SHARE = 0.03
_LOG_DIR = Path("logs")
_NAMESPACE = uuid.UUID("6f1c2b8e-4a40-4d4e-9a57-0b1d5d3a7e11")


def request_id(symbol: str, ordinal: int) -> uuid.UUID:
    """The deterministic request id of a series-chunk, shared by both paths."""
    return uuid.uuid5(_NAMESPACE, f"{symbol}|{ordinal}")


def lineage(symbol: str) -> dict[str, Any]:
    return {"harness": CALLER, "symbol": symbol}


# --------------------------------------------------------------------------------------
# Sample and offers
# --------------------------------------------------------------------------------------


def month_bounds(month: str) -> tuple[datetime, datetime]:
    first = date.fromisoformat(f"{month}-01")
    stop = (first + timedelta(days=32)).replace(day=1)
    return (
        datetime.combine(first, datetime.min.time(), UTC),
        datetime.combine(stop, datetime.min.time(), UTC),
    )


def draw_sample(cur: Any, lo: datetime, hi: datetime, caller: str) -> dict[str, list[str]]:
    cur.execute(
        "SELECT DISTINCT symbol FROM ohlcv_load WHERE caller = %s AND first_bar >= %s "
        "AND last_bar < %s ORDER BY symbol",
        (caller, lo.date(), hi.date()),
    )
    pool = [r[0] for r in cur.fetchall()]
    missing = [s for s in FORCED if s not in pool]
    if missing:
        raise SystemExit(f"forced symbols without a Massive load in the month: {missing}")
    rng = np.random.default_rng(SEED)
    others = [s for s in pool if s not in FORCED]
    total = sum(n for _, n in GROUPS)
    drawn = list(FORCED) + list(rng.choice(others, total - len(FORCED), replace=False))
    order = rng.permutation(len(drawn))
    shuffled = [str(drawn[i]) for i in order]
    groups: dict[str, list[str]] = {}
    at = 0
    for name, n in GROUPS:
        groups[name] = sorted(shuffled[at : at + n])
        at += n
    return groups


_DELETE_MONTH_SQL = (
    "DELETE FROM ohlcv_raw WHERE timeframe = %s AND vendor = %s AND kind = %s "
    'AND symbol = ANY(%s) AND "timestamp" >= %s AND "timestamp" < %s'
)
_STORED_SQL = (
    'SELECT symbol, "timestamp", open, high, low, close, volume, served_at FROM ohlcv_raw '
    "WHERE timeframe = %s AND vendor = %s AND kind = %s AND symbol = ANY(%s) "
    'AND "timestamp" >= %s AND "timestamp" < %s ORDER BY symbol, "timestamp"'
)


def read_stored(cur: Any, family: tuple[str, str, str], symbols, lo, hi) -> dict[str, pd.DataFrame]:
    cur.execute(_STORED_SQL, (*family, list(symbols), lo, hi))
    frame = pd.DataFrame(
        cur.fetchall(), columns=["symbol", "t", "o", "h", "l", "c", "v", "answered_at"]
    )
    for column in ("t", "answered_at"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return {
        str(s): g.drop(columns="symbol").reset_index(drop=True) for s, g in frame.groupby("symbol")
    }


def _perturb(frame: pd.DataFrame, rng: np.random.Generator, how: str) -> pd.DataFrame:
    out = frame.copy()
    if how == "ratio":  # every price x2: the price_ratio signature
        for column in "ohlc":
            out[column] = out[column] * 2.0
    elif how == "shift":  # each bar carries the previous bar's values: the time_shift signature
        for column in "ohlcv":
            out.loc[1:, column] = frame[column].to_numpy()[:-1]
    else:  # close plus one tick on a few bars
        n = max(1, int(round(len(out) * _REPLACE_SHARE)))
        picked = rng.choice(len(out), n, replace=False)
        out.loc[picked, "c"] = out.loc[picked, "c"] + _TICK
    return out


def build_offers(
    stored: Mapping[str, pd.DataFrame], groups: Mapping[str, list[str]]
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """(the offers both paths load, a contradicting offer each path must refuse)."""
    rng = np.random.default_rng(SEED + 1)
    offers: dict[str, pd.DataFrame] = {}
    for symbol in groups["new"] + groups["unchanged"]:
        offers[symbol] = stored[symbol].copy()
    for name, step in (("replace", _DAY), ("superseded", -_DAY)):
        for i, symbol in enumerate(groups[name]):
            how = "ratio" if i == 0 else "shift" if i == 1 else "tick"
            frame = _perturb(stored[symbol], rng, how)
            frame["answered_at"] = stored[symbol]["answered_at"] + step
            offers[symbol] = frame
    for symbol in groups["mixed"]:
        frame = stored[symbol].copy()
        frame.loc[::10, "c"] = frame.loc[::10, "c"] + _TICK
        half = len(frame) // 2
        days = np.where(np.arange(len(frame)) < half, -1, 1)
        frame["answered_at"] = stored[symbol]["answered_at"] + pd.to_timedelta(days, unit="D")
        offers[symbol] = frame
    identical, contradicting = groups["duplicates"]
    offers[identical] = pd.concat(
        [stored[identical], stored[identical].iloc[:5]], ignore_index=True
    )
    bad = stored[contradicting].copy()
    extra = bad.iloc[[0]].copy()
    extra["c"] = extra["c"] + _TICK
    return offers, {contradicting: pd.concat([bad, extra], ignore_index=True)}


# --------------------------------------------------------------------------------------
# The two paths
# --------------------------------------------------------------------------------------


def run_row_path(
    conn: Any,
    offers: Mapping[str, pd.DataFrame],
    family: tuple[str, str, str],
    params: RawContractParams,
    chunk_rows: int,
) -> LoadResult:
    """Today's call shape: one apply_raw_contract per series-chunk, the frame's latest answer
    time as the call's (load_frame), each row's own answer time on the row."""
    timeframe, vendor, kind = family
    result = LoadResult()
    for symbol in sorted(offers):
        frame = offers[symbol].sort_values("t", kind="stable", ignore_index=True)
        rows = frame_to_raw_rows(frame, symbol, vendor=vendor, timeframe=timeframe, kind=kind)
        answered = frame["answered_at"].max().to_pydatetime()
        for ordinal, start in enumerate(range(0, len(rows), chunk_rows)):
            result = result.plus(
                apply_raw_contract(
                    conn,
                    rows[start : start + chunk_rows],
                    caller=CALLER,
                    request_id=request_id(symbol, ordinal),
                    answered_at=answered,
                    params=params,
                    lineage=lineage(symbol),
                )
            )
    return result


def run_bulk_path(
    conn: Any,
    offers: Mapping[str, pd.DataFrame],
    family: tuple[str, str, str],
    params: RawContractParams,
    chunk_rows: int,
) -> LoadResult:
    """The bulk path in load_batch's packing, without its transaction (the harness owns it)."""
    timeframe, vendor, kind = family
    batch = frame_to_raw_batch(
        offers, vendor=vendor, timeframe=timeframe, params=params, kind=kind, chunk_rows=chunk_rows
    )
    bounds = batch.key_bounds()
    symbols = [str(batch.symbols[b]) for b in bounds[:-1]]
    seen: Counter[str] = Counter()
    ids = []
    for symbol in symbols:
        ids.append(request_id(symbol, seen[symbol]))
        seen[symbol] += 1
    result = LoadResult()
    for first, stop in pack_series_chunks(np.diff(bounds), params.write.batch_rows):
        result = result.plus(
            apply_raw_contract_batch(
                conn,
                batch.keys(first, stop),
                caller=CALLER,
                params=params,
                lineage_by_symbol={s: lineage(s) for s in offers},
                request_ids=ids[first:stop],
            )
        )
    return result


# --------------------------------------------------------------------------------------
# Capture
# --------------------------------------------------------------------------------------


def _norm(value: Any, labels: Mapping[Any, Any]) -> Any:
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, datetime):
        return datetime_to_us(value)
    if isinstance(value, uuid.UUID):
        return labels.get(value, str(value))
    if isinstance(value, date):
        return value.isoformat()
    return value


def _strip_selection(detail: str | None) -> str | None:
    """The load detail without the lineage note's horizon and selection fields."""
    if detail is None or not detail.startswith("lineage: "):
        return detail
    head, sep, rest = detail.partition("; ")
    note = json.loads(head.removeprefix("lineage: "))
    note.pop("horizon", None)
    note.pop("selection", None)
    return "lineage: " + json.dumps(note, sort_keys=True) + sep + rest


def capture(
    cur: Any, family: tuple[str, str, str], symbols: list[str], lo: datetime, hi: datetime
) -> dict[str, list]:
    timeframe, vendor, kind = family
    cur.execute(
        "SELECT load_id, symbol, timeframe, source, requested_start, requested_end, outcome, "
        "n_bars, n_new, n_changed, first_bar, last_bar, detail, caller, batch_id, n_unchanged, "
        "n_removed, destination, n_archived, n_superseded FROM ohlcv_load WHERE caller = %s",
        (CALLER,),
    )
    loads = cur.fetchall()
    labels = {row[0]: f"load:{row[1]}:{row[10]}:{row[11]}:{row[7]}" for row in loads}
    ids = list(labels)
    out: dict[str, list] = {
        "load": sorted(
            [labels[r[0]], *(_norm(v, labels) for v in r[1:12]), _strip_selection(r[12])]
            + [_norm(v, labels) for v in r[13:]]
            for r in loads
        )
    }
    cur.execute(
        'SELECT symbol, "timestamp", timeframe, vendor, kind, open, high, low, close, volume, '
        "served_at, request_id, load_id FROM ohlcv_raw WHERE timeframe = %s AND vendor = %s "
        'AND kind = %s AND symbol = ANY(%s) AND "timestamp" >= %s AND "timestamp" < %s '
        'ORDER BY symbol, "timestamp"',
        (timeframe, vendor, kind, symbols, lo, hi),
    )
    out["raw"] = [[_norm(v, labels) for v in r] for r in cur.fetchall()]
    cur.execute(
        'SELECT load_id, symbol, timeframe, "timestamp", old_open, old_high, old_low, '
        "old_close, old_volume, old_source, origin, vendor, kind, request_id FROM ohlcv_revision "
        "WHERE load_id = ANY(%s)",
        (ids,),
    )
    out["revision"] = sorted([_norm(v, labels) for v in r] for r in cur.fetchall())
    cur.execute(
        "SELECT load_id, symbol, timeframe, vendor, kind, n_stored, n_changed, share, signatures, "
        "ratio, shift_bars, detail, reviewed_at FROM ohlcv_restatement_flag "
        "WHERE load_id = ANY(%s)",
        (ids,),
    )
    out["flag"] = sorted([_norm(v, labels) for v in r] for r in cur.fetchall())
    out.update(canonical(cur, timeframe, symbols, lo, hi))
    return out


def canonical(cur: Any, timeframe: str, symbols: list[str], lo, hi) -> dict[str, list]:
    """The canonical rows and session choices of the series in the month (neither path may move
    them)."""
    cur.execute(
        'SELECT symbol, "timestamp", open, high, low, close, volume, vendor, kind '
        "FROM market_data_ohlcv WHERE timeframe = %s AND symbol = ANY(%s) "
        'AND "timestamp" >= %s AND "timestamp" < %s ORDER BY symbol, "timestamp"',
        (timeframe, symbols, lo, hi),
    )
    rows = [[_norm(v, {}) for v in r] for r in cur.fetchall()]
    cur.execute(
        "SELECT * FROM bar_session_choice WHERE timeframe = %s AND symbol = ANY(%s) "
        "AND session_date >= %s AND session_date < %s",
        (timeframe, symbols, lo.date(), hi.date()),
    )
    return {
        "canonical": rows,
        "session_choice": sorted([_norm(v, {}) for v in r] for r in cur.fetchall()),
    }


def first_difference(a: list, b: list) -> dict[str, Any] | None:
    if a == b:
        return None
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return {"index": i, "row_path": x, "bulk_path": y, "lengths": [len(a), len(b)]}
    return {"lengths": [len(a), len(b)]}


# --------------------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------------------


def rolled_back(
    conn: Any,
    family: tuple[str, str, str],
    groups: Mapping[str, list[str]],
    deleted: list[str],
    body: Callable[[], Any],
    lo: datetime,
    hi: datetime,
    *,
    after: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    """Run `body` under the bar-writer role in a transaction that always rolls back, after
    deleting `deleted`'s month of the family (the new group); capture what it wrote."""
    symbols = sorted(s for names in groups.values() for s in names)
    timeframe, vendor, kind = family
    with conn.transaction(force_rollback=True):
        with conn.cursor() as cur:
            before = canonical(cur, timeframe, symbols, lo, hi)
            n_deleted = _delete_month(cur, family, deleted, lo, hi)
            cur.execute(f"SET LOCAL ROLE {_ROLE}")
        t0 = time.monotonic()
        result = body()
        seconds = time.monotonic() - t0
        with conn.cursor() as cur:
            cur.execute("RESET ROLE")
            captured = capture(cur, family, symbols, lo, hi)
            extra = after(cur) if after else None
    return {
        "result": result,
        "seconds": seconds,
        "captured": captured,
        "canonical_before": before,
        "n_deleted": n_deleted,
        "extra": extra,
    }


def windowed_unselected(cur: Any, timeframe: str, symbols: list[str], lo, hi) -> int:
    """ops_selection_gate --compare's unselected slots over the month's sessions."""
    policy, kind_order = gate.read_policy(cur), gate.read_kind_order(cur)
    window = gate.compare_bounds(lo.date(), hi.date())
    total = 0
    for symbol in symbols:
        diff = gate.compare_window(
            cur,
            "market_data_ohlcv",
            symbol,
            timeframe,
            window,
            policy=policy,
            kind_order=kind_order,
            horizon=datetime.now(UTC),
        )
        total += 0 if diff is None else diff.unselected
    return total


def compare_scenario(row: dict[str, Any], bulk: dict[str, Any]) -> dict[str, Any]:
    tables = {
        name: first_difference(row["captured"][name], bulk["captured"][name])
        for name in row["captured"]
    }
    untouched = {
        path: first_difference(run["canonical_before"]["canonical"], run["captured"]["canonical"])
        is None
        and run["canonical_before"]["session_choice"] == run["captured"]["session_choice"]
        for path, run in (("row", row), ("bulk", bulk))
    }
    a, b = asdict(row["result"]), asdict(bulk["result"])
    counts = {k: a[k] for k in a if k not in ("n_unselected", "n_selection_deferred")}
    counts_bulk = {k: b[k] for k in b if k not in ("n_unselected", "n_selection_deferred")}
    return {
        "tables_identical": all(v is None for v in tables.values()),
        "first_differences": {k: v for k, v in tables.items() if v is not None},
        "rows": {k: len(v) for k, v in row["captured"].items()},
        "canonical_untouched": untouched,
        "counts_identical": counts == counts_bulk,
        "row_counts": a,
        "bulk_counts": b,
        "seconds": {"row": round(row["seconds"], 3), "bulk": round(bulk["seconds"], 3)},
    }


def contradiction(conn: Any, run: Callable[[], Any]) -> str:
    try:
        with conn.transaction(force_rollback=True):
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL ROLE {_ROLE}")
            run()
    except ValueError as error:
        return str(error)
    return "no error raised"


def _delete_month(cur: Any, family: tuple[str, str, str], symbols, lo, hi) -> int:
    """Delete the symbols' month of the family (inside the caller's rolled-back transaction)."""
    cur.execute(_DELETE_MONTH_SQL, (*family, list(symbols), lo, hi))
    return int(cur.rowcount)


def _insert_probe_loads(cur: Any, batch: Any) -> list[uuid.UUID]:
    """One ohlcv_load row per series-chunk (the revisions' and raw rows' foreign key), built by
    the contract's own row builder."""
    load_ids = [uuid.uuid4() for _ in range(batch.n_keys)]
    bounds = batch.key_bounds().tolist()
    rows = []
    for k, (start, stop) in enumerate(zip(bounds[:-1], bounds[1:], strict=True)):
        first = us_to_datetime(batch.ts_us[start]).date()
        last = us_to_datetime(batch.ts_us[stop - 1]).date()
        load = SeriesLoad(
            str(batch.symbols[start]),
            batch.timeframe,
            DESTINATION_RAW,
            CALLER,
            batch.vendor,
            stop - start,
            0,
            stop - start,
            0,
            0,
            first,
            last,
        )
        rows.append(_load_params(load, outcome=OUTCOME_APPLIED, detail=None, load_id=load_ids[k]))
    cur.executemany(_INSERT_LOAD_SQL, rows)
    return load_ids


def measure(
    conn: Any,
    family: tuple[str, str, str],
    stored: Mapping[str, pd.DataFrame],
    params: RawContractParams,
    lo: datetime,
    hi: datetime,
) -> dict[str, Any]:
    """Every sampled series' month offered as new (deleted inside the transaction): per-stage
    timings of the bulk path, then EXPLAIN (ANALYZE, BUFFERS) of the classification and the
    new-row INSERT in a second transaction. Both roll back."""
    timeframe, vendor, kind = family
    out: dict[str, Any] = {}
    with conn.transaction(force_rollback=True):
        with conn.cursor() as cur:
            _delete_month(cur, family, stored, lo, hi)
            cur.execute(f"SET LOCAL ROLE {_ROLE}")
            t0 = time.monotonic()
            batch = frame_to_raw_batch(
                stored, vendor=vendor, timeframe=timeframe, params=params, kind=kind
            )
            t1 = time.monotonic()
            classified = stage_and_classify(cur, batch)
            t2 = time.monotonic()
            load_ids = _insert_probe_loads(cur, batch)
            t3 = time.monotonic()
            write_classified(
                cur, classified, load_ids=load_ids, request_ids=[uuid.uuid4()] * batch.n_keys
            )
            t4 = time.monotonic()
    n = len(batch)
    out["rows"] = n
    out["stages_s"] = {
        "build_batch": round(t1 - t0, 3),
        "stage_lock_classify": round(t2 - t1, 3),
        "load_rows": round(t3 - t2, 3),
        "write_classified_insert": round(t4 - t3, 3),
    }
    out["bulk_rows_per_s_end_to_end"] = round(n / (t4 - t0))
    out["insert_rows_per_s_client_timed"] = round(n / (t4 - t3))
    with conn.transaction(force_rollback=True):
        with conn.cursor() as cur:
            _delete_month(cur, family, stored, lo, hi)
            cur.execute(f"SET LOCAL ROLE {_ROLE}")
            t0 = time.monotonic()
            _stage(cur, batch)
            out["stage_copy_s"] = round(time.monotonic() - t0, 3)
            lock_series(cur, batch)
            out["explain_classify"] = _explain(cur, _CLASSIFY_SQL, classify_params(batch))
            load_ids = _insert_probe_loads(cur, batch)
            plan = _explain(
                cur, _BULK_NEW_SQL, write_params(batch, load_ids, [uuid.uuid4()] * batch.n_keys)
            )
            out["explain_insert"] = plan
            out["server_insert_rows_per_s"] = round(n / (plan["execution_ms"] / 1000))
    return out


def _explain(cur: Any, sql: str, params: Mapping[str, Any]) -> dict[str, Any]:
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params, prepare=False)
    (plan,) = cur.fetchone()
    top = plan[0]
    return {
        "execution_ms": top["Execution Time"],
        "planning_ms": top["Planning Time"],
        "plan": top["Plan"],
    }


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    setup_service_logging(str(_LOG_DIR / "ops_raw_bulk_equivalence.log"))
    ingress = vendor_ingress("massive", "5m")
    family = (ingress.timeframe, ingress.source, ingress.kind)
    lo, hi = month_bounds(args.month)
    conn = psycopg.connect(get_settings().database_url)
    report: dict[str, Any] = {"month": args.month, "seed": SEED, "family": list(family)}
    try:
        with conn.cursor() as cur:
            params = read_raw_params(cur)
            groups = draw_sample(cur, lo, hi, f"massive-{ingress.timeframe}-load")
            symbols = sorted(s for names in groups.values() for s in names)
            stored = read_stored(cur, family, symbols, lo, hi)
        conn.rollback()
        report["groups"] = groups
        offers, contradicting = build_offers(stored, groups)
        report["n_offered"] = int(sum(len(f) for f in offers.values()))

        def windowed(cur: Any) -> int:
            return windowed_unselected(cur, family[0], symbols, lo, hi)

        # The row path cuts chunks over offered rows, the bulk path over unique bars, so the two
        # cut differently only where a repeat sits in the offer; the chunk-splitting scenario
        # offers the identical-repeat series without its repeats (the main scenario keeps them).
        identical = groups["duplicates"][0]
        split_offers = {**offers, identical: offers[identical].drop_duplicates(ignore_index=True)}
        scenarios: dict[str, Any] = {}
        for chunk_rows, offered in ((CHUNK_ROWS, offers), (1000, split_offers)):
            row = rolled_back(
                conn,
                family,
                groups,
                groups["new"],
                partial(run_row_path, conn, offered, family, params, chunk_rows),
                lo,
                hi,
            )
            bulk = rolled_back(
                conn,
                family,
                groups,
                groups["new"],
                partial(run_bulk_path, conn, offered, family, params, chunk_rows),
                lo,
                hi,
                after=windowed if chunk_rows == CHUNK_ROWS else None,
            )
            scenario = compare_scenario(row, bulk)
            if chunk_rows == CHUNK_ROWS:
                deferred = bulk["result"].n_selection_deferred
                scenario["unselected"] = {
                    "row_path_n_unselected": row["result"].n_unselected,
                    "bulk_n_selection_deferred": deferred,
                    "compare_unselected_after_bulk": bulk["extra"],
                    "equal": bulk["extra"] == row["result"].n_unselected and deferred > 0,
                }
            scenarios[f"chunk_rows_{chunk_rows}"] = scenario
            print(f"chunk_rows {chunk_rows}: {json.dumps(scenario, default=str)[:600]}", flush=True)
        report["scenarios"] = scenarios

        def twice() -> tuple[LoadResult, LoadResult, list]:
            first = run_bulk_path(conn, offers, family, params, CHUNK_ROWS)
            with conn.cursor() as cur:
                cur.execute("RESET ROLE")
                raw_after_first = capture(cur, family, symbols, lo, hi)["raw"]
                cur.execute(f"SET LOCAL ROLE {_ROLE}")
            second = run_bulk_path(conn, offers, family, params, CHUNK_ROWS)
            return first, second, raw_after_first

        idem = rolled_back(conn, family, groups, groups["new"], twice, lo, hi)
        first, second, raw_after_first = idem["result"]
        n_revisions = len(idem["captured"]["revision"])
        # A rerun inserts and replaces nothing. An offer older than the stored answer stays
        # older, so a rerun logs it as superseded again, exactly as the row path does: the
        # second run's only revisions are those, and raw does not move.
        report["idempotence"] = {
            "first": asdict(first),
            "second": asdict(second),
            "second_inserted_and_replaced_nothing": (second.n_new, second.n_changed) == (0, 0)
            and second.n_superseded == first.n_superseded,
            "raw_unchanged_by_second": raw_after_first == idem["captured"]["raw"],
            "second_logs_only_superseded": n_revisions
            == first.n_changed + first.n_superseded + second.n_superseded,
        }
        ((bad_symbol, bad_frame),) = contradicting.items()
        report["contradiction"] = {
            "row": contradiction(
                conn,
                lambda: run_row_path(conn, {bad_symbol: bad_frame}, family, params, CHUNK_ROWS),
            ),
            "bulk": contradiction(
                conn,
                lambda: run_bulk_path(conn, {bad_symbol: bad_frame}, family, params, CHUNK_ROWS),
            ),
        }
        report["contradiction"]["equal"] = report["contradiction"]["row"] == report[
            "contradiction"
        ]["bulk"] and report["contradiction"]["row"].startswith("chunk offers")
        report["measurement"] = measure(conn, family, stored, params, lo, hi)
    finally:
        conn.rollback()
        conn.close()
    report["passed"] = (
        all(
            s["tables_identical"]
            and s["counts_identical"]
            and all(s["canonical_untouched"].values())
            for s in report["scenarios"].values()
        )
        and report["scenarios"][f"chunk_rows_{CHUNK_ROWS}"]["unselected"]["equal"]
        and report["idempotence"]["second_inserted_and_replaced_nothing"]
        and report["idempotence"]["raw_unchanged_by_second"]
        and report["idempotence"]["second_logs_only_superseded"]
        and report["contradiction"]["equal"]
    )
    out = args.out or _LOG_DIR / (
        f"raw_bulk_equivalence_{args.month}_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, default=str))
    m = report["measurement"]
    print(
        f"passed={report['passed']} server_insert_rows_per_s={m['server_insert_rows_per_s']} "
        f"bulk_end_to_end_rows_per_s={m['bulk_rows_per_s_end_to_end']} report: {out}"
    )
    return 0 if report["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--month", default="2024-06", help="YYYY-MM, a month Massive has loaded")
    parser.add_argument("--out", type=Path, default=None)
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
