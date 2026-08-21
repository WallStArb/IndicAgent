---
status: closed
priority: P2
filed: 2026-08-21
closed: 2026-08-21
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

## Closed 2026-08-21: hypothesis was WRONG -- gate is not broken

Ran all 3 of the "not yet checked" scope items. The version-drift hypothesis this
todo was filed on did not survive the actual check -- worth recording clearly
since the filing itself asserted it as "strongly indicated."

1. **CI's resolved mypy version confirmed**: `2.3.1` (even newer than the local
   `2.3.0` this todo cited) -- checked via `gh run view --log-failed` on the most
   recent CI run.
2. **That CI run's actual failure was `vulture`, not mypy** -- the job never
   reached the Mypy step at all (steps run sequentially in the same job; vulture
   failing halted it first). This was an old, already-superseded commit (nothing
   from this session has been pushed to `origin` yet, confirmed via
   `git fetch origin main` showing it far behind local `main`) -- not evidence
   either way for the mypy question.
3. **`mypy-baseline sync` against the current `.mypy-baseline.txt`... except it
   wrote to a *different*, undotted `mypy-baseline.txt` at repo root** (the
   tool's own default output path, not the real `.mypy-baseline.txt` --
   `--baseline-path` controls this explicitly, not just CWD-relative to the
   dotted convention). First diff attempt compared the untouched real file
   against itself (0 lines changed) and looked like confirmation of "no drift" --
   that comparison was against the wrong file, caught and corrected, not left
   uncorrected. Deleted the stray file (untracked, never should have existed).

**The real, correct test**: ran the *exact* CI command
(`mypy src/ --ignore-missing-imports | mypy-baseline filter`) against the real,
already-committed `.mypy-baseline.txt` -- **`new: 0`, exit code 0. The gate is
genuinely clean, not broken.**

**Root cause of this todo's original "72 new" finding, now correctly
identified**: that test ran `mypy src/api/main.py` (a single file), not
`mypy src/` (the full tree) -- mypy's own `note:` annotations and cross-file
context differ meaningfully between a single-file check and a full-tree check
of the same code, even with identical mypy/baseline versions, because mypy's
error/note text for a given line can depend on what else got type-checked in
the same run. Comparing a single-file run's output against a baseline generated
from a full-tree run will show spurious "new" violations regardless of any
version drift -- that mismatch, not `.mypy-baseline.txt` staleness, is what
produced the original finding. **Lesson for future verification passes**:
`mypy-baseline filter` must be checked against the same invocation shape
(`mypy src/ --ignore-missing-imports`, the whole tree) the baseline was
generated with -- a scoped single-file check for "did my change break
anything" is not equivalent and will produce false positives.

No fix needed -- CI's mypy gate was never actually broken. Closing with the
corrected finding recorded, not silently dropping a wrong hypothesis.
