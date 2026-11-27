#!/usr/bin/env python3
"""Split Feed Auditor: oneshot canary for splits after the Massive seam (todo 649).

Canonical takes Massive to the 2026-11-16 seam and Alpaca after it. Alpaca serves history already
split-adjusted, so a split on an active name steps canonical at the seam and the only alarm is the
nightly restatement flag, which a human reads before writing the `corporate_action` row (SNDK,
VIXM). This job reads the Alpaca corporate-actions feed once (forward and reverse splits, ex-dates
in the last `infra.split_feed_auditor.lookback_days`), ignores names that are not active, and
judges each remaining split:

- recorded: a `corporate_action_current` row with the same symbol and factor, recorded no earlier
  than `record_lookback_days` before the ex-date. Nothing to do.
- candidate: no row yet but the nightly flagged the name (an `ohlcv_restatement_flag` whose price
  ratio matches the factor in either direction) and the ex-date is within `row_grace_days`. A
  loud warning and a row in the candidate file; the job still exits 0.
- unseen: no row and no matching flag, so the nightly never saw the restatement. Fails the job.
- overdue: no row and the ex-date is older than `row_grace_days`. Fails the job.

The feed being down or malformed fails the job; it never reads as "no splits". The job never
writes `corporate_action`: it writes `logs/split_candidates/split_candidates_<date>.csv` in the
`calendar_market` row format (`config/corporate_actions/split_rescale_rows_*.csv`), and the
Yahoo witness, the review and the apply stay manual. Factor is `new_rate / old_rate` (a 1:8 forward
split is 8, a 2:1 reverse split is 0.5).

Usage:
    python services/split_feed_auditor.py
"""

from __future__ import annotations

import csv
import math
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg
import structlog
from psycopg.rows import dict_row

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.batch_support.db import load_config_service_sync
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics, point_gauge
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/split_feed_auditor.log")

_logger = structlog.get_logger(__name__)

_JOB = "split-feed-auditor"
SPLIT_FEED_SPLITS = point_gauge(
    "split_feed_auditor_splits",
    "Feed splits by class from a successful judge of split_feed_auditor: inactive_ignored, recorded, "
    "candidates, unseen, overdue (unseen and overdue fail the run). A run that fails before judging "
    "sets nothing; liveness and failures are job_completed_total{job_name=split-feed-auditor}",
)
_FEED_URL = "https://data.alpaca.markets/v1/corporate-actions"
_FEED_TYPES = "forward_split,reverse_split"
_FEED_KEYS = {"forward_splits": "split", "reverse_splits": "reverse_split"}
_FEED_PAGE_LIMIT = 1000
_FEED_TIMEOUT_S = 30.0
_CANDIDATE_DIR = project_root / "logs" / "split_candidates"
_CANDIDATE_COLUMNS = (
    "symbol",
    "effective_date",
    "factor",
    "unadjusted_routes",
    "calendar_adjusted_step",
    "reason",
    "evidence",
)

_KEY_LOOKBACK = "infra.split_feed_auditor.lookback_days"
_KEY_RECORD_LOOKBACK = "infra.split_feed_auditor.record_lookback_days"
_KEY_GRACE = "infra.split_feed_auditor.row_grace_days"
_KEY_EARLIEST = "infra.split_feed_auditor.earliest_ex_date"
_KEY_REL_TOL = "infra.split_feed_auditor.factor_rel_tol"

_ACTIVE_SQL = "SELECT symbol FROM instruments WHERE is_active AND symbol = ANY(%s)"
_RECORDED_SQL = """
    SELECT symbol, action_type, factor, recorded_at
    FROM corporate_action_current
    WHERE symbol = ANY(%s) AND action_type IN ('split', 'reverse_split')
"""
_FLAGGED_SQL = """
    SELECT symbol, ratio, flagged_at
    FROM ohlcv_restatement_flag
    WHERE symbol = ANY(%s) AND ratio IS NOT NULL AND flagged_at >= %s
"""
# The last session canonical still carries on the old scale: the last stored Massive 1d session
# before the ex-date (the archive side of the seam is never restated).
_LAST_OLD_SCALE_SQL = """
    SELECT max((timestamp AT TIME ZONE 'America/New_York')::date) AS session
    FROM ohlcv_raw
    WHERE symbol = %s AND timeframe = '1d' AND vendor = 'massive'
      AND (timestamp AT TIME ZONE 'America/New_York')::date < %s
"""


class FeedError(RuntimeError):
    """The corporate-actions feed answered with an error or a payload that is not understood."""


@dataclass(frozen=True)
class FeedSplit:
    symbol: str
    ex_date: date
    action_type: str  # split | reverse_split, the corporate_action vocabulary
    old_rate: float
    new_rate: float

    @property
    def factor(self) -> float:
        return self.new_rate / self.old_rate


@dataclass(frozen=True)
class Recorded:
    symbol: str
    action_type: str
    factor: float
    recorded_at: datetime


@dataclass(frozen=True)
class Flagged:
    symbol: str
    ratio: float
    flagged_at: datetime


@dataclass(frozen=True)
class Judgement:
    """`recorded` and `inactive` need no action; `candidates` warn; `unseen` and `overdue` fail."""

    recorded: list[FeedSplit]
    inactive: list[FeedSplit]
    candidates: list[FeedSplit]
    unseen: list[FeedSplit]
    overdue: list[FeedSplit]

    @property
    def failed(self) -> bool:
        return bool(self.unseen or self.overdue)

    def counts(self) -> dict[str, int]:
        """Splits per class, the one source of the judged log line and the class gauge (todo 683)."""
        return {
            "inactive_ignored": len(self.inactive),
            "recorded": len(self.recorded),
            "candidates": len(self.candidates),
            "unseen": len(self.unseen),
            "overdue": len(self.overdue),
        }


def _rate(value: Any, where: str) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError) as error:
        raise FeedError(f"{where}: rate {value!r} is not a number") from error
    if not math.isfinite(rate) or rate <= 0:
        raise FeedError(f"{where}: rate {value!r} is not a positive finite number")
    return rate


def parse_feed_splits(payload: Any) -> list[FeedSplit]:
    """Splits out of one or more feed pages, a duplicate (symbol, ex-date, rates) dropped. A page
    without a `corporate_actions` object or a malformed entry raises: a feed that answers but is
    not understood must not read as "no splits"."""
    pages = payload if isinstance(payload, list) else [payload]
    found: set[FeedSplit] = set()
    for page in pages:
        actions = page.get("corporate_actions") if isinstance(page, dict) else None
        if not isinstance(actions, dict):
            raise FeedError("feed page has no corporate_actions object")
        for key, action_type in _FEED_KEYS.items():
            for index, entry in enumerate(actions.get(key) or []):
                where = f"{key}[{index}]"
                try:
                    symbol = str(entry["symbol"]).strip().upper()
                    ex_date = date.fromisoformat(entry["ex_date"])
                except (KeyError, TypeError, ValueError) as error:
                    raise FeedError(f"{where}: symbol or ex_date missing or malformed") from error
                if not symbol:
                    raise FeedError(f"{where}: empty symbol")
                found.add(
                    FeedSplit(
                        symbol,
                        ex_date,
                        action_type,
                        _rate(entry.get("old_rate"), where),
                        _rate(entry.get("new_rate"), where),
                    )
                )
    return sorted(found, key=lambda s: (s.ex_date, s.symbol))


def fetch_feed(
    settings: Settings, start: date, end: date, client: httpx.Client | None = None
) -> list[FeedSplit]:
    """One paginated feed read for ex-dates start..end. A transport error, a non-200 answer or a
    malformed payload raises FeedError."""
    if not (settings.alpaca_key_id and settings.alpaca_secret_key):
        raise FeedError("ALPACA_KEY_ID or ALPACA_SECRET_KEY is empty")
    headers = {
        "APCA-API-KEY-ID": settings.alpaca_key_id,
        "APCA-API-SECRET-KEY": settings.alpaca_secret_key,
    }
    owned = client is None
    http = client or httpx.Client(timeout=_FEED_TIMEOUT_S)
    pages: list[Any] = []
    token: str | None = None
    try:
        while True:
            params: dict[str, Any] = {
                "types": _FEED_TYPES,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": _FEED_PAGE_LIMIT,
            }
            if token:
                params["page_token"] = token
            try:
                response = http.get(_FEED_URL, params=params, headers=headers)
            except httpx.HTTPError as error:
                raise FeedError(f"feed request failed: {error}") from error
            if response.status_code != 200:
                raise FeedError(f"feed answered {response.status_code}: {response.text[:200]}")
            try:
                page = response.json()
            except ValueError as error:
                raise FeedError("feed answered 200 with a body that is not JSON") from error
            pages.append(page)
            token = page.get("next_page_token") if isinstance(page, dict) else None
            if not token:
                return parse_feed_splits(pages)
    finally:
        if owned:
            http.close()


def judge_splits(
    splits: list[FeedSplit],
    active: set[str],
    recorded: list[Recorded],
    flagged: list[Flagged],
    today: date,
    *,
    record_lookback_days: int,
    row_grace_days: int,
    rel_tol: float,
) -> Judgement:
    """Classify each feed split. Pure: the caller loads `active`, `recorded` and `flagged`."""
    recorded_ok: list[FeedSplit] = []
    inactive: list[FeedSplit] = []
    candidates: list[FeedSplit] = []
    unseen: list[FeedSplit] = []
    overdue: list[FeedSplit] = []
    for split in splits:
        if split.symbol not in active:
            inactive.append(split)
            continue
        record_floor = _midnight(split.ex_date - timedelta(days=record_lookback_days))
        if any(
            r.symbol == split.symbol
            and r.action_type == split.action_type
            and math.isclose(r.factor, split.factor, rel_tol=rel_tol)
            and r.recorded_at >= record_floor
            for r in recorded
        ):
            recorded_ok.append(split)
        elif (today - split.ex_date).days > row_grace_days:
            overdue.append(split)
        elif _flag_matches(split, flagged, rel_tol):
            candidates.append(split)
        else:
            unseen.append(split)
    return Judgement(recorded_ok, inactive, candidates, unseen, overdue)


def _flag_matches(split: FeedSplit, flagged: list[Flagged], rel_tol: float) -> bool:
    """A restatement flag on the name from the day before the ex-date whose price ratio is the
    split factor or its inverse (a 1:8 split restates prices by 0.125, a 2:1 reverse by 2.0)."""
    floor = _midnight(split.ex_date - timedelta(days=1))
    return any(
        f.symbol == split.symbol
        and f.flagged_at >= floor
        and (
            math.isclose(f.ratio, split.factor, rel_tol=rel_tol)
            or math.isclose(f.ratio * split.factor, 1, rel_tol=rel_tol)
        )
        for f in flagged
    )


def feed_window(today: date, lookback_days: int, earliest: date) -> tuple[date, date]:
    """Ex-dates to judge: no earlier than the seam (before it the archive already carries the
    split and no row or flag is expected) and no later than yesterday (the nightly has not run on
    today's session when this job fires)."""
    return max(today - timedelta(days=lookback_days), earliest), today - timedelta(days=1)


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def candidate_rows(
    splits: list[FeedSplit], last_old_scale: dict[str, date | None]
) -> list[dict[str, str]]:
    """Rows in the calendar_market format. The effective date is the last stored Massive 1d session
    before the ex-date (blank, with the route blank, when the name has none); the Yahoo step and
    witness are left to the reviewer."""
    rows = []
    for split in splits:
        session = last_old_scale.get(split.symbol)
        rows.append(
            {
                "symbol": split.symbol,
                "effective_date": session.isoformat() if session else "",
                "factor": f"{split.factor:.12g}",
                "unadjusted_routes": "massive/sip_flat" if session else "",
                "calendar_adjusted_step": "",
                "reason": (
                    f"{split.old_rate:g}-for-{split.new_rate:g} {split.action_type} per the Alpaca "
                    f"corporate-actions feed, ex-date {split.ex_date.isoformat()}"
                ),
                "evidence": (
                    "feed only, Yahoo witness and level check pending; "
                    + (
                        "effective date is the last stored massive/sip_flat 1d session before the "
                        "ex-date"
                        if session
                        else "no stored massive 1d session: route unknown"
                    )
                ),
            }
        )
    return rows


def write_candidates(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CANDIDATE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _load_context(
    cur: psycopg.Cursor, symbols: list[str], flag_since: datetime
) -> tuple[set[str], list[Recorded], list[Flagged]]:
    cur.execute(_ACTIVE_SQL, (symbols,))
    active = {row["symbol"] for row in cur.fetchall()}
    cur.execute(_RECORDED_SQL, (symbols,))
    recorded = [
        Recorded(r["symbol"], r["action_type"], r["factor"], r["recorded_at"])
        for r in cur.fetchall()
    ]
    cur.execute(_FLAGGED_SQL, (symbols, flag_since))
    flagged = [Flagged(r["symbol"], r["ratio"], r["flagged_at"]) for r in cur.fetchall()]
    return active, recorded, flagged


def _last_old_scale(cur: psycopg.Cursor, splits: list[FeedSplit]) -> dict[str, date | None]:
    out: dict[str, date | None] = {}
    for split in splits:
        cur.execute(_LAST_OLD_SCALE_SQL, (split.symbol, split.ex_date))
        out[split.symbol] = cur.fetchone()["session"]
    return out


def _describe(splits: list[FeedSplit]) -> list[str]:
    return [f"{s.symbol} {s.ex_date.isoformat()} factor {s.factor:g}" for s in splits]


def report_counts(judgement: Judgement) -> None:
    """The judged log line and one class gauge point per class, from the same counts."""
    counts = judgement.counts()
    _logger.info("split_feed_auditor.judged", **{f"n_{k}": v for k, v in counts.items()})
    for split_class, n in counts.items():
        SPLIT_FEED_SPLITS.set(n, {"class": split_class})


def main() -> None:
    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("split_feed_auditor.otel_init_failed", error=str(error))

    t0 = time.monotonic()
    status = "success"
    exit_code = 0
    conn = None
    try:
        settings = Settings()
        conn = psycopg.connect(
            settings.database_url, options="-c idle_in_transaction_session_timeout=0"
        )
        conn.autocommit = True
        cfg = load_config_service_sync(conn)
        lookback = int(cfg.get_sync(_KEY_LOOKBACK, 14))
        record_lookback = int(cfg.get_sync(_KEY_RECORD_LOOKBACK, 7))
        grace = int(cfg.get_sync(_KEY_GRACE, 2))
        rel_tol = float(cfg.get_sync(_KEY_REL_TOL, 0.02))
        earliest = date.fromisoformat(str(cfg.get_sync(_KEY_EARLIEST, "2026-11-16")))

        today = datetime.now(UTC).date()
        start, end = feed_window(today, lookback, earliest)
        splits = fetch_feed(settings, start, end)
        _logger.info("split_feed_auditor.feed_read", n_splits=len(splits), start=str(start))

        symbols = sorted({s.symbol for s in splits})
        with conn.cursor(row_factory=dict_row) as cur:
            active, recorded, flagged = (
                _load_context(cur, symbols, _midnight(start - timedelta(days=1)))
                if symbols
                else (set(), [], [])
            )
            judgement = judge_splits(
                splits,
                active,
                recorded,
                flagged,
                today,
                record_lookback_days=record_lookback,
                row_grace_days=grace,
                rel_tol=rel_tol,
            )
            proposed = judgement.candidates + judgement.unseen + judgement.overdue
            last_old = _last_old_scale(cur, proposed) if proposed else {}

        report_counts(judgement)
        if proposed:
            path = _CANDIDATE_DIR / f"split_candidates_{today.isoformat()}.csv"
            write_candidates(path, candidate_rows(proposed, last_old))
            _logger.warning(
                "split_feed_auditor.candidates_written",
                path=str(path),
                candidates=_describe(judgement.candidates),
                note="active-name splits without a corporate_action row; review the Yahoo "
                "witness, then apply by hand. This job never writes corporate_action.",
            )
            status = "candidates"
        if judgement.failed:
            _logger.error(
                "split_feed_auditor.gap_found",
                unseen=_describe(judgement.unseen),
                overdue=_describe(judgement.overdue),
                note="unseen: the feed lists a split the nightly restatement flag never matched; "
                "overdue: no corporate_action row past the grace days.",
            )
            status = "gap_found"
            exit_code = 1
        _logger.info(
            "split_feed_auditor.complete", elapsed_s=round(time.monotonic() - t0, 2), status=status
        )
    except Exception as error:
        _logger.error("split_feed_auditor.run_failed", error=str(error), exc_info=True)
        status = "failure"
        exit_code = 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
