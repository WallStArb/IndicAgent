# D-191-Q daily rule d2-v4 build note (todo 545 step 3)

Author: Claude (executor session, 2026-10-27). Informed by: D-191-Q and D-191-P in `docs/plans/2026-10-12-unified-raw-bar-table-design.md`, todo 545.

This step changes code and tests only. No bar_source_policy row was written, no daily stage or derive ran against the live database, and nothing was written to a live table. Every live query was read-only: the CVR, policy and raw lookups, plus a read-only session that ran the pure rule over live inputs.

## Commits

| Commit | What |
|--------|------|
| caab252ce | test(545): failing tests (RED) |
| 1cc7bf759 | feat(545): daily rule d2-v4 (GREEN) |

## What changed

- `src/intelligence/bars/daily_rule.py`: `RULE_VERSION = "d2-v4"`.
  - `(alpaca, sip_rth)` is in `RAW_DAILY_SERIES`, `PRIMARY_PAIR["alpaca"] = ("alpaca", "sip_rth")` and route `ALPACA`.
  - `FALLBACK_FOR` allows IBKR as the only fallback, for Tradier or Alpaca.
  - `RAW_DAILY_SESSION_ZONE` and `raw_session_date` define the session date of each series.
  - The Alpaca guards run in `_screen`. The head and interior rules work per primary through `_BasisFrame`, each on its own pair axis, so a Tradier-era decision never depends on Alpaca rows.
  - `servable_primary_dates` is new.
  - The result gains `zero_volume`, `pre_start` and `alpaca_start`.
- `services/bar_derivation.py`: the raw read joins a third array of session zones and dates each row `(timestamp AT TIME ZONE s.zone)::date` (`_RAW_DAILY_ZONES`). The report, load detail and run summary carry the guard counts.
- `services/bar_reconciliation_audit.py` (D7) passes the zone array.
- `src/intelligence/bars/integrity_checks.py`: `policy_conformance` takes the servable dates per primary, so `(ibkr, fallback)` conforms wherever the primary cannot serve: a hole, a head, stale scale, or, for Alpaca, zero volume or a date before the span start.
- `sources.CANONICAL_1D_SOURCES` gains `("alpaca", "sip_rth")`, and `vendor_kind.canonical_kind_for_raw` maps it to `sip_rth`.

## Decisions

- Canonical kind `sip_rth`. Canonical 5m already carries Alpaca rows as `(alpaca, sip_rth)`, and the CVR `bar_kind` namespace holds `sip_rth` (sort order 10). No migration was needed. The tradeable view leaves `sip_rth` volume intact (it nulls only `venue` and `fallback`), so the consolidated volume reaches research. An IBKR fallback session inside the Alpaca era reads NULL volume, the d2-v2 convention.
- Session dates. Alpaca's 04:00 or 05:00 UTC stamp is dated in New York; IBKR's and Tradier's 00:00 UTC stamp in UTC. Observations carry only the session date. The rule emits one bar per session, and the writer stamps it 00:00 UTC (`_utc_day`), so no second row can exist for a session.
- Guard 1, zero volume. An Alpaca bar with volume 0 or NULL is dropped before any other read: no basis ratio, no head, no anchor. The session falls through to the IBKR fallback under the ordinary interior or head test, or has no bar.
- Guard 2, listing. No trustworthy point-in-time listing date exists:
  - `instrument_metadata.listing_date` covers 63 of 166 rows and is upserted in place.
  - `listing_venue.valid_from` and `ohlcv_provider_head` are both IBKR's own first bar.

  The guard therefore anchors on the contract-keyed vendor. The Alpaca span starts at the first session where IBKR's current close agrees with Alpaca's within `fallback_basis_tolerance_bp`, both on that session and in the median of the `fallback_basis_window_sessions` common sessions from it (the head seam test). This is stricter than "IBKR has a bar". AA shows why: IBKR's contract trades when-issued from 2016-10-18 at about 16 while Alpaca's ticker still prints the old Alcoa at about 80 until 2016-11-01. An IBKR-has-a-bar anchor would serve 10 predecessor bars. The agreement anchor starts at 2016-11-01, and the 10 IBKR sessions before it are a seam-flagged head. Alpaca dates before the start are listed in `pre_start` and never served.
- Tradier code stays, and Tradier stays unguarded so that d2-v3 is unchanged.

## Verification

- Bit identity on the fixture: golden sha256 digests of every d2-v3 result over the known-case fixture (5 cases, 4 policy shapes) were taken at 1e88ae9aa before the bump. d2-v4 reproduces all 20, with and without synthetic Alpaca rows that include zero-volume and off-axis sessions.
- Bit identity on live inputs: a read-only session ran the HEAD d2-v3 copy and d2-v4 over all 1,523 names holding Alpaca 1d rows, under the live policy rows. Mismatches: 0.
- Gate: targeted suites pass, `pytest tests/unit/ -n auto` is green, and ruff and black are clean.
- Fresh-context review did not run. Codex is out of quota until 2026-11-26 and AGY for about 162 hours. The executor reviewed its own diff. That item of step 3 stays open.

## Measured under an in-memory D-191-Q policy (read-only, 2026-10-27, step 1 backfill still running)

Policy: IBKR before 2016-01-04; Alpaca primary with IBKR fallback from 2016-01-04. Over 1,523 names:

| Quantity | Value |
|----------|-------|
| Alpaca sessions served | 2,549,972 |
| IBKR fallback sessions | 847,250 (includes names whose Alpaca history the backfill has not reached) |
| zero-volume Alpaca sessions | 5,604 on 51 names (CORZ 276) |
| Alpaca sessions before the span start | 189,886 |
| of those, IBKR holds a bar (basis disagreement) | 90,484 on 69 names |
| of those, IBKR has no bar yet | 99,402 on 87 names |
| refused interior | 14 |
| names with no Alpaca span | 0 |

The 69 disagreement names are spin-offs. IBKR (and Tradier) adjust a name's history for a spin-off; Alpaca's split adjustment does not. IBKR/Alpaca measured 0.9718 on ILMN before 2024-06-25, 0.7557 on WDC before 2025-02-24, and 0.8265 then 0.9898 on J. The largest cases are SCCO, SPGI, HON, FDX, BDX, CMCSA, J, WDC, LEN, FTV, ILMN, APTV, GE (2024-04-03), MMM (2024-04-01), DHR (2023-10-02) and LH (2023-07-03). Under the guard, these names serve IBKR's adjusted history as the fallback head until the event: returns are right, volume is NULL. Serving Alpaca there would put each spin-off on its ex-date as a false return. The D-191-Q sample (21 names against Tradier) contains no such event, which is why it did not show this.

The 87 IBKR-missing names (CORZ, PCTY and others) are mostly names whose IBKR 1d history currently starts at 2026-08-28. The running IBKR pass should shrink this count. A re-derive after it lands reports the rest.

## For step 4 and later

1. Owner decision before step 4: spin-off names. The guard keeps returns right and gives up Alpaca's consolidated volume before each spin. The alternative is spin-off-adjusting Alpaca's 1d history from a corporate-action record (no such record exists; `corporate_action` holds splits). The guard keeps returns right and loses data rather than inventing it, so it stays the default.
2. `ops_source_policy.py --plan` cannot express the 1d decision as written:
   - `_CLOSE_DEFAULT_SQL` closes the open 1d default (IBKR from 2026-10-07) at the seam, and 2016-01-04 precedes that row's `valid_from`, which violates its `valid_to > valid_from` check.
   - The closed Tradier default (1990-01-01 to 2026-10-07) overlaps a new Alpaca default from 2016-01-04.

   The 1d plan has to retire both defaults and insert two: IBKR from 1990-01-01 to 2016-01-04, and Alpaca with IBKR fallback from 2016-01-04. `--plan` also retires every live symbol row, so the 154 1d symbol rows (143 names) need their disposition decided first.
3. The rule version moved. The IBKR fetcher's end stage (`--stage daily --apply` on the names it touched) now runs d2-v4 from this checkout. Its bars are identical under the current policy, but it relabels those names' 1d digests d2-v4. D7's `digest_fresh` fails for every name until a daily run rewrites its digests (plan 20 Task 3's re-derive, or a `--rewrite-digests` run). `tests/integration/test_d2_single_writer_live.py` asserts the live lineage rule version and fails until then too.
4. Splits. An Alpaca 1d row served before a recorded split is stale for earlier dates. The nightly asks only the tail, so after each split a name's older Alpaca sessions take the restated IBKR fallback (or are quarantined `pre_split_unrefetched`) until Alpaca's history is asked again. The split re-ask that IBKR has (`_escalate`) has no Alpaca 1d counterpart yet.
5. D7's `vendor_basis_run` measures Tradier against IBKR only and goes vacuous after the Tradier deletion. It needs an Alpaca-against-IBKR run before step 5 relies on D7. `services/bar_hold.py` `_VENDOR_RATIOS_SQL` reads SMART and TRADIER only.
6. `scripts/ops/bars/ops_bar_nightly.py` docstring ("a vendor daily can never author -- IBKR owns 1d") is stale in its last clause. It was left alone because the backfill is running. The fence itself (`LoadPolicy` refuses a derivation-owned timeframe) is still correct, because the daily stage, not the vendor load, writes canonical 1d.
