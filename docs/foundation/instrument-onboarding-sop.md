# Instrument onboarding SOP

Author: Claude Opus 5.5, 2026-09-26, at Brandon's request. Informed by the 2026-09-26 expansion
(273 -> 932 names), `docs/plans/2026-09-26-daily-data-foundation.md` (phase 185) and
`docs/plans/2026-09-26-unified-research-to-production-design.md` (E18).

How a security enters the universe, from a source file to a name research can read. Scope is the
1d path, the one that is built and proven. The intraday path (`compute_eligible`) is out of scope
until the phase 186 `feature_vectors` rebuild defines it; do not promote a name to `compute` in
the meantime.

## Principles

Adding names is a research decision, not housekeeping: the universe decides what every later
test can find. Six rules follow from that.

1. **Select without looking at outcomes.** The rule that picks names is written down before any
   of their data is fetched, and uses only facts known on the selection date: index membership,
   the price and weight in the holdings file, the asset class. Never history length, returns,
   volatility or data availability. The 2026-09-26 history screen broke this rule: it dropped
   names with no IBKR bar before 2016, which removed names that had changed listing venue (todo
   433) and tilted the small-cap draw toward long-listed firms. It was deleted and the 70 names
   it dropped were onboarded. Short histories are handled by each research panel's coverage
   rules, never at the door.
2. **Every name traces to its source.** Source file (committed, with its SHA-256), selection rule
   (seed, parameters, script revision), manifest row, onboarding time. `config/universe/README.md`
   holds the lineage and every deviation from a clean draw.
3. **One writer per fact.** `instruments`, `instrument_tags`, `instrument_classification` and
   `instrument_metadata`: `onboard_instrument()` only, called by the manifest onboarder. Raw 1d
   answers: the ingress write contract (D1, `ohlcv_load`, `ohlcv_revision`). Canonical 1d bars:
   the d2-v2 daily derivation (`services/bar_derivation.py`), the one writer, choosing each
   name's source by `bar_source_policy`. Verdicts: the D7 audit. Eligibility flags: the promote
   script only. No hand `INSERT` or `UPDATE` on any of them.
4. **Stages are a DAG over persisted state.** Each stage reads what the previous one wrote and
   nothing else, is dry-run by default, and is safe to rerun. A stage that fails leaves the
   database as it was, or in a state the same command resumes from.
5. **Gates count ground truth.** Promotion reads computed verdicts, not bookkeeping: every
   required `bar_integrity` check D7 writes must be passed and fresh (the verdict gate,
   `src/intelligence/bars/verdict_gate.py`, plan 185-41). A log line saying "0 fetch errors" is
   not evidence: CLBK passed the fetch with no error and zero bars, and only the gate held it.
6. **Nothing leaves.** A name is never deleted or deactivated, even after it stops trading; its
   bars simply stop. Research selects its universe from current `instruments` flags
   (`snapshot.py::universe_symbols`), so deactivating a dead name would erase it from every later
   panel and bring survivorship bias back.

## Universe dimensions

`is_active` alone conflates three scopes, so eligibility is three columns (migration 337, phase 174;
read through `get_active_contracts(dimension=)`):

- `compute_eligible_1d`: the name enters 1d research. Set by stage 9's promote once its 1d
  verdicts pass.
- `compute_eligible`: the name carries the intraday stack (233 names). Out of scope for this SOP.
- `live_tradeable`: the name may receive capital. False for every name today; no rule sets it yet
  (a note on todo 437).

## Known biases every onboarding carries

State them in the README entry for the batch; research discloses them through phase 185 D0.

- **Survivorship.** Sources are current index holdings, so every batch holds only names alive on
  the selection date, and their history back to 2006 is history of survivors (todo 376). IBKR
  serves no delisted names. Forward capture of delistings (185 D8) was descoped by the owner
  2026-09-26: few names in this universe delist, and rule 6 keeps any that do in the panels.
- **Current-cap selection.** Batch 1 and wave 2 chose names by today's market-cap rank from
  current index holdings. Today's rank reflects past returns, so it is an outcome-conditioned
  selector. A size or momentum claim needs point-in-time cap, never the holdings rank (todo 491 adds
  the entry date and cohort research needs to see it).
- **Venue truncation.** IBKR SMART history starts at a name's last listing-venue move (todo 433).
  The former venues' answers are kept in D1 but stay out of canonical bars (the 185 D3 venue
  study failed, so `infra.bar_derivation.venue_bars_1d` is false); `listing_venue` (D6) records
  the move. A Tradier-owned name's daily history does not have this truncation.
- **Scrubbed, not cleaned.** Bad prints are flagged, never edited: the daily derivation runs the
  D2a scrub rules and a quarantined bar disappears from `market_data_ohlcv_tradeable` while the
  stored bar stays. The 1d dry run on 2026-09-26 found 45 corrupt bars across the 932 names.
- **Price-only bars.** Stored bars are split-adjusted, not dividend-adjusted. Dividends live in
  `dividend_events` (Yahoo, refreshed daily for every active equity; todo 428), and a research
  spec gets total-return prices only if it declares `panel.total_return`. A newly onboarded name
  gets its dividend history on the next daily run (06:30 UTC); before that a total-return spec
  treats it as uncovered (NaN), never as paying nothing.

## The DAG

```
source snapshot ─> select ─> classify ─> manifest ─> qualify ─> write ─> fetch 1d ─> verify ─> promote ─> record
 (holdings CSV)   (draw,     (IBKR       (reviewed   (IBKR,     (one     (D1, then  (holds,    (compute_  (README,
                  read-only)  details +   CSV)        no txn)    txn)     derive,    heads,     eligible_  commit)
                              review)                                     scrub)     flags)     1d)
```

Stages 1-4 write no database table. Stages 5-6 are one script. Nothing downstream of `promote`
needs a manual step once the IBKR history fetcher's timer runs (phase 189 plan 10): it keeps
every active name's 1d current, the nightly D7 audit judges it, and research reads the name at
its next snapshot.

## Stages

Run every command from the main checkout (`/home/bg/dev/indicagent`). IBKR must be up:
`docker ps | grep ib-gateway`, and remember the weekly 2FA logout (todo 395). IBKR client IDs:
35 is the provider, 40 the history fetcher, 45 the gateway probe, 46 the manifest qualifier; pick
another ID at or below 50 for a manual run. Only one IBKR history fetch runs at a time: the
fetcher's `FetcherLock` refuses a second one loudly.

### 1. Source snapshot

Download the index holdings and commit the file under `config/universe/` with its date in the
name.

```
.venv/bin/python scripts/infrastructure/universe_expansion_fetch_iwv_holdings.py \
    --url <iShares holdings CSV URL> --dest config/universe/<fund>_holdings_<YYYY_MM_DD>.csv
```

For hand-chosen ETF cohorts (country, sector, commodity, fixed income), the source is the written
rationale for the cohort, recorded in the README before the manifest is built: which gap in the
universe the cohort fills and what was left out and why (IGOV as a near-duplicate of BWX, for
example). The rationale never cites the candidates' returns.

### 2. Select

Index constituents are taken whole (the S&P 500) or drawn mechanically:

```
.venv/bin/python scripts/infrastructure/universe_expansion_holdings_draw.py \
    --holdings config/universe/iwm_holdings_<date>.csv --out config/universe/<name>_draw_<date>.csv \
    [--size N] [--min-price 5] [--skip-top 1000]
```

The draw is seeded and cap-stratified (seed and bucket count from APR), excludes names already
held, and writes a provenance JSON beside the list. Rules:

- Exclude names held in `instruments` and in every other draw of the same batch. The 2026-09-26
  draws each excluded only `instruments`, so five names landed in both; the README discloses it.
- A drawn name is onboarded as drawn. No replacement in-bucket, no second screen.
- `--min-price` uses the holdings file's own price, a fact of the selection date.

### 3. Classify

Every row needs a level-4 `indicagent_v1` classification code (SCH) and its ITR tags. For single
names the code comes from IBKR contract details (industry, category, subcategory) mapped to a
node and reviewed by a person (`source_ref = ibkr_contract_details+review`); for funds it comes
from the fund's mandate (`source_ref = fund_mandate`). Codes and tags must already exist:
a new node or tag is a migration first (370 and 372 are the pattern).

Today the mapping from IBKR's industry fields to a node was done by hand for the 2026-09-26
batch; `classification_ibkr_sourcing.py` only reads names already onboarded. See gaps below.

### 4. Manifest

One CSV per batch under `config/universe/`, columns:

`symbol, name, code, source_ref, tags, cohort, issuer, underlying_index, description, ibkr_symbol`

- `tags` is `;`-separated. `cohort` names the selection rule the row came from and matches the
  README table.
- `issuer`, `underlying_index` and `description` fill `instrument_metadata`; leave them empty
  only when unknown.
- `ibkr_symbol` only for share classes IBKR spells with a space (`BRK.B` -> `BRK B`).
- A `spread_leg` tag needs its reciprocal pair, which a manifest row cannot express: write the
  pairs in a migration applied and committed together with the onboarding (371 and 373 are the
  pattern).

Commit the manifest before running stage 5, so the database never holds a name whose manifest is
not in git.

### 5-6. Qualify and write

```
.venv/bin/python scripts/infrastructure/universe_expansion_onboard_manifest.py \
    --manifest config/universe/<manifest>.csv            # dry run: qualify only
.venv/bin/python scripts/infrastructure/universe_expansion_onboard_manifest.py \
    --manifest config/universe/<manifest>.csv --commit
```

Phase 1 qualifies every row against IBKR outside any transaction, with a known-good probe symbol
before and after; a failed probe means the gateway dropped and the run aborts having written
nothing. Phase 2 writes the qualified set in one transaction, all or nothing: an existing
symbol, unknown code or unknown tag rolls the whole batch back. Every row lands with
`compute_eligible` and `compute_eligible_1d` false. Nothing else is seeded: the fetcher's queue
and the `ohlcv_coverage` ledger pick a new active name up from `instruments`.

Names IBKR does not resolve are listed and not written. Record them in the README (XWEB in the
ETF batch). Do not retry them under another spelling unless the spelling rule (`ibkr_symbol`)
applies.

### 7. Fetch 1d

IBKR is the 1d source for new names (owner decision 2026-10-07: Tradier is not funded; its
daily timer is disabled since plan 185-46 and plan 185-48 deletes the loader). The IBKR history
fetcher is the only IBKR history CLI:

```
.venv/bin/python -u scripts/infrastructure/backfill/ibkr_history_fetcher.py \
    --dimension backfill --timeframes 1d --symbols <comma-separated batch> --full-scan \
    --client-id <id> > <scratchpad>/fetch_<batch>.log 2>&1
```

Add `--dry-run` first to see the queue. Named `--symbols` are asked even when the ledger calls
them current. The fetcher service and timer are stopped and disabled by the owner until plan
189-10's pilot; a manual batch run is the operator's call. Every request goes through the ingress
write contract: the raw answer lands in D1 with an `ohlcv_request` row, each series gets an
`ohlcv_load` row, and a changed stored bar keeps its old values in `ohlcv_revision`. Progress
is the `ohlcv_coverage` ledger (one row per symbol and timeframe, with bounds and row count):

```sql
SELECT symbol, earliest_timestamp::date, latest_timestamp::date, row_count, last_fetch_status
FROM ohlcv_coverage WHERE timeframe = '1d' AND symbol = ANY(:batch) ORDER BY symbol;
```

Former listing venues are asked too and their answers land in D1 as venue observations (stage 8
reads them). If the run dies, rerun the same command: the contract writes only new and changed
bars. Keep the log.

The fetch writes observations, not bars. Scrubbing is part of the chain, not a person's step,
and the chain is one direction:

1. **1d fetch into D1** through the ingress write contract.
2. **Daily derivation (D2, rule d2-v2).** `services/bar_derivation.py --stage daily` turns the
   D1 observations into canonical 1d bars, taking each name's source (`tradier`,
   `ibkr_fallback` or `ibkr_named`) from `bar_source_policy`. Lineage is the
   `canonical_bar_lineage` view over D1, not a stored table.
3. **Scrub (D2a).** The same daily stage reruns the scrub rules over the symbols it touched and
   writes `bar_quality_flag`; quarantined bars leave the tradeable view.
4. **Grid (D2b).** For intraday names, `--stage grid` derives 15m/1h from tradeable 5m.

The fetcher runs steps 2 and 3 itself at exit, over every symbol whose 1d windows it asked,
and fails loudly if the derivation fails. After a failed derivation, rerun it by hand
(idempotent):

```
PYTHONPATH=. .venv/bin/python services/bar_derivation.py --stage daily --symbols <comma-separated batch> --apply
```

### 8. Verify

Five checks, all read-only. Record the results in the README entry.

1. **Held names.** The promote dry run lists every name whose gate fails:
   ```
   .venv/bin/python scripts/infrastructure/universe_expansion_promote_compute_eligible.py --dimension compute_1d
   ```
   Each held name gets the failing verdict as its reason in the README (CLBK: IBKR serves no
   daily history for its conId). A held name stays onboarded and unpromoted; it is never
   removed. D7 judges only the `compute_1d` names today, so a new name holds as "missing" until
   todo 502 lands.
2. **History heads.** Names whose first bar is after the request window's start are either real
   late listings or venue truncations:
   ```sql
   SELECT symbol, min(timestamp)::date AS first_bar
   FROM market_data_ohlcv_tradeable
   WHERE timeframe = '1d' AND symbol = ANY(:batch)
   GROUP BY symbol HAVING min(timestamp) > '2006-10-10'
   ORDER BY first_bar;
   ```
   Cross them with the fetch log's `ibkr.hist_venue_fallback_recovered` and "Query failed" lines:
   a name in both lists is a venue move. After promote, record it in `listing_venue` (D6):
   `.venv/bin/python -m services.listing_venue_writer --apply` (dry run without `--apply`;
   append-only, skips names already recorded). The nightly D7 audit's `listing_venue_coverage`
   check reports a moved 1d name with no closed former-venue span.
3. **Scrub flags.** Read what the derivation's scrub wrote; never flag by hand:
   ```sql
   SELECT rule, quarantine, count(*) FROM bar_quality_flag
   WHERE timeframe = '1d' AND symbol = ANY(:batch) GROUP BY 1, 2 ORDER BY 3 DESC;
   ```
   Record the quarantine count. A quarantined bar stays stored and is hidden from research; a
   wrong flag is fixed by a rule or APR change and a rerun, never by an edit.
4. **Gap closure.** The batch README claims the gaps it closes (sectors, rank bands, asset
   classes). Count them against the holdings file after promote and write the before and after
   numbers in the entry, so the claim is measured rather than assumed.
5. **Classification coverage.** Every active name has one open classification row:
   ```sql
   SELECT count(*) FROM instruments i
   WHERE i.is_active AND NOT EXISTS (
       SELECT 1 FROM instrument_classification c WHERE c.symbol = i.symbol AND c.valid_to IS NULL);
   ```
   Must be 0.

### 9. Promote

```
.venv/bin/python scripts/infrastructure/universe_expansion_promote_compute_eligible.py --dimension compute_1d --commit
```

Promotes every active name whose required 1d `bar_integrity` verdicts are passed and fresh;
holds the rest with the failing check named. Promotion is the moment the name enters research,
so it happens after stage 8, never before.

### 10. Record

Update `config/universe/README.md`: the cohort table (rows, source, rule), deviations from a clean
draw, names IBKR rejected, names held at promotion and why, and the verify results. Commit it
with any pair migration. Update `.planning/STATE.md`'s universe line with the new counts.

## Failure modes and their guards

| Failure | Guard | Where |
|---|---|---|
| Gateway logs out mid-run, every remaining name looks rejected | Probe symbol before and after qualification; abort before writing | Stage 5 |
| One bad row half-writes a batch | One all-or-nothing transaction | Stage 6 |
| A transaction held across hours of IBKR calls | Qualify outside the transaction | Stage 5 |
| Name with no data passes the fetch "clean" | Verdict gate (session_coverage) | Stage 9 |
| Selection biased by data availability | Rule 1; no screens on history | Stages 2, 8 |
| Venue-truncated history read as a late listing | Head check plus fetch log; 185 D3 | Stage 8 |
| Corrupt prints reach research | D2a scrub in the daily derivation; quarantine hides the bar | Stages 7-8 |
| Dead name deactivated, history erased from panels | Rule 6 (no automated guard; 185 D8 descoped) | After onboarding |
| Two draws overlap | Exclude every draw of the batch | Stage 2 |
| Two manual IBKR backfills share a client ID | Check running processes; pick a free ID | Stage 7 |
| Onboarding run crosses UTC midnight | Refused loudly by migration 368's same-day guard; rerun | Stage 6 |

## Gaps, in the order they matter

1. **No delisting guard** (185 D8 descoped 2026-09-26; D-03). A delisted name is never
   soft-deleted or deactivated: not through the API (`DELETE /instruments/{symbol}` sets
   `is_active = false`), not by hand. Its bars stop and it stays in every panel; rule 6 is the
   only protection.
2. **Classification mapping has no tool** (todo 444). Stage 3's IBKR-industry-to-node mapping was manual.
   A reproducible mapper (IBKR fields -> candidate node, review CSV out, manifest columns in)
   would make stage 3 a command.
3. **Second writer.** `universe_expansion_stratified_sourcing.py` still carries a `--commit`
   path that onboards outside the manifest flow and holds one transaction across IBKR calls
   (todo 431). Do not use it.
4. **`spread_leg` pairs need a migration** (todo 444). A manifest column naming the pair partner would
   remove the hand-written migration.
5. **No orchestrator** (todo 444). Stages 5-10 are separate commands. Once the next batch has run cleanly
   through this SOP, one resumable command (`universe_onboard.py --manifest ...`) that runs
   stages 5-9 in order, stops at every hold, and writes the verify report is the automation
   step. Build it from the scripts above; do not reimplement them.
6. **Point-in-time membership.** Holdings snapshots are downloaded when a draw needs one, and
   kept in `config/universe/` with their date. Scheduled snapshots (185 D8) were descoped
   2026-09-26.
