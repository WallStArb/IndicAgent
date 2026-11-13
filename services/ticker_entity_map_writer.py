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

``--amend SPANS_CSV --amend-sha256 HEX --amend-candidates CSV --gap-list CSV`` is the additive
amendment of design section 8c (identity witness, lead ruling 2026-11-13): each ``placed`` span
of the witness run becomes one ``ticker_event`` row under the name's existing composite FIGI
identifier, with the witness evidence; a name without one gets its FIGI identifiers minted from
its captured OpenFIGI answer only when exactly one entry matches its ticker on exchange US (any
other name stays a gap, listed). Any overlap with a live span (of the name, or of the ticker
under another name) refuses the run. The gap list is rewritten without the placed spans into a
new dated map directory. One transaction; rehearsal by default, --apply to write.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

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


_AMEND_OVERVIEW_SQL = """
SELECT split_part(request_key, '@', 1) AS symbol, reference_raw_id::text AS id
  FROM reference_raw_current
 WHERE vendor = 'massive' AND endpoint = 'overview' AND request_key LIKE '%@active'
"""
_AMEND_FIGI_SQL = """
SELECT request_key AS isin, reference_raw_id::text AS id, body
  FROM reference_raw_current WHERE vendor = 'openfigi' AND endpoint = 'mapping_isin_us'
"""
_AMEND_IDS_SQL = """
SELECT security_identifier_id, symbol, scheme, value FROM security_identifier_current
"""
_AMEND_SPANS_SQL = """
SELECT symbol, ticker, valid_from, valid_to FROM ticker_event_current WHERE vendor = 'massive'
"""
WITNESS_CODE, WITNESS_RULE = "07bfd963b", "8d10bd030"


@dataclass(frozen=True)
class PlacedSpan:
    symbol: str
    reason: str
    start: date
    end: date
    ticker: str
    evidence: dict[str, Any]


@dataclass
class Amendment:
    """What an --amend run writes: identifiers to mint, spans to insert, gap rows removed, and the
    placed names left as gaps (no unambiguous FIGI)."""

    mint: list[tuple[str, str, str, str]] = field(
        default_factory=list
    )  # symbol, scheme, value, ref
    spans: list[PlacedSpan] = field(default_factory=list)
    removed_gaps: list[dict[str, str]] = field(default_factory=list)
    kept_as_gap: list[tuple[str, str]] = field(default_factory=list)  # symbol, why


def read_placed(spans_csv: bytes, candidates_csv: bytes, sha256: str) -> list[PlacedSpan]:
    """The witness run's placed spans with their placing candidate's evidence; refuses unless the
    spans file hashes to ``sha256``."""
    digest = hashlib.sha256(spans_csv).hexdigest()
    if digest != sha256:
        raise ValueError(f"witness spans file sha256 {digest} is not the pinned {sha256}")
    evidence: dict[tuple[str, str, str], dict[str, str]] = {
        (c["symbol"], c["span_start"], c["candidate"]): c
        for c in csv.DictReader(io.StringIO(candidates_csv.decode()))
    }
    out = []
    for r in csv.DictReader(io.StringIO(spans_csv.decode())):
        if r["decision"] != "placed":
            continue
        c = evidence[(r["symbol"], r["span_start"], r["placing_ticker"])]
        out.append(
            PlacedSpan(
                r["symbol"],
                r["reason"],
                date.fromisoformat(r["span_start"]),
                date.fromisoformat(r["span_end"]),
                r["placing_ticker"],
                {
                    "amendment": "design 8c identity witness (lead ruling 2026-11-13)",
                    "witness_code": WITNESS_CODE,
                    "witness_rule": WITNESS_RULE,
                    "witness_spans_sha256": digest,
                    "gap_reason": r["reason"],
                    "list_date": r["list_date"],
                    "ibkr_sessions": int(r["ibkr_sessions"]),
                    **{k: c[k] for k in ("pairs", "agreeing", "correlation", "level_median",
                                         "level_iqr", "n_splits")},  # fmt: skip
                },
            )
        )
    return out


def single_figi(body: Any, ticker: str) -> tuple[str, str] | None:
    """(composite, share class) when exactly one captured OpenFIGI entry names ``ticker`` on
    exchange US, else None."""
    entries = [
        e
        for block in (body or [])
        for e in (block.get("data") or [])
        if e.get("ticker") == ticker and e.get("exchCode") == "US"
    ]
    pairs = {(e.get("compositeFIGI"), e.get("shareClassFIGI")) for e in entries}
    if len(entries) != 1 or None in next(iter(pairs)):
        return None
    return next(iter(pairs))


def _overlaps(a: date, b: date | None, c: date, d: date | None) -> bool:
    return (b is None or c < b) and (d is None or a < d)


def plan_amendment(
    placed: Sequence[PlacedSpan],
    identifiers: Mapping[str, Mapping[str, str]],
    isin_answers: Mapping[str, tuple[str, Any]],
    live_spans: Sequence[tuple[str, str, date, date | None]],
    gap_rows: Sequence[dict[str, str]],
    archive_start: date,
    archive_end: date,
) -> Amendment:
    """The amendment (module docstring). Raises on any overlap with a live span."""
    amendment = Amendment()
    clashes = [
        f"{p.symbol} {p.ticker} {p.start}..{p.end} overlaps {sym} {tick} {a}..{b}"
        for p in placed
        for sym, tick, a, b in live_spans
        if (sym == p.symbol or tick == p.ticker) and _overlaps(p.start, p.end, a, b)
    ]
    clashes += [
        f"{p.symbol} {p.start}..{p.end} overlaps placed {q.symbol} {q.start}..{q.end}"
        for i, p in enumerate(placed)
        for q in placed[i + 1 :]
        if (p.symbol == q.symbol or p.ticker == q.ticker)
        and _overlaps(p.start, p.end, q.start, q.end)
    ]
    if clashes:
        raise ValueError(f"{len(clashes)} overlap(s) with live or placed spans: {clashes}")
    placed_keys = set()
    for p in placed:
        ids = identifiers.get(p.symbol, {})
        if SPAN_SCHEME not in ids:
            isin = ids.get("isin")
            answer = isin_answers.get(isin) if isin else None
            figi = single_figi(answer[1], p.symbol) if answer else None
            if figi is None:
                amendment.kept_as_gap.append((p.symbol, "no single captured OpenFIGI answer"))
                continue
            for scheme, value in zip(("composite_figi", "share_class_figi"), figi, strict=True):
                if (p.symbol, scheme, value, answer[0]) not in amendment.mint:
                    amendment.mint.append((p.symbol, scheme, value, answer[0]))
        amendment.spans.append(p)
        placed_keys.add((p.symbol, p.reason, p.start, p.end))
    for g in gap_rows:
        start = max(date.fromisoformat(g["valid_from"]) if g["valid_from"] else archive_start,
                    archive_start)  # fmt: skip
        end = min(date.fromisoformat(g["valid_to"]) if g["valid_to"] else archive_end, archive_end)
        if (g["symbol"], g["reason"], start, end) in placed_keys:
            amendment.removed_gaps.append(g)
    return amendment


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


class TickerEntityMapAmender(BaseBatch):
    """The --amend run (module docstring): additive rows from the identity witness."""

    job_name = _JOB
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, apply: bool, args: argparse.Namespace,
                 out_root: Path = _OUT_ROOT):  # fmt: skip
        super().__init__(db_dsn)
        self._apply = apply
        self._args = args
        self._out_root = out_root

    async def execute(self, pool: asyncpg.Pool) -> None:
        from scripts.ops.bars.ops_massive_policy_plan import archive_end_of
        from src.intelligence.bars.ticker_entity_map import MASSIVE_ARCHIVE_START

        args = self._args
        placed = read_placed(
            args.amend.read_bytes(), args.amend_candidates.read_bytes(), args.amend_sha256
        )
        gap_bytes = args.gap_list.read_bytes()
        gap_rows = list(csv.DictReader(io.StringIO(gap_bytes.decode())))
        archive_end = archive_end_of(args.manifest.read_bytes())
        async with pool.acquire() as conn:
            identifiers: dict[str, dict[str, str]] = {}
            id_rows = {}
            for r in await conn.fetch(_AMEND_IDS_SQL):
                identifiers.setdefault(r["symbol"], {})[r["scheme"]] = r["value"]
                id_rows[(r["symbol"], r["scheme"])] = r["security_identifier_id"]
            isin_answers = {
                r["isin"]: (r["id"], r["body"]) for r in await conn.fetch(_AMEND_FIGI_SQL)
            }
            live = [tuple(r.values()) for r in await conn.fetch(_AMEND_SPANS_SQL)]
            overview = {r["symbol"]: r["id"] for r in await conn.fetch(_AMEND_OVERVIEW_SQL)}
            plan = plan_amendment(
                placed, identifiers, isin_answers, live, gap_rows, MASSIVE_ARCHIVE_START,
                archive_end,
            )  # fmt: skip
            if len(plan.removed_gaps) != len(plan.spans):
                raise RuntimeError(
                    f"{len(plan.spans)} spans placed but {len(plan.removed_gaps)} gap rows "
                    "match them: the gap list is not the one the witness read"
                )
            missing = sorted({p.symbol for p in plan.spans} - overview.keys())
            if missing:
                raise RuntimeError(f"no captured overview answer to cite for {missing}")
            report = {
                "apply": self._apply,
                "spans_to_insert": len(plan.spans),
                "identifiers_to_mint": len(plan.mint),
                "gap_rows_removed": len(plan.removed_gaps),
                "kept_as_gap": plan.kept_as_gap,
                "gap_list_in": {"path": str(args.gap_list),
                                "sha256": hashlib.sha256(gap_bytes).hexdigest()},
                "witness_spans_sha256": args.amend_sha256,
            }  # fmt: skip
            removed = {id(g) for g in plan.removed_gaps}
            kept_rows = [g for g in gap_rows if id(g) not in removed]
            buf = io.StringIO()
            writer = csv.DictWriter(buf, list(gap_rows[0]), lineterminator="\r\n")
            writer.writeheader()
            writer.writerows(kept_rows)
            new_gap = buf.getvalue().encode()
            out = self._out_root / (
                f"{datetime.now(UTC):%Y%m%d}_{hashlib.sha256(new_gap).hexdigest()[:12]}"
            )
            try:
                async with conn.transaction():
                    if plan.mint:
                        for r in await conn.fetch(
                            _INSERT_IDENTIFIERS_SQL,
                            [m[0] for m in plan.mint],
                            [m[1] for m in plan.mint],
                            [m[2] for m in plan.mint],
                            [datetime.now(UTC).date()] * len(plan.mint),
                            [m[3] for m in plan.mint],
                        ):
                            id_rows[(r["symbol"], r["scheme"])] = r["security_identifier_id"]
                    spans = plan.spans
                    await conn.execute(
                        _INSERT_SPANS_SQL,
                        [id_rows[(p.symbol, SPAN_SCHEME)] for p in spans],
                        [p.symbol for p in spans],
                        [p.ticker for p in spans],
                        [p.start for p in spans],
                        [p.end for p in spans],
                        [overview[p.symbol] for p in spans],
                        [canonical_json(p.evidence) for p in spans],
                    )
                    if not self._apply:
                        raise _Rehearsal
                outcome = "inserted"
            except _Rehearsal:
                outcome = "rolled_back"
        if self._apply:
            out.mkdir(parents=True, exist_ok=True)
            (out / "gap_list.csv").write_bytes(new_gap)
            (out / "amendment.json").write_text(
                json.dumps({**report, "outcome": outcome, "minted": plan.mint}, indent=2,
                           default=str) + "\n")  # fmt: skip
        self.logger.info("ticker_entity_map.amend_done", outcome=outcome, out=str(out))
        print(json.dumps({"outcome": outcome, "out": str(out), **report}, indent=2, default=str))


class _Rehearsal(Exception):
    """Raised inside the transaction to roll it back on a run without --apply."""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the stage 1 ticker-entity map")
    parser.add_argument("--apply", action="store_true", help="commit; default rolls back")
    parser.add_argument("--amend", type=Path, help="the identity witness spans CSV (design 8c)")
    parser.add_argument("--amend-sha256", help="--amend: the pinned sha256 of the spans CSV")
    parser.add_argument("--amend-candidates", type=Path, help="--amend: the candidates CSV")
    parser.add_argument("--gap-list", type=Path, help="--amend: the gap list the witness read")
    parser.add_argument(
        "--manifest", type=Path, default=_REPO_ROOT / "data/massive/manifest/manifest.jsonl"
    )
    args = parser.parse_args()
    if args.amend and not (args.amend_sha256 and args.amend_candidates and args.gap_list):
        parser.error("--amend needs --amend-sha256, --amend-candidates and --gap-list")
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    if args.amend:
        asyncio.run(TickerEntityMapAmender(db_dsn, args.apply, args).run())
    else:
        asyncio.run(TickerEntityMapWriter(db_dsn, args.apply).run())


if __name__ == "__main__":
    main()
