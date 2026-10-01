"""EconomicSeriesWriter: FRED and NY Fed series -> economic_series_observation, append-only.

Oneshot batch (todo 480). Fetches each entry of APR `infra.economic_series.sources` in full (a FRED
series, or a NY Fed rate type that expands to one series per published field) and appends what
is new or changed; it never updates or deletes (the table has a trigger).

Inside the run, one direction: sources fetch (I/O, concurrent up to
`infra.economic_series.fetch_concurrency`, one shared HTTP client) -> `plan_rows` decides what to
append (pure) -> this writer persists, one series at a time in arrival order (the table's only
writer, never concurrent). Sources implement `EconomicSource` and are looked up by name, so a new
source is a module and a registry line, not a branch here. A series
with no coverage row is a first fetch: FRED serves today's values, so each stored row's
available_at is the end of the business day `infra.economic_series.assumed_lag_business_days` after the
observation date (basis assumed_lag), an estimate of publication; exchange holidays are not modeled,
so the estimate can fall a day early. Every later run stamps what it finds new or revised with the fetch time
(basis fetch). A stored day FRED no longer serves (the ICE BofA spreads are limited to a trailing
window) is kept and counted.

Usage:
    python services/economic_series_writer.py                      # every series in APR
    python services/economic_series_writer.py --series DGS10 SOFR   # APR entry ids
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta

import asyncpg
import httpx

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers
from src.providers.economic_source import EconomicSource, Series, SourceError
from src.providers.fred import FredSource
from src.providers.nyfed import NyFedSource

_JOB = "economic-series-writer"
# Per-run outcome counts, labeled {outcome} only: never per series (the detail stays in the log).
_OUTCOME_TOTAL = counter(
    "economic_series_outcome_total",
    "economic_series_writer per-run outcome counts: observations inserted, revisions appended, "
    "stored days FRED no longer serves, failed series. Never labeled by series.",
)
BASIS_ASSUMED_LAG = "assumed_lag"
BASIS_FETCH = "fetch"
_REVISIONS = frozenset({"none", "model_revised", "revised"})
_APR_KEY = "infra.economic_series.sources"


@dataclasses.dataclass(frozen=True)
class NewRow:
    observation_date: date
    value: float
    available_at: datetime
    basis: str
    is_revision: bool


@dataclasses.dataclass(frozen=True)
class Plan:
    rows: list[NewRow]
    n_vanished: int  # stored days inside the fetched span that FRED did not serve


class _SeriesFailure(Exception):
    """One series could not be written (a database error is handled the same way); the run
    continues and fails at the end."""


def parse_series_config(raw: str, sources: Mapping[str, EconomicSource]) -> list[dict]:
    """The APR source list, validated against the registered sources, `source` defaulted to fred.
    Raises ValueError on a malformed entry: a typo must stop the run, not silently drop a series."""
    entries = json.loads(raw)
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{_APR_KEY} must be a non-empty JSON list")
    seen: set[tuple[str, str]] = set()
    out = []
    for entry in entries:
        entry = {"source": "fred", **entry}
        series_id = entry.get("series_id")
        if entry["source"] not in sources:
            raise ValueError(f"{entry}: source must be one of {sorted(sources)}")
        if not series_id or (entry["source"], series_id) in seen:
            raise ValueError(f"missing or duplicate series_id in {entry}")
        seen.add((entry["source"], series_id))
        sources[entry["source"]].validate(series_id)
        if entry.get("revision") not in _REVISIONS:
            raise ValueError(f"{series_id}: revision must be one of {sorted(_REVISIONS)}")
        if not entry.get("consumer"):
            raise ValueError(f"{series_id}: every series names a consumer")
        out.append(entry)
    return out


def available_after(day: date, lag_business_days: int) -> datetime:
    """The end (next 00:00 UTC) of the business day `lag_business_days` after `day`: a daily
    series is published during that day, so no read before its end can have seen the value.
    Weekends are skipped; exchange holidays are not modeled."""
    published = day
    remaining = lag_business_days
    while remaining > 0:
        published += timedelta(days=1)
        if published.weekday() < 5:
            remaining -= 1
    end = published + timedelta(days=1)
    return datetime(end.year, end.month, end.day, tzinfo=UTC)


def plan_rows(
    fetched: list[tuple[date, float]],
    stored: dict[date, float],
    first_fetch: bool,
    now: datetime,
    lag_days: int,
) -> Plan:
    """Rows to append for one series: days not yet stored, and stored days whose value changed.

    first_fetch: no coverage row exists, so every row's available_at is an estimate (the end of the
    publication business day, never later than now); afterwards a new or revised day is stamped with now.
    """
    rows: list[NewRow] = []
    for day, value in fetched:
        if day not in stored:
            if first_fetch:
                at = min(available_after(day, lag_days), now)
                rows.append(NewRow(day, value, at, BASIS_ASSUMED_LAG, False))
            else:
                rows.append(NewRow(day, value, now, BASIS_FETCH, False))
        elif stored[day] != value:
            rows.append(NewRow(day, value, now, BASIS_FETCH, True))
    served = {day for day, _ in fetched}
    lo, hi = fetched[0][0], fetched[-1][0]
    vanished = sum(1 for day in stored if lo <= day <= hi and day not in served)
    return Plan(rows, vanished)


class EconomicSeriesWriter(BaseBatch):
    """Batch service: registered sources -> economic_series_observation and its coverage."""

    job_name = _JOB
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, settings: Settings, only: list[str]) -> None:
        super().__init__(db_dsn)
        self._settings = settings
        self._only = only

    def _sources(self, max_attempts: int) -> dict[str, EconomicSource]:
        """The source registry: adding a source is one line here and its module."""
        registered: list[EconomicSource] = [
            FredSource(self._settings.fred_api_key, max_attempts),
            NyFedSource(max_attempts),
        ]
        return {source.name: source for source in registered}

    async def execute(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(conn, ["infra.economic_series.%"])
        sources = self._sources(int(_cfg(apr, "infra.economic_series.http_max_attempts", 3)))
        entries = parse_series_config(_cfg(apr, _APR_KEY, "[]"), sources)
        if self._only:
            unknown = set(self._only) - {e["series_id"] for e in entries}
            if unknown:
                raise RuntimeError(f"economic_series_writer: not in {_APR_KEY}: {unknown}")
            entries = [e for e in entries if e["series_id"] in self._only]
        lag_days = int(_cfg(apr, "infra.economic_series.assumed_lag_business_days", 1))
        timeout_sec = float(_cfg(apr, "infra.economic_series.http_timeout_sec", 60))
        gate = asyncio.Semaphore(int(_cfg(apr, "infra.economic_series.fetch_concurrency", 4)))

        totals = {"inserted": 0, "revised": 0, "vanished": 0}
        failed: list[str] = []
        n_series = 0
        async with httpx.AsyncClient(timeout=timeout_sec) as client:

            async def fetch(entry: dict) -> tuple[dict, dict[str, Series], str | None]:
                async with gate:
                    try:
                        source = sources[entry["source"]]
                        return entry, await source.fetch(entry["series_id"], client), None
                    except SourceError as error:
                        return entry, {}, str(error)
                    except Exception as error:
                        # A payload shape no parser expected (a null where a value belongs) fails
                        # this entry, loudly, without aborting the entries still in flight.
                        return entry, {}, f"unexpected {type(error).__name__}: {error}"[:200]

            # Fetches overlap; writes do not: each completed fetch is written before the next is
            # taken, so the table has one writer and one transaction at a time.
            for completed in asyncio.as_completed([fetch(e) for e in entries]):
                entry, fetched, error = await completed
                if error is not None:
                    failed.append(f"{entry['source']}/{entry['series_id']}: {error}")
                    continue
                for series_id, series in fetched.items():
                    try:
                        n_new, n_revised, n_vanished = await self._write_series(
                            pool, entry["source"], series_id, series, lag_days
                        )
                    except (_SeriesFailure, asyncpg.PostgresError) as write_error:
                        failed.append(f"{entry['source']}/{series_id}: {write_error}")
                        continue
                    totals["inserted"] += n_new
                    totals["revised"] += n_revised
                    totals["vanished"] += n_vanished
                    n_series += 1
                    self.logger.info(
                        "economic_series_writer.series",
                        source=entry["source"],
                        series_id=series_id,
                        inserted=n_new,
                        revised=n_revised,
                        vanished=n_vanished,
                        revision=entry["revision"],
                    )
        self.logger.info(
            "economic_series_writer.done", series=n_series, **totals, failed=len(failed)
        )
        for outcome, n in {**totals, "failed": len(failed)}.items():
            _OUTCOME_TOTAL.add(n, {"outcome": outcome})
        if failed:
            raise RuntimeError(f"economic_series_writer: {len(failed)} failures: {failed}")

    async def _write_series(
        self,
        pool: asyncpg.Pool,
        source: str,
        series_id: str,
        series: Series,
        lag_days: int,
    ) -> tuple[int, int, int]:
        """Append one series' new and revised days in one transaction; returns (new, revised,
        vanished)."""
        fetched = series.rows
        now = datetime.now(UTC)
        async with pool.acquire() as conn, conn.transaction():
            stored = {
                r["observation_date"]: r["value"]
                for r in await conn.fetch(
                    "SELECT observation_date, value FROM economic_series_observation_current "
                    "WHERE series_id = $1",
                    series_id,
                )
            }
            coverage = await conn.fetchrow(
                "SELECT unit FROM economic_series_observation_coverage WHERE series_id = $1",
                series_id,
            )
            if coverage is not None and coverage["unit"] != series.unit:
                raise _SeriesFailure(
                    f"{series_id}: unit changed from {coverage['unit']} to {series.unit}"
                )
            plan = plan_rows(fetched, stored, coverage is None, now, lag_days)
            if plan.n_vanished:
                self.logger.warning(
                    "economic_series_writer.vanished_days", series_id=series_id, n=plan.n_vanished
                )
            await conn.executemany(
                "INSERT INTO economic_series_observation "
                "(source, series_id, observation_date, value, available_at, availability_basis, "
                "compute_version) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                [
                    (
                        source,
                        series_id,
                        r.observation_date,
                        r.value,
                        r.available_at,
                        r.basis,
                        self.compute_version,
                    )
                    for r in plan.rows
                ],
            )
            await conn.execute(
                "INSERT INTO economic_series_observation_coverage "
                "(series_id, unit, covered_from, covered_to, checked_at) "
                "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (series_id) DO UPDATE SET "
                "covered_from = LEAST(economic_series_observation_coverage.covered_from, "
                "EXCLUDED.covered_from), "
                "covered_to = GREATEST(economic_series_observation_coverage.covered_to, "
                "EXCLUDED.covered_to), "
                "checked_at = EXCLUDED.checked_at",
                series_id,
                series.unit,
                fetched[0][0],
                fetched[-1][0],
                now,
            )
        n_revised = sum(1 for r in plan.rows if r.is_revision)
        return len(plan.rows) - n_revised, n_revised, plan.n_vanished


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch FRED and NY Fed economic series")
    parser.add_argument("--series", nargs="*", default=[], help="limit to these series ids")
    args = parser.parse_args()
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(EconomicSeriesWriter(db_dsn, settings, args.series).run())


if __name__ == "__main__":
    main()
