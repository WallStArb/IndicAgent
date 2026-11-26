# Pre-registration draft: family 10, volume shock members on the daily clock

**Status:** ADOPTED 2026-11-18 as ledger E24; Counted 2026-11-25 (four runs, ledger 2026-11-25b); read in `docs/research/construction-verdict-ledger.md`. Registered and run; the text below is the frozen draft as submitted, and the ledger entry governs. (Earlier status: DRAFT 2026-11-15, unapplied.)
**Amended 2026-11-23 (ledger 2026-11-22e, 2026-11-22h, 2026-11-23e, all before any return statistic of a family 10 member; the gate 5 measurement below is a read of bars and corporate actions, and it was read first: the original band failed, 327 of 3,133 split events outside 0.25 to 4 (10.4 percent), and the defect test replaced it, declared in 2026-11-23e):** V2's rank needs 37 of its 46 short means finite and V1's 40 of 50 (`min_finite_short` 40, the volume window itself); the orthogonalization fit runs over members only; section 6 item 5 is the near-factor defect test; items 4 is a seam and forward-confirmation precondition. Specs: `research/specs/family10_volume_shock_h5.yaml` and `_h5_core.yaml`.
**Author:** Claude (indicagent-c6), 2026-11-15, on the lead's brief.
**Informed by:** `docs/ideas/signal-published-prior-shortlist.md` item 4 (and its seen-data overlap list), `docs/plans/2026-11-15-published-prior-top3-prereg-drafts.md` (the shared frame, section 2, which this draft inherits unchanged except where it says so), `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md` (the form), `docs/research/construction-verdict-ledger.md` row 10, todos 555, 560 and 563 (the volume guard), `docs/foundation/glossary.md` (volume guard terms), `docs/plans/methodology-change-ledger.md` E17, E18, E21.

## 1. Scope: what this registers and what it leaves

Ledger family 10 (volume and order flow) is a design-only row whose pending members are `up_vol_ratio_fast`, `ofi_z`, `obv_z`, `mfi_slow` and the todo 281 statistics. Those are intraday stored columns with weak per-feature support (about 8 to 9 of 232 names FDR-pass each) and need the 5m clock, so they wait for the 5m tier and their own registration with its step 0 (residual n_eff at 5m and 15m). This draft registers the part that runs on the daily clock today: the two volume-shock members of shortlist item 4. Family 10's remaining members stay open under the same ledger row; adding them later is an amendment, each member counted.

## 2. Hypothesis

A name whose volume over the last day or week is unusually high against its own recent history rises over the following weeks, and unusually low volume precedes declines (Gervais, Kaniel and Mingelgrin 2001, Journal of Finance 56(3)). Published: the effect is not explained by return autocorrelation, announcements, market risk or liquidity, and the authors attribute it to a visibility shock; the working-paper version reports it stronger when the volume shock comes without an extreme return. Our inference: no replication was verified, decay and crowding are unknown, turnover is weekly. Every published number is a prior to count, never an expected result, and 65 percent of 452 anomalies fail a t of 1.96 under value weights (Hou, Xue and Zhang 2020).

## 3. Members (two, research-layer kernels over share volume and S1 residuals)

Both read the canonical 1d share volume (split-rescaled with the price by the daily rule, so a rank inside a window is scale-free) and S1 vintage 1 residual returns e. Row d is formed at d's close; the target enters at d+1's open, so no member reads a return or a volume inside the target window.

| Member | Statistic for row d | Sessions read | Sign |
|---|---|---|---|
| V1 `volume_shock_1_50` | the percentile rank of v[d] among v[d-49..d] (average rank for ties), minus 0.5, then made orthogonal to the same-session return: a cross-sectional OLS residual on row d of that value against e[d] and abs(e[d]) with an intercept, over the finite names | 50 | +1 |
| V2 `volume_shock_5_50` | the percentile rank of m[d] = mean of v[d-4..d] among m[s] for s in d-45..d (46 values, average rank for ties), minus 0.5, then residualized the same way against sum of e over d-4..d and its absolute value | 50 | +1 |

- A member is NaN when fewer than 40 of the 50 sessions have positive volume (V2: fewer than 37 of its 46 short means finite, each needing five finite sessions, ledger 2026-11-22e), or when the row has fewer than 200 finite names for the residualization (so no cross-section is fit on a handful of names).
- The orthogonalization is this registration's transfer of the paper's non-extreme-return condition to the residual construction; the paper conditions rather than residualizes, and a conditioned variant would be a separate counted member and is not run. Windows of 50 sessions and 5 sessions are pinned and never swept.
- Declared memory per member is `declared_memory_rows(slot_history_sessions, 1, vintage_1)`: slot history 50 (V1 and V2) plus S1's 252 and 21 sessions, read from the spec at registration, not retyped here.

## 4. Spec, universe, target and span

- Machine form: the spec file family10_volume_shock_h5.yaml (to be written), `kind: family`, `family: family10_volume_shock`, horizon 5, `factor_spec: vintage_1`, the two members above with `signal: src.intelligence.research.families.volume_shock.<function>`, construction R1 `rank_vol_neutral` (direction +1, coverage floor 20, 60-session residual vol, at least half finite), `timing_statistic: e17` with L = memory plus h, `session_scoring: true`, `min_shift: 63`, `bootstrap_mean_block: 21`, `bootstrap_reps: 2000`, `seed: 183`, guard seed 183, same scoring block as `daily_residual_h5.yaml`.
- Universe, target, span, family and guard config, pass and fail rule, costs and the forward-span rule: exactly the shared frame of the top three drafts, section 2. In brief: `universe_membership` and `universe_membership_core` panels, each member a counted series on each; the 231-name seen-set holdout applies (the corpus daily IC looks read `volume_z` and `rel_volume` on exactly those names); `panel.forward_returns` residualized by S1 with the forward-horizon lag; total-return prices; panel start 2005-01-03, end exclusive 2025-12-24; scored start 2007-03-01, sub-periods 2007-03-01 to 2011-12-31, 2012 to 2018, 2019 to 2025-12-23, reported not voted.
- Detection: each member's E17 statistic, one-sided positive, is in the Romano-Wolf StepM rejection set at 0.05 over the vintage selection universe. An opposite-sign result is recorded as counted, not promoted.
- Within the discovery span the only volume source is Massive (the vendor seam to Alpaca falls at the archive end, 2026-11-16, after `alpha.validation.oos_start`), so no window spans a vendor change in the span the members are scored on.

## 5. Looks, declared before any run

| Members | Horizons | Panels | Series added |
|---|---|---|---|
| 2 (V1, V2) | 1 (h = 5) | 2 (primary, core) | 4 |

h = 21 waits for todo 547 and is a separate registration that doubles the count. Cells of E21 sweeps that touch `volume_z`, `rel_volume` or any other volume column join the same universe under their own `n_looks` declaration; the registration lists those runs by id or states the sweep had not read them.

## 6. Data gate, in order, including the volume basis guard (todos 555, 560, 563)

1. The shared gate of the top three drafts, section 5, items 1 to 5 (step 7 D1, stage 2 gates, corpus rerun data gate for 1d on the membership names, I1 wiring, S1 regenerated), with the clean-data rule lifted by the owner for this family.
2. Single volume basis over the scored span (todo 555 and 560). After step 7 canonical 1d is Massive then Alpaca with no IBKR rows, and both vendors' kinds map to the consolidated basis (`VOLUME_BASIS_BY_VENDOR_KIND`: `(alpaca, sip_rth)` and `(massive, canonical)` are both consolidated). Pass: `SELECT count(*) FROM market_data_ohlcv_tradeable WHERE timeframe = '1d' AND vendor = 'ibkr'` is 0 and the span holds one volume basis value. Fail: any ibkr row, which the guard would mask loudly; the family waits.
3. No NULL volume mid-series (todo 563). Pass: no 1d row in the tradeable view over the span has NULL volume (the 145 names of todo 563 held IBKR fallback rows that step 7 removes). A name with a NULL is listed and masked, never filled.
4. Massive against Alpaca volume, a precondition of the seam and the forward confirmation, not of the discovery run (the scored span is Massive only; ledger 2026-11-23e: passes on 2024 to 2026, Alpaca 2016 to 2022 is a different basis and disclosed). Measured 2026-11-15 on raw before step 7 finishes: over 305,718 name-days of 2026 where both vendors have a positive 1d volume, the ratio Massive over Alpaca has median 0.99993, 5th percentile 0.9985 and 95th percentile 1.0005. Re-run after D1 and again at the forward confirmation; pass when the median stays within 0.99 to 1.01 and the 5th to 95th percentile within 0.95 to 1.05 (pre-declared). A larger shift means a basis change the guard does not know, and the confirmation waits.
5. Volume continuity across splits (amended 2026-11-23, ledger 2026-11-23e: the prior band tested real volume dynamics, not a rescale defect). Two parts, both must pass. (a) The original median bound is kept: over the post-D1 split dates in the span, the median session-after over session-before dollar-volume ratio is within 0.8 to 1.25 (measured 2026-11-23: 1.0599, passes), which catches a wrong rescale that is not near the split factor. (b) The near-factor defect test replaces the 2 percent outside 0.25 to 4 clause: over the same events, the share whose session-after over session-before dollar-volume ratio (close times volume) lies within 25 percent of the split factor or its inverse (an unrescaled volume) is at most 2 percent. Measured 2026-11-23: 43 of 3,133 events (1.4 percent), listed in `docs/research/family10-gate5-near-factor-events.md`; the other 284 of 327 events outside 0.25 to 4 are real volume jumps. This proves canonical rescales volume with the price, so a rank inside a window is scale free.
6. Zero volume. The tradeable view drops volume-zero bars (no trade), so a thin name has fewer than 50 positive sessions in a 50-session window; the member rule in section 3 (at least 40 positive sessions) handles it, and the run reports each name's share of masked rows.
7. Build requirements: two kernels in a new volume_shock module under the research families package (pure functions over arrays), unit tests for the rank, the tie rule, the window edge, the residualization and the causality probe; B2 H0 battery cells for both members (size at 0.05, 0.01, 0.00167 over 1,000 simulations per cell) and the static-size precondition on the real membership panel; B3 power statement per member; the spec added to the pinned spec-hash test.

## 7. Disclosed prior looks and overlap

- Todo 304 `volume_pct` (expanding percentile rank of `rel_volume`) is DEAD as a per-symbol regime: it did not sharpen IC beyond `regime_volatility` under the null-arm standard. That was a conditioning test, not a member test, but it is a seen look on the same quantity.
- H-A `extreme_volume_divergence` FAILED (15m, within-symbol, light volume at fresh price extremes): a different clock and mechanism, but a seen look on volume.
- Corpus `volume_z` and `rel_volume` have seen corpus IC on the 231 names; the holdout excludes those names from both panels.
- Trade count would sharpen the member (IDEAS bullet 2026-11-09) but is not stored; do not wait for it.

## 8. Ledger entry and owner adoption

**Draft entry for `docs/plans/methodology-change-ledger.md` (E24, written before any real-data result):** "Registration of family 10's two daily-clock volume-shock members on the stage 2 universe. Counted design choices: the 50-session and 5-session windows, the cross-sectional orthogonalization to the same-session return and its absolute value (a transfer of the paper's condition), the 40-of-50 positive-volume rule, the membership and core panels (two series per member), the seen-name holdout, h = 5 only, StepM detection at 0.05 as the only pass. Looks declared: 4 series (section 5). Pre-registered by construction: no real-data number exists. Moves no recorded spec hash."

**Owner adoption line:** adopt family 10's daily-clock registration (this draft, ledger entry E24, and the pre-declared basis gates of section 6). Lead recommendation: adopt. Sequence: it follows the three families of the top-three drafts and shares their gate; it adds 4 series (12 plus 4 = 16 across the four registrations).

## 9. Not registered here

The stored intraday members of family 10, the 5m versions and h = 21 (todo 547) are separate registrations. A book that combines these members with others is its own registration (combiner, missing-member rule, construction, book memory) and carries the promotion test: positive net expectation at measured costs (todo 553 kernels), then one forward confirmation after the book's freeze.
