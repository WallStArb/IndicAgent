"""Alpaca pilot puller (Workstream A of docs/plans/2026-10-09-alpaca-integration-pilot.md).

Read-only against the database: pulls bars from the Alpaca SIP feed into
data/scratch/alpaca-pilot/ as parquet, one file per name/timeframe, plus a
requests.jsonl log with one line per HTTP request. Respects the pre-registered
bounds: at most 10,000 requests, Basic-plan rate limit (190/min sustained,
under the documented 200), feed=sip, full depth from 2016-01-01.

Run: .venv/bin/python scripts/research/alpaca_pilot_pull.py
Idempotent: a name/timeframe with a complete marker file is skipped, so an
interrupted run resumes. Bounds are asserted, not assumed: the run refuses to
cross 10,000 logged requests.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd

SCRATCH = Path("data/scratch/alpaca-pilot")
ENV = Path(".env")
BASE = "https://data.alpaca.markets/v2/stocks/bars"
START = "2016-01-01"
MAX_REQUESTS = 10_000
MIN_INTERVAL_S = 60.0 / 190.0  # 190/min sustained, under the documented 200/min

CORE_20 = [
    "AMD",
    "BIL",
    "CRM",
    "DBC",
    "EFA",
    "EWT",
    "FXE",
    "HD",
    "ISRG",
    "KO",
    "MMM",
    "NEM",
    "PFE",
    "RIOT",
    "SLV",
    "TMUS",
    "UUP",
    "VRTX",
    "XBI",
    "XLY",
]
ONE_M_SUBSET = ["AMD", "BIL", "CRM", "DBC", "EFA"]  # first 5 core in symbol order
NAMES = CORE_20 + ["SPY", "AAPL"]
PLAN: list[tuple[str, str]] = [(s, "1Day") for s in NAMES]
PLAN += [(s, "5Min") for s in NAMES]
PLAN += [(s, "1Min") for s in ONE_M_SUBSET]


def load_keys() -> tuple[str, str]:
    key_id = secret = None
    for line in ENV.read_text().splitlines():
        if line.startswith("ALPACA_KEY_ID="):
            key_id = line.split("=", 1)[1]
        elif line.startswith("ALPACA_SECRET_KEY="):
            secret = line.split("=", 1)[1]
    if not key_id or not secret:
        raise SystemExit("ALPACA_KEY_ID / ALPACA_SECRET_KEY missing from .env")
    return key_id, secret


def main() -> None:
    key_id, secret = load_keys()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    log_path = SCRATCH / "requests.jsonl"
    headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}
    client = httpx.Client(timeout=60.0)
    n_requests = len(log_path.read_text().splitlines()) if log_path.exists() else 0
    last_request_at = 0.0

    for symbol, tf in PLAN:
        out = SCRATCH / f"{symbol}_{tf}.parquet"
        done_marker = SCRATCH / f"{symbol}_{tf}.complete"
        if done_marker.exists():
            continue
        rows: list[dict] = []
        page_token: str | None = None
        pages = 0
        while True:
            wait = MIN_INTERVAL_S - (time.monotonic() - last_request_at)
            if wait > 0:
                time.sleep(wait)
            params: dict[str, str] = {
                "symbols": symbol,
                "timeframe": tf,
                "start": START,
                "limit": "10000",
                "feed": "sip",
            }
            if page_token:
                params["page_token"] = page_token
            n_requests += 1
            if n_requests > MAX_REQUESTS:
                raise SystemExit(f"bound B1 crossed: {n_requests} requests > {MAX_REQUESTS}")
            response = client.get(BASE, headers=headers, params=params)
            last_request_at = time.monotonic()
            with log_path.open("a") as log:
                log.write(
                    json.dumps(
                        {
                            "ts": datetime.now(UTC).isoformat(),
                            "symbol": symbol,
                            "timeframe": tf,
                            "page": pages,
                            "status": response.status_code,
                            "n_bars": (
                                len(response.json().get("bars", {}).get(symbol, []))
                                if response.status_code == 200
                                else None
                            ),
                        }
                    )
                    + "\n"
                )
            if response.status_code == 429:
                retry_after = float(response.headers.get("retry-after", "30"))
                print(f"{symbol} {tf}: 429, sleeping {retry_after}s", flush=True)
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            payload = response.json()
            rows.extend(payload.get("bars", {}).get(symbol, []))
            pages += 1
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        frame = pd.DataFrame(rows)
        frame.to_parquet(out, index=False)
        done_marker.write_text(
            f"{len(frame)} bars, {pages} pages, written " f"{datetime.now(UTC).isoformat()}\n"
        )
        print(f"{symbol} {tf}: {len(frame)} bars, {pages} pages", flush=True)

    client.close()
    print(f"done: {n_requests} requests total", flush=True)


if __name__ == "__main__":
    main()
