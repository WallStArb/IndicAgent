---
gsd_state_version: 1.0
milestone: v3.5
milestone_name: Unified Research Pipeline
status: in_progress
stopped_at: "v3.4 closed and v3.5 opened 2026-09-26; phase 183 plan 10 in progress (other session)"
last_updated: "2026-09-26T21:00:00.000Z"
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

Current position only. History: git, `.planning/MILESTONES.md`, and the archived state at v3.4
close (`.planning/milestones/v3.4-STATE.md`). Don't stack dated narrative here; replace stale
bullets with current facts.

## Strategic plan (read this first)

- **The design:** `docs/plans/2026-09-26-unified-research-to-production-design.md`, ADOPTED
  2026-09-26 with methodology-change-ledger E18. It owns the sequence (section 16). One pipeline
  from data to a frozen book; the old ensemble chain is deleted; costs never enter a test
  statistic but promotion needs positive net expectation; every look at the vintage is counted and
  selection is by Romano-Wolf StepM; each book gets its own forward span (feature books never
  before 2026-08-08, after 7 recorded holdout looks); raw data is permanent, derived data is cache.
- **Milestone v3.5 Unified Research Pipeline, phases 183-188** (ROADMAP.md). Alpha track first,
  in parallel with the build: E17 H0 battery -> attempts 1a-1c (todo 442); first-cut cost model
  (437); price-only daily families and `generated_family` on the 931 names (441, 423, 440). Build:
  186 (delete, drop, rebuild `feature_vectors`, refactor items 1-6) -> 187 (research core) -> 184
  -> feature books -> 188 (forward runner, capital tier).
- **Evidence rules:** E15 (book as the unit), E16 and E17 (timing statistic), E18 (counting,
  selection, promotion, per-book span). Until phase 187 lands, the phase 183 runner's M = 30
  accounting stays in force for any book test.
- **Research record:** `docs/research/construction-verdict-ledger.md` until phase 187 generates it
  from UCR. Check it before recommending a candidate.

## Current position (2026-09-26)

- **Phase 183** (other session): plans 01-09 and 11 done; plan 10 in progress. Family 1 evidence
  done (HAC t 13-19 gross, about 26x turnover per session, untradeable net at 1 bp); book_v1
  refused (E16 bias); E17 adopted, H0 battery gating real runs; family 2 registered.
- **Phase 185:** accepted, not planned. First stage D8 (delisting record, holdings snapshots).
  Todo 433 (IBKR history truncated at venue moves, P0) is owned here; verify-only fix merged.
- **Phases 186-188:** added 2026-09-26, not planned. Next planning step: `/gsd-plan-phase 186`.
- **Quick, independent todos:** 438 (borrow snapshots; every unrecorded day is lost), 443
  (exporter scrape cost, idle-in-transaction timeout), 439 (write-once `oos_start`).
- **Universe:** 932 active; 931 `compute_eligible_1d`; 233 carry the intraday stack and
  `feature_vectors`. Lineage `config/universe/README.md`.
- **Data freshness:** features and regimes stale since 2026-08-10 (todo 411, now replaced by the
  phase 186 rebuild); live IBKR streaming down; nightly batch backfill refreshes OHLCV only.
  Check `max(timestamp)` before citing freshness.

## Open items that are not verdicts

- Todo 248 (HMM per-symbol lookahead): walk-forward fix built, not deployed; deploy with the
  phase 186 rebuild. HMM columns stay out of every family until then.
- Todo 372 (`Panel.sync_shift_null_p`): finding 1 fixed, lacks independent review; finding 2
  (`volume_z` diurnal detrending) untouched.
- N1 nonlinear combiner: structurally inconclusive; don't cite as pass or fail.
- Survivorship: every universe reads current state; phase 185 D0 bounds past verdicts and D8 fixes
  it forward.

## Process pointers

- `.planning/todos/PRIORITIES.md` is the sole todo priority source.
- The research ledger is the sole construction-verdict source.
- Methodology changes go through `docs/plans/methodology-change-ledger.md`.

## Key decisions (load-bearing)

- `HMM_RANDOM_STATE = 42`: changing it invalidates every regime-derived output.
- Executable returns only: `forward_returns.return_type = 'executable_open_to_open'`.
- `ON CONFLICT` for partial indexes on TimescaleDB: column list plus WHERE clause, not
  `ON CONSTRAINT`.
- Corpus pipeline: `--compute-only` silently skips every symbol if `backfill_status` is empty;
  seed it first (query in `.planning/milestones/v3.4-STATE.md`, "Corpus Pipeline Gotcha").
