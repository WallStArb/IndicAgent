# Phase 181 pre-registration: time-series momentum on the cross-asset sleeve

**Author:** Claude (Opus 5.5), 2026-09-24, at Brandon's request; parent plan
`docs/plans/2026-09-24-edge-proof-program.md` ("Phase 181 queue", candidate 1; todo 419).
**Status:** FROZEN 2026-09-24 by the commit that adds this line, before any real-data number
for this signal existed. Harness code: b01eb751a plus a docstring-only change in the same
commit. Any change from here is a `methodology-change-ledger.md` entry. Code review
(`/code-review`, 2026-09-24): no correctness findings; shift bound, causality and phase 179
bit-identity independently confirmed.

## 1. The question

Does classic time-series momentum on the 13-symbol cross-asset sleeve carry timing information
beyond a time-shifted copy of the same signal?

The comparator is the phase 179 null: the whole signal panel circularly shifted, with the
portfolio rerun on every copy. A copy keeps the signal's distribution, persistence and
cross-asset structure; only its alignment with future returns is broken. Being long an asset
that drifted up over the sample earns the same in the real and the shifted runs, so drift gets
no credit. A PASS therefore means trend timing, which is stricter than the published TSMOM
evidence (Moskowitz, Ooi and Pedersen 2012; Hurst, Ooi and Pedersen 2017), whose returns include
the drift.

Verdict token: `TSMOM_VERDICT = ACT | PASS | FAIL`. `FIDELITY` is not issued: the signal has no
fitted parameters, so there is no production method to reproduce (phase 179's V4 does not
apply). A degenerate null (section 5) still issues no token.

## 2. Why now

- Never tested. The 2026-09-13 "TSMOM screen" measured `ctf_momentum`, which at 1d is a
  14-period RSI, against a 2-session forward return (ledger note corrected 2026-09-24).
- Highest prior in the queue: a documented premium across a century and every asset class, with
  a mechanism (slow diffusion of information and hedging demand), on exactly the kind of
  cross-asset basket the sleeve is.
- Independent of todo 418: no refit, no production-fidelity question.

## 3. What is held fixed

| Item | Value | Source |
|---|---|---|
| Sleeve | GLD, DBA, DBB, DBC, URA, TLT, UUP, VIXY, EMLC, HYG, XOM, DHI, PGR | Phase 179 section 3 (Phase 174 Gate A, correlation-only: not selected on momentum) |
| Signal | `alpha[d, i] = ln(close[d, i] / close[d-252, i])`, closes from `market_data_ohlcv_tradeable` 1d | MOP 2012's 12-month lookback, no skip month (the skip is an equity-reversal adjustment) |
| Direction | +1 (long when the trailing return is positive), pinned | Theory |
| Construction | `w_i = sign(alpha_i) / sigma_i` over the calibration refit's admitted symbols, normalized to gross 1; missing alpha gives no position | MOP 2012's sign-and-volatility construction (`portfolio.fixed_sign_returns`) |
| Volatility | `sigma_i` from the phase 179 covariance plan: trailing 504-session close-to-close log returns through d-2, refit every 252 sessions, symbols below 95% coverage not admitted | Reused unchanged |
| Execution | Signal at d's close, enter at d+1's open, exit at d+2's open (`score.forward_returns`); gross returns | Invariant 1 |
| Panel | Sessions from the first session of 2011 to the last before `alpha.validation.oos_start` (2025-12-24), the phase 179 S2 span | Same shifts, warmup and trading window as 179 |
| Trading span | 2013-01-01 to 2025-12-23; sub-periods 2013-2016, 2017-2020, 2021-2025 | Phase 179 section 7 |
| Data | A fresh S0 snapshot (`run --stage s0`, `end_exclusive` = 2025-12-24T05:15Z) built after the freeze commit; its content hash is recorded with the result | See section 7 on the calendar |

Not tested, so not a forking path later: the continuous (unsigned) signal, the 12-1 skip
variant, other lookbacks, the phase 179 calibrated arms, costs.

Why not the calibrated arms: on synthetic panels with a planted persistent trend, they short the
trend (excess Sharpe -1.0 where the fixed-sign book earns +2.2 at the same planted strength,
2026-09-24, seed 0). They learn each symbol's IC sign and size from a trailing 504-session window,
and for a slow signal whose own innovations are the returns, that in-window IC is noisy and
biased (Stambaugh). A theory-signed construction removes the fit.

## 4. Architecture

Reuses the phase 179 harness; no production table is read after S0 or written ever.

```
S0 snapshot (read-only, content-hashed)
  -> s2sig --signal tsmom: signals.tsmom over sleeve closes, S2-shaped artifact
  -> s3: evaluate() with construction = fixed_sign_returns(direction=+1), memory-aware shifts
  -> s4 --n-tested 18: decide() -> verdict JSON
```

Commands (worker count free, results are deterministic):

```
python -m scripts.analysis.sleeve_walk_forward.run --stage s0 --out-dir logs/phase181
python -m scripts.analysis.sleeve_walk_forward.run --stage s2sig --signal tsmom --in logs/phase181/snapshot_<h> --out-dir logs/phase181
python -m scripts.analysis.sleeve_walk_forward.run --stage s3 --in logs/phase181/s2sig_<h>.pkl --out-dir logs/phase181 --workers 12
python -m scripts.analysis.sleeve_walk_forward.run --stage s4 --in logs/phase181/s3_<h>.pkl --out-dir logs/phase181 --fidelity OK --n-tested 18
```

`--fidelity OK` is the flag's only meaning here: no fidelity gate applies (section 1).

## 5. Null and statistic

- Statistic: annualized Sharpe of the daily gross book return over the trading span. One arm,
  so the Westfall-Young adjustment reduces to the plain permutation p:
  `(1 + #{k: S_k >= S_obs}) / (1 + K)`.
- Null: whole-panel circular shifts `out[t] = alpha[(t - k) mod n]` for
  `63 <= k <= n - 63 - 254`. The upper bound is new (`admissible_shifts(..., memory=254)`): for
  `t < k` the copy comes from `n - k` sessions later, and a 252-session trailing return read from
  within 254 sessions after t contains t's target return (the signal's lookback plus the
  return's two-session span). Those copies would see the answer; on the synthetic trend panel
  their median Sharpe was 1.60 against 1.21 for the rest. About 3,370 shifts remain.
- Shifts near the 63 floor share about 75% of the 252-session window with the real alignment,
  so the null keeps part of any real trend edge. That makes the test stricter, never looser;
  V3 measures the power it costs.
- Excess: `S_obs - median(S_null)`. Stability: mean daily excess over the null median in each
  sub-period. Reported CI: stationary bootstrap, mean block 21. All as phase 179.
- A degenerate null or an undefined Sharpe issues no token (`safe_evaluate`).

## 6. Decision rules

N_tested = 18: the ledger's 16 verdicted rows, phase 179's sleeve test (registered, pending) and
this test. Counted at the time of use, per the ledger's rule; if another verdict lands before
this run, N_tested rises with it and is recorded.

| Token | Condition |
|---|---|
| `FAIL` | p >= 0.05, or excess positive in fewer than 2 of the 3 sub-periods |
| `PASS` | p < 0.05 and excess positive in at least 2 of 3 sub-periods |
| `ACT` | PASS with p < 0.05 / 18, and the section 8 holdout excess positive |

- PASS opens a forward shadow run of the frozen construction and a breadth re-test with phase
  180's expanded universe. ACT also opens sizing work for a live sleeve (v4.0 phase 156 scope).
  FAIL closes classic TSMOM on this sleeve; the variants in section 3's "not tested" list stay
  closed with it rather than becoming the next attempt.
- Costs never change the token (standing directive); turnover and a cost band are reported.

## 7. Residual biases stated in advance

- **Short histories.** TLT's 1d history starts 2016-02-03 (IBKR returns nothing earlier,
  `ohlcv_empty_history` verified; phase 179 section 14 says 2017, the table says 2016-02-03).
  VIXY starts 2011-01-04, EMLC 2010-07-26, URA 2010-11-05. Each enters the book once the
  covariance plan admits it (95% coverage of the 504-session window), so the early book is
  thinner, and the Treasury leg, historically one of TSMOM's best, is absent until about 2018.
  This biases toward FAIL.
- **Survivorship.** All 13 symbols trade today (todo 376). A sleeve chosen from survivors misses
  funds that closed after losses; for a trend strategy the direction of this bias is unclear.
- **Calendar.** The snapshot's session axis is SPY's bar dates on current main. The only sleeve
  bar dates outside it are 2007-04-02 and 2007-07-02 (checked against the DB 2026-09-24), before
  any close this signal reads (first lookback start 2010), so todo 418's calendar change does not
  alter this panel.
- **Sparse gaps.** GLD, DBA, DBB, DBC, UUP and DHI have 1 to 6 missing closes since listing. A
  missing close gives no position for that symbol that day and for the day its lookback reads
  it; no fill.
- **Gross returns only.** Monthly-ish turnover on liquid ETFs; costs reported, never decisive.

## 8. Holdout (S5)

Read only if the in-sample result is ACT-level. Build a second snapshot with `end_exclusive` at
the latest complete session, rerun `s2sig` and `s3` with the same code, and read the mean daily
excess (book return minus the null-median return) over sessions on or after 2025-12-24. Positive
confirms ACT; otherwise the token is PASS. It cannot rescue a FAIL. Freshness caveat: the holdout
panel needs the nightly OHLCV backfill current for all 13 symbols (check `max(timestamp)` first).

## 9. Gates before the real run

| Gate | What | Threshold |
|---|---|---|
| V2-TSMOM null calibration | 200 synthetic seeds, no planted trend, per-asset drift (sd 3 bp/day), equicorrelated returns, the TSMOM signal computed from the synthetic closes with a full lookback before the panel, 199 sampled memory-aware shifts per seed | PASS rate inside 5% +/- 3.1% |
| V3-TSMOM power | Planted latent drift (AR(1), phi 0.995, half-life about 6 months) at the strengths that give mean excess Sharpe 0.6 and 0.8 | Reported; below 50% at 0.8 means the design is revisited before freezing |
| Unit tests | `tests/unit/sleeve_walk_forward/`, `tests/unit/test_panel_null.py` | Green |

Results (2026-09-24, synthetic only; no real-data number existed):

- **V2-TSMOM: PASS.** PASS rate 2.0% (4/200), inside the 1.9-8.1% band at its conservative
  edge; mean excess Sharpe -0.035. The test raises false alarms slightly less often than
  nominal, which costs a little power and never inflates a PASS. Harness at b766685d2
  (V2's code path is unchanged by b01eb751a). Artifact `logs/phase181/clean/v2_799d32e2cd648b12.json`.
- **V3-TSMOM: PASS.** The bisection undershot the targets, so read power against the realized
  mean excess Sharpe: 54% PASS (CI 47-61%) at 0.50 (target 0.6, latent drift sd 0.0457 daily
  vols), 74.5% (CI 68-81%) at 0.72 (target 0.8, 0.0551). Above the 50%-at-0.8 floor and in line
  with the arithmetic below. Harness at b01eb751a. Artifact
  `logs/phase181/clean/v3_5b8655f0d848d357.json`.
- Both reproduce bit-for-bit an earlier run of the same code from an uncommitted tree.
- **Unit tests:** green at b01eb751a.

Power by the same arithmetic as phase 179 section 9 (13 years, one arm, one-sided): PASS needs
t = 1.645, so excess IR about 0.46 at 50% power and 0.63 at 80%; ACT needs t = 2.77, excess IR
about 0.77 at 50%. A FAIL is recorded as "no detectable trend timing at this sample size", not
"no premium".

## 10. Result (2026-09-24)

`TSMOM_VERDICT = FAIL`. One run at 0c33a2596 (clean tree), snapshot
`logs/phase181/snapshot_dc800360d369f4d5`, verdict `logs/phase181/s4_12f955d9aca8f18f.json`.

| Measure | Value |
|---|---|
| Observed Sharpe, gross, 2013-01-01 to 2025-12-23 | 0.47 |
| Null median Sharpe (K = 3,389 shifts; 5th-95th pct -0.08 to 0.67) | 0.27 |
| Excess | +0.19, stationary-bootstrap CI [-0.32, +0.73] |
| Permutation p | 0.221 |
| Sub-period mean daily excess | +0.54, +0.76, +0.45 bp (3/3 positive) |

Fails on p, not on stability. Section 6 applies: classic TSMOM and the section 3 variants are
closed on this sleeve. Diagnostics (section 11 style, never decisive): observed Sortino 0.65,
max drawdown 16.4% of log wealth, hit rate 53.5%. Signal coverage: TLT has no signal until
2017-02 (its history starts 2016-02-03), as section 7 expected.
