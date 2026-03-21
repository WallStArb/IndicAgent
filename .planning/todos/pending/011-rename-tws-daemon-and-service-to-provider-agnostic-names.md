---
created: 2026-03-14T15:43:32.346Z
title: Rename tws daemon and service to provider-agnostic names
area: general
priority: 15
tier: deferred
phase: when-second-provider
files:
  - services/tws_daemon.py
  - /etc/systemd/system/indicagent-tws.service
  - CLAUDE.md
  - docs/cheatsheet.md
---

## Problem

`indicagent-tws.service` and `services/tws_daemon.py` expose the IBKR/TWS implementation detail as part of the service identity. CLAUDE.md explicitly requires provider-agnostic naming — IBKR/TWS is an implementation detail that belongs only in technical/operational sections, not in service names.

Surfaced during Phase 30 verification (2026-03-14): the systemd unit was still pointing to the old Redis-based daemon path, and the naming inconsistency was noticed when fixing it.

## Solution

1. Rename `services/tws_daemon.py` → `services/data_daemon.py` (or `market_data_daemon.py`)
2. Update systemd unit: `indicagent-tws.service` → `indicagent-data.service`
   - `sudo systemctl disable indicagent-tws`
   - Create `/etc/systemd/system/indicagent-data.service` with updated `ExecStart`
   - `sudo systemctl enable indicagent-data && sudo systemctl start indicagent-data`
3. Update CLAUDE.md service table (tws → data)
4. Update `docs/cheatsheet.md` if referenced there
5. Search for any other `indicagent-tws` or `tws_daemon` references in docs/scripts

Do after Phase 30 is verified and stable on main.
