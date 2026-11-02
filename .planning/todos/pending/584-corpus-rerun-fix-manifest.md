---
status: pending
priority: P0
filed: 2026-11-01
source: lead orchestrator (indicagent-4f), owner sequence 2026-11-01: data -> all fixes -> corpus rerun -> ensemble research
---

# Corpus rerun: the one list of fixes that must land before the feature recompute

## Decision (2026-11-01 23:10Z)

The 186-26 output on pin `92e588385` carries known stored-value defects (564 `hma_slope_z` is a
0.0 fill on every 1d row; 583 HMM NULL on whole names; 474 neutral fills where the quantity is
undefined). It cannot be swapped in by 186-27, so the corpus is recomputed once more at a new pin.
Stage 2 was paused at 650/1,252 intraday names (kill-and-resume safe; command and env in
`data/scratch/186-26/`) so the intraday screen could run on finished output and no more compute is
spent on superseded rows. Fixes land on main now: the pinned run tree is a separate worktree, so
the "wait for the kernel-edit window" constraint no longer applies.

One pin move, one rerun. Every item below that changes a stored value lands before the pin moves;
anything found after the pin moves waits for the following rerun.

## Batch (stored values change)

| # | Item | Source | State |
|---|---|---|---|
| 1 | `hma_slope_z` NaN while the slope history is short; parity golden updated | 564 | landed 20c1dcddc (shared helper: the cache and macro/beta z-scores are NaN in warmup too) |
| 2 | 1d applicability (design D1): intraday-session columns declared out of scope (NaN by declaration); VP/structure group decided per column | 564 done-when 2 | open |
| 3 | HMM whole-name NULL (D6): stale-volume cause fixed by the rerun; trend K per timeframe from the preregistered K experiment; `hmm_vol_prob_elevated` retires | 583 | measured (dc); K experiment running |
| 4 | Undefined is NaN (design D1) in kernel fallbacks; genuine zero states keep 0.0 and are declared (option 2; `no_fill` is an invariant, not a preference) | 474 | decided, open |
| 5 | Macro inputs: no fabricated zero without a cross-asset record; previous closes tracked before the first record | 463, 464 | landed: macro.py aee2404d9 (82); the streaming cache (vix, yield, TIP/HYG, spread correlation, flight quality), the legacy FeatureVector macro fields, the two macro products and the betas (`float \| None`, NaN is None) landed 2026-11-02 (02); shared `_z_or_nan`/`_corr_or_nan` in `_primitives.py`; parity golden regenerated from stored inputs (synthetic: ten macro columns; real 1d: `vix_z`, `sb_corr_z`, `vix_reversion_product`, early rows 0.0 to NaN). Unblocks item 8 |
| 6 | Intraday screen findings (D5): retire the universe-dead session columns; fix the intraday defects | this todo | screened 2026-11-02, open |
| 7 | Delete list after migration 543 (dropped-volume path, `volume_reset`, APR key retire) and the config field rename | 564 same-batch | landed 17cfe233b (migration 555 applied live; the field is deleted, so the rename is moot) |
| 8 | Add-list per design D2 (558's eight rows); never-computed `rank_z` registry rows retired | 558, 421 | open |
| 9 | Pilot gate tool (design D3) | this todo | in progress (indicagent-dc): G1-G3 and `--pilot` written in `scripts/ops/ops_feature_column_screen.py` (working tree, not yet through /simplify, /review and the full suite); G4 and G5 not started (sibling script); APR seeds and the 30 pilot names applied live and committed as migration 557 (names chosen from live data, how in the migration header); first stored-output pilot run, 1d only: 22 of 27 names judged, G1 54 columns, G2 227 and G3 684 cells fail, which is calibration data for the two tolerances, not a verdict |
| 10 | Calendar start 2000 (`_PMC_RANGE_START`); the 41 newly failing names backfilled or named holds | 564 same-batch, owner restart conditions | landed 2026-11-01 (data lane); the 41 are named verdict-gate holds for this rerun, see below |
| 11 | Proven-span start per name (design D4), closes 532: names held only for early-history holes (the 41 from item 10, AAOI, AGL, ACMR, ADPT and the like) enter the rerun from their proven start | 532, item 10 | landed 2026-11-01 (data lane), ledger E19; 189 of 205 failing names return, all 41 |
| 12 | Research guard contradiction: `research/guards.py` allows a leading NaN-volume run that `kernel_source` now refuses; one rule (refuse), `repro_frozen` bit-identical | item 1 finding 5 | open |

Out of the batch (no stored-value change, or a different path): 475, 473, 582.

Calendar start: the owner's restart conditions (STATE.md, "Decisions waiting on the owner") name
calendar start 2000 as part of this batch, so `_PMC_RANGE_START` moves to 2000; the 41 names that
fall below coverage at the 2000 era become named holds or get their 2000-2004 holes backfilled
first (data lane).

Item 10 disposition (data lane, 2026-11-01, indicagent-82). `_PMC_RANGE_START` is 2000-01-01, so
`first_session("NYSE")` and the 1d session_coverage era start at 2000-01-03. No per-name proven-span
start exists: the rebuild's `series_start` is the first loaded bar, and `session_coverage` anchors at
max(first bar, era start), so a hole after the first bar fails the name (todo 532 is the verdict-
definition change, a methodology-ledger entry). A `bar_hold` row is the wrong tool for the 41: the
daily stage skips a held name whatever the scope, which would also stop the backfill's results
reaching it. The disposition is the existing gate: at the next audit the 41 fail session_coverage
at the 2000 era, the verdict gate excludes them from this rerun and names them, and the list is
`191-SESSION-COVERAGE-ERA-2000-NEWLY-FAILING.tsv`. Measured on live data: every missing 2000-2004
session is name-specific (0 of 986 distinct dates are vendor-wide); for 39 of the 41 no vendor holds
a raw row for the missing dates; AIZ (21) and PAR (31) have Tradier rows that canonical does not
select, which is the D-191-Q policy (1d before 2016 is IBKR alone; Tradier is not a source, and its
consolidated volume is a different basis), not a selection defect. Follow-ups: (a) a 1d
2000-01-01..2004-12-31 IBKR pass for the 41, queued behind the pre-2016 campaign once the history
farm is live (fetch depth today is about 2006, so these dates were never requested); picked up by
the next rerun; (b) the per-name proven-span start (denominator and panel start declared per name,
the first session after the last pre-2005 hole), which closes todo 532 and goes through the
methodology ledger.

Owner restart conditions this rerun must also meet: all timeframes, including the 229 D7-hold
names and the 16 recent listings; phase 191 plans 22 and 23 (done); the 1d gaps of todo 566; a
fixed, written universe.

## Design (lead, 2026-11-01)

### D1. One null rule for every stored column (items 2 and 4)

Today each kernel module picks its own convention for "undefined": VP returns 0.0 and 0.5, SR,
sweep and pool return 0.0, swing and session levels return None. A reader cannot tell a measured
zero from a missing value. The rule that replaces them:

1. A stored value is a measurement or NaN. NaN has exactly two meanings, and the registry tells
   them apart: not applicable on this timeframe (declared, rule 3) or undefined at this row
   (warmup, no object exists, a refused fit).
2. 0.0 is stored only where zero is the measured state: event flags and counts over a fully
   observed window (`sweep_detected`, `in_lvn`, `price_in_value_area` where the value area is
   defined, `sr_level_count`, `pool_count`, touch counts). The distance, strength, age, velocity
   or position of an object that does not exist is NaN. "Bars since event" with no event in the
   observed history is NaN (right-censored), never 0.
3. Timeframe applicability is declared once, on the kernel: `Kernel.not_applicable:
   Mapping[str, frozenset[str]]` (output name to the timeframes where it is undefined by
   construction; amended 2026-11-02 because `minute_of_hour_*` is undefined on 1h, not only on
   1d). `compute_kernels` writes those
   outputs as NaN on those timeframes in one place, and every in-kernel `tf == "1d"` suppression branch
   (`_NEUTRAL_VP_EXTRA`'s 1d path, `_SESSION_LEVELS_DAILY_SUPPRESSED`, the calendar session
   flags) is deleted. The registry exposes `applicable_outputs(tf)`; the S0 read (184) and the
   column screen consume it, so a declared column is excluded, not "dead".
4. `Kernel.zero_is_state: frozenset[str]` names the outputs where rule 2 allows 0.0. A
   registry-wide unit test feeds each kernel a series where no object exists (flat price,
   too-short history) and asserts every output outside `zero_is_state` is NaN.

5. A history-dependent statistic appends to its history only values computed over their own full
   declared window (no realized vol from one return, no correlation from two), and a z-score of
   a zero-spread window is NaN, not 0.0. The short-history defaults (`_hurst_rs` 0.5,
   `_shannon_entropy` 1.0, `_garch_ratio` 1.0, `_adx` 0.0 and the matching cache defaults
   before the first refresh) are NaN. Source: item 1's implementer findings 1 to 3, 2026-11-02.
6. `hma_slope_z` is `not_applicable` on 1d: its z-score window is 252 refreshes of 30 rows,
   longer than any daily series. The intraday definition stands.

Scope of `not_applicable` on 1d: the session-anchored VP fields, the session-time and killzone
columns (`hour_of_day_*`, `minute_of_hour_*`, `in_ny_session`, `in_london_kz`, `in_overlap`,
`power_hour`, `session_time_pos`, `opening_range`), the overnight and Asian session distances,
the intraday return divergences, and the AMD phase family. A column that is constant on 1d
without being a session concept (`sweep_detected`, `manip_strength`, `hmm_vol_prob_elevated`)
is investigated, not declared away: if it cannot fire on a daily bar by construction it is
declared; otherwise it is a defect.

### D2. The add-list rides this pass (item 8)

558's eight-row add-list (decided 2026-11-01 with its spec pin-downs) enters as registry
`candidate` rows in this batch: the owner's rule is that new columns ride the next pass, and this
is it. The three never-computed `rank_z` rows retire. `redundancy_group` is filled after the
rerun from measured correlations.

### D3. The pilot gate: catch the next defect in a pilot chunk, not after a corpus pass

The 564 and 583 defects share one shape: a column whose first finite row comes far later than
its declared memory, or never. The gate measures that directly. It extends
`ops_feature_column_screen.py` (same single grouped pass, two more aggregates per column) and
runs on a pilot chunk at the new pin, before the full rerun:

- G1 dead columns per (tf, name): any dead column outside `applicable_outputs(tf)` fails.
- G2 warmup gap per (tf, name, column): first finite row index minus declared
  `feature_memory_bars`; a gap beyond tolerance fails (this is what would have caught
  `hma_slope_z` at 7,560 rows and HMM on AAPL at 5,470).
- G3 fill audit: the exact-0.0 share of post-warmup rows per column, outside `zero_is_state`;
  a share above tolerance fails for review.
- G4 causality: the existing `causality_probe` on pilot real data at three truncation points.
- G5 determinism: two pilot units computed twice, bit-identical.

Pilot set, about 40 names over all four timeframes, chosen to break things: SPY and two other
ETFs, AAPL, MSFT, HON, SCCO (583), KO, JPM, XOM, five of the 16 recent listings, five D7-hold
names, five thin names, a volume-basis-seam name, a spin-off, and one name with a pre-2016 IBKR
5m segment. The pass fails loudly; nothing launches on a red gate.

### D4. Proven-span start (item 11)

A hole in early history is missing depth, not a defect in the name; it becomes a correctness
problem only where a rolling window spans it. Excluding the whole name throws away its clean
later decades and tilts the universe toward names with complete early data. Rule: a name's
proven start is the earliest session `s` at which the existing session-coverage verdict over
`[s, last session]` passes its threshold. The verdict anchors there instead of at
`max(first bar, era start)`; the rebuild computes from that start and the panel declares it.
The start depends on bar presence only, never on returns. It is recorded per name with the
verdict, and the change is a methodology-ledger entry. The 2000-2004 backfill for the 41 moves
a proven start earlier in a later pass; it never blocks this one.

### D5. Intraday screen findings (item 6; 650 names, report `logs/feature_column_screen_20261102T002227Z.json`)

Retire (registry `deprecated` through `ConceptRegistryService`, kernel outputs deleted): columns
that cannot carry information on any name in the universe, because the bars are US equity
regular-hours bars. `asian_session_high_dist_atr`, `asian_session_low_dist_atr`,
`in_london_kz`, `amd_distribution_direction`, `amd_manipulation_detected`, `manip_strength`
(FX and futures killzone concepts), `ret_div_1m_5m` (no 1m bars), and `overnight_high_dist_atr`,
`overnight_low_dist_atr`, `overnight_range_pct` (populated on 81 of 650 names on 5m only where a
vendor served extended-hours bars: a feature that exists by vendor accident is a hidden bias).
Deleting beats declaring: a column re-enters when an asset class that has the session joins.
`amd_phase` is checked: if it is a function of time of day only it duplicates
`session_time_pos` and retires too.

Defects (fix in this batch):
- `hmm_vol_prob_elevated` constant on about 643 of 650 names on every timeframe: the elevated
  state is never assigned (label mapping or gate); goes with item 3.
- HMM state columns NULL on 34 (15m), 21 (1h) and 45 (5m) whole names: item 3's measurement
  covers intraday too.
- `ret_div_1h_1d` NULL on 5m and 15m, `ret_div_5m_1h` NULL on 15m and 1h, where the
  higher-timeframe inputs exist.
- `ctf_vwap_align` constant on 89 names at 1h (474's VWAP-filled-with-close path is the
  suspect).
- `sweep_detected` constant on 496 names at 1h and 63 at 15m: rare event or defect; measured
  against the 5m rate before deciding.

Declare (D1 rule 3): `minute_of_hour_*` on 1h.

### D6. HMM coverage (item 3; measurement by indicagent-dc, 2026-11-02)

1d, 1,314 names: 873 at least half written, 247 under half, 194 none. Two causes. (a) 104 of the
194 are fallback-kind names whose volume the tradeable view nulled before migration 543; on
current bars they write in full (HON 5,491 bars), so the rerun fixes them. (b) 337 non-fallback
names are refused by the occupation gate: 4,036 of 5,260 segments refused as
`degenerate_occupation`, every segment converged (0 at the n_iter cap, so todo 226 does not
explain it), and 813 of the 1,371 lowest occupation fractions are below 0.001 (a state never
used), not near misses at the 0.05 floor.

Decision: the 0.05 floor stays (a never-used state is a degenerate fit; lowering the floor would
write labels from it). The trend K = 5 came from a BIC study on 5m data of four ETFs and is
applied to every timeframe; todo 478 found the same stranding for the volatility family at
K = 3 on 1d. K becomes per timeframe (`feature.hmm.n_components.<tf>`), chosen by an experiment
with its rule fixed before the run: K in {3, 4, 5}; 1d on the 337 refusal names plus 100 fully
written names drawn with a fixed seed; 1h and 5m on 40 names with a fixed seed; per timeframe
the K with the lowest refused-segment share, ties within 2 percentage points to the smaller K.
The choice depends on fit validity only, never on returns; methodology-ledger entry with the
table.

`hmm_vol_prob_elevated` retires: with the volatility family at K = 2 (todo 478) the label map
never assigns the middle label, so the column is 0 by construction.

### Sequencing

Implementers work one at a time per shared file: items 1 and 7 (running) touch `registry.py`,
so D1 plus D5 (items 2, 4 and 6, one implementer: the same kernels) starts after they land. Item 5 (`macro.py`) and the add-list's new kernel
module (item 8) do not collide and run beside them. Item 3's fix waits for the 583 measurement.
The D3 gate tool is independent and is built now.

## Done when

1. Items 1-12 landed on main, each through /simplify, /review and the unit suite; `repro_frozen`
   bit-identical where research or statistics moved.
2. The pilot chunk at the new pin passes gates G1 to G5 (design D3) on every timeframe.
3. The rerun is launched at the new pin (1d then intraday), and 186-27 proceeds on its output.
