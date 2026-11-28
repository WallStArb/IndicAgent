# Massive plan lapse: dated checklist and renewal recommendation

**Status:** Condensed 2026-11-26. Decided: the plan lapses (owner 2026-11-26). The commands and remaining order are in `docs/operations/massive-final-capture.md`; this doc keeps the dates, what is on disk, what cannot be recaptured, and the disposition of the lapse items.
**Author:** Claude (indicagent-65), 2026-11-15, on the lead's brief (todo 600 open items 5, 7, 9 and 10).
**Informed by:** `.planning/todos/pending/600-massive-flat-files-all-history-vendor.md`, `docs/plans/2026-11-10-massive-admission-db-design.md`, `docs/operations/massive-step7-runbook.md`, `docs/ideas/vendor-pre2016-intraday-history.md`, `docs/plans/2026-11-15-stage2-5m-tier-and-intraday-universe.md`, `docs/plans/2026-11-15-family10-volume-shock-prereg-draft.md`, `.planning/STATE.md`, and a read-only check of `data/massive/` on ubuntu1 and the mirror on ubuntu2 (2026-11-15).
**Owner decision (2026-11-26):** lapse; renew only if go-live needs it (the plan's purpose, 20-plus years of history for all stocks, is met). No HX370 copy.

## Dates

| Date | What |
|---|---|
| Today to about 2026-11-17 | Part C and D1 to D4 finish; nothing in this doc runs before D5 |
| 2026-11-30 | Last NYSE month-end inside the plan; its ticker list is raw evidence only, because L stays 2026-11-09 (ruling 2026-11-16) |
| 2026-12-01 | Filings sizing decision due (item 7) |
| About 2026-12-07 | Final reference capture, file catch-up and verification (item 9) |
| About 2026-12-10 | The plan lapses. The final pass (2026-12-01 or 12-02) runs before any December expiry, so the exact date is not needed |

## What is already on disk (verified read-only, 2026-11-15)

| Asset | Coverage | Where |
|---|---|---|
| Flat files, both aggregates | 5,833 day files and 5,833 minute files, 2003-09-10 to 2026-11-13; the inventory (11,666 keys) equals the manifest (11,666 keys), no key missing either way; 87.9 GB recorded | `data/massive/files/`, `data/massive/manifest/` |
| Serve labels | ETag, `Last-Modified` and sha256 on every manifest record; the 2026-11-10 drift report is empty | `data/massive/manifest/` |
| Reference capture of 2026-11-10 | 332,019 responses: per-ticker overview, events, short interest, short volume, income statements, balance sheets, cash flow statements, ratios and float for 36,869 ticker keys each (events 13,829 answered and 23,040 answered 404; overview 36,367 answered and 502 answered 404), plus the list endpoints (active and delisted tickers, splits, dividends, IPOs) and the exchange, condition, ticker-type and holiday tables; 56 minutes end to end | `data/massive/reference/` |
| Point-in-time ticker lists | 6,132 files, each NYSE month-end from 2003-09 to the last file day then known, active and inactive (captured 2026-11-13, 5 minutes); the last entry is 2026-11-09, so the 2026-11-30 month-end is the one to add | `data/massive/reference/pit_snapshots/20261113/` |
| Backups | Reference tree tarball of 2026-11-10 (555 MB; it predates the pit snapshots). The ubuntu2 mirror (`/home/bg/mirror`, nightly pull, no `--delete`) holds all 11,666 flat files and 338,431 reference files, the same count as ubuntu1. No off-site copy (owner 2026-11-15, todo 618 closed as accepted risk) | `data/backups/massive-reference-2026-11-10/reference.tar.gz`, ubuntu2 |

Not captured: filings (EDGAR index, 8-K, Form 4), news, and any REST family beyond the list above. Corporate actions were captured as of 2026-11-10 only, so splits and dividends announced since then are not in the files; point-in-time rules (`recorded_at`) mean a later capture is a new dated directory, never an overwrite.

## What cannot be recaptured after the lapse

- Every file the vendor posts after the last download and before the lapse (new trading days). After the lapse the bucket is expected to list but not serve (the free plan "lists only", memo of 2026-11-08; unverified for a lapsed paid plan), so downloads stop and only `--restat` drift detection keeps working.
- A vendor restatement of an existing key. The downloader keeps superseded bytes, but only if the plan is live when the restatement happens.
- Dated as-of snapshots. Short interest, short volume, float, overview, ratios and the statements are each one capture as of 2026-11-10; the next capture as of any later date needs the plan.
- The 2026-11-30 month-end ticker list and every later one. The stage 2 membership rule reads the active and inactive lists as of each month-end.
- Corporate actions announced after 2026-11-10 from Massive (Alpaca and the dividend scrape remain, which are not point-in-time witnesses of the same kind).

Not at risk: everything in the table above (two copies, ETag-verifiable), and the stage 2 5m tier (it reads the archive already acquired, so the lapse does not limit it: tier doc, line 39).

## Disposition of the lapse items (todo 600)

- Item 5, measured decisions: nightly consolidation onto Massive is moot under a lapse (the Alpaca nightly stays the incumbent); post-2016 consolidation was decided by step 7 (Massive to the archive end, Alpaca after, no fallback); the stage 2 universe is todo 609. Not lapse items: the Parquet landing zone (`.planning/IDEAS.md`), and trade count and average trade size (the day and minute files on disk carry `transactions`, so a later load needs no vendor).
- Item 7, filings: the owner's 2026-11-26 order to capture every entitled dataset supersedes the 2026-11-15 ruling of no filings capture; the final capture takes filings text (sizing in `docs/operations/massive-final-capture.md`). Statements Massive serves key on filing date only (`.planning/IDEAS.md`, 2026-11-07), which leaks restatements; EDGAR direct (free, acceptance timestamps, does not lapse) stays the clean source and its own todo if ever needed.
- Item 9, the capture: restat, file catch-up, verification and the reference capture ran or are scheduled in the final-capture doc. The 2026-11-20 entitlement probe and tape sizing stand (`data/massive/reference/probe_20261120.jsonl`; findings in todo 600).
- Item 10, the nightly leaf: `scripts/ops/bars/ops_massive_nightly.py` and its unit and timer are on `main`; the timer was never installed. Under a lapse it stays off, and the leaf is deleted after the lapse if the plan is not renewed. Under a renewal, install per `docs/operations/operations-database.md` (scope ruled 2026-11-14: new days only, a vendor repost is reported and never reloaded).
