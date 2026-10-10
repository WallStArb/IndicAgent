# Alpaca 5m admission build (todo 521)

Author: Brandon with Claude Code (session, 2026-10-09)
Status: green-lit by the owner 2026-10-09; plan gates the build
Amendment 2026-10-10: the 2026-10-10 audit found the T2 loader's drop
categories (stored-held, extended-hours) hit the floor instead of persisting;
81.7M rows from the phase 2 run survive only in scratch. Capture/authoring
rules and the fix are todo 528 (`docs/plans/2026-10-10-raw-capture-enforcement.md`),
which supersedes this plan's scratch-disposition paragraph: deletion is gated
on 528's backfill, and T4's nightly leaf archives extended rows rather than
dropping them. Alpaca 1d raw capture joins the nightly under 528's R1 (it
never authors).
Informed by: the executed pilot
(`docs/plans/2026-10-09-alpaca-integration-pilot.md`), the data layer
integrity design amendment of the same date, the 189 probe verdict (todo 523,
IBKR 5m ceiling confirmed at ~180-day asks), and the 189 lane's design
dependencies (indicagent-7a, recorded in the todo file).

## Council verdicts that shaped this plan

1. **No new API client in this build.** The scratch pull
   (`scripts/research/alpaca_depth_scratch_pull.py`) is the fetcher of record
   for the campaign; its `requests.jsonl` log is the provenance artifact and
   moves to `logs/alpaca_depth/` beside the bars. The nightly-verifier client
   that writes observations natively is task T4, built only when that consumer
   exists.
2. **First writer stays.** Existing IBKR 5m bars are immutable. Alpaca fills
   only sessions IBKR lacks (the 2016+ span for the drain names, and C8
   single-day gap days). There is no span arbitration and no 5m restatement
   machinery. Overlap is D7 evidence, never a writer.
3. **Diagnose before load.** The three C3 5m names and EWT are diagnosed
   first; they are either explained or excluded, before any canonical write.

## Scope

Admit Alpaca 5m (2016-01-01 forward, `adjustment=split`, RTH-window aggregates
only) for **all 1,529 active names** into `market_data_ohlcv` through the
existing ingress write contract, then re-derive the grid and re-run D7.
Owner ruling 2026-10-09: all active names are intraday scope as of today;
the 233-name admission boundary is overruled. Scratch data:
`data/scratch/alpaca-pilot/depth/` (phase 1, the 233 intraday names) and the
chained full-universe pass (`depth_1502/`), which is now admission-eligible
supply rather than scratch-only optionality.

Admission precedes promotion: `instruments.compute_eligible` is still true
for 233 names, and promoting the other 1,296 to intraday scope goes through
the onboarding SOP / integrity verdict gates (the 185-41 pattern), which need
each name's 5m present first. Sequence: phase 2 pull -> tolerance migration
-> load all names -> derive -> D7 full sweep -> promotion wave (separate
task, not this build).

**Sequencing (final, 2026-10-09):** no hold. The 189 lane's interim
head-illusion concern was retracted after a verified dry run
(21f515c25, 0687a5d14): the queue planner already plans heads correctly
(gap = min(depth_days, proven_days, floor) - actual, where proven_days is
the name's deepest stored series — 1d, which stays IBKR-authored and this
build never touches — and floor is max(provider_head, empty_history)). The
"163 names" mass was differing vendor floors (1d from 2000, 5m from 2006),
not missing data; an Alpaca 5m load changes neither proven depth nor floor.
Phase 2's all-names canonical load therefore proceeds on its own timeline
after the phase 2 pull, under the standing rules: first-writer-stays
governs the overlap, IBKR's backfill skips stored slots. The owner's
"depth measured correctly per TF" directive survives as todo 526 (P3, the
small per-TF provider-head PK migration, 189-11), independent of this
build.

Out of scope: 1m storage (no consumer), the registry promotion wave (its own
task, gated on this build's D7 sweep), the execution client (separate build),
live streaming.

## T1: Diagnose the four outliers (blocks everything)

- DBC, UUP, PFE: C3 5m close basis failed on the stored side (68.7%, 57.4%,
  39.6% pass at 1 bp; none has a split in the window, so this is not the C1
  effect). Determine whether the stored IBKR 5m bars, the Alpaca bars, or the
  slot alignment is the outlier, using Massive (same-upstream reference) as
  the tiebreaker where the recent window allows.
- EWT: 1d pass rate drops to 91.5% under `adjustment=split`; characterize the
  residual.
- Outcome per name: explained (admit), stored-side defect (route to the
  bar-quality path, not this build), or unexplained (name excluded from T2,
  stays open).

## T2: Registry, policy, and the load path

- `SOURCE_ALPACA = "alpaca"` in `src/intelligence/bars/sources.py`; canonical
  source value only; no policy-semantics edits.
- `bar_source_policy`: a 5m default row (primary `alpaca`, ingress `direct`,
  evidence = the pilot doc), closed-span semantics unchanged; per-name hold
  rows for any T1 exclusions. No 1d policy change of any kind.
- Loader: scratch parquet -> ingress write contract (`ohlcv_load` row per
  series, replaced values to `ohlcv_revision`), RTH mask (09:30-16:00 ET)
  applied at load, `no_fill` respected (missing stays missing). IBKR-held
  sessions are skipped, never overwritten. The 15-minute recency hold means
  the last partial day comes from the nightly leaf or the next campaign run,
  never from a partial pull.
- **Slot convention pin (blocking; from the 189 lane's review, verified
  against both data sides 2026-10-09):** stored IBKR 5m is bar-OPEN stamped
  on session slots 09:30..15:55 inclusive (78 slots full day, 42 half days:
  09:30..12:55; corrected from 38 per the 189 lane's review),
  zero-volume slots retained. Alpaca's 5m bars verified the same convention
  (open-stamped, same session set). The loader matches bars by open stamp
  onto that grid, never fabricates a slot in either direction (a slot the
  feed does not provide stays missing), and retains zero-volume bars the
  feed does provide, so slot_coverage and the derivation's session mask read
  an Alpaca-filled session exactly like an IBKR one.
- **Expected-slot source pin:** the expected-slot count per session comes
  from `src/core/market_calendar.py` (early closes are 42-slot days), never
  a hardcoded 78; the loader and D7 read the same calendar function.
- **Component reuse pin:** T2's campaign loader and T4's nightly leaf share
  one load component (one slot-rule implementation, one RTH filter, one
  write-contract call); only the fetch source differs (scratch parquet vs
  API increment). A second loader implementation is a defect.
- **Spinoff-class monitoring note:** the 185-52 spinoff/adjustment-basis
  names (HON, LEN, IBM, O, and the rest of the restated-basis set) are where
  the tapes historically diverge (IBKR refetches its span after splits;
  spinoff adjustments are not in Alpaca's `adjustment=split`). Their
  `alpaca_basis` verdict rows get reviewed first at the D7 sweep; divergence
  is contained by first-writer-stays, so no new machinery, only attention
  ordering.
- **Phase 2 scratch disposition:** the `depth_1502/` pull persists until the
  IBKR drain completes (todo 523 hold), then loads through the same
  component; row counts reconcile against `ohlcv_load` at that point. It is
  never deleted before its `ohlcv_load` rows reconcile.
- **Coverage-ledger pin (189 single-writer fence):** each session's bars,
  its `ohlcv_load` row, and its `ohlcv_coverage` update land in the same
  transaction (`_intraday_persist.py` is the pattern). A lagging ledger
  would make the IBKR queue re-plan Alpaca-filled sessions as gaps, which
  under first-writer-stays becomes wasted overlap re-asks.
- Provenance: the campaign request log archived to `logs/alpaca_depth/`;
  row-level `ohlcv_request`/`ohlcv_observation` capture begins with T4's
  leaf and is recorded as a known gap in the registry's Alpaca row until
  then (campaign loads are one-time; the nightly leaf makes them continuous).

## T3: Derive, verify, gate

- Grid stage (`--stage grid --changed-only --apply`) over the loaded names;
  15m/1h re-derive from the stored 5m per the existing single-writer fence.
- D7 full run: session_coverage, slot_coverage, digest_fresh, grid_parity,
  stray_vendor_rows, plus the new vendor-agreement check (below).
- New D7 condition: `alpaca_basis` on names holding both tapes in an overlap
  span (2026-09 onward, every dual-tape name): sampled close basis between stored IBKR
  and stored Alpaca 5m, APR tolerance, flag-only (never a writer). This is
  the second-tape extension the 189 lane asked for, in evidence form.
  Pins from their review: the sample rule is deterministic and written here
  (first stored bar of each overlap session), the tolerance APR row is dated
  before the first apply, and verdict rows land in `integrity_monitor` like
  every other D7 condition, so the gate trail exists even though the check
  is flag-only.
- Promotion/verdict gates read the results as-is; no gate code changes.

## T4: The nightly leaf (separate follow-on, its own plan)

Alpaca client in Ring 0 (credentials isolated like ib_async), nightly
verifier pass after the IBKR backfill, native observation capture, T+1
morning window (outside the 15-minute hold, feasible on Basic rates).
Execution client stays a separate build.

## Acceptance (all must hold)

- Existing boundary tests pass unchanged
  (`test_market_data_ohlcv_writer_boundary.py`,
  `test_market_data_ohlcv_no_synthetic_fill.py`,
  `test_bar_write_no_first_write_wins.py`).
- Stored-row basis on the 22 pilot names at or above the pilot C3 level,
  with the T1 outcomes documented per outlier.
- D7 verdicts pass on every admitted name; digests fresh; grid parity holds.
- Zero writes outside the write contract; `ohlcv_load` rows reconcile with
  scratch row counts.

## T1 results (2026-10-09, all four resolved; none a data defect)

- **DBC, UUP, PFE (5m close basis): half-tick tape differences.** With the
  failures separated by tick size (half of a 1-cent tick in bp of mid), 377
  of 378 DBC failures, 674 of 675 PFE failures and all 444 UUP failures sit
  inside the half-tick band (1.9-2.3 bp on $22-28 instruments); the residue
  is one isolated slot per name at 1-2 ticks. The pilot's 1 bp C3 criterion
  was tighter than the instruments' own tick size. Resolution: the admission
  and D7 tolerance is tick-aware, `max(alpaca_basis_tolerance_bp,
  half-tick/mid)`, with `threshold.bar_integrity.alpaca_basis_tolerance_bp`
  seeded at 1.0 `[pilot-measured 2026-10-09]`; the tick term is a derived
  value (APR-exempt). All three names pass the >=99% criterion under it and
  admit. Pins from the 189 lane's tolerance review: **mid** is defined as
  `(stored IBKR close + stored Alpaca close) / 2` on the sampled slot, so
  "half-tick in bp of mid" is unambiguous once two tapes exist; and the tick
  size comes from `get_tick_size` (`src/config/settings.py:648`, the
  active-contracts cache, IBKR minTick), never inferred from stored bars,
  which would be flimsiest exactly for the sparse names the check most needs
  to be fair to.
- **EWT (1d split-adjusted residual): one corporate action, one boundary.**
  215 of 230 failing sessions are all of 2016 at exactly 2.0x: a single 2:1
  action whose adjustment boundary Alpaca draws at 2017 and the stored
  convention does not draw. Both tapes are internally consistent;
  first-writer-stays prevents any mixing, and the `alpaca_basis` overlap
  check flags any live manifestation. EWT admits with this note.

T2's load gate now needs only the dated APR tolerance row (migration at T2
start) and the 189 lane's T2 re-check, already given conditionally on that
row.
