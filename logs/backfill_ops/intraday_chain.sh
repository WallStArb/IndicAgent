#!/bin/bash
# Todo 449, owner decision 2026-09-27: one IBKR stream, 15m+1h first (what the strategy families read), then 5m.
cd /home/bg/dev/indicagent
logs/backfill_ops/intraday_htf_lane.sh htf_all 46 logs/backfill_ops/intraday_htf/all.symbols > logs/backfill_ops/intraday_htf/htf_all_loop.log 2>&1
logs/backfill_ops/intraday_5m_lane.sh solo 40 logs/backfill_ops/intraday_5m/solo.symbols > logs/backfill_ops/intraday_5m/solo_loop.log 2>&1
