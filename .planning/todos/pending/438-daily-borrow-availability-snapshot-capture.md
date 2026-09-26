

## Phase 185 revision 2 (2026-09-26)

Absorbed into phase 185's D8 capture job (spec revision 2): delisting check, holdings snapshots and borrow snapshots run as one daily job with one writer. Still start it first; every unrecorded day is lost.

## Standalone again (2026-09-26)

The owner descoped phase 185's D8 (forward survivorship capture), so this is no longer part of a
shared capture job. It is still worth doing on its own: borrow availability is live-only at IBKR,
and the short side of any book needs it (unified design 9.3). One small daily job with a
completion metric, so a missed day is heard.
