# Glossary Enforcement and Lifecycle Management

**Date:** 2026-06-06
**Status:** archived
**Type:** Design Specification
**Last Updated:** 2026-06-08
**Resolution:** Implemented — see commits around 2026-06-06

---

## Execution Summary (2026-06-08)

This design was implemented via commits:
- `6335c03a` feat(glossary): add check 8 - glossary enforcement in pre-commit hook
- `7148f430` fix(glossary): add python fallback check in hook check 8
- `d897c8f4` docs(glossary): allow taxonomy for hierarchical structures, scope vocabulary ban
- `23980bf1` refactor(glossary): precompile patterns, O(1) dedup, flatten mode dispatch
- `d96bdcf8` docs: fix naming conventions and add product-laws

Tools created: `tools/check_glossary.py`, `tools/migrate_glossary.py`

The glossary enforcement system is now production code. This document is preserved for historical reference.

---



Make the glossary self-enforcing. Every banned synonym is caught at commit time. Every term has an explicit lifecycle status. Deprecation produces a machine-generated blast radius report.

---

## Glossary Format Changes

Each entry gains two structured lines after the existing prose:

```markdown
**Banned:** synonym1, synonym2, synonym3
**Status:** active
```

`Status` values:

| Value | Meaning |
|---|---|
| `active` | Canonical. Enforced. Use this term. |
| `deprecated` | Being phased out. A replacement is designated. Pre-commit blocks new uses. |
| `retired` | Fully replaced. All uses removed. Kept for historical reference only. |

Deprecated entries also include:

```markdown
**Replaced by:** `canonical-term`
**Deprecated:** YYYY-MM-DD
```

The `**Banned:**` line is the machine-readable contract. The existing `**Not:**` prose remains for human context - it explains why the synonyms are wrong, not just that they are wrong.

---

## tools/check_glossary.py

Parses `docs/foundation/glossary.md` and scans staged files for violations.

### Rule extraction

Reads the glossary and builds a list of rules:

```python
@dataclass
class GlossaryRule:
    canonical: str          # e.g. "vocabulary"
    banned: list[str]       # e.g. ["taxonomy", "ontology", "classification scheme"]
    status: str             # "active" | "deprecated" | "retired"
    replaced_by: str | None # only for deprecated/retired
```

Parsing contract:
- `### \`term\`` line → canonical term
- `**Banned:** a, b, c` line → banned synonyms (comma-separated, stripped)
- `**Status:** value` line → status
- `**Replaced by:** \`term\`` line → replacement (optional)

### Scan modes

**Prose scan** — applied to all `.py` and `.md` files:
- Extracts comment/docstring content from `.py` files (lines starting with `#`, content between `"""`)
- Scans full content of `.md` files
- Regex: `\b{banned_term}\b` (whole word, case-insensitive)
- Multi-word banned terms (e.g. "classification scheme") matched as phrase

**Identifier scan** — applied to `.py` files only:
- Splits identifiers on `_` and camelCase boundaries
- Checks each token against banned terms
- Catches `taxonomy_weight`, `getOntology()`, `CLASSIFICATION_SCHEME`

### Exit behavior

- Any `retired` term hit → `FAILED` (exit 1), prints file:line
- Any `deprecated` term hit → `FAILED` (exit 1), prints file:line + replacement
- Clean → `OK` (exit 0)

Both deprecated and retired block — you fix before moving on. There is no "warn and continue."

### Usage

```bash
# Called by pre-commit with staged files
python tools/check_glossary.py src/some_file.py docs/some_doc.md

# Called standalone for a full codebase scan
python tools/check_glossary.py $(find . -name "*.py" -o -name "*.md" | grep -v .venv | grep -v node_modules)
```

---

## tools/migrate_glossary.py

Run manually when deprecating a term to assess blast radius before updating the glossary.

### Usage

```bash
# Scan entire codebase for a specific deprecated term
python tools/migrate_glossary.py --term taxonomy

# Scan for all currently deprecated terms
python tools/migrate_glossary.py --deprecated
```

### Output

```
Scanning for deprecated glossary terms...

  taxonomy (replace with: vocabulary)
    docs/foundation/old-doc.md:14:  "...the taxonomy of instruments..."
    src/intelligence/plugins/foo.py:42:  # taxonomy weight

  ontology (replace with: vocabulary)
    docs/research/some-idea.md:7:  "...ontology-driven classification..."

2 deprecated terms found across 3 occurrences.
Fix these and promote to 'retired' in the glossary.
```

Exits 1 if hits found, 0 if clean. No auto-replace. You fix, verify, then update the glossary status.

---

## Pre-commit Hook — Check 8

Added to `.git/hooks/pre-commit` following the existing pattern:

```bash
check_glossary_terms() {
    echo "[8/8] Glossary enforcement check..."

    CHANGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | \
        grep -E '\.(py|md)$' | \
        grep -vE '(\.venv|node_modules|\.git)' || true)

    if [ -z "$CHANGED_FILES" ]; then
        echo "  OK No Python or Markdown files changed"
        return 0
    fi

    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
    SCRIPT="${REPO_ROOT}/tools/check_glossary.py"

    if [ ! -f "$SCRIPT" ]; then
        echo "  SKIPPED: tools/check_glossary.py not found"
        return 0
    fi

    FULL_PATHS=""
    for file in $CHANGED_FILES; do
        if [ -f "${REPO_ROOT}/${file}" ]; then
            FULL_PATHS="${FULL_PATHS} ${REPO_ROOT}/${file}"
        fi
    done

    if ! "$PYTHON_BIN" "$SCRIPT" $FULL_PATHS; then
        echo "  Remediation: Replace banned term with canonical glossary term."
        echo "  Reference: docs/foundation/glossary.md"
        return 1
    fi

    return 0
}
```

The check count in the header comment updates from `[6/6]`-style to `[8/8]` (ring0 boundary is already 7).

---

## Lifecycle Process

### Adding a new term

1. Check the glossary — it may exist under a different name.
2. Add the entry with `**Status:** active`, `**Banned:**` list, and `**Not:**` prose.
3. Commit. Pre-commit picks it up immediately on next run.

### Deprecating a term

1. Run `python tools/migrate_glossary.py --term <old-term>` to get blast radius.
2. Fix all occurrences in the codebase.
3. Update the glossary entry: set `**Status:** deprecated`, add `**Replaced by:**` and `**Deprecated:**` date.
4. Commit the glossary change and all usage fixes together.
5. Pre-commit now blocks any new use of the deprecated term.

### Retiring a term (deprecation complete)

1. Confirm `python tools/migrate_glossary.py --term <old-term>` returns clean.
2. Update glossary entry to `**Status:** retired`.
3. Commit.

### Replacing a term (rename)

Deprecate the old term, add the new term as `active` in the same commit. The migration script handles the search; the pre-commit hook enforces forward.

---

## Files Changed

| File | Change |
|---|---|
| `docs/foundation/glossary.md` | Add `**Banned:**` and `**Status:** active` to all 20 entries |
| `tools/check_glossary.py` | New — parser + scanner |
| `tools/migrate_glossary.py` | New — blast radius reporter |
| `.git/hooks/pre-commit` | Add check 8 |
| `CLAUDE.md` | Already updated (v5.46.0) |

---

## Out of Scope

- Auto-replace on migration (manual fix ensures correct context)
- Glossary coverage of YAML/JSON config files (too noisy, too many false positives)
- Integration with `tag_vocabulary` DB table (separate system, separate enforcement)
