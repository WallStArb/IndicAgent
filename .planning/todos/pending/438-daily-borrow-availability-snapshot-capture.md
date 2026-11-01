

## Phase 185 revision 2 (2026-09-26)

Absorbed into phase 185's D8 capture job (spec revision 2): delisting check, holdings snapshots and borrow snapshots run as one daily job with one writer. Still start it first; every unrecorded day is lost.

## Standalone again (2026-09-26)

The owner descoped phase 185's D8 (forward survivorship capture), so this is no longer part of a
shared capture job. It is still worth doing on its own: borrow availability is live-only at IBKR,
and the short side of any book needs it (unified design 9.3). One small daily job with a
completion metric, so a missed day is heard.

## Status 2026-10-31 (PM, indicagent-9f): built and validated

The daily capture is built and verified against the live gateway. `services/borrow_availability_capture.py`
(BaseBatch oneshot, job `borrow-availability-capture`) -> `borrow_availability_snapshots`
(hypertable, migration 549), provider mechanics in `IBKRProvider.fetch_borrow_snapshots`
(tick 236 only: tick 46 is not legal for STK on gateway 1045.1, error 321 verified
2026-10-31; `shortable` is a generated column from `shortable_shares > 0`). Universe
`get_active_contracts(dimension="backfill")`, deliberately not configurable; batch mechanics
APR-backed (`infra.borrow.batch_size/pause_s/wait_s`); client id 46 (fetcher family is 40-42,
probe 44). Smoke 2026-10-31: 25 asked, 24 answered (NVDA 226.8M shortable shares), 1 asked-
but-unknown stored NULL. Units in production/systemd, installed 2026-10-31, timer 20:30 UTC
daily with Persistent=true. /simplify ran as four review agents (reuse, simplification,
efficiency, altitude); every finding applied (batch gather qualification, generated column,
flat three-stage execute, load_apr_dict_async, Settings host/port, format_iso_ts, no second
counter, generated-column docstring truth); full unit suite green except concurrent sessions'
in-flight files (93's 538 watchdog tests, b0's unlinked 574). Done-when complete once the
first full-universe timer run lands (1,529 names, about 10 minutes) and a missed day is
auditable from `job_completed_total{job="borrow-availability-capture"}`.
