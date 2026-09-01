---
status: pending
priority: P2
filed: 2026-09-01
source: starting statistical_factor_residual Stage 3 -- universe fetch returned 0/231
  symbols with complete daily history, traced to a live corpus data gap
---

**User direction, 2026-09-01: filed P2, not P0.** Decades of historical data already
available, no proven edge yet to protect, so live-ingestion freshness doesn't gate research
value -- a few weeks of missing recent bars doesn't materially change any discovery-track
result. A backfill to bring OHLCV current is optional/later, not blocking. Stage 3 itself was
unblocked by excluding the resulting gap dates from the analysis window, not by fixing this
todo -- see `docs/research/measurement-statistical-factor-residual.md`.

# Live ingestion consumer chain never restarted after todo 306/363's gateway fix -- 211/231 symbols have zero new bars since 2026-08-12, ongoing today

## What

Todo 306/363 fixed `ib-gateway`'s missing `libgtk-3-0` library live on 2026-08-31 and confirmed
the container reachable again at `127.0.0.1:7497` -- but that fix only restored the gateway's
own API port. The actual consumer services that read from it and write bars were never
restarted, and are still down as of this session (2026-09-01, host uptime since 2026-08-13,
zero reboots):

```
indicagent-ibkr-provider.service     disabled, inactive/dead, ZERO journal entries ever
indicagent-provider-merger.service   disabled, inactive/dead
indicagent-bar-writer.service        disabled, inactive/dead
indicagent-bar-aggregator.service    disabled, inactive/dead
indicagent-bar-auditor.service       disabled, inactive/dead
```

(Compare `indicagent-feature-vector-pipeline`/`indicagent-api`, both `enabled` -- these five
are the anomaly, not the norm.)

**Live impact, verified against the DB:** `market_data_ohlcv` at `timeframe='1m'` for AAPL and
SPY both show `max(timestamp) = 2026-08-12` -- no live bars in 19+ days, continuing today, for
what is presumably most of the 231-symbol active universe. At `timeframe='1d'`, daily row count
per day cratered from 231 symbols (through 2026-08-10) to just 10 symbols from 2026-08-14
onward:

```
2026-08-10: 231 symbols
2026-08-14 onward: 10 symbols only (BNTX, COIN, CRWD, CTVA, DD, DOCS, DOW, ETHA, GEV, ODFL)
```

Those 10 are NOT getting live bars either -- they're the explicit `--symbols` list
`indicagent-nightly-backfill.service` passes to `infrastructure_run_historical_pipeline.py`
(a historical REST-pull backfill, not live streaming), and even that job is currently failing
with IBKR pacing/timeout errors on at least GEV (`ibkr.hist_pacing_error`, live in this
session's journal check).

**This directly contradicts the `project_ibkr_live_ingestion_stalled_2fa` memory's "RESOLVED
2026-08-31" framing** -- the gateway-reachability half was genuinely fixed; the
consumer-restart half was never done, so live ingestion has been silently down the entire time
since, not resolved. Corrected in that memory file this session.

**Why this matters beyond one stale memory line:** `.planning/STATE.md` and multiple project
memories describe the post-Phase-173 corpus recompute as "COMPLETE as of 2026-08-31" and route
the discovery-track sequencing (`statistical_factor_residual` Stage 3, todos 303/304/364, Phase
151 Waves 6-7) as unblocked on that basis. That recompute's completeness is about the
historical range it processed, not about whether the corpus is staying current -- and it
is not: every day this stays down is unrecoverable real-time data loss for ~211/231 symbols
(Renaissance data-retention principle: never drop data that could contain signal -- this is
data never even arriving, the same failure mode one level upstream).

## What to do

1. Confirm `libgtk-3-0` is still present in the running `ib-gateway` container (`docker exec
   ib-gateway dpkg -l | grep gtk`) and the container is still accepting connections at
   `127.0.0.1:7497` before restarting anything downstream.
2. Re-enable and start the 5 services in DAG order (`_DAG_ORDER` in
   `services/service_auditor.py`): `indicagent-ibkr-provider` → `indicagent-provider-merger`
   → `indicagent-bar-writer` / `indicagent-bar-aggregator` → `indicagent-bar-auditor`.
3. Verify live: `market_data_ohlcv` `max(timestamp)` at `1m` advancing again for a broad sample
   of symbols (not just the 10-symbol backfill subset), within one polling cycle.
4. Investigate why `nightly-backfill`'s `GEV` pull is hitting `ibkr.hist_pacing_error` --
   possibly contention with the now-also-running live provider once it's back up, or a
   pre-existing pacing-limit issue independent of this todo; don't conflate the two root
   causes.
5. Once confirmed stable, land todo 363's durable Dockerfile fix so this exact chain of
   failures (gateway wedge -> live fix -> consumers never restarted) can't repeat silently on
   the next container recreation.
6. Re-run this session's `statistical_factor_residual` Stage 3 universe fetch after ingestion
   has caught up -- it currently returns 0/231 symbols with complete daily history over the
   trailing 2000-day window because of this gap, not because of any Stage 3 script bug.

## References

- `project_ibkr_live_ingestion_stalled_2fa` memory -- corrected this session, see its
  "Follow-up finding" section
- `.planning/todos/pending/363-ib-gateway-libgtk3-fix-not-durable-across-recreation.md` --
  sibling gap, same incident family, different half of the problem
- `services/service_auditor.py` -- `_DAG_ORDER`, canonical service registry
- `scripts/analysis/statistical_factor_residual_stage3_ic_falsification.py` -- where this was
  found (universe fetch returning 0 symbols)
