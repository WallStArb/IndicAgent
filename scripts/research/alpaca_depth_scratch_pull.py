"""Alpaca intraday depth pull, scratch staging (todo 521, phase 1 of 3).

Pulls full-depth 5m bars (2016-01-01 forward, adjustment=split, SIP feed) for
the 233-name intraday universe into data/scratch/alpaca-pilot/depth/ as
parquet, one file per name. Scratch only: nothing touches market_data_ohlcv.
Admission through the leaf is a later phase; this run only lands the bytes.

Per todo 521's pilot-mandated decisions: adjustment=split (stored bars are
split-adjusted), 5m only (1m has no registered consumer), both RTH and
extended-hours bars are kept in scratch and the RTH filter applies at
admission.

Run: .venv/bin/python scripts/research/alpaca_depth_scratch_pull.py
Idempotent per name (a .complete marker skips); resumes after interruption.
Rate limit: 190 requests/min sustained, under the documented Basic 200.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd

SCRATCH = Path("data/scratch/alpaca-pilot/depth")
UNIVERSE = Path("data/scratch/alpaca-pilot/intraday_universe_233.txt")
ENV = Path(".env")
BASE = "https://data.alpaca.markets/v2/stocks/bars"
START = "2016-01-01"
MIN_INTERVAL_S = 60.0 / 190.0

# Optional overrides for a second, chained pass over a wider universe
# (phase 2: the full 1,502-name daily universe, same scratch policy):
#   alpaca_depth_scratch_pull.py <universe_file> <scratch_dir>
if len(sys.argv) == 3:
    UNIVERSE = Path(sys.argv[1])
    SCRATCH = Path(sys.argv[2])


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
    names = [s.strip() for s in UNIVERSE.read_text().splitlines() if s.strip()]
    log_path = SCRATCH / "requests.jsonl"
    headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}
    client = httpx.Client(timeout=60.0)
    n_requests = len(log_path.read_text().splitlines()) if log_path.exists() else 0
    n_done = 0
    last_request_at = 0.0

    for symbol in names:
        out = SCRATCH / f"{symbol}_5Min.parquet"
        done = SCRATCH / f"{symbol}_5Min.complete"
        if done.exists():
            n_done += 1
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
                "timeframe": "5Min",
                "start": START,
                "limit": "10000",
                "feed": "sip",
                "adjustment": "split",
            }
            if page_token:
                params["page_token"] = page_token
            n_requests += 1
            response = client.get(BASE, headers=headers, params=params)
            last_request_at = time.monotonic()
            with log_path.open("a") as log:
                log.write(
                    json.dumps(
                        {
                            "ts": datetime.now(UTC).isoformat(),
                            "symbol": symbol,
                            "page": pages,
                            "status": response.status_code,
                        }
                    )
                    + "\n"
                )
            if response.status_code == 429:
                retry_after = float(response.headers.get("retry-after", "30"))
                print(f"{symbol}: 429, sleeping {retry_after}s", flush=True)
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
        done.write_text(f"{len(frame)} bars, {pages} pages, " f"{datetime.now(UTC).isoformat()}\n")
        n_done += 1
        print(
            f"[{n_done}/{len(names)}] {symbol}: {len(frame)} bars, " f"{pages} pages",
            flush=True,
        )

    client.close()
    print(f"done: {len(names)} names, {n_requests} requests total", flush=True)


if __name__ == "__main__":
    main()
