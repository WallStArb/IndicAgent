"""IBKR gateway auth-state probe (todo 395): is the gateway API actually usable?

Port 7497 accepting TCP says nothing. After IBKR's weekly re-auth the gateway
sits at a second-factor authentication prompt where the socket connects and the
API handshake times out (the 2026-09-23 recovery; the paused 2026-10-10
backfill rests on the same gateway). This probe runs the real handshake through
IBKRProvider -- the one place ib_async lives -- and records the outcome as a
point gauge the IBKRGatewayAuthDown alert fires on, so a logged-out gateway is
named before the next backfill run burns its budget on connect timeouts.

Read-only: no coverage rows, no ledger writes, no bars. Client id 44 is outside
the fetcher family's range (40-42) so the probe never collides with a live run,
and the FetcherLock is deliberately NOT taken: a backfill run in flight is
exactly when the answer matters most, and a lightweight second client does not
disturb the run's own connection.
"""

from __future__ import annotations

import asyncio
import sys

from src.config.settings import Settings
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    flush_and_shutdown_metrics,
    point_gauge,
)
from src.observability.otel import init_otel_providers
from src.providers.ibkr import IBKRProvider

JOB = "gateway-auth-probe"
CLIENT_ID = 44
CONNECT_TIMEOUT_S = 20.0

AUTH_GAUGE = point_gauge(
    "ibkr_gateway_authenticated",
    "1 if the IBKR gateway API handshake succeeded on the latest probe, else 0",
)


def auth_state(ok: bool) -> tuple[int, str]:
    """(gauge value, job status) for a probe outcome."""
    return (1, "success") if ok else (0, "failure")


async def probe() -> bool:
    """Run the real API handshake. True only when the gateway is logged in."""
    settings = Settings()
    provider = IBKRProvider(host=settings.ib_host, port=settings.ib_port, client_id=CLIENT_ID)
    try:
        connected = await asyncio.wait_for(provider.connect(), timeout=CONNECT_TIMEOUT_S)
        return bool(connected)
    except Exception:  # noqa: BLE001 -- the probe records any failure as unauthenticated
        return False
    finally:
        try:
            await provider.disconnect()
        except Exception:  # noqa: BLE001 -- never mask the probe result
            pass


async def amain() -> int:
    init_otel_providers(service_name="indicagent-gateway-auth-probe")
    ok = await probe()
    gauge_value, status = auth_state(ok)
    AUTH_GAUGE.set(gauge_value)
    JOB_COMPLETED_TOTAL.add(1, {"job": JOB, "status": status})
    flush_and_shutdown_metrics()
    print(f"ibkr_gateway_authenticated {gauge_value} ({status})")
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    sys.exit(main())
