# Ship or Sink Rules

**Version:** 2.9
**Status:** current
**Last Updated:** 2026-09-04

Guidelines for working with AI coding agents without losing momentum, burning context, or shipping broken code.

---

## Before You Start

- **Define "Good Enough":** Name the 3 things this session *must* produce. Once they work, stop and commit.
- **Pick Your Mode:** Are you *shipping* (working code, no experiments) or *researching* (algo improvement, shadow only)? The rules are different. Don't mix them in one session.
- **Check the branch:** Always work on a feature branch. Never develop directly on `main`.

## While You're Building

- **The 3-Prompt Rule:** If the bug isn't solved in 3 tries, stop. Manually debug 5 minutes or rewrite the prompt from scratch.
- **Resist the Refactor:** Don't ask for cleaner code unless it's broken or unreadable. Cleaner code that doesn't ship is waste.
- **One Variable at a Time:** When improving an algo, change exactly one thing per session. Multiple changes make causality impossible — you won't know what worked.
- **Shadow First:** Any change that could affect signal output lives in shadow mode until it proves itself. Working code always beats better code until there's evidence.

## Done-Coding SOP

Execute in this exact order before considering the session complete:

1. **Simplify** — run the `code-simplifier` agent on changed code
2. **Review** — run `/review` (peer code review)
3. **Test** — `.venv/bin/pytest tests/unit/ -q` must be green
4. **Commit** — on the feature branch, no AI attribution in commit messages
5. **Merge** — `git checkout main && git merge --ff-only <branch>`
6. **Clean** — `git branch -d <branch> && git worktree prune`
7. **Push** — `git push origin main`

Never skip steps. Never reorder steps. The SOP exists because each step catches a different class of defect.

## How You Work with the Agent

- **Be the Architect:** You own the intent. The agent owns the syntax. Never let those swap.
- **Commit Early:** If it works, commit it. Improvements happen *on top of* commits, not instead of them.
- **The "Does It Run?" Gate:** Before ending any session, verify the service starts and produces output. Don't end on "the code looks right."
- **Narrow the Scope:** Just because the agent *can* run 50 commands doesn't mean it should. Constrain the scope before it starts, not after it's made a mess.
- **No Human Checkpoints:** Run everything autonomously. Don't stop mid-session to ask for confirmation on decisions you can make from context.
