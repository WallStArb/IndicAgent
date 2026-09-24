---
status: pending
priority: P0
filed: 2026-09-23
source: post-power-outage recovery check, 2026-09-23 (nightly_backfill.failed seen in log tail)
---

# Nightly backfill fails 3 nights every week: IBKR weekly re-auth needs an unattended 2FA tap, and the failure alert is dropped

## What

`indicagent-nightly-backfill.service` (timer 05:00 UTC / 01:00 EDT) exits `status=1/FAILURE`
with `API connection failed: TimeoutError()` / `Cannot connect to TWS` on a weekly cadence
(`journalctl -u indicagent-nightly-backfill.service`):

| Run (EDT) | Result |
|---|---|
| Mon 09-14, Tue 09-15 | FAILED (IBKR connect) |
| Wed 09-16 | ok (07:32, manual run after intervention) |
| Thu 09-17 .. Sun 09-20 | ok |
| Mon 09-21, Tue 09-22, Wed 09-23 | FAILED (IBKR connect) |

The pattern matches IBKR's weekly forced logout (weekend): IBC's daily
`AUTO_RESTART_TIME=11:59 PM` (container `TZ=Etc/UTC`) avoids 2FA during the week, but after the
weekly logout the gateway sits at a Second Factor Authentication prompt
(`TWOFA_TIMEOUT_ACTION=restart`, `RELOGIN_AFTER_TWOFA_TIMEOUT=yes` just re-prompt) until a human
approves on the phone. It stayed logged out from Sun 09-20 until the post-power-outage restart
on 2026-09-23 18:08 UTC, where 2FA was approved in 9 s (human tap). Gateway log history before
that restart is gone (container log size cap), so the weekend-logout mechanism is inferred from
the failure calendar plus IBKR's documented weekly re-auth, not observed directly. Confirm next
Sunday/Monday by capturing `docker logs ib-gateway` around the logout before it rotates.

Consequence: OHLCV freshness gap of ~3 days every week for all 233 symbols, invisible to
anything downstream.

## Why nobody noticed

1. `OneshotJobFailed` (`production/alertmanager-rules.yml`) exists, but `alertmanager.yml`
   routes to a no-op `default` receiver since 2026-08-15 (Telegram `chat_id` never set). The
   alert fires into nothing.
2. The script logs `nightly_backfill.failed` at `level: info`.

## Fix

1. Restore a working Alertmanager receiver (Telegram chat_id, or ntfy) so `OneshotJobFailed`
   reaches a human. This is the actual forcing function; everything else is detected by it.
2. Add a gateway-auth-state alert: probe that the gateway is logged in (not just port 7497
   open; the port accepts TCP while the API handshake times out), e.g. a small oneshot that
   does an ib_async connect + `reqCurrentTime` and emits a gauge, alerting before the 05:00
   UTC run rather than after it.
3. Make the backfill retry: on IBKR connect failure, re-arm (systemd `Restart=on-failure` with
   `RestartSec` in the hours range, or a second timer) so a 2FA approved mid-morning still gets
   that day's catch-up without a manual run.
4. Log `nightly_backfill.failed` at `error`.

## Immediate

Gateway is logged in as of 2026-09-23 18:08 UTC. Manual catch-up run for the 09-20..09-23
gap started 2026-09-23 ~18:11 UTC (`infrastructure_nightly_backfill.py` run directly as `bg`
with the unit's env vars, since `systemctl start` needs sudo; all 233 symbols). Confirm it
completed and that `MAX(timestamp)` advanced before closing the gap.

## Related

- todo 382 (nightly backfill selection/throughput), todo 366 (live consumers still down),
  todo 363 (gateway libgtk fix durability)
- memory `project_ibkr_live_ingestion_stalled_2fa` (its 2026-08-31 "not a 2FA issue" finding
  was about a different, one-off failure; this one is the recurring weekly 2FA path)
