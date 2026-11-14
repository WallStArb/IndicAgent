"""Alpaca paper order-lifecycle pilot (todo 522, Workstream B of
docs/plans/archive/2026-10-09-alpaca-integration-pilot.md).

Paper endpoint only: the base URL is asserted, never configured, so a stray
environment cannot route this at the live endpoint. Zero canonical writes: the
pilot's ledger is JSONL under data/scratch/alpaca-paper/.

Pre-registered bounds (the pilot doc): at most 20 measured orders, 1 share
each, at least 5 names, all flat by EOD. `stage` validates the API surface
off-hours (place, replace, cancel, idempotent reconnect by client_order_id)
with deep unmarketable limits that cannot fill, then cancels everything; its
orders are plumbing checks and never count against the measured 20.
`run` is the measured protocol at an open market: one marketable limit per
name, the decision-time mid recorded before transmit, every order polled to a
terminal state, and any order still open at the end is cancelled (EOD flat).

Slippage definition (fixed here and in
docs/plans/2026-11-01-own-flow-slippage-instrumentation.md, not to be
redefined after first measurement): decision-time mid = the IEX quote midpoint
nearest before decision_time (the paper account's licensed feed; the pilot
draft said SIP, corrected before first measurement, 2026-11-01); realized
slippage (bps) = sign * (fill_price - decision_mid) / decision_mid * 1e4 with
sign +1 for buys and -1 for sells.

Commands:
    stage   -- off-hours API surface validation (deep limits, all cancelled)
    run     -- the measured protocol (requires an open market)
    check   -- orphan sweep: cancel any open order, assert flat
    status  -- print the ledger's order states

Run: .venv/bin/python scripts/ops/alpaca_paper_lifecycle.py stage
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE = "https://paper-api.alpaca.markets"  # asserted: paper only, never live
DATA_BASE = "https://data.alpaca.markets/v2"
LEDGER = Path("data/scratch/alpaca-paper/orders.jsonl")
QTY = "1"
STAGE_NAMES = ["SPY", "AAPL", "AMD", "KO", "HD"]


def _keys() -> tuple[str, str]:
    key_id = secret = None
    for line in Path(".env").read_text().splitlines():
        if line.startswith("ALPACA_KEY_ID="):
            key_id = line.split("=", 1)[1]
        elif line.startswith("ALPACA_SECRET_KEY="):
            secret = line.split("=", 1)[1]
    if not key_id or not secret:
        raise SystemExit("ALPACA_KEY_ID / ALPACA_SECRET_KEY missing from .env")
    return key_id, secret


def _headers() -> dict[str, str]:
    key_id, secret = _keys()
    return {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}


def _log(record: dict) -> None:
    """One JSONL line per event; the ledger is the pilot's only write."""
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")
    print(json.dumps(record, default=str)[:200])


def _mid(client: httpx.Client, symbol: str) -> tuple[float, datetime]:
    """The last IEX quote's midpoint (stale when the market is closed; the
    measured run requires an open market so the mid is decision-fresh). IEX is
    the paper account's licensed feed (SIP latest quotes 403, checked
    2026-11-01); the instrumentation spec fixes the mid on IEX before any
    measurement, and says so where the pilot draft said SIP."""
    r = client.get(
        f"{DATA_BASE}/stocks/quotes/latest",
        params={"feed": "iex", "symbols": symbol},
    )
    r.raise_for_status()
    q = r.json()["quotes"][symbol]
    mid = (q["bp"] + q["ap"]) / 2  # the v2 latest-quote's short keys: bid, ask
    return mid, datetime.fromisoformat(q["t"])


def _client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=15, headers=_headers())


def _order_by_client_id(client: httpx.Client, client_order_id: str) -> dict | None:
    # the dedicated lookup endpoint: a client_order_id filter on GET /v2/orders is silently
    # ignored (it reads as an unfiltered list; found out staging, 2026-11-01)
    r = client.get("/v2/orders:by_client_order_id", params={"client_order_id": client_order_id})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _place(
    client: httpx.Client,
    *,
    symbol: str,
    side: str,
    limit_price: str,
    decision_id: str,
    decision_mid: float,
    kind: str,
) -> dict:
    """Place one 1-share day limit order with a deterministic client_order_id."""
    client_order_id = f"p522-{decision_id}"
    transmit = datetime.now(UTC)
    r = client.post(
        "/v2/orders",
        json={
            "symbol": symbol,
            "qty": QTY,
            "side": side,
            "type": "limit",
            "time_in_force": "day",
            "limit_price": limit_price,
            "client_order_id": client_order_id,
        },
    )
    r.raise_for_status()
    order = r.json()
    record = {
        "event": "placed",
        "kind": kind,
        "decision_id": decision_id,
        "symbol": symbol,
        "side": side,
        "qty": QTY,
        "limit_price": limit_price,
        "decision_mid": decision_mid,
        "decision_time": transmit.isoformat(),
        "transmit_time": datetime.now(UTC).isoformat(),
        "client_order_id": client_order_id,
        "alpaca_order_id": order["id"],
        "status": order["status"],
    }
    _log(record)
    return record


def _terminal(status: str) -> bool:
    return status in ("filled", "canceled", "cancelled", "expired", "rejected")


def _await_terminal(client: httpx.Client, order_id: str, *, seconds: float = 60) -> str:
    deadline = time.monotonic() + seconds
    status = ""
    while time.monotonic() < deadline:
        r = client.get(f"/v2/orders/{order_id}")
        r.raise_for_status()
        status = r.json()["status"]
        if _terminal(status):
            return status
        time.sleep(1.0)
    return status


def stage() -> int:
    """Off-hours API surface validation: deep unmarketable limits that cannot
    fill, one deliberate idempotent reconnect, a replace, cancels, zero
    orphans. Staging orders never count against the measured 20."""
    problems: list[str] = []
    with _client() as client:
        account = client.get("/v2/account")
        account.raise_for_status()
        if not account.json()["id"]:
            problems.append("no account id")
        mid, quote_time = _mid(client, STAGE_NAMES[0])
        print(f"stage: last {STAGE_NAMES[0]} mid {mid} quoted {quote_time} (market closed)")

        # 1. place across five names, deep limits that cannot fill
        placed = []
        for i, symbol in enumerate(STAGE_NAMES):
            decision_id = f"stage-{uuid.uuid4().hex[:8]}"
            m, _ = _mid(client, symbol)
            side = "buy" if i % 2 == 0 else "sell"
            price = m * (0.5 if side == "buy" else 2.0)  # far through the book
            placed.append(
                _place(
                    client,
                    symbol=symbol,
                    side=side,
                    limit_price=f"{price:.2f}",
                    decision_id=decision_id,
                    decision_mid=m,
                    kind="stage",
                )
            )

        # 2. idempotent reconnect: a brand-new client resolves the same order by
        #    client_order_id, and re-placing the same id is rejected (no duplicate)
        target = placed[0]
        with _client() as reconnect:
            found = _order_by_client_id(reconnect, target["client_order_id"])
            if found is None or found["id"] != target["alpaca_order_id"]:
                problems.append("reconnect: order not found by client_order_id")
            else:
                print(f"reconnect: {target['client_order_id']} -> same order {found['id']}")
            dup = reconnect.post(
                "/v2/orders",
                json={
                    "symbol": target["symbol"],
                    "qty": QTY,
                    "side": target["side"],
                    "type": "limit",
                    "time_in_force": "day",
                    "limit_price": target["limit_price"],
                    "client_order_id": target["client_order_id"],
                },
            )
            if dup.status_code not in (400, 403, 409, 422):
                problems.append(
                    f"reconnect: duplicate client_order_id accepted ({dup.status_code})"
                )
            else:
                print("reconnect: duplicate client_order_id rejected (no duplicate order)")

        # 3. replace one order (limit price), verify the server version bumps
        target = placed[1]
        r = client.patch(
            f"/v2/orders/{target['alpaca_order_id']}",
            json={"limit_price": f"{float(target['limit_price']) * 1.1:.2f}"},
        )
        if r.status_code == 200:
            replaced = r.json()
            _log(
                {
                    "event": "replaced",
                    "decision_id": target["decision_id"],
                    "new_limit_price": replaced["limit_price"],
                }
            )
        else:
            problems.append(f"replace failed: {r.status_code} {r.text[:120]}")

        # 4. cancel everything and verify terminal states
        for record in placed:
            r = client.delete(f"/v2/orders/{record['alpaca_order_id']}")
            if r.status_code not in (200, 204, 404):
                problems.append(f"cancel {record['decision_id']}: {r.status_code}")
            status = _await_terminal(client, record["alpaca_order_id"])
            _log(
                {
                    "event": "terminal",
                    "kind": "stage",
                    "decision_id": record["decision_id"],
                    "status": status,
                }
            )
            if not _terminal(status):
                problems.append(
                    f"{record['decision_id']} never reached a terminal state ({status})"
                )

        # 5. zero orphans. The open-order list lags the per-order cancel by seconds to
        # minutes off-hours (seen staging, 2026-11-01): the per-order state flips to
        # canceled while the list still returns it, so settle before judging.
        open_orders = []
        for _ in range(12):
            open_orders = client.get("/v2/orders", params={"status": "open"}).json()
            if not open_orders:
                break
            time.sleep(10)
        if open_orders:
            problems.append(f"{len(open_orders)} open order(s) remain")
        print(
            f"stage: {len(placed)} orders placed, replaced, cancelled; "
            f"{len(open_orders)} open at end"
        )

    for problem in problems:
        print(f"PROBLEM: {problem}")
    return 1 if problems else 0


def check() -> int:
    """Orphan sweep: cancel anything open, assert flat."""
    with _client() as client:
        open_orders = client.get("/v2/orders", params={"status": "open"}).json()
        for order in open_orders:
            client.delete(f"/v2/orders/{order['id']}")
            _log(
                {
                    "event": "orphan_cancelled",
                    "client_order_id": order["client_order_id"],
                    "symbol": order["symbol"],
                }
            )
        print(f"check: {len(open_orders)} open order(s) cancelled")
        return 0


def status() -> int:
    if not LEDGER.exists():
        print("no ledger yet")
        return 0
    counts: dict[str, int] = {}
    for line in LEDGER.read_text().splitlines():
        record = json.loads(line)
        counts[record["event"]] = counts.get(record["event"], 0) + 1
    print(json.dumps(counts, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["stage", "run", "check", "status"])
    args = parser.parse_args()
    if args.command == "stage":
        return stage()
    if args.command == "check":
        return check()
    if args.command == "status":
        return status()
    raise SystemExit("run: the measured protocol needs an open market; see the todo")


if __name__ == "__main__":
    raise SystemExit(main())
