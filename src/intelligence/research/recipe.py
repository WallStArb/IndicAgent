"""Recipe content and hash (design 10.2.2, plan 187-11): what a concept IS, as a pure function of
its spec, so the S6 ledger can write a recipe version the first time a run touches it.

A recipe names the code that computes the concept (`module:name`), its pinned parameters, the
APR values the run read, its inputs (the panel, and for a book the recipes of everything it
combines), the universe selector, the controlled-vocabulary codes it uses, and its mechanism and
sources. `recipe_hash` is the sha256 of the canonical JSON of all of it plus the concept's own
name (two concepts with identical content are still two ideas), except the commit and author,
which are provenance: a re-run of the same definition at a new commit reuses the version.

Optional spec fields that are unset are left out of every dump, so adding one later never moves
an existing recipe's hash. Pure functions, no I/O.
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Any

from src.core.canonical_json import canonical_json
from src.intelligence.research.spec import BookSpec, FamilySpec, LoadedSpec, PodBookSpec

# Namespaces seeded by migration 530; the ledger validates cvr_codes against them.
NS_CONSTRUCTION_RULE = "research_construction_rule"
NS_COMBINER = "research_combiner"
NS_TIMEFRAME = "research_timeframe"

_BOOK_POINTER = "src.intelligence.research.runner:run_book"
_POD_POINTER = "src.intelligence.research.pod:run_pod"
_RULE_POINTER = "src.intelligence.research.construction:resolve_rule"
_COMBINER_POINTERS = {
    "ridge": "src.intelligence.research.combiner:RidgeSpec",
    "equal_weight": "src.intelligence.research.combiner:EqualWeight",
}


@dataclasses.dataclass(frozen=True)
class RecipeContent:
    concept: str
    code_pointer: str
    params: dict[str, Any]
    apr_values: dict[str, Any]
    inputs: tuple[Any, ...]
    universe_selector: dict[str, Any] | None
    cvr_codes: dict[str, str]
    mechanism: str | None
    sources: tuple[str, ...]

    def hashed(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "code_pointer": self.code_pointer,
            "params": self.params,
            "apr_values": self.apr_values,
            "inputs": list(self.inputs),
            "universe_selector": self.universe_selector,
            "cvr_codes": self.cvr_codes,
            "mechanism": self.mechanism,
            "sources": list(self.sources),
        }

    @property
    def recipe_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.hashed()).encode()).hexdigest()


def pointer(dotted: str) -> str:
    """'a.b.c' -> 'a.b:c' (the last segment is the callable)."""
    module, _, name = dotted.rpartition(".")
    if not module:
        raise ValueError(f"not a dotted path: {dotted!r}")
    return f"{module}:{name}"


def _clean(value: Any) -> Any:
    """A dump with unset (None) fields removed at every depth."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _dump(model: Any) -> dict[str, Any]:
    return _clean(model.model_dump(mode="json"))


def _universe(spec: FamilySpec) -> dict[str, Any]:
    return _clean(
        {"universe": spec.panel.universe, "members_universe": spec.panel.members_universe}
    )


def _recipe(
    concept: str,
    code_pointer: str,
    params: dict[str, Any],
    cvr_codes: dict[str, str],
    prior_source: str,
    *,
    apr_values: dict[str, Any] | None = None,
    inputs: tuple[Any, ...] = (),
    universe_selector: dict[str, Any] | None = None,
) -> RecipeContent:
    """A recipe whose mechanism and only source are the spec's prior source."""
    return RecipeContent(
        concept=concept,
        code_pointer=code_pointer,
        params=params,
        apr_values=apr_values or {},
        inputs=inputs,
        universe_selector=universe_selector,
        cvr_codes=cvr_codes,
        mechanism=prior_source,
        sources=(prior_source,),
    )


def family_recipes(loaded: LoadedSpec) -> dict[str, RecipeContent]:
    """The family's recipe and one per member, keyed by concept name."""
    spec = loaded.model
    if not isinstance(spec, FamilySpec):
        raise TypeError("family_recipes needs a family spec")
    family = f"family.{spec.family}"
    module = spec.members[0].signal.rsplit(".", 1)[0]
    cvr = {NS_TIMEFRAME: spec.panel.tf}
    out = {
        family: _recipe(
            family,
            f"{module}:make_plant",
            _clean(
                {
                    "horizon": spec.horizon,
                    "factor_spec": spec.factor_spec,
                    "members": [m.name for m in spec.members],
                    "construction": _dump(spec.construction),
                    "scoring": _dump(spec.scoring),
                    "guards": _dump(spec.guards),
                    "costs": _dump(spec.costs),
                }
            ),
            cvr,
            spec.prior_source,
            inputs=({"panel": _dump(spec.panel)},),
            universe_selector=_universe(spec),
        )
    }
    for m in spec.members:
        name = f"member.{spec.family}.{m.name}"
        out[name] = _recipe(
            name,
            pointer(m.signal),
            _clean(
                {
                    "params": dict(m.params),
                    "slot_history_sessions": m.slot_history_sessions,
                    "declared_memory_rows": m.declared_memory_rows,
                }
            ),
            cvr,
            spec.prior_source,
            inputs=({"panel": _dump(spec.panel)}, {"concept": family}),
            universe_selector=_universe(spec),
        )
    return out


def combiner_kind(book: BookSpec) -> str:
    """'ridge' or 'equal_weight' (an unset kind is the ridge, as book_v1 pins it)."""
    kind = book.combiner.kind or "ridge"
    if kind not in _COMBINER_POINTERS:
        raise ValueError(f"no recipe pointer for combiner kind {kind!r}")
    return kind


def book_recipes(loaded: LoadedSpec, apr_values: dict[str, Any]) -> dict[str, RecipeContent]:
    """Every family and member recipe of the book, its combiner and construction rule, and the
    book. The book's inputs carry each member's, the combiner's and the rule's recipe hash, so a
    change anywhere under it moves the book's hash and nothing beside the changed parts."""
    book = loaded.model
    if not isinstance(book, BookSpec):
        raise TypeError("book_recipes needs a book spec")
    out: dict[str, RecipeContent] = {}
    for fam in loaded.families:
        out.update(family_recipes(fam))
    first = loaded.families[0].model
    kind = combiner_kind(book)
    combiner = f"combiner.{kind}"
    rule = f"construction_rule.{book.construction.name}"
    out[combiner] = _recipe(
        combiner,
        _COMBINER_POINTERS[kind],
        _dump(book.combiner)
        | ({"horizon_rule": _dump(book.horizon_rule)} if book.horizon_rule else {}),
        {NS_COMBINER: kind},
        book.prior_source,
    )
    out[rule] = _recipe(
        rule,
        _RULE_POINTER,
        _dump(book.construction),
        {NS_CONSTRUCTION_RULE: book.construction.name},
        book.prior_source,
    )
    parts = sorted(out)
    name = f"book.{book.book}"
    out[name] = _recipe(
        name,
        _BOOK_POINTER,
        _clean(
            {
                "families": list(book.families),
                "scoring": _dump(book.scoring),
                "guards": _dump(book.guards),
                "costs": _dump(book.costs),
                "power": _dump(book.power),
            }
        ),
        {
            NS_COMBINER: kind,
            NS_CONSTRUCTION_RULE: book.construction.name,
            NS_TIMEFRAME: first.panel.tf,
        },
        book.prior_source,
        apr_values=dict(apr_values),
        inputs=tuple({"concept": p, "recipe_hash": out[p].recipe_hash} for p in parts),
        universe_selector=_universe(first),
    )
    return out


def pod_recipes(loaded: LoadedSpec) -> dict[str, RecipeContent]:
    """The pod's recipe: its member books by spec hash and pinned attempt (their own recipes were
    written when their runs started)."""
    pod = loaded.model
    if not isinstance(pod, PodBookSpec):
        raise TypeError("pod_recipes needs a pod spec")
    name = f"pod.{pod.pod}"
    return {
        name: _recipe(
            name,
            _POD_POINTER,
            {"books": [b.book for b in pod.books]},
            {NS_COMBINER: "pod"},
            pod.prior_source,
            inputs=tuple(
                {
                    "concept": f"book.{b.model.book}",
                    "spec_hash": b.spec_hash,
                    "run_id": pin.run_id,
                    "series_sha256": pin.series_sha256,
                }
                for pin, b in zip(pod.books, loaded.books, strict=True)
            ),
        )
    }
