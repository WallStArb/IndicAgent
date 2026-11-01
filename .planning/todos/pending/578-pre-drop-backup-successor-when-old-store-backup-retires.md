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
