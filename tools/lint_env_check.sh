#!/usr/bin/env bash
# Run the CI lint and plugin-invariant steps in CI's own environment: a Python 3.13 venv holding only
# ruff, black, vulture, mypy and mypy-baseline. CI's mypy baseline is built there, and the project
# .venv (full requirements, other versions) gives different mypy results, so a green local mypy is
# no promise of a green CI. Run before a push; read the result after with tools/ci_status.py.
#
#   tools/lint_env_check.sh            # all steps, from the repo or worktree you are in
#
# The venv is cached in $LINT_ENV (default ~/.cache/indicagent/lint-env) and re-synced to the newest
# allowed versions on each run, as CI installs fresh with the same specifiers; the uv cache makes
# the sync a no-op when nothing moved. Every step runs even after a failure, then the summary names
# each failed step. Exit 0 only when all pass.
set -u
cd "$(git rev-parse --show-toplevel)"

ENV_DIR="${LINT_ENV:-$HOME/.cache/indicagent/lint-env}"
SPECS=('ruff>=0.15.0' 'black>=26.1.0' 'vulture>=2.11' 'mypy>=1.19.0' 'mypy-baseline>=0.7.4')  # keep equal to .github/workflows/ci.yml

[ -x "$ENV_DIR/bin/python" ] || uv venv --quiet --python 3.13 "$ENV_DIR" || exit 2
uv pip install --quiet --upgrade --python "$ENV_DIR/bin/python" "${SPECS[@]}" || exit 2
export PATH="$ENV_DIR/bin:$PATH"

failed=()
step() {
  local name=$1; shift
  echo "[lint_env_check] $name"
  "$@" || failed+=("$name")
}

mypy_filter() { set +o pipefail; mypy src/ --ignore-missing-imports | mypy-baseline filter; }
plugins() {
  find src/intelligence/ -name "*.py" | tools/check_plugin_invariants.sh class-naming &&
  find src/intelligence/ -name "*.py" | tools/check_plugin_invariants.sh file-naming &&
  find src/intelligence/trading/ -name "*.py" | tools/check_plugin_invariants.sh regime-type &&
  tools/check_plugin_invariants.sh ring0-boundary
}
counterfactual() {
  git diff --name-only --diff-filter=ACM origin/main...HEAD -- '*.sql' | grep -E '(migrations?)/' |
    tools/check_counterfactual_ledger.sh
}

step ruff ruff check .
step black black --check .
step vulture vulture
step mypy bash -c "$(declare -f mypy_filter); mypy_filter"
step duplicate-tests python tools/check_duplicate_tests.py
step glossary python tools/check_glossary.py --all --baseline tools/glossary_baseline.json
step plugin-invariants plugins
step counterfactual-ledger counterfactual

if [ ${#failed[@]} -gt 0 ]; then
  echo "[lint_env_check] FAILED: ${failed[*]}"
  exit 1
fi
echo "[lint_env_check] all steps passed"
