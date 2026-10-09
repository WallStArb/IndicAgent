---
phase: 185-daily-data-foundation
plan: 48
subsystem: data-integrity
tags: [tradier-retirement, deletion, apr-retirement, migration-457, d7, grafana, d-28, docs, todos, gap_closure]
requires: [185-46, 185-47, 185-43, 185-51]
provides:
  - "no code path can call Tradier: loader, units (repo and installed), provider module and Settings fields deleted"
  - "SOURCE_TRADIER and ROUTE_TRADIER in src/intelligence/bars/sources.py; d2-v2, D7 and the listing venue writer read the Tradier history through them"
  - "D-28 condition 3 excludes late names by stored canonical tradier 1d bars (judged 51, unresolved FUBO, LION, RCAT)"
  - "D7 without tradier_refused; refusal gauge for ibkr and derived only; Grafana rule tradier_refused_uid deleted (deleteRules)"
  - "migration 457: six infra.tradier.* APR keys retired, live 2026-10-09 01:15:43 UTC"
  - "design doc Amendment 2026-10-07 (shape F, volume basis, residual risks, Stage V deferred)"
  - "todos 517 (P1), 518 (P2), 519 (P2); 492 updated; 493 closed"
affects: [189-10 Task 2, 189-10 Task 3, 186-26, todo 501, research lane]
tech-stack:
  added: []
  patterns:
    - "Grafana keeps a file-provisioned alert rule after its entry is deleted; removal needs a deleteRules entry and a provisioning reload"
key-files:
  created:
    - production/migrations/457_retire_tradier_apr.sql
    - tests/unit/test_retire_tradier_apr_migration_contract.py
    - .planning/todos/pending/517-tradier-history-before-d-after-a-split.md
    - .planning/todos/pending/518-1d-volume-basis-change-at-d-for-research.md
    - .planning/todos/pending/519-1d-names-frozen-at-their-last-tradier-bar.md
  modified:
    - src/intelligence/bars/sources.py
    - src/intelligence/bars/daily_rule.py
    - src/intelligence/bars/corporate_actions.py
    - services/bar_derivation.py
    - services/bar_reconciliation_audit.py
    - services/listing_venue_writer.py
    - services/service_auditor.py
    - src/config/settings.py
    - scripts/ops/bars/ops_data_bar_check.py
    - scripts/infrastructure/backfill/ibkr_history_fetcher.py
    - production/grafana/provisioning/alerting/alert-rules.yml
    - production/systemd/indicagent-bar-reconciliation-audit.timer
    - docs/operations/operations-database.md
    - docs/foundation/canonical-truth-registry.md
    - docs/foundation/glossary.md
    - docs/foundation/instrument-onboarding-sop.md
    - docs/reference/services/overview.md
    - docs/reference/gotchas.md
    - services/README.md
    - docs/plans/2026-10-06-data-layer-integrity-design.md
    - .planning/todos/PRIORITIES.md
    - .planning/todos/pending/492-tradier-vs-ibkr-vendor-reconciliation-and-production-token.md
  deleted:
    - scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py
    - src/providers/tradier.py
    - production/systemd/indicagent-tradier-daily.service
    - production/systemd/indicagent-tradier-daily.timer
    - tests/unit/test_tradier_provider.py
    - tests/unit/scripts/test_tradier_daily_plan.py
    - tests/unit/scripts/test_tradier_daily_run.py
decisions:
  - "D-28 condition 3's exclusion is any canonical tradier 1d bar in the tradeable view; the judged set and its verdict equal the pre-swap result, the excluded count grows because the swap made every switched name late"
  - "vendor_agreement kept: the operations dashboard plots its two gauges; its Tradier side is frozen, so it reports a constant"
  - "LOAD_SOURCES drops tradier: no Tradier load can happen, so its refusal gauge point would be a dead series"
  - "threshold.bar_integrity.tradier_admission_* kept: ops_source_policy.py and swap_1d_primary_measure.py read them over the stored history"
  - "Grafana rule removed by a deleteRules entry kept in alert-rules.yml (the documented file-provisioning mechanism)"
requirements: [D-01, D-06, D-26]
metrics:
  started: 2026-10-09T00:55Z
  completed: 2026-10-09T01:40Z
  duration: about 45 minutes (two 13-minute D7 runs included)
  tasks: 3
  files: 42
---

# Phase 185 Plan 48: retire the Tradier loader, units, provider and APR keys Summary

Nothing in the repository can call Tradier and nothing needs to. The Tradier history (canonical
before D = 2026-10-07) is still read by d2-v2, D7 and the lineage view through
`src/intelligence/bars/sources.py`, and every stored Tradier row is untouched.

## Commits

| Step | Commit | What |
|---|---|---|
| Task 1 RED | bf23cefef | condition 3 tests: stored-history predicate, no loader import |
| Task 1 | 543b02205 | loader (563 lines), its two tests and the repo units deleted; TRADIER_OWNED_SQL and the probe column deleted; condition 3 predicate; sources.py identifiers; auditor, registry and boundary entries |
| Task 1 | 4998ae701 | provider (102 lines) and its test deleted; Settings fields removed; D7 and listing venue writer import SOURCE_TRADIER from sources.py |
| Task 2 RED | 03504f35f | D7 and migration 457 contract tests |
| Task 2 | 3c15052d8 | D7 tradier_refused removed; Grafana rule deleted and reloaded |
| Task 2 | 2e335458e | migration 457, applied live; `_PENDING_RETIREMENT` empty again |
| vulture | fb22dd050 | `SplitInference.evidence_days` dropped (its one reader was the loader); d2-v2 docstring |
| Task 3 | 8a15b979f | living docs, design amendment, todos 517 to 519, 492 updated, 493 closed |

All pushed to origin/main. Diff over the plan: 42 files, 522 insertions, 1,546 deletions; 7 files
deleted (1,277 lines).

## Preconditions and live state

- `indicagent-tradier-daily.timer` and `.service`: disabled and inactive; no loader, fetcher,
  `backfill_feature_factory` or `intraday_chain` process ran at any point.
- Installed copies removed with sudo (`/etc/systemd/system/indicagent-tradier-daily.{service,timer}`),
  then `daemon-reload` and `reset-failed`; `systemctl list-unit-files | grep -c tradier` prints 0.
- Tradier rows before and after (equal): ohlcv_observation route TRADIER 7,161,155;
  ohlcv_request source tradier 6,513; ohlcv_load source tradier 5,582; market_data_ohlcv 1d source
  tradier 6,689,979; bar_source_policy rows naming tradier 3.
- No IBKR request, no Tradier call, no fetcher start. `.env` not edited: `TRADIER_API_TOKEN` is now
  dead (Settings ignores extra variables, so it is inert); the owner may remove it.

## Consumer grep (start of Task 1)

The plan's grep over `*.py *.sh *.service *.timer *.yml *.example` (excluding .venv, .planning,
docs, logs, evidence, migrations) returned 921 lines in 68 files. Almost all read the Tradier
history by the literal `tradier` / `TRADIER` (daily_rule, vendor_basis, source_admission,
ops_source_policy, integrity_checks, research scripts, fixtures) and stay. The live consumers of
the loader, provider, settings and ownership predicate were:

| Consumer | Action |
|---|---|
| `services/listing_venue_writer.py`, `services/bar_reconciliation_audit.py`: `from src.providers.tradier import SOURCE` | import from `sources.py` |
| `scripts/ops/bars/ops_data_bar_check.py`: imports `TRADIER_OWNED_SQL` from the loader | stored-bars predicate (below) |
| `services/bar_derivation.py`: `TRADIER_OWNED_SQL`, the probe's `tradier_owned` column | deleted (no reader: the fetcher stopped reading it, test pins that; the daily stage never read it) |
| `services/service_auditor.py`: `_DAG_ORDER` and the inactive-is-correct set | entries removed |
| `src/config/settings.py`: `tradier_api_token`, `tradier_base_url` | removed |
| `scripts/infrastructure/backfill/ibkr_history_fetcher.py`: docstring naming the loader | sentence removed (comment only) |
| tests: provider, two loader tests, single-writer registry (`corporate_action` `tradier_refetch` writer), ohlcv_load boundary (loader segment and two ownership tests), market_data writer boundary (one test), derivation daily (fake column, one test) | deleted or updated |
| `.env.example` | does not exist; nothing to remove |
| `tools/vulture_whitelist.py` | no Tradier entry |

## D-28 condition 3

Before any edit the gate already printed `Tradier-owned excluded 0` with 1,441 judged and 1,144
unresolved: since 185-47 the open default names IBKR, so the policy predicate excluded nobody
(the silent widening T-185-48-03 names). The late set itself is inflated by the swap: `_late_names`
takes the first `ibkr_named` bar as the SMART head, and 1,361 switched names now start `ibkr_named`
at D.

After (predicate: any canonical tradier 1d bar in the tradeable view):
`IBKR-sourced late names 51; unresolved 3 (FUBO, LION, RCAT); Tradier-history excluded 1390`.
The judged residue equals 185-35's pre-swap line (52 judged, unresolved FUBO, LION, RCAT); CHTR,
UNG, DAL, ODFL, ARES and ECH (excluded before the swap) are excluded now. The literal "same 23
names" of the plan could not be reproduced because the late set changed with the swap; the verdict
and the judged residue are the invariant that held. The evidence line's excluded-unresolved list is
now long (the inflated late set); the late-set definition is noted under open items.

## D7 and alerts

- `check_tradier_refused`, `_TRADIER_LATEST_LOAD_SQL`, `_tradier_refused` and the checks entry
  removed; `LOAD_SOURCES` is `("ibkr", "derived")`.
- `vendor_agreement` kept: `production/grafana/dashboards/operations.json` plots
  `bar_reconciliation_vendor_close_differ_share` and `bar_reconciliation_vendor_volume_ratio_median`.
  Its Tradier side ends at 2026-10-06, so it is constant; the D7 docstring and operations-database
  say so.
- `tradier_refused_uid` removed from the groups and named under `deleteRules`. The first reload left
  the rule in Grafana (17 rules); with `deleteRules` the API lists 16, `revision_refused_uid` and
  `bar_freshness_1d_uid` among them. The D7 timer's repo comment naming tradier_refused was updated;
  the installed copy differs only by that comment.

D7 by hand (PYTHONPATH as the unit sets it), before (01:08 to 01:21 UTC) and after (01:22 to 01:34 UTC):

| Check | Before fail | After fail |
|---|---|---|
| session_coverage | 263 | 263 |
| policy_conformance, lineage_missing, digest_fresh, report_age | 0 | 0 |
| canonical_recompute | 1 (CTVA) | 1 |
| unexplained_seam | 6 | 6 |
| vendor_basis_run | 13 | 13 |
| freshness_1d | 4 (CTVA 6, QRVO 4, PSKY 3, WBD 3) | 4 |
| slot_coverage / grid_parity / coverage_cache (intraday) | 240 / 131 / 11 | 240 / 131 / 11 |
| findings table | equal on every row | equal; `tradier_refused` (0 of 1,455) gone by design |

A first "before" attempt hit my 590 s shell timeout during the intraday report and was killed; it
had written its 1d verdict rows (01:04 UTC). The full runs above replaced it.

## APR retirement (migration 457)

Keys: `infra.tradier.concurrency` (4), `first_date_tolerance_days` (7), `history_start`
(2000-01-01), `min_session_ratio` (0.95), `nightly_enabled` (true), `request_timeout_s` (30).
`max_changed_bar_ratio` was already retired by 459. Reader grep
`grep -rn "infra.tradier" services src scripts`: empty after the deletion. The 185-44 readers guard
flagged exactly these six once the loader was gone; they sat in `_PENDING_RETIREMENT`
(`retire: 185-48`) for one commit and left with the migration. No other key was orphaned (the guard
flagged none); the `threshold.bar_integrity.tradier_admission_*` keys stay (two readers).
Rows exported first to `data/backups/185-48/config_{schema,state,history}_retired_keys.csv`
(6, 6, 11). ROLLBACK dry run: DELETE 11, 6, 6. Live apply 2026-10-09 01:15:43 UTC under
`lock_timeout 10s`; rerun dry: DELETE 0 three times; 0 rows in all three tables. Migration 441's
`tradier` stage in the `bar_derivation_batch` CHECK and the `ohlcv_load`/`ohlcv_request` source
CHECKs stay (history rows).

## Docs and todos

- CLAUDE.md proof: `grep -ci tradier CLAUDE.md src/intelligence/CLAUDE.md` prints 0 and 0; not edited.
- Replaced in place: operations-database (corporate_action writers, daily chain intro with the policy
  per date and the two fetcher lanes, D7 list without tradier_refused and with held_names, vendor
  agreement note, alert list), canonical truth registry (D1 writers, policy row, canonical 1d
  sources, corporate actions, provider matrix intro and the Tradier 1d row, IBKR 1d source label),
  glossary (canonical bar rewritten; new term `daily source`, defining a frozen name; "Tradier-owned"
  as Avoid, not Banned, because existing code comments use it and a ban would break the baseline),
  onboarding SOP (venue truncation note, stage 7 source, D2 source labels), services overview
  (Tradier row deleted), plus gotchas' timer line and services/README (outside the file list, they
  named the deleted units).
- Design doc: "Amendment 2026-10-07" at the end (owner decision, shape F, counts A 1,526 B 0 C 3,
  volume basis p10 0.409 p50 0.528 p90 0.807, residual risks with todos, Stage V deferred) and the
  facts this work verified added to "Verification status of claims".
- Todos (next free numbers after pending, completed, deferred): 517 P1 (Tradier history before D
  after a split; neither 516, which is spin-offs, nor 509, the v2.x remainder, covers it), 518 P2
  (volume basis at D, gate with 501), 519 P2 (PSKY, WBD, QRVO fail IBKR contract qualification,
  MOD's fallback is refused by the basis window; Tradier itself stopped early for the first three).
  PRIORITIES rows added through a scratch copy; `git diff` showed only these rows plus the 492 and
  493 rows; link integrity passes.
- Pending todos grepped for tradier and 1d primary: 492 updated (token item void, volume basis moved
  to 518, still open for closes before D); 493 closed (Tradier intraday capture, void); 433, 456,
  502, 512, 513 mention Tradier as history or context and need no change.

## Verification

- Task 1 verify passes except its grep clause over `production`: migrations 440 and 441 name the
  loader in their headers and are immutable history. Over services, src, scripts, tests, tools and
  `production` minus `production/migrations` the grep is empty.
- Task 2 verify: the five test files pass, `config_schema` has 0 `infra.tradier.%` keys, the YAML
  check passes.
- Task 3 verify: link integrity passes, the amendment heading exists, the CLAUDE.md count is 0, the
  three living docs name no loader.
- Full `pytest tests/unit/ -q`: exit 0, 0 failures, the same 5 pre-existing skips, run at 8a15b979f
  (the final code; this SUMMARY commit adds no code).
- vulture against the pre-plan tree (`git archive bf23cefef^`): 102 findings before, 102 after.
- ruff and black clean on touched files; pre-commit 9/9 on every commit.
- repro_frozen not run: nothing under `src/intelligence/research/` or `statistics/` changed.

## Deviations from plan

1. [Live state] Condition 3 was already widened before this plan (the swap closed the Tradier
   default). The predicate change restores the verdict and the judged residue of 185-35, not the
   literal 23-name list; the excluded count is 1,390 because the late set grew with the swap.
2. [Plan defect] Task 1's verify grep includes `production`, where migrations 440 and 441 name the
   loader; immutable, so the clause cannot pass literally.
3. [Rule 3] Grafana file provisioning does not drop a deleted rule; a `deleteRules` entry was added.
4. [Rule 3] `SplitInference.evidence_days` deleted to keep vulture at no new finding (a bars module,
   not research or statistics).
5. [Scope] `LOAD_SOURCES` drops tradier, the D7 timer comment, gotchas and services/README edited,
   the ibkr_history_fetcher docstring sentence removed (comment only, no fetcher process).
6. [Scope] Todo 493 closed and 492 updated (the plan asked to close or update todos this work
   resolves).
7. [Not done, by rule] STATE.md, ROADMAP.md and REQUIREMENTS.md not written (executor brief); the
   orchestrator records the plan and D-01, D-06, D-26.

## Open for phase 185 verification

- `ops_head_rerun._late_names` measures the SMART head as the first `ibkr_named` 1d bar, so since
  the swap every switched name looks late (1,361 at D). Condition 3's verdict is right, but its
  evidence line and any other `_late_names` reader see the inflated set. Not filed; a candidate
  for the 185 re-verification or todo 512's rule.
- Todos 517 (gate before the fetcher timer launch), 518 (with 501), 519 (owner per name).
- The four frozen names and CTVA fail `freshness_1d` until decided; MOD joins once two sessions pass.
- `.env` still holds `TRADIER_API_TOKEN` (inert); the owner may remove it.

## Known stubs

None.

## Threat flags

None beyond the register. T-185-48-01: per-item grep, the 185-44 guards, full suite, vulture.
T-185-48-02: Tradier row counts equal before and after; migration 457 names no market data table
(contract test). T-185-48-03: condition 3 evidence before and after recorded above.
T-185-48-04: the grep gates of Task 3 pass. T-185-48-05: Settings fields removed; `.env.example`
does not exist; the real `.env` is the owner's.

## Self-Check: PASSED

- GONE: the loader, provider, both repo units, the three Tradier tests, both installed units.
- FOUND: migration 457, its contract test, todos 517, 518, 519, 493 in completed/,
  data/backups/185-48/ (three CSVs).
- FOUND commits: bf23cefef, 543b02205, 4998ae701, 03504f35f, 3c15052d8, 2e335458e, fb22dd050,
  8a15b979f on origin/main.
- LIVE: 0 `infra.tradier.%` rows in config_schema, config_state, config_history; Grafana lists 16
  rules without tradier_refused_uid.
