---
status: pending
priority: P1
filed: 2026-10-29
source: data lane, 1d session_coverage recount (191-SESSION-COVERAGE-FIX.md)
---

# The canonical 1d series lacks bars the raw table holds, for 71 held names

After the answered-session fix (191-SESSION-COVERAGE-FIX.md), 110 of the 207 scored names still fail
`session_coverage`. For 71 of them the only remaining cause is the same one: sessions where
`ohlcv_raw` holds a canonical vendor's bar and `market_data_ohlcv` holds none. Such a session is not a
vendor answer of "no trade", so no answer evidence may cover it. It is a hole in the derived series.

Measured 2026-10-29 (read-only): 23,171 such sessions over the 71 names, 12,198 before 2016-01-04 (IBKR
era, 12 names), 10,953 from 2016-01-04 on (59 names) and 20 in the stale tail of CTVA (canonical
ends 2026-09-30, raw runs to 2026-10-28). The names are listed in 191-SESSION-COVERAGE-FIX.md. Examples:

- CUBE: canonical holds 94 IBKR `named` bars (2011-09-19..2012-02-01), then nothing until Alpaca
  `sip_rth` from 2016-01-04. Raw holds IBKR `smart_trades` for 2012-02-02..2015-12-31 (985 sessions).
- JBTM: canonical holds 8 IBKR bars (2008-07-18..2008-07-31); raw holds IBKR `smart_trades`
  2008-07-18..2015-12-31, 1,868 sessions without a canonical bar.
- APTV: 474 sessions 2016-01-04..2017-11-16 with a raw row from each vendor and no canonical bar.

The latest `derived` loads of CUBE and JBTM (2026-10-29, rule d2-v4) report `refused_head: []`,
`refused_interior: []`, `stale_only: []`, `restated: []`: the rule did not refuse these sessions by a
recorded reason, so the cause is open. Candidates to check first: the per-span hold rows of D-191-Q
(30 hold spans over 27 names in 191-D191Q-ARBITRATION.md; the 71 names are not all in that list), the
primary and fallback choice of `daily_rule.servable_primary_dates` over the pre-2016 range, and whether
these are names whose derivation stopped at the first discontinuity.

## Fix

Find why the daily stage admits no bar on these sessions, correct the rule or the policy rows, and
re-derive the 71 names. Then re-run the D7 verdicts: the names clear `session_coverage` with no change to
the coverage rule. Order against 186-26: the 71 names stay held until this lands.

## Not in scope

The 39 names with genuine holes (no raw bar and no answered window) and the freshness and seam holds:
191-SESSION-COVERAGE-FIX.md classifies them.

## Resolved cause and stage 1 drift (data lane, 2026-10-30)

The derivation gap is not a defect. After the Tradier delete the IBKR history fetcher backfills 1d
`smart_trades` for the pre-2016 era on the names Tradier used to cover (1,165 names now have it).
CUBE: its 3,664 new IBKR bars (2011-11-03 on) landed 2026-10-29 22:52Z, after the last daily
derive (11:54Z), so canonical holds IBKR 2011-09-19..2012-02-01 and Alpaca from 2016-01-04 until the
fetcher's daily stage derives the touched series at the end of its run. Expect the 71 names to clear
without code. Recount after the next daily derive and the next audit; a name that still has raw bars
canonical lacks after that is a real derivation defect.

Drift in the 186-26 stage 1 output (feature_vectors_v2, 1d): 27 of its 1,257 names have IBKR 1d raw
earlier than their canonical head, so the pending derive extends their history. Days gained:
NCMI 3252, DE 2555, ELS 2555, HUBB 2555, DOC 2555, FE 2555, EOG 2555, EZU 2170, PRI 2104, MDLZ 1937,
ZBH 1895, EPAM 1426, NRG 1035, NEXN 936, ASC 886, ESI 711, HUBS 452, XENE 425, EU 339, LNTH 193,
FTV 22, RKLB 7, DELL 7, PWP 4, ROIV 4, AUR 3, BOC 1. Rolling-window features keep their values past
the new warmup; expanding-state features (the HMM walk-forward, the never-reset VWAP series) differ for
these names. Handle at the 186-27 drift read: delete those names' stage 1 rows (derived cache) and
rebuild them as their own units with the same pin; the primary key is append-only, so a rerun cannot
overwrite. Names whose gain is under 30 days (FTV, RKLB, DELL, PWP, ROIV, AUR, BOC) change by warmup
only and can wait for the next full rebuild.

## Full classification (data lane, 2026-10-31)

The premise resolved as the 2026-10-30 note predicted: post-derive, eligible names have **0
pre-2016 gap sessions** (was 12,198); CUBE and JBTM are fully derived. Live recount 2026-10-31:
108,230 raw-holds-canonical-lacks sessions over 147 names, five classes:

- **A. 27 names with `compute_eligible_1d=false`: 66,110 sessions, never derived at all.** The
  daily stage's discovery and the audit's scored universe both filter on the flag, so there is
  no load row, no hold, no refusal: the largest silent class (61% of sessions). WMS: 2,723
  alpaca/sip_rth bars all volume>0 and zero canonical rows. Fix lane: eligibility promotion
  (migration 341's measured predicate, `universe_expansion_promote_compute_eligible.py`), no
  code. OWNER DECISION before promoting: why these 27 were never eligible (illiquidity class,
  todo 454's ultra-thin question) and todo 491's point that promoting wave 2 changes the panel
  silently until the S0 universe snapshot exists. Promote after 491, not before the first
  counted run.
- **B. 22 names, D-191-Q IBKR symbol rows where IBKR has no raw answer: 28,359 by-design
  sessions** ("IBKR serves, with no bar where IBKR is missing", 191-D191Q-ARBITRATION.md), but
  recorded nowhere: under an IBKR primary `derive_daily_v2` hits `if fallback is None or frame
  is None: continue` (`daily_rule.py`) with no refusal category. Sample: AKTS, 1,956 sessions,
  canonical only from 2026-01-09. Fix: owner arbitration (extend IBKR symbol rows), plus a
  small honesty-only code fix persisting an `unserved_primary` refusal in `ohlcv_load.detail`
  for the IBKR-primary-missing branch, sequenced outside a live rebuild.
- **C. 47 names, default-Alpaca refusals: 9,930 sessions, recorded** in `ohlcv_load.detail`
  (refused_head/interior/stale_only). APTV's 474 pre-spin-off sessions sit in refused_head
  (seam basis 0.847) and still fail coverage because the check counts only bars and
  empty_history spans as answered. Fix lane: owner arbitration (extend IBKR symbol rows), not
  code.
- **D. 60 names, zero-volume Alpaca placeholders with no IBKR fallback: 3,809 sessions,
  recorded** in the zero_volume list. No action beyond the arbitration lane.
- **E. CTVA, 22 sessions: its own hold** (`unclassified_rescale`, factor 5.5714), todo 516, not
  this todo.

Audit 2026-10-31 07:15Z: session_coverage fails 157 of 1,502. Recommended order: (1) owner
decision on the 27 ineligibles, then promote and re-derive (kills 61% of sessions, pure data
lane); (2) owner arbitration on the 22 IBKR-row names and the APTV-style refusals; (3) the
`unserved_primary` honesty fix outside a live rebuild.

## unserved_primary landed (research lane, 2026-10-31, commit a852f7008)

Class B honesty fix: `derive_daily_v2` lists the branch's dates in `DailyV2Result.unserved_primary`
and the daily stage persists them in `ohlcv_load.detail` (`unserved_primary`, ISO dates, beside
refused_head/stale_only), with the CSV report column and batch summary count. First write lands with
the next 05:20/05:45 UTC bar_derivation run. Two scope notes:

- The audit-side informational row (`unserved_primary_1d` beside `refused_head_1d` in the 1d
  verdict report) is not landed: the audit lane has in-flight WIP in `integrity_checks.py` and
  `bar_reconciliation_audit.py` (grid-parity D7 exceptions), so the read-side hunks were reverted
  out of the shared tree to keep the lanes separable. The hunk is small: an
  `INFO_UNSERVED_PRIMARY` constant, a `NameReport1d.unserved_primary` count from
  `derived.unserved_primary`, and one facts row in `_verdict_report_1d`.
- The list covers exactly the unserved sessions the raw answers prove (the rule's axis is dates
  some vendor answered); a session no vendor answered is outside the rule and stays outside the
  inventory. The docstring says so.

The class-B remediation itself is unchanged: owner arbitration on the 22 names' IBKR symbol rows.

## 2026-11-01: class-A evidence sharpened by the H load-ledger trace

The audit-classification pass (2026-11-01) confirmed the 27 class-A names are the only new 1d
failures and are all `compute_eligible_1d=false`. The H trace added hard evidence for 8 of them
(batch `cc0120c7`, 2026-10-28 01:10): each holds only the 15-18 ibkr/named rows of a 2,702-6,565
row derivation because the 191-20 Tradier delete removed the tradier/consolidated share after
the write, and the nightly discovery (`is_active AND compute_eligible_1d`,
services/bar_derivation.py:404-407) can never re-reach them; only an explicit `--symbols` run
can. Their raw survives (H: alpaca sip_rth 2,723 rows from 2016-01-04 plus ibkr 4,269 from
2009-11-05), so promoting eligibility and re-deriving restores 2009-11-05 onward for them. This
strengthens the existing promotion decision (owner, after todo 491): the 27 names are not just
never-derived, they are stranded in a ledger-inconsistent state (load row says applied 2,702+,
canonical holds 15), which is the silent-wrong-answer surface this todo exists to close.

## Status 2026-11-04 (session ab; work paused by the owner)

- Group 1, QRVO: done. Its stale 1d policy row is retired through `ops_source_policy.py --retire`
  (6433a469a; 1d only, evidence required, one atomic UPDATE).
- Group 2, the 27 class-A names: the open loop. Resume: run an IBKR 1d pre-2016 fetch for the 27
  through `ohlcv_history_fetcher.py --symbols ...` in a gap between timer runs (never two fetchers;
  `default_scopes` unchanged), then re-derive them with `bar_derivation --stage daily --symbols ...`
  and read their D7 rows. Eligibility promotion stays the owner's decision (todo 491).
- Group 3: waiting on the owner (the arbitration-lane refusals); no action here.
