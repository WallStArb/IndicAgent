# Massive plan lapse: dated checklist and renewal recommendation

**Status:** Plan, 2026-11-15. Nothing here has been run. No capture starts while step 7 Part C is live (one heavy job at a time); the commands below are for after Part D, in the dates given.
**Author:** Claude (indicagent-65), 2026-11-15, on the lead's brief (todo 600 open items 5, 7, 9 and 10).
**Informed by:** `.planning/todos/pending/600-massive-flat-files-all-history-vendor.md`, `docs/plans/2026-11-10-massive-admission-db-design.md`, `docs/operations/massive-step7-runbook.md`, `docs/ideas/vendor-pre2016-intraday-history.md`, `docs/plans/2026-11-15-stage2-5m-tier-and-intraday-universe.md`, `docs/plans/2026-11-15-family10-volume-shock-prereg-draft.md`, `.planning/STATE.md`, and a read-only check of `data/massive/` on ubuntu1 and the mirror on ubuntu2 (2026-11-15).
**Owner decision, outward-facing:** renewing or lapsing the Massive plan spends money with an outside vendor. The recommendation below is the lead's input; the owner decides.

## Dates

| Date | What |
|---|---|
| Today to about 2026-11-17 | Part C and D1 to D4 finish; nothing in this doc runs before D5 |
| 2026-11-30 | Last NYSE month-end inside the plan; the stage 2 membership needs its ticker list (item 9c) |
| 2026-12-01 | Filings sizing decision due (item 7) |
| About 2026-12-07 | Final reference capture, file catch-up and verification (item 9) |
| About 2026-12-10 | The plan lapses (todo 600 item 9, STATE). The exact date is not recorded in the repo: read it off the Massive account page and replace "about" here |

## What is already on disk (verified read-only, 2026-11-15)

| Asset | Coverage | Where |
|---|---|---|
| Flat files, both aggregates | 5,833 day files and 5,833 minute files, 2003-09-10 to 2026-11-13; the inventory (11,666 keys) equals the manifest (11,666 keys), no key missing either way; 87.9 GB recorded | `data/massive/files/`, `data/massive/manifest/` |
| Serve labels | ETag, `Last-Modified` and sha256 on every manifest record; the 2026-11-10 drift report is empty | `data/massive/manifest/` |
| Reference capture of 2026-11-10 | 332,019 responses: per-ticker overview, events, short interest, short volume, income statements, balance sheets, cash flow statements, ratios and float for 36,869 ticker keys each (events 13,829 answered and 23,040 answered 404; overview 36,367 answered and 502 answered 404), plus the list endpoints (active and delisted tickers, splits, dividends, IPOs) and the exchange, condition, ticker-type and holiday tables; 56 minutes end to end | `data/massive/reference/` |
| Point-in-time ticker lists | 6,132 files, each NYSE month-end from 2003-09 to the last file day then known, active and inactive (captured 2026-11-13, 5 minutes) | `data/massive/reference/pit_snapshots/20261113/` |
| Backups | Reference tree tarball of 2026-11-10 (555 MB; it predates the pit snapshots). The ubuntu2 mirror (`/home/bg/mirror`, nightly pull, no `--delete`) holds all 11,666 flat files and 338,431 reference files, the same count as ubuntu1. No off-site copy (owner 2026-11-15, todo 618 closed as accepted risk) | `data/backups/massive-reference-2026-11-10/reference.tar.gz`, ubuntu2 |

Not captured: filings (EDGAR index, 8-K, Form 4), news, and any REST family beyond the list above. Corporate actions were captured as of 2026-11-10 only, so splits and dividends announced since then are not in the files; point-in-time rules (`recorded_at`) mean a later capture is a new dated directory, never an overwrite.

## What cannot be recaptured after the lapse

- Every file the vendor posts after the last download and before the lapse (new trading days). After the lapse the bucket is expected to list but not serve (the free plan "lists only", memo of 2026-11-08; unverified for a lapsed paid plan), so downloads stop and only `--restat` drift detection keeps working.
- A vendor restatement of an existing key. The downloader keeps superseded bytes, but only if the plan is live when the restatement happens.
- Dated as-of snapshots. Short interest, short volume, float, overview, ratios and the statements are each one capture as of 2026-11-10; the next capture as of any later date needs the plan.
- The 2026-11-30 month-end ticker list and every later one. The stage 2 membership rule reads the active and inactive lists as of each month-end.
- Corporate actions announced after 2026-11-10 from Massive (Alpaca and the dividend scrape remain, which are not point-in-time witnesses of the same kind).

Not at risk: everything in the table above (two copies, ETag-verifiable), and the stage 2 5m tier (it reads the archive already acquired, so the lapse does not limit it: tier doc, line 39).

## Item 9: the capture before the lapse

Run in this order after D5, one heavy job at a time, detached with `setsid`, never while a Massive loader or step 7 job runs. Confirm the lapse date first.

1. Drift check, light network, no download:

```bash
.venv/bin/python -m scripts.infrastructure.massive.massive_download --restat
```

Expect an empty report. A key the vendor restated is a lead decision (the downloader moves the old bytes aside, never overwrites).

2. Final file catch-up, download only (no raw load; the seam stays pinned at 2026-11-16 by the runbook override, so new files cannot move it):

```bash
.venv/bin/python -m scripts.infrastructure.massive.massive_download --refresh-inventory --date-from 2026-11-14
```

Files after the pinned seam are raw only; they are a second witness for the Alpaca tail (family 10 draft, section 6 item 4: measured Massive over Alpaca volume ratio median 0.99993 over 305,718 name-days of 2026).

3. Full verification, heavy I/O (re-hashes 88 GB), only when no other heavy job runs:

```bash
.venv/bin/python -m scripts.infrastructure.massive.massive_download --verify
.venv/bin/python -m scripts.infrastructure.massive.massive_download --verify-etag
```

Exit 0 on both; any defect names the file, and the plan still serves it until the lapse, so fix before then.

4. Final reference capture dated after 2026-12-01, about 56 minutes with the 2026-11-10 settings (`--concurrency` as then; the tool refuses a second run and resumes with the same `--captured-at`):

```bash
.venv/bin/python -m scripts.infrastructure.massive.massive_reference_capture --captured-at 20261207
```

5. Month-end ticker lists for 2026-11-30 (and any later NYSE month-end before the lapse), about 5 minutes for the earlier 6,132 files so seconds for these:

```bash
.venv/bin/python -m scripts.infrastructure.massive.massive_reference_capture --pit-snapshots --pit-dates 2026-11-30
.venv/bin/python -m scripts.infrastructure.massive.massive_reference_capture --pit-snapshots --pit-dates 2026-11-30 --apply
```

The first form only prints its units; read them before `--apply`. Checked read-only on 2026-11-15: the dry run for `--pit-dates 2026-11-30` lists 2 units and exits 0, because `--pit-dates` takes any date; only the default list is capped at the archive's last file day. Run it on or after 2026-11-30. Open point for the stage 2 preregistration: membership after the last captured list needs a stated source once the plan lapses; the draft is `docs/plans/2026-11-15-stage2-membership-after-archive-end-amendment-draft.md` (closed list, no entrants), pending owner adoption.

6. Entitlement probe: one request per candidate REST family not in the 2026-11-10 capture, a 403 meaning not entitled. No tool exists for an arbitrary probe; write a throwaway script that reads `MASSIVE_API_KEY` from `.env` into an Authorization header (never argv, a file or a logged URL, the capture tool's own rule) and writes the status lines to `data/massive/reference/probe_20261207.jsonl`. Candidates, unverified and named from the vendor's public API families, not fetched here: news, related companies, REST aggregates, trades, quotes, technical indicators, and the filings families of item 7. Probe a family only if a hypothesis or a data-adjacency-register row names a consumer; a family with no consumer is not worth a capture.
7. Back up and mirror: tar the reference tree again after step 4 (the 2026-11-10 tarball does not hold the pit snapshots or the new capture), to a new dated directory under `data/backups/`, and let the nightly mirror pull the new files before the lapse. Then record the lapse date, the final manifest key count and the verify exit codes in todo 600.

## Item 7: filings (decide by 2026-12-01)

- Requirement (Musk step 1): a filing-date source for point-in-time features that need the original filing time (restated statements, 8-K events, Form 4 trades). No hypothesis in the backlog or the shortlist consumes one today (`docs/ideas/ranked-backlog-2026-11-15.md`: SEC filing text is parked, new data class).
- The statements Massive serves key on filing date only (`.planning/IDEAS.md`, 2026-11-07), which leaks restatements; EDGAR direct is free, carries acceptance timestamps and does not lapse.
- Recommendation: capture no filings from Massive. Do the one entitlement request of step 6 so the answer is recorded, then decide the source question on EDGAR direct as its own todo, not under this deadline. Record "no filings capture" in todo 600 by 2026-12-01.

## Item 5: measured decisions

- Nightly consolidation onto Massive: moot under a lapse (the Alpaca nightly stays the incumbent and is already running again after D5). Under a renewal it needs the publish-lag measurement of runbook A12 first.
- Post-2016 consolidation onto one vendor: decided by step 7 (Massive to the archive end, Alpaca after, no fallback). Close under the step 7 record.
- Stage 2 universe: todo 609, separate; its Massive dependencies are the captures above and the pit lists.
- Not date-critical and not a lapse item: the Parquet landing zone (`.planning/IDEAS.md`), and trade count and average trade size (`ohlcv_raw` holds OHLCV only; the day and minute files already on disk carry `transactions`, so a later load needs no vendor).

## Item 10: the nightly leaf

- `scripts/ops/bars/ops_massive_nightly.py` and `production/systemd/indicagent-massive-nightly.{service,timer}` are on `main`; the timer is not installed (`systemctl is-enabled` reports not-found). STATE says the leaf is an unpushed worker worktree; that text is stale and should be corrected at the next STATE edit.
- Under a lapse: never install the timer. Use the leaf once, by hand, for the final catch-up if the loader should also see the new months (`ops_massive_nightly --apply`, after D5; its quiet check refuses while a step 7 job runs). Otherwise item 9 step 2 is enough.
- Under a renewal: install per `docs/operations/operations-database.md` (item 2b); scope is ruled (new days only, repost reported not reloaded).

## Recommendation: lapse, owner decision

Lead recommendation: do not renew, after the item 9 capture is done and verified.

For the lapse:
- Everything the research path reads is on disk twice and ETag-verifiable; the archive, reference tree and pit lists are the keep-everything artifact (capture law 528).
- Canonical stops using Massive at the pinned seam (2026-11-16); the forward tail is Alpaca, which is free and was measured against Massive over 2026 at a median volume ratio of 0.99993 (5th to 95th percentile 0.9985 to 1.0005). Renewal buys a second witness for that tail and a self-updating archive, not a data need.
- The stage 2 5m tier reads the archive already held, so the lapse does not limit it.
- The cost of renewal is recurring spend for those two conveniences. The price is not recorded anywhere in the repo, so the owner supplies it; the decision rule is: renew only if one more month is trivially cheap and a named consumer needs data after 2026-12-10.

Against the lapse (accepted if the checklist is done):
- No re-download insurance: after the lapse the two same-site copies are the only copies, and there is no off-site copy (owner accepted the risk 2026-11-15). Verify both copies match (item 9 step 7) before the date.
- No later point-in-time captures: ticker lists, short interest, float and statements stop at the last capture; months after it have no Massive witness.
- Not irreversible, on an inference to confirm on the account page: the plan was bought for one month, so a month can presumably be bought again if a need appears; what is lost for good is only what the vendor served between lapse and re-purchase that was not captured.

If the owner prefers optionality, the cheaper hedge than renewing is a second dated reference capture and file catch-up at the last possible day before the lapse (the ones above, moved to the lapse date minus one day) with the month-end list of 2026-11-30 included.

## Done when

The owner has decided renew or lapse and todo 600 records it; items 9 steps 1 to 7 have exit codes and counts recorded in todo 600; the filings decision is recorded by 2026-12-01; the stale STATE sentence on the nightly leaf is corrected; and if the plan lapses, the lapse date and final manifest count are written in todo 600 and the todo moves to completed.
