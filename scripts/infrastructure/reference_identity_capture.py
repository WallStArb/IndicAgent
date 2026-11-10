#!/usr/bin/env python3
"""Capture the identity anchors of our instruments outside Massive (todo 600 admission step 3b).

Two read-only captures in the canonical dated reference layout (admission design section 6:
``<root>/<endpoint>/<YYYYMMDD>/<key>__p0001.json.gz`` plus ``<root>/manifest/<YYYYMMDD>.jsonl``,
one line per stored answer with its sha256 over the uncompressed bytes). The manifest, the
atomic fsynced file write, the intact-file check and the day lock are the Massive reference
capture's own (``scripts/infrastructure/massive/massive_reference_capture.py``), imported:

- ``ibkr``: IBKR contract details, Stock(SMART, USD), for every instrument of an asset class the
  Massive stock files hold, through ``iter_stock_contract_details`` (``src/providers/ibkr.py``;
  a plain read-only session with no restart path). The ISIN is in ``secIdList``. Root
  ``data/ibkr/reference``.
- ``openfigi``: OpenFIGI's mapping of every ISIN the IBKR capture served, restricted to the US
  composite (``exchCode`` US), one ISIN per request so each stored file is one exact response.
  OpenFIGI is the FIGI registry itself: the bridge from ISIN to the FIGIs Massive serves, which
  Massive cannot be for its own identifiers. The IBKR files are read through the reference
  parser, so a file that no longer matches its manifest hash fails the run. Root
  ``data/openfigi/reference``.

Only answers are stored: an IBKR ask that timed out or failed (body status ERROR) and an
OpenFIGI reply other than one job's answer in an HTTP 200 JSON body (a job error included) are
not answers about the security; they are
counted and printed, and a rerun asks again. Resumable: a key already in the day's manifest with
an intact file is skipped; one whose file no longer matches refuses the run (a second line for
the key would be a second capture in one manifest). Load with
``services.reference_raw_writer`` (it loads every ``data/*/reference`` root).

    .venv/bin/python scripts/infrastructure/reference_identity_capture.py ibkr --client-id 43
    .venv/bin/python scripts/infrastructure/reference_identity_capture.py openfigi
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import sys
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import httpx
import psycopg

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from scripts.infrastructure.massive.massive_reference_capture import (  # noqa: E402
    Manifest,
    intact_body,
    page_path,
    sha256_bytes,
    write_page,
)
from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import format_iso_ts  # noqa: E402
from src.intelligence.bars.massive_reference import (  # noqa: E402
    discover_manifests,
    parse_manifest_line,
    read_body,
)
from src.intelligence.bars.ticker_entity_map import MASSIVE_ASSET_CLASSES, isins_of  # noqa: E402
from src.providers.ibkr import iter_stock_contract_details  # noqa: E402

IBKR_ROOT = project_root / "data" / "ibkr" / "reference"
OPENFIGI_ROOT = project_root / "data" / "openfigi" / "reference"
IBKR_ENDPOINT = "contract_details"
OPENFIGI_ENDPOINT = "mapping_isin_us"
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"

_ASKS_SQL = """
SELECT symbol, coalesce(contract_details->'provider_meta'->'ibkr'->>'symbol', symbol)
  FROM instruments WHERE contract_details->>'asset_class' = ANY(%s) ORDER BY symbol
"""


class DayCapture:
    """One day's capture under one reference root: the manifest and its writes."""

    def __init__(self, root: Path, day: str):
        self.root = root
        self.day = day
        self.manifest = Manifest(root / "manifest" / f"{day}.jsonl")

    def present(self, endpoint: str, key: str) -> bool:
        """True if captured with an intact file; a damaged capture refuses the run."""
        record = self.manifest.get(endpoint, key, 1)
        if record is None:
            return False
        if intact_body(self.root / record["path"], record) is None:
            raise RuntimeError(f"{self.manifest.path}: {endpoint} {key} no longer matches its file")
        return True

    def record(
        self,
        *,
        endpoint: str,
        key: str,
        url: str,
        status: int | None,
        served: bytes,
        fetched_at: datetime,
        http_date: str | None,
        **extra: object,
    ) -> None:
        path = page_path(self.root, endpoint, self.day, key, 1)
        write_page(path, served)
        self.manifest.append(
            {
                "endpoint": endpoint,
                "key": key,
                "page": 1,
                "url": url,
                "status": status,
                "date": http_date,
                "bytes": len(served),
                "sha256": sha256_bytes(served),
                "path": path.relative_to(self.root).as_posix(),
                "fetched_at": format_iso_ts(fetched_at),
                **extra,
            }
        )


@contextmanager
def day_capture(root: Path) -> Iterator[DayCapture]:
    """The day's capture, held under the same per-day lock the Massive capture takes."""
    day = datetime.now(UTC).strftime("%Y%m%d")
    (root / "manifest").mkdir(parents=True, exist_ok=True)
    with (root / "manifest" / f"{day}.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit(f"another capture holds the lock for {root} {day}") from None
        yield DayCapture(root, day)


async def capture_ibkr(
    client_id: int, pause_s: float, in_use_wait_s: float, limit: int | None
) -> None:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn:
        asks = conn.execute(_ASKS_SQL, (sorted(MASSIVE_ASSET_CLASSES),)).fetchall()
    with day_capture(IBKR_ROOT) as capture:
        todo = [(s, i) for s, i in asks if not capture.present(IBKR_ENDPOINT, s)][:limit]
        symbol_for = {ibkr: symbol for symbol, ibkr in todo}
        statuses: Counter = Counter()
        async for answer in iter_stock_contract_details(
            [ibkr for _, ibkr in todo],
            host=settings.ib_host,
            port=settings.ib_port,
            client_id=client_id,
            pause_s=pause_s,
            connect_timeout_s=settings.ib_timeout_sec,
            in_use_wait_s=in_use_wait_s,
        ):
            statuses[answer.body["status"]] += 1
            if answer.body["status"] == "ERROR":
                continue  # a timeout or failed ask is no answer; a rerun asks again
            query = "&".join(f"{k}={quote(str(v))}" for k, v in answer.body["request"].items())
            capture.record(
                endpoint=IBKR_ENDPOINT,
                key=symbol_for[answer.ibkr_symbol],
                url=f"ibkr://reqContractDetails?{query}",
                status=None,
                served=json.dumps(answer.body, sort_keys=True).encode("utf-8"),
                fetched_at=answer.answered_at,
                http_date=None,
            )
    print(json.dumps({"ibkr_asked": len(todo), "statuses": statuses}))


def _isins_from_ibkr() -> list[str]:
    """Every ISIN in every IBKR capture, each file proven against its manifest hash."""
    isins: set[str] = set()
    for manifest in discover_manifests(IBKR_ROOT):
        for number, text in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
            capture = parse_manifest_line(text, manifest, number, repo_root=project_root)
            isins |= isins_of(json.loads(read_body(capture, repo_root=project_root)))
    return sorted(isins)


def capture_openfigi(spacing_s: float, limit: int | None) -> None:
    headers = {"Content-Type": "application/json", "User-Agent": "reference-capture/1.0"}
    statuses: Counter = Counter()
    with (
        day_capture(OPENFIGI_ROOT) as capture,
        httpx.Client(timeout=30.0, headers=headers) as client,
    ):
        isins = _isins_from_ibkr()
        todo = [i for i in isins if not capture.present(OPENFIGI_ENDPOINT, i)][:limit]
        for isin in todo:
            job = [{"idType": "ID_ISIN", "idValue": isin, "exchCode": "US"}]
            while True:
                started = time.monotonic()
                response = client.post(OPENFIGI_URL, json=job)
                if response.status_code != 429:
                    break
                time.sleep(float(response.headers.get("ratelimit-reset", "60")) + 1.0)
            statuses[response.status_code] += 1
            try:
                jobs = response.json()
                # One job's answer: data (a match) or warning (no match). A job-level error
                # is a failed ask, like a non-200.
                answered = (
                    response.status_code == 200
                    and isinstance(jobs, list)
                    and len(jobs) == 1
                    and "error" not in jobs[0]
                )
            except ValueError:
                answered = False
            if not answered:
                # Not an answer: nothing stored, counted, and a rerun asks again.
                statuses[f"{response.status_code}:not_an_answer"] += 1
                time.sleep(max(0.0, spacing_s - (time.monotonic() - started)))
                continue
            capture.record(
                endpoint=OPENFIGI_ENDPOINT,
                key=isin,
                url=OPENFIGI_URL,
                status=response.status_code,
                served=response.content,
                fetched_at=datetime.now(UTC),
                http_date=response.headers.get("date"),
                request=job,
            )
            time.sleep(max(0.0, spacing_s - (time.monotonic() - started)))
    print(json.dumps({"openfigi_asked": len(todo), "http": statuses}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="vendor", required=True)
    ibkr = sub.add_parser("ibkr")
    ibkr.add_argument("--client-id", type=int, required=True, help="an unused id <= 50")
    ibkr.add_argument("--pause-s", type=float, default=0.25)
    ibkr.add_argument(
        "--in-use-wait-s", type=float, default=2.0, help="wait for IBKR Error 326 after connect"
    )
    ibkr.add_argument("--limit", type=int, default=None)
    figi = sub.add_parser("openfigi")
    figi.add_argument("--spacing-s", type=float, default=2.5, help="25 requests a minute")
    figi.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if args.vendor == "ibkr":
        asyncio.run(capture_ibkr(args.client_id, args.pause_s, args.in_use_wait_s, args.limit))
    else:
        capture_openfigi(args.spacing_s, args.limit)


if __name__ == "__main__":
    main()
