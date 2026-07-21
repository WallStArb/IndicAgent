---
status: pending
priority: P0
filed: 2026-07-20
source: todo 147's true_range_pct CV re-check, re-run after 151/154 to verify their
  correction pass actually resolved the low_bull CV outlier -- it didn't
---

# `VWO`/`DIA`/`KRE` sentinel-value corrupt prints named in todo 147 were never corrected

## What's wrong

Todo 147's root-cause investigation (2026-07-20) identified three fabricated/sentinel-overflow
price prints in `market_data_ohlcv` and explicitly flagged them "for [151/154] directly...
not acting on here, per the other session's active ownership of that work":

- **VWO**, 1h, 2007-05-02 15:00:00+00 — `high=99999.99` (sentinel-overflow, real range ~41.7-41.9)
- **DIA**, 5m/15m/1h/1d, 2009-06-02 (5m bar at 14:00:00+00) — `high=100000` (real range ~87.5-87.8)
- **KRE**, 5m/15m/1h/1d, 2007-09-18 (5m bar at 18:15:00+00) — `high=400` (real range ~44.4-45.3)

Both todos 151 and 154 are recorded as CLOSED (2026-07-20) in project memory/PRIORITIES.md.
Re-ran todo 147's `true_range_pct` CV diagnostic today after that closure to confirm the fix
landed — **it hasn't**. `SELECT ... FROM market_data_ohlcv WHERE symbol IN ('VWO','DIA','KRE')
...` still returns the exact same sentinel values (`99999.99` / `100000` / `400`) verified live
via psql on 2026-07-20. `low_bull`'s `true_range_pct` CV is still ~150-300x every clean regime
(5m: 313.24, 15m: 279.22, vs. ~1-2 for clean cells) — barely improved from the original
582.9/469.4, not resolved.

**Likely cause:** 154's own noted tool gap — "candidate discovery misses rows whose
`return_suspect` flags were never tripped" (see
`.planning/todos/completed/154-*.md` or the project memory note on it). These three rows are
textbook fabricated ticks (`99999.99`, `100000`, `400` — round sentinel/overflow values) but
may never have tripped whatever detector fed 151/154's correction candidate list, since they
were found via a completely different path (this session's `true_range_pct` CV outlier hunt,
not the price-sanity guard's own detection logic).

## Why this matters

- Blocks todo 147 from closing — its Component F promotion decision (vol-normalized target
  keep/retire, feeding `ensemble_trainer`'s eligibility) can't proceed with `low_bull` still
  showing a 2x+ rank-correlation anomaly traceable to these exact rows.
- These are the same class of "no economic basis, real data-integrity bug" prints todo 152
  already established a precedent for (VWO/UUP/XRT named there too) — not an ambiguous
  crisis-event judgment call.
- Confirms a real coordination/tooling gap worth fixing once, not per-incident: a todo naming
  specific corrupt rows for another workstream to pick up needs some mechanical link (e.g. add
  to the correction candidate list directly, or a checklist item) or it silently falls through,
  as happened here.

## Fix

1. Correct these 3 rows through the established `price_sanity_status` mechanism (not a raw
   `UPDATE` — see CLAUDE.md: "Correction mechanism is now `price_sanity_status`, not the old
   `volume=0`"), reusing 151/154's correction tooling/pattern directly rather than building new.
2. Re-run the full recompute this correction requires (151's `--apply` needed a full 4-symbol
   recompute per its own gotcha note — `forward_return_writer.py` has no gap-fill mode) for
   `VWO`, `DIA`, `KRE`.
3. Re-run todo 147's `true_range_pct` CV check a third time to confirm parity, then re-run
   `ops_vol_normalized_target_ab.py --all-regimes` to close 147's Component F decision.
4. Optional process fix worth considering while here: when a todo names specific corrupt rows
   for another todo's scope, add them to that todo's own candidate list/file directly (not just
   prose in a different todo) so a closure doesn't silently miss them again.

## References

- `.planning/todos/pending/147-vol-normalized-target-low-bull-divergence.md` — the CV
  re-check and root-cause section this gap was found in
- `.planning/todos/completed/151-*.md`, `.planning/todos/completed/154-*.md` — the
  correction passes that should have included these rows but didn't
- Live verification (2026-07-20): `market_data_ohlcv` still has `VWO`/1h/2007-05-02 15:00
  `high=99999.99`; `DIA`/5m/2009-06-02 14:00 `high=100000`; `KRE`/5m/2007-09-18 18:15
  `high=400` — confirmed via direct psql query, not from stale memory
- Distinct from the 2010-05-06 IGV/CWB/VUG cluster also surfaced in this CV re-check — that's
  the real Flash Crash, legitimate per todo 152's crisis-event precedent, not corrupt
