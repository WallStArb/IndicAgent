---
status: pending
priority: P3
filed: 2026-08-09
source: found while running /gsd-review 172 --agy (Phase 172 cross-AI plan review)
---

# `gsd-review`'s documented Antigravity (`agy`) invocation via stdin doesn't work against the installed CLI version

## What

`~/.claude/get-shit-done/workflows/review.md`'s `invoke_reviewers` step documents this
invocation for Antigravity:

```bash
cat /tmp/gsd-review-prompt-{phase}.md | agy -p - 2>/dev/null > /tmp/gsd-review-antigravity-{phase}.md
```

Against the installed `agy` (v0.144.1-equivalent binary at `~/.local/bin/agy`), `-p -` does
**not** read the prompt from stdin. Piped content is silently discarded and `agy` responds as
if given an empty/no prompt (e.g. "It looks like your request was empty..."). This reproduces
with both a 227KB real review prompt and a trivial one-line test string piped in.

Confirmed via direct experiment (see `agy --help`): there is no documented `-`-means-stdin
convention for `-p`/`--prompt`/`--print`. The flag expects the prompt as a literal
command-line argument.

## Why it matters

Any `/gsd-review` run that includes `--antigravity`/`--agy` (or reaches Antigravity via
`--all`/`review.default_reviewers`, now `["codex","antigravity"]` after this session) silently
produces an empty/garbage review instead of failing loud — `agy`'s stdout is a real-looking
chat response ("How can I help you today?"), not an error, so the skill's existing
`[ ! -s file ]` empty-check does not catch it and a bad review could get written into
`REVIEWS.md` without anyone noticing.

## What was done as a workaround (this session, not upstreamed)

1. Passing the full 227KB prompt as a literal `agy -p "$(cat file)"` argument hit the
   sandbox's `ARG_MAX`-adjacent limit ("Argument list too long") even though `getconf ARG_MAX`
   reports 2MB and the environment is tiny (~1.8KB) — the actual ceiling in this environment is
   lower than `ARG_MAX` for unclear reasons and wasn't root-caused.
2. Switched to a compact (~2KB) prompt that points `agy` at the phase's `.planning/` files by
   path and asks it to read them itself, run with `--dangerously-skip-permissions` (both
   `read_file` and `command` tool calls are auto-denied in headless mode without it — confirmed
   via `jetski: no output produced ... auto-denied` errors). This worked and produced a real,
   useful review with no repo mutation (`git status --short` confirmed clean before/after).

## What to do

1. Fix `~/.claude/get-shit-done/workflows/review.md`'s Antigravity invocation to either:
   - pass the prompt as a literal argument with a *size guard* (fall back to the
     file-pointer-plus-`--dangerously-skip-permissions` pattern above once the prompt exceeds
     some threshold, e.g. ~50KB), or
   - always use the file-pointer pattern for Antigravity specifically, since it's an agentic
     CLI with real filesystem access rather than a plain chat-completion endpoint like Codex.
2. Make the `[ ! -s file ]` empty-output check in `invoke_reviewers` also detect a
   suspiciously-short, chat-greeting-shaped response (e.g. contains "How can I help you today"
   or "your request was empty") so a broken invocation fails loud instead of writing a fake
   review into `REVIEWS.md`.
3. Note the `--dangerously-skip-permissions` requirement and its risk (auto-approves *all*
   tool calls, not just read_file) explicitly in the workflow doc, with a reminder to keep the
   Antigravity review prompt read-only-scoped since the flag can't be narrowed to read-only.
4. Re-verify against whatever `agy` version is actually installed at fix time — this was found
   against v0.144.1-equivalent; the CLI may change its stdin/argument handling in a later
   release and the workaround above may become unnecessary or wrong.

This is GSD tooling (`~/.claude/get-shit-done/`), not IndicAgent repo code — no `src/`,
`services/`, or test changes apply here.
