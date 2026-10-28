"""ops_source_policy.py - the writer of bar_source_policy after its seed (phase 185 plan 38 Task 0).

Three modes; every row written carries its evidence.

--admission-sweep: for every compute_1d name (or --symbols), measure the latest current-scale
TRADIER and SMART TRADES close on each common session (src/intelligence/bars/source_admission.py)
and decide:
- admit: Tradier agrees with IBKR (threshold.bar_integrity.tradier_admission_min_overlap_sessions
  common sessions, tradier_admission_min_agree_share of them within fallback_basis_tolerance_bp).
  No row; the 1d default (Tradier primary) applies.
- write: Tradier fails and is not the name's canonical series today (no stored tradier 1d row),
  or it is and a full recent window of min_overlap common sessions fails too (Tradier
  disagrees with IBKR now). One 1d symbol row: primary ibkr, no fallback, valid_from the name's first
  observation date, open-ended.
- route_185_37: Tradier is canonical today and fails only over the whole history (a past basis
  run, RJF-like). No row: flipping it would replace a continuous series with IBKR's step. 185-37's
  basis study decides.
- keep_no_overlap: Tradier is canonical today and fewer than min_overlap common sessions exist
  (most of these names have no IBKR SMART 1d answer in D1 at all). No evidence either way, so
  no row: an IBKR-primary row would point the name at a vendor that never answered for it. The
  weekly IBKR 1d reconcile (189-10) supplies the evidence; the sweep then decides again.
Dry run by default (prints every failing name; --report writes one TSV row per name); --apply
writes the write-action rows, refusing any that would overlap an open symbol row (exit 2).

The exception row has no fallback: under primary ibkr d2-v2 admits no other vendor (its only
fallback pair is Tradier primary, IBKR fallback), and a Tradier fill would put the series the
evidence rejected back into the name's holes.

--add: one symbol row by hand (185-37), --evidence JSON required. `--timeframe` (default 1d)
selects the series; a dated span may be added to a name that has other rows of the series as long
as it overlaps none (the table's EXCLUDE constraint is the backstop). `--primary` and
`--fallback` are checked at run time against the CVR `bar_vendor` codes (an unknown vendor is
refused with the valid list); no vendor list lives in this file. The 5m Alpaca spans of the
selection gate (plan 191-07, D-191-C) are written through `insert_row` only.
--close: close a name's open symbol row of --timeframe at --valid-to (the only UPDATE the table's
trigger allows); --reason required and printed, since the closed row's own fields are immutable.

Backdated rows of a direct timeframe (1m, 5m, 4h; review finding 6 of plan 191-07). Selection
re-selects only the window a load touches, so a span added (or closed) with a date before today
would change historical canonical piecemeal, one later chunk at a time. Such a write is refused
unless --reselect is given; with it the policy write and the re-selection of the changed window
of that series ([valid_from, valid_to) for --add, [valid_to, open end) for --close) run in one
transaction, and the selection gate is run over the series after the commit (its exit code is
this command's). 1d, 15m and 1h are re-derived by their own stages and are not guarded here.

Rollback of an exception row: --close it and rerun the daily dry run.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402
import psycopg  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_apr_dict_async  # noqa: E402
from services.bar_derivation import (  # noqa: E402
    _DISCOVER_DAILY_SYMBOLS_SQL,
    read_daily_inputs,
)
from services.bar_derivation_batch import close_batch, open_batch  # noqa: E402
from services.bar_scrub import FlagRow, write_flags  # noqa: E402
from services.bar_selection import DIRECT_TIMEFRAMES, select_and_write  # noqa: E402
from services.ohlcv_ingress_contract import read_raw_params  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.bars.daily_rule import RAW_DAILY_SERIES  # noqa: E402
from src.intelligence.bars.derivation import Observation, SplitRecord  # noqa: E402
from src.intelligence.bars.selection import SESSION_TZ  # noqa: E402
from src.intelligence.bars.source_admission import (  # noqa: E402
    Admission,
    common_session_closes,
    tradier_admission,
)
from src.intelligence.bars.sources import SOURCE_TRADIER  # noqa: E402
from src.intelligence.bars.vendor_kind import label_to_vendor_kind  # noqa: E402

ACTION_ADMIT = "admit"
ACTION_WRITE = "write"
ACTION_ROUTE = "route_185_37"
ACTION_KEEP = "keep_no_overlap"
_PLAN = "185-38"
_ROUTES = ("TRADIER", "SMART")
# Every route d2-v3 reads, for the first-observation date (LEGACY_IMPORT included).
_D2V2_ROUTES = ("TRADIER", "SMART", "LEGACY_IMPORT")
_KEY_OVERLAP = "threshold.bar_integrity.tradier_admission_min_overlap_sessions"
_KEY_SHARE = "threshold.bar_integrity.tradier_admission_min_agree_share"
_KEY_TOL = "threshold.bar_integrity.fallback_basis_tolerance_bp"
# Fallbacks equal to migrations 454 and 446; the run reads APR.
_DEFAULT_OVERLAP = 60
_DEFAULT_SHARE = 0.9
_DEFAULT_TOL = 10.0

_REPORT_COLUMNS = (
    "symbol",
    "incumbent",
    "first_observation",
    "n_common",
    "agree_share",
    "median_ratio",
    "recent_agree_share",
    "recent_first",
    "recent_last",
    "admitted",
    "admitted_recent",
    "action",
)

# The (vendor, kind) of the tradier label; canonical rows carry the pair since the 191-14
# swap.
_TRADIER_PAIR = label_to_vendor_kind(SOURCE_TRADIER)

_INCUMBENT_SQL = """
SELECT EXISTS (SELECT 1 FROM market_data_ohlcv
               WHERE symbol = $1 AND timeframe = '1d' AND vendor = $2 AND kind = $3)
"""
_OVERLAPPING_ROW_SQL = """
SELECT policy_id FROM bar_source_policy_current
WHERE timeframe = $1 AND symbol = $2
  AND daterange(valid_from, valid_to, '[)') && daterange($3::date, $4::date, '[)')
LIMIT 1
"""
_VENDOR_CODES_SQL = """
SELECT code FROM controlled_vocabulary
WHERE namespace = 'bar_vendor' AND NOT is_deprecated ORDER BY sort_order, code
"""
# ingress mode per timeframe, as the migration 446 seeds state it
INGRESS_MODE = {"1d": "observed", "15m": "derived", "1h": "derived"}
DEFAULT_INGRESS_MODE = "direct"
TIMEFRAMES = ("1d", "5m", "1m", "15m", "1h", "4h")
_DECIDED_SYMBOLS_SQL = """
SELECT DISTINCT symbol FROM bar_source_policy_current WHERE timeframe = '1d' AND symbol IS NOT NULL
"""
_INSERT_POLICY_SQL = """
INSERT INTO bar_source_policy
    (timeframe, symbol, valid_from, valid_to, ingress_mode, primary_source, fallback_source,
     reason, evidence)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
"""
_CLOSE_POLICY_SQL = """
UPDATE bar_source_policy SET valid_to = $3
WHERE timeframe = $1 AND symbol = $2 AND valid_to IS NULL AND retired_at IS NULL
"""
# The same three statements for the --reselect path, which runs on one psycopg connection so the
# policy write and select_and_write share a transaction.
_PG_OVERLAPPING_ROW_SQL = (
    _OVERLAPPING_ROW_SQL.replace("$1", "%s")
    .replace("$2", "%s")
    .replace("$3::date", "%s::date")
    .replace("$4::date", "%s::date")
)
_PG_INSERT_POLICY_SQL = (
    "INSERT INTO bar_source_policy (timeframe, symbol, valid_from, valid_to, ingress_mode, "
    "primary_source, fallback_source, reason, evidence) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)"
)
_PG_CLOSE_POLICY_SQL = (
    "UPDATE bar_source_policy SET valid_to = %s "
    "WHERE timeframe = %s AND symbol = %s AND valid_to IS NULL"
)
_FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SweepParams:
    min_overlap: int
    min_agree_share: float
    tolerance_bp: float


@dataclass(frozen=True)
class SweepRow:
    symbol: str
    incumbent: bool
    first_observation: date | None
    admission: Admission
    action: str

    def report_row(self) -> dict[str, str]:
        a = self.admission

        def num(value: float | None) -> str:
            return "" if value is None else f"{value:.6f}"

        return {
            "symbol": self.symbol,
            "incumbent": str(self.incumbent).lower(),
            "first_observation": (
                self.first_observation.isoformat() if self.first_observation else ""
            ),
            "n_common": str(a.n_common),
            "agree_share": num(a.agree_share),
            "median_ratio": num(a.median_ratio),
            "recent_agree_share": num(a.recent_agree_share),
            "recent_first": a.recent_window[0].isoformat() if a.recent_window else "",
            "recent_last": a.recent_window[1].isoformat() if a.recent_window else "",
            "admitted": str(a.admitted).lower(),
            "admitted_recent": str(a.admitted_recent).lower(),
            "action": self.action,
        }


def sweep_action(admission: Admission, *, incumbent: bool, min_overlap: int) -> str:
    """admit, write or route_185_37 (module docstring)."""
    if admission.admitted:
        return ACTION_ADMIT
    if not incumbent or admission.recent_disagrees:
        return ACTION_WRITE
    if admission.n_common < min_overlap:
        return ACTION_KEEP
    return ACTION_ROUTE


def exception_row(row: SweepRow, params: SweepParams, swept_at: datetime) -> dict[str, Any]:
    """The bar_source_policy row a write-action name gets: IBKR primary for its whole span."""
    if row.action != ACTION_WRITE or row.first_observation is None:
        raise ValueError(f"{row.symbol}: only a write-action name with observations gets a row")
    a = row.admission
    share = "none" if a.agree_share is None else f"{a.agree_share:.4f}"
    return {
        "symbol": row.symbol,
        "valid_from": row.first_observation,
        "valid_to": None,
        "primary_source": "ibkr",
        "fallback_source": None,
        "reason": (
            f"Tradier fails source admission on evidence (plan {_PLAN} Task 0): "
            f"{a.n_common} common sessions with IBKR SMART, agree share {share} within "
            f"{params.tolerance_bp:g} bp (admission needs {params.min_overlap} sessions and "
            f"{params.min_agree_share:g}); "
            + (
                "Tradier is canonical today and disagrees on the recent window too"
                if row.incumbent
                else "Tradier was never this name's canonical series"
            )
            + "; IBKR SMART stays primary, no fallback."
        ),
        "evidence": {
            "plan": _PLAN,
            "rule": "tradier_admission",
            "swept_at": swept_at.isoformat(),
            "incumbent": row.incumbent,
            "n_common": a.n_common,
            "agree_share": a.agree_share,
            "median_ratio": a.median_ratio,
            "recent_agree_share": a.recent_agree_share,
            "recent_window": [d.isoformat() for d in a.recent_window] if a.recent_window else None,
            "min_overlap_sessions": params.min_overlap,
            "min_agree_share": params.min_agree_share,
            "tolerance_bp": params.tolerance_bp,
        },
    }


def sweep_symbol(
    symbol: str,
    observations: Sequence[Observation],
    splits: Sequence[SplitRecord],
    *,
    incumbent: bool,
    first_observation: date | None,
    params: SweepParams,
) -> SweepRow:
    """One name's admission and action (pure)."""
    admission = tradier_admission(
        common_session_closes(observations, splits),
        min_overlap=params.min_overlap,
        min_agree_share=params.min_agree_share,
        tolerance_bp=params.tolerance_bp,
    )
    return SweepRow(
        symbol=symbol,
        incumbent=incumbent,
        first_observation=first_observation,
        admission=admission,
        action=sweep_action(admission, incumbent=incumbent, min_overlap=params.min_overlap),
    )


def rows_to_write(rows: Sequence[SweepRow], *, decided: frozenset[str]) -> list[SweepRow]:
    """Write-action names with no 1d symbol row at all: an open or closed row is a recorded
    decision (an exception, or one closed and routed to 185-37) the sweep never overrides."""
    return [r for r in rows if r.action == ACTION_WRITE and r.symbol not in decided]


async def insert_row(conn: Any, row: dict[str, Any]) -> bool:
    """Insert one symbol row in its own transaction; False (nothing written) if it would overlap
    a row of the same (timeframe, symbol) series. `timeframe` defaults to 1d."""
    timeframe = row.get("timeframe", "1d")
    async with conn.transaction():
        if (
            await conn.fetchval(
                _OVERLAPPING_ROW_SQL, timeframe, row["symbol"], row["valid_from"], row["valid_to"]
            )
            is not None
        ):
            return False
        await conn.execute(
            _INSERT_POLICY_SQL,
            timeframe,
            row["symbol"],
            row["valid_from"],
            row["valid_to"],
            INGRESS_MODE.get(timeframe, DEFAULT_INGRESS_MODE),
            row["primary_source"],
            row["fallback_source"],
            row["reason"],
            json.dumps(row["evidence"]),
        )
    return True


async def close_row(conn: Any, symbol: str, valid_to: date, timeframe: str = "1d") -> int:
    status = await conn.execute(_CLOSE_POLICY_SQL, timeframe, symbol, valid_to)
    return int(str(status).rsplit(None, 1)[-1])


def session_today(now: datetime | None = None) -> date:
    """Today's NYSE session date (spans match session dates, D-191-L)."""
    return (now or datetime.now(UTC)).astimezone(SESSION_TZ).date()


def backdated(timeframe: str, effective: date, today: date) -> bool:
    """A direct-timeframe policy change effective before today: selection would apply it only
    to the windows later loads touch, so it needs --reselect (module docstring)."""
    return timeframe in DIRECT_TIMEFRAMES and effective < today


def session_start(day: date) -> datetime:
    """The UTC instant a session date begins (America/New_York midnight)."""
    return datetime.combine(day, datetime.min.time(), SESSION_TZ).astimezone(UTC)


_SELECTION_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"


def write_and_reselect(conn: Any, *, mode: str, row: dict[str, Any]) -> Any:
    """The policy write and the re-selection of the window it changes, on one psycopg connection
    in the caller's transaction (the caller commits). Raises ValueError when the --add overlaps
    a row or the --close finds no open row. Returns the SelectionResult."""
    timeframe, symbol = row["timeframe"], row["symbol"]
    with conn.cursor() as cur:
        # The series' selection lock first, held to the commit: an ingress chunk selecting this
        # series waits, then reads the new policy under the same lock (select_and_write).
        cur.execute(_SELECTION_LOCK_SQL, (f"bar_selection|{symbol}|{timeframe}",))
        if mode == "add":
            cur.execute(
                _PG_OVERLAPPING_ROW_SQL, (timeframe, symbol, row["valid_from"], row["valid_to"])
            )
            if cur.fetchone() is not None:
                raise ValueError(f"{symbol} {timeframe} has an overlapping policy row")
            cur.execute(
                _PG_INSERT_POLICY_SQL,
                (
                    timeframe,
                    symbol,
                    row["valid_from"],
                    row["valid_to"],
                    INGRESS_MODE.get(timeframe, DEFAULT_INGRESS_MODE),
                    row["primary_source"],
                    row["fallback_source"],
                    row["reason"],
                    json.dumps(row["evidence"]),
                ),
            )
            first, last = row["valid_from"], row["valid_to"]
        else:
            cur.execute(_PG_CLOSE_POLICY_SQL, (row["valid_to"], timeframe, symbol))
            if cur.rowcount != 1:
                raise ValueError(f"{symbol} {timeframe}: {cur.rowcount} open rows closed, not 1")
            first, last = row["valid_to"], None
        params = read_raw_params(cur)  # the policy as this transaction now sees it
    return select_and_write(
        conn,
        symbols=[symbol],
        timeframe=timeframe,
        start=session_start(first),
        end=session_start(last) if last else _FAR_FUTURE,
        policy_rows=params.policy_rows,
        kind_order=params.kind_order,
        batch_rows=params.write.batch_rows,
    )


def run_reselect(settings: Any, *, mode: str, row: dict[str, Any]) -> int:
    """--reselect: write and re-select in one transaction, then gate the series."""
    from scripts.ops.bars import ops_selection_gate as gate

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn:
        try:
            result = write_and_reselect(conn, mode=mode, row=row)
        except ValueError as error:
            conn.rollback()
            print(f"refused: {error}")
            return 2
        conn.commit()
    print(
        f"{mode} {row['symbol']} {row['timeframe']}: re-selected, new {result.new} replaced "
        f"{result.changed} unchanged {result.unchanged} unselected {result.unselected}"
    )
    return gate.main(["--compare", "--symbols", row["symbol"], "--timeframes", row["timeframe"]])


async def read_vendor_codes(conn: Any) -> list[str]:
    """The valid vendor codes: the CVR `bar_vendor` namespace, not deprecated."""
    return [r["code"] for r in await conn.fetch(_VENDOR_CODES_SQL)]


def check_vendors(codes: Sequence[str], *vendors: str | None) -> None:
    """SystemExit naming the valid list when a given vendor is not a CVR bar_vendor code."""
    for vendor in vendors:
        if vendor is not None and vendor not in codes:
            raise SystemExit(
                f"unknown vendor {vendor!r}; valid bar_vendor codes: {', '.join(codes)}"
            )


async def _load(
    conn: Any, symbol: str
) -> tuple[list[Observation], list[SplitRecord], bool, date | None]:
    # The daily stage's own raw read (phase 191 plan 08); the sweep measures the vendors' own
    # answers, so the corpus import (route LEGACY_IMPORT) stays out as before.
    inputs, splits = await read_daily_inputs(conn, symbol)
    observations = [o for o in inputs if o.route in _ROUTES]
    incumbent = bool(await conn.fetchval(_INCUMBENT_SQL, symbol, *_TRADIER_PAIR))
    # valid_from covers every route d2-v2 reads (LEGACY_IMPORT included), so no earlier date
    # falls back to the Tradier default. The raw read already holds them (plan 191-11: the
    # first TRADES date comes from the same current raw rows, not from ohlcv_observation).
    dates = [o.bar_date for o in inputs if o.route in _D2V2_ROUTES and o.what_to_show == "TRADES"]
    first = min(dates) if dates else None
    return observations, splits, incumbent, first


async def run_sweep(
    conn: Any, *, symbols: list[str] | None, apply: bool, report: str | None
) -> int:
    apr = await load_apr_dict_async(conn, ["threshold.bar_integrity.%"])
    params = SweepParams(
        min_overlap=int(_cfg(apr, _KEY_OVERLAP, _DEFAULT_OVERLAP)),
        min_agree_share=float(_cfg(apr, _KEY_SHARE, _DEFAULT_SHARE)),
        tolerance_bp=float(_cfg(apr, _KEY_TOL, _DEFAULT_TOL)),
    )
    names = symbols or [r[0] for r in await conn.fetch(_DISCOVER_DAILY_SYMBOLS_SQL)]
    rows: list[SweepRow] = []
    for symbol in names:
        observations, splits, incumbent, first = await _load(conn, symbol)
        rows.append(
            sweep_symbol(
                symbol,
                observations,
                splits,
                incumbent=incumbent,
                first_observation=first,
                params=params,
            )
        )
    if report:
        with Path(report).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_REPORT_COLUMNS, delimiter="\t")
            writer.writeheader()
            for row in rows:
                writer.writerow(row.report_row())
    failing = [r for r in rows if r.action != ACTION_ADMIT]
    print(f"params {params}")
    print(f"names {len(rows)}; admitted {len(rows) - len(failing)}; failing {len(failing)}")
    print("symbol\tincumbent\tn_common\tagree_share\tmedian_ratio\trecent_agree_share\taction")
    for r in failing:
        line = r.report_row()
        print(
            "\t".join(
                line[c]
                for c in (
                    "symbol",
                    "incumbent",
                    "n_common",
                    "agree_share",
                    "median_ratio",
                    "recent_agree_share",
                    "action",
                )
            )
        )
    by_action = {
        a: sum(1 for r in failing if r.action == a)
        for a in (ACTION_WRITE, ACTION_ROUTE, ACTION_KEEP)
    }
    print(f"actions {by_action}")
    if not apply:
        print("dry run: no row written (use --apply)")
        return 0
    swept_at = datetime.now(UTC)
    decided = frozenset(r[0] for r in await conn.fetch(_DECIDED_SYMBOLS_SQL))
    to_write = rows_to_write(failing, decided=decided)
    print(
        f"already decided (any symbol row), skipped: {sum(1 for r in failing if r.action == ACTION_WRITE) - len(to_write)}"
    )
    written, refused = 0, []
    for r in to_write:
        if r.first_observation is None:
            refused.append(f"{r.symbol} (no observation)")
            continue
        if await insert_row(conn, exception_row(r, params, swept_at)):
            written += 1
        else:
            refused.append(f"{r.symbol} (open symbol row exists)")
    print(f"written {written}; refused {len(refused)}: {refused}")
    return 2 if refused else 0


def _parse_date(text: str) -> date:
    return date.fromisoformat(text)


# --plan (migration 520, D-191-P): a ranking decision applied as one transaction. The 1d decision
# (D-191-Q, todo 545) extends it: retire_defaults takes every live default of the timeframe out of
# force (the closed Tradier default and the open IBKR default) instead of closing the open one at
# the seam, and the plan names every live symbol row explicitly, each either retired with a
# disposition (replaced by a new symbol row, or confirmed by the arbitration) or kept.
_RETIRE_SYMBOL_ROWS_SQL = """
UPDATE bar_source_policy SET retired_at = now(), retired_reason = $2
WHERE timeframe = $1 AND symbol IS NOT NULL AND retired_at IS NULL
"""
_RETIRE_ROW_SQL = """
UPDATE bar_source_policy SET retired_at = now(), retired_reason = $2
WHERE policy_id = $1::uuid AND symbol IS NOT NULL AND retired_at IS NULL
"""
_RETIRE_DEFAULTS_SQL = """
UPDATE bar_source_policy SET retired_at = now(), retired_reason = $2
WHERE timeframe = $1 AND symbol IS NULL AND retired_at IS NULL
"""
_CLOSE_DEFAULT_SQL = """
UPDATE bar_source_policy SET valid_to = $2
WHERE timeframe = $1 AND symbol IS NULL AND valid_to IS NULL AND retired_at IS NULL
"""
_LIVE_ROWS_SQL = """
SELECT count(*) FILTER (WHERE symbol IS NOT NULL), count(*) FILTER (WHERE symbol IS NULL)
FROM bar_source_policy_current WHERE timeframe = $1
"""
_LIVE_SYMBOL_IDS_SQL = """
SELECT policy_id::text AS policy_id FROM bar_source_policy_current
WHERE timeframe = $1 AND symbol IS NOT NULL
"""
DISPOSITIONS = ("replaced", "superseded_by_default")
_LOCK_SQL = "LOCK TABLE bar_source_policy IN SHARE ROW EXCLUSIVE MODE"
_LIVE_DEFAULT_IDS_SQL = """
SELECT policy_id::text AS policy_id FROM bar_source_policy_current
WHERE timeframe = $1 AND symbol IS NULL
"""
# The 1d raw rows the arbitration read, through its window end ($1): per series the row count and
# the latest serve. A plan built on other raw data is refused (second review M2).
_RAW_FINGERPRINT_SQL = """
SELECT r.vendor, r.kind, count(*) AS n_rows, max(r.served_at) AS max_served_at
FROM ohlcv_raw r
JOIN unnest($2::text[], $3::text[]) AS s(vendor, kind) ON s.vendor = r.vendor AND s.kind = r.kind
WHERE r.timeframe = '1d' AND r."timestamp" < (($1::date + 1)::timestamp AT TIME ZONE 'UTC')
GROUP BY r.vendor, r.kind
"""
_QUARANTINE_RULES_SQL = """
SELECT config_value FROM config_state WHERE config_key = 'threshold.bar_scrub.quarantine_rules'
"""
QUARANTINE_RULE_VERSION = "d191q-arbitration"
_QUARANTINE_FIELDS = ("open", "high", "low", "close")
# Timeframes whose plan must name every live symbol row (an implicit retire-all would drop the
# 185-37 evidence rows unread).
EXPLICIT_TIMEFRAMES = frozenset({"1d"})


@dataclass(frozen=True)
class PolicyPlan:
    """A ranking decision for one timeframe (--plan). Default: retire every live symbol row,
    close the live default at `seam` (it stays the rule before the seam), insert `defaults` from
    the seam on. With retire_defaults every live default is retired and `defaults` tile the whole
    span; with explicit symbol-row lists only the named rows retire and `symbol_rows` are
    inserted. All or nothing, one transaction."""

    timeframe: str
    seam: date
    defaults: tuple[dict[str, Any], ...]
    reason: str
    evidence: dict[str, Any]
    retire_defaults: bool = False
    symbol_rows: tuple[dict[str, Any], ...] = ()
    retire_symbol_rows: tuple[dict[str, Any], ...] | None = None
    keep_symbol_rows: tuple[dict[str, Any], ...] = ()
    retire_default_ids: tuple[str, ...] | None = None
    raw_fingerprint: dict[str, Any] | None = None
    hold: tuple[dict[str, Any], ...] = ()
    quarantine: tuple[dict[str, Any], ...] = ()
    quarantine_rule: str | None = None


async def read_raw_fingerprint(conn: Any, through: date) -> dict[str, Any]:
    """Per 1d raw input series, its row count and latest served_at through `through`."""
    rows = await conn.fetch(
        _RAW_FINGERPRINT_SQL,
        through,
        [v for v, _k in RAW_DAILY_SERIES],
        [k for _v, k in RAW_DAILY_SERIES],
    )
    return {
        "through": through.isoformat(),
        "series": {
            f"{r['vendor']}/{r['kind']}": {
                "rows": int(r["n_rows"]),
                "max_served_at": r["max_served_at"].isoformat() if r["max_served_at"] else None,
            }
            for r in sorted(rows, key=lambda r: (r["vendor"], r["kind"]))
        },
    }


async def read_quarantine_rules(conn: Any) -> frozenset[str]:
    """The APR list of rules whose flags quarantine a bar (threshold.bar_scrub.quarantine_rules)."""
    raw = await conn.fetchval(_QUARANTINE_RULES_SQL)
    return frozenset(json.loads(raw)) if raw else frozenset()


def _plan_row(raw: dict[str, Any], row: dict[str, Any], symbol: str | None) -> dict[str, Any]:
    return {
        "timeframe": raw["timeframe"],
        "symbol": symbol,
        "valid_from": _parse_date(row["valid_from"]),
        "valid_to": _parse_date(row["valid_to"]) if row.get("valid_to") else None,
        "primary_source": row["primary"],
        "fallback_source": row.get("fallback"),
        "reason": raw["reason"],
        "evidence": row.get("evidence", raw["evidence"]) if symbol else raw["evidence"],
    }


def _parse_symbol_lists(
    raw: dict[str, Any], symbol_rows: list[dict[str, Any]]
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    retire = tuple(raw["retire_symbol_rows"])
    keep = tuple(raw.get("keep_symbol_rows") or ())
    new_symbols = {r["symbol"] for r in symbol_rows}
    seen: set[str] = set()
    for row in (*retire, *keep):
        if row["policy_id"] in seen:
            raise ValueError(f"symbol row {row['policy_id']} is listed twice")
        seen.add(row["policy_id"])
    for row in retire:
        if row.get("disposition") not in DISPOSITIONS:
            raise ValueError(
                f"{row['symbol']}: disposition {row.get('disposition')!r} is not one of "
                f"{DISPOSITIONS}"
            )
        if not isinstance(row.get("evidence"), dict):
            raise ValueError(f"{row['symbol']}: a retired row needs its evidence object")
        if row["disposition"] == "replaced" and row["symbol"] not in new_symbols:
            raise ValueError(
                f"{row['symbol']}: replaced, but the plan has no new symbol row for it"
            )
    for row in keep:
        if not row.get("reason"):
            raise ValueError(f"{row['symbol']}: a kept row needs its reason")
        if row["symbol"] in new_symbols:
            raise ValueError(
                f"{row['symbol']}: a kept row and new symbol rows of one name would overlap"
            )
    return retire, keep


def _covers(row: dict[str, Any], start: date, end: date) -> bool:
    valid_to = row["valid_to"]
    return row["valid_from"] <= start and (valid_to is None or valid_to > end)


def _check_hold_coverage(
    hold: Sequence[dict[str, Any]],
    symbol_rows: Sequence[dict[str, Any]],
    keep: Sequence[dict[str, Any]],
) -> None:
    """A hold means the name's consolidated source does not serve the span: a new symbol row or
    a kept row must cover it (second review H1)."""
    kept = [
        {
            "symbol": k["symbol"],
            "valid_from": _parse_date(k["valid_from"]),
            "valid_to": _parse_date(k["valid_to"]) if k.get("valid_to") else None,
        }
        for k in keep
        if k.get("valid_from")
    ]
    for h in hold:
        start, end = _parse_date(h["start"]), _parse_date(h["end"])
        if not any(
            r["symbol"] == h["symbol"] and _covers(r, start, end) for r in (*symbol_rows, *kept)
        ):
            raise ValueError(
                f"{h['symbol']}: hold span {h['start']}..{h['end']} is not covered by a symbol row"
            )


def parse_plan(raw: dict[str, Any]) -> PolicyPlan:
    """Validate a --plan file. The new defaults must tile [first, open end) with no gap or
    overlap. Without retire_defaults they start at the seam (the closed old default covers the
    span before it); with it the seam is one of their boundaries. A 1d plan names every live
    symbol row: retire_symbol_rows (disposition replaced or confirmed, with evidence) and
    keep_symbol_rows (with a reason); a replaced name has new symbol_rows."""
    for key in ("timeframe", "seam", "defaults", "reason", "evidence"):
        if key not in raw:
            raise ValueError(f"plan needs {key!r}")
    if raw["timeframe"] not in TIMEFRAMES:
        raise ValueError(f"unknown timeframe {raw['timeframe']!r}")
    if not isinstance(raw["evidence"], dict) or not raw["evidence"]:
        raise ValueError("plan evidence must be a non-empty JSON object")
    seam = _parse_date(raw["seam"])
    retire_defaults = bool(raw.get("retire_defaults", False))
    explicit = raw.get("retire_symbol_rows") is not None
    if raw["timeframe"] in EXPLICIT_TIMEFRAMES and not explicit:
        raise ValueError(
            f"a {raw['timeframe']} plan must name every live symbol row explicitly "
            "(retire_symbol_rows and keep_symbol_rows)"
        )
    defaults = sorted(
        (_plan_row(raw, row, None) for row in raw["defaults"]), key=lambda r: r["valid_from"]
    )
    if not defaults or defaults[-1]["valid_to"] is not None:
        raise ValueError("the last new default must be open-ended")
    for before, after in zip(defaults, defaults[1:], strict=False):
        if before["valid_to"] != after["valid_from"]:
            raise ValueError(f"new defaults leave a gap or overlap at {before['valid_to']}")
    if retire_defaults:
        if seam not in {r["valid_from"] for r in defaults}:
            raise ValueError(f"the seam {seam} is not a boundary of the new defaults")
    elif defaults[0]["valid_from"] != seam:
        raise ValueError(
            f"the new defaults must start at the seam {seam}; the closed old default covers "
            "the span before it"
        )
    symbol_rows: list[dict[str, Any]] = []
    for row in raw.get("symbol_rows") or ():
        if not isinstance(row.get("evidence"), dict) or not row["evidence"]:
            raise ValueError(f"{row.get('symbol')}: a symbol row needs a non-empty evidence object")
        symbol_rows.append(_plan_row(raw, row, row["symbol"]))
    if symbol_rows and not explicit:
        raise ValueError("new symbol rows need the explicit symbol-row lists")
    symbol_rows.sort(key=lambda r: (r["symbol"], r["valid_from"]))
    for before, after in zip(symbol_rows, symbol_rows[1:], strict=False):
        if before["symbol"] == after["symbol"] and (
            before["valid_to"] is None or before["valid_to"] > after["valid_from"]
        ):
            raise ValueError(
                f"{before['symbol']}: new symbol rows overlap at {after['valid_from']}"
            )
    retire, keep = _parse_symbol_lists(raw, symbol_rows) if explicit else (None, ())
    default_ids = raw.get("retire_default_ids")
    fingerprint = raw.get("raw_fingerprint")
    if raw["timeframe"] in EXPLICIT_TIMEFRAMES:
        if retire_defaults and (not default_ids or len(set(default_ids)) != 2):
            raise ValueError(
                "a 1d plan pins exactly the 2 live default policy_ids it retires "
                "(retire_default_ids)"
            )
        if not isinstance(fingerprint, dict) or not fingerprint.get("series"):
            raise ValueError("a 1d plan carries the raw fingerprint its arbitration read")
    hold = tuple(raw.get("hold") or ())
    _check_hold_coverage(hold, symbol_rows, keep)
    quarantine = tuple(raw.get("quarantine") or ())
    if quarantine and not raw.get("quarantine_rule"):
        raise ValueError("a quarantine list needs its quarantine_rule")
    return PolicyPlan(
        raw["timeframe"],
        seam,
        tuple(defaults),
        raw["reason"],
        raw["evidence"],
        retire_defaults=retire_defaults,
        symbol_rows=tuple(symbol_rows),
        retire_symbol_rows=retire,
        keep_symbol_rows=keep,
        retire_default_ids=tuple(default_ids) if default_ids else None,
        raw_fingerprint=fingerprint,
        hold=hold,
        quarantine=quarantine,
        quarantine_rule=raw.get("quarantine_rule"),
    )


def _count(status: object) -> int:
    return int(str(status).split()[-1])


async def _retire_named_symbol_rows(conn: Any, plan: PolicyPlan) -> int:
    """Retire exactly the rows the plan names; refuse when a live row is unnamed or a named row
    is not live (the plan was built on another state of the table)."""
    assert plan.retire_symbol_rows is not None
    live = {r["policy_id"] for r in await conn.fetch(_LIVE_SYMBOL_IDS_SQL, plan.timeframe)}
    named = {r["policy_id"] for r in (*plan.retire_symbol_rows, *plan.keep_symbol_rows)}
    if live - named:
        raise ValueError(
            f"{plan.timeframe}: {len(live - named)} live symbol row(s) not named by the plan: "
            f"{sorted(live - named)[:10]}"
        )
    if named - live:
        raise ValueError(
            f"{plan.timeframe}: {len(named - live)} named row(s) are not live: "
            f"{sorted(named - live)[:10]}"
        )
    for row in plan.retire_symbol_rows:
        reason = f"{plan.reason}: {row['disposition']}"
        if _count(await conn.execute(_RETIRE_ROW_SQL, row["policy_id"], reason)) != 1:
            raise ValueError(f"symbol row {row['policy_id']} did not retire")
    return len(plan.retire_symbol_rows)


async def _insert(conn: Any, plan: PolicyPlan, row: dict[str, Any]) -> None:
    await conn.execute(
        _INSERT_POLICY_SQL,
        plan.timeframe,
        row["symbol"],
        row["valid_from"],
        row["valid_to"],
        INGRESS_MODE.get(plan.timeframe, DEFAULT_INGRESS_MODE),
        row["primary_source"],
        row["fallback_source"],
        row["reason"],
        json.dumps(row["evidence"]),
    )


async def apply_plan(conn: Any, plan: PolicyPlan, *, apply: bool) -> dict[str, int]:
    """Retire, close and insert in one transaction; a dry run rolls it back. Returns the counts."""
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(_LOCK_SQL)
        await _check_plan_preconditions(conn, plan)
        before = await conn.fetchrow(_LIVE_ROWS_SQL, plan.timeframe)
        if plan.retire_symbol_rows is not None:
            retired = await _retire_named_symbol_rows(conn, plan)
        else:
            retired = _count(
                await conn.execute(_RETIRE_SYMBOL_ROWS_SQL, plan.timeframe, plan.reason)
            )
        closed = defaults_retired = 0
        if plan.retire_defaults:
            defaults_retired = _count(
                await conn.execute(_RETIRE_DEFAULTS_SQL, plan.timeframe, plan.reason)
            )
            if defaults_retired < 1:
                raise ValueError(f"{plan.timeframe}: no live default to retire")
        else:
            closed = _count(await conn.execute(_CLOSE_DEFAULT_SQL, plan.timeframe, plan.seam))
            if closed != 1:
                raise ValueError(f"{plan.timeframe}: {closed} live open defaults closed, not 1")
        for row in (*plan.defaults, *plan.symbol_rows):
            await _insert(conn, plan, row)
        after = await conn.fetchrow(_LIVE_ROWS_SQL, plan.timeframe)
        quarantined = await _write_quarantine(conn, plan) if plan.quarantine else 0
    except BaseException:
        await tx.rollback()
        raise
    if apply:
        await tx.commit()
    else:
        await tx.rollback()
    return {
        "symbol_rows_before": before[0],
        "defaults_before": before[1],
        "retired": retired,
        "kept": len(plan.keep_symbol_rows),
        "default_closed": closed,
        "defaults_retired": defaults_retired,
        "inserted": len(plan.defaults),
        "symbol_rows_inserted": len(plan.symbol_rows),
        "symbol_rows_after": after[0],
        "defaults_after": after[1],
        "quarantined": quarantined,
    }


async def _check_plan_preconditions(conn: Any, plan: PolicyPlan) -> None:
    """Under the table lock: the raw data and the live defaults are the ones the plan was built
    on, and a quarantine rule really quarantines."""
    if plan.raw_fingerprint is not None:
        through = _parse_date(plan.raw_fingerprint["through"])
        now = await read_raw_fingerprint(conn, through)
        if now != plan.raw_fingerprint:
            raise ValueError(
                f"raw fingerprint changed since the arbitration (plan {plan.raw_fingerprint}, "
                f"now {now}): re-run ops_d191q_arbitration"
            )
    if plan.retire_default_ids is not None:
        live = {r["policy_id"] for r in await conn.fetch(_LIVE_DEFAULT_IDS_SQL, plan.timeframe)}
        if live != set(plan.retire_default_ids):
            raise ValueError(
                f"{plan.timeframe}: live default ids {sorted(live)} are not the pinned "
                f"{sorted(plan.retire_default_ids)}"
            )
    if plan.quarantine:
        rules = await read_quarantine_rules(conn)
        if plan.quarantine_rule not in rules:
            raise ValueError(
                f"{plan.quarantine_rule!r} is not in threshold.bar_scrub.quarantine_rules, so its "
                "flags would not quarantine; add it to the APR list first"
            )


async def _write_quarantine(conn: Any, plan: PolicyPlan) -> int:
    """The quarantine sessions as bar_quality_flag rows through the flag writer (bar_scrub's
    write_flags, the table's one writer path), under one scrub batch. Runs last: the batch and
    flag writes SET LOCAL ROLE bar_derivation_writer for the rest of the transaction."""
    rule = plan.quarantine_rule
    assert rule is not None
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for q in plan.quarantine:
        by_symbol.setdefault(q["symbol"], []).append(q)
    batch_id = await open_batch(
        conn,
        stage="scrub",
        rule_version=QUARANTINE_RULE_VERSION,
        apr_snapshot={"threshold.bar_scrub.quarantine_rules": [rule]},
        n_symbols=len(by_symbol),
        detail={"source": "ops_source_policy --plan", "reason": plan.reason},
    )
    written = 0
    for symbol, sessions in sorted(by_symbol.items()):
        flags = [
            FlagRow(
                timestamp=datetime.combine(_parse_date(q["session"]), datetime.min.time(), UTC),
                rule=rule,
                rule_version=QUARANTINE_RULE_VERSION,
                fields=_QUARANTINE_FIELDS,
                quarantine=True,
                detail={k: v for k, v in q.items() if k not in ("symbol", "session")},
            )
            for q in sorted(sessions, key=lambda q: q["session"])
        ]
        written += await write_flags(
            conn,
            tf="1d",
            symbol=symbol,
            rules_evaluated=frozenset({rule}),
            flags=flags,
            start=None,
            end=None,
            batch_id=batch_id,
        )
    await close_batch(conn, batch_id, status="completed", detail={"quarantined": written})
    return written


def reselect_series(settings: Any, *, timeframe: str, symbols: Sequence[str], start: date) -> int:
    """--reselect-only: re-select each series from `start` on, one transaction per symbol under
    its selection lock (select_and_write takes it), then gate the series. Run after a backdated
    --plan on a direct timeframe."""
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    totals = dict.fromkeys(("new", "changed", "unchanged", "unselected", "excluded", "dropped"), 0)
    with psycopg.connect(dsn) as conn:
        for i, symbol in enumerate(symbols, 1):
            with conn.cursor() as cur:
                params = read_raw_params(cur)
            result = select_and_write(
                conn,
                symbols=[symbol],
                timeframe=timeframe,
                start=session_start(start),
                end=_FAR_FUTURE,
                policy_rows=None,
                kind_order=params.kind_order,
                batch_rows=params.write.batch_rows,
            )
            conn.commit()
            for key in totals:
                totals[key] += getattr(result, key)
            print(
                f"[{i}/{len(symbols)}] {symbol} {timeframe}: new {result.new} replaced "
                f"{result.changed} unchanged {result.unchanged} retracted {result.dropped}",
                flush=True,
            )
    print(f"reselect totals: {totals}", flush=True)
    # The gate runs its own event loop (asyncio.run); this mode is reached from _main's loop, so
    # the gate runs as a subprocess (calling gate.main here raised "asyncio.run() cannot be
    # called from a running event loop" on 2026-10-27).
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ops.bars.ops_selection_gate",
            "--compare",
            "--symbols",
            *symbols,
            "--timeframes",
            timeframe,
        ],
        cwd=project_root,
        check=False,
    ).returncode


async def _main(args: argparse.Namespace) -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        if args.admission_sweep:
            symbols = (
                [s.strip() for part in args.symbols for s in part.split(",") if s.strip()]
                if args.symbols
                else None
            )
            return await run_sweep(conn, symbols=symbols, apply=args.apply, report=args.report)
        if args.add:
            check_vendors(await read_vendor_codes(conn), args.primary, args.fallback)
            row = {
                "timeframe": args.timeframe,
                "symbol": args.symbol,
                "valid_from": _parse_date(args.valid_from),
                "valid_to": _parse_date(args.valid_to) if args.valid_to else None,
                "primary_source": args.primary,
                "fallback_source": args.fallback,
                "reason": args.reason,
                "evidence": json.loads(args.evidence),
            }
            if backdated(args.timeframe, row["valid_from"], session_today()) and not args.reselect:
                print(
                    f"refused: {args.timeframe} valid_from {row['valid_from']} is before today; "
                    "a backdated direct-timeframe span needs --reselect (module docstring)"
                )
                return 2
            if not args.apply:
                print(f"dry run: would insert {row}")
                return 0
            if args.reselect:
                return run_reselect(settings, mode="add", row=row)
            if not await insert_row(conn, row):
                print(f"refused: {args.symbol} {args.timeframe} has an overlapping policy row")
                return 2
            print(f"inserted {args.symbol}")
            return 0
        if args.close:
            print(f"close {args.symbol} {args.timeframe} at {args.valid_to}: {args.reason}")
            valid_to = _parse_date(args.valid_to)
            if backdated(args.timeframe, valid_to, session_today()) and not args.reselect:
                print(
                    f"refused: {args.timeframe} valid_to {valid_to} is before today; closing "
                    "a direct-timeframe span in the past needs --reselect (module docstring)"
                )
                return 2
            if not args.apply:
                print("dry run: nothing closed (use --apply)")
                return 0
            if args.reselect:
                return run_reselect(
                    settings,
                    mode="close",
                    row={"timeframe": args.timeframe, "symbol": args.symbol, "valid_to": valid_to},
                )
            n = await close_row(conn, args.symbol, _parse_date(args.valid_to), args.timeframe)
            print(f"closed {n} row(s)")
            return 0 if n == 1 else 2
        if args.plan:
            plan = parse_plan(json.loads(Path(args.plan).read_text()))
            check_vendors(
                await read_vendor_codes(conn),
                *[
                    v
                    for r in (*plan.defaults, *plan.symbol_rows)
                    for v in (r["primary_source"], r["fallback_source"])
                ],
            )
            counts = await apply_plan(conn, plan, apply=args.apply)
            print(f"{'applied' if args.apply else 'dry run (rolled back)'}: {counts}")
            if plan.quarantine:
                print(
                    f"quarantine: {len(plan.quarantine)} session flag(s) ({plan.quarantine_rule})"
                )
            if plan.timeframe == "1d":
                print(
                    "next: the daily stage re-derives 1d under the new rows (plan 20 Task 3, "
                    "services.bar_derivation --stage daily); D7 judges it"
                )
            if plan.timeframe in DIRECT_TIMEFRAMES:
                print(
                    f"next, before any {plan.timeframe} consumer runs: --reselect-only "
                    f"--timeframe {plan.timeframe} --valid-from {plan.seam} --symbols <every name "
                    "whose canonical changes>; then ops_selection_gate --compare over all "
                    f"{plan.timeframe} names, then a full (not --changed-only) grid derivation of "
                    "the reselected names"
                )
            return 0
        if args.reselect_only:
            symbols = [s.strip() for part in args.symbols for s in part.split(",") if s.strip()]
            return reselect_series(
                settings,
                timeframe=args.timeframe,
                symbols=symbols,
                start=_parse_date(args.valid_from),
            )
        raise SystemExit("choose --admission-sweep, --add, --close, --plan or --reselect-only")
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--admission-sweep", action="store_true")
    mode.add_argument("--add", action="store_true")
    mode.add_argument("--close", action="store_true")
    mode.add_argument("--plan", help="JSON ranking decision applied in one transaction (520)")
    mode.add_argument("--reselect-only", action="store_true")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--report", default=None, help="sweep: per-name TSV path")
    parser.add_argument("--symbol")
    parser.add_argument("--valid-from")
    parser.add_argument("--valid-to")
    parser.add_argument("--timeframe", choices=TIMEFRAMES, default="1d")
    parser.add_argument("--primary", help="a CVR bar_vendor code (checked at run time)")
    parser.add_argument("--fallback", default=None, help="a CVR bar_vendor code or omitted")
    parser.add_argument("--reason")
    parser.add_argument("--evidence", help="JSON object")
    parser.add_argument(
        "--reselect",
        action="store_true",
        help="direct timeframes: write a backdated row and re-select its window in one "
        "transaction, then run the gate over the series (module docstring)",
    )
    args = parser.parse_args(argv)
    _validate(args)
    return asyncio.run(_main(args))


def _validate(args: argparse.Namespace) -> None:
    """Refuse an incomplete --add or --close before any connection opens."""
    if args.add:
        if not (args.symbol and args.valid_from and args.primary and args.reason):
            raise SystemExit("--add needs --symbol, --valid-from, --primary and --reason")
        evidence = json.loads(args.evidence or "null")
        if not isinstance(evidence, dict) or not evidence:
            raise SystemExit("--add needs --evidence, a non-empty JSON object")
    if args.close and not (args.symbol and args.valid_to and args.reason):
        raise SystemExit("--close needs --symbol, --valid-to and --reason")
    if args.reselect_only and not (args.symbols and args.valid_from):
        raise SystemExit("--reselect-only needs --symbols, --valid-from and --timeframe")


if __name__ == "__main__":
    sys.exit(main())
