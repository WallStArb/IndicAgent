# Pre-registration draft: family 9, 52-week-high anchoring on the daily clock

**Status:** DRAFT 2026-11-15, unapplied. Nothing here is registered, built or run, and no real-data number exists for the member. It becomes a registration only after the owner adopts it (adoption line, section 8), its build requirements land and the data gate (section 6) passes. A value changed after a real-data number is a methodology change.
**Author:** Claude (indicagent-65), 2026-11-15, on the lead's brief (ranked item 2 of `docs/ideas/ranked-backlog-2026-11-15.md`).
**Informed by:** `docs/plans/2026-11-15-published-prior-top3-prereg-drafts.md` (the shared frame, section 2, which this draft inherits unchanged except where it says so), `docs/plans/2026-11-15-family10-volume-shock-prereg-draft.md` (the form), `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md` (the family this joins in universe and target), `docs/research/construction-verdict-ledger.md` (family 9 row, section 4 row for `bars_since_high_fast_xs_ls_h5`, section 5 corpus IC look), `docs/plans/2026-11-13-stage2-universe-preregistration.md` (the universe), `docs/plans/methodology-change-ledger.md` E17, E18 and E21.
**Governing rules:** E17 (decision statistic), E18 (every attempt counted, Romano-Wolf StepM selection, net-expectation promotion, one forward confirmation per book), E21 (every measured cell counted).

## 1. Scope: what this registers and what it leaves

Ledger family 9 (price anchoring and slow reversal) lists seven pending members (`vwap_dev_sigma`, `high_52w_dist`, `rsi_slow`, `aroon_slow`, `price_percentile_slow`, `stoch_k_slow`, `dist_from_high_slow`). The pooled corpus look found them to be one mechanism, price position inside the recent range (ledger section 5), so seven members would be one bet counted seven times and would dilute StepM. Musk step 1 on the requirement: the requirement is one test of whether nearness to the 52-week high predicts residual returns, so this draft registers one member, the ratio of George and Hwang. The other six are not registered here; any of them can enter later as its own counted variant.

The stored columns `high_52w_dist` and `dist_from_high_slow` are not read. The stored `high_52w_dist` is price-only and fills a partial window during warmup (`_high_52w_dist_series_full` uses `min(window, b + 1)` and writes 0 at the first bar), which the `no_fill` invariant forbids; `dist_from_high_slow` is ATR-normalized with a window set by an APR key, not by the paper. The member is a research-layer kernel over total-return closes.

## 2. Hypothesis and expected sign, stated before any run

Published: nearness to the 52-week high predicts future returns better than past returns do, including individual and industry past returns, and the returns it forecasts do not reverse over the long run (George and Hwang 2004, Journal of Finance 59(5), pp. 2145 to 2176; [paper](https://www.bauer.uh.edu/tgeorge/papers/gh5-paper.pdf); abstract level, not rechecked against the full text in this lane). The proposed mechanism is anchoring: traders treat the 52-week high as a reference price, so good news is under-reacted to near it.

Expected sign, pre-declared: positive. A name closer to its own 52-week high has a higher subsequent residual return than one far below its high. The member below is defined so that a larger value means nearer the high.

Against, stated before the run:
- The corpus read the same mechanism with the opposite sign: pooled raw IC of `high_52w_dist` is -0.058 at 1d horizon 10, with 0 or 1 of 227 names passing FDR (ledger section 5). The registration does not adopt that sign. A significant negative result is an opposite-sign finding: counted, not promoted, and never turned into a reversed hypothesis.
- Published decay (the shortlist's discount): portfolio returns of published predictors are 26% lower out of sample and 58% lower after publication (McLean and Pontiff 2016), and 65% of 452 anomalies fail a t of 1.96 with microcaps controlled (Hou, Xue and Zhang 2020). The stage 2 universe has a $1M entry floor, so it reaches far below the large-cap range those value-weighted figures describe. Our inference: expect a small effect.
- Horizon mismatch. The paper's holding period is six months. This registration reads h = 5 only (the family's horizon, the only one with a recorded size cell until todo 547 lands). A null at h = 5 is not a null of the paper's claim; h = 21 and h = 63 are separate registrations that wait for todo 547.

## 3. Member (one, a research-layer kernel over total-return closes)

| Member | Statistic for row d | Sessions read | Sign |
|---|---|---|---|
| F1 `high_distance_252` | (c[d] - max(c[d-251..d])) / max(c[d-251..d]), where c is the total-return close | 252 | +1 |

- The value is at most 0, equal to 0 on a new 52-week high. Sign +1 means nearer the high ranks higher.
- c is the total-return close (`panel.total_return: {suspect_yield: 0.10}`), so an ex-dividend drop does not count as a fall from the high; outside `dividend_event_coverage` dividends are unknown, never zero, and those names use the price-only close with a flag counted in the disclosure.
- F1 is NaN when fewer than 240 of the 252 sessions have a finite close (a missing session can hide the high), or when the maximum is not positive. No fill, no partial window.
- The member reads bars through d's close; the target enters at d+1's open, so the member reads nothing inside the target window.
- The window of 252 sessions and the 240-of-252 rule are pinned and never swept; both are counted design choices (section 8). Declared memory: slot history 252 plus S1's 252 + 21 sessions, 525 rows, the same as the momentum members, so the scored start is the same (section 4).
- The paper builds the ratio from month-end prices; the daily form is this registration's transfer, as the daily residual family transfers its own papers.

Overlap, declared. Nearness to the high is positively related to 12-1 momentum (George and Hwang argue the ratio subsumes it) and to the last month's return, so F1 is correlated with M1 and M2 of the daily residual family and with the mirror of R2 (names near the high have just risen). The run reports the session-average cross-sectional Spearman correlation of F1 with M1, M2, R1, R2 and R3 as a disclosure that gates nothing. StepM's joint bootstrap prices the dependence, and the combiner, not this registration, weighs the members inside a book. The family 4 overlap is declared so one reversal edge is not counted twice.

## 4. Spec, universe, target and span

- Machine form: the spec file family9_high_anchor_h5.yaml (to be written), `kind: family`, `family: family9_high_anchor`, horizon 5, `factor_spec: vintage_1`, the one member above with `signal: src.intelligence.research.families.high_anchor.<function>`, construction R1 `rank_vol_neutral` (direction +1, coverage floor 20, 60-session residual vol, at least half finite), `timing_statistic: e17` with L = memory plus h, `session_scoring: true`, `min_shift: 63`, `bootstrap_mean_block: 21`, `bootstrap_reps: 2000`, `seed: 183`, guard seed 183, same scoring block as `daily_residual_h5.yaml`.
- Universe, target, span, family and guard config, pass and fail rule, costs and the forward-span rule: exactly the shared frame of the top three drafts, section 2. In brief: `universe_membership` and `universe_membership_core` panels, the member a counted series on each; the seen-name holdout applies; `panel.forward_returns` residualized by S1 with the forward-horizon lag; panel start 2005-01-03, end exclusive 2025-12-24 (the forward span is never read); scored start 2007-03-01; sub-periods 2007-03-01 to 2011-12-31, 2012 to 2018, 2019 to 2025-12-23, reported not voted.
- Detection: the member's E17 statistic, one-sided positive, is in the Romano-Wolf StepM rejection set at 0.05 over the vintage selection universe. An opposite-sign result is recorded as counted, not promoted.
- The seen-name holdout excludes the 231 names the 2026-09-13 screen read and the 13-name cross-asset set, by the pinned list the daily residual family defines (B1). This matters here more than for the other drafts: the corpus IC look that suggested the opposite sign was read on the 227 intraday-scope names, the seen set the holdout excludes, so the holdout keeps this test off the data that set the suspicion. If the owner declines the holdout, the registration discloses that the opposite-sign suspicion was formed on about 5 percent of the panel.

## 5. Looks, declared before any run

| Members | Horizons | Panels | Series added |
|---|---|---|---|
| 1 (F1) | 1 (h = 5) | 2 (primary, core) | 2 |

h = 21 and h = 63 wait for todo 547 and are separate registrations. Cells of E21 sweeps that touch `high_52w_dist`, `dist_from_high_slow` or `bars_since_high` join the same universe under their own `n_looks` declaration; the registration lists those runs by id or states the sweep had not read them. Declaring one member instead of the ledger's seven is a design choice that lowers the count; it is recorded, not hidden.

## 6. Data gate, in order

1. The shared gate of the top three drafts, section 5, items 1 to 5 (step 7 D1, stage 2 gates, corpus rerun data gate for 1d on the membership names, I1 wiring, S1 regenerated), with the clean-data rule lifted by the owner for this family.
2. Split continuity over the 252-session window. A split inside a window must not read as a collapse from the high. Pass: the D4 audit left no new red `split_continuity` (the step 7 D4 gate), and the todo 615 check over placed ticker pairs has run (a missing split row for a renamed name would manufacture a false fall from the high). Fail: the family waits for the affected names to be masked by the existing guard.
3. Dividend basis. Pass: `panel.total_return` is declared with `suspect_yield: 0.10`, the family 9 guard in `tests/unit/research/test_dividends.py` passes, and the share of scored rows outside `dividend_event_coverage` is reported. A high-yield name on a price-only close would manufacture a signal, so those rows are flagged and counted in the disclosure.
4. Close convention in 2005 to 2007. The scored span starts 2007-03-01, but the first 252-session windows read 2005 to 2007 closes, the era whose Massive close convention needs a third witness (todo 610). Pass: that witness is resolved, or the run reports F1 with and without the first windows as a disclosure (the sensitivity gates nothing and adds no series, because it re-reads the same member cells).
5. Window and warmup. The run reports each name's first finite row and the memory guard holds (S3 guard: no output earlier than 252 sessions allows).
6. Build requirements: one kernel (`high_distance`) in a new module under the research families package (pure function over arrays), unit tests for the sign, the window edge, the 240-of-252 rule, split-rescale invariance and the causality probe; a B2 H0 battery cell for the member (size at 0.05, 0.01, 0.00167 over 1,000 simulations per cell) and the static-size precondition on the real membership panel; a B3 power statement for the member; the spec added to the pinned spec-hash test.

## 7. Disclosed prior looks and overlap

- Corpus IC term structure, 2026-09-25 (ledger section 5): `high_52w_dist` -0.058 at 1d horizon 10 (pooled, raw, vintage 1), with `vwap_dev_sigma` -0.061, `rsi_slow` -0.052 and `price_percentile_slow` -0.046; 0 or 1 of 227 names FDR-passing. One mechanism, opposite to the registered sign, read on the intraday-scope names that the holdout excludes.
- `bars_since_high_fast_xs_ls_h5` is DEAD (2026-09-11): the cross-sectional long-short on bars since the rolling high had negative gross return (mean -0.0004 per rebalance) despite a pooled regime-averaged IC of 0.1118, and the apparent support decomposed across four unrelated regime taxonomies. It is a different feature (bars since the high, not distance) and a different construction (a regime-gated cross-section), but it is a seen look on the same neighborhood and a published prior of failure for this idea on that panel.
- The 2026-09-13 screen found a negative-IC hint on a 14-period RSI at 1d (the daily residual prereg section 6); its names are excluded by the holdout.
- No residual-target quantity for F1 has been measured, and the forward span has not been read.

## 8. Ledger entry and owner adoption

Entry ids: E25 is reserved by indicagent-c6 for item 5 (realized semivariance), so this draft takes E26. E27 stays free for the next registration.

**Draft entry for `docs/plans/methodology-change-ledger.md` (E26, written before any real-data result):** "Registration of family 9's one 52-week-high member on the stage 2 universe. Counted design choices: the single member F1 (the ledger's seven pending members reduced to one by Musk step 1), the 252-session window and the 240-of-252 finite rule, the total-return close, the pinned positive sign against the seen opposite-sign corpus look, the membership and core panels (two series), the seen-name holdout, h = 5 only, StepM detection at 0.05 as the only pass. Looks declared: 2 series (section 5). Pre-registered by construction: no real-data number exists. Moves no recorded spec hash."

**Owner adoption line:** adopt family 9's daily-clock registration (this draft, ledger entry E26, and the pre-declared gates of section 6). Lead recommendation: adopt. Sequence: it follows the daily residual family and shares its gate; it adds 2 series (12 plus 4 plus 2 = 18 across the published-prior drafts and this one; the daily residual family's reversal members R1 to R3 are already inside its own 10 series).

## 9. Not registered here

The other six family 9 members, h = 21 and h = 63, the stored columns, the ATR-normalized form and any regime-conditioned form are separate registrations. A book that combines F1 with other members is its own registration (combiner, missing-member rule, construction, book memory) and carries the promotion test: positive net expectation at measured costs (todo 553 kernels), then one forward confirmation after the book's freeze.
