# Stage 2 split rows plan, todo 646 (archived)

Date: 2026-11-19. Archived 2026-11-22.
Outcome: executed. 3,026 Massive reference rows with a tape witness were recorded for the stage 2 names plus 140 reverse splits under numerator cap 1000, canonical 1d was re-derived for the affected names, and the member history audit is clean. Status, corrections and evidence paths are in `.planning/todos/pending/646-record-splits-for-the-stage-2-names-before-the-pin.md`; the strict sweep gate scope (materiality, owner 2026-11-20) is in todo 629 and CLAUDE.md.

Decisions kept:
- Record dead names' splits through the path the active names used: the Massive splits reference as the event source, the name's own unadjusted 1d tape as the confirming witness, `ops_massive_split_audit.py` to propose, `ops_split_calendar_audit.py --apply-massive` to write `massive_reference` rows. The only change is scope: attribute by `ticker_event` span, never by ticker label.
- A row needs an attributed event, a recognised ratio and the tape step at the vendor's date. Tape-unconfirmed events are never written and tape steps with no event get no row; both stay on the unresolved list. A Massive bar cannot witness itself; the second witness is Yahoo.
- Measured scale before the run: about 2,580 confirmable events on about 1,755 names; 5,284 step-days that snap to a recognised ratio with no event are mostly real moves, bad bars and reused-ticker joins.

Full text: git history, `docs/plans/2026-11-19-stage2-split-rows-plan.md` as of `0814ce71e`.
