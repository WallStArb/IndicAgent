# Plan 191-19 review: Tradier residue harness and the not-ready record

Reviewer: fresh-context read-only review (phase 191 standing SOP), 2026-10-22/23
Commits: b0280dbbc (RED tests), 1b4bb935e (harness GREEN), 46e14ee24 (not-ready docs)
Ground truth read: 191-19-PLAN.md, CLAUDE.md, src/intelligence/bars/daily_rule.py,
services/bar_derivation.py, scripts/infrastructure/backfill/_d1_gaps.py,
scripts/infrastructure/backfill/_history_fetch_item.py, and the live DB (read-only).

## Verdict: FAIL

Task 1 (the harness, commits b0280dbbc and 1b4bb935e) passes every gate: plan-conformant,
honest tests, genuinely read-only, the unchanged rule, the migration-476 route kinds, and the
digest self-check reproduces stored canonical rows on live data. The FAIL is the Task 2
not-ready record (commit 46e14ee24): its headline numbers are right, but the cause analysis
that the owner and plan 20 will act on is wrong for most of the 1,027 unanswered names
(finding 1), and the same commit silently moved STATE.md completed_plans from 120 to 125
while its own message says it stays 120 (finding 2). The harness needs no change; the
SUMMARY analysis and the STATE.md frontmatter do.

## Findings

### 1. P1: the not-ready cause analysis misclassifies 446 of the 1,027 names

.planning/phases/191-unified-raw-bar-table/191-19-SUMMARY.md:44 (A2 row), :46 (B1 row) and
:52-56 ("a completed gap-fill cycle flips at most 28 of the 1,027; 999 fail the readiness
rule as written regardless of further cycles"); the same claims are repeated in
.planning/STATE.md:122-134 and in the commit message of 46e14ee24.

Two claims do not survive the DB:

a) A2 ("IBKR's verified floor sits above the threshold (verified no 1d data below it); no
future ask can carry a window start at or below the threshold; permanent residue") is false
for 429 of the 515 A2 names. Verified per name against ohlcv_raw, ohlcv_request,
ohlcv_empty_history and ohlcv_provider_head (1d rows): those 429 have no IBKR bar at or
below their threshold, no no_data request window starting at or below it, no empty-history
span at or below it, and no provider head above it. Nothing below their floor is asked or
verified; the deep span is simply unasked. Since the fetcher derives window starts as the
first uncovered session from max(today minus 9800 days, provider head)
(scripts/infrastructure/backfill/_history_fetch_item.py:795-820, planned by
scripts/infrastructure/backfill/_d1_gaps.py:detect_gaps_1d_from_d1), the next gap-fill cycle
that reaches one of these names WILL issue a window starting at or below the threshold, and
whatever IBKR answers (bars or no_data both satisfy the readiness predicate) flips it to
answered. Examples: AMP, AOS, APA, APD, APH, ARE (AOS: threshold 2000-01-03, earliest IBKR
bar 2006-10-02, verified head 1983-09-30 below the threshold, no empty span, no no_data).
Only 86 of the 515 are settled as claimed: 75 have a verified 1d provider head above the
threshold (the head floors every future ask above it; recorded evidence), and 11 have a deep
no_data answer window (CTRE, ETSY, EXLS, FUBO, LYB, NEXT, QXO, RBLX, RSPR, TAN, TROX).

b) B1 ("28 names whose deep ask is owed; they flip the moment the cycle asks them") is false
for 17 of the 28. Those 17 already have their deep span covered by ohlcv_empty_history
evidence below the threshold (for example BJ: span 2006-10-09..2011-05-21 against a
2011-05-23 threshold), so the planner owes them no deep ask and they never flip. They are
the same covered-but-blind class as A1. Only 11 of the 28 are owed an ask.

Corrected split of the 1,027 (measured; threshold rule exactly as the harness implements
it, today = 2026-10-23):

| Class | Names | A finished cycle answers them? |
|---|---|---|
| Covered-but-blind (A1 481 plus 17 of B1) | 498 | No, unless coverage goes stale (below) |
| A2 with verified 1d head above threshold | 75 | No (head floors all asks above it) |
| A2 settled by a deep no_data answer | 11 | No (already asked and answered nothing) |
| A2 unasked, nothing below the floor verified | 429 | Yes, when their slot comes due |
| B1 unasked, deep ask owed | 11 | Yes |
| WBD, PSKY (head above threshold), QRVO (no evidence) | 3 | No (frozen, todo 519) |

Net: about 440 flip when a finished cycle runs (429 plus 11; MOD, frozen under todo 519,
sits in the 429 and will not be asked), and about 587 fail regardless, not 28 and 999. The
practical conclusion inverts: an evidence-based readiness amendment (crediting verified
heads and no_data windows, not just post-change ask window starts) plus one finished cycle
would leave roughly the same ~89 evidence-settled names unresolved, and the permanent
data residue for plan 20 is the Tradier sessions below IBKR's verified floors, which is a
much smaller set than the SUMMARY's "515 permanent residue" framing suggests. The decision
this record feeds (amend the readiness rule, re-arm the deepening driver, or accept the
residue) is materially affected.

Caveats on my side of the claim: for horizon-bound thresholds the first planned session can
fall a session above the threshold date (the ACM one-session miss the SUMMARY itself
documents), and a head lookup at next fetch could return a head above the threshold for
some of the 429, converting them to the 75-name class with evidence. Neither changes the
classification of the names as unasked today.

### 2. P2: STATE.md completed_plans silently moved to 125

.planning/STATE.md:11 now reads completed_plans: 125. The diff in commit 46e14ee24 changed
it from 120 to 125, while the commit message says "completed_plans stays 120" and the file's
own prose at .planning/STATE.md:134 says "completed_plans stays 120 (plan 19 is not done)".
The recount note at :135 says the count was 119 before plan 18, so 120 is the correct value.
The frontmatter must go back to 120.

### 3. P3: exception variable named error_found

scripts/ops/bars/ops_tradier_residue.py:532 uses `except Exception as error_found:`. The
project convention (CLAUDE.md, Style) is `except X as error:`. The rename was presumably to
avoid shadowing the pre-initialized `error` variable; `exc`/restructure would also work, but
as written it is a convention miss.

### 4. P3: the readiness ask query lacks the test-caller filter

scripts/ops/bars/ops_tradier_residue.py:365-369 (_REQUESTS_SQL) selects ohlcv_request rows
without the `(caller IS NULL OR caller NOT LIKE 'test-%')` guard that _TRADIER_NAMES_SQL,
_TRADIER_ROWS_SQL and _IBKR_ROWS_SQL all carry (and that bar_derivation's raw read carries,
services/bar_derivation.py:411-423). A test fixture request in the live DB would silently
satisfy readiness. Measured: zero test-caller ibkr 1d requests with outcome bars/no_data
exist after the depth change, so no wrong answer today; latent only. Cheapest fix is the
same LEFT JOIN guard the other queries use.

### 5. P3: readiness_threshold docstring says "deeper", the code implements the later date

scripts/ops/bars/ops_tradier_residue.py:78-81: the docstring calls the threshold "the
deeper of the first Tradier bar and the 9800-day depth horizon", but max() returns the later
(shallower-reach) of the two dates, which is what the plan text specifies
(191-19-PLAN.md:72). The code is right; the docstring wording is inverted. Wording only.

### 6. P3: plan file list deviation not recorded

191-19-PLAN.md:70 and :75 place the d2v2 fixture-shape tests (head, interior,
no-primary-bars cases) in tests/unit/bars/test_daily_rule.py; the commits put them in
tests/unit/scripts/test_ops_tradier_residue.py (test_dal_head_case..., test_inda...,
test_etha..., lines 212-248) and never touch test_daily_rule.py (verified: empty diff across
the three commits). The coverage exists and is arguably better placed beside the harness;
the Deviations section of the SUMMARY should have said so instead of listing only the three
test-defect fixes.

### 7. P3 (note, no action required): self-check stored side is not canonical-pair filtered

scripts/ops/bars/ops_tradier_residue.py:401-406 (_STORED_POST_D_SQL) reads every post-D
market_data_ohlcv row for the symbol, while the canonical 1d digest definition
(services/bar_derivation.py:_SELECT_DIGEST_1D_SQL) filters to CANONICAL_1D_VENDORS/KINDS.
A stray non-canonical post-D row would break self-check equality, which is loud (the kinds
dict is in the output) and was deliberately tested (test_self_check_catches...:345-354),
so this is a robustness note, not a silent-wrong-answer risk.

## SOP checklist

1. Plan conformance (Task 1): PASS. All four verbs present and mutually exclusive; one
   serial connection with SET default_transaction_read_only = on; the no-write grep is
   empty and a unit test enforces it; git diff over daily_rule.py and bar_derivation.py
   across the three commits is empty; the proof runs derive_daily_v2 over
   read_daily_inputs/read_daily_params outputs with route != TRADIER filtering and the real
   policy rows; IBKR_RAW_KINDS is smart_trades plus VENUE_ROUTE_KINDS (never the bare
   venue kind, asserted by test at tests/unit/scripts/test_ops_tradier_residue.py:383-388),
   honoring the amendment. Live check: --prove on AAOI and ACM returns proven for both with
   the post-D digest self-check equal on both, so the harness reproduces the rule on real
   stored rows, not only on synthetic fixtures.
2. Test honesty: PASS. The RED commit contains only the test file (module absent, so RED is
   real by import failure). The three GREEN-phase test fixes are genuine defects in the RED
   tests, not accommodation of wrong code: datetime(date, tzinfo=UTC) is a TypeError; the
   threshold assertion contradicted the plan's own max() rule; the proof test asserted
   proven while constructing required sessions with no bar. All three are disclosed in the
   SUMMARY Deviations. The ETHA no-primary-bars case is characterized honestly: I verified
   from the fixture JSON that all 21 IBKR observations are stale for the recorded reverse
   split (fetched before recorded_at, none the evidence request), so the rule serves
   nothing and lists every session stale_only, exactly what the test asserts. Minor: the
   GREEN version of test_classify_proof_marks_a_name_proven (tests/...py:254-263) derives
   smart_dates from the served bars, which makes its proven assertion near-tautological;
   the adjacent venue-moved test covers the negative path, so this is a weak-test note, not
   dishonesty.
3. Boundary and style: PASS with findings 3-6 above. The allow-list entry is the exact
   reason string the plan specifies (tests/unit/test_market_data_ohlcv_boundary.py:106-108)
   and the temporary-allow-list expiry test passes with it naming 191-25. APR judgment:
   DEPTH_DAYS = 9800 is a plan-defined constant that the script cross-checks against
   config_history at runtime and hard-fails on mismatch (a guard, not a shadowed tunable);
   DEFAULT_SELF_CHECK_SAMPLE = 50 and D = 2026-10-07 are plan-defined facts; no other
   numeric thresholds exist in the readiness/proof logic. Timestamps are UTC throughout
   (datetime.now(UTC)). No em dashes in any of the new files; no AI attribution in any of
   the three commit messages.
4. Silent-wrong-answer sweep: the stale kind='venue' trap is avoided and tested; exceptions
   in the prove path are recorded per name (never swallowed); measure edges (no common
   sessions, zero volume) return None rather than inventing values; finding 4 is the one
   latent zero-row trap found; finding 7 is loud by construction.
5. SUMMARY claims vs code and DB: the Task 1 verification claims (72 tests = 20 + 44 + 2 +
   6 across the four files; no-write grep; no-diff greps) all reproduce. The Task 2
   headline (1,529 names, 502 answered, 1,027 unanswered, exit 2; 6,905 post-change asks;
   depth change 2026-10-12 10:45:49.537152Z; last IBKR 1d answer 2026-10-17 20:41:11Z; last
   any-timeframe answer 2026-10-19 00:28:16Z; A/B 996/29; A1/A2 481/515 with the floor
   defined as least(earliest smart/venue bar, deepest empty span); the AAOI and ACM
   examples; the frozen four) all verify exactly against the DB. The failure is the
   interpretation layered on A2 and B1 (finding 1). The plan's Task 2 instruction to record
   the next weekly gap-fill session time is met with the cadence (7 days) plus the gateway
   blocker instead of a concrete time; a concrete time is not computable while the gateway
   awaits 2FA, so this is acceptable.

## Rider verification (queries run, read-only, against the live DB)

Reproduction of the readiness rule exactly as implemented (asks = source ibkr, timeframe
1d, outcome in (bars, no_data), answered_at > depth change; threshold = max(first Tradier
bar, 2026-10-23 minus 9800 days); test-caller exclusion on the names side):

- 1,529 Tradier names; 502 answered; 1,027 unanswered; 996 class A (asked post-change, no
  qualifying window); 31 never asked post-change. Matches the SUMMARY (its B row counts 29;
  QRVO and PSKY, listed as C and D, are the other two never-asked names).
- A1/A2 split with floor = least(earliest ibkr smart/venue raw day, deepest
  ohlcv_empty_history empty_from): 481 / 515. Exact match, which pins down the executor's
  floor definition.
- 6,905 post-change ibkr 1d asks; max answered_at for ibkr 1d = 2026-10-17 20:41:11;
  any timeframe = 2026-10-19 00:28:16; config_history depth row = 2026-10-12
  10:45:49.537152+00, value 9800. All match.
- A2 evidence classification (1d-scoped ohlcv_provider_head rows; note the table is keyed
  (symbol, provider, timeframe) since migration 465, so an unscoped min mixes in 5m seed
  floors): 75 with verified head above threshold, 11 with a no_data request window starting
  at or below threshold at any time, 429 with none of these. The 429 are the unasked deep
  spans (finding 1a).
- Never-asked classification: 29 with 1d head at or below threshold, 2 above (WBD, PSKY);
  QRVO has a seeded 2000-01-03 floor row below its threshold but no data at all. Of the 28
  B1 names (head at or below threshold, QRVO excluded), 17 are covered deep (A1-like floor),
  11 are not (finding 1b). BJ span 2006-10-09..2011-05-21 vs threshold 2011-05-23 checked
  directly.
- Named examples verified: AAOI (empty span 2006-10-09..2013-09-25 with 5 confirming
  chunks, first Tradier bar and earliest IBKR bar both 2013-09-26, so A1), ACM (earliest
  IBKR bar exactly at the 2007-05-10 threshold, post-change ask window starting 2007-05-11,
  plus pre-change SMART and all-venue no_data 2006-10-16..2007-05-10 answered 2026-10-08),
  MOD (A2, threshold 2000-01-03, earliest bar 2026-08-28, seeded floor head at the
  threshold, no no_data), PSKY (verified head and earliest bar 2025-08-07 above the 2006
  threshold), QRVO (no IBKR 1d raw rows at all), WBD (verified head 2005-07-21 above the
  2005-07-08 threshold).
- Planner mechanism check (code, not DB): scripts/infrastructure/backfill/
  _history_fetch_item.py:795-820 derives start_dt from the depth horizon and the provider
  head, then narrows to the first uncovered session via _d1_gaps.detect_gaps_1d_from_d1;
  coverage is the vendor's own raw rows, definitive no_data request windows (any age,
  minus open transport failures), and freshness-gated empty spans, plus a shallow recent
  overlap window. Conclusion: a name with an uncovered deep span and no head above the
  threshold will be asked deep; a name whose deep span is covered will not. This is what
  drives finding 1 in both directions.
- One nuance the SUMMARY could state: coverage from ohlcv_empty_history is
  freshness-gated (re-verified after infra.backfill.empty_history_reverify_days; the spans
  I sampled were verified 2026-10-03). If a span goes stale without re-verification the
  planner re-opens that span, so "the planner will never issue a window that deep again"
  is not strictly permanent for the empty-span-backed subset of A1; it is permanent for
  the bar-backed subset.

## What the fixer should change (analysis docs only, no code change required)

1. Rewrite the 191-19-SUMMARY.md cause table and the "at most 28 / 999" paragraph per
   finding 1, and the matching paragraph in .planning/STATE.md, with the corrected split
   (498 covered-but-blind, 75 head-floored, 11 no_data-settled, 440 cycle-flippable, 3
   frozen), keeping the honest framing that no rule or policy change is proposed here.
2. Restore completed_plans to 120 in .planning/STATE.md.
3. Findings 3-6 are small; fix opportunistically (error_found rename, test-caller guard in
   _REQUESTS_SQL, docstring wording, one Deviations sentence).
