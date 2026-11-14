# Service auditor design (archived)

Date: 2026-04-03. Condensed to a stub 2026-11-14.
Outcome: built; `services/service_auditor.py` is live and holds the service registry (`_DAG_ORDER`).

Idea kept: Recovery is graduated (observe, restart, escalate) and driven by health signals, not by systemd retry limits alone; a service registry has one home so scrape and audit lists cannot drift.

Full text: git history, `docs/plans/archive/2026-04-03-service-auditor-design.md` as of `a88ab9985`.
