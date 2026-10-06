"""Gated recovery of intraday history from before a stock's listing-venue move (plan 185-20, D-19).

Storing recovered 5m history changes feature inputs for moved names, so it refuses by default.
`recovery_refusals` lists every reason it may not run; `--check` prints them, `--apply` requires
the list to be empty. The locks, in APR:

- infra.bar_derivation.venue_bars_intraday: the venue study's 5m verdict passed.
- infra.bar_derivation.intraday_recovery_unlocked: set by phase 186 when its rebuild completes.
- infra.bar_derivation.rebuild_state_table: JSON {"table": ..., "target_tables": [...]} set by
  186's close-out; any unit not 'completed' there means a rebuild is live or resumable.
- no ic_engine, backfill_feature_factory or rebuild process is running.

Targets come from the verify-only walk's recorded venue answers in ohlcv_request (5m, route not
SMART, outcome bars), never from the venue study's own windows. Bars are fetched through the
provider's explicit venue-routed path (route=), written with source ibkr_venue through the
pipeline's store function, and the grid stage re-derives 15m/1h with --changed-only so
bar_content_digest moves only for the affected ranges and phase 186 recomputes only those cells.

IBKR client id 49 through the campaign preflight (D-30). --apply shares the single IBKR history
fetcher lock (phase 189, CD-09) with the ibkr_history_fetcher and every other manual IBKR history
tool: it takes the lock before connecting and refuses at once (exit 1) while another holder runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
import structlog
from psycopg import sql

_logger = structlog.get_logger(__name__)

_JOB = "intraday-venue-recovery"
_CLIENT_ID = 49
_TIMEFRAME = "5m"
_STUDY_CALLER = "venue-study"

_KEY_STUDY_PASSED = "infra.bar_derivation.venue_bars_intraday"
_KEY_UNLOCKED = "infra.bar_derivation.intraday_recovery_unlocked"
_KEY_STATE_TABLE = "infra.bar_derivation.rebuild_state_table"
_KEY_CLIENT_IDS = "infra.bar_campaign.client_ids"
_APR_KEYS = (_KEY_STUDY_PASSED, _KEY_UNLOCKED, _KEY_STATE_TABLE, _KEY_CLIENT_IDS)

_RUN_MARKERS = ("ic_engine", "backfill_feature_factory", "rebuild")
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _is_true(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _incomplete_unit_refusal(conn: Any, raw_state: str) -> str | None:
    try:
        spec = json.loads(raw_state)
        table = spec["table"]
        targets = list(spec["target_tables"])
    except (ValueError, KeyError, TypeError):
        return f"{_KEY_STATE_TABLE} is malformed ({raw_state!r}); recovery refuses"
    if not _IDENTIFIER.match(str(table)):
        return f"{_KEY_STATE_TABLE} names an invalid table {table!r}; recovery refuses"
    query = sql.SQL(
        "SELECT count(*) FROM {table} WHERE target_table = ANY(%s) AND status <> 'completed'"
    ).format(table=sql.Identifier(table))
    with conn.cursor() as cur:
        cur.execute(query, (targets,))
        incomplete = int(cur.fetchone()[0])
    if incomplete:
        return (
            f"{incomplete} rebuild unit(s) in {table} are not completed for {targets}: "
            "a rebuild is live or resumable"
        )
    return None


def recovery_refusals(conn: Any, apr: Mapping[str, Any], process_args: Sequence[str]) -> list[str]:
    """Every reason storing recovered intraday history must not run now; [] means allowed."""
    reasons: list[str] = []
    if not _is_true(apr.get(_KEY_STUDY_PASSED)):
        reasons.append(
            f"the venue study's 5m verdict has not passed ({_KEY_STUDY_PASSED} is not true)"
        )
    if not _is_true(apr.get(_KEY_UNLOCKED)):
        reasons.append(f"phase 186's rebuild has not completed ({_KEY_UNLOCKED} is not true)")
    raw_state = str(apr.get(_KEY_STATE_TABLE) or "").strip()
    if not raw_state:
        reasons.append(f"{_KEY_STATE_TABLE} is empty: the rebuild has not landed")
    else:
        refusal = _incomplete_unit_refusal(conn, raw_state)
        if refusal:
            reasons.append(refusal)
    for marker in _RUN_MARKERS:
        running = [arg for arg in process_args if marker in arg]
        if running:
            reasons.append(f"a {marker} process is running: {running[0][:100]}")
    return reasons


@dataclass(frozen=True)
class RecoveryTarget:
    symbol: str
    route: str
    start: datetime
    end: datetime


def recovery_targets(conn: Any) -> list[RecoveryTarget]:
    """Per moved name, the venue with the most recorded 5m bars and its recorded span.

    The venue study's own requests are excluded: its windows are recent comparison sessions,
    not pre-move spans.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, route, window_start, window_end, n_bars FROM ohlcv_request "
            "WHERE timeframe = %s AND what_to_show = 'TRADES' AND outcome = 'bars' "
            "AND route <> 'SMART' AND caller <> %s AND window_start IS NOT NULL",
            (_TIMEFRAME, _STUDY_CALLER),
        )
        rows = cur.fetchall()
    per_route: dict[str, dict[str, list[tuple[datetime, datetime, int]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for symbol, route, start, end, n_bars in rows:
        per_route[symbol][route].append((start, end, n_bars))
    targets: list[RecoveryTarget] = []
    for symbol in sorted(per_route):
        route = min(
            per_route[symbol],
            key=lambda r: (-sum(n for _s, _e, n in per_route[symbol][r]), r),
        )
        windows = per_route[symbol][route]
        targets.append(
            RecoveryTarget(
                symbol, route, min(s for s, _e, _n in windows), max(e for _s, e, _n in windows)
            )
        )
    return targets


async def recover(
    targets: Sequence[RecoveryTarget],
    *,
    fetch: Callable[[RecoveryTarget], Awaitable[list[dict[str, Any]]]],
    store: Callable[[str, list[dict[str, Any]]], int],
    run_grid_stage: Callable[[list[str]], int],
) -> dict[str, Any]:
    """Fetch and store each target's venue bars, then re-derive the grid for the stored names."""
    stored: dict[str, int] = {}
    for target in targets:
        bars = await fetch(target)
        if bars:
            stored[target.symbol] = store(target.symbol, bars)
    names = sorted(stored)
    grid_rc = run_grid_stage(names) if names else 0
    return {"stored": stored, "grid_returncode": grid_rc}


def _process_args() -> list[str]:
    """Command lines of running python processes: a marker in a shell's argument text (a
    grep, a pytest -k) is not a run, so only interpreter processes count."""
    out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, check=True)
    return [
        ln.strip()
        for ln in out.stdout.splitlines()[1:]
        if ln.split() and ln.split()[0].rsplit("/", 1)[-1].startswith("python")
    ]


def _load_apr(conn: Any) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
            (list(_APR_KEYS),),
        )
        return {k: v for k, v in cur.fetchall()}


async def _apply(
    settings: Any, conn: Any, apr: Mapping[str, Any], targets: list[RecoveryTarget]
) -> int:
    from scripts.infrastructure.backfill._derivation_stage import run_derivation_stage
    from scripts.infrastructure.backfill._fetcher_lock import LOCK_HELD_MESSAGE, FetcherLock
    from scripts.infrastructure.backfill.infrastructure_run_historical_pipeline import store_bars
    from scripts.ops.bars._campaign import preflight
    from src.config.settings import get_active_contracts
    from src.providers import IBKRProvider

    preflight(client_id=_CLIENT_ID, apr=apr)
    instruments = {i.symbol: i for i in get_active_contracts(settings, dimension="compute_1d")}
    # Fail fast, never wait (CD-09): the fetcher or another tool holds the one stream.
    lock = FetcherLock(settings.database_url, holder=f"{_JOB}:{_CLIENT_ID}")
    if not lock.acquire():
        print(LOCK_HELD_MESSAGE)
        return 1
    provider = IBKRProvider(host=settings.ib_host, port=settings.ib_port, client_id=_CLIENT_ID)
    try:
        if not await provider.connect():
            print("cannot connect to IBKR gateway")
            return 2

        async def fetch(target: RecoveryTarget) -> list[dict[str, Any]]:
            instrument = instruments.get(target.symbol)
            if instrument is None or not await provider.qualify_instrument(instrument):
                return []
            bars = await provider.fetch_historical_bars(
                target.symbol, _TIMEFRAME, target.start, target.end, route=target.route
            )
            return [
                {
                    "timestamp": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "source": b.source,
                }
                for b in bars
            ]

        report = await recover(
            targets,
            fetch=fetch,
            store=lambda symbol, bars: store_bars(conn, bars, symbol, _TIMEFRAME),
            run_grid_stage=lambda names: run_derivation_stage(
                "grid", "--changed-only", "--symbols", ",".join(names), "--apply"
            ),
        )
        print(json.dumps(report, default=str))
        return int(report["grid_returncode"])
    finally:
        try:
            await provider.disconnect()
        finally:
            lock.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="print refusals; exit 1 if any")
    mode.add_argument("--apply", action="store_true", help="recover; requires no refusals")
    args = parser.parse_args()

    from src.config.settings import Settings

    settings = Settings()
    conn = psycopg.connect(settings.database_url, autocommit=True)
    apr = _load_apr(conn)
    refusals = recovery_refusals(conn, apr, _process_args())
    if refusals:
        print("intraday venue recovery refuses:")
        for reason in refusals:
            print(f"  - {reason}")
        return 1
    targets = recovery_targets(conn)
    print(f"allowed; {len(targets)} recovery target(s) at {datetime.now(UTC).isoformat()}")
    if args.check:
        return 0
    return asyncio.run(_apply(settings, conn, apr, targets))


if __name__ == "__main__":
    sys.exit(main())
