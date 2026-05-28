# IB Gateway on Linux — Design Spec

**Version:** 1.0
**Last Updated:** 2026-05-03
**Date:** 2026-05-03
**Status:** Approved
**Driver:** Eliminate single point of failure (Windows TWS desktop) from data pipeline

## Problem

IBKR TWS runs on a Windows desktop at 192.168.68.50. When that machine goes offline (sleep, reboot, weekend), the entire intelligence pipeline stops producing data. Last data gap: April 30 → present (3 days, possibly including a full trading day on May 1). This violates Renaissance principle: never drop data that could contain signal.

## Solution

Run IB Gateway headless in Docker on the Linux server. Same IBKR account, same API protocol, zero code changes to the pipeline.

## Changes

### 1. docker-compose.yml — add ib-gateway service

```yaml
ib-gateway:
  image: ghcr.io/gnzsnz/ib-gateway:stable
  container_name: ib-gateway
  restart: always
  environment:
    TWS_USERID: ${TWS_USERID}
    TWS_PASSWORD: ${TWS_PASSWORD}
    TRADING_MODE: paper
    TWOFA_TIMEOUT_ACTION: restart
    RELOGIN_AFTER_TWOFA_TIMEOUT: "yes"
    BYPASS_WARNING: "yes"
    AUTO_RESTART_TIME: "11:59 PM"
    TIME_ZONE: Etc/UTC
    TZ: Etc/UTC
  ports:
    - "127.0.0.1:7497:4003"
  volumes:
    - ib-gateway-settings:/home/ibgateway/Jts
```

Port mapping: host 7497 → container 4003 (paper trading). All existing services connect on localhost:7497 — no changes needed.

### 2. .env — update IBKR_HOST, add credentials

```
IBKR_HOST=localhost
IB_HOST=localhost
TWS_USERID=goyett507
TWS_PASSWORD=<provided>
```

### 3. No other changes

- All 31 systemd services: unchanged
- src/providers/ibkr.py: unchanged
- ib_insync connection params: unchanged (localhost:7497, client ID 35)
- All pipeline code: unchanged

## Failure Handling

- Container crash: Docker `restart: always` (seconds)
- Daily restart: `AUTO_RESTART_TIME=11:59 PM` (avoids 2FA re-auth accumulation)
- 2FA timeout: `TWOFA_TIMEOUT_ACTION=restart` (retry, not exit)
- Settings persistence: Docker volume `ib-gateway-settings` survives container recreation

## Network Flow (After)

```
IB Gateway (Docker) localhost:7497 → ibkr-provider (systemd) → Redpanda → pipeline
```

## Verification

1. `docker compose up -d ib-gateway` — container starts
2. Wait ~60s for gateway to initialize
3. `sudo systemctl restart indicagent-ibkr-provider` — reconnect to localhost:7497
4. Check `logs/ibkr_provider_agent.log` for `setup_complete`
5. Check `market_data_ohlcv` for new bars (requires market hours)
