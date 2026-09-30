"""D3 listing-venue validation study (phase 185 plan 13, D-17).

Fetches SMART and venue-routed bars for names selected by the pre-registered
rule (config/bars/venue_study_preregistration.json), judges them mechanically
with src/intelligence/bars/venue_study.py separately for 1d and 5m, and writes
config/bars/venue_study_verdict.json plus a report. With --apply-verdict it sets
infra.bar_derivation.venue_bars_1d / venue_bars_intraday through config_history
(changed_by 'venue_study_185'). A failed criterion leaves venue bars stored and
unused (D-17); venue volume stays NULL in the tradeable view whatever the
verdict (D-18).

Discipline:
- Refuses to run unless the pre-registration file is committed, clean, not dated
  in the future, and older than the first recorded 'venue-study' request (the
  thresholds cannot be set after seeing data).
- Holds the ibkr_history_stream lease at PRIORITY tier for the whole run and
  checkpoints after each (symbol, route) so the todo 449 chain and other
  campaigns yield at unit boundaries (D-29). IBKR client id 48 (D-30 preflight).
- 1d answers land in D1 (ohlcv_request + ohlcv_observation) through the plan 02
  sink; 5m requests land in ohlcv_request and the 5m bars are kept in a gzip CSV
  artifact under data/venue_study/ (not committed) whose sha256 goes in the
  report.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import structlog

from scripts.ops.bars._campaign import CampaignRefused, preflight
from services.ohlcv_observation_writer import ObservationSink, new_fetch_run_id
from src.config.settings import Settings, get_active_contracts
from src.core.resource_lease import LeaseTimeout, ResourceLease, Tier
from src.intelligence.bars.venue_study import (
    _VENUE_ALIASES,
    NameEvaluation,
    VenueStudyResult,
    evaluate_name,
    evaluate_study,
)
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers
from src.providers import IBKRProvider

_logger = structlog.get_logger(__name__)

_JOB = "venue-study"
_CALLER = "venue-study"
_LEASE_NAME = "ibkr_history_stream"
_CLIENT_ID = 48
_CHANGED_BY = "venue_study_185"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PREREG_PATH = _REPO_ROOT / "config" / "bars" / "venue_study_preregistration.json"
_VERDICT_PATH = _REPO_ROOT / "config" / "bars" / "venue_study_verdict.json"
_REPORT_PATH = _REPO_ROOT / "docs" / "research" / "venue-validation-study.md"
_ARTIFACT_DIR = _REPO_ROOT / "data" / "venue_study"

_APR_CLIENT_IDS = "infra.bar_campaign.client_ids"
_APR_LEASE_WAIT = "infra.ibkr_history_lease.priority_wait_minutes"
_APR_BATCH_ROWS = "infra.ohlcv_observation.copy_batch_rows"
_SWITCH_KEYS = {
    "1d": "infra.bar_derivation.venue_bars_1d",
    "5m": "infra.bar_derivation.venue_bars_intraday",
}
_TIMEFRAMES = ("1d", "5m")
# Calendar-day conversion of a session window (mathematical, not tunable).
_CALENDAR_DAYS_PER_SESSION = 365.25 / 252.0
_SMART = "SMART"


class PreregistrationRefused(RuntimeError):
    """The pre-registration guard failed; the study must not fetch (D-17)."""


# --- pure pieces -----------------------------------------------------------------


def load_preregistration(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PreregistrationRefused(f"pre-registration file missing: {path}")
    return json.loads(path.read_text())


def check_preregistration(
    committed_at: datetime, first_request_at: datetime | None, now: datetime
) -> None:
    """Refuse when the pre-registration was committed after the fact (T-185-13-01)."""
    if committed_at > now:
        raise PreregistrationRefused(
            f"pre-registration commit time {committed_at.isoformat()} is later than now "
            f"{now.isoformat()}"
        )
    if first_request_at is not None and committed_at > first_request_at:
        raise PreregistrationRefused(
            f"pre-registration committed {committed_at.isoformat()} after the first "
            f"'{_CALLER}' request {first_request_at.isoformat()}: thresholds cannot be "
            "set after seeing data"
        )


def git_commit_time(path: Path) -> datetime:
    """Commit time of the file's last commit; refuses an untracked or modified file."""
    rel = str(path.relative_to(_REPO_ROOT))
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", rel],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if status:
        raise PreregistrationRefused(f"{rel} is uncommitted or modified ({status})")
    out = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--", rel],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if not out:
        raise PreregistrationRefused(f"{rel} has no commit")
    return datetime.fromisoformat(out).astimezone(UTC)


def max_first_bar_date(prereg: Mapping[str, Any]) -> date:
    """The 'first 1d bar on or before' date, read from the eligibility text."""
    match = re.search(r"on or before (\d{4}-\d{2}-\d{2})", prereg["selection"]["eligibility"])
    if match is None:
        raise PreregistrationRefused("eligibility text names no first-bar cutoff date")
    return date.fromisoformat(match.group(1))


def normalize_venue(primary_exchange: str) -> str:
    return _VENUE_ALIASES.get(primary_exchange, primary_exchange)


def order_candidates(symbols: Sequence[str], seed: int) -> list[str]:
    """sha256(seed||symbol) ascending, symbol as the tie-break."""
    return sorted(symbols, key=lambda s: (hashlib.sha256(f"{seed}{s}".encode()).hexdigest(), s))


def select_names(
    primary_by_symbol: Mapping[str, str], prereg: Mapping[str, Any]
) -> dict[str, list[str]]:
    """The pre-registered selection: per listing venue, the first per_venue_names
    qualified names in seeded hash order (NASDAQ counts as ISLAND)."""
    selection = prereg["selection"]
    chosen: dict[str, list[str]] = {venue: [] for venue in selection["listing_venues"]}
    for symbol in order_candidates(list(primary_by_symbol), selection["seed"]):
        venue = normalize_venue(primary_by_symbol[symbol])
        if venue in chosen and len(chosen[venue]) < selection["per_venue_names"]:
            chosen[venue].append(symbol)
    return chosen


def quotas_full(primary_by_symbol: Mapping[str, str], prereg: Mapping[str, Any]) -> bool:
    chosen = select_names(primary_by_symbol, prereg)
    quota = prereg["selection"]["per_venue_names"]
    return all(len(names) >= quota for names in chosen.values())


def switch_values(results: Mapping[str, VenueStudyResult]) -> dict[str, bool]:
    return {_SWITCH_KEYS[tf]: bool(results[tf].passed) for tf in _TIMEFRAMES}


def apply_verdict(conn: Any, results: Mapping[str, VenueStudyResult], verdict_sha: str) -> None:
    """Set both switches to the verdict in one transaction: config_history row plus
    config_state update, changed_by 'venue_study_185' (T-185-13-02)."""
    values = switch_values(results)
    with conn.transaction():
        with conn.cursor() as cur:
            for tf in _TIMEFRAMES:
                key = _SWITCH_KEYS[tf]
                value = "true" if values[key] else "false"
                cur.execute(
                    "SELECT version FROM config_state WHERE config_key = %s FOR UPDATE", (key,)
                )
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError(f"{key} missing from config_state (migration 401)")
                version = int(row[0]) + 1
                reason = f"D3 venue study {tf} verdict passed={values[key]}; verdict sha256 {verdict_sha}"
                cur.execute(
                    "UPDATE config_state SET config_value = %s, version = %s, updated_at = NOW() "
                    "WHERE config_key = %s",
                    (value, version, key),
                )
                cur.execute(
                    "INSERT INTO config_history "
                    "(timestamp, config_key, version, config_value, changed_by, reason) "
                    "VALUES (NOW(), %s, %s, %s, %s, %s)",
                    (key, version, value, _CHANGED_BY, reason),
                )


def _result_json(result: VenueStudyResult) -> dict[str, Any]:
    return {
        "criterion_a_pass": result.criterion_a_pass,
        "criterion_b_pass": result.criterion_b_pass,
        "passed": result.passed,
        "n_names_by_venue": result.n_names_by_venue,
        "reasons": list(result.reasons),
        "names": [
            {
                "symbol": n.symbol,
                "listing_venue": n.listing_venue,
                "n_days": n.n_days,
                "listing_max_volume_share": n.listing_max_volume_share,
                "close_match_share_by_venue": n.close_match_share_by_venue,
                "passes_volume": n.passes_volume,
                "passes_close": n.passes_close,
            }
            for n in result.names
        ],
    }


def window_start(end: datetime, sessions: int) -> datetime:
    return end - timedelta(days=math.ceil(sessions * _CALENDAR_DAYS_PER_SESSION))


# --- report ----------------------------------------------------------------------


def render_report(
    verdict: Mapping[str, Any],
    results: Mapping[str, VenueStudyResult],
    prereg: Mapping[str, Any],
    excluded: Sequence[Mapping[str, str]],
) -> str:
    lines = [
        "# Venue validation study (D3)",
        "",
        "Author: Claude Sonnet 5.5, executing phase 185 plan 13, 2026-09-29",
        "Informed by: config/bars/venue_study_preregistration.json (committed before any fetch), "
        "docs/plans/2026-09-26-daily-data-foundation.md (D3, D-17, D-18), "
        "src/intelligence/bars/venue_study.py",
        "",
        "## Method",
        "",
        f"Names per venue: {json.dumps({k: len(v) for k, v in verdict['selected'].items()})}. "
        f"Selection is sha256(seed||symbol) ascending with seed {prereg['selection']['seed']}. "
        f"Routes: {', '.join(prereg['routes'])}. Windows: {prereg['windows']['daily_sessions']} "
        f"daily sessions and {prereg['windows']['intraday_5m_sessions']} 5m sessions. "
        f"fetch_run_id {verdict['fetch_run_id']}; client id {_CLIENT_ID}; caller '{_CALLER}'.",
        "",
        f"Pre-registration sha256 {verdict['preregistration_sha256']}.",
        "",
        "5m artifact: "
        f"{verdict['artifact']['path']} (sha256 {verdict['artifact']['sha256']}, not committed).",
        "",
        "## Verdict",
        "",
        "| Timeframe | Criterion A (listing venue has most volume) | Criterion B (only listing closes match) | Passed |",
        "| --- | --- | --- | --- |",
    ]
    for tf in _TIMEFRAMES:
        r = results[tf]
        lines.append(f"| {tf} | {r.criterion_a_pass} | {r.criterion_b_pass} | {r.passed} |")
    lines.append("")
    for tf in _TIMEFRAMES:
        r = results[tf]
        lines += [
            f"## {tf} per-name statistics",
            "",
            f"Names by venue: {json.dumps(r.n_names_by_venue)}. "
            f"Reasons: {'; '.join(r.reasons) if r.reasons else 'none'}.",
            "",
            "| Symbol | Venue | Days | Listing max-volume share | Listing close match | "
            "Max other close match | Volume | Close |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for n in r.names:
            listing = n.close_match_share_by_venue.get(n.listing_venue, 0.0)
            others = [v for k, v in n.close_match_share_by_venue.items() if k != n.listing_venue]
            lines.append(
                f"| {n.symbol} | {n.listing_venue} | {n.n_days} | {n.listing_max_volume_share:.3f} "
                f"| {listing:.3f} | {max(others, default=0.0):.3f} | {n.passes_volume} | "
                f"{n.passes_close} |"
            )
        lines.append("")
    if excluded:
        lines += ["## Excluded names", ""]
        lines += [f"- {e['symbol']} ({e['timeframe']}): {e['reason']}" for e in excluded]
        lines.append("")
    lines += [
        "## Effect",
        "",
        f"- infra.bar_derivation.venue_bars_1d is set to {results['1d'].passed} "
        "(D2 rule may use listing-venue 1d bars only when true).",
        f"- infra.bar_derivation.venue_bars_intraday is set to {results['5m'].passed} "
        "(plan 20 intraday recovery may use venue bars only when true).",
        "- Venue volume stays NULL in market_data_ohlcv_tradeable whatever the verdict (D-18).",
        "",
    ]
    return "\n".join(lines)


# --- run -------------------------------------------------------------------------


def _load_apr(conn: Any) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
            ([_APR_CLIENT_IDS, _APR_LEASE_WAIT, _APR_BATCH_ROWS],),
        )
        return {k: v for k, v in cur.fetchall()}


def _eligible_symbols(conn: Any, cutoff: date) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.symbol
            FROM instruments i
            JOIN (
                SELECT symbol, MIN(timestamp) AS first_ts
                FROM market_data_ohlcv_tradeable
                WHERE timeframe = '1d'
                GROUP BY symbol
            ) f USING (symbol)
            WHERE i.is_active = true
              AND i.compute_eligible_1d = true
              AND i.contract_details->>'asset_class' = 'equity'
              AND f.first_ts <= %s
            """,
            (datetime.combine(cutoff, datetime.min.time(), tzinfo=UTC),),
        )
        return {row[0] for row in cur.fetchall()}


def _first_study_request(conn: Any) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT MIN(requested_at) FROM ohlcv_request WHERE caller = %s", (_CALLER,))
        row = cur.fetchone()
    return row[0] if row else None


def _day_key(timeframe: str, ts: datetime) -> Any:
    return ts.date() if timeframe == "1d" else ts


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    prereg = load_preregistration(_PREREG_PATH)
    prereg_sha = hashlib.sha256(_PREREG_PATH.read_bytes()).hexdigest()
    committed_at = git_commit_time(_PREREG_PATH)
    if _VERDICT_PATH.exists() and not args.allow_rerun:
        raise PreregistrationRefused(
            f"{_VERDICT_PATH} already exists; a second run needs --allow-rerun (D-17)"
        )

    conn = psycopg.connect(settings.database_url, autocommit=True)
    apr = _load_apr(conn)
    preflight(client_id=_CLIENT_ID, apr=apr)
    check_preregistration(committed_at, _first_study_request(conn), datetime.now(UTC))

    eligible = _eligible_symbols(conn, max_first_bar_date(prereg))
    instruments = {
        i.symbol: i
        for i in get_active_contracts(settings, dimension="compute_1d")
        if i.symbol in eligible
    }
    ordered = order_candidates(list(instruments), prereg["selection"]["seed"])
    print(f"eligible candidates: {len(ordered)}")

    lease = ResourceLease(
        settings.database_url,
        _LEASE_NAME,
        tier=Tier.PRIORITY,
        holder=f"{_CALLER}:{_CLIENT_ID}",
    )
    wait_s = float(apr.get(_APR_LEASE_WAIT, 240.0)) * 60.0
    try:
        lease.acquire(wait_s)
    except LeaseTimeout:
        lease.close()
        raise

    fetch_run_id = new_fetch_run_id()
    sink_conn = psycopg.connect(settings.database_url, autocommit=True)
    sink = ObservationSink(
        sink_conn,
        caller=_CALLER,
        max_buffer_rows=int(apr.get(_APR_BATCH_ROWS, 50_000)),
    )
    provider = IBKRProvider(host=settings.ib_host, port=settings.ib_port, client_id=_CLIENT_ID)
    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = _ARTIFACT_DIR / f"{fetch_run_id}.csv.gz"
    excluded: list[dict[str, str]] = []
    evals: dict[str, list[NameEvaluation]] = {tf: [] for tf in _TIMEFRAMES}
    selected: dict[str, list[str]] = {}
    print(f"fetch_run_id {fetch_run_id}")
    try:
        if not await provider.connect():
            print("cannot connect to IBKR gateway")
            return 2

        primary: dict[str, str] = {}
        for symbol in ordered:
            if quotas_full(primary, prereg):
                break
            if await provider.qualify_instrument(instruments[symbol]):
                contract = provider._qualified_contracts.get(symbol)
                venue = getattr(contract, "primaryExchange", "") or ""
                primary[symbol] = venue
            lease.checkpoint()
        selected = select_names(primary, prereg)
        print(f"selected: {json.dumps({k: len(v) for k, v in selected.items()})}")

        end = datetime.now(UTC)
        routes = list(prereg["routes"])
        with gzip.open(artifact_path, "wt", newline="") as gz:
            writer = csv.writer(gz)
            writer.writerow(
                ["symbol", "route", "timestamp", "open", "high", "low", "close", "volume"]
            )
            for venue, names in selected.items():
                for symbol in names:
                    for tf in _TIMEFRAMES:
                        sessions = prereg["windows"][
                            "daily_sessions" if tf == "1d" else "intraday_5m_sessions"
                        ]
                        start = window_start(end, sessions)
                        kwargs: dict[str, Any] = {
                            "on_request": sink.on_request,
                            "fetch_run_id": fetch_run_id,
                        }
                        if tf == "1d":
                            kwargs["on_observation"] = sink.on_observation
                        series: dict[str, dict[Any, tuple[float, float]]] = {}
                        smart_close: dict[Any, float] = {}
                        failed: str | None = None
                        for route in routes:
                            try:
                                bars = await provider.fetch_historical_bars(
                                    symbol, tf, start, end, route=route, **kwargs
                                )
                            except Exception as error:
                                bars = []
                                if route == _SMART:
                                    failed = f"SMART fetch failed: {type(error).__name__}: {error}"
                            if tf == "5m":
                                for b in bars:
                                    writer.writerow(
                                        [
                                            symbol,
                                            route,
                                            b.timestamp.isoformat(),
                                            b.open,
                                            b.high,
                                            b.low,
                                            b.close,
                                            b.volume,
                                        ]
                                    )
                            if route == _SMART:
                                smart_close = {_day_key(tf, b.timestamp): b.close for b in bars}
                            else:
                                series[route] = {
                                    _day_key(tf, b.timestamp): (b.close, b.volume) for b in bars
                                }
                            sink.flush()
                            if lease.checkpoint():
                                print(f"  yielded lease at {symbol}/{tf}/{route}")
                        if failed is None and not smart_close:
                            failed = "SMART returned no bars"
                        if failed:
                            excluded.append({"symbol": symbol, "timeframe": tf, "reason": failed})
                            print(f"  {symbol}/{tf}: excluded ({failed})")
                            continue
                        evals[tf].append(evaluate_name(symbol, venue, smart_close, series, prereg))
                        print(f"  {symbol}/{tf}: done")
        sink.flush()
    finally:
        try:
            sink.flush()
        finally:
            await provider.disconnect()
            lease.release()
            sink_conn.close()

    results = {tf: evaluate_study(evals[tf], prereg, tf) for tf in _TIMEFRAMES}
    artifact_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    verdict: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "preregistration_sha256": prereg_sha,
        "fetch_run_id": fetch_run_id,
        "selected": selected,
        "excluded": excluded,
        "artifact": {"path": str(artifact_path.relative_to(_REPO_ROOT)), "sha256": artifact_sha},
        "results": {tf: _result_json(results[tf]) for tf in _TIMEFRAMES},
    }
    _VERDICT_PATH.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    _REPORT_PATH.write_text(render_report(verdict, results, prereg, excluded))
    verdict_sha = hashlib.sha256(_VERDICT_PATH.read_bytes()).hexdigest()
    print(json.dumps({tf: results[tf].passed for tf in _TIMEFRAMES}))
    if args.apply_verdict:
        apply_verdict(conn, results, verdict_sha)
        print(f"applied verdict (sha256 {verdict_sha})")
    conn.close()
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--apply-verdict",
        action="store_true",
        help="set the two venue_bars APR switches from the verdict",
    )
    parser.add_argument(
        "--allow-rerun", action="store_true", help="run although a verdict file exists"
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        init_otel_providers(service_name=f"indicagent-{_JOB}")
    except OTelInitError as error:
        _logger.warning("venue_study.otel_init_failed", error=str(error))
    status = "success"
    try:
        exit_code = asyncio.run(_run(args))
    except (PreregistrationRefused, CampaignRefused, LeaseTimeout) as error:
        status = "refused"
        print(f"REFUSED: {error}")
        exit_code = 3
    except Exception as error:
        status = "failure"
        _logger.error("venue_study.failed", error=str(error))
        exit_code = 1
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
