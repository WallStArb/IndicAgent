"""Ticker-entity map writer: the one writer of ``security_identifier`` and ``ticker_event``.

Admission design section 6, step 3b (stage 1, current names). Reads the reference answers
(``reference_raw_current``: Massive overview, events and the delisted universe; IBKR contract
details; OpenFIGI's ISIN mapping), hands them to the pure
``src.intelligence.bars.ticker_entity_map.propose_ticker_entity_map``, and inserts what it
proposes: identifiers first, then the spans that resolve to them, in one transaction.

The gate is checked before anything is written: every instrument is mapped (it has a span) or
is on the gap list, and the counts add up to the instrument count. The gap list and the
partition are written to ``data/ticker_entity_map/<YYYYMMDD>_<digest12>/`` on every run. A run
over tables already holding exactly the proposed rows is a no-op; any other existing row
refuses the run (a correction retires and replaces rows, which is not this writer's job yet).
A run without --apply does everything inside the transaction and rolls it back.

    .venv/bin/python -m services.ticker_entity_map_writer            # rolled-back rehearsal
    .venv/bin/python -m services.ticker_entity_map_writer --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.core.canonical_json import canonical_json
from src.intelligence.bars.ticker_entity_map import (
    SPAN_SCHEME,
    Answer,
    DelistedTicker,
    MapInputs,
    Proposal,
    propose_ticker_entity_map,
)
from src.observability.otel import OTelInitError, init_otel_providers

_JOB = "ticker-entity-map-writer"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_OUT_ROOT = _REPO_ROOT / "data" / "ticker_entity_map"

_INSTRUMENTS_SQL = "SELECT symbol, contract_details->>'asset_class' AS asset_class FROM instruments"
_ANSWERS_SQL = """
SELECT reference_raw_id::text AS id, request_key, served_at, body
  FROM reference_raw_current
 WHERE vendor = $1 AND endpoint = $2
   AND ($3::text[] IS NULL OR split_part(request_key, '@', 1) = ANY($3))
"""
_DELISTED_SQL = """
SELECT r.reference_raw_id::text AS id, x->>'ticker' AS ticker, x->>'delisted_utc' AS delisted_utc
  FROM reference_raw_current r, jsonb_array_elements(r.body->'results') AS x
 WHERE r.vendor = 'massive' AND r.endpoint = 'tickers_delisted'
"""
# Every page of the delisted universe must be an OK answer: a failed page would silently take
# its tickers out of the reused-ticker check.
_DELISTED_PAGES_SQL = """
SELECT count(*) FILTER (WHERE body->>'status' = 'OK' AND jsonb_typeof(body->'results') = 'array')
           AS ok,
       count(*) AS pages
  FROM reference_raw_current WHERE vendor = 'massive' AND endpoint = 'tickers_delisted'
"""
_EVENTS_STATUS_SQL = """
SELECT CASE WHEN split_part(request_key, '@', 2) = 'active' THEN 'active' ELSE 'dated' END
           AS query, body->>'status' AS status, count(*) AS n
  FROM reference_raw_current WHERE vendor = 'massive' AND endpoint = 'events' GROUP BY 1, 2
"""
_CURRENT_IDENTIFIERS_SQL = """
SELECT symbol, scheme, value, valid_from, valid_to, reference_raw_id::text AS id
  FROM security_identifier_current
"""
_CURRENT_SPANS_SQL = """
SELECT symbol, ticker, valid_from, valid_to, reference_raw_id::text AS id, evidence
  FROM ticker_event_current WHERE vendor = 'massive'
"""
_INSERT_IDENTIFIERS_SQL = """
INSERT INTO security_identifier (symbol, scheme, value, valid_from, reference_raw_id)
SELECT * FROM unnest($1::text[], $2::text[], $3::text[], $4::date[], $5::uuid[])
RETURNING security_identifier_id, symbol, scheme
"""
_INSERT_SPANS_SQL = """
INSERT INTO ticker_event (security_identifier_id, symbol, vendor, ticker, valid_from, valid_to,
                          reference_raw_id, evidence)
SELECT i, s, 'massive', t, f, v, r, e::jsonb
  FROM unnest($1::uuid[], $2::text[], $3::text[], $4::date[], $5::date[], $6::uuid[], $7::text[])
       AS u(i, s, t, f, v, r, e)
"""


def _answers(rows: list) -> dict[str, Answer]:
    return {r["request_key"]: Answer(r["id"], r["served_at"], r["body"]) for r in rows}


def _identifier_rows(proposal: Proposal) -> set[tuple]:
    return {
        (i.symbol, i.scheme, i.value, i.valid_from, None, i.reference_raw_id)
        for i in proposal.identifiers
    }


def _span_rows(proposal: Proposal) -> set[tuple]:
    return {
        (
            s.symbol,
            s.ticker,
            s.valid_from,
            s.valid_to,
            s.reference_raw_id,
            canonical_json(s.evidence),
        )
        for s in proposal.spans
    }


def write_gap_list(proposal: Proposal, partition: dict, out_root: Path) -> Path:
    """The gap list (one row per gap) and the partition, under a directory named by digest."""
    out = out_root / f"{datetime.now(UTC):%Y%m%d}_{proposal.digest[:12]}"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "gap_list.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "scope", "reason", "valid_from", "valid_to", "detail"])
        for gap in proposal.gaps:
            writer.writerow(
                [
                    gap.symbol,
                    "instrument" if gap.valid_from is None else "span",
                    gap.reason,
                    gap.valid_from.isoformat() if gap.valid_from else "",
                    gap.valid_to.isoformat() if gap.valid_to else "",
                    canonical_json(gap.detail),
                ]
            )
    (out / "partition.json").write_text(json.dumps(partition, indent=2, sort_keys=True) + "\n")
    return out


class TickerEntityMapWriter(BaseBatch):
    """Batch service: reference answers -> security_identifier and ticker_event."""

    job_name = _JOB
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, apply: bool, out_root: Path = _OUT_ROOT):
        super().__init__(db_dsn)
        self._apply = apply
        self._out_root = out_root

    async def _inputs(self, conn: asyncpg.Connection) -> MapInputs:
        instruments = {r["symbol"]: r["asset_class"] for r in await conn.fetch(_INSTRUMENTS_SQL)}
        pages = await conn.fetchrow(_DELISTED_PAGES_SQL)
        if not pages["pages"] or pages["ok"] != pages["pages"]:
            raise RuntimeError(f"delisted universe pages: {pages['ok']} OK of {pages['pages']}")
        delisted = tuple(
            DelistedTicker(r["ticker"], r["delisted_utc"], r["id"])
            for r in await conn.fetch(_DELISTED_SQL)
        )
        return MapInputs(
            instruments=instruments,
            # Overview: our symbols' answers only. Events: every answer, which the
            # FIGI-grouping needs.
            overview=_answers(
                await conn.fetch(_ANSWERS_SQL, "massive", "overview", sorted(instruments))
            ),
            events=_answers(await conn.fetch(_ANSWERS_SQL, "massive", "events", None)),
            delisted=delisted,
            contract_details=_answers(
                await conn.fetch(_ANSWERS_SQL, "ibkr", "contract_details", None)
            ),
            figi_mapping=_answers(
                await conn.fetch(_ANSWERS_SQL, "openfigi", "mapping_isin_us", None)
            ),
        )

    async def _write(self, conn: asyncpg.Connection, proposal: Proposal) -> str:
        current_ids = {tuple(r.values()) for r in await conn.fetch(_CURRENT_IDENTIFIERS_SQL)}
        current_spans = {
            (
                r["symbol"],
                r["ticker"],
                r["valid_from"],
                r["valid_to"],
                r["id"],
                canonical_json(r["evidence"]),
            )
            for r in await conn.fetch(_CURRENT_SPANS_SQL)
        }
        if current_ids or current_spans:
            if current_ids == _identifier_rows(proposal) and current_spans == _span_rows(proposal):
                return "already_applied"
            raise RuntimeError(
                f"security_identifier/ticker_event already hold {len(current_ids)}/"
                f"{len(current_spans)} unretired rows that differ from the proposal; a "
                "correction retires and replaces rows and is not this writer's job"
            )
        ids = proposal.identifiers
        returned = await conn.fetch(
            _INSERT_IDENTIFIERS_SQL,
            [i.symbol for i in ids],
            [i.scheme for i in ids],
            [i.value for i in ids],
            [i.valid_from for i in ids],
            [i.reference_raw_id for i in ids],
        )
        id_for = {(r["symbol"], r["scheme"]): r["security_identifier_id"] for r in returned}
        spans = proposal.spans
        evidence = [canonical_json(s.evidence) for s in spans]
        await conn.execute(
            _INSERT_SPANS_SQL,
            [id_for[(s.symbol, SPAN_SCHEME)] for s in spans],
            [s.symbol for s in spans],
            [s.ticker for s in spans],
            [s.valid_from for s in spans],
            [s.valid_to for s in spans],
            [s.reference_raw_id for s in spans],
            evidence,
        )
        return "inserted"

    async def execute(self, pool: asyncpg.Pool) -> None:
        async with pool.acquire() as conn:
            inputs = await self._inputs(conn)
            proposal = propose_ticker_entity_map(inputs)
            partition = proposal.partition()
            if sum(partition.values()) != len(inputs.instruments):
                raise RuntimeError(
                    f"partition {partition} does not cover {len(inputs.instruments)}"
                )
            status_rows = await conn.fetch(_EVENTS_STATUS_SQL)
            events_status = {f"{r['query']}:{r['status']}": r["n"] for r in status_rows}
            not_found = sum(r["n"] for r in status_rows if r["status"] == "NOT_FOUND")
            report = {
                "digest": proposal.digest,
                "apply": self._apply,
                "instruments": len(inputs.instruments),
                "partition": partition,
                "span_gaps": proposal.span_gaps(),
                "identifiers": len(proposal.identifiers),
                "spans": len(proposal.spans),
                "unreadable_events_chains": list(proposal.unreadable_chains),
                "events_answers_by_query_and_body_status": events_status,
                "events_not_found_rate": round(not_found / max(sum(events_status.values()), 1), 6),
            }
            out = write_gap_list(proposal, report, self._out_root)
            # The cross-security check is only as complete as the chains it could read: an
            # unreadable chain or a failed events ask (neither OK nor NOT_FOUND) could hide a
            # rival claim, so the apply refuses while any exists.
            failed = {
                k: n for k, n in events_status.items() if not k.endswith((":OK", ":NOT_FOUND"))
            }
            if self._apply and (proposal.unreadable_chains or failed):
                raise RuntimeError(
                    f"refusing --apply: unreadable chains {list(proposal.unreadable_chains)}, "
                    f"failed events answers {failed}"
                )
            try:
                async with conn.transaction():
                    outcome = await self._write(conn, proposal)
                    if not self._apply:
                        raise _Rehearsal
            except _Rehearsal:
                outcome = "rolled_back"
        self.logger.info("ticker_entity_map.run_done", outcome=outcome, out=str(out), **report)
        print(json.dumps({"outcome": outcome, "out": str(out), **report}, indent=2, default=str))


class _Rehearsal(Exception):
    """Raised inside the transaction to roll it back on a run without --apply."""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the stage 1 ticker-entity map")
    parser.add_argument("--apply", action="store_true", help="commit; default rolls back")
    args = parser.parse_args()
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(TickerEntityMapWriter(db_dsn, args.apply).run())


if __name__ == "__main__":
    main()
