---
status: pending
priority: P2
filed: 2026-08-21
source: verifying todo 329's fix didn't introduce new mypy violations -- ran the exact
  CI command (`mypy src/ --ignore-missing-imports | mypy-baseline filter`) locally
---

# `mypy-baseline filter` reports ~70 false-positive "new" violations against files
# unrelated to any local change -- baseline is version-drifted, not actually clean

## Finding

Running the exact CI command from `.github/workflows/*.yml`'s Mypy step
(`mypy src/ --ignore-missing-imports | mypy-baseline filter`) locally reports
`total errors: new: 72` and exits nonzero -- even when the only file checked
(`src/api/main.py`) has **zero import relationship** to anything actually changed
this session (confirmed via `grep -n "vocabulary_access\|signal_auditor\|
feature_validation_analyzer" src/api/main.py` -- no hits). The reported "new"
errors are all pre-existing code paths (`dependencies.db_manager` typing,
`KafkaSSEBroadcaster`, LLM provider chain `None`-checks) that have nothing to do
with any recent commit.

Root cause, not yet fully confirmed but strongly indicated: `errors by error code`
in the run's own summary shows `note: 70 [+70]` -- the bulk of the "new" count is
`note:` lines (contextual annotations mypy appends after certain errors), not new
`error:` lines. `requirements.txt` pins `mypy>=1.19.0` (a loose floor, not an exact
version) for both local installs and CI's `pip install`. Locally installed mypy is
**2.3.0**. If `.mypy-baseline.txt` (`tools: mypy-baseline sync`, per todo 311's
closing note) was generated against an older mypy version whose error/note text
formatting differs even slightly from 2.3.0's, `mypy-baseline filter`'s
message-text matching would treat every reformatted note as "new" even though the
underlying error is unchanged and pre-existing.

## Practical impact

Todo 311 (CLOSED 2026-08-21, same session) wired this gate into CI specifically to
"block only genuinely new type errors." If this drift is real, the gate is
currently **failing on every PR regardless of content** -- exactly the "training
people to ignore CI red" failure mode todo 311's own migration comment says the
baseline mechanism exists to prevent. Todo 329's actual changed files
(`src/core/vocabulary_access.py`, `services/signal_auditor.py`,
`src/intelligence/services/feature_validation_analyzer.py`) were separately
verified clean via a per-file `mypy <file>.py` check with zero `group_codes`-
related errors -- this todo is about the baseline mechanism itself, not a
regression from that change.

## Not yet checked (scope for the fix)

1. Confirm the mypy-version-drift hypothesis directly: pin the exact mypy version
   used when `.mypy-baseline.txt` was generated (check `mypy-baseline sync`'s
   invocation history / commit that added todo 311's fix) and diff its output
   against 2.3.0's on the same file.
2. If confirmed, either (a) pin `mypy==<baseline-generation-version>` exactly in
   `requirements.txt` (removes the drift permanently but freezes the type-checker
   version), or (b) regenerate `.mypy-baseline.txt` against the currently-pinned
   `mypy>=1.19.0` resolution and re-pin CI to install that exact resolved version
   going forward (keeps checker current, but needs periodic baseline regeneration
   discipline).
3. Verify CI itself (not just local) actually reproduces this -- GitHub Actions'
   `pip install "mypy>=1.19.0"` might resolve to a different version than what's
   installed in this local `.venv` (e.g. if CI's pip cache pinned an older
   release before 2.3.0 shipped) -- if so, CI may currently be passing cleanly and
   this is a local-environment-only symptom, changing the fix's urgency.

## Sizing

Investigation: small (confirm the version-drift hypothesis, check CI's actual
resolved mypy version). Fix: small if (a), medium if (b) (needs `mypy-baseline
sync` re-run + review of what shrinks/grows in the regenerated baseline before
committing it, per todo 311's own "should only shrink over time" invariant).
