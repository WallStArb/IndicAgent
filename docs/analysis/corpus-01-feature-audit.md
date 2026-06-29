# CORPUS-01: Feature Distribution Audit

**Date:** 2026-06-29
**Corpus:** V1-corrected (Phase 141 P0)

## Audit Criteria

- **(a) Variance > epsilon (1e-12):** No silent constants. A feature is BLOCKED only if ALL symbols have variance <= epsilon.
- **(b) NaN rate < 5% post-warmup:** Excludes first 100 bars per symbol.
- **(c) No distributional cliff:** Not implemented (WARNING criterion only).

## Disposition Legend

- **PASS:** All criteria met
- **BLOCKED:** Fails criterion (a) - ALL symbols have variance <= epsilon. These features are excluded from IC measurement.
- **WARNING:** Fails criterion (b) or (c) - flagged for review but NOT dropped (Renaissance principle: never drop data that could contain signal).

## Per-Feature Audit Table

| Feature | Variance Pass | Min Variance | Max Variance | Symbols w/ Zero Var | NaN Rate % | NaN Pass | Disposition |
|---------|---------------|--------------|--------------|-------------------|------------|----------|------------|
| vix_z | PASS | 1.328630097916907 | 1.6305495761838644 | 0 / 58 | 0.00 | PASS | PASS |
| above_wk_vwap | PASS | 0.21912688288729068 | 0.24999886939349097 | 0 / 58 | 0.00 | PASS | PASS |
| vol_ratio | PASS | 0.11537802542406703 | 0.16780168361581074 | 0 / 58 | 0.00 | PASS | PASS |
| adx | PASS | 492.6405542365277 | 1831.3927523293535 | 0 / 58 | 0.00 | PASS | PASS |
| volatility_rank_z | PASS | 0 | 0 | 0 / 58 | 100.00 | FAIL | WARNING |
| amihud_illiq_z | PASS | 0 | 0.17610960395288533 | 28 / 58 | 0.00 | PASS | PASS |
| aroon_fast | PASS | 0.04386413189277671 | 0.1095650347906171 | 0 / 58 | 0.00 | PASS | PASS |
| volume_rank_z | PASS | 0 | 0 | 0 / 58 | 100.00 | FAIL | WARNING |
| aroon_slow | PASS | 0.06045167001783315 | 0.12678346778923433 | 0 / 58 | 0.00 | PASS | PASS |
| volume_z | PASS | 0.39928844237795114 | 0.514673898506129 | 0 / 58 | 0.00 | PASS | PASS |
| atr_z | PASS | 1.693812628020258 | 1.8895494925681122 | 0 / 58 | 0.00 | PASS | PASS |
| vwap_dev_sigma | PASS | 1.8136320983645526 | 4.70621888623767 | 0 / 58 | 0.00 | PASS | PASS |
| yield_slope_z | PASS | 0.8153949893162182 | 0.981161605497662 | 0 / 58 | 0.00 | PASS | PASS |

## Summary

- **Total features audited:** 64
- **BLOCKED:** 0
- **WARNING:** 10
- **PASS:** 54

## Notes

- Variance audit is per-symbol: a feature is BLOCKED only if ALL symbols have variance <= epsilon.
- NaN rate is computed post-warmup: first 100 bars per symbol are excluded.
- BLOCKED features are excluded from IC measurement: IC is undefined for constant series.
- Cross-sectional features (momentum_rank_z, volume_rank_z, volatility_rank_z) show 100% NaN rate because they are populated by the equity_regime_model service, not feature_factory. This is expected.
| bar_close_pos | PASS | 0.017105624834439837 | 0.045232293271005766 | 0 / 58 | 0.00 | PASS | PASS |
| cci_fast | PASS | 2689.679870693676 | 3358.297380500225 | 0 / 58 | 0.00 | PASS | PASS |
| cci_mid | PASS | 5637.9420886141625 | 8233.519375311096 | 0 / 58 | 0.00 | PASS | PASS |
| cci_slow | PASS | 14068.755533234415 | 19538.85157311382 | 0 / 58 | 0.00 | PASS | PASS |
| cmf | PASS | 0.01596537822463973 | 0.12571976514174482 | 0 / 58 | 0.00 | PASS | PASS |
| ctf_momentum | PASS | 0.1867467508820807 | 0.2847078527996161 | 0 / 58 | 0.00 | PASS | PASS |
| ctf_regime_align | PASS | 0 | 0.0612981082516377 | 3 / 58 | 0.00 | PASS | PASS |
| ctf_vwap_align | PASS | 0.0019909297141512783 | 0.9975179233053948 | 0 / 58 | 0.00 | PASS | PASS |
| cvd_slope_z | PASS | 0.46844926271612564 | 0.6731783640647031 | 0 / 58 | 0.00 | PASS | PASS |
| days_to_month_end | PASS | 0.0824369781512713 | 0.08300381022313999 | 0 / 58 | 0.00 | PASS | PASS |
| dow_cos | PASS | 0.37608341588838584 | 0.37669569143134646 | 0 / 58 | 0.00 | PASS | PASS |
| dow_sin | PASS | 0.5415520977683969 | 0.542088776762822 | 0 / 58 | 0.00 | PASS | PASS |
| flight_quality | PASS | 0.3364155083274741 | 2.0215411489827178 | 0 / 58 | 0.00 | PASS | PASS |
| gap_z | PASS | 0.5300667713140464 | 0.963357326856976 | 0 / 58 | 0.00 | PASS | PASS |
| garch_ratio | PASS | 75.72688025792436 | 7204.491396533153 | 0 / 58 | 0.00 | PASS | PASS |
| high_52w_dist | PASS | 4.195573388728768e-07 | 0.0008890173998334676 | 0 / 58 | 0.00 | PASS | PASS |
| hma_slope_z | PASS | 0.9491297748884652 | 1.0626708311453388 | 0 / 58 | 0.00 | PASS | PASS |
| hmm_duration | PASS | 32261.179627933372 | 18342160931.491085 | 0 / 58 | 0.00 | PASS | PASS |
| hmm_entropy | PASS | 9.184046670871729e-08 | 0.09961393704669708 | 0 / 58 | 0.00 | PASS | PASS |
| hmm_prob_ranging | PASS | 0.04282544637408168 | 0.2497764553735645 | 0 / 58 | 61.72 | FAIL | WARNING |
| hmm_prob_trending_down | PASS | 0.11052815682954349 | 0.24824973492486702 | 0 / 58 | 61.72 | FAIL | WARNING |
| hmm_prob_trending_up | PASS | 0.08514236324480014 | 0.24766292461303815 | 0 / 58 | 61.72 | FAIL | WARNING |
| hmm_regime_prob | PASS | 6.358705032437726e-09 | 0.03874525951599972 | 0 / 58 | 0.00 | PASS | PASS |
| hurst | PASS | 0.0012891763691943673 | 0.009705922766949525 | 0 / 58 | 0.00 | PASS | PASS |
| in_london_kz | PASS | 0.10866410322592654 | 0.10917529536106511 | 0 / 58 | 0.00 | PASS | PASS |
| in_ny_session | PASS | 0.19522878060249657 | 0.196751064610275 | 0 / 58 | 0.00 | PASS | PASS |
| in_overlap | PASS | 0.10868503948377821 | 0.10924729276926001 | 0 / 58 | 0.00 | PASS | PASS |
| informed_flow | PASS | 0.22313319732115816 | 0.6247182057011983 | 0 / 58 | 0.00 | PASS | PASS |
| momentum_rank_z | PASS | 0 | 0 | 0 / 58 | 100.00 | FAIL | WARNING |
| momentum_reversal_z | PASS | 0.9934857002289388 | 1.3361491120472917 | 0 / 58 | 0.00 | PASS | PASS |
| momentum_z_fast | PASS | 1.3748045453259248 | 1.5644877749429844 | 0 / 58 | 0.00 | PASS | PASS |
| momentum_z_mid | PASS | 1.6229724824788783 | 1.8417859860200867 | 0 / 58 | 0.00 | PASS | PASS |
| momentum_z_slow | PASS | 1.6243862035110201 | 1.771054919495902 | 0 / 58 | 0.00 | PASS | PASS |
| month_position | PASS | 0.08243697815127181 | 0.0830038102231401 | 0 / 58 | 0.00 | PASS | PASS |
| ofi_div | PASS | 1.3534814051965323 | 1.9394557407199722 | 0 / 58 | 0.00 | PASS | PASS |
| ofi_z | PASS | 0.37714258507627263 | 0.5071655986248231 | 0 / 58 | 0.00 | PASS | PASS |
| opening_range | PASS | 0.055680370466722626 | 0.057456228232634084 | 0 / 58 | 0.00 | PASS | PASS |
| poc_dist_atr | PASS | 0 | 0 | 0 / 58 | 100.00 | FAIL | WARNING |
| power_hour | PASS | 0.07586614857856451 | 0.0762912402981643 | 0 / 58 | 0.00 | PASS | PASS |
| quarter_position | PASS | 0.079199550688587 | 0.08103603946009355 | 0 / 58 | 0.00 | PASS | PASS |
| range_position | PASS | 0.07645246974298009 | 0.15377774952624965 | 0 / 58 | 0.00 | PASS | PASS |
| rel_volume | PASS | 2.1309450444457307 | 3.649264278117642 | 0 / 58 | 0.00 | PASS | PASS |
| ret_acf1_z | PASS | 1.450452737986597 | 1.7799771716697006 | 0 / 58 | 0.00 | PASS | PASS |
| ret_skew_z | PASS | 1.2378097996691049 | 1.4462885462256037 | 0 / 58 | 0.00 | PASS | PASS |
| rsi_fast | PASS | 705.6850736941947 | 867.7555802605302 | 0 / 58 | 0.00 | PASS | PASS |
