**Author:** Fable (dispatched via Claude Code Agent tool, independent from-scratch design pass, 2026-09-09)

# H-B redesign: confirmed-reversal volume statistic

Design proposal only. Not reviewed, not run, not merged into the pre-registration doc. The
main doc (`docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md`) and
both AGY review rounds are read-only inputs to this design, not things this file edits.

## Why the round-2 construction kept failing

Both failed attempts (`swing_volume_confirmation`, then `k = min(bars_since_low_fast,
bars_since_high_fast)` with `k >= 1`) shared one root cause: they read the *runtime value* of a
sliding-window statistic at an arbitrary bar `t` and tried to infer two different things from it
at once — how far bar `t` sits from a reversal's origin, and which origin (high or low) is
closer. `bars_since_low_fast`/`bars_since_high_fast` are correct at exactly one thing: `== 0`
means "this bar's low/high is the extreme of the trailing `dist_window_fast`-bar window,
right now." Their non-zero values are a byproduct of sliding-window argmin/argmax bookkeeping,
not a leg-length counter, and using them as one produced every bug AGY found: the value doesn't
saturate, so once the true extreme ages out of the window the column keeps reporting a *number*
that looks like "bars since the reversal started" but is arithmetically unrelated to when any
reversal actually began.

The redesign below only ever reads `bars_since_low_fast == 0` / `bars_since_high_fast == 0` as a
boolean per-bar event flag (the one part of these columns AGY's round-2 review explicitly
verified as causal and correct) and does all "how long has it been since the last one of these
fired" bookkeeping itself, in the read-only script, with a construction that cannot drift.

## 1. The exact statistic

### 1.1 Anchor tracking (derived in the analysis script, not a new `feature_factory.py` column)

Per `(symbol, tf)`, over the bar sequence ordered by `bar_ts` (index `i = 0 .. n-1`):

```
low_ext[i]  = (bars_since_low_fast[i]  == 0)
high_ext[i] = (bars_since_high_fast[i] == 0)
tie[i]      = low_ext[i] AND high_ext[i]        # outside bar; excluded as an anchor,
                                                  # same convention as H-A's extreme_proximity_t
clean_low[i]  = low_ext[i]  AND NOT tie[i]
clean_high[i] = high_ext[i] AND NOT tie[i]

anchor_idx  = None    # forward scan state, carried across i
anchor_type = None
for i in 0 .. n-1:
    if clean_low[i]:
        anchor_idx, anchor_type = i, 'low'
    elif clean_high[i]:
        anchor_idx, anchor_type = i, 'high'
    # tie[i] or neither: anchor unchanged, carries over
    anchor_idx_at[i]  = anchor_idx
    anchor_type_at[i] = anchor_type

k[i] = i - anchor_idx_at[i]     # undefined (NaN) while anchor_idx_at[i] is None (warmup,
                                  # before the first clean extreme in this symbol's series)
```

This is a plain forward scan, O(n) per symbol, reading only already-persisted `feature_vectors`
columns. It is the same *kind* of operation as `_bars_since_event_series_full` in
`feature_factory.py` (an event-indexed "bars since the last True" tracker) but implemented
independently in the analysis script against the `==0` boolean stream, not as a new pipeline
column and not by reusing the sliding-window `bars_since_*` value itself.

### 1.2 Confirmation event set

Lock a single fixed integer `K_CONFIRM` before running (a real researcher degree of freedom —
see "trade-offs" and "needs verification" below; proposed primary `K_CONFIRM = 3`, with
`K_CONFIRM ∈ {1, 2, 5}` as reported, ungated robustness, matching this codebase's
primary/robustness pattern for `return_fast`/`return_mid` and for `range_pct_fast`'s 5-offset
stride table).

```
E = { i : k[i] == K_CONFIRM  AND  anchor_type_at[i] is not None }
```

`E` is the full domain of definition of the H-B statistic — it is undefined everywhere else,
not zero-filled, not NaN-filled-and-kept-in-the-panel. A bar enters `E` if and only if it sits
exactly `K_CONFIRM` bars past the most recent clean fresh extreme, with no other clean extreme
(of either type) having fired anywhere in between.

### 1.3 The statistic, for `i ∈ E`, with `a = anchor_idx_at[i]`

```
leg_volume[i] = mean(volume_z[a+1 .. a+K_CONFIRM])     # = mean(volume_z[a+1 .. i]); NEVER
                                                          # includes volume_z[a] itself
sign[i]       = +1 if anchor_type_at[i] == 'low' else -1
confirmed_reversal[i] = sign[i] * leg_volume[i]
```

No `close` values, no `market_data_ohlcv_tradeable` join, anywhere in this construction. That
join existed in both failed attempts solely to compute a close-delta sign; §2.5 below shows why
this design needs no such join at all — a real simplification, not a deferred requirement.

Forward return: measured from bar `i` (the confirmation bar itself), `return_fast` primary/gated
and `return_mid` ungated/reported, `return_type = 'executable_open_to_open'`
(Invariant 1) — identical convention to H-A, no new lookahead-band question introduced.
Panel requires `complete_fast = true` (`complete_mid = true` for the secondary band), matching
house convention.

## 2. Why each of the 5 confirmed bugs is structurally impossible here

**(1) Density/subset fallacy.** `E` is defined by `k[i] == K_CONFIRM`, an exact equality on a
small fixed integer — not `k[i] >= 1`, which is `k[i] == 0`'s set complement and therefore
almost everything. Because `k[i]` strictly increases by exactly 1 per bar for a given anchor
until the anchor resets, `k[i] == K_CONFIRM` can be true **at most once per leg's lifetime** —
there is no integer value a strictly-increasing-by-1 counter can hit twice before resetting.
`|E|` is therefore bounded by the number of legs that survive at least `K_CONFIRM` bars without
a new clean extreme, itself bounded by H-A's own event count (26-30% of bars) — a genuine
subset, both by construction and arithmetically, never the complement of anything.

**(2) Reference-anchor drift.** `anchor_idx` is assigned in exactly two places in the scan, both
gated on the *current* bar's own `clean_low[i]`/`clean_high[i]` flag being true. It is never
derived from, or compared against, the sliding-window `bars_since_low_fast`/`bars_since_high_fast`
*value* at any bar other than to test `== 0`. There is no code path by which `anchor_idx` can
become the index of a bar that was not itself a genuine clean extreme when it happened — the
assignment literally requires that bar's own flag to be true at assignment time. This is the
direct fix for the exact mechanism AGY traced by hand: the round-2 construction's `k` came from
re-reading a sliding-window argmin's current state, which silently changes identity as the
window slides past the true extreme; this design's `anchor_idx` is a write-once-per-leg value
that is never subsequently reinterpreted.

**(3) Capitulation-volume contamination.** `leg_volume[i]` averages `volume_z[a+1 .. a+K_CONFIRM]`
— the range's lower bound is `a+1`, syntactically one bar past the anchor. `volume_z[a]` (the
extreme bar's own volume) cannot enter this average; there is no filter to forget, because the
index range itself never includes `a`. This is the same shape of guarantee H-A already has for
its own single-bar statistic, extended correctly to a multi-bar average instead of re-broken.

**(4) Serial correlation from overlapping windows.** Combining (1) and (3): `E` contains at most
one row per leg, and two different legs' `[a+1, a+K_CONFIRM]` windows cannot overlap, because a
new anchor `a'` can only be set at a bar strictly after the previous leg ended, and the previous
leg's one possible included row (if it exists) sits at `a + K_CONFIRM`, which is `<= a' - 1` by
construction (a leg that resets before reaching `K_CONFIRM` bars contributes zero rows, it does
not contribute a truncated one). Every row in the panel corresponds to a disjoint span of bars
in the underlying series — there is no pair of included observations that share so much as one
`volume_z` value between their averaging windows. Ordinary cross-leg autocorrelation from shared
market regimes still exists (it exists in every panel in this codebase) and is handled the
ordinary way — date-block bootstrap CI, date-aware null — not the extra ~5-10x degrees-of-freedom
inflation AGY measured, which came specifically from consecutive *bars* of one ongoing leg
sharing nearly their entire averaging window, a mechanism this design has no analog of.

**(5) Sign inversion on wick candles.** `sign[i]` is read directly off `anchor_type_at[i]` — a
label produced entirely by which of `clean_low`/`clean_high` fired at the anchor bar. It contains
no reference to `close` at any bar, at the anchor or elsewhere, so there is no arithmetic path by
which a hammer or shooting-star candle's close-to-open geometry could flip it. This isn't a
"less likely to invert" fix, it's a formula with no term that could invert.

## 3. Testing machinery (reuse, no new statistical machinery)

Directly port the pattern from `alpha_score_residual_single_security_15m.py`'s `Panel` class,
which already solves exactly the problem the round-1 review flagged (`_circular_block_bootstrap_ic`'s
raw row-index block slicing has no date awareness and is wrong once the panel is filtered to
sparse rows):

- **Panel construction:** build the `Panel` over the `E`-filtered measurement rows directly (as
  `alpha_score_residual` already does — its panel is the join-filtered `alpha_events` rows, not
  the full dense bar series). `Panel.__init__` groups by symbol and calendar date from whatever
  rows are handed to it; handing it `E`'s rows rather than a dense panel is the intended usage,
  not a misuse of the class.
- **Family statistic:** equal-weighted mean across qualifying symbols (`>= 100` measurement rows,
  matching `_MIN_BARS_PER_SYMBOL`) of within-symbol Spearman IC of `confirmed_reversal` against
  `return_fast` — identical convention to H-A and both reference scripts.
- **Bootstrap CI:** `Panel.bootstrap_ci` — date-block circular resampling (`_DATE_BLOCK = 5`
  trading days or the codebase's live APR value), `B = 2000`. Correct here because rows still
  carry a real calendar date each, even though the underlying event is sparse.
- **Null:** `Panel.sync_shift_null_p` — panel-synchronous whole-date circular shift, one common
  `k` per replicate, `N = 1000`. Pairs each symbol's `confirmed_reversal` values with returns
  from a different date while preserving within-date structure — the same null H-A uses, now
  applied to a construction where "the panel" genuinely is the already-sparse event set (no
  dense-vs-filtered mismatch to reason about, because the confirmation event itself, not a
  post-hoc filter, defines the rows).
- **Per-symbol significance / BY-FDR:** `ic_math.py::_p_values_from_ic`'s asymptotic
  t-approximation (`df = n - 2`), exactly as `alpha_score_residual`'s `_per_symbol_table` and
  `range_pct_fast`'s per-symbol attribution table both already do — never an empirical
  permutation p-value (round 1's correctly-identified reason: no discrete resolution floor
  problem at any `N_null`). `n` here is now a true per-symbol confirmation-event count, not an
  inflated ~70%-of-bars count, so `df = n - 2`'s implicit independence assumption is far less
  abused than in the round-2 construction — see §5 for why this still needs an empirical check,
  not just an assertion.
- **BH (reported) alongside BY (gated)** across symbols, via `apply_bh_fdr`, same as both
  reference scripts.
- **PASS rule:** identical shape to H-A's Track 1 (bootstrap `ci_lower > 0`; null `p < 0.05`;
  positive point estimate in 3/3 calendar-date thirds; `>= 10%` of family symbols BY-FDR
  significant and positive; `IC_min = 0.003` effect-size floor) — same numbers, same house
  precedent, no new PASS-rule invention. H-A and H-B remain scored independently, never combined
  into one statistic, per the main doc's existing rule.
- **Cross-sectional arm:** dropped, for the same reason H-A's was — `E` is, by construction,
  sparser than H-A's own 26-30%, so same-bar cross-sectional ranking is at least as degenerate.

No new bootstrap, null, or FDR machinery is proposed anywhere in this design — every piece above
is an existing function or an existing class used the way its own codebase precedent already
uses it.

## 4. Trade-offs this design accepts, explicitly

- **Loses multi-length-leg information.** The claim is narrowed from "does volume on the bounce
  leg predict continuation" (leg length unconstrained) to "does volume in the fixed
  `K_CONFIRM`-bar window immediately following a confirmed extreme predict the next bar's
  return." This is a real narrowing, not merely a technicality — a construction that separately
  tested, say, `K_CONFIRM = 15` would be answering a different, more momentum-flavored question
  (AGY's round-2 flaw 6.2 concern) than one testing `K_CONFIRM = 2`. Reporting several fixed
  `K_CONFIRM` values as ungated robustness is a mitigation, not a fix — each one is still its own
  narrow claim, not a "leg-level" one.
- **Survivorship on the leg's persistence.** Only legs that reach exactly `K_CONFIRM` bars
  without a new clean extreme of either type resetting the anchor contribute a row. A reversal
  that fails and re-extends the prior extreme within `K_CONFIRM` bars contributes nothing. This
  is arguably consistent with the economic hypothesis as stated ("a reversal ... already
  underway" presupposes some persistence), but it does mean this design cannot speak to whether
  volume distinguishes real reversals from fakeouts at the moment of the extreme itself — only
  whether, conditional on `K_CONFIRM` bars of persistence, volume during that window adds
  information. That conditioning should be stated plainly wherever this result is cited, not
  left implicit.
- **No price follow-through gate.** `sign[i]` is set purely by which extreme type most recently
  fired — it does not require price to have actually kept moving away from the extreme over
  `[a+1, a+K_CONFIRM]` (no check that, say, `close[i] > close[a]` for a low anchor). A leg that
  chopped sideways or dipped back toward the extreme without printing a *new* clean extreme still
  enters `E` with the same sign a cleanly-trending bounce would. This is the direct price of
  buying immunity from the wick-inversion bug (§2.5) — reintroducing any close-based check risks
  reintroducing exactly that failure mode unless it is scoped very carefully (e.g. compared
  against the anchor's own high/low, never against its close). Left out of the primary statistic
  here; a price-follow-through sub-table, reported not gated, is a reasonable future addition
  in the same spirit as H-A's wick-corroboration sidecar — not proposed as part of the gated
  construction in this design.
- **`K_CONFIRM` is a real, unremovable researcher degree of freedom.** It is not derivable from
  the economic hypothesis or from the data without looking at results — it must be locked before
  any run, exactly like H-A's timeframe and universe locks, and its choice should be justified on
  economic grounds (short enough to stay "coincident," long enough that a 3-bar mean is more than
  single-bar noise) before results are seen, not tuned afterward.
- **No use of `market_data_ohlcv_tradeable` at all.** A genuine simplification relative to both
  prior attempts (§1.3), but it does mean this construction cannot see anything about *where
  within its range* the confirmation-window bars closed — a form of information the original
  user-framing ("wick size/bar characteristic") gestured at. That information is deliberately
  left out of the gated statistic here for the same reason as the point above.

## 5. What still needs empirical verification before this is trusted

Matching this doc's own density-calibration precedent (live SQL against `feature_vectors`, not
an assumed number) — none of the following should be taken on faith:

1. **Event density of `E`, per `K_CONFIRM ∈ {1, 2, 3, 5}`, at `tf = 15m`.** Confirm `|E|` really
   is a small fraction of bars (expect low single-digit percent or less, well under H-A's own
   26-30%) and that per-symbol counts clear whatever family-minimum floor (`>= 100` rows) the
   final pre-registration locks, across the 231-symbol universe. This is the direct analog of
   the density calibration already run for H-A and for the round-2 construction (which is what
   caught bug 1 in the first place) — it must be re-run against this construction specifically,
   not inferred from either prior number.
2. **Leg survival rate to `K_CONFIRM` bars.** Of all H-A-eligible clean extreme events, what
   fraction have `anchor_type_at` still equal to the same type and unreset `K_CONFIRM` bars
   later? This bears directly on how much the survivorship trade-off (§4) actually bites — a
   survival rate near 100% makes that trade-off nearly moot; a survival rate near 10% means most
   of H-A's own event population is being thrown away before it ever reaches `E`, which changes
   how the design should be described.
3. **Outside-bar (tie) frequency and its effect on anchor carry-over.** AGY estimated `< 1%` for
   the round-2 construction; re-check for this one, and separately check whether "anchor
   unchanged on a tie" versus "tie hard-resets the anchor" produces materially different `E` sets
   — a robustness variant worth comparing, not assuming away.
4. **Hand-verify the anchor scan against raw data for at least one symbol.** Pull a few hundred
   consecutive 15m bars for one liquid symbol, compute `anchor_idx_at`/`anchor_type_at`/`k` in
   the script, and manually check 5-10 anchor transitions against the bar-level high/low series
   by eye — the same "independently re-derive the algorithm by hand" discipline that caught all
   five round-2 bugs in the first place, applied to this new code before trusting it with the
   same scrutiny, not less.
5. **Warmup-period contamination.** Check whether `bars_since_low_fast`/`bars_since_high_fast`
   emit a degenerate `0.0` during a symbol's earliest `dist_window_fast` bars (rather than NaN or
   some other warmup marker) — if so, the anchor scan could pick up a spurious "extreme" at the
   very start of a symbol's history and produce a first `E` event with no real economic content
   behind it. Check for anomalous concentration of `E` rows in the first `dist_window_fast` bars
   per symbol.
6. **Residual serial correlation across included rows.** Even though windows are disjoint by
   construction (§2.4), measure the empirical autocorrelation of `confirmed_reversal[i]` across
   time-ordered *included* rows within a symbol, to confirm it is unremarkable (nowhere near the
   `r > 0.95` AGY measured for the flawed construction) before trusting `df = n - 2` in the
   per-symbol BY-FDR gate. This validates the structural argument in §2.4 against the actual
   data rather than resting on the construction argument alone.
7. **`K_CONFIRM` robustness in direction and rough magnitude.** Once run, check that the sign and
   approximate size of the Track 1 point estimate are qualitatively stable across
   `K_CONFIRM ∈ {1, 2, 3, 5}` — not as a second gated chance to pass (only the locked primary
   value is gated, per §4), but as an honest check that a PASS at `K_CONFIRM = 3` isn't an
   artifact of that one integer.

## Addendum (2026-09-09) — empirical verification against real data, and a new finding

Not part of Fable's original design pass; added afterward by checking items 1, 2, 3, and 4
above against live `feature_vectors` data for one symbol (SPY, `tf=15m`, 130,632 bars,
2006-07-20 onward), rather than accepting the design's own density expectations on faith.

**Confirmed, matching expectations:**
- H-A's own event rate for this symbol: 25.61% of bars — consistent with the project-wide
  26-30% calibration already run elsewhere.
- Tie (outside-bar) frequency: 0.059% — negligible, matches AGY's `<1%` estimate.
- `|E|` density at `K_CONFIRM=3`: **6.9% of bars**, genuinely sparse (nowhere near the ~70%
  round-2 bug). Leg survival rate to `K_CONFIRM=3`: **27.1%** of H-A-eligible extremes — real,
  not a near-zero degenerate rate. At `K_CONFIRM=1/2/5`: 11.3%/8.5%/5.2% density,
  43.9%/33.1%/20.2% survival respectively.
- Hand-verified the first 10 anchor-setting transitions against the raw
  `bars_since_low_fast`/`bars_since_high_fast` values (item 4) — mechanically correct, matches
  the algorithm as specified, with one exception below.

**New finding, not anticipated by items 1-7 above: warmup contamination is real.** 13 of the
first 20 bars in this symbol's history register as a "fresh low" event (`bars_since_low_fast
== 0`) — a warmup artifact: before a full `dist_window_fast`-bar trailing window has
accumulated, nearly every new bar trivially becomes "the minimum seen so far," firing the
`==0` flag on almost every bar rather than reflecting a genuine repeated extreme. Left
unguarded, this would seed `E` with spurious anchors during each symbol's warmup period.
**Required addition to the construction (§1.1):** exclude each symbol's first
`2 * dist_window_fast` bars from eligibility as either an anchor-setting event or an `E`
member. Cost is negligible (~0.03% of this symbol's history). This finding likely also applies
to H-A's own construction (which reads the same `==0` flag with no warmup guard either) —
flagged as a follow-up check on the already-reviewed H-A construction, not addressed here.

**Locked for the candidate spec going into round 3 review:** `K_CONFIRM = 3` primary (gated),
`K_CONFIRM ∈ {1, 2, 5}` reported/ungated robustness, plus the warmup-exclusion guard above.

## Round 3 outcome (2026-09-09)

Full review: `docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-agy-review-round3.md`.
**Conditional pass.** All 5 round-2 bugs confirmed structurally eliminated (independently
re-verified, not accepted on assertion — see that file's own verification-status header).
Four amendments required; incorporated into the main pre-registration doc's final H-B section:

1. **Tie hard-reset**: an outside bar (fresh high AND low simultaneously) must reset
   `anchor_idx = None`, not carry the prior anchor over — a tie means the prior single-sided
   extreme was just invalidated by a new, opposite-direction extreme printing at the same bar.
2. **SQL fetch buffer**: the analysis script must fetch a trailing buffer of data before the
   IS-window start date so the forward scan's anchor state is genuinely warmed up at the
   clamp boundary, not falsely reset to `None` there; only rows at or after the IS start enter
   the evaluation panel `E`.
3. **Diurnal reported sub-panel**: `volume_z` has no session-boundary detrending (verified,
   see the main doc and todo 372) — add a reported, ungated morning-vs-afternoon breakdown so
   a PASS isn't an artifact of the market-open volume smile.
4. **Panel.sync_shift_null_p per-symbol shift gap** — real, verified against source, reaches
   beyond H-B (shared testing machinery). Filed separately as todo 372, not fixed inline here;
   gates H-B's Track 1 execution but not the construction spec itself.
