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

--add: one symbol row by hand (185-37), --evidence JSON required.
--close: close a name's open 1d symbol row at --valid-to (the only UPDATE the table's trigger
allows); --reason required and printed, since the closed row's own fields are immutable.

Rollback of an exception row: --close it and rerun the daily dry run.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_apr_dict_async  # noqa: E402
from services.bar_derivation import (  # noqa: E402
    _D2V2_ROUTES,
    _DISCOVER_DAILY_SYMBOLS_SQL,
    _SELECT_DAILY_OBSERVATIONS_SQL,
    _SELECT_DAILY_SPLITS_SQL,
)
from src.config.settings import Settings  # noqa: E402
from src.intelligence.bars.derivation import Observation, SplitRecord  # noqa: E402
from src.intelligence.bars.source_admission import (  # noqa: E402
    Admission,
    common_session_closes,
    tradier_admission,
)

ACTION_ADMIT = "admit"
ACTION_WRITE = "write"
ACTION_ROUTE = "route_185_37"
ACTION_KEEP = "keep_no_overlap"
_PLAN = "185-38"
_ROUTES = ("TRADIER", "SMART")
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

_INCUMBENT_SQL = """
SELECT EXISTS (SELECT 1 FROM market_data_ohlcv
               WHERE symbol = $1 AND timeframe = '1d' AND source = 'tradier')
"""
_FIRST_OBSERVATION_SQL = """
SELECT min(bar_date) FROM ohlcv_observation
WHERE symbol = $1 AND timeframe = '1d' AND what_to_show = 'TRADES'
  AND route = ANY($2::text[])
"""
_OPEN_SYMBOL_ROW_SQL = """
SELECT policy_id FROM bar_source_policy
WHERE timeframe = '1d' AND symbol = $1 AND valid_to IS NULL
"""
_DECIDED_SYMBOLS_SQL = """
SELECT DISTINCT symbol FROM bar_source_policy WHERE timeframe = '1d' AND symbol IS NOT NULL
"""
_INSERT_POLICY_SQL = """
INSERT INTO bar_source_policy
    (timeframe, symbol, valid_from, valid_to, ingress_mode, primary_source, fallback_source,
     reason, evidence)
VALUES ('1d', $1, $2, $3, 'observed', $4, $5, $6, $7::jsonb)
"""
_CLOSE_POLICY_SQL = """
UPDATE bar_source_policy SET valid_to = $2
WHERE timeframe = '1d' AND symbol = $1 AND valid_to IS NULL
"""


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
    """Insert one symbol row in its own transaction; False (nothing written) if one is open."""
    async with conn.transaction():
        if await conn.fetchval(_OPEN_SYMBOL_ROW_SQL, row["symbol"]) is not None:
            return False
        await conn.execute(
            _INSERT_POLICY_SQL,
            row["symbol"],
            row["valid_from"],
            row["valid_to"],
            row["primary_source"],
            row["fallback_source"],
            row["reason"],
            json.dumps(row["evidence"]),
        )
    return True


async def close_row(conn: Any, symbol: str, valid_to: date) -> int:
    status = await conn.execute(_CLOSE_POLICY_SQL, symbol, valid_to)
    return int(str(status).rsplit(None, 1)[-1])


async def _load(
    conn: Any, symbol: str
) -> tuple[list[Observation], list[SplitRecord], bool, date | None]:
    obs_rows = await conn.fetch(_SELECT_DAILY_OBSERVATIONS_SQL, symbol, list(_ROUTES))
    observations = [
        Observation(
            request_id=r["request_id"],
            route=r["route"],
            bar_date=r["bar_date"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
            fetched_at=r["fetched_at"],
            legacy=r["legacy"],
            what_to_show=r["what_to_show"],
        )
        for r in obs_rows
    ]
    splits = [
        SplitRecord(
            effective_date=r["effective_date"],
            recorded_at=r["recorded_at"],
            factor=r["factor"],
            evidence_request_ids=tuple(r["evidence_request_ids"] or ()),
        )
        for r in await conn.fetch(_SELECT_DAILY_SPLITS_SQL, symbol)
    ]
    incumbent = bool(await conn.fetchval(_INCUMBENT_SQL, symbol))
    # valid_from covers every route d2-v2 reads (LEGACY_IMPORT included), so no earlier date
    # falls back to the Tradier default.
    first = await conn.fetchval(_FIRST_OBSERVATION_SQL, symbol, list(_D2V2_ROUTES))
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
            row = {
                "symbol": args.symbol,
                "valid_from": _parse_date(args.valid_from),
                "valid_to": _parse_date(args.valid_to) if args.valid_to else None,
                "primary_source": args.primary,
                "fallback_source": args.fallback,
                "reason": args.reason,
                "evidence": json.loads(args.evidence),
            }
            if not args.apply:
                print(f"dry run: would insert {row}")
                return 0
            if not await insert_row(conn, row):
                print(f"refused: {args.symbol} has an open 1d symbol row")
                return 2
            print(f"inserted {args.symbol}")
            return 0
        if args.close:
            print(f"close {args.symbol} at {args.valid_to}: {args.reason}")
            if not args.apply:
                print("dry run: nothing closed (use --apply)")
                return 0
            n = await close_row(conn, args.symbol, _parse_date(args.valid_to))
            print(f"closed {n} row(s)")
            return 0 if n == 1 else 2
        raise SystemExit("choose --admission-sweep, --add or --close")
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--admission-sweep", action="store_true")
    mode.add_argument("--add", action="store_true")
    mode.add_argument("--close", action="store_true")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--report", default=None, help="sweep: per-name TSV path")
    parser.add_argument("--symbol")
    parser.add_argument("--valid-from")
    parser.add_argument("--valid-to")
    parser.add_argument("--primary", choices=["tradier", "ibkr"])
    parser.add_argument("--fallback", choices=["tradier", "ibkr"], default=None)
    parser.add_argument("--reason")
    parser.add_argument("--evidence", help="JSON object")
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


if __name__ == "__main__":
    sys.exit(main())
