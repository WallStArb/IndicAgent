#!/bin/bash
# tools/check_counterfactual_ledger.sh
#
# Single source of truth for the counterfactual-ledger enforcement check
# (pre-commit hook check #9), shared between tools/pre-commit.hook (staged
# files, local) and .github/workflows/ci.yml (PR-diff files, todo 310).
#
# Extracted 2026-08-21 (todo 310) rather than re-typed a second time in CI --
# this project already hit the exact "two independently-copied bash regexes
# drifted apart" failure mode once with the plugin/Ring invariants (see
# check_plugin_invariants.sh's own docstring: 30+ consecutive red CI runs,
# 2026-08-12 through 2026-08-16), so a new check does not get a second,
# separately-maintained copy of its own logic.
#
# Invariant enforced: docs/research/canonical-simulator.md's binding rule --
# no validation client builds its own replay or counterfactual path;
# counterfactual P&L claims are alpha_frames rows, new shapes are
# frame_variants, never new tables or services. A new table shaped like a
# claim ledger (events/frames/claims/occurrences/outcomes/ledger suffix) is
# exactly the silent-drift failure mode that invariant exists to block (see
# also: signal_outcomes was dropped in favor of signal_ledger in Phase 130 --
# this codebase has hit this before).
#
# Escape hatch: a `-- LEDGER-EXCEPTION: <reason>` comment anywhere in the file.
#
# Usage: echo "$SQL_FILES" | tools/check_counterfactual_ledger.sh
#   SQL_FILES: newline-separated candidate .sql migration file paths (repo-
#   relative or absolute -- both callers pre-filter to .sql files under a
#   migrations?/ directory before piping in; this script does not re-filter
#   by path, only by file content).
#
# Exit 0 = clean (prints "OK: ..."), exit 1 = violations found (printed).

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Existing, already-legitimate ledger-shaped tables -- not new drift.
ALLOWLIST='^(alpha_events|alpha_frames|signal_ledger|signal_events|trade_frames|trade_executions|llm_calls|config_history|concept_transition_log)$'

SQL_FILES="$(cat)"

if [ -z "$SQL_FILES" ]; then
    echo "OK: no migration files changed"
    exit 0
fi

FAILURES=0
for file in $SQL_FILES; do
    case "$file" in
        /*) full_path="$file" ;;
        *) full_path="${REPO_ROOT}/${file}" ;;
    esac
    [ -f "$full_path" ] || continue

    # Extract table names from CREATE TABLE statements (with or without IF NOT EXISTS)
    TABLES=$(grep -ioE 'CREATE TABLE( IF NOT EXISTS)? [a-zA-Z_][a-zA-Z0-9_]*' "$full_path" | \
        awk '{print $NF}')

    for table in $TABLES; do
        table_lc=$(echo "$table" | tr '[:upper:]' '[:lower:]')

        if echo "$table_lc" | grep -qE "$ALLOWLIST"; then
            continue
        fi

        if echo "$table_lc" | grep -qE '(_events|_frames|_claims|_occurrences|_outcomes|_ledger)$'; then
            if grep -qE '^\s*--\s*LEDGER-EXCEPTION:' "$full_path"; then
                continue
            fi
            echo "FAILED: new table '${table}' looks like a parallel claim/event ledger"
            echo "  File: ${file}"
            echo "  Rule: docs/research/canonical-simulator.md -- counterfactual claims are"
            echo "    alpha_frames rows; new shapes are frame_variants, not new tables."
            echo "  Remediation: extend alpha_frames with a frame_variant instead, or if"
            echo "    this table is genuinely a different concept, add a comment:"
            echo "    -- LEDGER-EXCEPTION: <why this is not a frame_variant>"
            FAILURES=$((FAILURES + 1))
        fi
    done
done

if [ "$FAILURES" -gt 0 ]; then
    exit 1
fi

echo "OK: no unjustified parallel ledger tables"
exit 0
