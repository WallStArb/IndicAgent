# Massive final capture (plan lapse, about 2026-12-10)

Status: capture running 2026-11-26 (owner order). Raw files only; nothing loads them into the
database. Tool: `scripts/infrastructure/massive/massive_final_capture.py` (reuses the reference
capture's retry, pagination, resume and verify). Entitlement source: the 2026-11-20 probe in
`.planning/todos/pending/600-*.md` and `data/massive/reference/probe_20261120.jsonl`.

## Sizing (read-only probes, 2026-11-26)

Sizes are gzip bytes on disk (the stored form). Projections come from sampled pages; actuals are
filled in from `final_manifest/20261126.summary.json` when a family completes.

| Family | Requests | Projected | Basis |
|---|---|---|---|
| economy (4 series) | 4 | under 1 MB | one page each, full history |
| news | about 940 | 0.25 GB | 2016-06 onward, month slices; 2016 to mid 2020 almost empty, 100 to 740 articles per day since |
| related companies | 13,778 | under 0.1 GB | one answer per active ticker, 0.3 KB each |
| fx and crypto lists | 5 | under 1 MB | 1,097 fx (97 inactive), 625 crypto |
| fx and crypto daily aggregates | about 1,720 | 0.05 GB | about 625 bars per pair: the plan serves two years only (from 2024-11-26); older starts are clamped |
| options contracts | about 110,000 pages | 0.8 to 1.0 GB | 2.3 MB gzip per monthly expiry day (319 pages of 1,000), 0.6 MB per ordinary Friday, history from 2010-02 (sparse before 2015-06), active contracts to 2029 |
| filings text | about 4,000 pages | 5 to 12 GB | risk factors 1 to 2 MB per month, 8-K text 5 MB per month, 10-K sections 40 MB per 25 pages (about 60 KB per section row, 2013 onward and earlier) |
| options daily aggregates | not run | n/a | see below |

Total projected: about 8 to 15 GB, far under the 250 GB budget. ubuntu1 had 1.5 TB free. The
ubuntu2 mirror had 194 GB free, which is the real ceiling: the nightly pull already carries 102 GB.

Not captured, with the reason:

- Options daily aggregates: one request per contract per range, so the requests number in the
  millions (about 320,000 contracts for a single expiry day) and the aggregate endpoints answer
  only about 5 requests per minute (see below). Cannot finish before the lapse.
- Trades and quotes tapes (4.1 TB and 15.2 TB): out of scope by the lead's ruling.
- Benzinga, options snapshot chain, indices, all non-stock flat-file prefixes: 403.

## Vendor behaviour found

- Aggregate endpoints (`/v2/aggs/...`) answer 429 ("maximum requests per minute") after a burst of
  about 5 requests, then recover after about 50 s. The family is paced at one request per 13 s
  (`AGGS_MIN_INTERVAL_S`), so the 1,720 pairs take about 6 hours. Every other family ran at 5 to
  10 requests per second with concurrency 2 and no 429.
- fx and crypto history is capped to a rolling two years: a request from 2000-01-01 returns bars
  from 2024-11-26 only, and a range wholly older than the window returns 403. The window rolls
  forward each day, so a capture that runs later loses early bars permanently.
- Options contracts: the `expired` flag splits the listing (a contract lists as active until it
  expires). `expiration_date=` queries older than 2015-06 return days with no rows next to days with
  rows, so coverage before 2015-06 is partial on the vendor side.
- Filings: each path accepts only its own sort field (10-K sections `period_end`, the others
  `filing_date`); a wrong field is a 400.
- News has no history before 2016-06-22.

## Layout and guards

Each family writes `data/massive/reference/<endpoint>/<captured_at>/<key>__pNNNN.json.gz`, one
manifest line per page in `data/massive/reference/final_manifest/<captured_at>.jsonl` (endpoint,
key, page, URL without credentials, status, bytes, sha256, fetched_at), and a summary of counts and
the manifest's own sha256 in `final_manifest/<captured_at>.summary.json`. The manifest directory is
not `manifest/`, so the reference loader never sees these files.

- Pages are written to `.part`, fsynced and renamed; a record is appended after the rename.
- Resume: rerun with the same `--captured-at`; a recorded page whose file matches its size and
  sha256 is skipped.
- `--budget-gb` (250) caps bytes written, `--min-free-gb` (400) stops the run, 401 stops the run
  (exit 3), a 403 denies one family and the rest continue (exit 1), a unit that fails after the
  retry passes is listed and never recorded as complete.
- One capture per `--captured-at` (file lock); concurrency 2.

```
.venv/bin/python -m scripts.infrastructure.massive.massive_final_capture --captured-at 20261126 \
    --reference-captured-at 20261126 [--only economy,news,...]
.venv/bin/python -m scripts.infrastructure.massive.massive_final_capture --captured-at 20261126 --verify
```

## Mirror to ubuntu2

`production/standby/data_mirror.sh` (the nightly pull at 04:30Z, installed at
`/home/bg/standby/data_mirror.sh` on ubuntu2) pulls all of `~/dev`, so the new directories ride along
with no change. The script now refuses to start when the mirror disk has under 40 GB free (exit 3,
`MIRROR_MIN_FREE_GB` overrides) and its repository copy carries the `data/massive/tapes` exclude the
installed copy already had. After a pull:

```
.venv/bin/python -m scripts.infrastructure.massive.massive_final_capture --captured-at 20261126 --mirror-verify
```

compares every file of the capture (path and size) with ubuntu2 over a read-only `ssh find` and
exits 1 on a missing or differing file. `--mirror-push` runs an additive `rsync` of just those
files (no `--delete`) and refuses when the mirror would be left under 40 GB.
