---
status: pending
priority: P2
filed: 2026-11-01
source: data-layer redundancy audit (docs/plans/2026-11-01-data-layer-redundancy-audit.md), owner ask 2026-11-01
---

# Dormant streaming bars block: retire or keep, one decision not four

The streaming-era persistence and audit units are disabled and the live feed is down: `services/
bar_auditor.py` (canonical completeness + gap requests), `services/bar_replay_provider.py`
(tradeable-view replay into live topics), `services/bar_writer.py` (BarWriter batch), `services/
bar_aggregator.py` (live 5m->15m/1h). The nightly batch path (capture -> selection -> derive ->
audit) covers the canonical plane without them; bar_auditor's gap detection is superseded in
practice by bar_reconciliation_audit.

This is an owner call, not a hygiene call: Alpaca was chosen (2026-10-09) as the streaming
candidate and execution venue, and the endgame is live trading, so the streaming path is the
eventual live path, not dead v2.x weight. The choice is retire-with-the-archive versus
keep-for-the-live-feed-return (with a documented reactivation test). Decide as one block; the
four files, their units, `_DAG_ORDER` rows and topic consumers go together.

Done when: the owner decides; if retire, one deletion commit plus gotchas/service-auditor
repairs; if keep, a one-line reactivation note in `docs/operations/operations-infrastructure.md`.

## Closed: KEEP (owner decision 2026-11-01)

The owner's answer: the real-time feed returns, so the streaming block is the eventual
real-time path and stays. Reactivation note written into
`docs/operations/operations-infrastructure.md` (Architecture section, KEEP decision + wave
order on feed return). No files change; future audits close on that note, not on this todo.
