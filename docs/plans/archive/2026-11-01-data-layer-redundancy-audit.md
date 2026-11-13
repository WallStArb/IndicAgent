# Data layer redundancy audit (archived)

Date: 2026-11-01. Archived 2026-11-13.
Outcome: consumed. All four of its proposed todos executed: the dormant streaming bars block was
retired (todo 579), the one-shot-done sweep confirmed and deleted its two completed passes (todo
580), and the post-534 doors audit closed as superseded by the Massive transition (todo 581). The
IBKR-side doors it said to keep die with step 7 Part F; one-name tables and the migration sweep
landed separately (todos 570/575/576/577, migrations to 589 and beyond).

Idea kept: audit dormant doors before deleting them; a disposition map (keep, retire, already dead)
turns a cleanup sweep into a counted checklist instead of ad-hoc removals.

Full text: git history, `f5a4db54a`.
