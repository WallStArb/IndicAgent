"""CI guard: summary cards under docs/research/summary-cards/ must be valid and must cover
every table phase 186 drops.

Drift class: a table dropped with no checked-in record of what was learned from it (design
14.2 "conclusions are records", D-06). Downstream drop plans (186-11, 186-22, 186-27 and the
other drop plans) gate on this test being green before any drop migration runs: a wrong or
incomplete card would let a table go with its lesson lost. The lint validates front matter
(the strict YAML loader rejects YAML 1.1 booleans so `reproducible: no` cannot pass as False),
source references (against .planning/gate_look_log.jsonl for gate refs), git existence of
recipe pointers, and full DROP_TABLES coverage.

CI-clean: no DB, no network; git-history checks skip on a shallow clone (CI's checkout has no
fetch-depth) or outside a git repo, with a stated reason; every other check still runs.
"""

from __future__ import annotations

import functools
import json
import re
import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).parent.parent.parent
_CARD_DIR = _REPO_ROOT / "docs" / "research" / "summary-cards"
_GATE_LOOK_LOG = _REPO_ROOT / ".planning" / "gate_look_log.jsonl"

_REQUIRED_KEYS = (
    "card_id",
    "kind",
    "title",
    "idea",
    "verdict",
    "verdict_date",
    "recipe",
    "results",
    "known_defects",
    "spans_looked_at",
    "forward_span_looks",
    "tables",
    "status_now",
    "reopened_as",
    "reproducible",
    "sources",
    "related_cards",
)
_KINDS = frozenset({"legacy_verdict", "dead_cache"})
_VERDICTS = frozenset(
    {"DEAD", "FAIL", "INCONCLUSIVE", "KILLED_ON_PAPER", "REJECTED_AS_AXIS", "NO_CONCLUSION"}
)
_SPAN_ROLES = frozenset({"in_sample", "forward_span", "full_history"})
_STATUS_VALUES = frozenset({"closed", "reopened"})

# The 14 drop targets of phase 186 (D-14 list plus ctx tables, construction_spreads,
# forward_returns, feature_vectors, feature_ic_scores). Later drop plans must add any new
# drop target here BEFORE dropping it, and write its summary card first.
DROP_TABLES = frozenset(
    {
        "ensemble_weights",
        "ensemble_alpha",
        "alpha_ensemble_ic",
        "alpha_events",
        "alpha_frames",
        "context_features",
        "feature_ic_scores_history",
        "ctx_events",
        "ctx_snapshots",
        "construction_spreads",
        "alpha_strategy_scores",
        "forward_returns",
        "feature_vectors",
        "feature_ic_scores",
    }
)

_CARD_ID_RE = re.compile(r"^(legacy|cache)-[a-z0-9]+(-[a-z0-9]+)*$")
_TABLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_KNOWN_REF_PREFIXES = frozenset({"db", "gate_look_log"})


class _CardLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 booleans: only true/false. YAML 1.1 also reads yes/no/on/off
    as booleans, which would let `reproducible: no` pass silently as False."""


_CardLoader.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_CardLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def _as_date(value) -> bool:
    """Accept a YAML-parsed date or an ISO string (hand-built dicts in tests)."""
    if isinstance(value, date):
        return True
    if isinstance(value, str):
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    return False


def _parse_card(path: Path) -> dict:
    """Split a card file into front matter via the strict loader. Raises on missing fences."""
    text = path.read_text()
    if not text.startswith("---\n"):
        raise ValueError(f"{path.name}: card must start with a '---' front matter fence")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError(f"{path.name}: card front matter has no closing '---' fence")
    front = yaml.load(text[4:end], Loader=_CardLoader)
    if not isinstance(front, dict):
        raise ValueError(f"{path.name}: front matter must be a YAML mapping")
    return front


def _lint_card(front: dict, *, gate_ids: set[str], gate_run_ts: set[str]) -> list[str]:
    """Every non-git lint rule. Returns a list of human-readable errors (empty when clean)."""
    errors: list[str] = []

    for key in _REQUIRED_KEYS:
        if key not in front:
            errors.append(f"missing required key: {key}")

    if errors:
        # Later checks index into missing keys; report the gaps and stop.
        return errors

    card_id = front["card_id"]
    if not isinstance(card_id, str) or not _CARD_ID_RE.match(card_id):
        errors.append(f"card_id {card_id!r} does not match ^(legacy|cache)-[a-z0-9]+(-[a-z0-9]+)*$")

    kind = front["kind"]
    if kind not in _KINDS:
        errors.append(f"kind {kind!r} not in {sorted(_KINDS)}")

    if not isinstance(front["title"], str) or not front["title"]:
        errors.append("title must be a non-empty string")
    if not isinstance(front["idea"], str) or not front["idea"]:
        errors.append("idea must be a non-empty string")

    verdict = front["verdict"]
    if verdict not in _VERDICTS:
        errors.append(f"verdict {verdict!r} not in {sorted(_VERDICTS)}")
    elif kind == "dead_cache" and verdict != "NO_CONCLUSION":
        errors.append(f"dead_cache card must use verdict NO_CONCLUSION, got {verdict!r}")

    if not _as_date(front["verdict_date"]):
        errors.append("verdict_date must be an ISO date")

    recipe = front["recipe"]
    if not isinstance(recipe, dict) or set(recipe) < {"spec", "script", "recipe_commit"}:
        errors.append("recipe must be a mapping with spec, script and recipe_commit")
    else:
        for path_key in ("spec", "script"):
            value = recipe[path_key]
            if value is not None and (not isinstance(value, str) or value.startswith("/")):
                errors.append(f"recipe.{path_key} must be a repo-relative path or null")
        commit = recipe["recipe_commit"]
        if not isinstance(commit, str) or not _COMMIT_RE.match(commit):
            errors.append(f"recipe.recipe_commit {commit!r} must be 40 lowercase hex")

    results = front["results"]
    if not isinstance(results, list):
        errors.append("results must be a list")
    else:
        if not results and kind != "dead_cache":
            errors.append("results may be empty only for dead_cache cards")
        for entry in results:
            if not isinstance(entry, dict) or set(entry) < {"name", "value", "source"}:
                errors.append(f"results entry {entry!r} needs name, value and source")
                continue
            value = entry["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                errors.append(f"results[{entry.get('name')!r}].value must be a number or string")

    if not isinstance(front["known_defects"], list) or not all(
        isinstance(d, str) for d in front["known_defects"]
    ):
        errors.append("known_defects must be a list of strings")

    spans = front["spans_looked_at"]
    if not isinstance(spans, list):
        errors.append("spans_looked_at must be a list")
    else:
        for span in spans:
            if not isinstance(span, dict) or set(span) < {"start", "end", "role"}:
                errors.append(f"spans_looked_at entry {span!r} needs start, end and role")
                continue
            if not _as_date(span["start"]) or not _as_date(span["end"]):
                errors.append(f"span {span!r}: start and end must be ISO dates")
            elif date.fromisoformat(str(span["start"])) > date.fromisoformat(str(span["end"])):
                errors.append(f"span {span!r}: start is after end")
            if span.get("role") not in _SPAN_ROLES:
                errors.append(f"span role {span.get('role')!r} not in {sorted(_SPAN_ROLES)}")

    looks = front["forward_span_looks"]
    if isinstance(looks, bool) or not isinstance(looks, int) or looks < 0:
        errors.append("forward_span_looks must be an int >= 0")

    tables = front["tables"]
    if not isinstance(tables, list) or not tables:
        errors.append("tables must be a non-empty list of snake_case table names")
    else:
        for table in tables:
            if not isinstance(table, str) or not _TABLE_RE.match(table):
                errors.append(f"table name {table!r} is not snake_case")

    if front["status_now"] not in _STATUS_VALUES:
        errors.append(f"status_now {front['status_now']!r} not in {sorted(_STATUS_VALUES)}")

    reopened_as = front["reopened_as"]
    if reopened_as is not None and not isinstance(reopened_as, str):
        errors.append("reopened_as must be a string or null")

    reproducible = front["reproducible"]
    if reproducible is not False:
        errors.append(
            f"reproducible must be boolean false, got {reproducible!r} "
            "(the strict loader parses YAML 1.1 forms like 'no' as the string 'no')"
        )

    sources = front["sources"]
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty list of source references")
    else:
        errors.extend(_lint_source_refs(sources, gate_ids=gate_ids, gate_run_ts=gate_run_ts))

    related = front["related_cards"]
    if not isinstance(related, list) or not all(isinstance(c, str) for c in related):
        errors.append("related_cards must be a list of card ids")

    return errors


def _lint_source_refs(refs: list, *, gate_ids: set[str], gate_run_ts: set[str]) -> list[str]:
    errors: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref:
            errors.append(f"source reference {ref!r} must be a non-empty string")
            continue
        if ":" in ref:
            prefix, rest = ref.split(":", 1)
            if prefix not in _KNOWN_REF_PREFIXES:
                errors.append(f"source reference {ref!r} has an unknown prefix {prefix!r}")
                continue
            if prefix == "db":
                if not _TABLE_RE.match(rest):
                    errors.append(f"db source {ref!r} needs a snake_case table name")
            elif ref.removeprefix("gate_look_log:") not in gate_ids | gate_run_ts:
                errors.append(
                    f"source reference {ref!r} matches no gate_id or run_ts in "
                    ".planning/gate_look_log.jsonl"
                )
        elif ref.startswith("/"):
            errors.append(f"source reference {ref!r} must be repo-relative")
        elif ref.startswith("logs/"):
            errors.append(
                f"source reference {ref!r} is untracked (logs/ is gitignored); copy the number "
                "into results and name the log path in prose only"
            )
    return errors


def _uncovered_tables(cards: list[dict]) -> set[str]:
    return DROP_TABLES - {t for card in cards for t in card["tables"]}


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=check, capture_output=True, text=True
    )


def _git_checks_available() -> str | None:
    """A skip reason when the git-history checks cannot run, else None."""
    try:
        _git(_REPO_ROOT, "rev-parse", "--is-inside-work-tree")
    except subprocess.CalledProcessError:
        return "not a git repository; git-history checks skipped"
    shallow = _git(_REPO_ROOT, "rev-parse", "--is-shallow-repository").stdout.strip()
    if shallow == "true":
        return "shallow clone (no fetch-depth); git-history checks skipped"
    return None


_SKIP_REASON = _git_checks_available()


def _repo_refs(front: dict) -> set[str]:
    """Every path-shaped source reference (with #anchor stripped) plus recipe spec/script."""
    refs: set[str] = set()
    for ref in list(front["sources"]) + [r["source"] for r in front["results"]]:
        if not isinstance(ref, str) or ":" in ref.split("#")[0]:
            continue
        refs.add(ref.split("#", 1)[0])
    recipe = front["recipe"]
    for key in ("spec", "script"):
        value = recipe[key]
        if isinstance(value, str):
            refs.add(value)
    return refs


@functools.lru_cache(maxsize=1)
def _gate_look_refs() -> tuple[set[str], set[str]]:
    gate_ids: set[str] = set()
    gate_run_ts: set[str] = set()
    for line in _GATE_LOOK_LOG.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        gate_run_ts.add(row["run_ts"])
        if "gate_id" in row:
            gate_ids.add(row["gate_id"])
    return gate_ids, gate_run_ts


@functools.lru_cache(maxsize=1)
def _real_cards() -> list[tuple[Path, dict]]:
    cards = []
    for path in sorted(_CARD_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        cards.append((path, _parse_card(path)))
    return cards


# ---------------------------------------------------------------- fixture-level tests


def _valid_front() -> dict:
    return {
        "card_id": "legacy-test-process",
        "kind": "legacy_verdict",
        "title": "A synthetic process",
        "idea": "One sentence.",
        "verdict": "FAIL",
        "verdict_date": "2026-07-23",
        "recipe": {
            "spec": None,
            "script": "scripts/analysis/some_eval.py",
            "recipe_commit": "a" * 40,
        },
        "results": [
            {"name": "shuffled_null_p", "value": 0.001, "source": "docs/plans/some-report.md"}
        ],
        "known_defects": ["known defect one"],
        "spans_looked_at": [{"start": "2025-01-01", "end": "2025-12-24", "role": "in_sample"}],
        "forward_span_looks": 2,
        "tables": ["ensemble_alpha"],
        "status_now": "closed",
        "reopened_as": None,
        "reproducible": False,
        "sources": ["docs/plans/some-report.md", "gate_look_log:gate1_signal"],
        "related_cards": [],
    }


def test_synthetic_valid_card_lints_clean(tmp_path):
    errors = _lint_card(_valid_front(), gate_ids={"gate1_signal"}, gate_run_ts=set())
    assert errors == []
    # And a card file built in tmp_path parses and lints clean end to end.
    text = "---\n" + yaml.safe_dump(_valid_front(), sort_keys=False) + "\n---\n\n# Title\n"
    card = tmp_path / "legacy-test-process.md"
    card.write_text(text)
    gate_ids, gate_run_ts = _gate_look_refs()
    assert _lint_card(_parse_card(card), gate_ids=gate_ids, gate_run_ts=gate_run_ts) == []


@pytest.mark.parametrize(
    "key",
    [
        "card_id",
        "kind",
        "title",
        "idea",
        "verdict",
        "verdict_date",
        "recipe",
        "results",
        "known_defects",
        "spans_looked_at",
        "forward_span_looks",
        "tables",
        "status_now",
        "reopened_as",
        "reproducible",
        "sources",
        "related_cards",
    ],
)
def test_missing_required_key_is_named_in_error(key):
    front = _valid_front()
    del front[key]
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any(key in error for error in errors), f"error must name the missing key {key}"


def test_reproducible_no_string_fails(tmp_path):
    text = (
        "---\ncard_id: cache-x\nkind: dead_cache\ntitle: t\nidea: i\n"
        "verdict: NO_CONCLUSION\nverdict_date: 2026-01-01\n"
        "recipe: {spec: null, script: null, recipe_commit: " + "b" * 40 + "}\n"
        "results: []\nknown_defects: []\nspans_looked_at: []\nforward_span_looks: 0\n"
        "tables: [forward_returns]\nstatus_now: closed\nreopened_as: null\n"
        "reproducible: no\nsources: [docs/plans/x.md]\nrelated_cards: []\n---\n\n# t\n"
    )
    card = tmp_path / "cache-x.md"
    card.write_text(text)
    front = _parse_card(card)
    # The strict loader must NOT coerce the YAML 1.1 'no' to boolean False.
    assert front["reproducible"] == "no"
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("reproducible" in error for error in errors)


def test_reproducible_true_fails():
    front = _valid_front()
    front["reproducible"] = True
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("reproducible" in error for error in errors)


def test_unknown_kind_fails():
    front = _valid_front()
    front["kind"] = "verdict"
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("kind" in error for error in errors)


def test_unknown_verdict_fails():
    front = _valid_front()
    front["verdict"] = "MAYBE"
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("verdict" in error for error in errors)


def test_dead_cache_with_non_no_conclusion_verdict_fails():
    front = _valid_front()
    front["kind"] = "dead_cache"
    front["verdict"] = "FAIL"
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("NO_CONCLUSION" in error for error in errors)


def test_dead_cache_may_have_empty_results_but_legacy_verdict_may_not():
    front = _valid_front()
    front["kind"] = "dead_cache"
    front["verdict"] = "NO_CONCLUSION"
    front["results"] = []
    assert _lint_card(front, gate_ids={"gate1_signal"}, gate_run_ts=set()) == []

    front = _valid_front()
    front["results"] = []
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("results" in error for error in errors)


def test_malformed_recipe_commit_fails():
    front = _valid_front()
    front["recipe"]["recipe_commit"] = "deadbeef"
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("recipe_commit" in error for error in errors)


def test_unknown_source_prefix_fails():
    front = _valid_front()
    front["sources"] = ["s3://bucket/thing"]
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("unknown prefix" in error for error in errors)


def test_gate_look_log_ref_not_in_log_fails():
    front = _valid_front()
    front["sources"] = ["gate_look_log:no_such_gate"]
    errors = _lint_card(front, gate_ids={"gate1_signal"}, gate_run_ts=set())
    assert any("no gate_id or run_ts" in error for error in errors)


def test_untracked_logs_source_ref_fails():
    front = _valid_front()
    front["sources"] = ["logs/corpus_pipeline/step_timings.jsonl"]
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("untracked" in error for error in errors)


def test_bad_span_role_fails():
    front = _valid_front()
    front["spans_looked_at"] = [{"start": "2025-01-01", "end": "2025-12-24", "role": "oos"}]
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("role" in error for error in errors)


def test_span_start_after_end_fails():
    front = _valid_front()
    front["spans_looked_at"] = [{"start": "2025-12-25", "end": "2025-12-24", "role": "in_sample"}]
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("start is after end" in error for error in errors)


def test_negative_forward_span_looks_fails():
    front = _valid_front()
    front["forward_span_looks"] = -1
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("forward_span_looks" in error for error in errors)


def test_non_snake_case_table_name_fails():
    front = _valid_front()
    front["tables"] = ["EnsembleAlpha"]
    errors = _lint_card(front, gate_ids=set(), gate_run_ts=set())
    assert any("snake_case" in error for error in errors)


def test_uncovered_tables_is_drop_tables_minus_union_of_card_tables():
    cards = [_valid_front(), _valid_front()]
    cards[1]["card_id"] = "cache-test-cache"
    cards[1]["kind"] = "dead_cache"
    cards[1]["verdict"] = "NO_CONCLUSION"
    cards[1]["results"] = []
    cards[1]["tables"] = ["ensemble_weights", "ctx_events"]
    assert _uncovered_tables(cards) == DROP_TABLES - {
        "ensemble_alpha",
        "ensemble_weights",
        "ctx_events",
    }


# ---------------------------------------------------------------- real-card tests


def test_card_dir_contains_cards():
    assert _CARD_DIR.is_dir(), f"missing card directory {_CARD_DIR}"
    assert _real_cards(), "no summary cards found; write the cards before dropping tables"


def test_filenames_match_card_ids():
    mismatches = [
        f"{path.name} vs card_id {front['card_id']}"
        for path, front in _real_cards()
        if path.stem != front["card_id"]
    ]
    assert not mismatches, f"filenames must equal card_id + .md: {mismatches}"


def test_card_ids_unique():
    ids = [front["card_id"] for _, front in _real_cards()]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"duplicate card_ids: {duplicates}"


def test_every_real_card_lints_clean():
    gate_ids, gate_run_ts = _gate_look_refs()
    failures = {
        path.name: errors
        for path, front in _real_cards()
        if (errors := _lint_card(front, gate_ids=gate_ids, gate_run_ts=gate_run_ts))
    }
    assert not failures, f"cards failing the lint: {failures}"


def test_drop_tables_fully_covered():
    uncovered = _uncovered_tables([front for _, front in _real_cards()])
    assert not uncovered, (
        f"table(s) {sorted(uncovered)} are phase 186 drop targets with no summary card citing "
        "them; write a summary card citing this table before any drop (D-06)"
    )


def test_related_cards_resolve():
    known = {front["card_id"] for _, front in _real_cards()}
    dangling = [
        (front["card_id"], ref)
        for _, front in _real_cards()
        for ref in front["related_cards"]
        if ref not in known
    ]
    assert not dangling, f"related_cards pointing at nonexistent card ids: {dangling}"


@pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")
def test_recipe_commits_exist_in_git():
    missing = [
        front["card_id"]
        for _, front in _real_cards()
        if _git(
            _REPO_ROOT, "cat-file", "-e", front["recipe"]["recipe_commit"], check=False
        ).returncode
        != 0
    ]
    assert not missing, f"recipe_commit(s) not found in git history: {missing}"


@pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")
def test_repo_source_paths_exist_at_recipe_commit_or_head():
    dangling: list[str] = []
    for _, front in _real_cards():
        commit = front["recipe"]["recipe_commit"]
        for ref in _repo_refs(front):
            at_commit = _git(_REPO_ROOT, "cat-file", "-e", f"{commit}:{ref}", check=False)
            at_head = _git(_REPO_ROOT, "cat-file", "-e", f"HEAD:{ref}", check=False)
            if at_commit.returncode != 0 and at_head.returncode != 0:
                dangling.append(f"{front['card_id']}: {ref}")
    assert not dangling, (
        f"source path(s) not found at recipe_commit or HEAD: {dangling}; paths must survive "
        "repo deletions via their recipe_commit"
    )
