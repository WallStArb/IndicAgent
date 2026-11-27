# Harness improvement SOP

**Version:** 1.0
**Status:** current (owner ruling 2026-11-27: a core SOP)
**Last Updated:** 2026-11-27

## Why this doc exists

The harness is everything that steers the agent sessions: CLAUDE.md, `.planning/PLANNING-SYSTEM.md`, the lead loop, the gates, the tests that enforce process, the tools under `tools/`, skills and memory. The harness exists to serve the goal (fast, honest hypothesis tests); it is not sacred (owner 2026-11-27: "we are goal oriented not process slaves"). It should get better on evidence, the same way the research machine does, and that includes improving how it improves.

The worked example that set the pattern (2026-11-27): sessions sat idle twice until the owner poked the lead, so the push-only assignment model became pull-based claiming (`1850fb596`); its first review found four defects in prose-only rules, which became parser checks in `tools/todo_claims.py`.

## The loop

1. **Instrument.** The harness logs its own signals, append-only, outside any research table:
   - session idle time (periodic `ListAgents` snapshots: busy, idle at a shell, gone);
   - owner interventions (a message from the owner that does a lead's job: a poke, a reassignment, a missed rule restated);
   - review findings per landing, by class (correctness, rule breach, stale doc, test gap);
   - CI reds, reverts, and a todo's filed-to-closed time;
   - outcome: landings that shorten the critical path in `PRIORITIES.md`.
2. **Retro.** The lead runs a retro on a fixed cadence (daily, and after any owner intervention). Input is the signals, not memory of the day. A failure shape that occurred twice is a candidate; once is noted only.
3. **Mechanize first.** A candidate fix is, in order of preference: delete the rule or step that caused it; a check (test, lint, tool exit code) that fails loudly; a change to a tool's default. A prose rule in CLAUDE.md or PLANNING-SYSTEM.md is the last resort, used only when no check can express it.
4. **Predict.** Each harness change records, in its todo or commit body: the failure it targets, the signal it should move, the expected direction, and a check date. No prediction, no change.
5. **Judge.** At the check date the lead reads the signal. Moved as predicted: keep. Not moved: revert or replace the change, and record why. A change is not kept on argument alone.
6. **Prune.** Every rule carries its origin (owner ruling or retro, with date). A rule that has not fired or been cited for 60 days is a deletion candidate at the next retro. CLAUDE.md has a size budget (its size on 2026-11-27); a new rule pays for its space by deleting or condensing an older one, or by moving detail to a linked doc.
7. **Recurse.** Monthly, the retro judges itself: the share of its changes that were kept at their check date, and the trend of owner interventions and idle time. A poor hit rate changes the retro method (its signals, cadence or candidate rule), not just the rules it produced.

## Guards

- The owner keeps the veto on CLAUDE.md and on anything irreversible or outward-facing; a harness change of that kind goes to the owner once, with the prediction.
- No session changes its own permission settings, hooks or sandbox, or asks a peer to.
- Harness changes pass the same gates as code: Done-Coding SOP, independent review, reversible.
- Pair every activity signal with an outcome signal. Idle time alone invites busywork; it is read together with critical-path landings.
- Process signals never enter a research statistic, and no harness change touches a frozen spec, the ledger or a live run.

## Where things live

- Signals: `logs/harness/` (append-only JSONL), written by the harness logger (todo 685).
- Retro notes: one dated section per retro in the todo or phase that carries the change; standing results in `.planning/STATE.md` only while they are current.
- The lead loop in CLAUDE.md names the retro step; this doc is the method.
