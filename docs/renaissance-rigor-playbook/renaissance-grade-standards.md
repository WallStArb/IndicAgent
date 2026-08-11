# Renaissance-Grade Standards

**Version:** 1.0 (portable)
**Status:** template
**Source:** genericized from IndicAgent `docs/foundation/renaissance-grade-standards.md` v1.0

## Philosophy

At Renaissance Technologies, discipline wasn't an afterthought — it was the core advantage. Jim Simons' team didn't succeed by finding better signals; they succeeded by applying mathematical rigor to everything: how they named concepts, how they evaluated evidence, how they kept their workspace.

A messy codebase is a messy mind. Accumulated junk files, bloated logs in git infrastructure, orphaned worktrees, stale cache — these are not "minor annoyances." They are institutional rot. They signal that precision is optional, that debris is acceptable, that someone else will clean up later.

"Later" never comes.

**Clean as you go** means:
- No accumulation of debris
- No shortcuts that become permanent
- No "temporary" files that outlive their context
- Git infrastructure stays pristine
- Standards are enforced, not suggested

The standard is not "clean when it hurts." The standard is **always clean**.

---

## The Renaissance Principles

| Concept | Principle | Anti-pattern |
|---------|-----------|--------------|
| **Clean As You Go** | No debris accumulation. Clean before context switch. | "I'll clean it later" (never happens) |
| **Evidence Over Opinion** | p < 0.05 or it doesn't exist. Shadow mode first. | Promoting unproven features to production |
| **Data Is Permanent** | Every labeled sample is kept forever. Storage is cheap; signal is irrecoverable. | Deleting "old" outcome records to save space |
| **Silent Failure Is Fatal** | Loud crashes > silent wrong answers. Hidden bias is a bug. | Swallowed exceptions, default values that hide errors |
| **Standards Are Enforced** | If it matters, it's automated. Pre-commit hooks, not guidelines. | "We should remember to do X" (no enforcement) |
| **Naming Precision = Thinking Precision** | One definition per term. Glossary is law. | Using two words for the same concept |
| **Separation of Concerns Is Law** | Compute ≠ Persistence ≠ Transport. Violations break the system. | Hot-path components querying the database directly |
| **Trust Your Automation** | No human checkpoints on decisions context can resolve. | Mid-session confirmations on foreseeable choices |
| **Complexity Is Technical Debt** | Every unnecessary abstraction is paid forever. Remove before calcification. | Premature abstraction, over-engineering |
| **Git Infrastructure Is Sacred** | `.git/` never accumulates runtime state. Logs belong in `logs/`. | Multi-MB log files written into `.git/hooks/` |
| **Architectural Invariants Are Non-Negotiable** | The DAG topology is the architecture. Violating it means the system can't be reasoned about. | Component-to-component direct calls, hardcoded topic strings |
| **Renaissance Naming Convention** | Concept name derives all layer names (`signal_tracker` → `SignalTracker`). | Inconsistent naming across code/infra/db |

These are timeless. They apply regardless of which architectural generation the system is currently on.

---

## Standards by Domain

### Filesystem Hygiene

| Area | Standard | Anti-pattern |
|------|----------|--------------|
| Git infrastructure | Never accumulate runtime logs in `.git/` | Multi-MB log file written into `.git/hooks/` |
| Language build/dep cache | Removed before commit | Committing cache directories |
| Worktrees | Pruned after merge; no orphaned dirs | Empty worktree dirs lingering for weeks |
| Logs | Rotate to `logs/`; apply retention policies | Log files growing without bound |
| Dependencies | No build artifacts, no vendored libs in repo | Package build artifacts committed |

**Rule:** If it's generated, it's not committed. If it's temporary, it's removed before context switch.

### Code Hygiene

| Area | Standard | Anti-pattern |
|------|----------|--------------|
| Imports | No unused imports; no wildcard imports | Bloated import blocks |
| Dead code | Remove immediately upon deprecation | Commented-out blocks "just in case" |
| Tests | One test name per directory; no dupes | Same test name duplicated across files |
| Naming | Glossary-compliant; no synonyms | Two names for the same concept in one codebase |
| Separation | Hot path never touches database | Pipeline components querying DB directly |

**Rule:** If it's not used, delete it. If it's ambiguous, name it precisely.

### Data Hygiene

| Area | Standard | Rationale |
|------|----------|------------|
| Retention | No data deletion policies for signal-bearing tables | Every labeled outcome is a training sample |
| Storage | Compression over deletion | Storage-layer compression handles cost |
| Evidence | Shadow mode before production | Significance gates prevent unproven promotion |
| Integrity | Boundary invariants enforced | Gate-boundary bugs discard training data permanently |

**Rule:** Storage is the cheapest thing you own. Signal is irrecoverable.

### Architecture Hygiene

| Area | Standard | Violation Impact |
|------|----------|------------------|
| DAG topology | Invariants are non-negotiable | System can no longer be reasoned about |
| Topics/keys | All keys via a single central module | Hardcoded strings create invisible coupling |
| Timestamps | All UTC, timezone-aware | Mixed timezones corrupt ordering |
| Communication | Topics/queues only; no direct component calls | Violates restart-from-offset guarantee |
| Scaling | Process manager + lag/queue-depth metric | Lag/depth is the metric, not raw CPU |

**Rule:** The DAG is the architecture. Violating it breaks guarantees.

---

## Standard Operating Procedures

### Daily (Automatic)
- Log rotation via your process manager
- Build/dependency cache ignored by git (`.gitignore` enforces this)
- Pre-commit hooks enforce standards (lint, format, glossary, duplicates)

### Weekly (Manual)
```bash
# 1. Prune git worktrees
git worktree prune

# 2. Check for accumulating artifacts
find . -type f -name "*.log" -size +10M -not -path "*/.git/*"
find . -type d -name "__pycache__" -not -path "*/.git/*"   # or your language's build-cache dir

# 3. Verify database health
psql -h <host> -d <your_db> -c "
SELECT schemaname, tablename,
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
LIMIT 10;
"
```

### Monthly (Manual)
```bash
# 1. Database maintenance
psql -h <host> -d <your_db> -c "VACUUM ANALYZE;"

# 2. Check compression/partition health (if using a time-series extension)
# 3. Log archival — compress logs older than 30 days
find logs/ -name "*.log" -mtime +30 -exec gzip {} \;

# 4. Coverage/cleanup of test artifacts
rm -rf .pytest_cache .ruff_cache htmlcov .coverage
```

### Done-Coding SOP
From [Ship or Sink Rules](ship-or-sink-rules.md) — execute in order before considering a session complete:

1. **Simplify** — run a code-simplification pass on changed code
2. **Review** — run a peer code review
3. **Test** — unit test suite must be green
4. **Commit** — on the feature branch, no AI attribution
5. **Merge** — fast-forward merge to main
6. **Clean** — delete the feature branch, prune worktrees ← Renaissance-grade
7. **Push** — push main to remote

No branches left behind. No worktrees accumulating. Clean as you ship.

---

## Anti-Patterns

These violate Renaissance-grade standards. Do not do them.

### The "I'll Clean It Later" Pattern
```bash
# BAD: Temporary file that becomes permanent
touch /tmp/quick_fix.json && mv /tmp/quick_fix.json data/

# GOOD: Name it properly, put it in the right place
mv /tmp/quick_fix.json data/ephemeral_fix_<date>.json
```

### The "Git Infrastructure as Log Storage" Pattern
```bash
# BAD: Hook writes to .git/hooks/
LOG_FILE="${GIT_COMMON_DIR_PATH}/hooks/pre-commit.log"

# GOOD: Hook writes to repo logs/
LOG_FILE="${REPO_ROOT}/logs/pre-commit.log"
```

### The "Commented-Out Code" Pattern
```python
# BAD: Dead code "just in case"
# def old_signal_logic():
#     return deprecated_calculation()

# GOOD: Remove it. Git history has the old code.
def signal_logic():
    return current_calculation()
```

### The "Silent Failure" Pattern
```python
# BAD: Swallows errors, produces hidden wrong answers
try:
    result = risky_calculation()
except Exception:
    result = 0  # Silent default — no one knows calculation failed

# GOOD: Fail loudly
result = risky_calculation()  # Let exception propagate
```

### The "Premature Abstraction" Pattern
```python
# BAD: Abstracting before pattern is proven
class AbstractSignalProcessorFactory:
    def create_processor(self, type: str) -> SignalProcessor:
        # Only one implementation exists, but we're "ready for future"
        ...

# GOOD: One concrete class. Abstract when you have 2+ implementations.
class SignalProcessor:
    def process(self, data): ...
```

---

## Enforcement

### Pre-commit Hook
The pre-commit hook enforces standards automatically:
- Lint (code quality)
- Format (consistency)
- Duplicate test detection (test hygiene)
- Glossary enforcement (naming precision)
- Ring/layer boundary checks (separation of concerns) — see [naming-system.md](naming-system.md) §2

### Git Ignore
`.gitignore` must exclude all generated artifacts:
```
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
*.log.1
*.log.[0-9].gz
```

### Review Checklist
Before any commit or merge:
- [ ] No cache directories committed
- [ ] No runtime logs in `.git/`
- [ ] No commented-out code
- [ ] No unused imports
- [ ] Glossary-compliant naming
- [ ] Database maintenance up-to-date
- [ ] Worktrees pruned

---

## References

- [Renaissance Principles](principles.md) — Core philosophy
- [Musk's 5-Step Process](musk-5-step-process.md) — Order of operations before touching code
- [Ship or Sink Rules](ship-or-sink-rules.md) — Done-Coding SOP
- [Naming System](naming-system.md) — Naming convention

---

**Remember:** Renaissance-grade discipline is not a goal. It is a baseline. The alternative is institutional rot — and Renaissance didn't win by accumulating rot.

---

## Adopting This in a New Project

Copy this file verbatim. Delete the "Case Study" section pattern entirely (the source project had one documenting its own first cleanup pass) — don't fabricate one. Write your own case study only after you've actually run a real cleanup and have real before/after numbers to cite; a placeholder case study with invented sizes is worse than no case study.
