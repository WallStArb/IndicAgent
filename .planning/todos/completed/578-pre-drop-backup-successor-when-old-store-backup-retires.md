---
status: pending
priority: P2
filed: 2026-11-01
source: coordinator cleanup pass, 2026-11-01 (gotchas.md backup-before-drop pattern)
gate: 2026-11-12, when todo 574 deletes scripts/ops/bars/ops_old_store_backup.py with the Tradier backups
---

# Successor for the generic pre-drop backup procedure when ops_old_store_backup retires

`ops_old_store_backup.py` is the repo's one generic "backup before an irreversible drop" tool
(COPY to per-year gzip CSV under `data/backups/`, one REPEATABLE READ transaction, `--verify`
reconciles manifest, live recount and file rows). `docs/reference/gotchas.md` names it as the
pattern and migration 502 already records the plan: it is deleted with the Tradier backup
retention on 2026-11-12 (todo 574), because its only named use was the 191 old-store and Tradier
backups.

The gap: irreversible drops are a standing operation in this repo (todo 571 needs "back up
first" and is scheduled after the rebuild; problem-name deletion, todo 512, is another). After
2026-11-12 there is no tool and no documented pattern for it, and plain `pg_dump` of a
compressed hypertable is not the pattern.

Options to decide between (Musk order): question whether a generic tool is needed at all versus
writing the procedure into the drop migration itself each time (the 191-17 precedent: the drop
migration and phase summaries are the record); if a tool, extract the COPY/verify core from
574's deletion commit before it dies and re-home it (e.g. `scripts/ops/db/ops_table_backup.py`,
vendor-agnostic), migrating the `infra.old_store_backup.disk_margin` key rather than retiring
it.

Done when: on or after 2026-11-12, `docs/reference/gotchas.md`'s backup-before-drop paragraph
names a live procedure, and 571's "back up first" step has a tool or a written migration-time
pattern to execute it with.

## Decided and landed (research lane, session b0, 2026-11-01)

Decision: migrate the tool (the coordinator's lean, confirmed on the evidence). The three named
future consumers need three different backup shapes — 571's concept tables are plain tables
(its own written procedure, `pg_dump -Fc`, is right for them); 512's archive-then-delete needs
per-name row slices out of hypertables; 574's retirement needs the file-only verify. The old
tool's core is generic over a TableSpec already, so the successor is an extraction, not a
rewrite: `scripts/ops/db/ops_table_backup.py` — tables named on the CLI
(`--table NAME[:DATE_COLUMN[:KIND]]`, repeatable), optional `--where` for row-slice archives,
`--retention-until` recorded in the manifest, same REPEATABLE READ + manifest + verify
machinery, APR `infra.table_backup.disk_margin` (migration 553, applied live; the old key
retires with todo 574 on 2026-11-12). Per the 191-17 precedent, gotchas now says a small
table's drop migration plus summaries can remain the record — the tool exists for the
hypertable-class drops where pg_dump is not the pattern.

ops_old_store_backup.py itself is untouched and still dies on 2026-11-12 with todo 574; the
gotchas backup paragraph now names the live successor, so 578's done-when is met ahead of the
date. Tests: tests/unit/scripts/test_ops_table_backup.py (14, the ported pure-function suite
plus the CLI contract).
