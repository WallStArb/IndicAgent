# Documentation Maintenance Checklist

Keep docs up-to-date with regular maintenance.

---

## After Every Release

- [ ] Update STATUS.md version number
- [ ] Update STATUS.md intelligence tiers table (plugin counts)
- [ ] Update STATUS.md system health table (service versions)
- [ ] Add entry to STATUS.md "Recent Changes"
- [ ] Update CLAUDE.md version (sync with STATUS.md)
- [ ] Update CLAUDE.md plugin count

---

## When Adding Plugins

- [ ] Add plugin to reference/plugins/iX-*.md
- [ ] Update STATUS.md plugin count in intelligence tiers table
- [ ] Update CLAUDE.md plugin count in "Plugin System" section
- [ ] Optional: Add example to guides/adding-plugins.md

---

## When Completing Major Phases

- [ ] Update MASTER_ROADMAP.md phase status
- [ ] Move completed phase to "Completed" section
- [ ] Update STATUS.md "Next Steps" if priorities changed
- [ ] Consider updating architecture docs in concepts/

---

## Quarterly (Every 3 Months)

- [ ] Run STATUS.md audit: plugin counts vs actual codebase
- [ ] Verify service versions in system health table
- [ ] Check for broken internal links
- [ ] Update outdated examples/screenshots
- [ ] Archive obsolete content to _archive/
- [ ] Run /claude-md-improver skill

---

## When Making Doc Changes

- [ ] Update "Last Updated" date in modified files
- [ ] Check cross-references still work
- [ ] Verify markdown renders correctly
- [ ] Commit with "docs:" prefix

---

**Last Review:** 2026-02-17
