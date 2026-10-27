---
status: pending
priority: P2
filed: 2026-10-08
source: plan 185-48 (residual risk of the 1d primary swap; 185-47 Apply results, 189-10 1D fetch record item 5)
owner: owner decision per name, then the onboarding SOP or ops_source_policy.py
---

# Four 1d names frozen at their last Tradier bar: PSKY, WBD, QRVO, MOD

## What

From D = 2026-10-07 no source answers these active compute_1d names, so each canonical 1d series
stops at its last Tradier bar and nothing after it is written (checked 2026-10-08):

| Name | Last canonical 1d bar | Open policy for D on | Why no bar since |
|---|---|---|---|
| PSKY | 2026-10-05 (tradier) | default: IBKR, no fallback | IBKR contract qualification fails ("No security definition has been found"); SMART answered through 2026-09-30 |
| WBD | 2026-10-05 (tradier) | default: IBKR, no fallback | same as PSKY; SMART answered through 2026-09-30 |
| QRVO | 2026-10-02 (tradier) | hold row: Tradier primary, IBKR fallback (185-47 class C) | IBKR has no contract definition; no IBKR request was ever made |
| MOD | 2026-10-06 (tradier) | hold row: Tradier primary, IBKR fallback (185-47 class C, few common sessions) | IBKR SMART answered 2026-10-07, but d2-v2 refuses the fallback date (basis window outside tolerance) |

Tradier's own answers for PSKY, WBD and QRVO also stop before 2026-10-06, the last bar of every
other name. That points at a listing or corporate event rather than an IBKR fault; check the company
record before any contract fix. CTVA is frozen too, by its hold (todo 516), and is not in scope here.

D7's `freshness_1d` fails PSKY (3 sessions), WBD (3) and QRVO (4) today; MOD fails once more than
`threshold.bar_integrity.freshness_max_lag_sessions_1d` (2) sessions pass. The rebuild gate refuses
a stale name, so these four block nothing else but cannot pass themselves.

## Decision per name (owner)

1. An IBKR contract fix (a symbol change or new conid, through the onboarding SOP's spelling rule),
   then a named fetch; or
2. an onboarding review (a merger or delisting: the name's history ends, it stays active and is
   handled under todo 512's rule for names whose defect is not worth fixing); or
3. a deliberate freeze recorded as a `bar_source_policy` row with the reason, so `freshness_1d`
   judges against a known end.

Never deactivate or soft-delete a name (onboarding SOP). MOD needs its own call: a symbol row that
makes IBKR primary from D with the seam recorded, or a wait for more common sessions.

## Done when

Each of the four has a recorded decision and either current 1d bars or a policy row that explains
its end; `freshness_1d` passes or names a recorded cause for each.

## Corporate record (checked 2026-10-26, secondary sources; confirm each against the SEC Form 25 before writing anything)

| Name | Event | Last session (approx.) | Class |
|---|---|---|---|
| WBD | Acquired by Paramount Skydance, cash ($31/share); closed about 2026-10-06; Form 25 filed | 2026-10-05 | Ended |
| QRVO | Merged into Skyworks ($32.50 cash + 0.960 SWKS per share); combined company trades as SWKS | 2026-10-02 | Ended |
| CCO | Taken private by Mubadala Capital ($2.43 cash); closed 2026-10-14, NYSE suspended trading 10-15, delisted 10-26 | 2026-10-14 | Ended (new to this todo) |
| PSKY | Same Class B shares renamed Skydance Corporation, moved Nasdaq -> NYSE as SKYD around 2026-10-06 | trading | Ticker and venue change |
| MOD | Unchanged (IBKR answers; d2 seam question only) | trading | As above |

Yahoo agrees: it now serves one row each for WBD, QRVO and CCO, and its PSKY history is broken
around the 2026-09-15 ex-date ($0.05 dividend, NaN close, missing neighbors). These four are the
four nightly failures of `indicagent-dividend-event-writer@yahoo` (2026-10-26 run), so the unit
stays red every night and would hide any new failure.

## Recommended shape (Claude 2026-10-26; owner decides)

One lifecycle surface, not a hold list: `listing_venue` already records a name's listing venue
point in time (`valid_from`, `valid_to`, evidence). Extend it to carry listing end.

- Ended names (WBD, QRVO, CCO): a closing row with `valid_to` = the session after the last one
  and the Form 25 as evidence. `freshness_1d` counts no session after listing end; the dividend
  writer records `ended` (not `failed`) for a name whose listing ended before the vendor's
  history went short; the residue readiness gate (`ops_tradier_residue.py`) reads ended names
  from the same rows and `--frozen-names` is deleted. Rule 6 holds: the name stays active and in
  every panel, its bars simply stop.
- PSKY: a venue row NYSE from the switch date, plus an IBKR spelling for SKYD. The SOP's
  `ibkr_symbol` rule covers share-class spaces only, so a ticker change needs a point-in-time
  spelling (or a conid key), which is the real design question here. `instruments.symbol` stays
  PSKY (concept identity).
- PSKY Yahoo dividend: keep refusing (the writer is right); it is a vendor defect and only the
  owner can accept it as a known gap.

Open questions for the owner: (1) listing end on `listing_venue` vs a new table; (2) PSKY spelling
point in time vs conid identity.

## PSKY -> SKYD measured at IBKR (2026-10-26, read-only probe)

IBKR resolves SKYD (conid 804144296, NYSE, "SKYDANCE CORP", TRADES head 2025-08-07 = PSKY's own
SMART head) and no longer resolves PSKY. Over the 17 common sessions 2026-09-08..09-30 every SKYD
close is the stored PSKY ibkr/smart_trades close times 0.9787..0.9796 (median about 0.979) and
volume about 1.02x: IBKR re-served the whole series on a new scale at the rename, a constant
factor that is no split ratio. SKYD also has no 2026-10-05 bar (Tradier served 9.775 that day).

So pointing PSKY at SKYD (`provider_meta.ibkr.symbol`, the BRK.B mechanism) is a one-row change,
but its first fetch re-serves the history last-wins on the new scale. The overlap judge should
hold the name as an `unclassified_rescale` (same class as CTVA's 39/7, todo 516) and the
restatement detector flags the rows. The scale decision then rides with 516's policy. The factor
is plausibly a merger exchange or special-distribution adjustment; confirm it against the
merger terms before choosing a basis.

## Owner decisions (2026-10-26)

1. Listing end gets its own small append-only table (one row per ended name: last session, reason,
   evidence such as the Form 25), written by migration. `freshness_1d` counts no session after it,
   the residue readiness gate reads it, and `--frozen-names` is deleted. Rule 6 holds: ended names
   stay active and in every panel. First rows: WBD, QRVO, CCO (confirm each last session against
   the filing before writing).
2. PSKY is repointed to SKYD for IBKR (`provider_meta.ibkr.symbol`, the BRK.B mechanism). The first
   fetch re-serves its history last-wins on the 0.979 scale; the name is held as an unclassified
   rescale and decided together with CTVA (todo 516).

## Landed 2026-10-26

- Migration 518 (58572432d): `listing_end` with CCO 2026-10-14, QRVO 2026-10-02, WBD 2026-10-05
  (SEC Forms 25-NSE and 15-12G); `freshness_1d` and the 191-19 readiness gate read it.
- Migration 519: PSKY asked at IBKR as SKYD (`provider_meta.ibkr.symbol`).
- Open: confirm after the first SKYD fetch that the 0.979 re-serve lands last-wins with
  restatement flags and that the daily stage holds PSKY as `unclassified_rescale` (as CTVA); if it
  does not hold, hold it explicitly before the next daily apply. Alpaca has no spelling override:
  PSKY 5m comes from the IBKR fallback until the alpaca leaf maps symbols (small leaf change).
  MOD keeps its class C hold (`--frozen-names MOD,PSKY` until the PSKY hold is decided).

## New ended listings found 2026-10-27 (listing_end rows needed)

Found by the plan 19 pass: IBKR answers "Error 200 No security definition" at qualify, and
Alpaca's asset endpoint reports the name inactive. Confirm each against SEC EDGAR (Form 25 or
Form 15) before writing a `listing_end` row through a migration, as with CCO, QRVO and WBD.
- BZH (Beazer Homes): last Alpaca 1d bar 2026-10-19, Alpaca status inactive. On the plan 19
  frozen hold (`FROZEN` in `ops_tradier_residue_gate.sh`) until its listing_end row lands.
- ACA (Arcosa): last Alpaca 1d bar 2026-10-22, Alpaca status inactive. Already settled for plan
  19; freshness_1d will fail it nightly until its listing_end row lands.
- MSGS (Madison Square Garden Sports): IBKR qualify fails and Alpaca's asset endpoint returns
  "not found", yet Alpaca served 1d bars through 2026-10-26. Likely a ticker change; check
  before treating it as ended.
