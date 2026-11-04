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
| 2 | 1d applicability (design D1): intraday-session columns declared out of scope (NaN by declaration); VP/structure group decided per column | 564 done-when 2 | landed 2026-11-02 (Track A, indicagent-dc WIP resumed): `Kernel.not_applicable` mapping (amended rule 3; `minute_of_hour_*` on 1h is a data entry away for item 6), the batch path routes the cache-backed VP/session-levels/AMD kernels through `compute_kernels`, golden regenerated in its own commit; follow-up landed same day: `kernel_source` forwards `Panel.tf` as the per-row tf external, so research requests whose closure declares `not_applicable` outputs or reads tf directly run and gate on the panel's tf instead of refusing (pre-fix: loud `KernelSourceRefused`, never a default; `repro_frozen` bit-identical) |
| 3 | HMM whole-name NULL (D6): stale-volume cause fixed by the rerun; trend K per timeframe; `hmm_vol_prob_elevated` retires | 583 | landed 2026-11-04: trend K=3 uniform (migration 566, E20), `hmm_vol_prob_elevated` retired; 1d K=3 rule per 583 |
| 4 | Undefined is NaN (design D1) in kernel fallbacks; genuine zero states keep 0.0 and are declared (option 2; `no_fill` is an invariant, not a preference) | 474 | decided, open |
| 5 | Macro inputs: no fabricated zero without a cross-asset record; previous closes tracked before the first record | 463, 464 | landed: macro.py aee2404d9 (82); the streaming cache (vix, yield, TIP/HYG, spread correlation, flight quality), the legacy FeatureVector macro fields, the two macro products and the betas (`float \| None`, NaN is None) landed 2026-11-02 (02); shared `_z_or_nan`/`_corr_or_nan` in `_primitives.py`; parity golden regenerated from stored inputs (synthetic: ten macro columns; real 1d: `vix_z`, `sb_corr_z`, `vix_reversion_product`, early rows 0.0 to NaN). Unblocks item 8 |
| 6 | Intraday screen findings (D5): retire the universe-dead session columns; fix the intraday defects | this todo | retire landed 2026-11-03 (11 columns, migration 561); `ret_div` NULL on other tfs resolved as by definition (6a); `ctf_vwap_align` fixed as an absorbing anchored VWAP (6b); `sweep_detected` retired and the sweeps ATR gate removed (6c); row 6 is done |
| 6d | SMC ATR gates narrowed (bos_choch, fair_value_gap, order_blocks): an invalid ATR no longer wipes the outputs that do not divide by it | this todo | landed 2026-11-03 (golden first; invalid-ATR share measured in the 6d note) |
| 8b | Beta builders iterate common dates only (no stale-close 0.0 return on a gap day) | this todo | landed 2026-11-03 (golden unchanged; impact measured in the 8b note) |
| 7 | Delete list after migration 543 (dropped-volume path, `volume_reset`, APR key retire) and the config field rename | 564 same-batch | landed 17cfe233b (migration 555 applied live; the field is deleted, so the rename is moot) |
| 8 | Add-list per design D2 (558's eight rows); never-computed `rank_z` registry rows retired | 558, 421 | landed 2026-11-03: ten stored columns (kernels/residual.py, distribution.py, dividend.py), migration 559, rank_z concepts deprecated; `days_to_ex_dividend` deferred (no declaration time in `dividend_events`) |
| 9 | Pilot gate tool (design D3) | this todo | G1-G3 and `--pilot` landed in `scripts/ops/ops_feature_column_screen.py` (through /simplify, /review and the full suite); tolerances and the 30 pilot names are APR (migration 557); G1 and G3 tolerate the absent D1 registry declarations (`applicable_outputs`, `zero_is_state`) and the report says so until item 2 lands. G4 and G5 landed in `scripts/ops/ops_pilot_compute_gate.py` (commit 3c7d1b349: probe_registry over the compute's own kernel plan at three truncation quarters plus the bundle-readable acausal controls; double compute with bit-level digests; smoke SPY:1d 139 kernels, canary control caught, digests identical). Open: a pilot run at the new pin, then recalibration of the two tolerances from its gap and share distributions |
| 10 | Calendar start 2000 (`_PMC_RANGE_START`); the 41 newly failing names backfilled or named holds | 564 same-batch, owner restart conditions | landed 2026-11-01 (data lane); the 41 are named verdict-gate holds for this rerun, see below |
| 11 | Proven-span start per name (design D4), closes 532: names held only for early-history holes (the 41 from item 10, AAOI, AGL, ACMR, ADPT and the like) enter the rerun from their proven start | 532, item 10 | landed 2026-11-01 (data lane), ledger E19; 189 of 205 failing names return, all 41 |
| 12 | Research guard contradiction: `research/guards.py` allows a leading NaN-volume run that `kernel_source` now refuses; one rule (refuse), `repro_frozen` bit-identical | item 1 finding 5 | landed d003eb028 (2026-11-02 03:41; repro panels carry no volume so bit-identical is structural, and the empty research_run ledger means no book exercised the permissive branch - see the item-12 note) |

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

D5 design check against the live kernel registry (Track A read-only pass, indicagent-ea,
2026-11-02; the implementer's edit list, no code changed). 11 columns retire (the 10 listed plus
`amd_phase`, whose check resolves to retire):

- `calendar_session` (6 outputs): `in_london_kz` dies; `in_ny_session`, `in_overlap`, `power_hour`,
  `opening_range`, `session_time_pos` survive (all vary inside RTH bars; the screen retired only
  the killzone flag). Same edit: `_SESSION_OUTPUTS`, the compute row, the `_in_london_kz` helper
  and its factory import, the london-KZ APR hour seeds, and the declaration shrinks to five
  outputs (item 2's "six" note above becomes five).
- `session_levels` (16 outputs): the five in `_SESSION_LEVELS_UNDEFINED_ON_1D` die
  (`overnight_high/low_dist_atr`, `overnight_range_pct`, `asian_session_high/low_dist_atr`); 11
  survive (prior_session_* 3, `opening_gap_pct`, weekly pivot/R/S 5, `nearest_level_dist_atr`,
  `gap_filled`; none of those is on the retire list). The whole 1d declaration dies with the
  tuple, and with it the helper's tf=='1d' suppression block, the kernel's `tf` input and the
  compute's `constant_tf` read (no declared output remains, so the tf external is no longer
  required). `_sl_overnight_*`/`_sl_asia_*` state in `update_session_levels` goes unused with the
  five; the weekly/prior-session state it shares with the survivors stays.
- `amd_cycle` (4 outputs): all four die, so the kernel retires whole. `amd_phase` verified: a pure
  function of the bar's UTC hour plus the three APR hour bounds (`_amd_phase_ordinal`, smc.py),
  the same information basis as `session_time_pos` - it retires under D5's own check. The
  manipulation window (00:00 UTC through manip_end) does not intersect US regular-hours bars
  (13:30-21:00 UTC), which is the screen's constant-on-643 mechanism; the few non-constant names
  are the vendor-accident extended-hours set. Same edit: `_derive_amd_cycle`, the AMD KeyGroup,
  `_AMD_PHASE_*`, FeatureCache `amd_*`/`manip_strength` fields and the whole
  `update_overnight_range` mutator (its only readers; session_levels reads the separate `_sl_*`
  state), both replays in `services/feature_vector_pipeline.py`, and the `feature.smc.amd.*` APR
  seeds. Ordering: the 4b/4c zero_is_state list in item 4 must drop `amd_manipulation_detected`
  (retire lands first or 4c skips the AMD entries).
- `cross_tf_divergence` (3 outputs): `ret_div_1m_5m` dies (no 1m bars anywhere in the universe);
  `ret_div_5m_1h`/`ret_div_1h_1d` survive (their NULL-on-lower-tf findings are defect fixes
  above, not retires). Same edit: the `ext_ltf_last_log_ret` external build (~feature_factory.py
  1395-1411) and the 1m aggregation feeding it; the kernel's tf input stays for the two survivors.

Knock-on sweep for all 11:

- schemas.py `FeatureVector`: drop the 11 fields; the persistence `.index()` slices
  (feature_vector_persistence.py) self-adjust at import, the `in_london_kz` references there die
  with the field. The pydantic copies in `I3Structure`/`SMCContext` are v2.x-remainder surfaces
  (reachable via state_serializer/bar_history_seeder); verify that path's liveness before touching
  it, else leave the remainder alone.
- feature_factory.py: FEATURE_GROUP rows, build-site params and routing, the two docstrings
  naming the columns.
- tests: `_UNGUARDED_PASSTHROUGH` in test_feature_factory_batch_parity.py drops `in_london_kz` or
  the schema-tie test fails; the golden fixtures lose 11 columns (regen, own commit).
- DB `feature_vectors` columns: derived cache; stop writing, drop only after the rebuild's summary
  card per the data policy, no same-day DROP.
- Registry: `deprecated` through ConceptRegistryService per the row; deleting outputs from the
  KERNELS tuples rides the same edit (`not_applicable` is validated as a subset of outputs).

Declarations: `calendar_cycles` gains 1h for `minute_of_hour_sin`/`minute_of_hour_cos` only. The
mapping is output-keyed (`undefined_on` returns {output: {tf}}), so those two become {"1d", "1h"}
while `hour_of_day_*` stay {"1d"}; on 1h bars the minute is constant :00, so the encodings carry
no information. The tf external is already supplied (calendar_cycles is declared on 1d today);
the 1h golden cases change in the same regen as the retire.

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

### Item 2 landed (2026-11-02, Track A; dc's WIP resumed)

`Kernel.not_applicable: Mapping[str, frozenset[str]]` (the amended rule 3 shape; the WIP's
`intraday_only` set was pre-amendment), validated as a subset of the kernel outputs;
`applicable_outputs(tf)` subtracts per timeframe. `compute_kernels` writes a declared output NaN
on its declared timeframes in one place, skips a kernel whose outputs are all declared there, and
refuses to schedule a declared kernel without the `tf` external (the `volume_basis` precedent; a
mixed-tf column refuses too). Declarations: `calendar_session` (six), `calendar_cycles` (hour and
minute encodings, 1d; the 1h `minute_of_hour_*` entry is item 6's to add), `rolling_poc`,
`session_vp`, `session_levels` (the five overnight/Asian fields), `amd_cycle` (four),
`cross_tf_divergence` (three).

The dc-era failing test had the wrong hypothesis: the batch path passes `tf` correctly, it never
ran the three cache-backed kernels at all (their outputs were not requested; the loop read
`_derive_*` off its own per-bar-updated cache). Fix: `_STRUCTURE_KERNEL_OUTPUTS` now carries
`SESSION_LEVEL`/`VP`/`AMD` outputs, the loop reads `_kernel_row(..., declared=na)` rows (the
per-tf declared set from `KernelRegistry.not_applicable_outputs(tf)`; a declared output reads
back None), the per-bar accumulator updates and the VP `tf=='1d'` neutral branch are deleted, and
the ten calendar/clock fields read through `_none_if_nan` (a plain `float()` read handed grid NaN
to `_guard`, which fabricated 0.0/1.0). The two call-site wiring tests now pin the kernel route;
the legacy per-bar `compute()` path still gives 1d neutrals (dormant, item 582). Golden
regenerated from stored inputs in its own commit: 18 changed columns on the four 1d cases only.
Item 9's G1/G3 can drop their absent-declaration tolerance. Simplify follow-up (same day):
`constant_value`/`constant_tf` moved to the contract layer (`compute_kernels` had re-implemented
both), the declared set drives the batch row reads instead of NaN-sniffing, and the wholly-skipped
kernel writes one shared placeholder array.

Item 4 landing 4a (D1 rule 5, same day): `_hurst_rs`/`_garch_ratio`/`_adx` return NaN on too-short
and degenerate windows, `_shannon_entropy` NaN on insufficient data but keeps a measured 0.0 for a
one-bin (point-mass) return window; the five `FeatureCache` regime defaults are NaN; the legacy
FeatureVector carries the five as `float | None` through `_missing_if_nan` (the item-5 macro
pattern; the v2 rebuild already writes NaN as NULL), and `momentum_trend_product`/
`reversion_hurst_product` become `_missing_product` `float | None` (a missing adx/hurst parent
propagates). The `_guard(hurst, 0.5)`-style fallbacks are gone; they had been fabricating all
five, `hma_slope_z` included, on every pre-refresh row. Remaining for item 4: 4b (zero-spread
z-scores/correlations and ratio denominators NaN; smc/vp_sr no-object fallbacks) and 4c
(`zero_is_state` declarations + the registry-wide no-object test).

Item 9 follow-up: the all-timeframe pilot run on the stored stage output (report
`logs/feature_column_screen_20261102T142626Z.json`, disk only) shows gate failures G1 1,935, G2 562,
G3 2,901 over 27/19/19/19 names judged on 1d/15m/1h/5m; those numbers predate item 2's declarations,
so G1 and G3 need a fresh read. Pilot names with no stored rows (APLD, CTVA, LQD) are reported
missing, as designed. Recalibrate the two tolerances on the first pilot run at the new pin; G4 and
G5 (sibling script) follow.

Item 4 resume state (Track A, 2026-11-02; 4a landed, **4b-1 LANDED** same day, 4b-2+/4c open).

**4b-2 GROUP 1 LANDED (Track A, 2026-11-03, 24bae0c41 + golden a77074136):** the 0/0 ratio
family. Kernels NaN where the window does not define the statistic, scalar + `_series_full`
twins identically: `updown_ratio` (no down bars), `realized_var_ratio` (degenerate slow
variance, sub-2 windows), `variance_ratio` (same), `hv_ratio` (bar 0, zero mean HV),
`intraday_noise_ratio` (warmup, net-zero session movement), `vol_acceleration` (no prior bar,
zero prior volume; zero CURRENT volume over positive prior stays measured 0.0). Build site: 9
columns `_guard(x, 1.0)` -> `_missing_if_nan`; schemas `float | None` (both policed by
`test_missing_routing_ties_to_the_schema_annotation`). Evidence: kernel-layer products
(`momentum_vol_regime_product`, `variance_ratio_momentum_product`) propagate the NaN
array-wise with no extra edit; a 2673-comparison randomized scalar/twin probe (random, flat,
zeros, zero-head, short inputs) shows exact NaN-placement agreement; the only value deltas are
pre-existing cumsum-vs-`np.var` summation noise (<=2.9e-08 relative) on a cancellation stress
case, formulas untouched. `/simplify`: one fix applied (dead `safe_prev` alias in
`_vol_acceleration_series_full` replaced by a masked `np.divide`); two altitude suggestions
skipped (boundary-wide NaN->None sweep at FeatureVector construction: out of scope, per-field
routing is deliberate and test-policed; shared `_ratio_or_nan` helper: abstracts only the
trivial half, the per-site degeneracy predicates stay anyway). `/review` subagent died on the
5h quota wall (resets 20:52 UTC 2026-11-03); the machine probe above is the review evidence.
**4b-2 GROUP 2 LANDED (Track A, 2026-11-03, ce7548847 + golden dc5c659c4):** the
oscillator/percentile family plus the three lead-ruled ratios. Kernels NaN where the window
defines no statistic, scalar + `_series_full` twins identically, finite formulas untouched:
mfi (cold, zero total flow; flat-tp positive-volume 0.0 stays measured), stoch_k (zero
range), bb_pct_b (cold, zero std), cci (cold, zero MAD), aroon (cold rows < period+1; a
flat FULL window keeps its measured 0.0: np.argmax first-occurrence picks the oldest bar and
up/down pick the same bar, so the oscillator is tie-break-invariant - verified before
landing, 4c declaration), price_percentile + vol_percentile (cold, all-equal window),
efficiency_ratio (zero movement, updown_ratio precedent), vol_range_ratio (degenerate bar;
NaN-aware window with recovery, `_cumsum_window_moments` precedent), vol_asymmetry_ratio
(cold, degenerate down-std; genuine std_up == std_down stays a measured 1.0, the
separate-verify outcome), range_position (probe extension: fabricated 0.0 on a flat range),
zero-range bar anatomy (body/upper-wick/lower-wick/close-position); vol_percentile joined as
a second probe extension (same all-equal convention as its ruled sibling price_percentile).
Build site: 23 columns `_guard(x, neutral)` -> `_missing_if_nan` (22 planned + the review
fix below), schemas `float | None`, tied by `test_missing_routing_ties_to_the_schema_
annotation`. The /review gate found one material bug, fixed before landing:
`up_vol_body_diff` (`up_vol_ratio_fast - body_ratio`) still routed `_guard(x, 0.0)`, which
fabricates 0.0 where a genuine measurement was stored before body_ratio went NaN; now
`_missing_if_nan` + `float | None` (a difference with a missing parent is missing; a
non-finite difference of finite inputs is impossible, so no `_guard_counted` tripwire).
Evidence: 6460-check scalar/twin parity probe (random, flat, zeros, zero-head, short,
degenerate-head; exact NaN placement, <=1e-08 relative on finite values); golden delta:
synthetic aroon_fast/slow, cci_fast/mid/slow, range_position, vol_asymmetry_z, real
vol_asymmetry_z only; full suite green. Gates: /simplify nothing to apply (cold guards
load-bearing, pinned eps kept); /review one finding, fixed and re-verified. The 24bae0c41
review debt was cleared first: 4 agents (2 CLAUDE.md compliance, 2 bug hunt), no findings.
GROUP 3 LANDED 2026-11-03 (a8, successor of the quota-dead worker; the dead WIP verified
complete and coherent, goldens independently regenerated bit-identical at 2fdd5efa2 before
any edit): the four event counters are right-censored - NaN when no event is known inside
the trailing window (rule 2), None through `_missing_if_nan` (build sites ~1990,
cold-start vector, schemas `float | None`); unknown event rows NEWER than the newest known
True censor the count, older unknowns leave it exact (lead ruling 15:35Z). Producer
symmetry (lead-approved): `_compute_extreme_move_events` emits float 1.0/0.0/NaN, NaN when
either operand is non-finite (NaN close, NaN-holding window), mirroring
`_compute_vol_spike_events`; sole consumer of the event series is the
bars_since_extreme_move kernel itself (no other reader in src/services/tests/scripts);
both producers feed the helper raw float events. /simplify substance: helper rewritten to
vectorized prepasses + scalar newest-True (824-case equivalence probe bit-identical, ~10x
measured); the retired window-1 literal also killed at both upstream `_series_last`/per-row
fallbacks (kept for bars_since_high/low/52w where the in-window extreme exists by
construction); migration 558 supersedes 288's saturating column comments (applied live).
Golden delta: only the four counters, all 17 cases. RE-PARK: item-8 pre-staged kernels
moved kernels/ -> features/_item8_staging/ (lead-authorized; sha256 identical before/after,
/tmp/item8_sha_*.txt) because the shared suite had been red at HEAD from registry
auto-discovery since ~15:00Z - six ownership/probe tests, stash-proof
/tmp/g3_head_verify.log; dag-invariants' walk reaches the staging dir but stays green;
item 8's wiring landing moves them back as its first step. Gates: /simplify (4 agents),
/review medium (5 findings: the producer asymmetry - fixed as the approved extension;
vacuous all-NaN bounds test; self-contradictory schemas block comment; stale DB column
comments -> 558; staging location - declined, the lead's ruled path), full suite green.
REMAINING in 4b-2 (successor starts here): 4c.
GROUP 4 LANDED 2026-11-03 (a8): all smc/vp_sr no-object fallbacks moved to None per D1
rule 2 through the fallback-dict nullable mechanism (fallback None entry -> KeyGroup
nullable -> none-mask column -> `_kernel_row` None -> builder `_missing_if_nan`):
sr_resist/support_dist + resistance/support strength/age (per-side: a side with no cluster
in-window is missing, not 0.0), poc_dist_atr/va_position/price_in_value_area/in_lvn (None
when no live session histogram, gate `va_exists`; va_position also None on zero-width VA),
ob bull/bear dist, ob_strength, ob_mitigation_pct, breaker_dist_atr, fvg dist/size,
sweep_strength/reclaim_velocity/bars_since_last_sweep (right-censored), bsl/ssl_dist_atr,
demand/supply dist/freshness (per-side), zone_friction_score (None only when NEITHER side
has a zone), bos/choch_strength (choch only when a CHoCH fired), bars_since_last_shift
(right-censored). Kept 0.0 as measured state (zero_is_state lists land in 4c):
sr_level_count, pool_count, fvg_open_count, active_demand/supply_zones, bsl/ssl_touches,
sweep_detected, ob_mitigated_flag, breaker_block_active, bos/choch_direction,
smc_trend_direction; fvg_midpoint/price_in_premium stay float sentinels (in-memory zone
soft-dependency inputs, not stored columns). amd_cycle untouched (retires whole in item 6,
D5). The 1d compute() branch and `_cold_start_vector` now match the batch path (the four
legacy VP/SR columns None). Migration 560 states the NULL contract in column COMMENTs (21
columns, applied live; 559 reserved for item 8). Golden delta: 28 columns union over the 17
cases (price_in_value_area/in_lvn unchanged on goldens - every golden bar has a live session
histogram), regenerated from HEAD-restored fixtures in its own commit. Gates: /simplify
(4 agents: stale `_SESSION_LEVELS_FALLBACK` contrast comment; 12 conditional None-casts
moved to measured-assignment `float()` with pass-through returns; cold-start locals
inlined; per-branch annotation unified), /review medium (1 confirmed finding, FIXED:
`corpus_manifest_verifier._check_feature_null_rates` strict max_null_rate tier would fail
the rerun's own final verification on honest nulls - now two-tier, `_ABSENCE_EXEMPT_TFS`
exempts the session pair on 1d and gates the four columns only against being entirely NULL
where the object can exist, 4 new tier tests), full suite green. Successor: 4c
(zero_is_state declarations + the registry-wide no-object test; drop
amd_manipulation_detected from the zero_is_state list per the D5 ordering note; probe at
/tmp/584_item4/probe_no_object.py needs `HmmConfig.from_values(SMALL_HMM_APR.get)`).
4b-1 landed the helper layer AND its build-site half: `_primitives.py` z-score helpers
(`_zscore_last`/`_z_or_nan` one implementation, `_rolling_zscore_series`,
`_fixed_window_zscore_series`) NaN on cold and zero-spread; `wilder_rsi_series` NaN cold and
0/0 with NO epsilon branch (an epsilon on the decaying Wilder averages made the NaN boundary
seed-dependent, a causality violation the probe caught; the exact 0-divisor cases are stated
instead); `_cumsum_window_moments` NaN-aware with window recovery (bit-identical on
all-finite input); price.py gap family rows 0-1 NaN (`_overnight_gap_z` now reads
`_overnight_gap_series_full`, the one gap definition); `_zscore_from_deque` deleted (stale
twin of `_z_or_nan`). Build site: 55 rule-5 columns `_guard` -> `_missing_if_nan`, product
compounds through `_missing_product` with parent tuples (None parents are missing, not a
TypeError), schemas widened `float | None`, `_guard_counted` lost its dead `inputs=` param.
New `test_missing_routing_ties_to_the_schema_annotation` polices the annotation/routing tie
for every later flip. Known limitation (kept, both /simplify and /review flagged it): the
`_missing_product` parent tuples are hand-enumerated at the call sites and must move with the
producer definitions; the deeper producer-side tripwire is a future refinement. The
streaming compute() lane keeps its own upstream neutrals (582); the still-guarded quantities
(mfi, stoch_k, bb_pct_b, the ratios, bars_since caps) are 4b-2+. Gates: /simplify (4 agents)
and /review (medium) applied, full suite green except the golden digests, golden regenerated
in its own commit immediately before the landing commit. The full-graph no-object probe
(flat 400-bar 5m series, all float externals NaN, `compute_kernels` over every output) adjudicates
the columns into four classes:

- Already correct (all-NaN on flat): every z/corr column that goes through `_z_or_nan`/
  `_corr_or_nan` (rules 5 landed there in items 1/5), the macro/CTF columns on NaN externals, the
  HMM walk-forward columns (fit refuses on degenerate input).
- Fabricated neutrals to fix in 4b (helper altitude first): the vectorized window helpers
  `_rolling_zscore_series`/`_fixed_window_zscore_series`/`_sliding_rolling` and `_zscore_last`
  (0.0 on zero-spread), `wilder_rsi_series` (50.0 cold start and flat window; 100.0 on all-gain
  is measured and stays), mfi (50), stoch_k (0.5 = 0/0), bb_pct_b (0.5), updown_ratio (1.0 = 0/0),
  variance_ratio/hv_ratio/realized_var_ratio (1.0 = 0/0), cci (0.0), aroon (0.0 on flat: the
  rolling max is the current bar, verify before changing), intraday_noise_ratio (1.0), wick/
  body/close-position ratios on a zero-range bar (0.5/0.0 = 0/0), price_percentile on an
  all-equal window (0.5/1.0 boundary convention), vol_acceleration (1.0), and the right-censored
  `bars_since_extreme_move_*`/`bars_since_vol_spike_*` (window-cap 19/49 must be NaN: rule 2's
  "bars since event with no event is NaN"; `bars_since_high/low_*` are measured 0 on flat and are
  zero_is_state, not fixes). Genuine-constant ratios stay measured: rel_volume, vol_ratio,
  vol_trend_ratio read 1.0 on constant volume and that is a real measurement (zero_is_state
  declarations in 4c, not fixes). Noted from the 4b-1 review: `_gap_z_series_full` still
  fabricates `gap[:2] = 0.0` as z-window INPUT (rows 0-1 output are NaN, but rows 2..window
  score over the made-up 0.0); with the now NaN-aware moments the honest form is `gap[1]=NaN`
  extending warmup - deliberate for now because it moves the streaming warmup boundary with it
  (582 lane decision), revisit when the streaming gap builder is unified.
- smc/vp_sr no-object fallbacks to fix in 4b: sr_resist/support_dist 0.0, resistance/support
  strength+age 0.0, ob/fvg/zone/bos distance-strength-age 0.0 (all "the distance/strength/age of
  an object that does not exist"), sweep_strength/bars_since_last_sweep, va_position 0.5,
  poc_dist_atr 0.0, price_in_value_area 0.0, in_lvn 0.0 where no VA exists. Counts and event
  flags keep 0.0 and get zero_is_state in 4c: sr_level_count, pool_count, fvg_open_count,
  active_demand/supply_zones, bsl/ssl_touches, sweep_detected, amd_manipulation_detected,
  ob_mitigated_flag, breaker_block_active, bos/choch flags (verify each is a flag not a strength).
- Exempt from the no-object test (4c) because their object always exists: the four calendar
  kernels, the three canaries, calendar_above_wk_vwap (0.0 on flat = measured "at/below"), and
  the bar-level always-measured columns (ret_lag_*, open_ret, overnight_gap, true_range_pct,
  abs-range/body columns, dist_from_high/low_*, high_52w_dist, shannon's point-mass 0.0).

4c then lands `Kernel.zero_is_state` per kernel (the lists above plus ret_lag_*, dist_*,
  bars_since_high/low_*) and the registry-wide test: every stored column outside zero_is_state
  is all-NaN on both the flat series and a 2-bar series; zero_is_state outputs are asserted
  finite-or-NaN only. The probe lives at `/tmp/584_item4/probe_no_object.py` (rerun to
  regenerate the list; it needs `HmmConfig.from_values(SMALL_HMM_APR.get)` on the config).

### Item 4c landed (2026-11-03)

`Kernel.zero_is_state` declared per kernel and the registry-wide no-object test
(`tests/unit/intelligence/test_kernel_no_object_contract.py`) is in; goldens regenerated first in
`8a9c60e8d`. Degenerate correlation windows go through `_corr_or_nan` (floor `STD_FLOOR`, 1e-8,
where the two inline guards used 1e-10); streaming and batch paths agree for `vol_persistence`
and `vol_trend_ratio` (NaN on a zero-volume slow window). Not part of 4c: the legacy `feature_factory` `_guard(..., 0.0|1.0)` and `_series_last(..., 0.0)`
refills and the `vwap_dev_sigma` default vector (todo 463; the rerun's `_compute_series_columns` keeps
the kernel NaN, so they do not block it), and the cold prefixes in `_ret_skew_z_series_full`,
`_ret_acf1_z_series_full` and the `vol_trend_ratio` cold start (todo 474; they sit inside declared
memory, so the rebuild masks them).

### Item 6 landed (2026-11-03)

D5 retire executed as the 2026-11-02 edit list specified: 11 columns (`in_london_kz`, `amd_phase`,
`amd_manipulation_detected`, `amd_distribution_direction`, `manip_strength`, the five
`session_levels` overnight/Asian columns, `ret_div_1m_5m`). The `amd_cycle` kernel is gone whole,
`calendar_session` has five outputs, `session_levels` eleven with no 1d declaration (and no `tf`
input), `cross_tf_divergence` two, and `minute_of_hour_*` is declared undefined on {"1d", "1h"}.
Also gone: `update_overnight_range` and the AMD, overnight and Asian `FeatureCache` state, the
`ext_ltf_last_log_ret` external with `Alignment.LTF_ASOF_BAR_START`, `_build_ltf_return_series` and
the 1m fetches that fed it (backfill worker, pilot gate, parity capture), the seven
`FeatureFactoryConfig` hour fields. Migration 561 deletes their seven APR keys; the 11 concepts are
`deprecated` through `ops_concept_registry_override.py`. `feature_vectors` and `feature_vectors_v2`
keep the physical columns (derived cache; the DROP waits for the rebuild's summary card), recorded
as `RETIRED_COLUMNS` in the v2 schema test. The v2.x pydantic copies in `I3Structure`/`SMCContext`
are untouched. The legacy live `compute()` still emits `minute_of_hour_*` as 0.0/1.0 on 1h (as it already did on 1d), a legacy-path fill for todo 463. Golden regenerated in its own commit (`1f917b6ed`): only `minute_of_hour_*` on 1h
changed besides the dropped columns.

Item 6 gate note: `/code-review` ran before the landing; `/simplify` ran afterwards over
`1f917b6ed^..47f35b440` and landed as its own commit (stale counts and comments naming the retired
columns, the no-op `declared=na`, the half-stripped `$N` annotations in
`feature_vector_persistence`, and the dead `ltf` members stripped from `real_inputs.npz`). Left
for the owner: `_FETCH_STAGE_TIMEFRAMES` still fetches 1m bars in `--fetch-only`, and the 1m consumer
is gone; whether anything else reads 1m rows is not traced.

### Item 6a landed (2026-11-03): ret_div NULL on other timeframes is by definition

`ret_div_X_Y` is the X-timeframe return minus the Y-timeframe return, so it exists on X only. The
HTF external is the row timeframe's mapped HTF (1h for 5m and 15m, 1d for 1h), and `ret_lag_1` is
the row's own return. On 15m, `ret_div_5m_1h` would be a 15m-versus-1h gap under a 5m name, and
`ret_div_1h_1d` on 5m or 15m would need a 1d return no timeframe's external carries (the mapped HTF
is 1h there). The "NULL where the inputs exist" finding is therefore not a defect: both columns are
now declared `not_applicable` off their own timeframe (`ret_div_5m_1h` undefined on 1m/15m/1h/1d,
`ret_div_1h_1d` on 1m/5m/15m/1d), and the compute no longer carries a second copy of the pinning.
`undefined_on` takes a tuple of timeframes. No stored value changes (the cells were NaN), so the
golden does not move. Decision against the lead ruling "defined on tf <= X": a finer row's own
return is a different horizon, so the column would mislabel it; building a 1d external for 5m and
15m would be a new feature, not a fix.

### Item 6b landed (2026-11-03): ctf_vwap_align was absorbing, not a 474 fill

Cause, measured on `feature_vectors_v2` 1h rows and on daily bars: `_build_ctf_series` computed
sign(close - VWAP anchored at the start of the higher-timeframe series). On the 1h rows the HTF is
1d with history from 2006, so a trending name sits on one side of its inception VWAP for good: the
89 constant names are 84 at +1 and 5 at -1, never 0 and never NaN (ADI above it on 98% of daily
bars, ACIW 87%, AGNC 23%; a 252-bar window flips 110 to 190 times on the same names). The 474 path
named in the first finding (VWAP filled with the close on a no-volume window) cannot fire on the
tradeable view, which has `volume > 0`. The VWAP now covers the last `feature.ctf.vwap_window` HTF
bars (migration 562, [initial_estimate] 20, the HMM return buffer's length), NaN until the window
is full and NaN on a window with no volume, from direct window sums (a prefix-sum difference cannot
resolve a zero-volume window after 1e11 of earlier volume). A window below 2 raises. Only
`ctf_vwap_align` moves in the golden. The pilot run reads the per-timeframe sign-flip rate and the
lead recalibrates the window. Known and not part of 6b: the legacy `_guard` still turns the NaN
into 0.0 on the legacy FeatureVector path and the live `FeatureCache.ctf_vwap_align` is never
updated (todo 463; the rerun's `_compute_series_columns` keeps the NaN).

### Item 6c landed (2026-11-03): sweep_detected retired, liquidity_sweeps loses its ATR gate

Measured on `feature_vectors_v2` (lead, 20 large caps: rate 0.9973 to 1.0000 on every name at 15m,
0.9995 to 1.0000 at 1h; this session, AAPL/MSFT/KO/JPM/XOM since 2026-06-01: 5m 0.9994 over 19,890
rows, 15m 1.0000 over 6,630, 1h 1.0000 over 1,785, 1d 1.0000 over 420). The cause is the
definition: the flag is 1.0 when any sweep exists anywhere in the 120-bar lookback, which real
series almost always have. The per-bar event is `bars_since_last_sweep == 0`, already stored, at
0.29 to 0.36 on the same rows. Deleted rather than redefined (Musk step 2): kernel output,
`zero_is_state` entry, `FeatureVector` field, concept deprecated through
`ops_concept_registry_override.py`, physical columns kept (added to `RETIRED_COLUMNS`). Sweep
geometry never divides by ATR (depth is a percent of the swing price), so `_compute_liquidity_sweeps`
loses its `_is_valid_atr` gate and the kernel its ATR input; strength, velocity and bars-since now
exist on bars with an invalid ATR. Only `sweep_detected` leaves the golden (real series have a valid
ATR). Audit of the other SMC kernels for the same gate (reported, not fixed here): `bos_choch`
divides by ATR only for `bos_strength` and `choch_strength`, yet the gate also resets
`bos_direction`, `choch_direction`, `smc_trend_direction` and `bars_since_last_shift`;
`fair_value_gap` divides only for `fvg_dist_atr` and `fvg_size_atr`, yet the gate also zeroes
`fvg_open_count` and `fvg_midpoint` (the zones kernel consumes the midpoint); `order_blocks`
divides only for the two `ob_*_dist_atr` and `breaker_dist_atr`, yet the gate also resets
`ob_strength`, `ob_mitigated_flag`, `breaker_block_active` and `ob_mitigation_pct`. The pools and
zones kernels use ATR in the detection itself, so their gates are needed. Gate note for 6a and 6b:
`/code-review` and `/simplify` ran over both before the 6b landing; their findings that were fixed
are in the 6b commit (direct window sums, window guard, `4h` in the denylist, stale text).

### Item 8 landed (2026-11-03): the add-list

Ten stored columns in three kernel modules (`kernels/residual.py`, `distribution.py`,
`dividend.py`), the spec pinned in `docs/plans/2026-10-28-pre-rebuild-feature-additions-draft.md`
("Implementation spec"); `days_to_ex_dividend` stays out (no declaration time in
`dividend_events`). Wiring: nine `FeatureFactoryConfig` fields (defaulted, read by both service
config builders) and nine APR seeds; `DailySeriesRecord` plus `_daily_records_kernel_inputs` align the
daily records as-of the row's bar end like the betas; `build_daily_records` in the backfill
service runs the three builders per symbol (Yahoo coverage span decides known versus unknown,
one amount per ex-date Yahoo first with IBKR fallback, an ex-date without a bar moves to the next
bar); the pilot gate builds the same records. Ten `V2_ONLY_COLUMNS` entries, ten columns on
`feature_vectors_v2` and ten `candidate` concept rows by migration 559 (applied live; feature rows
are seeded by migration as in 289, `register_idea.py` takes the idea domains only); the three
`rank_z` concepts deprecated through `ops_concept_registry_override.py` (421). The parity golden
does not move: it holds the legacy-path columns only, as for `high_low_spread`. The new daily-grid
kernels pass the causality and memory probe ("ok"), and the macro-alignment truncation tests cut
and rebuild all ten.
Decisions in the build: the residual builder runs over dates both the name and SPY have a bar on
(a missing bar would read as a stale close and a fabricated 0.0 return); `build_symbol_beta_series`
still iterates the union of dates and so carries that zero return on such dates, which makes the
stored `equity_beta_z` differ from the residual's beta in those rare cases. Left open, with the
reviewers' cost notes: the daily records are rebuilt for each (symbol, timeframe) unit (about four
times the daily work and two small queries per symbol; hoist per symbol if the rerun's cost shows
it), the columns are rebuild-only (V2-only, no live path), and the beta loop is a second
implementation of the macro one (add an equivalence test or share a generator).

### Item 6d landed (2026-11-03): the SMC ATR gates narrowed to the outputs that divide by ATR

Measured first (last 40,000 5m / 30,000 15m / 20,000 1h bars and the 1d history per name; invalid
means `_is_valid_atr`: ATR not finite, not positive, or below `feature.atr_normalization.min_atr_pct`
of the close): SPY, AAPL, KO and USMV are invalid on 0.04% to 0.07% of intraday rows and 0.3% of 1d
rows, all of it ATR warmup (0.0% after 200 bars); SHY 1.1% of 5m rows and 0.05% at 15m/1h, BIL 5.4%
of 5m, 3.0% of 15m and 0.7% of 1h rows (ultra-short T-bill ETFs, flat for long stretches, past
warmup too). So the gate is cheap to keep wrong on large caps and costly on the cash-like ETFs,
where it wiped the whole SMC group. Change: `bos_choch` (only the two strengths divide by ATR;
directions, trend and bars_since_last_shift are computed), `fair_value_gap` (only the two
distances; open count and midpoint are computed, the midpoint feeds zones), `order_blocks` (only
the three distances; strength, mitigation flag and pct, and breaker flag are computed). Each
returns None for the ATR outputs when the ATR is invalid. `liquidity_pools` and
`supply_demand_zones` keep the whole-fallback gate: ATR is in their detection (equal-level
tolerance, impulse and base thresholds), and zones with an invalid ATR ignore the now-populated
midpoint. Golden regenerated first: only `fvg_open_count` on the synthetic cold rows moves (real
series have a valid ATR after warmup). `test_smc_atr_gate_narrowing.py` pins that an invalid ATR
changes only the ATR outputs. Stored values on invalid-ATR rows change, so this rides the pin.

### Item 8b landed (2026-11-03): the beta builders run on common dates only

`build_symbol_beta_series` iterated the union of the name's, SPY's and TLT's dates. On a date one
series had no bar, the missing bar read as a stale close, a fabricated 0.0 return entered the beta
window, and the next real return was measured from the stale close. It now runs on
`common_bar_dates` (the dates every series has a bar on; `prev_close` advances only there), the
same helper the market-residual builder uses, so the stored `equity_beta_z`/`rate_beta_z` and the
residual's beta cannot disagree on gap days. Impact on real data is small and bounded (1d,
tradeable view): against SPY the names AAPL, BIL, CENT, GNE, HON, INGN, KO and SCCO have 0 to 2
dates SPY has and they lack, and 1 to 7 dates they have and SPY lacks, over about 25 years, so a
handful of windows per name carry the old zero return. Consumers checked: the backfill worker, the
pilot gate and `compute_batch` take the builder's date-keyed dict and read it as-of
(`daily_asof_indices`), and the `factor_beta_daily` grid kernel runs the same builder, so a date
with no record is skipped by all of them. The golden does not move (the fixtures have no gap
days); `test_beta_series_gaps.py` pins that a gap day emits no record and enters no zero return.
`build_cross_asset_series` has the same union-of-dates shape for its returns and is not changed
here: it handles partial coverage on purpose (`n_partial_coverage_dates`) and intersecting its six
series would shrink its output, so it needs its own ruling. Known: the daily-grid kernels' declared
memory counts grid rows (the union of dates) while the builders now count common dates, so around a
gap day a window reaches a few rows further back than declared; a unit computes from the series
start, so no warmup mask is affected, and the holes-and-late-start probe cases pass.

### Item 3 landed (2026-11-04): trend K=3, hmm_vol_prob_elevated retired

The 583 refusal-rule study is complete and uniform: trend K=3 at 1d/5m/15m/1h (refused share 5m
6.2% vs K4 7.9%, K5 17.0%; 15m 1.3% vs 3.5%, 12.0%; 1h 1.5% vs 5.5%, 9.6%; 1d from the rule on
complete data), volatility K=2 at every timeframe (1h 0.0% vs K3 56.6%), equal to the existing
`alpha.hmm_volatility.n_components`. So the per-timeframe key mechanism that was first built was
deleted before landing; migration 566 only moves `feature.hmm.n_components` from 5 to 3 with the
provenance `[583 refusal-rule study 2026-11-04, uniform across 1d/5m/15m/1h]` and a
`config_history` row quoting the rule and the table. Methodology-ledger entry E20 holds the table,
the rule fixed beforehand, the uniform-K decision and the BIC disclosure (BIC prefers K=6 on every
timeframe, 380 of 437 names at 1d, so it is uninformative here). Label map at K=3: trending_down,
ranging, trending_up; `transition_up`/`transition_down` no longer occur. Consumers checked: nothing
branches on them (the label tuple keeps them so codes stay stable; the seeded vocabulary, the
migration comments and the glossary still list them as valid codes). `hmm_vol_prob_elevated`
retires per D6: the volatility family's numeric block drops from seven columns to six
(`prob_order` (2, 0); `N_NUMERIC_COLUMNS` replaced by the per-family `n_numeric`), the column
leaves `REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES`, the concept is deprecated, the physical
columns stay (`RETIRED_COLUMNS`). The regime-kernel golden changes layout only: every volatility
case drops one column and zero values changed (flip report all zero). The pin now waits only on
the data-lane items. Repair (2026-11-04): a first, per-timeframe migration 566 was applied live and
reverted before landing; it had deleted `feature.hmm.n_components`' `config_history` rows (APR as of
t reads this table). They were re-created with their original timestamps reconstructed from
evidence, since no backup holds them (`data/backups/*` carry only retired-key and unrelated
config_history dumps; the baseline fixture seed has no history inserts): `migration_176`, version 2,
2026-06-19 14:45:42.183585+00 from the baseline fixture's `config_state` row for the key, and
`migration_265`, version 2, 2026-07-28 15:07:16+00 from migration 265's git commit date (0eb45042f);
both reasons say RECONSTRUCTED. Verified: an as-of read at 2026-08-01 returns 5 and at 2026-11-05
returns 3. Also noted (8b): a builder window that reaches past the declared memory around
a gap day only makes the warmup mask conservative, since the builder emits NaN until its own window
fills; no change.

### Item G4-a landed (2026-11-04): rolling sums are exact per window

The dry pilot's G4 memory check found a length-dependent numeric defect, not float noise.
`_cumsum_window_moments` (and `_bb_pct_b_series_full`) took each window sum as a difference of
whole-series prefix sums, whose rounding grows with the running total. Measured with the new
`ops_pilot_compute_gate.py --drift` (max |full - windowed| in float32 ulps, SPY, 3 probe rows,
`causality_probe.measure_memory_drift`; the default gate is unchanged):

| kernel output | SPY 1h (35,647 rows) before / after | SPY 5m (399,508 rows) before / after |
|---|---|---|
| garman_klass_vol_z | 1 / 0 | 3,834 (rel 4.0e-4) / 0 |
| parkinson_vol_z | 5 / 0 | 1,498 (rel 1.3e-4) / 0 |
| bb_pct_b_fast | 0 / 0 | 759 (rel 6.0e-5) / 0 |
| bb_pct_b_slow | 0 / 0 | 392 (rel 4.3e-5) / 0 |
| the other 312 float outputs | 0 / 0 | 0 / 0 |

Fix (the 6b precedent): `_trailing_window_sums` adds each window left to right, so a window's sum
depends only on its own values and a recompute over any suffix returns the same bits; every user of
`_cumsum_window_moments` (rolling mean, std, z-score, hv_z, parkinson, garman_klass, yang_zhang) and
`_bb_pct_b_series_full` takes it. The bad-value count keeps an exact integer prefix difference.
Cost is O(n * window) vector additions. After the change both timeframes measure 0 ulp on all 316
outputs. Golden regenerated first (1 to 3 columns per case). Audit, reported and not fixed here:
`volume.py` still differences whole-series prefix sums in `_dollar_vol_z`-style rolling kernels
(about lines 354-356, 389-394, 410, 461-462, 483-508, 583-584) and `price.py` in the realized-vol,
efficiency-ratio and session-return kernels (about lines 422, 820, 975-976, 1073-1078, 1178,
1292-1293). SPY showed no drift in them at 1h or 5m, but the pattern is the same and grows with
length; the lead decides whether to port them before the pin.

### Item 12 landed (d003eb028, 2026-11-02 03:41; verified read-only by Track A, indicagent-ea)

The code half landed before Track A's 4b-1 leg; this note records the design for the record and
resolves the bit-identical question the batch row asks. Edit sites (all in `d003eb028`):

- `research/guards.py::integrity`, the volume branch: the permissive form was
  `bad = close_ok & ((volume <= 0) | (~isfinite(volume) & maximum.accumulate(isfinite(volume))))`
  - a LEADING per-symbol run of NaN volume passed (the former-venue NULL volume of migration
  374/todo 433), everything else failed. One rule now: `bad = close_ok & ~(panel.volume > 0)` -
  any bar with a close and a volume that is not positive and finite fails, leading or not.
  `volume_checked=False` (a panel carrying no volume at all, synthetic) still skips the check.
- The module docstring states the same rule and its agreement with
  `registry.require_finite_volume` (`features/contract/registry.py:475`, enforced at compute in
  `compute_kernels` at registry.py:613 - the item-7/17cfe233b side). The contradiction it closes:
  S3 could pass a panel that compute refused, so a guard verdict contradicted the kernel path.

Why `repro_frozen` bit-identical was the structural outcome, not the tripwire:

1. Both frozen artifact sets (phase 179 E14 S2/S3, phase 181 TSMOM) rebuild their panels through
   `daily_panel(sleeve_closes, dates, opens=sleeve_opens)` - opens/closes only, no volume array -
   so `volume_checked` reads False and the volume branch is unreachable in the repro; the edit
   cannot move any compared value.
2. No frozen book ever exercised the permissive branch: `research_run` is empty (migration 544
   reset it; the owner's clean-data rule of 2026-10-30 blocks new real-data runs), so no
   DB-built book panel exists on record at all, permissive or otherwise.
3. Since migration 543 the tradeable view serves no NULL volume, so even pre-edit the permissive
   branch had no reachable input from a research panel; the new GuardFailure can only fire on a
   panel not built from `market_data_ohlcv_tradeable`, which is what its message says. The one
   construction that could flip a historical pass into a refuse is a pre-543 pinned book
   snapshot replayed through current code - none exists (point 2).

Re-derivation for any future frozen artifact: to know whether it exercised the permissive branch,
check whether its pinned panel carries volume (`volume_checked`) and, if it does,
`close_ok & ~(volume > 0)` over the pinned arrays. Bit-identical is the expected outcome whenever
both are clean; a GuardFailure on rerun is the tripwire, and it means the artifact's panel did
not come from the tradeable view.

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
