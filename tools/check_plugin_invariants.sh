#!/bin/bash
# tools/check_plugin_invariants.sh
#
# Single source of truth for the plugin/Ring naming and boundary invariants
# shared between tools/pre-commit.hook (fast, staged-files-only local check)
# and .github/workflows/ci.yml (thorough, full-repository CI gate).
#
# Root cause this eliminates: the two call sites used to hand-maintain their
# own independent copies of the same allowlist regex and exclusion lists.
# They drifted apart -- CI's copy was missing 'Record' and 16 other suffixes
# the hook already accepted, and CI additionally lacked the hook's ai/swarm/
# statistics/services directory exclusions -- and broke main's CI on every
# single push from 2026-08-12 through 2026-08-16 (30+ consecutive red runs)
# because Unit Tests is gated behind this check (`needs: [lint, plugin-guards]`
# in ci.yml) and never ran during that window either. Patching the one missing
# suffix (commit ebef6d6b7) fixed the symptom; this consolidation fixes the
# defect class so the two checks cannot diverge again.
#
# Callers pass a newline-separated candidate file list on stdin (staged diff
# for the hook -- fast, local, incremental; a full find/glob for CI -- slower,
# thorough, catches drift from any source). File *selection* strategy is a
# legitimate, deliberate difference and stays in each caller. Everything that
# decides WHAT COUNTS AS COMPLIANT (allowlist suffixes, excluded paths) lives
# here exactly once.
#
# Usage: echo "$FILES" | tools/check_plugin_invariants.sh <check-name>
#   check-name: class-naming | file-naming | regime-type | ring0-boundary
#   (ring0-boundary ignores stdin -- it is always a full-repo scan, no
#   allowlist/exclusion drift is possible since it has no per-suffix rules)
#
# Exit 0 = clean (prints "OK: ..."), exit 1 = violations found (printed).

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
CHECK="${1:-}"

# Canonical allowlist: approved suffixes for concrete (non-abstract) classes
# in src/intelligence/. Do not duplicate this regex anywhere else in the repo
# -- both call sites source it from here.
_ALLOWED_SUFFIXES='Plugin|Mixin|Agent|Test|Data|Protocol|Enum|Error|Exception|Config|Result|State|Score|Frame|Entry|Event|Spec|Type|Info|Registry|Manager|Builder|Handler|Tracker|Scorer|Aggregat|Transition|Monitor|Stage|Runner|Client|Service|Target|Profile|Weight|Provider|Chain|Candidate|Queue|Executor|Processor|Task|Snapshot|Shape|Trainer|Analyzer|Validator|Auditor|Writer|Publisher|Report|Factory|Cache|Record|Vector|Decision'

case "$CHECK" in
  class-naming)
    # Canonical exclusions (union of what each side previously carved out
    # independently -- schemas.py/alpha_multiplier.py were excluded by both;
    # dag.py/position_sizer.py were CI-only (DagNode/Dag/PositionSize classes
    # don't fit the suffix taxonomy and were never meant to); swarm/ai/
    # statistics/services dir excludes were hook-only.
    VIOLATIONS=""
    while IFS= read -r file; do
      [ -z "$file" ] && continue
      case "$file" in
        *schemas.py|*alpha_multiplier.py|*dag.py|*position_sizer.py) continue ;;
        src/intelligence/swarm/*|src/intelligence/ai/*|src/intelligence/statistics/*|src/intelligence/services/*) continue ;;
      esac
      [ -f "${REPO_ROOT}/${file}" ] || continue
      FILE_VIOLATIONS=$(grep -n '^class [A-Z]' "${REPO_ROOT}/${file}" 2>/dev/null | \
          grep -vE "class.*((${_ALLOWED_SUFFIXES}))\\b" || true)
      if [ -n "$FILE_VIOLATIONS" ]; then
        VIOLATIONS="${VIOLATIONS}  ${file}:"$'\n'"$(echo "$FILE_VIOLATIONS" | sed 's/^/    /')"$'\n'
      fi
    done
    if [ -n "$VIOLATIONS" ]; then
      echo "FAIL: plugin class naming violations (rename to an approved suffix):"
      echo "$VIOLATIONS"
      exit 1
    fi
    echo "OK: all plugin classes follow naming convention"
    ;;

  file-naming)
    # Canonical exclusion: ai/swarm dirs use their own naming conventions.
    VIOLATIONS=""
    while IFS= read -r file; do
      [ -z "$file" ] && continue
      case "$file" in
        src/intelligence/ai/*|src/intelligence/swarm/*) continue ;;
      esac
      filename=$(basename "$file")
      echo "$filename" | grep -qE '^([a-z][a-z0-9_]*|__init__|conftest|TEMPLATE_agent|TEMPLATE)\.py$' || \
        VIOLATIONS="${VIOLATIONS}  ${file}"$'\n'
    done
    if [ -n "$VIOLATIONS" ]; then
      echo "FAIL: plugin file naming violations (rename to snake_case.py):"
      echo "$VIOLATIONS"
      exit 1
    fi
    echo "OK: all plugin files use snake_case naming"
    ;;

  regime-type)
    INFRA="signal_ledger.py lifecycle_tracker.py trade_framer.py signal_aggregator.py cis_scorer.py weight_updater.py confidence_calibrator.py __init__.py"
    VIOLATIONS=""
    while IFS= read -r file; do
      [ -z "$file" ] && continue
      case "$file" in
        src/intelligence/trading/*.py) ;;
        *) continue ;;
      esac
      filename=$(basename "$file")
      is_infra=false
      for i in $INFRA; do [ "$filename" = "$i" ] && is_infra=true && break; done
      $is_infra && continue
      [ -f "${REPO_ROOT}/${file}" ] || continue
      grep -q '^class.*Plugin' "${REPO_ROOT}/${file}" 2>/dev/null || continue
      grep -qE 'regime_type[[:space:]]*[:=]' "${REPO_ROOT}/${file}" || \
        VIOLATIONS="${VIOLATIONS}  ${file}"$'\n'
    done
    if [ -n "$VIOLATIONS" ]; then
      echo "FAIL: I7 plugins missing regime_type declaration:"
      echo "$VIOLATIONS"
      echo "Fix: add 'regime_type: ClassVar[str] = \"trend\" | \"mean_reversion\" | \"any\"'"
      exit 1
    fi
    echo "OK: all I7 plugins declare regime_type"
    ;;

  ring0-boundary)
    VIOLATIONS=$(grep -rn \
      "from src\.intelligence\|from src\.providers\|from src\.self_healing\|from services" \
      "${REPO_ROOT}/src/core/" "${REPO_ROOT}/src/observability/" --include="*.py" 2>/dev/null \
      | grep -v "^\s*#" | grep -v "ring0-ok" || true)
    if [ -n "$VIOLATIONS" ]; then
      echo "FAIL: Ring 0 boundary violation -- src/core/ or src/observability/ imports domain layer"
      echo "$VIOLATIONS"
      echo "Remediation: move the file to Ring 1 (src/intelligence/) or add a ring0-ok comment for lazy imports"
      exit 1
    fi
    echo "OK: Ring 0 boundary clean"
    ;;

  *)
    echo "Usage: check_plugin_invariants.sh <class-naming|file-naming|regime-type|ring0-boundary>" >&2
    exit 2
    ;;
esac
