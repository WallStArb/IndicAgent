---
status: pending
priority: P1
filed: 2026-07-30
source: user pushback on todo 146's session-bounded grid for 1h + follow-up architecture
  review this session
---

# `forward_return_writer`'s same-ET-session completeness gate (5m/15m/1h) has no
# analog in the trade-construction layer that actually consumes bars -- likely
# suppressing real signal, not protecting executability. Compounded by a second,
# related rigidity: the fixed 4-tier `fast/mid/slow/extended` scale shape is itself
# uniform across all 4 tfs with no empirical basis.

## Live completeness numbers (2026-07-30, this morning's forward_returns rebuild,
## current session-gated grid -- confirms the severity is worse than the pre-rebuild
## estimate this todo originally cited)

```
SELECT tf, avg(complete_fast::int), avg(complete_mid::int),
       avg(complete_slow::int), avg(complete_extended::int)
FROM forward_returns GROUP BY tf;
```

| tf | fast | mid | slow | extended |
|---|---|---|---|---|
| 5m | 0.972 | 0.903 | 0.821 | 0.461 |
| 15m | 0.920 | 0.881 | 0.762 | 0.566 |
| 1h | 0.689 | 0.535 | 0.000 | 0.000 |
| 1d | 1.000 | 0.999 | 0.999 | 0.997 |

**1h's `mid` (2-bar horizon) completeness is 53.5% -- essentially half of every 1h bar
in the corpus, not just late-session ones, has no valid forward return at even the
shortest multi-bar horizon.** Any signal firing in roughly the back half of a trading
day at 1h is structurally invisible to IC measurement regardless of quality. 5m/15m
degrade the same way at their `extended` tier (46-57% complete). This is the concrete,
measured form of the user's point: "if you were to buy or sell into a signal at 3pm
[the] last 1h bar[,] how it reacts the next day or few days is immaterial [under the
current gate] ... that seems like we are throwing away signal."

## Second, compounding finding: the 4-tier `fast/mid/slow/extended` shape is itself
## an unexamined, hardcoded assumption -- not just the session gate's cutoff point

`ic_engine.py`'s `_SCALES` tuple is a fixed 4-wide array threaded through ~13
positionally-indexed call sites (`_compute_one_regime_cell`, `_compute_symbol_tf`,
`_compute_cross_sectional_tf`, the SQL/array-building sections feeding them). This
shape was never derived per-tf from first principles (how many horizon points does a
tf's decay curve actually need, given how many bars it has to work with) -- it is
inherited array-shape convenience, most naturally justified for 1d, stamped onto 5m/
15m/1h uniformly. Todo 146 itself flagged this exact restructuring as explicitly out
of scope, "deliberately left ... under time pressure ahead of an imminent full-corpus
run" -- i.e., known, not overlooked, just deferred. Two distinct questions therefore
need answering, not one: (a) *where* should the forward-return boundary be (this
todo's original scope, the session-gate question), and (b) *how many* horizon tiers,
and at what spacing, should each tf actually get once (a) is resolved -- 5m has 78
bars/session and might warrant more than 4 sample points to characterize its decay
curve; 1h, once no longer artificially capped at 7 bars/session, might want a
differently-shaped grid than "fast/mid/slow/extended" implies. Don't re-derive a new
4-tier grid under the corrected session definition and call the design work done --
the tier *count* itself needs the same scrutiny the boundary just got.

## Problem

Todo 146 accepted "1h has no viable slow/extended tier" as an empirical finding and
shipped a grid where 1h stops at `mid=2` (7 bars/session ceiling). The user pushed back:
1h forward returns are perfectly capable of extending past the session close, moving
averages and other indicators are already computed contiguously across midnight, and
treating the session boundary as a hard wall "implies there's no use for the last few 1h
bars of the day."

Re-checked from first principles against the actual codebase, not just the diagnostic
output:

1. **Invariant 1's own text does not require session-boundedness.** `docs/foundation/
   v3-north-star.md`: "Theoretical returns capture overnight gaps and opening moves that
   cannot be traded" -- the rule is open-to-open (executable) vs close-to-close
   (theoretical), not same-session vs cross-session. 1d already uses cross-session
   open-to-open forward returns and explicitly documents overnight gaps as "part of the
   signal, no session-boundary gate" (`forward_return_writer.py` comment). Nothing in the
   invariant singles out intraday tfs for different treatment.

2. **The trade-construction layer that actually produces ML training labels already
   treats every tf as one contiguous bar-indexed sequence, no session concept at all.**
   `services/counterfactual_tracker.py::determine_exit` walks `bars_since_entry`
   sequentially with zero date/session check; `hold_max_bars` (the exit trigger) is
   seeded at 60 bars uniformly across ALL (regime, tf) cells (migration 214's comment:
   "the longest `alpha.frame.hold_max_bars.*` value across all (regime, tf) cells is 60
   bars"), meaning the system's own default assumption is that a 1h position can be held
   ~8.5 trading sessions. `alpha_frame_writer.py` has no session-boundary logic either.
   **The measurement layer (`forward_return_writer.py`) enforces a same-session
   constraint that the execution/hypothesis layer (`counterfactual_tracker.py`,
   `alpha_frame_writer.py`) does not share and never has.** This is a genuine
   measurement/construction mismatch, not just an aesthetic inconsistency: IC discovery
   is structurally blind to any feature whose payoff only materializes by holding past
   the session close, while the actual trade-hypothesis layer would happily realize that
   payoff if such a feature were ever promoted -- except it never can be, because IC
   discovery zeroes it out first. This is exactly the kind of silent data-dropping
   `CLAUDE.md`'s "never drop data that could contain signal" principle exists to catch.

3. **The original bug the same-session gate fixed (commit `5ffc6b5f`, Phase 140 P0) was
   real, but the fix was likely an overcorrection.** The bug: a 15:55 ET bar's "1-bar
   forward return" was silently matching the *next morning's* open across the full
   overnight gap, while a 10:00 ET bar's "1-bar forward return" stayed intraday --
   mixing wildly different holding periods (minutes vs. ~17 hours) under one nominal
   `fast` label, contaminating that feature's IC. The fix chosen was to exclude any
   cross-session row entirely. An alternative that fixes the same contamination without
   discarding data: treat "N bars forward" as genuinely bar-indexed (exactly what
   `LEAD()` over `market_data_ohlcv_tradeable` -- already gap-free, real trading bars
   only -- naturally computes), matching how every other bar-indexed construct in this
   codebase works (moving averages, HMM regime state, `hold_max_bars`). "1 bar forward"
   would then consistently mean "the next real trading decision point," whether that's 5
   minutes or 17 hours away -- not two different things depending on time of day.

4. **Fable's 2026-07-19 review already flagged this exact fork and deferred it,
   pending data:** `docs/research/fable-2026-07-19-lookahead-and-target-calibration-
   review.md` Q1 Step 2: "(i) accept session-bounded per-tf grids ... or (ii) define an
   overnight-inclusive return type ... Recommend (i) unless Step 1 shows IC still rising
   at the session boundary." Todo 146's own full-corpus run found exactly that
   ambiguous signal for 5m/15m ("IC rising alongside collapsing completeness at their
   longest grid points ... genuinely ambiguous ... flagging as unresolved") and never
   ran option (ii) to resolve it. 1h's case is more extreme -- its entire slow/extended
   tier was eliminated by the gate without ever testing whether contiguous bars retain
   signal past the boundary.

## What already exists to test this

This morning's session built exactly the tool needed: `ops_lookahead_horizon_response.py`
now has `--allow-overnight` (skips the same-session gate, uses an extended multi-day
horizon grid for 1h/15m) plus `--features`/`--bootstrap` for a properly-calibrated CI
recheck on shortlisted columns. It has not been run yet -- blocked on `feature_ic_scores`
being empty pending the in-flight corpus rebuild (todo 202/205's regime-wipe fix,
relaunched 2026-07-30, `regime_writer -> forward_return_writer -> cross_sectional_regime_model
-> ic_engine`).

## Fix (staged, do not skip the empirical step)

**Step 1 (once the in-flight ic_engine run completes and `feature_ic_scores` is
populated again):** run `ops_lookahead_horizon_response.py --tf 1h --allow-overnight`
(and `--tf 15m --allow-overnight`) at full corpus scale. This settles Fable's
deferred fork with real data instead of architecture reasoning alone -- per this
project's "empirical over theoretical" principle, the reasoning above is necessary but
not sufficient; confirm IC actually holds (or at least isn't systematically destroyed)
past the session boundary before touching production.

**Step 2 (if Step 1 confirms real signal persists):** remove the same-ET-session
`complete_{scale}` gate from `_build_forward_return_sql` for intraday tfs entirely (not
just add an `--allow-overnight` escape hatch) -- make all four tfs use the same
contiguous, bar-indexed, no-session-gate construction 1d already uses. This is a
`forward_returns` schema-semantics change (the `complete_{scale}` flag's meaning
changes for 5m/15m/1h), so it must ride a full corpus rebuild, same discipline as todo
146's own Step 3 -- do not partially apply.

**Step 3:** re-derive the per-tf lookahead grid under the new contiguous definition --
and treat the tier *count* as open too, not just the bar values within a fixed
4-slot template. See "Design: what the grid should actually be" below for the specific
proposed method, not just the fact that it's open.

**If Step 1 instead shows IC decaying to noise past the boundary** -- a legitimate
possible outcome, not assumed -- then the session-bounded grid stands as correctly
derived, and this todo closes with that finding recorded (the architectural
inconsistency in point 2 above would still be worth resolving on its own terms, e.g. by
adding an explicit session-boundary control feature, but would no longer imply lost
signal). The Step 3 design below is orthogonal to which outcome occurs -- it's about
how many/which horizons to measure once the *ceiling* per tf is known, whichever way
Step 1 resolves it.

## Design: what the grid should actually be (2026-07-30 addendum, not just where the
## boundary sits)

Prompted by a direct question: does the `fast/mid/slow/extended` framing that makes
sense for something like SMA/EMA periods actually hold for forward-return lookaheads?
**No, and the two shouldn't have been designed the same way.**

An MA period is a backward-looking smoothing window over data already observed --
computing a 20-bar and a 50-bar SMA side by side costs nothing extra, has no
completeness/censoring interaction, and carries no statistical multiple-testing burden.
Picking 4 of them vs. 8 is a free choice. A forward-return horizon is a *prediction
target* embedded in a significance-testing pipeline -- each additional horizon is a real
IC estimate, a real CI (Fisher-z or bootstrap), and a real addition to the FDR
correction's family size, and it's exactly the thing that gets censored when data runs
out (this todo's whole finding). `fast/mid/slow/extended` is CLAUDE.md's documented
*naming style* for APR gradients ("use scale qualifiers instead of numbers so a key
stays meaningful without a magic constant") -- that is a naming convention, not a
cardinality mandate. Somewhere it got read as "there must be exactly 4 gradient points,"
and that reading was never independently justified. The actual source of "4" is
`ic_engine.py`'s `_SCALES` tuple -- a hardcoded 4-slot array threaded through ~13
positionally-indexed call sites, an implementation artifact inherited from 1d's original
design and stamped onto every tf uniformly. Todo 146's own candidate grid values are a
tell: its text says they were "picked to keep completeness in a reasonable range" under
the session gate -- i.e., reverse-engineered to survive a constraint, not derived from
where each tf's actual IC-vs-horizon curve has real structure.

**Proposed method, once Step 1/2 settle the ceiling per tf:**

1. Use `ops_lookahead_horizon_response.py`'s existing dense, roughly log-spaced grid
   (already denser than 4 points per tf -- e.g. 5m tests `{1,3,6,12,26,39,66}`) as the
   *characterization* tool, not just a one-off diagnostic. Log-spacing is the right
   shape because return-IC decay curves are typically power-law-ish in horizon -- even
   resolution in log-horizon gives even resolution across the actual timescales that
   matter (minutes vs. hours vs. days), unlike linear spacing, which over-samples short
   horizons and under-samples long ones.
2. From that curve per tf, identify: where completeness collapses below a usable floor
   (the real ceiling, post-208), where CI half-width overtakes the IC point estimate
   (the statistical noise floor -- exactly what killed 1d's old `extended=60`), and
   where the curve's *shape* changes (rises, peaks, decays). Those inflection points are
   where a production measurement point earns its keep.
3. Let the number of production horizons be whatever that curve says, per tf -- not a
   number fixed in advance. 1h might genuinely want 2 real points; 5m might want 6.
   That's a finding, not something to design around.
4. **Decouple measurement resolution from decision granularity.** `ic_engine` can
   measure IC densely to characterize the curve; `hold_max_bars`/ensemble weighting only
   need to consume the 1-2 points that are actually tradeable and reliable. Right now
   both are forced through the same 4 `_SCALES` slots -- the wrong coupling.
5. Mechanically: store the per-tf grid as a JSON list (`alpha.ic.lookahead.{tf}`, a
   variable-length array) rather than four scalar named keys
   (`alpha.ic.lookahead.{tf}.{fast,mid,slow,extended}`) -- this project's own APR
   "behavioral list" pattern (CLAUDE.md's APR mandate, category 2: "lists controlling
   WHAT the algorithm processes → APR as JSON"; full spec
   `docs/foundation/adaptive-parameter-registry.md`). Named qualifiers can still be
   used for whichever 1-2 points feed downstream decisions -- that's a separate,
   smaller-cardinality concern from the measurement grid itself.

This requires the `_SCALES` array-shape refactor both 146 and this todo have now
flagged and deferred -- 146 explicitly, at Phase 138 corpus-rebuild time; this todo,
pending Step 1's data. Recommend not deferring it a third time once Step 1 lands --
scope it as its own follow-up plan at that point, informed by real per-tf curve shapes
rather than argued in the abstract.

## Sizing

Step 1 is cheap (existing tool, one more `--max-symbols 80` run per tf, read-only).
Step 2 is a real production code change (`forward_return_writer.py` + tests) that must
ride a full corpus rebuild -- do not attempt as a quick patch outside a planned rebuild
window. Step 3's tier-count question, if it turns out a tf needs a non-4-slot grid, is
a bigger lift than Step 2 alone -- the `_SCALES` array-shape refactor todo 146 deferred
-- and should be scoped as its own follow-up once Step 1's data says whether it's
actually needed, not speculatively built now.

## References

- `.planning/todos/pending/146-lookahead-grid-per-tf-recalibration.md` -- the grid this
  todo would supersede for 5m/15m/1h if Step 1 confirms
- `docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md` Q1 Step 2
  -- the deferred (i)/(ii) fork this todo resolves
- `docs/foundation/v3-north-star.md` Invariant 1 -- the actual executability rule (does
  not require session-boundedness)
- `services/counterfactual_tracker.py::determine_exit`, `production/migrations/
  214_alpha_frames_compression.sql` -- evidence the trade-construction layer is already
  session-agnostic and bar-indexed
- `scripts/ops/alpha/ops_lookahead_horizon_response.py` `--allow-overnight` -- the tool
  to run for Step 1 (committed `7db90af9`, 2026-07-30)
- `services/forward_return_writer.py::_build_forward_return_sql` -- the production
  construction Step 2 would change
