"""Expected delta of the Massive switch without IBKR, and every slot it loses, classified (todo 600
step 7; runbook docs/operations/massive-step7-runbook.md, A2 and D1).

Read-only (a read-only session; temp nothing, write nothing). Run it against the live selection
BEFORE the drop. Per (timeframe, UTC month) of canonical ``market_data_ohlcv`` and of Massive's
raw months it full-joins the
canonical slots with Massive's raw slots (5m ``sip_flat_agg`` by stamp, 1d ``sip_flat`` by
session date) and counts, under the switch policy (``ops_massive_policy_plan``: Massive before the
archive end, Alpaca from it, no fallback, nothing before Massive's first file):

- before, before_ibkr, before_alpaca: canonical rows now
- pre_start: canonical rows before 2003-09-10 (they leave: no source)
- massive: Massive raw slots in [2003-09-10, archive end) (they become canonical)
- moved_alpaca, moved_ibkr: canonical slots in that span that Massive also holds (vendor changes)
- gained: Massive slots canonical lacks today
- lost_alpaca, lost_ibkr: canonical slots in that span Massive lacks (they leave; classified)
- gap_alpaca: Alpaca slots inside a gap-list span from 2016-01-04 (the plan's Alpaca gap rows
  keep them, byte-identical); gap_other: other slots there (they leave: no fallback)
- after_end_alpaca: Alpaca slots from the archive end (byte-identical after the rebuild)
- after_end_other: other slots from the archive end (they leave: no fallback)
- expected_after = massive + gap_alpaca + after_end_alpaca

After the rebuild, ``--verify BEFORE_CARD AFTER_CARD`` (runbook D1, file-only) checks the cards
against this run's ``switch_delta.csv``: every (timeframe, month) of 5m and 1d holds exactly
``expected_after`` rows, 1m and 4h hold none, no row carries vendor ibkr, and every Alpaca group
(symbol, month) wholly inside an Alpaca gap row is byte-identical to the before card. 1m (IBKR
only) leaves whole by ruling. The months wanted are the union of the before card's months and the
delta rows' months: a month canonical never held but Massive raw fills is a delta row (the run
reads Massive's raw months too), and a before-card month the delta run skipped fails loudly as
an unpredicted month rather than passing silently.

Post-policy expectation (``--post-policy DELTA_DIR``, D1 after the rebuild, read-only). The B4 delta
above is computed from the canonical rows BEFORE the switch, so it counts as ``gap_alpaca`` only the
Alpaca slots canonical already held at a name with an Alpaca gap row. After the policy switch the
slot truth is a function of raw and policy: at a gap-row name every Alpaca raw slot (regular-hours grid
for 5m; a zero-volume 5m bar is kept, a zero-volume Alpaca 1d bar is not selected) from 2016-01-04 to the
archive end is selected, whatever vendor held it before, and after the archive end every such Alpaca
raw slot is. A name the daily stage holds
(``daily_rebuild.tsv``, outcome held) has no canonical 1d at all, so its Massive 1d slots are not
expected. ``--post-policy`` reads the B4 ``switch_delta.csv`` (never modified) and writes a NEW
directory: ``switch_delta.csv`` with ``expected_after = massive + alpaca_gap_raw +
alpaca_after_end_raw - held_massive``, ``gap_raw_groups.csv`` (Alpaca raw slots per gap-row
(symbol, month), the whole-month check reads it), ``held.json`` (the held names, disclosed) and a
summary. ``--verify`` against that directory compares each whole-month gap-row Alpaca group with
its raw count and prints the held names as their own line.

Every lost slot is classified (``classify_loss``), in this order: ``gap_list`` (an identity gap
span covers it: unplaced, no source by design), ``after_listing_end`` (after the name's recorded
last session), ``zero_volume`` (the incumbent bar has zero or unknown volume: a non-trade
placeholder the tradeable view drops anyway), ``no_ticker_span`` (no Massive ticker span of the
name covers the date: a mapping hole, to be fixed, not an accepted loss), ``unexplained``. 5m
losses are one row per (name, session, vendor, volume class) with the slot count.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from scripts.ops.bars.ops_canonical_summary_card import read_card  # noqa: E402
from scripts.ops.bars.ops_massive_policy_plan import (  # noqa: E402
    ALPACA_FIRST_DAY,
    DEFAULT_MANIFEST,
    GapRow,
    archive_end_of,
    read_gap_list,
)
from src.config.settings import get_settings  # noqa: E402
from src.intelligence.bars.selection import (  # noqa: E402
    RTH_GRID_STEP_MINUTES,
    rth_grid_stamps,
)
from src.intelligence.bars.ticker_entity_map import MASSIVE_ARCHIVE_START  # noqa: E402

MASSIVE_KIND = {"5m": "sip_flat_agg", "1d": "sip_flat"}
CAUSES = ("gap_list", "after_listing_end", "zero_volume", "no_ticker_span", "unexplained")
DELTA_FIELDS = (
    "timeframe",
    "month",
    "before",
    "before_ibkr",
    "before_alpaca",
    "pre_start",
    "massive",
    "moved_alpaca",
    "moved_ibkr",
    "gained",
    "lost_alpaca",
    "lost_ibkr",
    "gap_alpaca",
    "gap_other",
    "after_end_alpaca",
    "after_end_other",
    "expected_after",
)
HANDOVER_DELTA_TIMEFRAMES = ("5m", "1d")
LOSS_FIELDS = ("timeframe", "symbol", "session", "vendor", "zero_volume", "slots", "cause")

#: One grouped row of the month join: (symbol, session date, canonical vendor or None, zero or
#: unknown canonical volume, in canonical, in Massive raw, slot count).
_JOIN_SQL = """
WITH c AS (
    SELECT symbol, {c_key} AS k, {c_day} AS d, vendor, coalesce(volume, 0) = 0 AS zero
    FROM market_data_ohlcv
    WHERE timeframe = %(tf)s AND "timestamp" >= %(lo)s AND "timestamp" < %(hi)s
), m AS (
    SELECT symbol, {m_key} AS k, {m_day} AS d
    FROM ohlcv_raw
    WHERE timeframe = %(tf)s AND vendor = 'massive' AND kind = %(kind)s
      AND "timestamp" >= %(lo)s AND "timestamp" < %(hi)s{m_grid}
)
SELECT coalesce(c.symbol, m.symbol), coalesce(c.d, m.d), c.vendor, coalesce(c.zero, false),
       c.symbol IS NOT NULL, m.symbol IS NOT NULL, count(*)
FROM c FULL JOIN m ON c.symbol = m.symbol AND c.k = m.k
GROUP BY 1, 2, 3, 4, 5, 6
"""
_GRID_CLAUSE = ' AND "timestamp" = ANY(%(grid)s)'
_NY = "AT TIME ZONE 'America/New_York'"
_RAW_DAY = f'("timestamp" {_NY})::date'  # a raw bar's session date (classification only)
_KEYS = {
    # 5m: the bar stamp on both sides; 1d: canonical is stamped at the UTC date, raw at New York
    # midnight, so the key is the session date. The month both sides belong to is the UTC stamp
    # month (the card's bucket); d never scopes a month.
    "5m": {"c_key": '"timestamp"', "c_day": f'("timestamp" {_NY})::date', "m_key": '"timestamp"'},
    "1d": {
        "c_key": "(\"timestamp\" AT TIME ZONE 'UTC')::date",
        "c_day": "(\"timestamp\" AT TIME ZONE 'UTC')::date",
        "m_key": f'("timestamp" {_NY})::date',
    },
}
_SPANS_SQL = """
SELECT symbol, valid_from, valid_to FROM ticker_event_current
WHERE vendor = 'massive' AND retired_at IS NULL
"""
_LISTING_END_SQL = "SELECT symbol, last_session FROM listing_end_current"
_MONTHS_SQL = """
SELECT DISTINCT date_trunc('month', "timestamp" AT TIME ZONE 'UTC')::date
FROM market_data_ohlcv WHERE timeframe = %s ORDER BY 1
"""
_RAW_MONTHS_SQL = """
SELECT DISTINCT date_trunc('month', "timestamp" AT TIME ZONE 'UTC')::date
FROM ohlcv_raw WHERE timeframe = %s AND vendor = 'massive' AND kind = %s ORDER BY 1
"""
POST_POLICY_FIELDS = (*DELTA_FIELDS, "alpaca_gap_raw", "alpaca_after_end_raw", "held_massive")
GAP_RAW_FIELDS = ("timeframe", "symbol", "month", "n", "whole_month")
ALPACA_KIND = "sip_rth"
_VOLUME_CLAUSE = {"1d": " AND coalesce(volume, 0) > 0"}  # 5m keeps its zero-volume bars
#: Alpaca raw slots at the gap-row names in one UTC stamp month, per session date: the regular-hours
#: grid for 5m, as selection takes it, with a zero-volume 5m bar kept (it is in canonical, the
#: tradeable view drops it) and a zero-volume Alpaca 1d bar not selected (the daily rule; canonical 1d holds no zero-volume Alpaca row).
_ALPACA_GAP_SQL = f"""
SELECT symbol, {_RAW_DAY} AS d, count(*) FROM ohlcv_raw
WHERE timeframe = %(tf)s AND vendor = 'alpaca' AND kind = '{ALPACA_KIND}'
  AND symbol = ANY(%(symbols)s)
  AND "timestamp" >= %(lo)s AND "timestamp" < %(hi)s{{grid}}{{volume}}
GROUP BY 1, 2
"""
#: Alpaca raw slots on or after the archive end, every name, one month (same volume rule).
_ALPACA_AFTER_END_SQL = f"""
SELECT count(*) FROM ohlcv_raw
WHERE timeframe = %(tf)s AND vendor = 'alpaca' AND kind = '{ALPACA_KIND}'
  AND symbol <> ALL(%(held)s)
  AND "timestamp" >= %(lo)s AND "timestamp" < %(hi)s{{grid}}{{volume}} AND {_RAW_DAY} >= %(end)s
"""
#: A held name's Massive 1d slots per session date.
_HELD_MASSIVE_SQL = f"""
SELECT symbol, {_RAW_DAY} AS d, count(*) FROM ohlcv_raw
WHERE timeframe = '1d' AND vendor = 'massive' AND kind = 'sip_flat' AND symbol = ANY(%s)
GROUP BY 1, 2
"""


@dataclass(frozen=True)
class Group:
    symbol: str
    day: date
    vendor: str | None
    zero: bool
    in_canonical: bool
    in_massive: bool
    n: int


@dataclass(frozen=True)
class Identity:
    """The facts a lost slot is classified by."""

    gaps: Mapping[str, Sequence[GapRow]]
    spans: Mapping[str, Sequence[tuple[date, date | None]]]
    listing_end: Mapping[str, date]

    def gap_covers(self, symbol: str, day: date) -> bool:
        return any(
            (g.valid_from is None or g.valid_from <= day)
            and (g.valid_to is None or day < g.valid_to)
            for g in self.gaps.get(symbol, ())
        )

    def span_covers(self, symbol: str, day: date) -> bool:
        return any(a <= day and (b is None or day < b) for a, b in self.spans.get(symbol, ()))


def classify_loss(identity: Identity, symbol: str, day: date, zero: bool) -> str:
    """The cause of one lost slot (module docstring order)."""
    if identity.gap_covers(symbol, day):
        return "gap_list"
    end = identity.listing_end.get(symbol)
    if end is not None and day > end:
        return "after_listing_end"
    if zero:
        return "zero_volume"
    if not identity.span_covers(symbol, day):
        return "no_ticker_span"
    return "unexplained"


def tally(
    groups: Iterable[Group], timeframe: str, month: date, archive_end: date, identity: Identity
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The delta row of one (timeframe, month) and its lost-slot rows."""
    row: dict[str, Any] = dict.fromkeys(DELTA_FIELDS, 0)
    row.update(timeframe=timeframe, month=month.isoformat())
    losses: list[dict[str, Any]] = []
    for g in groups:
        if g.in_canonical:
            row["before"] += g.n
            if g.vendor in ("ibkr", "alpaca"):
                row[f"before_{g.vendor}"] += g.n
        if g.day < MASSIVE_ARCHIVE_START:
            row["pre_start"] += g.n if g.in_canonical else 0
            continue
        if g.day >= archive_end:
            if g.in_canonical:
                key = "after_end_alpaca" if g.vendor == "alpaca" else "after_end_other"
                row[key] += g.n
            continue
        if g.day >= ALPACA_FIRST_DAY and identity.gap_covers(g.symbol, g.day):
            # an Alpaca gap row: Massive holds nothing here (the name is unplaced)
            if g.in_canonical:
                row["gap_alpaca" if g.vendor == "alpaca" else "gap_other"] += g.n
            continue
        if g.in_massive:
            row["massive"] += g.n
            if not g.in_canonical:
                row["gained"] += g.n
            elif g.vendor in ("ibkr", "alpaca"):
                row[f"moved_{g.vendor}"] += g.n
            continue
        if g.vendor not in ("ibkr", "alpaca"):
            raise ValueError(f"{timeframe} {g.symbol} {g.day}: canonical vendor {g.vendor!r}")
        row[f"lost_{g.vendor}"] += g.n
        losses.append(
            {
                "timeframe": timeframe,
                "symbol": g.symbol,
                "session": g.day.isoformat(),
                "vendor": g.vendor,
                "zero_volume": g.zero,
                "slots": g.n,
                "cause": classify_loss(identity, g.symbol, g.day, g.zero),
            }
        )
    row["expected_after"] = row["massive"] + row["gap_alpaca"] + row["after_end_alpaca"]
    return row, losses


def month_bounds(month: date) -> tuple[datetime, datetime]:
    nxt = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return (
        datetime(month.year, month.month, 1, tzinfo=UTC),
        datetime(nxt.year, nxt.month, 1, tzinfo=UTC),
    )


def gap_identity(gap_rows: Iterable[GapRow]) -> Identity:
    """An Identity that knows the gap rows only (no spans, no listing ends)."""
    by_gap: dict[str, list[GapRow]] = defaultdict(list)
    for g in gap_rows:
        by_gap[g.symbol].append(g)
    return Identity(dict(by_gap), {}, {})


def read_identity(conn: Any, gaps: Sequence[GapRow]) -> Identity:
    by_gap: dict[str, list[GapRow]] = defaultdict(list)
    for g in gaps:
        by_gap[g.symbol].append(g)
    spans: dict[str, list[tuple[date, date | None]]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(_SPANS_SQL)
        for symbol, start, end in cur.fetchall():
            spans[symbol].append((start, end))
        cur.execute(_LISTING_END_SQL)
        listing_end = dict(cur.fetchall())
    return Identity(dict(by_gap), dict(spans), listing_end)


def month_params(timeframe: str, month: date) -> dict[str, Any]:
    """The month join's parameters: the UTC stamp month on both sides (the card's bucket), and
    for 5m only the regular-hours grid stamps selection can take (one calendar year of slack
    each side, as selection builds its grids)."""
    lo, hi = month_bounds(month)
    params: dict[str, Any] = {"tf": timeframe, "kind": MASSIVE_KIND[timeframe], "lo": lo, "hi": hi}
    if timeframe in RTH_GRID_STEP_MINUTES:
        params["grid"] = sorted(rth_grid_stamps(timeframe, lo.year - 1, lo.year + 1))
    return params


def month_sql(timeframe: str) -> str:
    return _JOIN_SQL.format(
        **_KEYS[timeframe],
        m_day=_RAW_DAY,
        m_grid=_GRID_CLAUSE if timeframe in RTH_GRID_STEP_MINUTES else "",
    )


def month_groups(conn: Any, timeframe: str, month: date) -> list[Group]:
    with conn.cursor() as cur:
        cur.execute(month_sql(timeframe), month_params(timeframe, month))
        return [Group(*r) for r in cur.fetchall()]


def whole_month_gap_row(identity: Identity, symbol: str, month: date, archive_end: date) -> bool:
    """Every session date of the month lies inside one of the name's Alpaca gap rows."""
    _, hi = month_bounds(month)
    first = max(month, ALPACA_FIRST_DAY)
    if month < ALPACA_FIRST_DAY.replace(day=1) or hi.date() > archive_end:
        return False
    days = (first + timedelta(days=i) for i in range((hi.date() - first).days))
    return all(identity.gap_covers(symbol, d) for d in days)


def read_held(path: Path) -> list[dict[str, str]]:
    """The names the daily stage holds (``daily_rebuild.tsv``, outcome held) and why."""
    with path.open(newline="") as handle:
        rows = csv.DictReader(handle, delimiter="\t")
        return [
            {"symbol": r["symbol"], "reason": r.get("held", "")}
            for r in rows
            if r.get("outcome") == "held"
        ]


def alpaca_gap_slots(
    groups: Iterable[tuple[str, date, int]],
    identity: Identity,
    archive_end: date,
    held: frozenset[str],
    timeframe: str,
) -> Counter[str]:
    """Alpaca raw slots per gap-row name that selection takes (zero-volume Alpaca 1d bars are filtered in SQL): a session date
    from the Alpaca seam to the archive end that an identity gap row covers. A held name has no
    canonical 1d, so none of its slots count for 1d."""
    out: Counter[str] = Counter()
    for symbol, day, n in groups:
        if timeframe == "1d" and symbol in held:
            continue
        if ALPACA_FIRST_DAY <= day < archive_end and identity.gap_covers(symbol, day):
            out[symbol] += n
    return out


def held_massive_slots(
    groups: Iterable[tuple[str, date, int]], identity: Identity, archive_end: date
) -> Counter[tuple[str, int, int]]:
    """A held name's Massive 1d slots that the B4 delta counted as ``massive`` (inside the
    archive, outside an Alpaca gap row), per (name, UTC stamp month = the session date's month)."""
    out: Counter[tuple[str, int, int]] = Counter()
    for symbol, day, n in groups:
        if not MASSIVE_ARCHIVE_START <= day < archive_end:
            continue
        if day >= ALPACA_FIRST_DAY and identity.gap_covers(symbol, day):
            continue
        out[(symbol, day.year, day.month)] += n
    return out


def post_policy_row(
    base: Mapping[str, Any], alpaca_gap_raw: int, alpaca_after_end_raw: int, held_massive: int
) -> dict[str, Any]:
    """The B4 row with the post-policy expectation: ``expected_after`` is the slots selection
    takes from raw under the switch policy (docstring), the B4 columns kept as they were."""
    row = dict(base)
    row.update(
        alpaca_gap_raw=alpaca_gap_raw,
        alpaca_after_end_raw=alpaca_after_end_raw,
        held_massive=held_massive,
    )
    row["expected_after"] = (
        int(base["massive"]) + alpaca_gap_raw + alpaca_after_end_raw - held_massive
    )
    return row


def verify(
    before: Iterable[Mapping[str, Any]],
    after: Iterable[Mapping[str, Any]],
    deltas: Iterable[Mapping[str, Any]],
    identity: Identity,
    archive_end: date,
    gap_raw: Iterable[Mapping[str, Any]] | None = None,
    held: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The D1 gate (module docstring): failures are listed whole, never sampled. With ``gap_raw``
    (the post-policy directory) a whole-month gap-row Alpaca group must hold exactly its raw slot
    count; without it (the B4 directory) it must be byte-identical to the before card. ``held`` is
    printed in the report as its own line and excluded from the expectation upstream."""
    before = list(before)
    after = list(after)
    got: Counter[tuple[str, str]] = Counter()
    for r in after:
        got[(r["timeframe"], r["month"])] += int(r["n"])
    want = {(d["timeframe"], d["month"]): int(d["expected_after"]) for d in deltas}
    predicted = set(want)
    # A before-card month the delta run skipped is unpredictable: the rebuild could hold
    # anything there and the gate could not count it, so it fails unconditionally (a handover
    # timeframe's canonical-before month is always a delta row by construction; its absence is
    # a B4 defect).
    count_failures = [
        {"timeframe": tf, "month": m, "expected": "delta_skipped", "got": got.get((tf, m), 0)}
        for (tf, m) in sorted({(r["timeframe"], r["month"]) for r in before} - predicted)
        if tf in HANDOVER_DELTA_TIMEFRAMES
    ]
    count_failures += [
        {"timeframe": tf, "month": m, "expected": n, "got": got.get((tf, m), 0)}
        for (tf, m), n in sorted(want.items())
        if got.get((tf, m), 0) != n
    ]
    count_failures += [
        {"timeframe": tf, "month": m, "expected": 0, "got": n}
        for (tf, m), n in sorted(got.items())
        if tf in HANDOVER_DELTA_TIMEFRAMES and (tf, m) not in want and n or tf in ("1m", "4h") and n
    ]
    ibkr_left = sorted({(r["timeframe"], r["symbol"]) for r in after if r["vendor"] == "ibkr"})

    key = ("timeframe", "symbol", "vendor", "kind", "month")
    after_groups = {tuple(r[k] for k in key): (r["n"], r["digest"]) for r in after}
    kept = changed = 0
    changed_groups = []
    if gap_raw is None:
        for r in before:
            if r["vendor"] != "alpaca" or r["timeframe"] not in HANDOVER_DELTA_TIMEFRAMES:
                continue
            if not whole_month_gap_row(
                identity, r["symbol"], date.fromisoformat(r["month"]), archive_end
            ):
                continue
            if after_groups.get(tuple(r[k] for k in key)) == (r["n"], r["digest"]):
                kept += 1
            else:
                changed += 1
                changed_groups.append({k: r[k] for k in key})
    else:
        before_groups = {tuple(r[k] for k in key): (r["n"], r["digest"]) for r in before}
        for g in gap_raw:
            if str(g["whole_month"]) not in ("True", "true", "1") or int(g["n"]) == 0:
                continue
            group = (g["timeframe"], g["symbol"], "alpaca", ALPACA_KIND, g["month"])
            was = before_groups.get(group)
            n_after, digest_after = after_groups.get(group, (0, ""))
            # the count is the raw count; a group the before card already held complete (same
            # count) must also be byte-identical, so a different revision or kind cannot pass
            unchanged = was is None or int(was[0]) != int(g["n"]) or was[1] == digest_after
            if n_after == int(g["n"]) and unchanged:
                kept += 1
            else:
                changed += 1
                changed_groups.append(dict(zip(key, group, strict=True)))
    return {
        "ok": not count_failures and not ibkr_left and not changed,
        "count_failures": count_failures,
        "ibkr_rows_left": [f"{tf}:{s}" for tf, s in ibkr_left],
        "gap_row_groups_identical": kept,
        "gap_row_groups_changed": changed_groups,
        "held_names_excluded": [dict(h) for h in held],
    }


def summarize(losses: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    """Per timeframe and cause: slots, name-sessions and names."""
    slots: Counter[tuple[str, str]] = Counter()
    sessions: Counter[tuple[str, str]] = Counter()
    names: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in losses:
        key = (r["timeframe"], r["cause"])
        slots[key] += r["slots"]
        sessions[key] += 1
        names[key].add(r["symbol"])
    out: dict[str, dict[str, dict[str, int]]] = defaultdict(dict)
    for tf, cause in sorted(slots):
        out[tf][cause] = {
            "slots": slots[(tf, cause)],
            "name_sessions": sessions[(tf, cause)],
            "names": len(names[(tf, cause)]),
        }
    return dict(out)


def _write_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=4)
def _grid_stamps(timeframe: str, year: int) -> list[datetime]:
    """The regular-hours stamps around a year, sorted, built once per (timeframe, year)."""
    return sorted(rth_grid_stamps(timeframe, year - 1, year + 1))


def run_post_policy(args: argparse.Namespace, archive_end: date) -> int:
    """``--post-policy``: the expectation after the policy switch, into a NEW directory."""
    delta_dir = args.post_policy.resolve()
    out = args.out.resolve()
    if out == delta_dir or out.is_relative_to(delta_dir):
        print(
            f"REFUSING: --out {out} is inside the B4 delta directory; it is evidence and never changes"
        )
        return 2
    if out.exists() and any(out.iterdir()):
        print(f"REFUSING: {out} is not empty; evidence is never overwritten")
        return 2
    base = _read_csv(delta_dir / "switch_delta.csv")
    gap_rows = read_gap_list(Path(args.gap_list))
    identity = gap_identity(gap_rows)
    held_rows = read_held(Path(args.daily_rebuild))
    held = frozenset(h["symbol"] for h in held_rows)
    gap_symbols = sorted(
        {g.symbol for g in gap_rows if g.valid_to is None or g.valid_to > ALPACA_FIRST_DAY}
    )
    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    new_rows: list[dict[str, Any]] = []
    raw_groups: list[dict[str, Any]] = []
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0")
            cur.execute(_HELD_MASSIVE_SQL, (sorted(held),))
            held_by_month = held_massive_slots(cur.fetchall(), identity, archive_end)
        held_by_ym: Counter[tuple[int, int]] = Counter()
        held_slots: Counter[str] = Counter()
        for (symbol, year, mon), n in held_by_month.items():
            held_by_ym[(year, mon)] += n
            held_slots[symbol] += n
        for row in base:
            tf, month = row["timeframe"], date.fromisoformat(row["month"])
            lo, hi = month_bounds(month)
            gap_n = after_end_n = 0
            sql_parts = {"grid": "", "volume": _VOLUME_CLAUSE.get(tf, "")}
            params: dict[str, Any] = {"tf": tf, "lo": lo, "hi": hi}
            if tf in RTH_GRID_STEP_MINUTES:
                sql_parts["grid"] = _GRID_CLAUSE
                params["grid"] = [s for s in _grid_stamps(tf, lo.year) if lo <= s < hi]
            if hi.date() > ALPACA_FIRST_DAY and lo.date() < archive_end and gap_symbols:
                with conn.cursor() as cur:
                    cur.execute(
                        _ALPACA_GAP_SQL.format(**sql_parts),
                        {**params, "symbols": gap_symbols},
                    )
                    per_symbol = alpaca_gap_slots(cur.fetchall(), identity, archive_end, held, tf)
                gap_n = sum(per_symbol.values())
                raw_groups += [
                    {"timeframe": tf, "symbol": sym, "month": month.isoformat(), "n": n,
                     "whole_month": whole_month_gap_row(identity, sym, month, archive_end)}
                    for sym, n in sorted(per_symbol.items())
                ]  # fmt: skip
            if hi.date() > archive_end:
                with conn.cursor() as cur:
                    cur.execute(
                        _ALPACA_AFTER_END_SQL.format(**sql_parts),
                        {**params, "end": archive_end, "held": sorted(held) if tf == "1d" else []},
                    )
                    after_end_n = cur.fetchone()[0]
            held_n = held_by_ym[(month.year, month.month)] if tf == "1d" else 0
            new_rows.append(post_policy_row(row, gap_n, after_end_n, held_n))
            print(
                f"{tf} {month}: B4 {row['expected_after']} -> {new_rows[-1]['expected_after']}",
                flush=True,
            )
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "switch_delta.csv", POST_POLICY_FIELDS, new_rows)
    _write_csv(out / "gap_raw_groups.csv", GAP_RAW_FIELDS, raw_groups)
    held_report = [
        {**h, "massive_1d_slots_not_expected": held_slots[h["symbol"]]} for h in held_rows
    ]
    (out / "held.json").write_text(json.dumps(held_report, indent=2) + "\n")
    summary = {
        "archive_end": archive_end.isoformat(),
        "b4_delta": str(delta_dir),
        "gap_list": args.gap_list,
        "daily_rebuild": str(args.daily_rebuild),
        "held": held_report,
        "held_massive_1d_slots": sum(held_slots.values()),
        "totals": {
            tf: {
                f: sum(int(r[f]) for r in new_rows if r["timeframe"] == tf)
                for f in ("expected_after", *POST_POLICY_FIELDS[-3:])
            }
            for tf in sorted({r["timeframe"] for r in new_rows})
        },
    }
    (out / "switch_post_policy_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--timeframes", nargs="+", default=["1d", "5m"], choices=sorted(_KEYS))
    parser.add_argument("--gap-list", required=True, help="the pinned identity gap_list.csv")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument(
        "--verify",
        nargs=2,
        type=Path,
        metavar=("BEFORE_CARD", "AFTER_CARD"),
        help="D1: check the after card against --out's switch_delta.csv (file-only)",
    )
    parser.add_argument(
        "--post-policy",
        type=Path,
        metavar="B4_DELTA_DIR",
        help="D1: write the expectation after the policy switch into --out (a new directory), "
        "read from the B4 directory's switch_delta.csv, which is never modified",
    )
    parser.add_argument(
        "--daily-rebuild",
        default=str(project_root / "logs" / "massive_step7" / "daily_rebuild.tsv"),
        help="--post-policy: the daily stage's report (held names are read from it)",
    )
    args = parser.parse_args(argv)
    if args.post_policy and args.verify:
        parser.error("--post-policy and --verify are separate runs")
    archive_end = archive_end_of(Path(args.manifest).read_bytes())
    if args.post_policy:
        return run_post_policy(args, archive_end)
    if args.verify:
        deltas = _read_csv(args.out / "switch_delta.csv")
        gap_raw_path, held_path = args.out / "gap_raw_groups.csv", args.out / "held.json"
        report = verify(
            read_card(args.verify[0]),
            read_card(args.verify[1]),
            deltas,
            gap_identity(read_gap_list(Path(args.gap_list))),
            archive_end,
            _read_csv(gap_raw_path) if gap_raw_path.exists() else None,
            json.loads(held_path.read_text()) if held_path.exists() else (),
        )
        (args.out / "switch_verify.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k != "count_failures"} | {
            "count_failures": len(report["count_failures"])}, indent=2))  # fmt: skip
        return 0 if report["ok"] else 1
    args.out.mkdir(parents=True, exist_ok=True)
    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    deltas: list[dict[str, Any]] = []
    losses: list[dict[str, Any]] = []
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0")
        identity = read_identity(conn, read_gap_list(Path(args.gap_list)))
        for tf in args.timeframes:
            with conn.cursor() as cur:
                cur.execute(_MONTHS_SQL, (tf,))
                months = {r[0] for r in cur.fetchall()}
                cur.execute(_RAW_MONTHS_SQL, (tf, MASSIVE_KIND[tf]))
                months |= {r[0] for r in cur.fetchall()}
            last = date(archive_end.year, archive_end.month, 1)
            months = sorted(months | {last})
            for month in months:
                row, lost = tally(month_groups(conn, tf, month), tf, month, archive_end, identity)
                deltas.append(row)
                losses += lost
                print(
                    f"{tf} {month}: before {row['before']}, after {row['expected_after']}",
                    flush=True,
                )
    _write_csv(args.out / "switch_delta.csv", DELTA_FIELDS, deltas)
    _write_csv(args.out / "switch_losses.csv", LOSS_FIELDS, losses)
    totals = {
        tf: {f: sum(r[f] for r in deltas if r["timeframe"] == tf) for f in DELTA_FIELDS[2:]}
        for tf in args.timeframes
    }
    summary = {
        "archive_end": archive_end.isoformat(),
        "gap_list": args.gap_list,
        "totals": totals,
        "losses": summarize(losses),
    }
    (args.out / "switch_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
