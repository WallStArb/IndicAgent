# Readiness note: shortlist item 5 (realized skewness and semivariances from 5m bars)

**Status:** note 2026-11-15, not a registration. It lists what must be true on the 5m tier and on the cost side before item 5 is registered, so the registration can be written the day those hold. Source: `docs/ideas/signal-published-prior-shortlist.md` item 5; tier design `docs/plans/2026-11-15-stage2-5m-tier-and-intraday-universe.md`.

## What item 5 needs that the daily families do not

Two members on the daily clock built from 5m log returns over the past 5 sessions: RSkew (Amaya, Christoffersen, Jacobs and Vasquez 2015; lowest minus highest decile earns 19 bp a week, t 3.70) and the normalized difference of realized up and down semivariances (Bollerslev, Li and Zhao 2020). In-session returns only, so the overnight gap never enters. Both are pure kernels over the 5m panel aligned to the daily clock (S2b). It is the one shortlist item where costs bind: weekly full turnover.

## Must be true on the tier side (all mechanical, before registration)

1. The 5m tier amendment is adopted by the owner ($25M entry, $12.5M exit, nested in the membership) and the writer rule id is `stage2-2026-11-15` or the amended one.
2. Migration 597 is applied and `universe_membership` is built with `tier_5m`; the member and tier counts by year are shown to the owner. Expected from the design table: about 1,313 tier members at a typical month-end (571 to 2,539), 5,525 names ever in the tier.
3. The measured 5m cost estimate is recorded as the amendment's last step before the first tier load: rows per name-year, feature-compute time per name-year and disk, taken on the 5m already loaded for current names. Planning figures to beat or revise: 46k whole-history name-years, 0.6 to 0.9 billion 5m rows. Until it exists the tier load does not start.
4. The tier's 5m is loaded from the Massive minute archive (86.8 GB, already acquired, aggregated to 5m by our reader) through the load engine with the per-year compare gate, and the corpus rerun's 5m data gate passes on tier names with `corpus_universe(conn, intraday=True)`; the 1d-only era term and the non-tier names carry no 5m term (`corpus_rerun_data_gate`, L3).
5. 5m sessions per tier name-year pass `max_missing_session_fraction` (0.01) and each session's bar share passes `min_session_bar_fraction` (0.9). Massive emits no bar for a bucket without trades and the loader never fills, so the sparsest tier names carry the most NaN; the registration reports per-name valid-session share and masks, never fills.
6. The volume and price basis over 5m is one basis (consolidated), checked as in the family 10 draft section 6, items 2 to 4, on 5m rows.
7. IC wiring I1 landed with the 5m reader declared per timeframe (`corpus_universe(conn, intraday=True)`), `check_ic_universe_aligned` passing, and the 5m tier panel exists in two forms (tier point in time and tier core), each member a counted series on each: 2 members times 2 panels = 4 series.
8. Todo 583 (HMM regime outputs NULL on whole names) fixed before any regime disclosure; the seen-data disclosures below listed in the registration.

## Cost side

Trading cost never enters the statistic and never gates registration (E18: costs gate promotion only), so none of this blocks the counted test; it decides whether a detection is worth acting on and should be in hand so the verdict reads correctly.
- Half-spreads on the tier names through the todo 553 kernels (Corwin-Schultz and Roll) on tier names' daily bars, and the quote-free 5m proxies. The only measured spreads today are 1.5 to 1.9 bp (233 names) and 3.6 to 4.9 bp (the other 201); tier names reach down to $12.5M a day and will sit above the first group.
- Arithmetic to state in the registration, with the published number halved (the working haircut): 19 bp a week gross becomes about 9.5 bp. A long-short book turning over fully each week pays about two legs times two crossings of the half-spread, so 1.5 to 4.9 bp half-spreads cost roughly 6 to 20 bp a week. On those figures a detection most likely fails promotion unless a pre-declared buy-hold band cuts turnover (Novy-Marx and Velikov 2016); the band is a construction choice and is its own counted look if it is added later.
- Recommendation: register item 5 after the tier is built and the 5m data gate passes, without waiting for costs, but record the measured tier half-spreads and the break-even arithmetic in the registration so the verdict says in advance what it must beat.

## Seen data the registration must disclose

`jump_diffusion_decomposition` is DEAD (a per-symbol time-series test on a SPY 15m pilot, not a cross-sectional weekly one); corpus `ret_skew_z` has seen corpus IC; todo 445's counted 5m look (run 2026-09-28: 240 features at 2 horizons on 233 `compute_eligible` names, 2016-01-01 to `oos_start`, 176 of 480 cells BH-significant, only `ret_autocorr_1` and `sweep_detected` clearing the cost hurdle) read 5m-derived features on this panel. The seen-name holdout applies.

## Ledger

Item 5 takes the next free methodology-change entry id at its registration (E25 if E24 is family 10's), written before any real-data result, with the looks count of 4 series (2 members, 2 tier panels) at h = 5.
