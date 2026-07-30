---
status: pending
priority: P1
filed: 2026-07-19
source: Fable 5 review (docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md,
  Q1) + this session's horizon-response diagnostic run
  (scripts/ops/alpha/ops_lookahead_horizon_response.py, 20-symbol sample)
---

# `alpha.ic.lookahead.{fast,mid,slow,extended}` is one uniform bar-count grid across
# all 4 tfs; empirically it breaks 1h/15m/5m's slow/extended tiers -- needs per-tf grids

## Status (2026-07-30) — Step 3 shipped, but this todo's own grid is now provisional
## for 5m/15m/1h, not confirmed

**Step 3 landed** (migration 269, 2026-07-29 — `config_state` verified live 2026-07-30):
`alpha.ic.lookahead.{tf}.{scale}` per-tf keys exist and are read by `ICEngineConfig`/
`EnsembleICConfig`/`forward_return_writer.py`. The "rides Phase 162" framing in Step 3's
original text below is stale — Phase 162 completed independently 2026-07-23; the actual
rebuild vehicle ended up being a later, separate corpus-rebuild pass. `1h`'s `slow`/
`extended` keys are still present in `config_state` (`20`/`60`, inherited from the old
grid) rather than removed — they are known-degenerate placeholders, not a real "--" (the
`_SCALES` array-shape refactor needed to actually drop them is deferred, see below).

**This todo's central premise needs correcting.** The Problem section below (2026-07-19
text) calls the same-ET-session completeness gate "a deliberate, correct Invariant-1
constraint." Re-examined 2026-07-30 (see [208](208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md)):
that characterization does not hold up. Invariant 1 (`docs/foundation/v3-north-star.md`)
requires executable open-to-open pricing, not same-session pricing — 1d already crosses
sessions and is fully Invariant-1-compliant. The trade-construction layer that actually
builds ML training labels (`counterfactual_tracker.py`, `hold_max_bars` seeded at 60 bars
uniformly even for 1h) has no session concept at all and never has. Live completeness
numbers from this morning's `forward_returns` rebuild make the cost concrete: **1h's
`mid` (2-bar) completeness is 53.5%** — roughly half of all 1h bars, not just
late-session ones, have no valid forward return at even the shortest multi-bar horizon
under the current gate.

**Practical effect: do not treat the "Step 2 grid as shipped" table below as
locked for 5m/15m/1h.** It was derived under the assumption that session-boundedness is
a correct, load-bearing constraint — [208](208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md)
is actively checking whether that assumption should be dropped, which would change the
grid for three of the four rows and potentially the tier *count* itself (`_SCALES`'s
fixed 4-wide shape, also never independently derived — see 208). `1d`'s row is
unaffected either way (no session gate applies to it). Read the rest of this todo as
"how the currently-live grid was derived," not as a closed decision — 208 is now the
todo that decides whether it needs to change again.

## Problem (2026-07-19 text — the "deliberate, correct" framing below is superseded by
## the Status section above; kept verbatim for the historical record)

Confirmed live (`config_state`/`config_schema`): `alpha.ic.lookahead.{fast,mid,slow,
extended} = 1/5/20/60` bars, every one `[initial_estimate]`, never empirically
calibrated despite being tagged "ML learning target" in its own description. The same
four bar-counts apply identically to 5m/15m/1h/1d, never tf-scaled the way `_tf_window()`
scales day-denominated regime-model window params, or the way `alpha.ic.bootstrap_block_size`
is already tf-differentiated.

This is worse than an inconsistent-economic-horizon smell: it collides with
`forward_return_writer`'s intraday same-ET-session completeness gate (a deliberate,
correct Invariant-1 constraint -- overnight gaps aren't tradeable for intraday entries)
and structurally breaks a third of the design grid. Measured live from `feature_ic_scores`
before this session's fix work: **1h slow/extended have ZERO rows anywhere in the table;
15m extended has ZERO rows; 5m extended is measured on ~20% of bars (morning-entry-only,
a silent selection bias nothing downstream flags).**

## Empirical evidence (this session)

Ran a new diagnostic, `ops_lookahead_horizon_response.py` (read-only, computes forward
returns directly via the same LEAD()-based construction and same-ET-session completeness
gate as production, across a dense per-tf horizon grid, pooled across all regimes). Full
methodology in the script's docstring. 20-symbol bounded sample, vintage
`2025-12-24 05:15:00+00:00`:

| tf | horizon_bars | completeness | n_valid | median\|IC\| | median CI halfwidth |
|---|---|---|---|---|---|
| 5m | 1 | 0.973 | 389144 | 0.0030 | 0.0031 |
| 5m | 26 | 0.634 | 253771 | 0.0104 | 0.0039 |
| 5m | 39 | 0.462 | 184923 | 0.0103 | 0.0046 |
| 5m | 66 | 0.124 | 49569 | 0.0124 | 0.0088 |
| 15m | 1 | 0.922 | 368832 | 0.0027 | 0.0032 |
| 15m | 10 | 0.572 | 228607 | 0.0083 | 0.0041 |
| 15m | 22 | 0.111 | 44302 | 0.0105 | 0.0093 |
| 1h | 1 | 0.661 | 253663 | 0.0047 | 0.0039 |
| 1h | 4 | 0.163 | 62763 | 0.0066 | 0.0078 |
| 1h | 6 | **0.000** | 0 | n/a | n/a |
| 1d | 1 | 1.000 | 83895 | 0.0046 | 0.0068 |
| 1d | 40 | 0.991 | 83115 | 0.0109 | 0.0068 |
| 1d | **60** | 0.986 | 82715 | **0.0122 (peak)** | 0.0068 |
| 1d | 90 | 0.980 | 82115 | 0.0078 | 0.0068 |

Full curve (all grid points, not just the excerpt above): see the diagnostic's own
stdout, not re-persisted anywhere -- re-run `python
scripts/ops/alpha/ops_lookahead_horizon_response.py` to reproduce (read-only, no writes).

**Reading the curve (magnitude and CI width together, not magnitude alone -- a rising
median\|IC\| with a proportionally-widening CI is consistent with pure noise from
shrinking N, not real signal growth):**

- **1d is the one tf where today's guessed grid holds up.** No session boundary, so
  completeness stays 98-100% even at horizon=90; CI half-width stays flat (~0.0068)
  across the whole grid since n_valid barely shrinks (84K -> 82K). IC genuinely peaks
  at horizon=60 (0.0122) and declines by 90 (0.0078) -- a real decay curve, not noise.
  Today's `extended=60` is close to the empirical optimum for 1d specifically. No urgent
  change needed here.
- **1h has almost no room for 4 distinct horizon tiers within one session.**
  Completeness is already down to 66%/49% at horizon 1/2, collapses to 16% at 4, and is
  literally impossible at 6 (7 bars/session -- matches the prediction exactly). A
  `fast`/`mid` pair around 1-2 is the honest ceiling; `slow`/`extended` cannot exist as
  session-bounded measurements at 1h without accepting a badly biased, near-empty
  population.
- **15m and 5m show rising IC alongside collapsing completeness at their longest
  grid points** (15m/22: IC 0.0105 but completeness 11%, CI 3x wider than horizon=1;
  5m/66: IC 0.0124 but completeness 12%, CI ~3x wider). This is genuinely ambiguous on
  a 20-symbol sample -- could be real signal still building toward the session boundary,
  could be the classic noise-inflation-as-N-shrinks pattern. Flagging as unresolved
  rather than claiming either reading; full-corpus reproduction (Step 1 below) should
  settle it with real power instead of guessing from a 20-symbol pass.

## Fix

**Step 1 (this session, done):** the horizon-response diagnostic exists and produced
the table above. Re-run at full 80-symbol corpus scale before locking any production
grid change -- this todo's numbers are a 20-symbol proof of the method and the
qualitative story (intraday coverage collapse is real and severe), not a final
calibration.

**Step 2 (decision, per Fable's framing -- recommend (i) unless full-scale data shows
otherwise):** for intraday tfs, accept session-bounded per-tf grids honestly reflecting
what one session can measure, rather than (ii) inventing an overnight-inclusive return
type. Candidate per-tf grids to validate against the full-corpus re-run (session-bounded,
picked to keep completeness in a reasonable range -- NOT locked, needs full-N
confirmation):

| tf | fast | mid | slow | extended (candidate) |
|---|---|---|---|---|
| 5m (78/session) | 1 | 5-6 | 12 | 26-39 (needs full-N read on the 39-66 ambiguity above) |
| 15m (26/session) | 1 | 2 | 5 | 10 |
| 1h (7/session) | 1 | 2 | -- | -- (no session-bounded slow/extended tier survives; needs its own design decision, not a number) |
| 1d | 1 | 5-10 | 20-40 | 60 (keep -- empirically near-optimal already) |

**Step 3 (apply at next corpus rebuild, rides Phase 162, pre-registered in
`docs/plans/methodology-change-ledger.md`):** the gradient-naming design already pays
for this -- `forward_returns` columns are scale-named, `feature_ic_scores` stores
`lookahead_bars` explicitly, `_build_forward_return_sql` is already invoked per tf.
Making the APR keys per-tf (e.g. `alpha.ic.lookahead.{tf}.{scale}`, or a JSON per-tf
grid) requires no schema migration. **Do NOT change `alpha.ic.lookahead.*` now** -- this
would invalidate every fingerprint/checkpoint mid-corpus and force an unplanned
recompute; apply only at the next scheduled rebuild window, same discipline as Phase
162's own fingerprint-timing decision.

**1h's missing slow/extended tier is a real open design question, not just a number to
pick** -- worth its own explicit decision (accept 1h as effectively fast/mid-only, or
retire it from slow/extended-tier ensemble eligibility entirely, or something else) at
Step 2/3 time, not silently defaulted.

## Sizing

Todo-sized for Steps 1-2 (diagnostic exists, full-scale re-run is cheap -- same script,
`--max-symbols 80`). Step 3 (the actual APR/production change) is properly scoped to
ride the next corpus rebuild, not a standalone effort -- no new sizing needed beyond
what that rebuild already costs.

## Steps 1-2: DONE (2026-07-20), Step 3 still deferred to Phase 162

Ran the full-corpus re-run this todo called for (`--max-symbols 80`, all 4 tfs). Two
findings beyond the 20-symbol pilot's scope:

**Memory:** the naive `--max-symbols 200` full-run OOM'd the shared machine (14GB+ RSS,
system down to 480MB free while another session's live corpus work was running) -- 5m's
default `--max-bars-per-symbol=20000` at full symbol count generates ~1.6M rows x 7
horizons of pure-Python tuple/list overhead in `per_horizon_keys`. Re-ran per-tf as
separate process invocations with `--max-bars-per-symbol 5000` (1h/15m) / `3000` (5m) and
an active memory-guard kill switch; all four completed cleanly. `--max-bars-per-symbol`'s
docstring already warned about this failure mode for an *unbounded* run; it under-warns
for a bounded-but-large one. Worth a note if this script gets a fourth run: don't pass
`--max-symbols` beyond the actual universe size (80) and keep intraday
`--max-bars-per-symbol` at a few thousand, not the 20K default.

**Instrument defect found and fixed:** Fable 5's review of the full-corpus results (see
`docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md`'s "Q1
addendum, 2026-07-20") caught that the diagnostic's Fisher-z CI was computed on raw
overlapping-window observations with no stride correction -- effective independent N at
long horizons is n_valid/horizon, not n_valid, so the CI understated its own half-width
(this is why 1d's CI looked artificially flat across the whole grid in the first
full-corpus run). Fixed in `ops_lookahead_horizon_response.py`
(`_stride_for_horizon(min_stride, horizon_bars) = max(min_stride, horizon_bars)`,
mirroring `ic_engine.py`'s production `scale_stride` exactly) and re-ran 1d
stride-corrected. Unit tests: `tests/unit/scripts/test_ops_lookahead_horizon_response.py`.

**Result: 1d's candidate grid changes, the other three tfs' candidates are confirmed
unchanged.** Stride-corrected 1d shows every horizon >=20 with CI half-width exceeding the
IC point estimate itself (not distinguishable from noise at 1-sigma) -- the pilot's
"extended=60 near-optimal" claim was read off the artificially-flat pre-fix curve and is
withdrawn. This isn't a diagnostic-only finding: production `ic_engine` uses the identical
stride discipline, so it's what production actually measures at 1d/60 today, consistent
with the original review's independent evidence for that cell (`n_independent` ~372-451,
FDR pass 0.83%, Component F's `1d/high_bull/extended` collapse).

**Step 2 grid as shipped in migration 269 (2026-07-29, live in `config_state` —
PROVISIONAL for 5m/15m/1h, see Status section at top):**

| tf | fast | mid | slow | extended |
|---|---|---|---|---|
| 5m | 1 | 6 | 12 | 39 |
| 15m | 1 | 2 | 5 | 10 |
| 1h | 1 | 2 | 20 (degenerate) | 60 (degenerate) |
| 1d | 1 | 2 | 5 | 10 |

1h's `slow`/`extended` keys were left at their old values rather than removed — they are
known-degenerate (zero completeness under the session gate, see Status section), not a
real "--" tier. Actually dropping them requires restructuring `ic_engine.py`'s fixed
`_SCALES` 4-wide array shape, deliberately left out of scope here (see 208 for why that
restructuring may be needed for a different reason too — the tier count itself, not just
which values fill it).

**Step 3 shipped 2026-07-29** (migration 269) — superseding the "still NOT done" text
this section originally had. `alpha.ic.lookahead.{tf}.{scale}` is live and read by
`ICEngineConfig`/`EnsembleICConfig`/`forward_return_writer.py`. What remains open is not
whether Step 3 happened, but whether the grid it applied is correct for 5m/15m/1h —
that question now belongs to [208](208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md),
not this todo.

## Addendum (2026-07-29) — downstream consequence confirmed in live `config_state`

Independently verified, while investigating a TSMOM/momentum-edge discussion, that this
todo's already-diagnosed root cause has a live downstream symptom: `alpha.frame.hold_max_bars.
<regime>.1d` and `.<regime>.1h` are **100% seed-only in production right now** — checked
`config_history` directly, all 36 history rows for each of those two timeframes are the
2026-07-02 `[initial_estimate]` placeholder (`"Initial estimate: conservative hold_max_bars
default pending EIC-02 calibration"`), zero real `EIC-02` calibration rows ever, for either
timeframe. `5m` (36/74 real calibrations) and `15m` (31/71) calibrate fine by comparison.

This is not a new bug — it is exactly what this todo's own finding predicts: `1h` has zero
`feature_ic_scores` rows at `slow`/`extended` corpus-wide (session-completeness collapse), so
`_calibrate_hold_max_bars`'s per-symbol qualifying gate (`passes_fdr AND reliable AND
walk_forward_stable`) has nothing to evaluate for those cells and silently returns 0 written
keys, forever, until Step 3 ships. `1d`'s case is the same mechanism from the other finding
above: `extended=60`'s "near-optimal" read was the pre-fix flat-CI artifact, so `1d` cells at
`slow`/`extended` under the *current* grid are being asked to confirm a decay boundary that
was never real, and (per the momentum_z_slow spot-check this session: 0/53 FDR passes at 1d
non-pooled) essentially never can.

**Practical implication for Step 3's rollout:** re-deriving `hold_max_bars` under the new
per-tf grid (`1d`: 1/2/5/10; `1h`: 1/2, no slow/extended tier by design) should be treated as
part of the same rebuild step, not a separate follow-up — until then, anything reading
`alpha.frame.hold_max_bars.*.1d` or `.*.1h` for real position-sizing/hold decisions is reading
an uncalibrated 3.5-week-old guess, not a measurement. Worth a `calibration_status` (seed vs.
calibrated) surfaced wherever these keys are consumed, so this doesn't silently recur for
some other (regime, tf) cell in the future.

## References

- [208](208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md)
  -- the successor todo that now owns the open question: whether the same-session gate
  this todo's grid was derived under should exist at all for 5m/15m/1h, and whether the
  fixed 4-tier shape is the right one. Read 208 before treating any grid in this file as
  final.
- `docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md` Q1 --
  full analysis this todo implements Step 1-2 of
- `scripts/ops/alpha/ops_lookahead_horizon_response.py` -- the diagnostic (read-only,
  reusable, `--max-symbols`/`--max-bars-per-symbol`/`--tf` bound cost)
- `services/forward_return_writer.py` `_build_forward_return_sql` -- the production
  construction this diagnostic mirrors (same LEAD() pattern, same completeness gate)
- `services/ic_engine.py` `ICEngineConfig.from_apr` (~line 537-540) -- where the
  current flat lookahead dict loads; the eventual Step-3 change site
- `.planning/todos/pending/097-vol-normalized-return-target-pooled-ic.md` -- Component
  F, whose worst-stratum finding (1d/extended) motivated re-checking this grid; Fable's
  review found the coupling is real but resolvable by conditioning Component F's
  verdict on stratum reliability, not by sequencing this todo first (see Q3b in the
  Fable doc above)
