# Summary cards

Author: Claude Opus 5.5, 2026-09-27
Informed by: docs/plans/2026-09-26-unified-research-to-production-design.md 10.2, 14.2; .planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-CONTEXT.md D-04..D-06

A summary card is a checked-in record of what an old verdict or dead process tried and found.
The term is defined once in `docs/foundation/glossary.md` (entry `summary card`); this README
defines the file format and the lint contract, not the concept.

Cards exist because of design section 14.2: raw market data is permanent, derived data is cache,
and conclusions are records. Before phase 186 drops any old-chain table, what was learned from it
must live in a card here. Phase 187 loads every card in this directory as a `kind =
'legacy_verdict'` attempt in the new `research_run` table (design 10.2 item 3).

Two rules govern the numbers on a card:

- Numbers are copied, never recomputed. Every result comes from a stored database row, a committed
  report, or `.planning/gate_look_log.jsonl`. No card may re-run a backtest or re-score a stored
  verdict (D-05).
- Cards are append-only records. A correction adds a dated note in the prose; the front matter
  numbers are fixed at write time and are not revised in place.

Every card carries `reproducible: false`: flagged not reproducible from stored rows, never
re-scored. The lint rejects any other value, including the string forms YAML 1.1 would coerce.

## Card files

One file per card, named `<card_id>.md`, in this directory. The file has YAML front matter between
`---` lines, then `# <title>`, then these prose sections, in order:

- What was tried
- What was found
- Known defects
- Why closed
- Where the numbers came from

The last section must contain the exact read-only SQL used for any `db:` source, together with the
date the query was run. Untracked paths such as `logs/...` are not valid sources; if a number
lives only in a log, copy the number into `results` and name the log path in prose only.

`tests/unit/test_summary_cards.py` lints every card and enforces drop-table coverage (D-06):
every table in the test's `DROP_TABLES` set must be cited by at least one card's `tables` list
before any phase 186 drop migration runs.

## Front matter schema

| Key | Type | Rules |
|---|---|---|
| `card_id` | str | `^(legacy\|cache)-[a-z0-9]+(-[a-z0-9]+)*$`, equals the filename stem, unique |
| `kind` | str | `legacy_verdict` or `dead_cache` |
| `title` | str | Human title |
| `idea` | str | One sentence |
| `verdict` | str | One of `DEAD`, `FAIL`, `INCONCLUSIVE`, `KILLED_ON_PAPER`, `REJECTED_AS_AXIS`, `NO_CONCLUSION`; dead_cache cards use `NO_CONCLUSION` |
| `verdict_date` | date | ISO date the verdict was reached |
| `recipe` | mapping | `spec` (repo path or null), `script` (repo path or null), `recipe_commit` (40 lowercase hex; the last commit touching `script` or `spec`, from `git log -1 --format=%H -- <path>`) |
| `results` | list of mappings | Each `{name: str, value: number or str, source: ref}`; may be empty only for `dead_cache` |
| `known_defects` | list of str | Empty list allowed |
| `spans_looked_at` | list of mappings | Each `{start: date, end: date, role}` with role in `in_sample`, `forward_span`, `full_history` |
| `forward_span_looks` | int | Count of gate looks at or after `oos_start` (2025-12-24) that this card's process made; >= 0 |
| `tables` | list of str | Snake_case table names this card records what was learned from; the D-06 coverage key |
| `status_now` | str | `closed` or `reopened` |
| `reopened_as` | str or null | Ledger section 2 pointer |
| `reproducible` | boolean | Must be exactly `false` (boolean; `no`, `true`, or any string form fails) |
| `sources` | list of refs | See grammar below |
| `related_cards` | list of str | Other card ids; may be empty |

The verdict enum covers the ledger section 4 verdict wordings so the 18 ledger verdict cards
(written by plan 186-02) need no schema change.

## Source references

A source reference (`sources` entries and `results[].source`) is one of:

- A git-tracked repo path, optionally suffixed `#anchor` (for example
  `docs/research/measurement-alpha-emission.md#verdict`)
- `db:<table>` - a stored database row; the SQL lives in the prose with its run date
- `gate_look_log:<gate_id>` or `gate_look_log:<run_ts>` for gate looks whose log line has no
  `gate_id` key; resolved against `.planning/gate_look_log.jsonl` by the lint

## Adding or correcting a card

Run `pytest tests/unit/test_summary_cards.py -q` before committing. The lint checks front matter
validity, source-reference resolution, git existence of `recipe_commit` and every repo-path source
(these git checks skip with a stated reason on a shallow clone, such as CI's checkout), and full
`DROP_TABLES` coverage. Later drop plans must add any new drop target to `DROP_TABLES` before
dropping it, and write its card first.

## Deleted recipe code

`scripts/analysis/` was deleted in phase 186 plan 16. The last commit containing it is
`920f8e2b36b305f8c46069d8a91d326e6b1244db`; read any cited path with
`git show 920f8e2b36b305f8c46069d8a91d326e6b1244db:<path>`. A card's own `recipe_commit` is
authoritative for that card.
